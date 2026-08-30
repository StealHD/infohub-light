#!/usr/bin/env python3
"""Explicit offline installer for global 36 proof-gated auto replacement."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from pathlib import Path
from typing import Any


ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.actorops_migration_safety import active_workers_fail_closed
from scripts.migrate_apify_actor_ops_v15 import _backup_database, _restore_database
from src.storage.actorops_v2_verified_replacement_schema import (
    MIGRATION_CHECKSUM, MIGRATION_NAME, MIGRATION_VERSION, apply_migration,
    migration_marker_exists, prerequisite_ready, schema_shapes_valid,
)


def _connect(path: Path, *, read_only: bool) -> sqlite3.Connection:
    target: str | Path = f"file:{path}?mode=ro" if read_only else path
    connection = sqlite3.connect(target, uri=read_only)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _state(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT name,checksum FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,),
    ).fetchone()
    if row is not None:
        if row["name"] != MIGRATION_NAME or row["checksum"] != MIGRATION_CHECKSUM:
            raise RuntimeError("global schema migration version 36 is already occupied")
        if not schema_shapes_valid(connection):
            raise RuntimeError("verified replacement marker exists with invalid schema")
        return "ready"
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global schema 35 is required before verified replacement")
    return "required"


def preview(data_dir: Path) -> dict[str, Any]:
    database = data_dir / "service.db"
    if not database.exists():
        raise RuntimeError("service database does not exist")
    connection = _connect(database, read_only=True)
    try:
        state = _state(connection)
    finally:
        connection.close()
    workers = active_workers_fail_closed(database)
    return {
        "status": (
            "already_migrated" if state == "ready"
            else "blocked" if workers else "migration_required"
        ),
        "required": state != "ready",
        "blocker_counts": {"workers": len(workers)} if workers else {},
    }


def migrate(
    data_dir: Path, *, apply: bool, backup_dir: Path | None = None,
) -> dict[str, Any]:
    database = data_dir / "service.db"
    result = preview(data_dir)
    if not apply or result["status"] == "already_migrated":
        return result
    if result["status"] == "blocked":
        raise RuntimeError("API and Worker must stop before global 36 migration")
    destination = backup_dir or data_dir / "backups"
    original_mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, destination)
    backup = raw_backup.with_name(raw_backup.name.replace(
        "service-apify-actor-ops-v15-", "service-actorops-v2-v36-", 1
    ))
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    connection: sqlite3.Connection | None = None
    apply_started = False
    try:
        connection = _connect(database, read_only=False)
        _state(connection)
        if active_workers_fail_closed(database):
            raise RuntimeError("API and Worker must stop before global 36 migration")
        apply_started = True
        changes = apply_migration(connection)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if (
            integrity.casefold() != "ok" or foreign_keys
            or not migration_marker_exists(connection)
            or not schema_shapes_valid(connection)
        ):
            raise RuntimeError("post-migration checks failed")
        connection.close()
        connection = None
    except Exception:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        if apply_started:
            _restore_database(
                backup_path=backup, db_path=database, original_mode=original_mode
            )
        raise
    return {
        "status": "applied", "required": False, "backup": str(backup),
        "backup_mode": "0o600", "integrity_check": "ok",
        "foreign_key_violations": 0, **changes,
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = migrate(args.data_dir, apply=args.apply, backup_dir=args.backup_dir)
    except (RuntimeError, OSError, sqlite3.Error) as error:
        print(json.dumps({"status": "failed", "error": str(error)}))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
