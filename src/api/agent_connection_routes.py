"""Personal status and trusted-administrator setup entry points."""
from fastapi import Depends, FastAPI, Response
from .context import ApiContext
from .responses import ok, ApiError
from .system_auth import api_context, current_user
from .agent_setup_routes import register_agent_setup_routes
from ..storage.information_automation_schema import ready as reminders_ready
from ..services.agent_connections.service import AgentConnections
from ..services.openclaw_relay.settings import enabled, configuration


async def connection_status(response: Response, user=Depends(current_user), context: ApiContext = Depends(api_context)):
    response.headers['Cache-Control'] = 'no-store'
    from ..services.agent_connections.managed_setup import status as setup_status
    progress = setup_status(context, user)
    status = AgentConnections(context.store, context.secret_values).status(user)
    from ..mcp.role_permissions import permissions
    status.update(permission_profile='role_default', permissions=permissions(user['role'], context.remote_mcp_settings))
    status['can_manage_setup'] = user['role'] in {'owner', 'admin'}
    status['setup'] = progress
    from .agent_access_routes import own_status
    status.update(own_status(context, user))
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
    from ..services.agent_connections import cleanup, cleanup_store
    from ..services.agent_connections.access_requests import AccessError
    connections = AgentConnections(context.store, context.secret_values)
    try:
        row = cleanup_store.begin(context, user, user)
        cleanup.start(context, row, user)
    except AccessError as error:
        raise ApiError('agent_cleanup_conflict', str(error), status_code=409) from error
    response.headers['Cache-Control'] = 'no-store'
    return ok({**connections.status(user), 'cleanup': cleanup.public(context, user['id'])})


def register_agent_connection_routes(app: FastAPI):
    from .agent_cleanup_routes import register as cleanup_register
    cleanup_register(app)
    from .agent_access_routes import register
    register(app)
    register_agent_setup_routes(app)
    app.add_api_route('/api/me/agent-connection', connection_status, methods=['GET'])
    app.add_api_route('/api/me/agent-connection', connection_revoke, methods=['DELETE'])
