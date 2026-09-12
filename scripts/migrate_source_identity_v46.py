#!/usr/bin/env python3
"""Offline global 46 installer. Preview is read-only; apply requires stopped services."""
from __future__ import annotations

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
from src.storage.source_identity_schema import apply_migration, preflight, _integrity_check


def preview(data_dir: Path):
    database = data_dir / "service.db"
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as conn:
        result = preflight(conn)
        _integrity_check(conn)
    if result["status"] != "already_migrated":
        workers = len(active_workers_fail_closed(database))
        if workers:
            result["blocker_counts"]["workers"] = workers
            result["status"] = "blocked"
    return result


def _apply_offline(data_dir, backup_dir):
    database = data_dir / "service.db"
    result = preview(data_dir)
    if result["status"] == "already_migrated":
        return result
    if result["status"] == "blocked":
        raise ValueError(f"Stop API and Worker; resolve source identity blockers: {result['blocker_counts']}")
    raw_backup = _backup_database(database, backup_dir or data_dir / "backups")
    backup = raw_backup.with_name(raw_backup.name.replace(
        "service-apify-actor-ops-v15-", "service-source-identity-v46-", 1))
    raw_backup.rename(backup)
    os.chmod(backup, 0o600)
    with closing(sqlite3.connect(backup.as_uri() + "?mode=ro", uri=True)) as conn:
        _integrity_check(conn)
        if preflight(conn)["status"] != "migration_required":
            raise ValueError("migration backup must contain valid pre-migration schema")
    if active_workers_fail_closed(database):
        # No schema changes yet: never restore over work from a restarted service.
        raise ValueError("Stop API and Worker before migration")
    with closing(sqlite3.connect(database)) as conn:
        conn.execute("PRAGMA foreign_keys=ON")
        # All shape/integrity checks precede the migration's atomic commit.
        # Failure rolls back only that transaction; the backup is operator-owned.
        apply_migration(conn)
    return {"status": "applied", "backup": str(backup), "backup_mode": "0o600",
            "integrity_check": "ok", "foreign_key_violations": 0}


def migrate(data_dir: Path, *, apply=False, services_stopped=False, backup_dir=None):
    data_dir = Path(data_dir).resolve()
    result = preview(data_dir)
    if not apply or result["status"] == "already_migrated":
        return result
    if not services_stopped:
        raise ValueError("Stop API and Worker, then acknowledge --services-stopped before migration")
    # Serialize backup/apply, including two installers started concurrently.
    lock = os.open(data_dir / ".source-identity-v46.lock", os.O_CREAT | os.O_RDWR, 0o600)
    try:
        fcntl.flock(lock, fcntl.LOCK_EX)
        return _apply_offline(data_dir, Path(backup_dir).resolve() if backup_dir else None)
    finally:
        os.close(lock)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--data-dir", required=True, type=Path)
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    parser.add_argument("--services-stopped", action="store_true",
                        help="Acknowledge API and Worker are stopped; heartbeat guard still applies")
    args = parser.parse_args()
    try:
        result = migrate(args.data_dir, apply=args.apply, services_stopped=args.services_stopped,
                         backup_dir=args.backup_dir)
    except (ValueError, RuntimeError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1
    except (sqlite3.Error, OSError):
        print(json.dumps({"status": "failed", "error": "source identity migration blocked; inspect preview and offline prerequisites"}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
