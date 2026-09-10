"""Actual API/MCP handlers and WebSocket relay against a deterministic Gateway."""
import asyncio
import json
import threading
from types import SimpleNamespace
import httpx
import pytest
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client
from starlette.websockets import WebSocketDisconnect
from tests.remote_mcp_http_test_support import _app, _seed_feed
from tests.test_agent_connections import bind
from scripts.provision_openclaw_agent import check_mcp
from src.services.agent_connections.service import AgentConnections
from src.services.openclaw_relay.ownership import Ownership


@pytest.fixture
def anyio_backend():
    return 'asyncio'


@pytest.fixture
def site(tmp_path, monkeypatch):
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_ENABLED', 'true')
    monkeypatch.setenv('HORIZON_OPENCLAW_CHAT_ENABLED', 'true')
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_URL', 'wss://gateway.test')
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_TOKEN', 'test-upstream-token')
    relay_root = tmp_path / 'relay'
    monkeypatch.setenv('HORIZON_OPENCLAW_RELAY_STATE', str(relay_root))
    app = _app(tmp_path, monkeypatch)
    store = app.state.service_store
    alice = store.get_user_by_username('owner')
    bob = store.create_user(workspace_id=alice['workspace_id'], username='bob', password='test-password')
    connections = AgentConnections(store, app.state.api_context.secret_values)
    a, ta, _ = bind(connections, alice)
    b, tb, _ = bind(connections, bob)
    return app, store, connections, alice, bob, a, b, ta, tb, relay_root


@pytest.mark.anyio
async def test_personal_mcp_reads_use_own_data_and_reject_other_identity_and_writes(site):
    app, store, connections, alice, bob, a, b, ta, tb, _ = site
    job = _seed_feed(app, alice)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        await check_mcp(a, ta, transport=transport)
        await check_mcp(b, tb, transport=transport)
        for token, own in ((ta, True), (tb, False)):
            async with httpx.AsyncClient(transport=transport, headers={'Authorization': 'Bearer ' + token}) as client:
                async with streamable_http_client(a['mcp_url'], http_client=client, terminate_on_close=False) as (read, write, _):
                    async with ClientSession(read, write) as session:
                        await session.initialize()
                        feed = await session.call_tool('get_my_feed', {})
                        item = await session.call_tool('get_item', {'article_id': 'article-1'})
                        assert ('Remote MCP' in str(feed)) is own
                        assert ('Remote MCP' in str(item)) is own
                        if not own:
                            denied = await session.call_tool('get_job', {'job_id': job['id']})
                            assert denied.isError or 'not_found' in str(denied)
                        injected = await session.call_tool('get_my_feed', {'user_id': alice['id']})
                        assert injected.isError
                        write_result = await session.call_tool('prepare_delete_subscription', {'subscription_id': 'unowned'})
                        assert write_result.isError or 'forbidden' in str(write_result)
        connections.revoke(bob['id'])
        async with httpx.AsyncClient(transport=transport) as client:
            response = await client.post(b['mcp_url'], headers={'Authorization': 'Bearer ' + tb})
            assert response.status_code == 401


class Gateway:
    def __init__(self, agents):
        self.agents = agents
        self.requests = []
        self.sessions = {}
        self.stream = None

    async def __aenter__(self):
        self.stream = asyncio.Queue()
        await self.stream.put({'type': 'event', 'event': 'connect.challenge', 'payload': {'nonce': 'test'}})
        return self

    async def __aexit__(self, *args):
        pass

    async def send(self, raw):
        frame = json.loads(raw)
        self.requests.append(frame)
        method, params = frame['method'], frame['params']
        if method == 'connect':
            payload = {'protocol': 4, 'snapshot': {'sessionDefaults': {'defaultAgentId': 'main'}}}
        elif method == 'agents.list':
            payload = {'agents': [{'id': value} for value in self.agents]}
        elif method == 'sessions.create':
            key = 'agent:' + params['agentId'] + ':test'
            self.sessions[key] = params['agentId']
            payload = {'key': key}
        elif method == 'chat.history':
            payload = {'messages': [{'role': 'assistant', 'content': 'owned-history'}]}
        else:
            payload = {'accepted': True}
        await self.stream.put({'type': 'res', 'id': frame['id'], 'ok': True, 'payload': payload})

    async def recv(self):
        return json.dumps(await self.stream.get())

    def __aiter__(self):
        return self

    async def __anext__(self):
        return await self.recv()


def handshake(ws):
    assert ws.receive_json()['event'] == 'connect.challenge'
    ws.send_json({'type': 'req', 'id': 'connect', 'method': 'connect', 'params': {}})
    return ws.receive_json()['payload']['snapshot']['sessionDefaults']['defaultAgentId']


def rpc(ws, method, params):
    ws.send_json({'type': 'req', 'id': 'req', 'method': method, 'params': params})
    return ws.receive_json()


