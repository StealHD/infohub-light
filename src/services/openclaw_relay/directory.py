"""Bounded personal session directory and public skill metadata projections."""
import re


def personal_agent(agent):
    return isinstance(agent, str) and re.fullmatch(r'ih-[a-f0-9]{32}', agent) is not None


def directory_params(params, owner, agent):
    if not personal_agent(agent):
        if not owner.owns(params.get('search')):
            raise PermissionError('An owned session is required')
        return {'search': params['search'], 'limit': 100}
    allowed = {'agentId', 'limit', 'offset', 'search', 'archived', 'sortBy',
               'includeDerivedTitles', 'includeLastMessage'}
    if set(params) - allowed:
        raise PermissionError('Unsupported directory options')
    search = params.get('search')
    if owner.owns(search) and not search.startswith('agent:' + agent + ':'):
        return {'search': search, 'limit': 1, 'archived': 'all'}
    limit, offset = params.get('limit', 50), params.get('offset', 0)
    search, archived = params.get('search', ''), params.get('archived', False)
    if (type(limit) is not int or not 1 <= limit <= 100 or type(offset) is not int or offset < 0
            or not isinstance(search, str) or len(search) > 512
            or not (type(archived) is bool or archived == 'all')
            or params.get('sortBy', 'updatedAt') != 'updatedAt'):
        raise PermissionError('Invalid directory options')
    return {'agentId': agent, 'limit': limit, 'offset': offset, 'search': search,
            'archived': archived, 'sortBy': 'updatedAt',
            'includeDerivedTitles': True, 'includeLastMessage': True}


SESSION_FIELDS = {'key', 'label', 'displayName', 'derivedTitle', 'lastMessagePreview', 'agentId',
                  'updatedAt', 'createdAt', 'archived', 'parentSessionKey', 'createdVia',
                  'hasActiveRun', 'totalTokens', 'contextWindow', 'totalTokensFresh', 'model',
                  'modelProvider', 'provider', 'modelId', 'contextTokens', 'inputTokens', 'outputTokens'}


def directory_payload(payload, owner, agent, params=None):
    rows = payload.get('sessions', [])
    if not isinstance(rows, list):
        raise ValueError('Invalid upstream directory')
    search = (params or {}).get('search')
    legacy = owner.owns(search) and not search.startswith('agent:' + agent + ':')
    personal = personal_agent(agent) and not legacy
    sessions = []
    for row in rows:
        if not isinstance(row, dict):
            raise ValueError('Invalid upstream session')
        key = row.get('key')
        if personal:
            if not isinstance(key, str) or not key.startswith('agent:' + agent + ':'):
                raise ValueError('Upstream directory escaped personal Agent')
            owner.add(key)
        if owner.owns(key) and (not legacy or key == search):
            sessions.append({k: v for k, v in row.items() if k in SESSION_FIELDS})
    result = {'sessions': sessions, 'count': len(sessions)}
    if personal:
        for field in ('totalCount', 'nextOffset'):
            value = payload.get(field)
            if type(value) is int and value >= 0:
                result[field] = value
        result['hasMore'] = payload.get('hasMore') is True
    return result


def skills_params(params, owner, agent):
    if set(params) - {'agentId', 'sessionKey'}:
        raise PermissionError('Unsupported skill options')
    key = params.get('sessionKey')
    if key is not None and (not owner.owns(key) or not key.startswith('agent:' + agent + ':')):
        raise PermissionError('Session is not owned by this user')
    return {'agentId': agent, **({'sessionKey': key} if key else {})}


def skills_payload(payload, allowed_skill_keys=None):
    fields = {'skillKey', 'name', 'description', 'disabled', 'enabled', 'eligible',
              'blockedByAllowlist', 'blockedByAgentFilter', 'userInvocable', 'commandVisible', 'modelVisible'}
    rows = payload.get('skills')
    if not isinstance(rows, list):
        raise ValueError('Invalid upstream skills')
    skills = []
    for row in rows:
        if not isinstance(row, dict):
            continue
        if allowed_skill_keys is not None and row.get('skillKey') not in allowed_skill_keys:
            continue
        public = {k: v for k, v in row.items() if k in fields}
        missing = row.get('missing', {})
        public['missing'] = {key: [value for value in missing.get(key, [])[:64]
                                  if isinstance(value, str) and re.fullmatch(r'[A-Za-z0-9_.-]{1,128}', value)]
                             for key in ('bins', 'anyBins', 'env', 'config', 'os')
                             if isinstance(missing, dict) and isinstance(missing.get(key), list)}
        skills.append(public)
    return {'skills': skills, 'install': {'allowUploadedArchives': False}}
