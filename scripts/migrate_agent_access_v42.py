"""Offline explicit migration; no users or requests are provisioned."""
import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from scripts.actorops_migration_safety import active_workers_fail_closed
from scripts.migrate_apify_actor_ops_v15 import _backup_database
from src.storage.agent_access_schema import apply_migration, ready, prerequisite_ready


def migrate(data, apply=False):
    path = data / 'service.db'
    conn = sqlite3.connect(f'file:{path}?mode=ro', uri=True)
    try:
        if ready(conn):
            return {'status': 'already_migrated'}
        if not prerequisite_ready(conn):
            raise RuntimeError('global 41 required')
    finally:
        conn.close()
    if not apply:
        return {'status': 'migration_required'}
    if active_workers_fail_closed(path):
        raise RuntimeError('Stop API and Worker before migration')
    backup = _backup_database(path, data / 'backups')
    renamed = backup.with_name(backup.name.replace('service-apify-actor-ops-v15-', 'service-agent-access-v42-', 1))
    backup.rename(renamed)
    backup = renamed
    os.chmod(backup, 0o600)
    conn = sqlite3.connect(path)
    try:
        conn.execute('PRAGMA foreign_keys=ON')
        apply_migration(conn)
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchone():
            raise RuntimeError('Integrity check failed; preserve backup for operator recovery')
    finally:
        conn.close()
    return {'status': 'applied', 'backup': str(backup), 'requests_created': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', type=Path, required=True)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(migrate(args.data_dir, args.apply)))
