"""Read/revoke only: provisioning and activation require local operator access."""
from fastapi import Depends, FastAPI, Response
from .context import ApiContext
from .responses import ok
from .system_auth import api_context, current_user
from ..services.agent_connections.service import AgentConnections
from ..services.openclaw_relay.settings import enabled


async def connection_status(response: Response, user=Depends(current_user), context: ApiContext = Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    status = AgentConnections(context.store, context.secret_values).status(user)
    status['can_connect'] &= enabled() and context.openclaw_chat_settings.enabled
    status['can_chat'] &= status['can_connect']
    status['verification']['own_content'] &= context.remote_mcp_settings.enabled
    return ok(status)


async def connection_revoke(response: Response, user=Depends(current_user), context: ApiContext = Depends(api_context)):
    connections = AgentConnections(context.store, context.secret_values)
    connections.revoke(user['id'])
    response.headers['Cache-Control'] = 'no-store'
    return ok(connections.status(user))


def register_agent_connection_routes(app: FastAPI):
    app.add_api_route('/api/me/agent-connection', connection_status, methods=['GET'])
    app.add_api_route('/api/me/agent-connection', connection_revoke, methods=['DELETE'])
