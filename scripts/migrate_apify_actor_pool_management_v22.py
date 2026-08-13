#!/usr/bin/env python3
"""Install ActorOps per-slot pool management as global schema 24."""

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

from scripts.migrate_apify_actor_ops_v15 import _backup_database, _restore_database
from scripts.migrate_user_feed_v2 import _active_workers
from src.storage.apify_actor_pool_management_schema import (
    apify_actor_pool_management_v22_schema_shapes_valid,
    install_schema,
    mark_migrated,
    migration_marker_exists,
)
from src.storage.service_store import (
    APIFY_ACTOR_RESILIENCE_MIGRATION_CHECKSUM,
    apify_actor_resilience_v21_schema_shapes_valid,
)


def _require_prerequisite(connection: sqlite3.Connection) -> None:
    marker = connection.execute(
        """SELECT 1 FROM schema_migrations
           WHERE version = 23 AND name = 'apify_actor_resilience_v21'
             AND checksum = ?""",
        (APIFY_ACTOR_RESILIENCE_MIGRATION_CHECKSUM,),
    ).fetchone()
    if not marker or not apify_actor_resilience_v21_schema_shapes_valid(connection):
        raise RuntimeError("apify_actor_resilience_v21 migration is required first")


def _active_actor_work(database: Path) -> list[dict[str, str]]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        jobs = connection.execute(
            """SELECT id, job_type, status FROM fetch_jobs
               WHERE job_type IN (
                   'apify_actor_discovery', 'apify_actor_validation',
                   'apify_actor_canary_batch', 'apify_actor_freshness_check'
               ) AND status IN ('queued', 'running')"""
        ).fetchall()
        runs = connection.execute(
            """SELECT id, 'apify_actor_run' AS job_type, status
               FROM apify_actor_runs
               WHERE status IN ('reserved', 'starting', 'running',
                                'start_outcome_unknown')"""
        ).fetchall()
        return [dict(row) for row in (*jobs, *runs)]
    finally:
        connection.close()


def migrate(
    data_dir: Path,
    *,
    apply: bool,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    database = data_dir / "service.db"
    if not database.exists():
        raise RuntimeError("service database does not exist")
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        _require_prerequisite(connection)
        ready = bool(
            migration_marker_exists(connection)
            and apify_actor_pool_management_v22_schema_shapes_valid(connection)
        )
        if not apply:
            return {"required": not ready, "database": str(database)}
        if _active_workers(database):
            raise RuntimeError("active workers must be stopped before migration")
        if _active_actor_work(database):
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
        "service-apify-actor-ops-v15-", "service-apify-actor-pool-management-v22-", 1
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
        valid = migration_marker_exists(connection) and apify_actor_pool_management_v22_schema_shapes_valid(connection)
        if integrity != "ok" or foreign_keys or not valid:
            raise RuntimeError(
                f"post-migration integrity checks failed: integrity={integrity!r} "
                f"foreign_keys={len(foreign_keys)} valid={valid}"
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
    os.chmod(backup, 0o600)
    return {
        "required": False, "applied": True, "backup": str(backup),
        "backup_mode": oct(backup.stat().st_mode & 0o777), "integrity_check": "ok",
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
