"""Narrow privileged lifecycle operation for a user's already-owned personal session."""
import math
from ..operation_log import safe_emit_operation_event
from ..agent_skill_gateway import AgentSkillGateway
from .policy import request_params, response_payload


async def delete_owned_session(context, owner, agent, params, valid_session):
    request_params('sessions.delete', params, owner, agent)
    gateway = AgentSkillGateway(context.secret_values, context.store.data_dir)
    async def operation(socket, hello):
        methods = hello.get('features', {}).get('methods', [])
        if not {'sessions.list', 'sessions.delete'} <= set(methods):
            raise PermissionError('Session deletion unsupported')
        listing = await gateway._request(socket, 'delete-check', 'sessions.list',
            {'agentId': agent, 'search': params['key'], 'limit': 100, 'archived': 'all'})
        matches = [row for row in listing.get('sessions', []) if row.get('key') == params['key']]
        if len(matches) != 1 or matches[0].get('hasActiveRun') is not False:
            raise PermissionError('Session activity is not safely idle')
        row = matches[0]
        if row.get('worktree'):
            raise PermissionError('Worktree cleanup cannot preserve the session atomically')
        if row.get('agentId', agent) != agent or not valid_session():
            raise PermissionError('Session authority changed')
        payload = dict(params)
        if not isinstance(row.get('sessionId'), str) or not row['sessionId']:
            raise PermissionError('Session identity is unavailable')
        payload['expectedSessionId'] = row['sessionId']
        updated = row.get('updatedAt')
        if type(updated) in {int, float} and math.isfinite(updated) and updated >= 0:
            payload['expectedSessionUpdatedAt'] = updated
        if isinstance(row.get('lifecycleRevision'), str) and row['lifecycleRevision']:
            payload['expectedLifecycleRevision'] = row['lifecycleRevision']
        result = await gateway._request(socket, 'delete-session', 'sessions.delete', payload)
        return response_payload('sessions.delete', result, owner, agent, params)
    try:
        result = await gateway._session(operation)
    except Exception:
        safe_emit_operation_event(category='agent', action='session_delete', outcome='failed', error_code='session_delete_unconfirmed')
        raise
    safe_emit_operation_event(category='agent', action='session_delete', outcome='succeeded' if result['deleted'] else 'skipped', counts={'deleted': int(result['deleted'])})
    return result
