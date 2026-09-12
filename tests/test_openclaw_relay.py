"""Security boundaries for server-managed OpenClaw transport."""
import json
from types import SimpleNamespace
from unittest.mock import AsyncMock
import pytest
from fastapi import FastAPI
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect
from src.api.openclaw_relay_routes import register_openclaw_relay_routes, valid_origin
from src.services.openclaw_relay.ownership import Ownership
from src.services.openclaw_relay.policy import request_params, response_payload, visible_event
from src.services.openclaw_relay.identity import connect_params, load_key
from src.services.openclaw_relay.settings import settings


def test_owner_isolation_and_rpc_allowlist(tmp_path):
    alice, bob = Ownership(tmp_path, 'a'), Ownership(tmp_path, 'b')
    alice.add('agent:main:a')
    bob.add('agent:main:b')
    for method, params in [('chat.history', {'sessionKey': 'agent:main:b'}), ('sessions.describe', {'key': 'agent:main:b'}),
                           ('sessions.create', {'parentSessionKey': 'agent:main:b'}), ('sessions.list', {'search': ''}),
                           ('sessions.preview', {'keys': ['agent:main:a', 'agent:main:b']}), ('config.get', {}), ('device.pair.approve', {}), ('sessions.patch', {'key': 'agent:main:a', 'model': 'x'})]:
        with pytest.raises(PermissionError):
            request_params(method, params, alice, 'main')
    safe = request_params('chat.send', {'sessionKey': 'agent:main:a', 'message': 'hello', 'deliver': True}, alice, 'main')
    assert safe['deliver'] is False
    with pytest.raises(PermissionError):
        request_params('chat.send', {**safe, 'to': 'external-recipient'}, alice, 'main')
    with pytest.raises(PermissionError):
        request_params('sessions.create', {'agentId': 'other'}, alice, 'main')


def test_response_and_event_ownership(tmp_path):
    owner = Ownership(tmp_path, 'a')
    response_payload('sessions.create', {'key': 'agent:main:a'}, owner, 'main')
    result = response_payload('sessions.list', {'sessions': [{'key': 'agent:main:a'}, {'key': 'agent:main:b'}]}, owner, 'main')
    assert result['sessions'] == [{'key': 'agent:main:a'}]
    assert visible_event({'event': 'chat', 'payload': {'sessionKey': 'agent:main:a'}}, owner)
    assert not visible_event({'event': 'chat', 'payload': {'sessionKey': 'agent:main:b'}}, owner)
    assert not visible_event({'event': 'exec.approval.requested', 'payload': {'sessionKey': 'agent:main:a'}}, owner)
    assert not visible_event({'event': 'agent', 'payload': {}}, owner)


def test_server_identity_is_stable_and_scoped(tmp_path):
    a = connect_params(tmp_path, 'private-test-token', 'nonce1')
    b = connect_params(tmp_path, 'private-test-token', 'nonce2')
    assert a['device']['id'] == b['device']['id']
    assert a['device']['signature'] != b['device']['signature']
    assert a['scopes'] == ['operator.read', 'operator.write']
    assert (tmp_path / 'device.key').stat().st_mode & 0o777 == 0o600


@pytest.mark.parametrize('origin,host', [('https://evil.test', 'info.test'), ('null', 'info.test'), ('http://info.test', 'info.test'), ('https://u@info.test', 'info.test')])
def test_origin_rejected(origin, host):
    assert not valid_origin(origin, host)


def socket_app(user):
    app = FastAPI()
    store = SimpleNamespace(get_session_user=lambda cookie: user if cookie == 'valid' else None)
    app.state.api_context = SimpleNamespace(store=store, secret_values=None, openclaw_chat_settings=SimpleNamespace(enabled=True))
    register_openclaw_relay_routes(app)
    return app


@pytest.mark.parametrize('role,cookie,origin', [('owner', '', 'https://testserver'), ('owner', 'valid', 'https://evil.test')])
def test_socket_requires_login_origin_and_admin(monkeypatch, role, cookie, origin):
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_ENABLED', 'true')
    app = socket_app({'id': 'a', 'workspace_id': 'w', 'role': role})
    with TestClient(app) as client:
        with pytest.raises(WebSocketDisconnect):
            with client.websocket_connect('/api/me/openclaw/socket', headers={'origin': origin, 'cookie': 'horizon_session=' + cookie}):
                pass


