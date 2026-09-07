"""Explicit RPC boundary: the browser cannot control arbitrary Gateway methods."""
from .ownership import Ownership

SESSION_METHODS = {
    'chat.history': {'sessionKey', 'agentId', 'limit'},
    'chat.send': {'sessionKey', 'agentId', 'message', 'idempotencyKey', 'thinking', 'attachments', 'deliver', 'fastMode'},
    'chat.abort': {'sessionKey', 'agentId', 'runId'},
    'sessions.describe': {'key'},
    'sessions.patch': {'key', 'agentId', 'archived'},
    'tools.effective': {'sessionKey', 'agentId'},
}


def request_params(method: str, params: dict, owner: Ownership, agent: str) -> dict:
    if method == 'models.list':
        return {'view': 'configured'}
    if method in {'agents.list', 'sessions.subscribe'}:
        return {}
    if method == 'sessions.create':
        if set(params) - {'agentId', 'label', 'parentSessionKey', 'fork', 'model'}:
            raise PermissionError('Unsupported session options')
        result = {'agentId': agent}
        if params.get('parentSessionKey'):
            if not owner.owns(params['parentSessionKey']):
                raise PermissionError('Session is not owned by this user')
            result.update(parentSessionKey=params['parentSessionKey'], fork=True)
        if params.get('model'):
            result['model'] = params['model']
        return result
    if method == 'sessions.preview':
        keys = params.get('keys')
        if set(params) != {'keys'} or not isinstance(keys, list) or not 1 <= len(keys) <= 20 or not all(owner.owns(key) for key in keys):
            raise PermissionError('Owned sessions are required')
        return {'keys': keys}
    if method == 'sessions.list':
        if not owner.owns(params.get('search')):
            raise PermissionError('An owned session is required')
        return {'search': params['search'], 'limit': 100}
    allowed = SESSION_METHODS.get(method)
    if allowed is None or set(params) - allowed:
        raise PermissionError('RPC is not available through InfoHub')
    key = params.get('sessionKey', params.get('key'))
    if not owner.owns(key):
        raise PermissionError('Session is not owned by this user')
    result = dict(params)
    if 'agentId' in result:
        result['agentId'] = agent
    if method == 'chat.send':
        result['deliver'] = False
    return result


def response_payload(method: str, payload: dict, owner: Ownership, agent: str) -> dict:
    if method == 'sessions.create':
        key = payload.get('key')
        if not isinstance(key, str) or not key.startswith('agent:' + agent + ':'):
            raise ValueError('Invalid upstream session')
        owner.add(key)
    if method == 'sessions.list':
        sessions = [s for s in payload.get('sessions', []) if owner.owns(s.get('key'))]
        return {'sessions': sessions, 'count': len(sessions)}
    if method == 'sessions.preview':
        return {'previews': [p for p in payload.get('previews', []) if owner.owns(p.get('key'))]}
    if method == 'agents.list':
        return {**payload, 'agents': [a for a in payload.get('agents', []) if a.get('id') == agent]}
    return payload


def visible_event(frame: dict, owner: Ownership) -> bool:
    payload = frame.get('payload')
    if not isinstance(payload, dict):
        return False
    key = payload.get('sessionKey', payload.get('key'))
    return frame.get('event') in {'chat', 'agent', 'sessions.changed'} and owner.owns(key)
