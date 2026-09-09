"""Personal binding lifecycle, operator proof and offline migration boundaries."""
import json
import sqlite3
from contextlib import closing
from datetime import datetime, timedelta, timezone
import pytest
from src.storage.service_store import ServiceStore
from src.services.secret_store import SecretStore
from src.services.agent_connections.service import AgentConnections, BindingError
from src.services.agent_skill_access import AgentSkillAccess, AgentSkillPolicyError
from src.services.agent_connections.manifest import receipt, digest
from src.services.agent_connections.gateway_config import configure, verify_config
from scripts.migrate_agent_connections_v37 import migrate
from scripts.manage_agent_connection import export_bundle


@pytest.fixture
def personal(tmp_path, monkeypatch):
    monkeypatch.setenv('HORIZON_AUTH_USER', 'owner')
    monkeypatch.setenv('HORIZON_AUTH_PASSWORD', 'test-password')
    store = ServiceStore(tmp_path)
    store.initialize()
    alice = store.get_user_by_username('owner')
    bob = store.create_user(workspace_id=alice['workspace_id'], username='bob', password='test-password')
    return store, AgentConnections(store, SecretStore(tmp_path)), alice, bob


def bind(connections, user):
    manifest = connections.prepare(user['id'], 'http://127.0.0.1:8080/mcp')
    _, token = connections.export(user['id'])
    proof = receipt(manifest, token, 'a' * 64)
    connections.activate(user['id'], proof)
    return manifest, token, proof


def test_personal_identity_credentials_and_restart(personal, tmp_path):
    store, connections, alice, bob = personal
    a, ta, _ = bind(connections, alice)
    b, tb, _ = bind(connections, bob)
    for name in ('agent_id', 'mcp_server', 'delegation_id', 'secret_ref'):
        assert a[name] != b[name]
    assert len(a['mcp_server']) <= 30
    assert store.authenticate_agent_delegation(ta)['user_id'] == alice['id']
    assert store.authenticate_agent_delegation(tb)['user_id'] == bob['id']
    dumped = '\n'.join(store.connect().iterdump())
    assert ta not in dumped and tb not in dumped
    assert (tmp_path / 'secrets.env').stat().st_mode & 0o777 == 0o600
    restarted = AgentConnections(ServiceStore(tmp_path), SecretStore(tmp_path))
    assert restarted.live(alice)['agent_id'] == a['agent_id']
    assert restarted.live(bob)['agent_id'] == b['agent_id']
    assert ta not in json.dumps(restarted.status(alice))
    export_bundle(connections, alice['id'], tmp_path / 'export')
    assert (tmp_path / 'export/token').stat().st_mode & 0o777 == 0o600
    assert ta not in (tmp_path / 'export/manifest.json').read_text()


@pytest.mark.parametrize('failure', ['revoke', 'disable', 'expire', 'expand', 'delete', 'wrong_owner'])
def test_binding_invalidates_live_authorization_without_fallback(personal, failure):
    store, connections, alice, bob = personal
    a, token, _ = bind(connections, alice)
    bind(connections, bob)
    if failure == 'revoke':
        store.revoke_agent_delegation(alice['id'], a['delegation_id'])
    elif failure == 'disable':
        store.update_user(alice['id'], enabled=False)
    elif failure == 'delete':
        store.revoke_agent_delegation(alice['id'], a['delegation_id'])
        store.delete_revoked_agent_delegation(alice['id'], a['delegation_id'])
    else:
        column, value = {'expire': ('expires_at', '2000-01-01T00:00:00+00:00'),
                         'expand': ('scopes_json', '["inteliscope:read","inteliscope:subscriptions:write"]'),
                         'wrong_owner': ('user_id', bob['id'])}[failure]
        store.connect().execute(f'UPDATE agent_delegations SET {column}=? WHERE id=?', (value, a['delegation_id']))
        store.connect().commit()
    assert connections.live(alice) is None
    assert connections.status(alice)['state'] == 'invalid'
    assert connections.live(bob)


def test_provisioning_never_adopts_existing_delegation_or_accepts_other_proof(personal):
    store, connections, alice, bob = personal
    old, _ = store.create_agent_delegation(workspace_id=alice['workspace_id'], user_id=alice['id'], name='Old')
    a, token, proof = bind(connections, alice)
    b, _, other = bind(connections, bob)
    assert a['delegation_id'] != old['id']
    assert store.get_active_agent_delegation_principal(old['id'])['scopes'] == ['inteliscope:read']
    with pytest.raises(ValueError):
        connections.activate(alice['id'], other)
    with pytest.raises(ValueError):
        connections.activate(alice['id'], {**proof, 'manifest_sha256': digest(b)})
    with pytest.raises(BindingError):
        connections.prepare(alice['id'], a['mcp_url'])
    connections.retire(alice['id'])
    new, _, _ = bind(connections, alice)
    assert new['agent_id'] != a['agent_id']
    assert store.authenticate_agent_delegation(token) is None


