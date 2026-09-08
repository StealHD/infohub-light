"""Explicit additive migration preserves historical content without scheduling it."""
import sqlite3
from contextlib import closing

from test_information_automation_events import store  # noqa: F401
from src.storage.information_automation_schema import TABLES, ready
from src.services.user_content_store import UserContentStore
from scripts.migrate_information_automations_v38 import migrate


def test_migration_backup_no_replay_and_existing_store_does_not_autoupgrade(store):
    user = store.get_user_by_username('owner')
    UserContentStore(store).upsert_items(workspace_id=user['workspace_id'], user_id=user['id'],
        items=[{'id': 'historical', 'title': 'Old AI news'}], seen_at='2026-09-01T00:00:00+00:00')
    conn = store.connect()
    for table in reversed(TABLES):
        conn.execute('DROP TABLE ' + table)
    conn.execute('DELETE FROM schema_migrations WHERE version=38')
    conn.commit()
    store.initialize()
    assert not ready(store.connect())
    assert migrate(store.data_dir, apply=False)['status'] == 'migration_required'
    result = migrate(store.data_dir, apply=True)
    assert result['status'] == 'applied' and result['integrity_check'] == 'ok'
    with closing(sqlite3.connect(result['backup'])) as backup:
        assert backup.execute('SELECT count(*) FROM user_content_items').fetchone()[0] == 1
        assert not backup.execute('SELECT 1 FROM schema_migrations WHERE version=38').fetchone()
    assert ready(store.connect())
    assert store.connect().execute('SELECT article_id FROM information_seen_items').fetchone()[0] == 'historical'
    assert store.connect().execute('SELECT count(*) FROM information_events').fetchone()[0] == 0
    assert store.connect().execute('SELECT count(*) FROM information_rules').fetchone()[0] == 0
    assert migrate(store.data_dir, apply=True)['status'] == 'already_migrated'
