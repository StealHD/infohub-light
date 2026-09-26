"""Minimal managed Skill capabilities; never grant shell or arbitrary filesystem access."""
from copy import deepcopy

_OWNED_TOOLS = {'read', 'browser', 'book_desktop'}
_OWNED_DENIES = _OWNED_TOOLS | {'group:fs', 'group:ui', 'canvas', 'computer'}


def required_skill_tools(skill_keys):
    required = ['read'] if skill_keys else []
    if 'book-skill' in skill_keys:
        required.extend(['browser', 'book_desktop'])
    return required


def skill_tool_policy(tools, skill_keys):
    """Keep MCP/custom policy intact while reconciling the owned read/browser slice."""
    result = deepcopy(tools)
    for field in ('allow', 'deny'):
        values = result.get(field, [])
        if not isinstance(values, list) or any(not isinstance(value, str) for value in values):
            raise ValueError('Invalid managed tool policy')
    if not result.get('allow'):
        raise ValueError('Managed Agent must have an explicit tool allowlist')
    required = required_skill_tools(skill_keys)
    result['allow'] = [tool for tool in result['allow'] if tool not in _OWNED_TOOLS] + required
    blocked = ['write', 'edit', 'apply_patch', 'exec', 'process', 'canvas', 'computer']
    if 'book_desktop' not in required:
        blocked.append('book_desktop')
    for tool, group in (('read', 'group:fs'), ('browser', 'group:ui')):
        if tool not in required:
            blocked.extend([group, tool])
    denied = [tool for tool in result.get('deny', []) if tool not in _OWNED_DENIES or tool in blocked]
    denied.extend(tool for tool in blocked if tool not in denied)
    result['deny'] = denied
    result['fs'] = {**result.get('fs', {}), 'workspaceOnly': True}
    return result


def verify_skill_tools(payload, skill_keys):
    available = {tool.get('id') for group in payload.get('groups', [])
                 for tool in group.get('tools', []) if isinstance(tool, dict)}
    if not set(required_skill_tools(skill_keys)).issubset(available):
        raise ValueError('Gateway Skill execution tools are unavailable')
