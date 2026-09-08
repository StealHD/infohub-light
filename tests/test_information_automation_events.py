"""No historical replay and no event survives a failed Feed transaction."""
import json
import pytest

from src.storage.service_store import ServiceStore
from src.storage.information_automation_schema import apply_migration, ready
from src.services.information_automations.events import record_events
from src.services.information_automations.config import RuleConfig


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv('HORIZON_AUTH_USER', 'owner')
    monkeypatch.setenv('HORIZON_AUTH_PASSWORD', 'test-password')
    value = ServiceStore(tmp_path)
    value.initialize()
    apply_migration(value.connect())
    yield value
    value.close()


def publish(store, user, items, sources=('s1',), *, commit=True):
    conn = store.connect()
    conn.execute('BEGIN IMMEDIATE')
    count = record_events(conn, workspace_id=user['workspace_id'], user_id=user['id'],
                          items=items, successful_sources=sources)
    if commit:
        conn.commit()
    else:
        conn.rollback()
    return count


def item(name, sources=('s1',)):
    return {'id': name, 'source_ids': list(sources), 'title': name}


def test_baseline_revision_restart_and_fanout(store):
    alice = store.get_user_by_username('owner')
    bob = store.create_user(workspace_id=alice['workspace_id'], username='bob', password='test-password')
    for user in (alice, bob):
        assert publish(store, user, [item('old')]) == 0
        assert publish(store, user, [item('old'), item('new')]) == 1
        assert publish(store, user, [{**item('new'), 'title': 'revised'}]) == 0
    restarted = ServiceStore(store.data_dir)
    try:
        assert publish(restarted, alice, [item('new')]) == 0
        events = restarted.connect().execute('SELECT user_id,article_id FROM information_events').fetchall()
        assert {(r['user_id'], r['article_id']) for r in events} == {(alice['id'], 'new'), (bob['id'], 'new')}
    finally:
        restarted.close()


def test_empty_first_collection_rollback_and_cross_source_duplicate(store):
    user = store.get_user_by_username('owner')
    assert publish(store, user, []) == 0
    assert publish(store, user, [item('new')], commit=False) == 1
    assert not store.connect().execute('SELECT 1 FROM information_events').fetchone()
    assert publish(store, user, [item('new')]) == 1
    assert publish(store, user, [item('new', ('s2',))], ('s2',)) == 0
    assert publish(store, user, [item('both', ('s1', 's2'))], ('s1', 's2')) == 1
    row = store.connect().execute("SELECT source_ids_json FROM information_events WHERE article_id='both'").fetchone()
    assert json.loads(row[0]) == ['s1', 's2']


def test_schema_is_explicit_idempotent_and_fail_closed(store):
    conn = store.connect()
    assert ready(conn)
    assert apply_migration(conn) == {'rules_created': 0}
    assert conn.execute('SELECT count(*) FROM information_rules').fetchone()[0] == 0
    conn.execute('DROP INDEX information_events_owner')
    conn.commit()
    assert not ready(conn)
    with pytest.raises(RuntimeError, match='conflict'):
        apply_migration(conn)


def test_durable_url_identity_deduplicates_changed_source_id_without_losing_query(store):
    user = store.get_user_by_username('owner')
    assert publish(store, user, [{**item('old'), 'url': 'https://www.example.com/story/?id=1'}]) == 0
    assert publish(store, user, [{**item('new-source-id'), 'url': 'https://example.com/story?id=1#section'}]) == 0
    assert publish(store, user, [{**item('different-story'), 'url': 'https://example.com/story?id=2'}]) == 1
    assert publish(store, user, [{**item('new-source-id'), 'url': 'https://example.com/changed'}]) == 0


def test_legacy_keyword_conditions_become_one_requirement():
    value = RuleConfig(name='legacy', mode='keyword', conditions={'all':['AI'],'any':['research'],'exclude':['ad']})
    assert value.schema_version == 2
    assert 'AI' in value.requirement and 'research' in value.requirement and 'ad' in value.requirement
    assert 'conditions' not in value.model_dump() and 'mode' not in value.model_dump()
