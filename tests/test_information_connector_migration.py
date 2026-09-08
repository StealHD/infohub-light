"""Global 39 requires explicit backup and never grants existing users credentials."""
import sqlite3
from contextlib import closing
from test_information_automation_events import store  # noqa: F401
from src.storage.information_connector_schema import TABLES, ready
from scripts.migrate_information_connector_v39 import migrate


def test_explicit_connector_backup_and_no_automatic_grants(store):
    conn = store.connect()
    for table in reversed(TABLES): conn.execute('DROP TABLE ' + table)
    conn.execute('DELETE FROM schema_migrations WHERE version=39'); conn.commit()
    store.initialize()
    assert not ready(conn)
    assert migrate(store.data_dir, apply=False)['status'] == 'migration_required'
    result = migrate(store.data_dir, apply=True)
    assert result['status'] == 'applied'
    with closing(sqlite3.connect(result['backup'])) as backup:
        assert not backup.execute('SELECT 1 FROM schema_migrations WHERE version=39').fetchone()
        assert backup.execute('SELECT count(*) FROM users').fetchone()[0] == conn.execute('SELECT count(*) FROM users').fetchone()[0]
    assert ready(conn) and conn.execute('SELECT count(*) FROM information_connectors').fetchone()[0] == 0
    assert migrate(store.data_dir, apply=True)['status'] == 'already_migrated'
