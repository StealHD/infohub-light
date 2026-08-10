#!/usr/bin/env python3
"""Install ActorOps manual three-slot selection as global schema 21."""

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

from scripts.migrate_apify_actor_canary_batches_v17 import _active_jobs  # noqa: E402
from scripts.migrate_apify_actor_ops_v15 import (  # noqa: E402
    _backup_database,
    _restore_database,
)
from scripts.migrate_user_feed_v2 import _active_workers  # noqa: E402
from src.storage.service_store import (  # noqa: E402
    APIFY_ACTOR_MANUAL_POOL_SELECTION_MIGRATION_CHECKSUM,
    APIFY_ACTOR_MANUAL_POOL_SELECTION_MIGRATION_NAME,
    APIFY_ACTOR_MANUAL_POOL_SELECTION_MIGRATION_VERSION,
    APIFY_ACTOR_POOL_STAGING_MIGRATION_CHECKSUM,
    apify_actor_manual_pool_selection_v19_schema_shapes_valid,
    apify_actor_pool_staging_v18_schema_shapes_valid,
)


def _marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(
        connection.execute(
            """
            SELECT 1 FROM schema_migrations
            WHERE version = ? AND name = ? AND checksum = ?
            """,
            (
                APIFY_ACTOR_MANUAL_POOL_SELECTION_MIGRATION_VERSION,
                APIFY_ACTOR_MANUAL_POOL_SELECTION_MIGRATION_NAME,
                APIFY_ACTOR_MANUAL_POOL_SELECTION_MIGRATION_CHECKSUM,
            ),
        ).fetchone()
    )


def _require_prerequisite(connection: sqlite3.Connection) -> None:
    marker = connection.execute(
        """
        SELECT 1 FROM schema_migrations
        WHERE version = 20
          AND name = 'apify_actor_pool_staging_v18'
          AND checksum = ?
        """,
        (APIFY_ACTOR_POOL_STAGING_MIGRATION_CHECKSUM,),
    ).fetchone()
    if not marker or not apify_actor_pool_staging_v18_schema_shapes_valid(
        connection
    ):
        raise RuntimeError(
            "apify_actor_pool_staging_v18 migration is required first"
        )


