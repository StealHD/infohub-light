"""Explicit RPC boundary: the browser cannot control arbitrary Gateway methods."""
import re
from .ownership import Ownership
from .directory import directory_params, directory_payload, skills_params, skills_payload
from .errors import safe_history_failures

SESSION_METHODS = {
    'chat.history': {'sessionKey', 'agentId', 'limit', 'maxChars'},
    'chat.send': {'sessionKey', 'agentId', 'message', 'idempotencyKey', 'thinking', 'attachments', 'deliver', 'fastMode'},
    'chat.abort': {'sessionKey', 'agentId', 'runId'},
    'sessions.describe': {'key'},
    'sessions.patch': {'key', 'agentId', 'archived'},
    'tools.effective': {'sessionKey', 'agentId'},
}


def request_params(method: str, params: dict, owner: Ownership, agent: str, *, readonly: bool = False) -> dict:
    if 'agentId' in params and params['agentId'] != agent:
        # An earlier Agent is addressable only for already-owned history.
        key = params.get('sessionKey')
        if not (method == 'chat.history' and isinstance(key, str) and key.startswith('agent:' + str(params['agentId']) + ':')
                and owner.owns(key)):
            raise PermissionError('Agent is not bound to this user')
    if readonly and method not in {'models.list', 'agents.list', 'sessions.subscribe', 'sessions.preview',
                                   'sessions.list', 'sessions.describe', 'chat.history', 'tools.effective', 'skills.status'}:
        raise PermissionError('Viewer is read-only')
    if method == 'models.list':
        return {'view': 'configured', 'agentId': agent}
    if method in {'agents.list', 'sessions.subscribe'}:
        return {}
    if method == 'sessions.create':
        if set(params) - {'agentId', 'label', 'parentSessionKey', 'fork', 'model'}:
            raise PermissionError('Unsupported session options')
        result = {'agentId': agent}
        if params.get('parentSessionKey'):
            if not owner.owns(params['parentSessionKey']) or not params['parentSessionKey'].startswith('agent:' + agent + ':'):
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
        return directory_params(params, owner, agent)
    if method == 'skills.status':
        return skills_params(params, owner, agent)
    allowed = SESSION_METHODS.get(method)
    if allowed is None or set(params) - allowed:
        raise PermissionError('RPC is not available through InfoHub')
    key = params.get('sessionKey', params.get('key'))
    if not owner.owns(key):
        raise PermissionError('Session is not owned by this user')
    if not key.startswith('agent:' + agent + ':'):
        if method not in {'chat.history', 'sessions.describe'}:
            raise PermissionError('Retired sessions are read-only')
    result = dict(params)
    if method == 'chat.history' and not key.startswith('agent:' + agent + ':'):
        # Let the exact legacy key select its original Agent; never rewrite history routing.
        result.pop('agentId', None)
    if method == 'chat.send':
        message = result.get('message')
        if not isinstance(message, str) or re.match(r'^[\s\ufeff]*[/!]', message):
            raise PermissionError('Native Gateway commands are unavailable through personal chat')
        result['deliver'] = False
    return result


def response_payload(method: str, payload: dict, owner: Ownership, agent: str, params: dict | None = None,
                     allowed_skill_keys=None) -> dict:
    if method == 'chat.history':
        return safe_history_failures(payload)
    if method == 'sessions.create':
        key = payload.get('key')
        if not isinstance(key, str) or not key.startswith('agent:' + agent + ':'):
            raise ValueError('Invalid upstream session')
        owner.add(key)
    if method == 'sessions.list':
        return directory_payload(payload, owner, agent, params)
    if method == 'skills.status':
        return skills_payload(payload, allowed_skill_keys)
    if method == 'sessions.preview':
        return {'previews': [p for p in payload.get('previews', []) if owner.owns(p.get('key'))]}
    if method == 'agents.list':
        return {'defaultId': agent, 'agents': [a for a in payload.get('agents', []) if a.get('id') == agent]}
    return payload


def visible_event(frame: dict, owner: Ownership) -> bool:
    payload = frame.get('payload')
    if not isinstance(payload, dict):
        return False
    key = payload.get('sessionKey', payload.get('key'))
    return frame.get('event') in {'chat', 'agent', 'sessions.changed'} and owner.owns(key)
