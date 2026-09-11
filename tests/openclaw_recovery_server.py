"""Temporary real Service/relay + controlled Gateway browser harness, no external inference."""
import json
import socket
import sys
import tempfile
from pathlib import Path
from types import SimpleNamespace

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
import httpx
import pytest
import uvicorn
from fastapi import FastAPI, Request, WebSocket
from starlette.responses import Response
from test_information_automation_rules import context
from openclaw_recovery_gateway import RecoveryGateway
from src.api.openclaw_relay_routes import register_openclaw_relay_routes
from src.services.openclaw_relay.ownership import Ownership


def serve(root, frontend):
    patch = pytest.MonkeyPatch()
    fixture = context.__wrapped__(root, patch)
    store, _, bindings, user, *_ = next(fixture)
    binding = bindings.live(user)
    gateway = RecoveryGateway(binding['agent_id'], patched=True)
    relay_root = root / 'relay'
    relay_root.mkdir()
    owner = Ownership(relay_root, user['workspace_id'] + ':' + user['id'])
    owner.add(gateway.parent)
    owner.add(gateway.child)
    sock = socket.socket()
    sock.bind(('127.0.0.1', 0))
    sock.listen(128)
    url = 'http://127.0.0.1:' + str(sock.getsockname()[1])
    for key, value in {'HORIZON_OPENCLAW_SERVER_ENABLED': 'true',
                       'HORIZON_OPENCLAW_MANAGED_LOCAL_ENABLED': 'true',
                       'HORIZON_OPENCLAW_SERVER_URL': url.replace('http', 'ws') + '/gateway',
                       'HORIZON_OPENCLAW_SERVER_TOKEN': 'controlled',
                       'HORIZON_OPENCLAW_RELAY_STATE': str(relay_root)}.items():
        patch.setenv(key, value)
    app = FastAPI()
    app.state.api_context = SimpleNamespace(store=store, secret_values=None, openclaw_chat_settings=SimpleNamespace(enabled=True))
    register_openclaw_relay_routes(app)

    @app.websocket('/gateway')
    async def controlled(ws: WebSocket):
        await gateway.socket(ws)

    @app.get('/__fixture')
    async def info():
        return {'calls': gateway.calls, 'created': gateway.created}

    @app.get('/{path:path}')
    async def assets(path: str, request: Request):
        async with httpx.AsyncClient() as client:
            response = await client.get(frontend.rstrip('/') + '/' + path, params=request.query_params)
        return Response(response.content, status_code=response.status_code, media_type=response.headers.get('content-type'))

    print(json.dumps({'url': url, 'user': user['id'], 'agent': binding['agent_id'], 'key': gateway.child,
                      'cookie': store.create_session(user['id'])}), flush=True)
    try:
        uvicorn.Server(uvicorn.Config(app, log_level='error', access_log=False)).run(sockets=[sock])
    finally:
        fixture.close()
        patch.undo()
        sock.close()


if __name__ == '__main__':
    with tempfile.TemporaryDirectory(prefix='openclaw-recovery-') as directory:
        serve(Path(directory), sys.argv[1])
