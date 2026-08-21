#!/usr/bin/env python3
"""Explicit offline installer for global 28 ActorOps operator controls."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))

from scripts.actorops_migration_safety import active_workers_fail_closed
from scripts.migrate_apify_actor_ops_v15 import _backup_database, _restore_database
from src.storage.actorops_v2_operator_backfill import backfill_v1_metadata
from src.storage.actorops_v2_operator_schema import (
    ACTOROPS_V2_OPERATOR_MIGRATION_CHECKSUM, ACTOROPS_V2_OPERATOR_MIGRATION_NAME,
    ACTOROPS_V2_OPERATOR_MIGRATION_VERSION, existing_operator_tables, install_schema,
    mark_migrated, migration_marker_exists, prerequisite_ready, schema_shapes_valid,
)


def _connect(path: Path, *, read_only: bool) -> sqlite3.Connection:
    connection = sqlite3.connect(f"file:{path}?mode=ro" if read_only else path, uri=read_only)
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys=ON")
    return connection


def _state(connection: sqlite3.Connection) -> str:
    row = connection.execute("SELECT name, checksum FROM schema_migrations WHERE version=?", (ACTOROPS_V2_OPERATOR_MIGRATION_VERSION,)).fetchone()
    if row is not None:
        if str(row["name"]) != ACTOROPS_V2_OPERATOR_MIGRATION_NAME or str(row["checksum"]) != ACTOROPS_V2_OPERATOR_MIGRATION_CHECKSUM:
            raise RuntimeError("global schema migration version 28 is already occupied")
        if not schema_shapes_valid(connection):
            raise RuntimeError("ActorOps v2 operator marker exists with an invalid schema")
        return "ready"
    if existing_operator_tables(connection):
        raise RuntimeError("partial ActorOps v2 operator schema must be restored before migration")
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global schema 26 is required before ActorOps operator controls")
    return "required"


def preview(data_dir: Path) -> dict[str, Any]:
    database = data_dir / "service.db"
    connection = _connect(database, read_only=True)
    try:
        state = _state(connection)
        candidates = int(connection.execute("SELECT COUNT(*) FROM actor_candidates_v2").fetchone()[0]) if state == "required" else 0
    finally:
        connection.close()
    workers = active_workers_fail_closed(database)
    return {
        "status": "already_migrated" if state == "ready" else ("blocked" if workers else "migration_required"),
        "required": state != "ready", "blocker_counts": {"workers": len(workers)} if workers else {},
        "safe_candidate_count": candidates, "global_25_ignored": True, "global_27_ignored": True,
    }


def migrate(data_dir: Path, *, apply: bool, backup_dir: Path | None = None) -> dict[str, Any]:
    database = data_dir / "service.db"
    if not database.exists():
        raise RuntimeError("service database does not exist")
    result = preview(data_dir)
    if not apply or result["status"] == "already_migrated":
        return result
    if result["status"] == "blocked":
        raise RuntimeError("API and Worker must stop before global 28 migration")
    destination = backup_dir or data_dir / "backups"
    mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, destination)
    backup = raw_backup.with_name(raw_backup.name.replace("service-apify-actor-ops-v15-", "service-actorops-v2-v28-", 1))
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    connection: sqlite3.Connection | None = None
    try:
        connection = _connect(database, read_only=False)
        _state(connection)
        if active_workers_fail_closed(database):
            raise RuntimeError("API and Worker must stop before global 28 migration")
        connection.execute("BEGIN IMMEDIATE")
        install_schema(connection)
        count = backfill_v1_metadata(connection)
        mark_migrated(connection)
        connection.commit()
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys or not migration_marker_exists(connection) or not schema_shapes_valid(connection):
            raise RuntimeError("post-migration checks failed")
        connection.close()
        connection = None
    except Exception:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        _restore_database(backup_path=backup, db_path=database, original_mode=mode)
        raise
    return {"status": "applied", "required": False, "backup": str(backup), "backup_mode": "0o600", "backfill_counts": {"store_metadata": count}, "integrity_check": "ok", "foreign_key_violations": 0, "applied_at": datetime.now(timezone.utc).isoformat()}


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=ROOT / "data")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = migrate(args.data_dir, apply=bool(args.apply), backup_dir=args.backup_dir)
    except RuntimeError as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