def test_two_login_accounts_route_to_distinct_agents_and_keep_legacy_history_readonly(site, monkeypatch):
    app, store, connections, alice, bob, a, b, _, _, root = site
    gateway = Gateway(['main', a['agent_id'], b['agent_id']])
    monkeypatch.setattr('src.services.openclaw_relay.bridge.connect', lambda *a, **kw: gateway)
    with TestClient(app, base_url='http://127.0.0.1:8080') as client:
        for user, own, other in ((alice, a, b), (bob, b, a)):
            token = store.create_session(user['id'])
            root.mkdir(exist_ok=True)
            Ownership(root, user['workspace_id'] + ':' + user['id']).add('agent:main:' + user['id'])
            headers = {'host': '127.0.0.1:8080', 'origin': 'http://127.0.0.1:8080', 'cookie': 'horizon_session=' + token}
            status = client.get('/api/me/agent-connection', headers=headers).json()['data']
            assert status['agent_id'] == own['agent_id'] and status['can_chat']
            assert client.post('/api/me/agent-connection', headers=headers, json={'agent_id': other['agent_id']}).status_code == 404
            with client.websocket_connect('/api/me/openclaw/socket', headers=headers) as ws:
                assert handshake(ws) == own['agent_id']
                denied = rpc(ws, 'sessions.create', {'agentId': other['agent_id']})
                assert not denied['ok']
                key = rpc(ws, 'sessions.create', {})['payload']['key']
                assert key.startswith('agent:' + own['agent_id'] + ':')
                assert not rpc(ws, 'chat.history', {'sessionKey': 'agent:' + other['agent_id'] + ':test'})['ok']
                assert not rpc(ws, 'tools.effective', {'sessionKey': key, 'agentId': other['agent_id']})['ok']
                legacy = 'agent:main:' + user['id']
                assert rpc(ws, 'chat.history', {'sessionKey': legacy, 'agentId': 'main'})['ok']
                assert not rpc(ws, 'chat.send', {'sessionKey': legacy, 'message': 'no'})['ok']
                assert not rpc(ws, 'sessions.create', {'parentSessionKey': legacy, 'fork': True})['ok']
                assert rpc(ws, 'chat.send', {'sessionKey': key, 'message': 'controlled-input'})['ok']
                connections.revoke(user['id'])
                ws.send_json({'type': 'req', 'id': 'late', 'method': 'chat.history', 'params': {'sessionKey': key}})
                with pytest.raises(WebSocketDisconnect):
                    ws.receive_json()
    sends = [r for r in gateway.requests if r['method'] == 'chat.send']
    assert len(sends) == 2 and all(r['params']['deliver'] is False for r in sends)


def test_missing_binding_agent_and_viewer_permissions_fail_closed(site, monkeypatch):
    app, store, connections, alice, bob, a, _, _, _, root = site
    gateway = Gateway(['main'])
    monkeypatch.setattr('src.services.openclaw_relay.bridge.connect', lambda *a, **kw: gateway)
    headers = {'host': '127.0.0.1:8080', 'origin': 'http://127.0.0.1:8080', 'cookie': 'horizon_session=' + store.create_session(alice['id'])}
    with TestClient(app, base_url='http://127.0.0.1:8080') as client:
        with client.websocket_connect('/api/me/openclaw/socket', headers=headers) as ws:
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        assert all(r['method'] != 'sessions.create' for r in gateway.requests)
        gateway.agents.append(a['agent_id'])
        store.update_user(alice['id'], role='viewer')
        with client.websocket_connect('/api/me/openclaw/socket', headers=headers) as ws:
            assert handshake(ws) == a['agent_id']
            assert not rpc(ws, 'sessions.create', {})['ok']
            ws.close()
            with pytest.raises(WebSocketDisconnect):
                ws.receive_json()
        connections.retire(alice['id'])
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/me/openclaw/socket', headers=headers):
                pass


@pytest.mark.anyio
async def test_revocation_discards_late_upstream_frames(tmp_path):
    from src.services.openclaw_relay.bridge import gateway_events, RelayFailure
    from unittest.mock import AsyncMock
    async def upstream():
        yield json.dumps({'type': 'res', 'id': 'pending', 'ok': True, 'payload': {'secret': 'late'}})
    browser = AsyncMock()
    with pytest.raises(RelayFailure):
        await gateway_events(browser, upstream(), Ownership(tmp_path, 'alice'), 'personal',
                             {'pending': 'chat.history'}, lambda: False)
    browser.send_json.assert_not_called()


def test_connection_revoke_endpoint_is_owned_and_switches_affect_status(site, monkeypatch):
    app, store, connections, alice, bob, a, b, _, _, _ = site
    cookie = {'cookie': 'horizon_session=' + store.create_session(alice['id'])}
    started = []
    original_start = threading.Thread.start
    def track_start(thread):
        if thread.name == 'agent-cleanup':
            started.append(thread)
        original_start(thread)
    monkeypatch.setattr(threading.Thread, 'start', track_start)
    with TestClient(app) as client:
        monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_ENABLED', 'false')
        status = client.get('/api/me/agent-connection', headers=cookie).json()['data']
        assert status['state'] == 'ready' and not status['can_connect'] and not status['can_chat']
        response = client.delete('/api/me/agent-connection?user_id=' + bob['id'], headers=cookie)
        assert response.status_code == 200 and response.headers['cache-control'] == 'no-store'
        assert response.json()['data']['state'] == 'revoked'
        assert connections.live(alice) is None and connections.live(bob)
        for thread in started:
            thread.join(timeout=5)
            assert not thread.is_alive(), 'Cleanup must exit before the test store closes'
        assert len(started) == 1