def test_activation_rolls_back_when_prepared_skill_policy_is_stale(personal):
    store, connections, alice, _ = personal
    manifest = connections.prepare(alice['id'], 'http://127.0.0.1:8080/mcp')
    _, token = connections.export(alice['id'])
    proof = receipt(manifest, token, 'a' * 64)
    AgentSkillAccess(store).prepare(alice['workspace_id'], expected_revision=1, allowed_skill_keys=['reader'])

    with pytest.raises(AgentSkillPolicyError):
        connections.activate(alice['id'], proof)
    assert connections.row(alice['id'])['state'] == 'pending'


def test_two_agent_config_denies_shared_tools_and_rejects_drift(personal, tmp_path):
    _, connections, alice, bob = personal
    a, _, _ = bind(connections, alice)
    b, _, _ = bind(connections, bob)
    original = {'agents': {'entries': {'main': {}, 'legacy': {'tools': {'allow': ['read']}}}},
                'mcp': {'servers': {'inteliscope': {'url': 'https://example.test/mcp'}}}}
    config = configure(configure(original, a, tmp_path), b, tmp_path)
    verify_config(config, a, tmp_path)
    verify_config(config, b, tmp_path)
    assert original['agents']['entries']['main'] == {}
    for own, other in ((a, b), (b, a)):
        entry = config['agents']['entries'][own['agent_id']]
        assert all(tool.startswith(own['mcp_server'] + '__') for tool in entry['tools']['allow'])
        assert other['mcp_server'] + '__*' in entry['tools']['deny']
        assert own['mcp_server'] + '__*' in config['agents']['entries']['main']['tools']['deny']
        assert entry['workspace'] != config['agents']['entries'][other['agent_id']]['workspace']
    config['agents']['entries'][a['agent_id']]['tools']['allow'].append('exec')
    with pytest.raises(ValueError):
        verify_config(config, a, tmp_path)


def test_existing_database_requires_explicit_backed_up_empty_migration(personal, tmp_path):
    store, connections, alice, _ = personal
    store.connect().execute('DROP TABLE agent_connections')
    store.connect().execute('DELETE FROM schema_migrations WHERE version=37')
    store.connect().commit()
    store.initialize()
    assert connections.status(alice)['state'] == 'migration_required'
    assert migrate(tmp_path, apply=False)['status'] == 'migration_required'
    result = migrate(tmp_path, apply=True)
    assert result['bindings_created'] == 0 and result['integrity_check'] == 'ok'
    from pathlib import Path
    assert Path(result['backup']).stat().st_mode & 0o777 == 0o600
    with closing(sqlite3.connect(result['backup'])) as backup:
        assert not backup.execute('SELECT 1 FROM schema_migrations WHERE version=37').fetchone()
    assert migrate(tmp_path, apply=True)['status'] == 'already_migrated'
    assert connections.status(alice)['state'] == 'unconfigured'


def test_migration_conflict_and_live_worker_fail_closed(personal, tmp_path, monkeypatch):
    store, _, _, _ = personal
    store.connect().execute('DROP TABLE agent_connections')
    store.connect().execute('DELETE FROM schema_migrations WHERE version=37')
    store.connect().commit()
    monkeypatch.setattr('scripts.migrate_agent_connections_v37.active_workers_fail_closed', lambda path: ['worker'])
    with pytest.raises(RuntimeError):
        migrate(tmp_path, apply=True)
    monkeypatch.setattr('scripts.migrate_agent_connections_v37.active_workers_fail_closed', lambda path: [])
    store.connect().execute('CREATE TABLE agent_connections(user_id TEXT)')
    store.connect().commit()
    with pytest.raises(RuntimeError):
        migrate(tmp_path, apply=True)


def test_retired_personal_history_remains_owned_and_read_only(tmp_path):
    from src.services.openclaw_relay.ownership import Ownership
    from src.services.openclaw_relay.policy import request_params
    owner = Ownership(tmp_path, 'alice')
    owner.add('agent:old:history')
    assert request_params('chat.history', {'sessionKey': 'agent:old:history', 'agentId': 'old'}, owner, 'new') == {'sessionKey': 'agent:old:history'}
    with pytest.raises(PermissionError):
        request_params('chat.send', {'sessionKey': 'agent:old:history', 'agentId': 'old', 'message': 'no'}, owner, 'new')


def test_custom_shared_session_store_and_session_symlinks_are_rejected(personal, tmp_path):
    _, connections, alice, _ = personal
    manifest, _, _ = bind(connections, alice)
    with pytest.raises(ValueError, match='session.store'):
        configure({'session': {'store': '/shared/sessions.json'}}, manifest, tmp_path)
    config = configure({}, manifest, tmp_path)
    parent = tmp_path / 'agents' / manifest['agent_id']
    parent.mkdir(parents=True)
    (parent / 'sessions').symlink_to(tmp_path, target_is_directory=True)
    with pytest.raises(ValueError, match='symlink'):
        verify_config(config, manifest, tmp_path)
