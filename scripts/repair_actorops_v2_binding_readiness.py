#!/usr/bin/env python3
"""Promote v2 bindings only when exact settled v1 source evidence still matches."""

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
from src.services.actorops.legacy_readiness import (
    apply_legacy_ready_bindings,
    legacy_ready_binding_plans,
)
from src.services.actorops.repository import ActorOpsRepository
from src.storage.actorops_v2_schema import migration_marker_exists, schema_shapes_valid
from src.storage.service_store import DEFAULT_WORKSPACE_ID


class BindingReadinessRepairError(RuntimeError):
    pass


def _database(data_dir: Path) -> Path:
    database = data_dir / "service.db"
    if not database.is_file():
        raise BindingReadinessRepairError("service database does not exist")
    return database


def _connect(database: Path, *, read_only: bool) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{database}?mode=ro" if read_only else database,
        uri=read_only,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _route_id(connection: sqlite3.Connection, workspace_id: str, platform: str) -> str:
    rows = connection.execute(
        """SELECT route_id FROM actor_routes_v2
           WHERE workspace_id=? AND platform=? ORDER BY route_id""",
        (workspace_id, platform.strip().casefold()),
    ).fetchall()
    if len(rows) != 1:
        raise BindingReadinessRepairError("binding readiness requires one Route per platform")
    return str(rows[0]["route_id"])


def _require_schema(connection: sqlite3.Connection) -> None:
    if not migration_marker_exists(connection) or not schema_shapes_valid(connection):
        raise BindingReadinessRepairError("ActorOps v2 schema is not valid")


def _counts(report: Any) -> dict[str, int]:
    return {
        "pending_bindings": report.pending_bindings,
        "planned_ready": report.planned_ready,
        "legacy_mismatch": report.legacy_mismatch,
        "no_runnable_candidates": report.no_runnable_candidates,
        "candidate_order_mismatch": report.candidate_order_mismatch,
        "missing_source_evidence": report.missing_source_evidence,
    }


def preview(
    data_dir: Path, *, platform: str, workspace_id: str = DEFAULT_WORKSPACE_ID
) -> dict[str, Any]:
    connection = _connect(_database(data_dir), read_only=True)
    try:
        _require_schema(connection)
        _plans, report = legacy_ready_binding_plans(
            connection,
            workspace_id=workspace_id,
            route_id=_route_id(connection, workspace_id, platform),
        )
    finally:
        connection.close()
    status = "ready_to_apply" if report.planned_ready else (
        "already_ready" if not report.pending_bindings else "blocked"
    )
    return {"status": status, "counts": _counts(report), "global_25_ignored": True}


def repair(
    data_dir: Path,
    *,
    platform: str,
    apply: bool,
    workspace_id: str = DEFAULT_WORKSPACE_ID,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    database = _database(data_dir)
    report = preview(data_dir, platform=platform, workspace_id=workspace_id)
    if not apply or report["status"] != "ready_to_apply":
        return report
    if active_workers_fail_closed(database):
        raise BindingReadinessRepairError("stop API and Worker before repairing readiness")

    original_mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, backup_dir or data_dir / "backups")
    backup = raw_backup.with_name(raw_backup.name.replace("v15", "v2-binding-readiness", 1))
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    connection: sqlite3.Connection | None = None
    try:
        connection = _connect(database, read_only=False)
        _require_schema(connection)
        if active_workers_fail_closed(database):
            raise BindingReadinessRepairError("stop API and Worker before repairing readiness")
        repository = ActorOpsRepository(connection, workspace_id)
        with repository.transaction():
            route_id = _route_id(connection, workspace_id, platform)
            plans, readiness = legacy_ready_binding_plans(
                connection, workspace_id=workspace_id, route_id=route_id
            )
            if not plans:
                raise BindingReadinessRepairError("binding readiness evidence changed")
            applied = apply_legacy_ready_bindings(repository, plans)
            integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
            foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
            if integrity != "ok" or foreign_keys:
                raise BindingReadinessRepairError("binding readiness postcheck failed")
        connection.close()
        connection = None
    except Exception:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        _restore_database(backup_path=backup, db_path=database, original_mode=original_mode)
        raise
    os.chmod(backup, 0o600)
    return {
        "status": "applied",
        "ready_bindings": applied,
        "counts": _counts(readiness),
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
    parser.add_argument("--platform", required=True, choices=("youtube", "instagram", "x"))
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    try:
        result = repair(
            args.data_dir,
            platform=args.platform,
            apply=bool(args.apply),
            backup_dir=args.backup_dir,
        )
    except (BindingReadinessRepairError, sqlite3.Error) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, sort_keys=True))
        return 1
    print(json.dumps(result, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
