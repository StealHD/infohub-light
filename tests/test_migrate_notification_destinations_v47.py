"""Global 47 requires an explicit offline apply for existing databases."""

import sqlite3
from contextlib import closing

import pytest

from scripts.migrate_notification_destinations_v47 import migrate
from src.storage.notification_extension_schema import ready
from src.storage.service_store import ServiceStore


def test_preview_apply_backup_and_existing_data(tmp_path, monkeypatch):
    monkeypatch.setenv('HORIZON_AUTH_USER', 'owner')
    monkeypatch.setenv('HORIZON_AUTH_PASSWORD', 'test-password')
    store = ServiceStore(tmp_path)
    store.initialize()
    assert ready(store.connect())
    conn = store.connect()
    conn.execute('DELETE FROM schema_migrations WHERE version=47')
    for table in ('information_preview_notifications', 'openclaw_notification_services', 'notification_target_topics'):
        conn.execute(f'DROP TABLE {table}')
    conn.commit()
    store.close()
    assert migrate(tmp_path)['status'] == 'migration_required'
    with pytest.raises(ValueError, match='Stop API'):
        migrate(tmp_path, apply=True)
    result = migrate(tmp_path, apply=True, services_stopped=True)
    assert result['status'] == 'applied'
    with closing(sqlite3.connect(tmp_path / 'service.db')) as migrated:
        assert ready(migrated)
        assert migrated.execute('PRAGMA foreign_key_check').fetchone() is None
    assert migrate(tmp_path)['status'] == 'already_migrated'
