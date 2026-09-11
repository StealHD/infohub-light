"""Concurrent page admission and release without interrupting long-running relays."""
import asyncio
from contextlib import ExitStack

import pytest
from fastapi.testclient import TestClient
from starlette.websockets import WebSocketDisconnect

from src.services.openclaw_relay.settings import connection_limit
from tests.test_openclaw_relay import socket_app


@pytest.mark.parametrize('value', ['0', '-1', '101', 'bad', ''])
def test_invalid_capacity_rejected(monkeypatch, value):
    monkeypatch.setenv('HORIZON_OPENCLAW_MAX_CONNECTIONS_PER_USER', value)
    with pytest.raises(ValueError):
        connection_limit()


@pytest.mark.parametrize('limit', [None, '4'])
def test_concurrent_pages_release_capacity_and_have_no_one_hour_deadline(monkeypatch, limit):
    monkeypatch.setenv('HORIZON_OPENCLAW_SERVER_ENABLED', 'true')
    monkeypatch.delenv('HORIZON_OPENCLAW_MAX_CONNECTIONS_PER_USER', raising=False)
    if limit:
        monkeypatch.setenv('HORIZON_OPENCLAW_MAX_CONNECTIONS_PER_USER', limit)
    maximum = int(limit or 12)
    monkeypatch.setattr('src.api.openclaw_relay_routes.AgentConnections.live',
                        lambda self, user: {'agent_id': 'ih-test', 'binding_id': 'test'})
    original_wait = asyncio.wait_for

    async def bounded_wait(awaitable, timeout):
        assert timeout != 3600, 'Active relays must not have a one-hour lifetime'
        return await original_wait(awaitable, timeout)

    monkeypatch.setattr(asyncio, 'wait_for', bounded_wait)

    async def relay(socket, *args, **kwargs):
        await socket.send_json({'ready': True})
        await socket.receive_text()

    monkeypatch.setattr('src.api.openclaw_relay_routes.relay', relay)
    headers = {'origin': 'https://testserver', 'cookie': 'horizon_session=valid'}
    with TestClient(socket_app({'id': 'capacity', 'workspace_id': 'w', 'role': 'owner'})) as client:
        with ExitStack() as stack:
            sessions = []
            for _ in range(maximum):
                context = client.websocket_connect('/api/me/openclaw/socket', headers=headers)
                ws = stack.enter_context(context)
                assert ws.receive_json() == {'ready': True}
                sessions.append(context)
            with pytest.raises(WebSocketDisconnect):
                with client.websocket_connect('/api/me/openclaw/socket', headers=headers):
                    pass
            sessions.pop().__exit__(None, None, None)
            with client.websocket_connect('/api/me/openclaw/socket', headers=headers) as ws:
                assert ws.receive_json() == {'ready': True}
    from src.api.openclaw_relay_routes import _connections
    assert 'w:capacity' not in _connections
