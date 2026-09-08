"""Separate, explicit reminder grant export and restrictive Gateway extension."""
import copy
import hashlib
import json
from .service import AgentConnections, BindingError
from .gateway_config import verify_config, _safe_server
from .manifest import validate_manifest

TOOLS = ['list_my_information_automations', 'prepare_information_automation']


def prepare(store, secrets, user_id):
    connections = AgentConnections(store, secrets)
    user = store.get_user(user_id)
    binding = connections.live(user) if user and user['enabled'] else None
    if not binding or user['role'] == 'viewer':
        raise BindingError('Active personal binding and writable user required')
    base = validate_manifest(json.loads(binding['manifest_json']))
    name = 'Reminder drafts ' + binding['binding_id'][:8]
    secret_ref = 'INTELISCOPE_REMINDERS_' + binding['binding_id'].upper()
    grants = [row for row in store.list_agent_delegations(user_id)
              if row['name'] == name and row['status'] == 'active']
    token = secrets.read().get(secret_ref)
    if grants:
        if len(grants) != 1 or grants[0]['access'] != 'information_automations_draft' or not token:
            raise BindingError('Existing reminder grant needs operator review')
        grant = grants[0]
        principal = store.authenticate_agent_delegation(token)
        if not principal or principal.get('delegation_id') != grant['id']:
            raise BindingError('Reminder credential mismatch')
    else:
        grant, token = store.create_agent_delegation(workspace_id=user['workspace_id'], user_id=user_id,
            name=name, access='information_automations_draft')
        try:
            secrets.set(secret_ref, token)
        except Exception:
            store.revoke_agent_delegation(user_id=user_id, delegation_id=grant['id'])
            raise
    return {'base': base, 'delegation_id': grant['id'], 'mcp_server': 'ir_' + binding['binding_id'][:24],
            'secret_ref': secret_ref, 'token_sha256': hashlib.sha256(token.encode()).hexdigest(), 'tools': TOOLS}, token


def configure(config, manifest, root):
    base = validate_manifest(manifest['base'])
    namespace = 'ir_' + base['binding_id'][:24]
    if manifest['mcp_server'] != namespace or manifest['tools'] != TOOLS or manifest['secret_ref'] != 'INTELISCOPE_REMINDERS_' + base['binding_id'].upper():
        raise ValueError('Invalid reminder namespace policy')
    result = copy.deepcopy(config)
    servers = result.get('mcp', {}).get('servers', {})
    entry = {'url': base['mcp_url'], 'headers': {'Authorization': 'Bearer ${' + manifest['secret_ref'] + '}'},
             'toolFilter': {'include': TOOLS}, 'connectionTimeoutMs': 15000, 'requestTimeoutMs': 30000}
    allowed = [namespace + '__' + tool for tool in TOOLS]
    if namespace in servers:
        if servers.pop(namespace) != entry:
            raise ValueError('Reminder namespace drift')
        for identity, agent in result['agents']['entries'].items():
            if identity == base['agent_id']:
                previous = agent['tools']['allow']
                if not all(tool in previous for tool in allowed):
                    raise ValueError('Reminder tool policy drift')
                agent['tools']['allow'] = [tool for tool in previous if tool not in allowed]
            else:
                agent['tools']['deny'] = [rule for rule in agent['tools']['deny'] if rule != namespace + '__*']
    if any(_safe_server(name) == namespace for name in servers):
        raise ValueError('Reminder namespace collision')
    verify_config(result, base, root)
    result['mcp']['servers'][namespace] = entry
    for identity, agent in result['agents']['entries'].items():
        if identity == base['agent_id']:
            agent['tools']['allow'].extend(allowed)
        else:
            deny = agent.setdefault('tools', {}).setdefault('deny', [])
            previous = config['agents']['entries'][identity].get('tools', {}).get('deny', [])
            if namespace + '__*' in previous:
                deny.insert(previous.index(namespace + '__*'), namespace + '__*')
            else:
                deny.append(namespace + '__*')
    return result
