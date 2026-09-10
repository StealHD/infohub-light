"""Explicit offline migration; existing bindings are not configured or approved."""
import argparse
import json
import os
import sqlite3
import sys
from contextlib import closing
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from scripts.actorops_migration_safety import active_workers_fail_closed
from scripts.migrate_apify_actor_ops_v15 import _backup_database
from src.storage.agent_analysis_schema import apply_migration, ready, prerequisite_ready


def migrate(data, apply=False):
    path = data / 'service.db'
    with closing(sqlite3.connect(f'file:{path}?mode=ro', uri=True)) as conn:
        if ready(conn):
            return {'status': 'already_migrated'}
        if not prerequisite_ready(conn):
            raise ValueError('global 43 required')
    if not apply:
        return {'status': 'migration_required'}
    if active_workers_fail_closed(path):
        raise ValueError('Stop API and Worker before migration')
    original = _backup_database(path, data / 'backups')
    backup = original.with_name(original.name.replace('service-apify-actor-ops-v15-', 'service-agent-analysis-v44-', 1))
    original.rename(backup)
    os.chmod(backup, 0o600)
    with closing(sqlite3.connect(path)) as conn:
        conn.execute('PRAGMA foreign_keys=ON')
        apply_migration(conn)
        if conn.execute('PRAGMA integrity_check').fetchone()[0] != 'ok' or conn.execute('PRAGMA foreign_key_check').fetchone():
            raise ValueError('Database integrity check failed')
    return {'status': 'applied', 'backup': str(backup), 'installations_created': 0}


if __name__ == '__main__':
    parser = argparse.ArgumentParser()
    parser.add_argument('--data-dir', required=True, type=Path)
    parser.add_argument('--apply', action='store_true')
    args = parser.parse_args()
    print(json.dumps(migrate(args.data_dir, args.apply)))
