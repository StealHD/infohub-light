"""Same-origin, session-authenticated server OpenClaw transport."""
import logging
import time
import uuid
from functools import partial
from collections import Counter
from urllib.parse import urlsplit
from fastapi import FastAPI, WebSocket
from starlette.websockets import WebSocketDisconnect
from ..auth import COOKIE_NAME
from ..services.openclaw_relay.session_delete import delete_owned_session
from ..services.agent_connections.service import AgentConnections
from ..services.agent_skill_access import AgentSkillAccess, AgentSkillPolicyError
from ..services.openclaw_relay.bridge import RelayFailure, relay
from ..services.openclaw_relay.settings import RELAY_PATH, enabled, connection_limit

_connections = Counter()
_logger = logging.getLogger(__name__)


def _close_diagnostics(exc: Exception) -> tuple[str, bool, int | None, int | None, int | None]:
    failure = exc if isinstance(exc, RelayFailure) else None
    cause = failure.cause if failure and failure.cause is not None else exc
    browser_code = cause.code if isinstance(cause, WebSocketDisconnect) else None
    received = getattr(cause, 'rcvd', None)
    upstream_code = getattr(received, 'code', None)
    response = getattr(cause, 'response', None)
    upstream_status = getattr(response, 'status_code', None)
    return (
        failure.stage if failure else 'relay',
        bool(failure and failure.terminal),
        browser_code if isinstance(browser_code, int) else None,
        upstream_code if isinstance(upstream_code, int) else None,
        upstream_status if isinstance(upstream_status, int) else None,
    )


def valid_origin(origin: str, host: str) -> bool:
    parsed = urlsplit(origin)
    return (parsed.scheme == 'https' or parsed.scheme == 'http' and parsed.hostname in {'localhost', '127.0.0.1'}) and parsed.netloc == host and not parsed.username and not parsed.password and parsed.path in {'', '/'} and not parsed.query and not parsed.fragment


async def openclaw_socket(socket: WebSocket):
    context = socket.app.state.api_context
    cookie = socket.cookies.get(COOKIE_NAME)
    user = context.store.get_session_user(cookie)
    if not enabled() or not context.openclaw_chat_settings.enabled or not user or not valid_origin(socket.headers.get('origin', ''), socket.headers.get('host', '')):
        await socket.close(code=1008)
        return
    connections = AgentConnections(context.store, context.secret_values)
    binding = connections.live(user)
    if not binding or user.get('role') not in {'owner', 'admin', 'member', 'viewer'}:
        await socket.close(code=1008)
        return
    owner = str(user['workspace_id']) + ':' + str(user['id'])
    skill_access = AgentSkillAccess(context.store)
    def allowed_skill_keys():
        try:
            return set(skill_access.policy(str(user['workspace_id']))['allowed_skill_keys'])
        except AgentSkillPolicyError:
            return set()
    def skill_policy_ready():
        return skill_access.chat_ready(str(user['workspace_id']), str(binding['binding_id']))
    if _connections[owner] >= connection_limit():
        await socket.close(code=1013)
        return
    def valid_session():
        current = context.store.get_session_user(cookie)
        live = connections.live(current) if current else None
        return bool(current and current['id'] == user['id'] and current['workspace_id'] == user['workspace_id']
                    and current.get('role') == user.get('role') and live
                    and live['binding_id'] == binding['binding_id'])
    _connections[owner] += 1
    request_id = f'req_{uuid.uuid4().hex}'
    started = time.monotonic()
    try:
        await socket.accept(headers=[(b'x-request-id', request_id.encode('ascii'))])
        await relay(
            socket, owner, valid_session, binding['agent_id'], readonly=user['role'] == 'viewer',
            allowed_skill_keys=allowed_skill_keys, chat_ready=skill_policy_ready, delete_session=partial(delete_owned_session, context),
        )
    except Exception as exc:
        stage, terminal, browser_code, upstream_code, upstream_status = _close_diagnostics(exc)
        duration_ms = max(0, round((time.monotonic() - started) * 1000))
        normal_browser_close = browser_code in {1000, 1001}
        log = _logger.info if normal_browser_close else _logger.warning
        log(
            'OpenClaw relay closed duration_ms=%d browser_close_code=%s '
            'upstream_close_code=%s upstream_status=%s terminal=%s',
            duration_ms, browser_code, upstream_code, upstream_status, terminal,
            extra={
                'request_id': request_id,
                'stage': stage,
                'error_code': 'relay_closed' if normal_browser_close else 'relay_interrupted',
            },
        )
        if normal_browser_close:
            return
        try:
            await socket.close(
                code=1008 if terminal else 1011,
                reason=(
                    'InfoHub login or Agent binding is no longer available'
                    if terminal else 'InfoHub OpenClaw relay temporarily unavailable'
                ),
            )
        except Exception:
            pass
    finally:
        _connections[owner] -= 1
        if not _connections[owner]:
            del _connections[owner]


def register_openclaw_relay_routes(app: FastAPI):
    app.add_api_websocket_route(RELAY_PATH, openclaw_socket)
