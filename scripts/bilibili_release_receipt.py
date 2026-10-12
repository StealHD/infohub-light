"""Private, revision-bound evidence for the explicit Bilibili data cutover.

Verification uses only stdlib so the release gate can stream it over SSH.
"""

import argparse
import json
import os
import re
import sqlite3
import stat
from contextlib import closing
from pathlib import Path

MARKER = {'version': 30, 'name': 'actorops_v2_single_track',
          'checksum': 'actorops-v2-single-track-v1'}
SCHEMA = 'bilibili_actor_sources_release_receipt_v1'


def private_file(path, directory):
    if path.parent != directory or path.resolve().parent != directory.resolve():
        raise ValueError('migration evidence escapes the managed backup directory')
    metadata = path.lstat()
    if not stat.S_ISREG(metadata.st_mode) or stat.S_IMODE(metadata.st_mode) != 0o600:
        raise ValueError('migration evidence must be a private regular file')


def binding_snapshot(connection):
    return [list(row) for row in connection.execute(
        """SELECT binding.workspace_id, binding.source_id, binding.route_id,
                  binding.target_fingerprint FROM actor_source_bindings_v2 AS binding
           JOIN actor_routes_v2 AS route ON route.route_id=binding.route_id
           WHERE route.platform='bilibili' AND route.target_type='profile'
                 AND route.capability='items' ORDER BY binding.workspace_id, binding.source_id"""
    )]


def database_ready(database, bindings):
    with closing(sqlite3.connect(f'file:{database}?mode=ro', uri=True, timeout=30)) as conn:
        marker = conn.execute('SELECT name,checksum FROM schema_migrations WHERE version=30').fetchone()
        if marker != (MARKER['name'], MARKER['checksum']):
            raise ValueError('production ActorOps v2 marker is invalid')
        if conn.execute("""SELECT 1 FROM workspaces AS workspace WHERE NOT EXISTS (
            SELECT 1 FROM actor_routes_v2 AS route WHERE route.workspace_id=workspace.id
            AND route.platform='bilibili' AND route.target_type='profile'
            AND route.capability='items') LIMIT 1""").fetchone():
            raise ValueError('Bilibili route provisioning is incomplete')
        if binding_snapshot(conn) != bindings:
            raise ValueError('Bilibili migration bindings changed before release')


def verify(base, receipt_path, revision):
    directory = base / 'data' / 'backups'
    if not re.fullmatch('[0-9a-f]{40}', revision):
        raise ValueError('full release revision required')
    private_file(receipt_path, directory)
    receipt = json.loads(receipt_path.read_text())
    expected = {'schema': SCHEMA, 'migration': 'bilibili_actor_sources',
                'marker': MARKER, 'release_revision': revision}
    if any(receipt.get(key) != value for key, value in expected.items()):
        raise ValueError('Bilibili receipt is not bound to this release')
    backup = receipt.get('backup', {})
    if backup.get('mode') != '0o600' or not isinstance(receipt.get('bindings'), list):
        raise ValueError('invalid migration metadata')
    backup_path = Path(backup.get('path', ''))
    private_file(backup_path, directory)
    # Integrity/FK scans belong to the stopped-service migration, not online verification.
    database_ready(base / 'data' / 'service.db', receipt['bindings'])
    return str(backup_path)


def write(base, receipt_path, revision, backup):
    """Called by the migrator inside its stopped-service safety boundary."""
    directory = base / 'data' / 'backups'
    if not re.fullmatch('[0-9a-f]{40}', revision) or receipt_path.parent != directory:
        raise ValueError('managed receipt path and full release revision required')
    private_file(backup, directory)
    with closing(sqlite3.connect(f'file:{base / "data" / "service.db"}?mode=ro', uri=True)) as conn:
        bindings = binding_snapshot(conn)
    database_ready(base / 'data' / 'service.db', bindings)
    receipt = {'schema': SCHEMA, 'migration': 'bilibili_actor_sources', 'marker': MARKER,
               'release_revision': revision, 'backup': {'path': str(backup), 'mode': '0o600'},
               'bindings': bindings}
    descriptor = os.open(receipt_path, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
    with os.fdopen(descriptor, 'w') as handle:
        json.dump(receipt, handle, sort_keys=True)
        handle.write('\n')
    return verify(base, receipt_path, revision)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('command', choices=['verify'])
    parser.add_argument('--base', type=Path, required=True)
    parser.add_argument('--receipt', type=Path, required=True)
    parser.add_argument('--revision', required=True)
    args = parser.parse_args()
    print(verify(args.base, args.receipt, args.revision))


if __name__ == '__main__':
    main()
