"""Verify release proof against real migration data and evidence tampering."""

import json
import sqlite3
from contextlib import closing

import pytest

from scripts.bilibili_release_receipt import verify
from scripts.migrate_bilibili_actor_sources import migrate
from src.storage.service_store import ServiceStore
from tests.test_bilibili_actor_cutover import _source


@pytest.fixture
def evidence(tmp_path):
    data = tmp_path / 'data'
    store = ServiceStore(data)
    store.initialize()
    _source(store, '39627524')
    store.close()
    receipt = data / 'backups' / 'bilibili.json'
    revision = 'a' * 40
    result = migrate(data, apply=True, services_stopped=True,
                     release_revision=revision, release_receipt=receipt)
    return tmp_path, receipt, revision, result['backup_path']


def test_migration_receipt_is_private_and_revision_bound(evidence):
    base, receipt, revision, backup = evidence
    assert verify(base, receipt, revision) == backup
    assert receipt.stat().st_mode & 0o777 == 0o600
    assert len(json.loads(receipt.read_text())['bindings']) == 1
    with pytest.raises(ValueError, match='bound'):
        verify(base, receipt, 'b' * 40)


@pytest.mark.parametrize('damage', ['marker', 'binding', 'backup', 'symlink', 'escape'])
def test_receipt_rejects_drift_or_unsafe_evidence(evidence, damage, tmp_path):
    base, receipt, revision, backup = evidence
    if damage in {'marker', 'binding'}:
        with closing(sqlite3.connect(base / 'data' / 'service.db')) as conn:
            conn.execute('DELETE FROM schema_migrations WHERE version=30' if damage == 'marker'
                         else "UPDATE actor_source_bindings_v2 SET target_fingerprint='changed'")
            conn.commit()
    elif damage == 'backup':
        from pathlib import Path
        Path(backup).chmod(0o644)
    elif damage == 'symlink':
        target = receipt.with_suffix('.original')
        receipt.rename(target)
        receipt.symlink_to(target)
    else:
        contents = json.loads(receipt.read_text())
        contents['backup']['path'] = str(tmp_path / 'elsewhere.db')
        receipt.write_text(json.dumps(contents))
    with pytest.raises(ValueError):
        verify(base, receipt, revision)


def test_invalid_receipt_request_blocks_data_changes(tmp_path):
    store = ServiceStore(tmp_path)
    store.initialize()
    source = _source(store, '39627524')
    store.close()
    with pytest.raises(ValueError, match='managed receipt'):
        migrate(tmp_path, apply=True, services_stopped=True,
                release_revision='invalid', release_receipt=tmp_path / 'outside.json')
    store = ServiceStore(tmp_path)
    assert store.get_source(source)['enabled'] is True
    store.close()
