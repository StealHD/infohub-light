"""A reopened existing database requires explicit global 45 with no preview backfill."""
from test_information_automation_rules import context  # noqa: F401
from src.storage.information_recovery_schema import TABLES, ready, apply_migration
from src.storage.service_store import ServiceStore


def test_explicit_migration_preserves_existing_records(context):
    store=context[0];conn=store.connect()
    for name in reversed(TABLES): conn.execute(f'DROP TABLE {name}')
    conn.execute('DELETE FROM schema_migrations WHERE version=45');conn.commit()
    reopened=ServiceStore(store.data_dir);reopened.initialize()
    assert not ready(reopened.connect())
    before=reopened.connect().execute('SELECT count(*) FROM information_previews').fetchone()[0]
    apply_migration(reopened.connect());apply_migration(reopened.connect())
    assert ready(reopened.connect())
    assert reopened.connect().execute('SELECT count(*) FROM information_previews').fetchone()[0]==before
    assert reopened.connect().execute('SELECT count(*) FROM information_preview_confirmations').fetchone()[0]==0
    reopened.close()
