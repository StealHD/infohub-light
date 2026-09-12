"""One live permission projection for MCP discovery and user-facing connection status."""
from ..storage.agent_delegation_scopes import (
    effective_scopes, AGENT_DELEGATION_READ_SCOPE, AGENT_DELEGATION_WRITE_SCOPE,
    AGENT_DELEGATION_SYSTEM_SETTINGS_WRITE_SCOPE, AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE,
)
from ..services.agent_connections.manifest import READ_TOOLS, USER_TOOLS


def permissions(role, settings):
    return {
        'read': settings.enabled,
        'subscriptions_write': settings.enabled and settings.subscription_writes_enabled and role in {'owner', 'admin', 'member'},
        'system_settings_write': settings.enabled and settings.system_settings_writes_enabled and role in {'owner', 'admin'},
        'workspace_diagnostics': settings.enabled and role in {'owner', 'admin'},
    }


def project_connection(connection, role, settings):
    scopes = connection['scopes']
    if not scopes:
        return {**connection, 'permission_profile': 'role_default', 'permissions': dict.fromkeys(permissions(role, settings), False)}
    if any(scope.startswith('inteliscope:information-automations:') for scope in scopes):
        return connection
    scopes = effective_scopes(scopes, role)
    return {**connection, 'access': 'role_default', 'permission_profile': 'role_default',
            'permissions': permissions(role, settings) if connection.get('status') == 'active' else dict.fromkeys(permissions(role, settings), False), 'scopes': scopes,
            'diagnostics_scope': 'workspace' if AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE in scopes else 'self'}


def visible_tools(principal, settings):
    if not principal:
        return set()
    scopes = principal['scopes']
    names = set(READ_TOOLS) if AGENT_DELEGATION_READ_SCOPE in scopes and settings.enabled else set()
    access = permissions(principal['role'], settings)
    if access['subscriptions_write'] and AGENT_DELEGATION_WRITE_SCOPE in scopes:
        names.update(USER_TOOLS[13:17])
    if access['system_settings_write'] and AGENT_DELEGATION_SYSTEM_SETTINGS_WRITE_SCOPE in scopes:
        names.update(USER_TOOLS[17:])
    from .remote_information_tools import TOOL_SCOPES
    names.update(name for name, scope in TOOL_SCOPES.items() if scope in scopes and settings.enabled)
    return names
