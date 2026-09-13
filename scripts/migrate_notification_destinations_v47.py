#!/usr/bin/env python3
"""Offline global 47 installer. Preview is read-only; apply requires stopped services."""

import argparse
import fcntl
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.actorops_migration_safety import active_workers_fail_closed
from scripts.migrate_apify_actor_ops_v15 import _backup_database
from src.storage.notification_extension_schema import apply_migration, prerequisite_ready, ready


def _integrity(conn):
    if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok':
        raise ValueError('Database integrity check failed')
    if conn.execute('PRAGMA foreign_key_check').fetchone():
        raise ValueError('Database foreign keys are invalid')


def preview(data_dir):
    database = Path(data_dir) / 'service.db'
    with closing(sqlite3.connect(database.as_uri() + '?mode=ro', uri=True)) as conn:
        _integrity(conn)
        if ready(conn):
            return {'status': 'already_migrated'}
        if not prerequisite_ready(conn):
            raise ValueError('global 46 required')
    return {'status': 'blocked' if active_workers_fail_closed(database) else 'migration_required'}


def migrate(data_dir, *, apply=False, services_stopped=False, backup_dir=None):
    data_dir = Path(data_dir).resolve()
    result = preview(data_dir)
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
        raw_backup = _backup_database(database, Path(backup_dir).resolve() if backup_dir else data_dir / 'backups')
        backup = raw_backup.with_name(raw_backup.name.replace(
            'service-apify-actor-ops-v15-', 'service-notification-destinations-v47-', 1))
        raw_backup.rename(backup)
        os.chmod(backup, 0o600)
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
        return {'status': 'applied', 'backup': str(backup), 'backup_mode': '0o600',
                'integrity_check': 'ok', 'foreign_key_violations': 0}
    finally:
        os.close(lock)


if __name__ == '__main__':
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--backup-dir', type=Path)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--services-stopped', action='store_true')
    args = parser.parse_args()
    print(json.dumps(migrate(args.data_dir, apply=args.apply, services_stopped=args.services_stopped,
                             backup_dir=args.backup_dir)))
