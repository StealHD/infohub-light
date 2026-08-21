#!/usr/bin/env python3
"""Explicit offline upgrade for ActorOps' $0.20 validation ceiling."""

from __future__ import annotations

import argparse
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.actorops_migration_safety import active_actor_work, active_workers_fail_closed
from scripts.migrate_apify_actor_ops_v15 import _backup_database, _restore_database
from src.storage.apify_actor_pool_management_schema import (
    apify_actor_pool_management_v22_schema_shapes_valid,
    migration_marker_exists as pool_management_marker_exists,
)
from src.storage.apify_actor_validation_cap_v27_schema import (
    install_schema,
    mark_migrated,
    migration_marker_exists,
    schema_shapes_valid,
)


def _require_prerequisite(connection: sqlite3.Connection) -> None:
    if not (
        pool_management_marker_exists(connection)
        and apify_actor_pool_management_v22_schema_shapes_valid(connection)
    ):
        raise RuntimeError("global schema 24 is required before validation-cap v27")


def migrate(
    data_dir: Path, *, apply: bool, backup_dir: Path | None = None
) -> dict[str, Any]:
    database = data_dir / "service.db"
    if not database.exists():
        raise RuntimeError("service database does not exist")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        _require_prerequisite(connection)
        ready = migration_marker_exists(connection) and schema_shapes_valid(connection)
        if not apply:
            return {"required": not ready, "database": str(database)}
        if active_workers_fail_closed(database):
            raise RuntimeError("active workers must be stopped before migration")
        if active_actor_work(database):
            raise RuntimeError("active ActorOps jobs must finish before migration")
        if ready:
            return {"required": False, "applied": False, "already_migrated": True,
                    "database": str(database)}
    finally:
        connection.close()

    destination = backup_dir or data_dir / "backups"
    original_mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, destination)
    backup = raw_backup.with_name(raw_backup.name.replace(
        "service-apify-actor-ops-v15-", "service-apify-actor-validation-cap-v27-", 1
    ))
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    connection: sqlite3.Connection | None = None
    try:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        connection.execute("PRAGMA foreign_keys = OFF")
        try:
            connection.execute("BEGIN IMMEDIATE")
            install_schema(connection)
            mark_migrated(connection, commit=False)
            connection.commit()
        finally:
            connection.execute("PRAGMA foreign_keys = ON")
        connection.close()
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        valid = migration_marker_exists(connection) and schema_shapes_valid(connection)
        if integrity != "ok" or foreign_keys or not valid:
            raise RuntimeError(
                "post-migration integrity checks failed: "
                f"integrity={integrity!r} foreign_keys={len(foreign_keys)} valid={valid}"
            )
        connection.close()
        connection = None
    except Exception:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        _restore_database(backup_path=backup, db_path=database, original_mode=original_mode)
        raise
    return {
        "required": False,
        "applied": True,
        "backup": str(backup),
        "backup_mode": oct(backup.stat().st_mode & 0o777),
        "integrity_check": "ok",
        "foreign_key_violations": 0,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(migrate(args.data_dir, apply=args.apply, backup_dir=args.backup_dir))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
