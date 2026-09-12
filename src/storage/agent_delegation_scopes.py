"""Role-derived user permissions and isolated internal delegation profiles."""
AGENT_DELEGATION_READ_SCOPE = 'inteliscope:read'
AGENT_DELEGATION_WRITE_SCOPE = 'inteliscope:subscriptions:write'
AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE = 'inteliscope:diagnostics:read'
AGENT_DELEGATION_SYSTEM_SETTINGS_WRITE_SCOPE = 'inteliscope:system-settings:write'
INFORMATION_READ_SCOPE = 'inteliscope:information-automations:read'
INFORMATION_DRAFT_SCOPE = 'inteliscope:information-automations:draft'
SCOPE_ORDER = (AGENT_DELEGATION_READ_SCOPE, AGENT_DELEGATION_WRITE_SCOPE,
               AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE, AGENT_DELEGATION_SYSTEM_SETTINGS_WRITE_SCOPE,
               INFORMATION_READ_SCOPE, INFORMATION_DRAFT_SCOPE)
PROFILES = {
    'role_default': (),
    'read': (),
    'subscriptions_write': (AGENT_DELEGATION_WRITE_SCOPE,),
    'system_settings_write': (AGENT_DELEGATION_SYSTEM_SETTINGS_WRITE_SCOPE,),
    'information_automations_read': (INFORMATION_READ_SCOPE,),
    'information_automations_draft': (INFORMATION_READ_SCOPE, INFORMATION_DRAFT_SCOPE),
}


def scopes_for_access(access: str, *, diagnostics_scope: str = 'self') -> list[str]:
    if access not in PROFILES:
        raise ValueError('unsupported delegation access')
    scopes = [AGENT_DELEGATION_READ_SCOPE, *PROFILES[access]]
    if diagnostics_scope == 'workspace':
        scopes.append(AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE)
    elif diagnostics_scope != 'self':
        raise ValueError('diagnostics_scope must be self or workspace')
    return [scope for scope in SCOPE_ORDER if scope in scopes]


def access_for_scopes(scopes: list[str]) -> str:
    if INFORMATION_DRAFT_SCOPE in scopes:
        return 'information_automations_draft'
    if INFORMATION_READ_SCOPE in scopes:
        return 'information_automations_read'
    return 'role_default' if scopes else 'read'


def effective_scopes(scopes, role):
    if not scopes or INFORMATION_READ_SCOPE in scopes or INFORMATION_DRAFT_SCOPE in scopes:
        return scopes
    allowed = [AGENT_DELEGATION_READ_SCOPE]
    if role in {'owner', 'admin', 'member'}:
        allowed.append(AGENT_DELEGATION_WRITE_SCOPE)
    if role in {'owner', 'admin'}:
        allowed.extend([AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE, AGENT_DELEGATION_SYSTEM_SETTINGS_WRITE_SCOPE])
    return allowed
