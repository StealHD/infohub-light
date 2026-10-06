"""Verify additive migration evidence without accessing real runtime data."""

import json
import sqlite3
from contextlib import closing

import pytest

from scripts.content_translation_release_receipt import COLUMNS, verify, write
from scripts.migrate_content_translations_v49 import migrate
from src.storage.content_translation_schema import COLUMNS as STORAGE_COLUMNS
from src.storage.service_store import ServiceStore


@pytest.fixture
def evidence(tmp_path):
    data = tmp_path / 'data'
    store = ServiceStore(data)
    store.initialize()
    conn = store.connect()
    conn.execute('DROP TABLE content_translation_requests')
    conn.execute('DROP TABLE content_translations')
    conn.execute('DELETE FROM schema_migrations WHERE version=49')
    conn.commit()
    store.close()
    result = migrate(data, data / 'backups')
    backup = data / 'backups' / result['backup'].split('/')[-1]
    receipt = data / 'backups' / 'translation.json'
    revision = 'a' * 40
    write(tmp_path, receipt, revision, backup)
    return tmp_path, receipt, revision, backup


def test_receipt_matches_storage_and_is_bound_to_revision(evidence):
    base, receipt, revision, backup = evidence
    assert COLUMNS == STORAGE_COLUMNS
    assert verify(base, receipt, revision) == str(backup)
    assert receipt.stat().st_mode & 0o777 == 0o600
    with pytest.raises(ValueError, match='bound'):
        verify(base, receipt, 'b' * 40)
    with pytest.raises(FileExistsError):
        write(base, receipt, revision, backup)


@pytest.mark.parametrize('damage', ['marker', 'table', 'index', 'backup', 'symlink', 'escape'])
def test_receipt_rejects_tampered_schema_or_evidence(evidence, damage, tmp_path):
    base, receipt, revision, backup = evidence
    if damage in {'marker', 'table', 'index'}:
        with closing(sqlite3.connect(base / 'data' / 'service.db')) as conn:
            conn.execute({
                'marker': 'DELETE FROM schema_migrations WHERE version=49',
                'table': 'ALTER TABLE content_translations ADD COLUMN wrong TEXT',
                'index': 'DROP INDEX content_translation_expiry',
            }[damage])
            conn.commit()
    elif damage == 'backup':
        backup.chmod(0o644)
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
