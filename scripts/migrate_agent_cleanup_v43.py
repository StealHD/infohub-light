"""Explicit offline global 43 migration; no historical revocations."""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.actorops_migration_safety import active_workers_fail_closed
from scripts.migrate_apify_actor_ops_v15 import _backup_database
from src.storage.agent_cleanup_schema import apply_migration, ready, prerequisite_ready


def migrate(data, apply=False):
    path = data / 'service.db'
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        if ready(conn):
            return {'status': 'already_migrated'}
        if not prerequisite_ready(conn):
            raise ValueError('global 42 required')
    finally:
        conn.close()
    if not apply:
        return {'status': 'migration_required'}
    if active_workers_fail_closed(path):
        raise ValueError('Stop API and Worker before migration')
    original = _backup_database(path, data / 'backups')
    backup = original.with_name(original.name.replace('service-apify-actor-ops-v15-', 'service-agent-cleanup-v43-', 1))
    original.rename(backup)
    os.chmod(backup, 0o600)
    conn = sqlite3.connect(path)
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        apply_migration(conn)
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Database integrity check failed')
    finally:
        conn.close()
    return {'status': 'applied', 'backup': str(backup), 'revocations_created': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(migrate(args.data_dir, args.apply)))
