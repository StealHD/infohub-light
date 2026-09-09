"""Personal status and trusted-administrator setup entry points."""
from fastapi import Depends, FastAPI, Response
from .context import ApiContext
from .responses import ok
from .system_auth import api_context, current_user
from .agent_setup_routes import register_agent_setup_routes
from ..storage.information_automation_schema import ready as reminders_ready
from ..services.agent_connections.service import AgentConnections
from ..services.openclaw_relay.settings import enabled, configuration


async def connection_status(response: Response, user=Depends(current_user), context: ApiContext = Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    status = AgentConnections(context.store, context.secret_values).status(user)
    status['can_manage_setup'] = user['role'] in {'owner', 'admin'}
    status['can_connect'] &= enabled() and context.openclaw_chat_settings.enabled
    try:
        configuration()
    except ValueError:
        status['can_connect'] = False
    status['can_chat'] &= status['can_connect']
    status['verification']['own_content'] &= context.remote_mcp_settings.enabled
    status['verification']['information_automations'] = bool(status['verification']['deployment']
        and user['role'] != 'viewer' and reminders_ready(context.store.connect()))
    targets = context.notification_targets.list_public_targets(workspace_id=user['workspace_id'], user_id=user['id'])
    status['verification']['notifications'] = any(target.get('available') for target in targets['targets'])
    return ok(status)


async def connection_revoke(response: Response, user=Depends(current_user), context: ApiContext = Depends(api_context)):
    connections = AgentConnections(context.store, context.secret_values)
    connections.revoke(user['id'])
    response.headers['Cache-Control'] = 'no-store'
    return ok(connections.status(user))


def register_agent_connection_routes(app: FastAPI):
    register_agent_setup_routes(app)
    app.add_api_route('/api/me/agent-connection', connection_status, methods=['GET'])
    app.add_api_route('/api/me/agent-connection', connection_revoke, methods=['DELETE'])
