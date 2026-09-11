"""User scope, version fencing and explicit reminder activation."""
from types import SimpleNamespace
import pytest

from src.storage.service_store import ServiceStore
from src.storage.information_automation_schema import apply_migration
from src.services.agent_connections.service import AgentConnections
from src.services.agent_connections.manifest import receipt
from src.services.secret_store import SecretStore
from src.services.user_content_store import UserContentStore
from src.services.information_automations.rules import InformationRules, RuleConfig, RuleError


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv('HORIZON_AUTH_USER', 'owner')
    monkeypatch.setenv('HORIZON_AUTH_PASSWORD', 'test-password')
    store = ServiceStore(tmp_path)
    store.initialize()
    apply_migration(store.connect())
    alice = store.get_user_by_username('owner')
    bob = store.create_user(workspace_id=alice['workspace_id'], username='bob', password='test-password')
    viewer = store.create_user(workspace_id=alice['workspace_id'], username='viewer', role='viewer', password='test-password')
    bindings = AgentConnections(store, SecretStore(tmp_path))
    for user in (alice, bob):
        manifest = bindings.prepare(user['id'], 'http://127.0.0.1:8080/mcp')
        _, token = bindings.export(user['id'])
        bindings.activate(user['id'], receipt(manifest, token, 'a' * 64))
    source = store.create_source(workspace_id=alice['workspace_id'], scope='workspace', owner_user_id=alice['id'],
                                 source_type='rss', display_name='Test', config={'url': 'https://example.com/feed'})
    store.create_subscription(user_id=alice['id'], source_id=source)
    target = {'id': 'test-target', 'config_generation': 1, 'activation_generation': 1}
    # No transport exists in this fixture. The target availability seam tests
    # confirmation logic without sending or enabling an actual destination.
    targets = SimpleNamespace(list_public_targets=lambda **kw: {'targets': [target] if kw['user_id'] == alice['id'] else []},
                              target_is_available=lambda _: True)
    monkeypatch.setattr(store, 'get_notification_target', lambda **_: target)
    rules = InformationRules(store, targets)
    from src.services.information_automations.connector_auth import provision, authenticate
    from src.services.information_automations.model_catalog import Capabilities, sync_catalog
    _, token = provision(store, SecretStore(tmp_path), alice['id'])
    store.test_machine_token = token
    sync_catalog(store, authenticate(store, token), Capabilities(protocol_version=2, execution_mode='full', models=[{'id':'test/model','name':'Test','thinking_levels':['low']}]))
    config = RuleConfig(name='AI 提醒', source_ids=[source], target_id='test-target', requirement='Find AI research; exclude advertising.',
                        model={'id':'test/model'}, trigger={'kind':'interval','interval_seconds':60})
    yield store, rules, bindings, alice, bob, viewer, config, target
    store.close()


def test_draft_confirm_versions_pause_and_no_reenable_replay(context):
    store, rules, _, alice, _, _, config, _ = context
    draft = rules.save(alice['id'], config)
    assert draft['state'] == 'draft' and draft['version'] == 1
    active = rules.transition(alice['id'], draft['id'], 1, 'enable')
    assert active['state'] == 'active'
    assert rules.transition(alice['id'], draft['id'], 1, 'enable')['confirmed_at'] == active['confirmed_at']
    changed = rules.save(alice['id'], config.model_copy(update={'name': 'edited'}), rule_id=draft['id'], expected_version=1)
    assert changed['state'] == 'paused' and changed['version'] == 2 and changed['confirmed_at'] is None
    with pytest.raises(RuleError, match='刷新'):
        rules.transition(alice['id'], draft['id'], 1, 'enable')
    conn = store.connect()
    conn.execute('''INSERT INTO information_events(workspace_id,user_id,article_id,source_ids_json,created_at)
        VALUES(?,?,'paused-event','[]','2026-01-01')''', (alice['workspace_id'], alice['id']))
    conn.commit()
    rules.transition(alice['id'], draft['id'], 2, 'enable')
    assert rules.row(alice, draft['id'])['cursor'] == 1
    assert conn.execute('SELECT count(*) FROM information_rule_versions').fetchone()[0] == 2


def test_cross_user_source_target_binding_and_viewer_fail_closed(context):
    _, rules, bindings, alice, bob, viewer, config, _ = context
    draft = rules.save(alice['id'], config)
    with pytest.raises(RuleError) as missing:
        rules.get(bob['id'], draft['id'])
    assert missing.value.status == 404
    assert rules.list(bob['id'])['items'] == []
    with pytest.raises(RuleError, match='订阅'):
        rules.save(bob['id'], config)
    with pytest.raises(RuleError, match='通知服务'):
        rules.save(bob['id'], config.model_copy(update={'source_ids': []}))
    with pytest.raises(RuleError, match='只允许查看'):
        rules.save(viewer['id'], config)
    bindings.revoke(alice['id'])
    with pytest.raises(RuleError, match='Agent'):
        rules.transition(alice['id'], draft['id'], 1, 'enable')


def test_test_is_readonly_no_cursor_or_delivery_and_user_content_only(context):
    store, rules, _, alice, bob, _, config, _ = context
    UserContentStore(store).upsert_items(workspace_id=alice['workspace_id'], user_id=alice['id'], seen_at='2026-09-08T00:00:00+00:00',
        items=[{'id': 'article', 'source_id': config.source_ids[0], 'title': 'ＡＩ research', 'content': 'AI news'}])
    store.connect().commit()
    draft = rules.save(alice['id'], config)
    before = rules.row(alice, draft['id'])
    result = rules.test(alice['id'], draft['id'], 1, ['article'])
    assert result['status'] == 'pending' and result['results'] == []
    assert not result['sends_notification'] and not result['advances_cursor']
    assert rules.row(alice, draft['id']) == before
    assert store.connect().execute('SELECT count(*) FROM information_runs').fetchone()[0] == 0
    with pytest.raises(RuleError):
        rules.test(bob['id'], draft['id'], 1, ['article'])


def test_archived_rule_can_restore_to_unconfirmed_draft(context):
    _, rules, _, alice, _, _, _, _ = context
    draft = rules.save(alice['id'], RuleConfig(name='未完成草稿'))
    with pytest.raises(RuleError, match='补齐'):
        rules.transition(alice['id'], draft['id'], 1, 'enable')
    archived = rules.transition(alice['id'], draft['id'], 1, 'archive')
    assert archived['state'] == 'archived'
    with pytest.raises(RuleError):
        rules.transition(alice['id'], draft['id'], 1, 'enable')
    restored = rules.transition(alice['id'], draft['id'], 1, 'restore')
    assert restored['state'] == 'draft'
    assert restored['confirmed_at'] is None
    with pytest.raises(RuleError, match='已归档'):
        rules.transition(alice['id'], draft['id'], 1, 'restore')
