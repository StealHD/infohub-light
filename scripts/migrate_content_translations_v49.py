#!/usr/bin/env python3
"""Offline, additive Feed translation migration. Default mode only previews."""

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
from src.storage.content_translation_schema import apply_migration, prerequisite_ready, ready


def preview(data_dir):
    database = Path(data_dir) / 'service.db'
    with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as conn:
        installed = ready(conn)
        if not installed and not prerequisite_ready(conn):
            raise ValueError('valid global 48 required')
        if not installed and conn.execute('SELECT 1 FROM schema_migrations WHERE version=49').fetchone():
            raise ValueError('invalid global 49 marker or schema')
        jobs = conn.execute("SELECT COUNT(*) FROM fetch_jobs WHERE status IN ('queued','running')").fetchone()[0]
    workers = active_workers_fail_closed(database)
    return {'status': 'ready' if installed else 'blocked' if workers or jobs else 'migration_required',
            'active_workers': len(workers), 'active_jobs': jobs}


def migrate(data_dir, backup_dir):
    data_dir = Path(data_dir)
    database = data_dir / 'service.db'
    with open(data_dir / '.content-translation-v49.lock', 'a') as lock:
        fcntl.flock(lock, fcntl.LOCK_EX | fcntl.LOCK_NB)
        state = preview(data_dir)
        if state['status'] == 'ready':
            return state
        if state['status'] == 'blocked':
            raise ValueError('drain the job queue and stop API and Worker before applying migration')
        backup_dir = Path(backup_dir)
        backup_dir.mkdir(parents=True, exist_ok=True)
        backup = backup_dir / ('service-translation-v49-' + datetime.now(timezone.utc).strftime('%Y%m%dT%H%M%S%fZ') + '.db')
        descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
        os.close(descriptor)
        with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True)) as source:
            with closing(sqlite3.connect(backup)) as destination:
                source.backup(destination)
        with closing(sqlite3.connect(database)) as conn:
            conn.execute('PRAGMA foreign_keys=ON')
            if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchone():
                raise ValueError('database integrity check failed; migration not applied')
            apply_migration(conn)
        return {'status': 'migrated', 'backup': str(backup)}


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    parser.add_argument('--backup-dir', type=Path)
    args = parser.parse_args()
    if args.apply and args.backup_dir is None:
        parser.error('--apply requires --backup-dir; drain the job queue and stop API and Worker first')
    result = migrate(args.data_dir, args.backup_dir) if args.apply else preview(args.data_dir)
    print(json.dumps(result, ensure_ascii=False))


if __name__ == '__main__':
    main()
