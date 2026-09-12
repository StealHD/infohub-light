"""Existing user tokens follow roles; internal reminder grants remain isolated."""
import pytest
from tests.test_agent_connections import personal  # noqa: F401
from src.mcp.remote_config import RemoteMCPSettings
from src.mcp.role_permissions import visible_tools, project_connection


@pytest.mark.parametrize('role,count', [('owner',20),('admin',20),('member',17),('viewer',13)])
def test_existing_token_role_changes_and_flags(personal, role, count):
    store, _, owner, user = personal
    grant, token = store.create_agent_delegation(workspace_id=user['workspace_id'], user_id=user['id'], name='Legacy read')
    store.update_user(user['id'], role=role)
    principal = store.authenticate_agent_delegation(token)
    settings = RemoteMCPSettings(public_url="http://localhost/mcp", enabled=True, subscription_writes_enabled=True, system_settings_writes_enabled=True)
    assert len(visible_tools(principal, settings)) == count
    assert project_connection(grant, role, settings)['permission_profile'] == 'role_default'
    settings = RemoteMCPSettings(public_url="http://localhost/mcp", enabled=True)
    assert len(visible_tools(principal, settings)) == 13
    store.update_user(user['id'], role='viewer')
    assert store.authenticate_agent_delegation(token)['scopes'] == ['inteliscope:read']
    store.update_user(user['id'], enabled=False)
    assert store.authenticate_agent_delegation(token) is None


def test_reminder_token_never_gains_system_or_subscription_write(personal):
    store, _, owner, _ = personal
    grant, token = store.create_agent_delegation(workspace_id=owner['workspace_id'], user_id=owner['id'], name='Isolated', access='information_automations_draft')
    principal = store.authenticate_agent_delegation(token)
    assert principal['scopes'] == grant['scopes']
    names = visible_tools(principal, RemoteMCPSettings(public_url="http://localhost/mcp", enabled=True, subscription_writes_enabled=True, system_settings_writes_enabled=True))
    assert 'prepare_information_automation' in names
    assert 'apply_subscription_change' not in names
    assert 'apply_system_settings_change' not in names