def _rebuild_stage_table(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.executescript(
            """
            BEGIN IMMEDIATE;
            DROP TABLE IF EXISTS apify_actor_pool_stages_v19;
            CREATE TABLE apify_actor_pool_stages_v19 (
                stage_id TEXT PRIMARY KEY,
                workspace_id TEXT NOT NULL,
                route_id TEXT NOT NULL,
                discovery_run_id TEXT NOT NULL,
                initial_batch_id TEXT NOT NULL,
                goal TEXT NOT NULL CHECK(goal IN (
                    'initial_pool', 'complete_third', 'upgrade_legacy'
                )),
                target_slot_count INTEGER NOT NULL DEFAULT 3
                    CHECK(target_slot_count BETWEEN 2 AND 3),
                selection_mode TEXT NOT NULL DEFAULT 'server'
                    CHECK(selection_mode IN ('server', 'manual')),
                base_generation INTEGER NOT NULL CHECK(base_generation >= 1),
                base_pool_hash TEXT NOT NULL CHECK(
                    length(base_pool_hash) = 64
                    AND base_pool_hash NOT GLOB '*[^0-9a-f]*'
                ),
                plan_hash TEXT NOT NULL CHECK(
                    length(plan_hash) = 64
                    AND plan_hash NOT GLOB '*[^0-9a-f]*'
                ),
                approval_key_hash TEXT NOT NULL CHECK(
                    length(approval_key_hash) = 64
                    AND approval_key_hash NOT GLOB '*[^0-9a-f]*'
                ),
                max_total_charge_usd REAL NOT NULL CHECK(
                    max_total_charge_usd > 0
                    AND max_total_charge_usd <= 6.06
                ),
                route_validation_cap_usd REAL NOT NULL CHECK(
                    route_validation_cap_usd > 0
                    AND route_validation_cap_usd <= 0.06
                ),
                target_primary_revision_id TEXT,
                target_backup_1_revision_id TEXT,
                target_backup_2_revision_id TEXT,
                target_pool_hash TEXT CHECK(
                    target_pool_hash IS NULL OR (
                        length(target_pool_hash) = 64
                        AND target_pool_hash NOT GLOB '*[^0-9a-f]*'
                    )
                ),
                status TEXT NOT NULL CHECK(status IN (
                    'queued', 'validating_route', 'validating_sources',
                    'apply_ready', 'applied', 'replan_required',
                    'blocked_unknown_start', 'stale', 'failed', 'cancelled'
                )),
                apply_key_hash TEXT CHECK(
                    apply_key_hash IS NULL OR (
                        length(apply_key_hash) = 64
                        AND apply_key_hash NOT GLOB '*[^0-9a-f]*'
                    )
                ),
                applied_route_generation INTEGER,
                last_error_code TEXT,
                created_by_user_id TEXT NOT NULL,
                created_at TEXT NOT NULL,
                updated_at TEXT NOT NULL,
                applied_at TEXT,
                UNIQUE(workspace_id, stage_id),
                UNIQUE(workspace_id, approval_key_hash),
                FOREIGN KEY(workspace_id)
                    REFERENCES workspaces(id) ON DELETE CASCADE,
                FOREIGN KEY(workspace_id, route_id)
                    REFERENCES apify_actor_route_profiles(
                        workspace_id, route_id
                    ) ON DELETE CASCADE,
                FOREIGN KEY(workspace_id, discovery_run_id)
                    REFERENCES apify_actor_discovery_runs(
                        workspace_id, run_id
                    ) ON DELETE RESTRICT,
                FOREIGN KEY(workspace_id, initial_batch_id)
                    REFERENCES apify_actor_canary_batches(
                        workspace_id, batch_id
                    ) ON DELETE RESTRICT,
                FOREIGN KEY(created_by_user_id)
                    REFERENCES users(id) ON DELETE RESTRICT
            );

            INSERT INTO apify_actor_pool_stages_v19 (
                stage_id, workspace_id, route_id, discovery_run_id,
                initial_batch_id, goal, target_slot_count, selection_mode,
                base_generation, base_pool_hash, plan_hash,
                approval_key_hash, max_total_charge_usd,
                route_validation_cap_usd, target_primary_revision_id,
                target_backup_1_revision_id, target_backup_2_revision_id,
                target_pool_hash, status, apply_key_hash,
                applied_route_generation, last_error_code,
                created_by_user_id, created_at, updated_at, applied_at
            )
            SELECT
                stage_id, workspace_id, route_id, discovery_run_id,
                initial_batch_id, goal,
                CASE
                    WHEN goal = 'complete_third' THEN 3
                    WHEN target_backup_2_revision_id IS NOT NULL THEN 3
                    ELSE 2
                END,
                'server', base_generation, base_pool_hash, plan_hash,
                approval_key_hash, max_total_charge_usd,
                route_validation_cap_usd, target_primary_revision_id,
                target_backup_1_revision_id, target_backup_2_revision_id,
                target_pool_hash, status, apply_key_hash,
                applied_route_generation, last_error_code,
                created_by_user_id, created_at, updated_at, applied_at
            FROM apify_actor_pool_stages;

            DROP TABLE apify_actor_pool_stages;
            ALTER TABLE apify_actor_pool_stages_v19
                RENAME TO apify_actor_pool_stages;
            CREATE UNIQUE INDEX idx_apify_actor_pool_stages_active
                ON apify_actor_pool_stages(workspace_id, route_id)
                WHERE status NOT IN (
                    'applied', 'stale', 'failed', 'cancelled'
                );
            """
        )
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                APIFY_ACTOR_MANUAL_POOL_SELECTION_MIGRATION_VERSION,
                APIFY_ACTOR_MANUAL_POOL_SELECTION_MIGRATION_NAME,
                APIFY_ACTOR_MANUAL_POOL_SELECTION_MIGRATION_CHECKSUM,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


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
        already_ready = bool(
            _marker_exists(connection)
            and apify_actor_manual_pool_selection_v19_schema_shapes_valid(
                connection
            )
        )
        if not apply:
            return {"required": not already_ready, "database": str(database)}
        if _active_workers(database):
            raise RuntimeError("active workers must be stopped before migration")
        if _active_jobs(database):
            raise RuntimeError("active ActorOps jobs must finish before migration")
        if already_ready:
            return {
                "required": False,
                "applied": False,
                "already_migrated": True,
                "database": str(database),
            }
    finally:
        connection.close()

    destination = backup_dir or data_dir / "backups"
    original_mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, destination)
    backup = raw_backup.with_name(
        raw_backup.name.replace(
            "service-apify-actor-ops-v15-",
            "service-apify-actor-manual-pool-v19-",
            1,
        )
    )
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    connection = None
    try:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        _rebuild_stage_table(connection)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if (
            integrity != "ok"
            or foreign_keys
            or not apify_actor_manual_pool_selection_v19_schema_shapes_valid(
                connection
            )
        ):
            raise RuntimeError("post-migration integrity checks failed")
        connection.close()
        connection = None
    except Exception:
        if connection is not None:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
        _restore_database(
            backup_path=backup,
            db_path=database,
            original_mode=original_mode,
        )
        raise
    os.chmod(backup, 0o600)
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
    print(
        json.dumps(
            migrate(
                args.data_dir,
                apply=args.apply,
                backup_dir=args.backup_dir,
            )
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
