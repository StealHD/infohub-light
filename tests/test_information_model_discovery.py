"""Configured model discovery is metadata-only and fails closed on unsupported RPCs."""
import asyncio
import json
import pytest
from src.services.information_automations import model_discovery as discovery


class Socket:
    def __init__(self, frames):
        self.frames = iter(frames)
        self.sent = []

    async def __aenter__(self):
        return self

    async def __aexit__(self, *_):
        return False

    async def recv(self):
        return json.dumps(next(self.frames))

    async def send(self, value):
        self.sent.append(json.loads(value))


@pytest.mark.parametrize('supported', [True, False])
def test_metadata_rpc_is_scoped_to_completion_agent(tmp_path, monkeypatch, supported):
    socket = Socket([
        {'event': 'connect.challenge', 'payload': {'nonce': 'n'}},
        {'id': 'connect', 'ok': True, 'payload': {'features': {'methods': ['models.list'] if supported else []}}},
        {'id': 'models', 'ok': True, 'payload': {'models': []}},
    ])
    monkeypatch.setattr(discovery, 'connect', lambda *args, **kwargs: socket)
    monkeypatch.setattr(discovery, 'connect_params', lambda *args, **kwargs: {})
    operation = discovery.rpc_models('http://127.0.0.1:18789', 'fixture-token', 'ic-fixture', tmp_path / 'device')
    if supported:
        assert asyncio.run(operation) == {'models': []}
        assert socket.sent[-1]['params'] == {'view': 'configured', 'agentId': 'ic-fixture'}
        assert [value['method'] for value in socket.sent] == ['connect', 'models.list']
    else:
        with pytest.raises(ValueError, match='unsupported'):
            asyncio.run(operation)
        assert [value['method'] for value in socket.sent] == ['connect']
