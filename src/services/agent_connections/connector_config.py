"""An isolated completion Agent has no MCP, filesystem or notification tools."""
import copy
from pathlib import Path
from .gateway_config import DENIED, _safe_server
from .manifest import validate_manifest


def configure(config, base, root):
    validate_manifest(base)
    root = Path(root).resolve()
    result = copy.deepcopy(config)
    agents = result.get('agents', {}).get('entries', {})
    personal = agents.get(base['agent_id'])
    if not personal or Path(personal.get('workspace', '')).resolve() != root / 'managed' / base['agent_id'] / 'workspace':
        raise ValueError('Personal Agent must already be installed')
    agent_id = 'ic-' + base['binding_id']
    denied = list(DENIED) + [_safe_server(name) + '__*' for name in result.get('mcp', {}).get('servers', {})]
    entry = {'workspace': str(root / 'managed' / agent_id / 'workspace'),
             'agentDir': str(root / 'managed' / agent_id / 'agent'),
             'tools': {'allow': ['llm-task'], 'deny': denied}, 'subagents': {'allowAgents': []}}
    if agent_id in agents and agents[agent_id] != entry:
        raise ValueError('Connector Agent policy drift')
    for identity, other in agents.items():
        if identity == agent_id:
            continue
        is_connector = (identity.startswith('ic-') and other.get('tools', {}).get('allow') == ['llm-task']
                        and other.get('workspace') == str(root / 'managed' / identity / 'workspace'))
        if not is_connector:
            deny = other.setdefault('tools', {}).setdefault('deny', [])
            if 'llm-task' not in deny:
                deny.append('llm-task')
    agents[agent_id] = entry
    result.setdefault('plugins', {}).setdefault('entries', {}).setdefault('llm-task', {})['enabled'] = True
    return result, agent_id
