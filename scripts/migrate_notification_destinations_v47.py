#!/usr/bin/env python3
"""Offline global 47 installer. Preview is read-only; apply requires stopped services."""

import argparse
import fcntl
import json
import os
import sqlite3
import sys
from contextlib import closing
from datetime import datetime, timezone
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.actorops_migration_safety import active_workers_fail_closed
from src.storage.notification_extension_schema import apply_migration, prerequisite_ready, ready


RELEASE_RECEIPT_SCHEMA = 'notification_destinations_v47_release_receipt_v1'


def _integrity(conn):
    if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('Database integrity check failed')
    if conn.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('Database foreign keys are invalid')


def _backup_database(database, backup_dir):
    backup_dir.mkdir(parents=True, exist_ok=True)
    backup = backup_dir / (
        'service-notification-destinations-v47-'
        f"{datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ')}.db"
    )
    descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(descriptor)
    source = destination = None
    succeeded = False
    try:
        source = sqlite3.connect(f'file:{database}?mode=ro', uri=True)
        destination = sqlite3.connect(backup)
        source.backup(destination)
        succeeded = True
    finally:
        if source is not None:
            source.close()
        if destination is not None:
            destination.close()
        if not succeeded:
            backup.unlink(missing_ok=True)
    os.chmod(backup, 0o600)
    return backup


def _restore_database(database, backup):
    with closing(sqlite3.connect(f'file:{backup}?mode=ro', uri=True)) as source:
        with closing(sqlite3.connect(database)) as destination:
            source.backup(destination)
            _integrity(destination)
            if ready(destination):
                raise ValueError('Restored database still has the v47 marker')
    os.chmod(database, 0o600)


def _write_release_receipt(receipt_path, *, release_revision, backup):
    receipt_path = Path(receipt_path)
    backup = Path(backup)
    if not receipt_path.is_absolute() or not backup.is_absolute():
        raise ValueError('release receipt and backup paths must be absolute')
    if len(release_revision) != 40 or any(char not in '0123456789abcdef' for char in release_revision):
        raise ValueError('release revision must be a full lowercase Git SHA')
    if receipt_path.exists() or receipt_path.is_symlink():
        raise ValueError('release receipt already exists or is unsafe')
    if backup.is_symlink() or not backup.is_file() or (backup.stat().st_mode & 0o777) != 0o600:
        raise ValueError('migration backup is unavailable or has unsafe permissions')
    receipt = {
        'schema': RELEASE_RECEIPT_SCHEMA,
        'migration': 'notification_destinations_v47',
        'release_revision': release_revision,
        'backup': {'path': str(backup), 'mode': '0o600'},
        'marker': {
            'version': 47,
            'name': 'notification_destinations',
            'checksum': 'notification-destinations-v1',
        },
    }
    flags = os.O_WRONLY | os.O_CREAT | os.O_EXCL
    if hasattr(os, 'O_NOFOLLOW'):
        flags |= os.O_NOFOLLOW
    descriptor = os.open(receipt_path, flags, 0o600)
    try:
        with os.fdopen(descriptor, 'w', encoding='utf-8') as handle:
            json.dump(receipt, handle, sort_keys=True, separators=(',', ':'))
            handle.write('\n')
        os.chmod(receipt_path, 0o600)
    except BaseException:
        receipt_path.unlink(missing_ok=True)
        raise
    return str(receipt_path)


def preview(data_dir):
    database = Path(data_dir) / 'service.db'
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as conn:
        _integrity(conn)
        if ready(conn):
            return {'status': 'already_migrated'}
        if not prerequisite_ready(conn):
            raise ValueError('global 46 required')
    return {'status': 'blocked' if active_workers_fail_closed(database) else 'migration_required'}


def migrate(data_dir, *, apply=False, services_stopped=False, backup_dir=None,
            release_receipt=None, release_revision=None):
    if (release_receipt is None) != (release_revision is None):
        raise ValueError('release receipt and release revision must be supplied together')
    if release_receipt is not None and not apply:
        raise ValueError('release receipt requires --apply')
    data_dir = Path(data_dir).resolve()
    result = preview(data_dir)
    if result['status'] == 'already_migrated' and release_receipt is not None:
        raise ValueError('cannot issue a release receipt for an already migrated database')
    if not apply or result['status'] == 'already_migrated':
        return result
    if not services_stopped or result['status'] == 'blocked':
        raise ValueError('Stop API and Worker, then acknowledge --services-stopped')
    lock = os.open(data_dir / '.notification-destinations-v47.lock', os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        if preview(data_dir)['status'] != 'migration_required':
            raise ValueError('Migration precondition changed')
        database = data_dir / 'service.db'
        backup = _backup_database(
            database, Path(backup_dir).resolve() if backup_dir else data_dir / 'backups',
        )
        with closing(sqlite3.connect(backup.as_uri() + '?mode=ro', uri=True)) as conn:
            _integrity(conn)
            if ready(conn):
                raise ValueError('Backup is not a pre-migration database')
        if active_workers_fail_closed(database):
            raise ValueError('Stop API and Worker before migration')
        with closing(sqlite3.connect(database)) as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            apply_migration(conn)
            _integrity(conn)
        response = {'status': 'applied', 'backup': str(backup), 'backup_mode': '0o600',
                    'integrity_check': 'ok', 'foreign_key_violations': 0}
        if release_receipt is not None:
            try:
                response['release_receipt'] = _write_release_receipt(
                    release_receipt, release_revision=release_revision, backup=backup,
                )
            except BaseException:
                _restore_database(database, backup)
                raise
        return response
    finally:
        os.close(lock)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--services-stopped', action='store_true')
    parser.add_argument('--release-receipt', type=Path)
    parser.add_argument('--release-revision')
    args = parser.parse_args()
    print(json.dumps(migrate(args.data_dir, apply=args.apply, services_stopped=args.services_stopped,
                             backup_dir=args.backup_dir, release_receipt=args.release_receipt,
                             release_revision=args.release_revision)))
