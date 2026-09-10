"""Conservative managed Agent configuration compiler for OpenClaw 2026.9.2."""
import copy
import re
from pathlib import Path
from .manifest import validate_manifest

# A fixed restrictive allowlist is authoritative. Denies additionally block host/cross-session paths.
DENIED = ['group:runtime', 'group:fs', 'group:sessions', 'group:memory', 'group:ui',
          'group:messaging', 'group:automation', 'group:nodes', 'exec', 'process', 'read',
          'write', 'edit', 'apply_patch', 'browser', 'web_fetch', 'web_search', 'sessions_spawn',
          'sessions_send', 'session_status', 'message', 'cron', 'gateway', 'nodes']


def agent_entry(manifest, root):
    root = Path(root).resolve()
    agent_id = manifest['agent_id']
    return {'workspace': str(root / 'managed' / agent_id / 'workspace'),
            'agentDir': str(root / 'managed' / agent_id / 'agent'),
            'skills': list(manifest.get('skills', [])),
            'memorySearch': {'enabled': False},
            'tools': {'allow': [manifest['mcp_server'] + '__' + tool for tool in manifest['tools']],
                      'deny': list(DENIED)},
            'subagents': {'allowAgents': []}}


def mcp_entry(manifest):
    return {'url': manifest['mcp_url'], 'transport': 'streamable-http', 'headers': {
        'Authorization': 'Bearer ${' + manifest['secret_ref'] + '}'},
        'toolFilter': {'include': manifest['tools']},
        'connectionTimeoutMs': 15000, 'requestTimeoutMs': 30000}


def _safe_server(name):
    value = re.sub(r'[^A-Za-z0-9_-]', '-', name.strip()) or 'mcp'
    return (value if value[0].isalpha() else 'mcp-' + value)[:30].lower()


def configure(config, manifest, root):
    validate_manifest(manifest)
    result = copy.deepcopy(config)
    if result.get('session', {}).get('store'):
        raise ValueError('Custom session.store must be reviewed and removed before personal provisioning')
    if '$include' in result or 'list' in result.get('agents', {}):
        raise ValueError('Included/legacy Agent configs must be migrated explicitly first')
    agents = result.setdefault('agents', {}).setdefault('entries', {})
    servers = result.setdefault('mcp', {}).setdefault('servers', {})
    agent_id, namespace = manifest['agent_id'], manifest['mcp_server']
    if not isinstance(agents, dict) or not isinstance(servers, dict):
        raise ValueError('Expected named Agent entries and MCP servers')
    if any(_safe_server(name) == namespace for name in servers if name != namespace):
        raise ValueError('MCP canonical namespace collision')
    expected_agent, expected_mcp = agent_entry(manifest, root), mcp_entry(manifest)
    # Re-running may preserve denies added when another personal Agent was provisioned.
    if agent_id in agents:
        prior = copy.deepcopy(agents[agent_id])
        prior.setdefault('memorySearch', {'enabled': False})
        extra_denies = prior.get('tools', {}).get('deny', [])
        prior.setdefault('tools', {})['deny'] = list(DENIED)
        permitted = set(DENIED) | {_safe_server(name) + '__*' for name in servers if name != namespace}
        if 'llm-task' in extra_denies:
            permitted.add('llm-task')
        if prior != expected_agent or set(extra_denies) != permitted:
            raise ValueError('Existing managed Agent differs; review config drift before reinstalling')
        expected_agent['tools']['deny'] = extra_denies
    if namespace in servers and not compatible_mcp(servers[namespace], manifest):
        raise ValueError('MCP name already occupied or changed')
    # Explicit main prevents an implicit default Agent inheriting new global MCP credentials.
    agents.setdefault('main', {})
    if result['agents'].get('ownership') != 'explicit' and not any(e.get('default') is True for e in agents.values()):
        agents['main']['default'] = True
    for other_id, entry in agents.items():
        if other_id == agent_id:
            continue
        deny = entry.setdefault('tools', {}).setdefault('deny', [])
        rule = namespace + '__*'
        if rule not in deny:
            deny.append(rule)
    for name in servers:
        rule = _safe_server(name) + '__*'
        if name != namespace and rule not in expected_agent['tools']['deny']:
            expected_agent['tools']['deny'].append(rule)
    agents[agent_id] = expected_agent
    servers[namespace] = expected_mcp
    return result


def compatible_mcp(value, manifest):
    """Only the historical omission is repairable; explicit protocol drift is not."""
    prior = copy.deepcopy(value)
    prior.setdefault('transport', 'streamable-http')
    return prior == mcp_entry(manifest)


def verify_config(config, manifest, root):
    if configure(config, manifest, root) != config:
        raise ValueError('Agent or namespace isolation is not installed')
    expected = agent_entry(manifest, root)
    paths = [Path(expected[field]) for field in ('workspace', 'agentDir')]
    paths.append(Path(root).resolve() / 'agents' / manifest['agent_id'] / 'sessions')
    for path in paths:
        if path.is_symlink() or path.resolve() != path:
            raise ValueError('Managed directories must not use symlinks')
    # No other Agent may reuse this workspace, Agent directory or personal MCP namespace.
    for identity, entry in config['agents']['entries'].items():
        if identity == manifest['agent_id']:
            continue
        for field in ('workspace', 'agentDir'):
            other = entry.get(field)
            if other and (Path(other).expanduser().resolve() == Path(expected[field])):
                raise ValueError('Agent directories are shared')