def test_socket_uses_server_identity_not_browser_token(monkeypatch):
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_ENABLED', 'true')
    observed = []
    monkeypatch.setattr('src.api.openclaw_relay_routes.AgentConnections.live',
                        lambda self, user: {'agent_id': 'ih-test', 'binding_id': 'test'})
    async def stub(socket, owner, valid, agent, *, readonly=False, allowed_skill_keys, chat_ready, delete_session):
        observed.append((owner, bool(valid()), callable(allowed_skill_keys), callable(chat_ready)))
        await socket.send_json({'ready': True})
        await socket.close()
    monkeypatch.setattr('src.api.openclaw_relay_routes.relay', stub)
    with TestClient(socket_app({'id': 'a', 'workspace_id': 'w', 'role': 'owner'})) as client:
        with client.websocket_connect('/api/me/openclaw/socket', headers={'origin': 'https://testserver', 'cookie': 'horizon_session=valid'}) as ws:
            assert ws.receive_json() == {'ready': True}
    assert observed == [('w:a', True, True, True)]


def test_private_configuration_not_public(monkeypatch):
    from src.mcp.remote_config import OpenClawChatSettings
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_ENABLED', 'true')
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_TOKEN', 'private-test-token')
    config = OpenClawChatSettings.from_env().public_config()
    assert config['default_gateway_url'] == '/api/me/openclaw/socket'
    assert 'private-test-token' not in json.dumps(config)


def test_preview_and_current_send_params(tmp_path):
    owner = Ownership(tmp_path, 'a')
    owner.add('agent:main:a')
    assert request_params('sessions.preview', {'keys': ['agent:main:a']}, owner, 'main') == {'keys': ['agent:main:a']}
    params = request_params('chat.send', {'sessionKey': 'agent:main:a', 'agentId': 'main', 'message': 'hello', 'fastMode': True}, owner, 'main')
    assert params['agentId'] == 'main' and params['deliver'] is False


@pytest.mark.anyio
async def test_pending_skill_policy_blocks_new_send_but_keeps_abort_available(tmp_path):
    from src.services.openclaw_relay.bridge import RelayFailure, browser_requests

    owner = Ownership(tmp_path, 'alice')
    owner.add('agent:main:owned')
    browser = AsyncMock()
    browser.receive_text.side_effect = [
        json.dumps({'type': 'req', 'id': 'send', 'method': 'chat.send',
                    'params': {'sessionKey': 'agent:main:owned', 'message': 'new work'}}),
        RelayFailure('stop'),
    ]
    upstream = AsyncMock()
    with pytest.raises(RelayFailure):
        await browser_requests(browser, upstream, owner, 'main', {}, lambda: True,
                               chat_ready=lambda: False)
    upstream.send.assert_not_called()
    assert browser.send_json.call_args.args[0]['ok'] is False

    browser.reset_mock()
    browser.receive_text.side_effect = [
        json.dumps({'type': 'req', 'id': 'abort', 'method': 'chat.abort',
                    'params': {'sessionKey': 'agent:main:owned', 'runId': 'run-1'}}),
        RelayFailure('stop'),
    ]
    with pytest.raises(RelayFailure):
        await browser_requests(browser, upstream, owner, 'main', {}, lambda: True,
                               chat_ready=lambda: False)
    upstream.send.assert_called_once()


def test_browser_history_load_preserves_bounds_and_owner_isolation(tmp_path):
    owner = Ownership(tmp_path, 'alice')
    owner.add('agent:main:alice')
    params = {'sessionKey': 'agent:main:alice', 'agentId': 'main',
              'limit': 100, 'maxChars': 100_000}
    assert request_params('chat.history', params, owner, 'main') == params
    for rejected in [{**params, 'sessionKey': 'agent:main:bob'},
                     {**params, 'includeAllSessions': True}]:
        with pytest.raises(PermissionError):
            request_params('chat.history', rejected, owner, 'main')
