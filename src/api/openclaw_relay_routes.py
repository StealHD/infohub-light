"""Same-origin, session-authenticated server OpenClaw transport."""
import asyncio
import logging
from collections import Counter
from urllib.parse import urlsplit
from fastapi import FastAPI, WebSocket
from ..auth import COOKIE_NAME
from ..services.agent_connections.service import AgentConnections
from ..services.agent_skill_access import AgentSkillAccess, AgentSkillPolicyError
from ..services.openclaw_relay.bridge import RelayFailure, relay
from ..services.openclaw_relay.settings import RELAY_PATH, enabled

_connections = Counter()


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
    if _connections[owner] >= 3:
        await socket.close(code=1013)
        return
    def valid_session():
        current = context.store.get_session_user(cookie)
        live = connections.live(current) if current else None
        return bool(current and current['id'] == user['id'] and current['workspace_id'] == user['workspace_id']
                    and current.get('role') == user.get('role') and live
                    and live['binding_id'] == binding['binding_id'])
    _connections[owner] += 1
    try:
        await socket.accept()
        await asyncio.wait_for(relay(
            socket, owner, valid_session, binding['agent_id'], readonly=user['role'] == 'viewer',
            allowed_skill_keys=allowed_skill_keys, chat_ready=skill_policy_ready,
        ), 3600)
    except Exception as exc:
        logging.getLogger(__name__).warning("OpenClaw relay closed: %s", str(exc) if isinstance(exc, RelayFailure) else type(exc).__name__)
        # Never log raw upstream frames, URLs, tokens, or provider error bodies.
        try:
            await socket.close(code=1011, reason='InfoHub OpenClaw relay unavailable; contact administrator')
        except Exception:
            pass
    finally:
        _connections[owner] -= 1
        if not _connections[owner]:
            del _connections[owner]


def register_openclaw_relay_routes(app: FastAPI):
    app.add_api_websocket_route(RELAY_PATH, openclaw_socket)
