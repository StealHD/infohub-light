"""Standalone global 49 release evidence; safe to stream to a remote Python stdin."""

import argparse
import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

MARKER = {'version': 49, 'name': 'content_translations', 'checksum': 'content-translations-v1'}
SCHEMA = 'content_translations_v49_release_receipt_v1'
COLUMNS = {
    'content_translations': {'cache_key', 'workspace_id', 'user_id', 'article_id', 'job_id',
                             'translated_text', 'scope', 'source_truncated', 'created_at', 'expires_at'},
    'content_translation_requests': {'workspace_id', 'user_id', 'request_id', 'cache_key', 'job_id'},
}


def private_file(path, directory):
    if path.parent != directory or path.resolve().parent != directory.resolve():
        raise ValueError('migration evidence escapes the managed backup directory')
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError('migration evidence must be a private regular file')


def database_ready(database):
    with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=30)) as conn:
        marker = conn.execute('SELECT name,checksum FROM schema_migrations WHERE version=49').fetchone()
        if marker != (MARKER['name'], MARKER['checksum']):
            raise ValueError('production global 49 marker is invalid')
        for table, columns in COLUMNS.items():
            if {row[1] for row in conn.execute(f'PRAGMA table_info({table})')} != columns:
                raise ValueError('production translation table shape is invalid')
        if not conn.execute("SELECT 1 FROM sqlite_master WHERE type='index' AND name='content_translation_expiry'").fetchone():
            raise ValueError('translation expiry index is missing')


def verify(base, receipt_path, revision):
    directory = base / 'data' / 'backups'
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('full release revision required')
    private_file(receipt_path, directory)
    receipt = json.loads(receipt_path.read_text())
    if any(receipt.get(key) != value for key, value in {
        'schema': SCHEMA, 'migration': 'content_translations_v49',
        'marker': MARKER, 'release_revision': revision,
    }.items()):
        raise ValueError('translation receipt is not bound to this release')
    backup = receipt.get('backup', {})
    if backup.get('mode') != '0o600':
        raise ValueError('invalid backup metadata')
    backup_path = Path(backup.get('path', ''))
    private_file(backup_path, directory)
    # Full integrity/FK checks belong to the stopped-service migration only.
    database_ready(base / 'data' / 'service.db')
    return str(backup_path)


def write(base, receipt_path, revision, backup):
    directory = base / 'data' / 'backups'
    if not re.fullmatch('[0-9a-f]{40}', revision) or receipt_path.parent != directory:
        raise ValueError('managed receipt path and full release revision required')
    private_file(backup, directory)
    database = base / 'data' / 'service.db'
    database_ready(database)
    with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as conn:
        if conn.execute("SELECT 1 FROM fetch_jobs WHERE status IN ('queued','running') LIMIT 1").fetchone():
            raise ValueError('drain jobs before recording migration evidence')
        for (heartbeat,) in conn.execute('SELECT heartbeat_at FROM worker_heartbeats'):
            timestamp = datetime.fromisoformat(heartbeat.replace('Z', '+00:00'))
            timestamp = timestamp.replace(tzinfo=timestamp.tzinfo or timezone.utc)
            if (datetime.now(timezone.utc) - timestamp).total_seconds() < 35:
                raise ValueError('stop Worker before recording migration evidence')
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('migrated database integrity failed')
    with closing(sqlite3.connect(f'file:{backup}?mode=ro', uri=True)) as conn:
        if conn.execute('SELECT 1 FROM schema_migrations WHERE version=49').fetchone():
            raise ValueError('backup must precede global 49')
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('backup integrity failed')
    receipt = {'schema': SCHEMA, 'migration': 'content_translations_v49', 'marker': MARKER,
               'release_revision': revision, 'backup': {'path': str(backup), 'mode': '0o600'}}
    descriptor = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(receipt, handle, sort_keys=True)
        handle.write('\n')
    return verify(base, receipt_path, revision)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['verify', 'write'])
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    parser.add_argument('--backup', type=Path)
    args = parser.parse_args()
    if args.command == 'write':
        if not args.backup:
            parser.error('write requires --backup')
        print(write(args.base, args.receipt, args.revision, args.backup))
    else:
        print(verify(args.base, args.receipt, args.revision))


if __name__ == '__main__':
    main()
