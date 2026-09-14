"""Global 47 requires an explicit offline apply for existing databases."""

import json
import sqlite3
from contextlib import closing

import pytest

from scripts import migrate_notification_destinations_v47 as migration
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
    receipt = tmp_path / 'backups' / 'release-v47.json'
    result = migrate(
        tmp_path, apply=True, services_stopped=True,
        release_receipt=receipt, release_revision='a' * 40,
    )
    assert result['status'] == 'applied'
    assert result['release_receipt'] == str(receipt)
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert json.loads(receipt.read_text(encoding='utf-8')) == {
        'schema': 'notification_destinations_v47_release_receipt_v1',
        'migration': 'notification_destinations_v47',
        'release_revision': 'a' * 40,
        'backup': {'path': result['backup'], 'mode': '0o600'},
        'marker': {
            'version': 47,
            'name': 'notification_destinations',
            'checksum': 'notification-destinations-v1',
        },
    }
    with closing(sqlite3.connect(tmp_path / 'service.db')) as migrated:
        assert ready(migrated)
        assert migrated.execute('PRAGMA foreign_key_check').fetchone() is None
    assert migrate(tmp_path)['status'] == 'already_migrated'
    database_inode = (tmp_path / 'service.db').stat().st_ino
    reissued = tmp_path / 'backups' / 'release-v47-descendant.json'
    with pytest.raises(ValueError, match='source migration receipt is invalid'):
        migration.reissue_release_receipt(
            tmp_path, source_receipt=receipt, source_revision='c' * 40,
            release_receipt=reissued, release_revision='b' * 40,
        )
    result = migration.reissue_release_receipt(
        tmp_path, source_receipt=receipt, source_revision='a' * 40,
        release_receipt=reissued, release_revision='b' * 40,
    )
    assert result['status'] == 'reissued'
    assert result['backup'] == json.loads(receipt.read_text())['backup']['path']
    assert json.loads(reissued.read_text())['reissued_from'] == str(receipt)
    assert json.loads(reissued.read_text())['release_revision'] == 'b' * 40
    assert reissued.stat().st_mode & 0o777 == 0o600
    assert (tmp_path / 'service.db').stat().st_ino == database_inode


def test_release_receipt_failure_restores_the_existing_database(tmp_path, monkeypatch):
    monkeypatch.setenv('HORIZON_AUTH_USER', 'owner')
    monkeypatch.setenv('HORIZON_AUTH_PASSWORD', 'test-password')
    store = ServiceStore(tmp_path)
    store.initialize()
    conn = store.connect()
    conn.execute('DELETE FROM schema_migrations WHERE version=47')
    for table in ('information_preview_notifications', 'openclaw_notification_services', 'notification_target_topics'):
        conn.execute(f'DROP TABLE {table}')
    conn.commit()
    account_count = conn.execute('SELECT COUNT(*) FROM users').fetchone()[0]
    store.close()

    def fail_receipt(*_args, **_kwargs):
        raise OSError('receipt write failed')

    monkeypatch.setattr(migration, '_write_release_receipt', fail_receipt)
    with pytest.raises(OSError, match='receipt write failed'):
        migrate(tmp_path, apply=True, services_stopped=True,
                release_receipt=tmp_path / 'backups' / 'release-v47.json',
                release_revision='a' * 40)

    with closing(sqlite3.connect(tmp_path / 'service.db')) as restored:
        assert not ready(restored)
        assert restored.execute('SELECT COUNT(*) FROM users').fetchone()[0] == account_count
        assert restored.execute('PRAGMA integrity_check').fetchone()[0] == 'ok'
    assert not (tmp_path / 'backups' / 'release-v47.json').exists()
