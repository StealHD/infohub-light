#!/usr/bin/env python3
"""Safely fill missing pending v2 bindings for existing catalog social sources."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.actorops_migration_safety import active_workers_fail_closed
from scripts.migrate_apify_actor_ops_v15 import _backup_database, _restore_database
from src.services.actorops.catalog_binding_bridge import bridge_catalog_source_bindings
from src.storage.actorops_v2_single_track_schema import (
    migration_marker_exists as single_track_marker_exists,
)
from src.storage.actorops_v2_schema import migration_marker_exists, schema_shapes_valid


class CatalogBindingRepairError(RuntimeError):
    pass


def _database(data_dir: Path) -> Path:
    database = data_dir / "service.db"
    if not database.is_file():
        raise CatalogBindingRepairError("service database does not exist")
    return database


def _connect(database: Path, *, read_only: bool) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{database}?mode=ro" if read_only else database,
        uri=read_only,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _require_v2_schema(connection: sqlite3.Connection) -> None:
    if single_track_marker_exists(connection):
        raise CatalogBindingRepairError("actorops_v1_retired")
    if not migration_marker_exists(connection) or not schema_shapes_valid(connection):
        raise CatalogBindingRepairError("ActorOps v2 schema is not valid")


def _preview(database: Path) -> dict[str, Any]:
    connection = _connect(database, read_only=True)
    try:
        _require_v2_schema(connection)
        report = bridge_catalog_source_bindings(connection, apply=False)
    finally:
        connection.close()
    counts = report.planned_counts()
    return {
        "status": "repair_required" if report.catalog_candidates else "nothing_to_repair",
        "planned_counts": counts,
        "global_25_ignored": True,
    }


def repair(
    data_dir: Path,
    *,
    apply: bool,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    database = _database(data_dir)
    preview = _preview(database)
    if not apply:
        return preview
    if preview["status"] == "nothing_to_repair":
        return {**preview, "status": "already_repaired"}
    if active_workers_fail_closed(database):
        raise CatalogBindingRepairError("stop API and Worker before repairing bindings")

    original_mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, backup_dir or data_dir / "backups")
    backup = raw_backup.with_name(
        raw_backup.name.replace(
            "service-apify-actor-ops-v15-", "service-actorops-v2-catalog-bindings-", 1
        )
    )
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    connection: sqlite3.Connection | None = None
    try:
        connection = _connect(database, read_only=False)
        _require_v2_schema(connection)
        if active_workers_fail_closed(database):
            raise CatalogBindingRepairError("stop API and Worker before repairing bindings")
        connection.execute("BEGIN IMMEDIATE")
        report = bridge_catalog_source_bindings(connection, apply=True)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise CatalogBindingRepairError("catalog binding repair postcheck failed")
        connection.commit()
        connection.close()
        connection = None
    except Exception:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        _restore_database(
            backup_path=backup, db_path=database, original_mode=original_mode
        )
        raise
    os.chmod(backup, 0o600)
    return {
        "status": "applied",
        "inserted": report.inserted,
        "planned_counts": report.planned_counts(),
        "backup": str(backup),
        "backup_mode": oct(backup.stat().st_mode & 0o777),
        "integrity_check": "ok",
        "foreign_key_violations": 0,
        "global_25_ignored": True,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = repair(args.data_dir, apply=bool(args.apply), backup_dir=args.backup_dir)
    except (CatalogBindingRepairError, sqlite3.Error) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
