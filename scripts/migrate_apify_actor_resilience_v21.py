#!/usr/bin/env python3
"""Install ActorOps compatibility, freshness and diagnostics as schema 23."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import uuid
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.migrate_apify_actor_ops_v15 import (  # noqa: E402
    _backup_database,
    _restore_database,
)
from scripts.migrate_apify_actor_validation_tuning_v20 import (  # noqa: E402
    _rebuild_table,
)
from scripts.migrate_user_feed_v2 import _active_workers  # noqa: E402
from src.storage.service_store import (  # noqa: E402
    APIFY_ACTOR_RESILIENCE_MIGRATION_CHECKSUM,
    APIFY_ACTOR_RESILIENCE_MIGRATION_NAME,
    APIFY_ACTOR_RESILIENCE_MIGRATION_VERSION,
    APIFY_ACTOR_VALIDATION_TUNING_MIGRATION_CHECKSUM,
    ServiceStore,
    apify_actor_resilience_v21_schema_shapes_valid,
    apify_actor_validation_tuning_v20_schema_shapes_valid,
)


_DETERMINISTIC_CANARY_FAILURES = frozenset(
    {
        "apify_actor_contract_mismatch",
        "apify_actor_identity_mismatch",
        "apify_actor_target_identity_mismatch",
        "apify_actor_metadata_only",
        "apify_actor_input_schema_unmappable",
        "apify_manifest_output_pointer_unverifiable",
        "apify_manifest_item_identity_invalid",
        "apify_manifest_source_identity_invalid",
        "actor_requires_full_permissions",
    }
)


def _evidence_fingerprint(row: sqlite3.Row) -> str:
    row_keys = set(row.keys())
    try:
        pricing = json.loads(str(row["pricing_json"] or "{}"))
    except (TypeError, ValueError, json.JSONDecodeError):
        pricing = {}
    if not isinstance(pricing, dict):
        pricing = {}
    return hashlib.sha256(
        json.dumps(
            {
                "route_id": str(row["route_id"]),
                "candidate_id": str(row["candidate_id"]),
                "actor_id": str(row["actor_id"]),
                "build_id": str(row["build_id"] or ""),
                "build_number": str(row["build_number"] or ""),
                "manifest_hash": str(row["manifest_hash"] or ""),
                "input_schema_hash": str(
                    row["input_schema_hash"] or ""
                    if "input_schema_hash" in row_keys
                    else ""
                ),
                "output_schema_hash": str(
                    row["output_schema_hash"] or ""
                    if "output_schema_hash" in row_keys
                    else ""
                ),
                "pricing": pricing,
            },
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(
        connection.execute(
            """
            SELECT 1 FROM schema_migrations
            WHERE version = ? AND name = ? AND checksum = ?
            """,
            (
                APIFY_ACTOR_RESILIENCE_MIGRATION_VERSION,
                APIFY_ACTOR_RESILIENCE_MIGRATION_NAME,
                APIFY_ACTOR_RESILIENCE_MIGRATION_CHECKSUM,
            ),
        ).fetchone()
    )


def _require_prerequisite(connection: sqlite3.Connection) -> None:
    marker = connection.execute(
        """
        SELECT 1 FROM schema_migrations
        WHERE version = 22
          AND name = 'apify_actor_validation_tuning_v20'
          AND checksum = ?
        """,
        (APIFY_ACTOR_VALIDATION_TUNING_MIGRATION_CHECKSUM,),
    ).fetchone()
    if not marker or not apify_actor_validation_tuning_v20_schema_shapes_valid(
        connection
    ):
        raise RuntimeError(
            "apify_actor_validation_tuning_v20 migration is required first"
        )


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _active_actor_work(database: Path) -> list[dict[str, str]]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        jobs = connection.execute(
            """
            SELECT id, job_type, status
            FROM fetch_jobs
            WHERE job_type IN (
                'apify_actor_discovery', 'apify_actor_validation',
                'apify_actor_canary_batch', 'apify_actor_freshness_check'
            ) AND status IN ('queued', 'running')
            """
        ).fetchall()
        runs = connection.execute(
            """
            SELECT id, 'apify_actor_run' AS job_type, status
            FROM apify_actor_runs
            WHERE status IN ('reserved', 'starting', 'running',
                             'start_outcome_unknown')
            """
        ).fetchall()
        return [dict(row) for row in (*jobs, *runs)]
    finally:
        connection.close()


def _add_column(
    connection: sqlite3.Connection,
    table: str,
    name: str,
    definition: str,
) -> None:
    if name not in _column_names(connection, table):
        connection.execute(
            f"ALTER TABLE {table} ADD COLUMN {name} {definition}"
        )


def _install_columns_and_constraints(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for name, definition in (
            (
                "admission_mode",
                "TEXT NOT NULL DEFAULT 'standard' "
                "CHECK(admission_mode IN ('standard', 'compatibility'))",
            ),
            ("compatibility_risk_code", "TEXT"),
            (
                "freshness_enabled",
                "INTEGER NOT NULL DEFAULT 0 CHECK(freshness_enabled IN (0, 1))",
            ),
            (
                "freshness_interval_hours",
                "INTEGER NOT NULL DEFAULT 24 "
                "CHECK(freshness_interval_hours BETWEEN 6 AND 168)",
            ),
            ("freshness_authorized_at", "TEXT"),
            (
                "freshness_authorized_by_user_id",
                "TEXT REFERENCES users(id) ON DELETE SET NULL",
            ),
            ("freshness_last_checked_at", "TEXT"),
            ("freshness_next_check_at", "TEXT"),
            (
                "freshness_status",
                "TEXT NOT NULL DEFAULT 'disabled' CHECK(freshness_status IN ("
                "'disabled', 'scheduled', 'running', 'fresh', "
                "'suspected_stale', 'stale', 'partial', "
                "'unverified_single', 'blocked_no_validation_key', 'failed'))",
            ),
            (
                "freshness_last_cost_usd",
                "REAL CHECK(freshness_last_cost_usd IS NULL "
                "OR freshness_last_cost_usd >= 0)",
            ),
        ):
            _add_column(
                connection,
                "apify_actor_route_profiles",
                name,
                definition,
            )
        route_triggers = connection.execute(
            """
            SELECT name, sql FROM sqlite_master
            WHERE type = 'trigger' AND sql LIKE '%apify_actor_route_profiles%'
            ORDER BY name
            """
        ).fetchall()
        for trigger in route_triggers:
            connection.execute(f'DROP TRIGGER "{str(trigger["name"])}"')
        _rebuild_table(
            connection,
            "apify_actor_route_profiles",
            replacements=(
                (
                    "CHECK(min_runtime_healthy BETWEEN 2 AND 3)",
                    "CHECK(min_runtime_healthy BETWEEN 1 AND 3)",
                ),
                (
                    "CHECK(min_publishers BETWEEN 2 AND 3)",
                    "CHECK(min_publishers BETWEEN 1 AND 3)",
                ),
            ),
            index_sql=(
                """
                CREATE INDEX idx_apify_actor_route_profiles_capability
                ON apify_actor_route_profiles(
                    workspace_id, platform, target_type, capability, status
                )
                """,
            ),
        )
        for trigger in route_triggers:
            if trigger["sql"]:
                connection.execute(str(trigger["sql"]))
        for name, definition in (
            (
                "execution_mode",
                "TEXT NOT NULL DEFAULT 'pinned' "
                "CHECK(execution_mode IN ('pinned', 'current'))",
            ),
            (
                "observed_manifest",
                "INTEGER NOT NULL DEFAULT 0 CHECK(observed_manifest IN (0, 1))",
            ),
        ):
            _add_column(
                connection,
                "apify_actor_adapter_revisions",
                name,
                definition,
            )
        _add_column(
            connection,
            "apify_key_pool_members",
            "role",
            "TEXT NOT NULL DEFAULT 'acquisition' "
            "CHECK(role IN ('acquisition', 'validation'))",
        )
        _add_column(
            connection,
            "apify_actor_runs",
            "purpose",
            "TEXT NOT NULL DEFAULT 'acquisition' "
            "CHECK(purpose IN ('acquisition', 'validation'))",
        )
        for name, definition in (
            (
                "preferred_candidate_id",
                "TEXT REFERENCES apify_actor_candidates(id) ON DELETE SET NULL",
            ),
            (
                "active_candidate_id",
                "TEXT REFERENCES apify_actor_candidates(id) ON DELETE SET NULL",
            ),
            ("watermark_latest_published_at", "TEXT"),
            (
                "watermark_item_id_hash",
                "TEXT CHECK(watermark_item_id_hash IS NULL OR ("
                "length(watermark_item_id_hash) = 64 AND "
                "watermark_item_id_hash NOT GLOB '*[^0-9a-f]*'))",
            ),
            ("watermark_last_advanced_at", "TEXT"),
            ("preference_suspended_at", "TEXT"),
            (
                "preference_recovery_successes",
                "INTEGER NOT NULL DEFAULT 0 "
                "CHECK(preference_recovery_successes BETWEEN 0 AND 2)",
            ),
        ):
            _add_column(
                connection,
                "apify_source_route_bindings",
                name,
                definition,
            )
        _rebuild_table(
            connection,
            "apify_actor_canary_batches",
            replacements=(
                (
                    "'initial_pool', 'complete_third', 'upgrade_legacy'",
                    "'initial_pool', 'complete_third', 'upgrade_legacy', "
                    "'compatibility_single'",
                ),
            ),
            index_sql=(
                """
                CREATE INDEX idx_apify_actor_canary_batches_route
                ON apify_actor_canary_batches(
                    workspace_id, route_id, created_at DESC
                )
                """,
            ),
        )
        _rebuild_table(
            connection,
            "apify_actor_pool_stages",
            replacements=(
                (
                    "'initial_pool', 'complete_third', 'upgrade_legacy'",
                    "'initial_pool', 'complete_third', 'upgrade_legacy', "
                    "'compatibility_single'",
                ),
                (
                    "CHECK(target_slot_count BETWEEN 2 AND 3)",
                    "CHECK(target_slot_count BETWEEN 1 AND 3)",
                ),
            ),
            index_sql=(
                """
                CREATE UNIQUE INDEX idx_apify_actor_pool_stages_active
                ON apify_actor_pool_stages(workspace_id, route_id)
                WHERE status NOT IN (
                    'applied', 'stale', 'failed', 'cancelled'
                )
                """,
            ),
        )
        connection.execute("DROP INDEX IF EXISTS idx_apify_key_pool_one_active")
        connection.execute(
            """
            CREATE UNIQUE INDEX idx_apify_key_pool_one_active
            ON apify_key_pool_members(workspace_id)
            WHERE status = 'active' AND role = 'acquisition'
            """
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX idx_apify_key_pool_one_validation
            ON apify_key_pool_members(workspace_id)
            WHERE role = 'validation'
            """
        )
        connection.execute(
            """
            UPDATE apify_actor_route_profiles
            SET min_runtime_healthy = 1, min_publishers = 1,
                updated_at = ?
            WHERE route_key = 'youtube/channel/items'
            """,
            (datetime.now(timezone.utc).isoformat(),),
        )
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _backfill(connection: sqlite3.Connection) -> None:
    now = datetime.now(timezone.utc).isoformat()
    bindings = connection.execute(
        """
        SELECT workspace_id, source_id
        FROM apify_source_route_bindings
        WHERE watermark_latest_published_at IS NULL
        """
    ).fetchall()
    for binding in bindings:
        row = connection.execute(
            """
            SELECT article_id, published_at
            FROM user_feed_items
            WHERE workspace_id = ? AND source_id = ?
              AND published_at IS NOT NULL
            ORDER BY published_at DESC, article_id DESC
            LIMIT 1
            """,
            (str(binding["workspace_id"]), str(binding["source_id"])),
        ).fetchone()
        if row is None:
            continue
        item_hash = hashlib.sha256(str(row["article_id"]).encode()).hexdigest()
        connection.execute(
            """
            UPDATE apify_source_route_bindings
            SET watermark_latest_published_at = ?,
                watermark_item_id_hash = ?,
                watermark_last_advanced_at = ?,
                updated_at = ?
            WHERE workspace_id = ? AND source_id = ?
            """,
            (
                str(row["published_at"]),
                item_hash,
                now,
                now,
                str(binding["workspace_id"]),
                str(binding["source_id"]),
            ),
        )
    failed = connection.execute(
        """
        SELECT validation.workspace_id, validation.route_id,
               revision.candidate_id, validation.revision_id,
               revision.actor_id, revision.build_id, revision.build_number,
               revision.manifest_hash, revision.input_schema_hash,
               revision.output_schema_hash, revision.pricing_json,
               COALESCE(validation.completed_at, validation.created_at) AS seen_at,
               COALESCE(validation.semantic_outcome, 'validation_failed') AS reason
        FROM apify_actor_validations AS validation
        JOIN apify_actor_adapter_revisions AS revision
          ON revision.workspace_id = validation.workspace_id
         AND revision.revision_id = validation.revision_id
        WHERE validation.status = 'failed'
          AND validation.failure_fingerprint IS NOT NULL
        """
    ).fetchall()
    for row in failed:
        connection.execute(
            """
            INSERT OR IGNORE INTO apify_actor_evaluation_history (
                evaluation_id, workspace_id, route_id, candidate_id,
                revision_id, evidence_fingerprint, policy_mode, stage,
                outcome, reason_code, deterministic, attempt_count,
                first_seen_at, last_seen_at
            ) VALUES (?, ?, ?, ?, ?, ?, 'standard', 'canary',
                      'failed', ?, ?, 1, ?, ?)
            """,
            (
                str(uuid.uuid4()),
                str(row["workspace_id"]),
                str(row["route_id"]),
                str(row["candidate_id"]),
                str(row["revision_id"]),
                _evidence_fingerprint(row),
                str(row["reason"]),
                int(str(row["reason"]) in _DETERMINISTIC_CANARY_FAILURES),
                str(row["seen_at"]),
                str(row["seen_at"]),
            ),
        )
    connection.commit()


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
            and apify_actor_resilience_v21_schema_shapes_valid(connection)
        )
        if not apply:
            return {"required": not already_ready, "database": str(database)}
        if _active_workers(database):
            raise RuntimeError("active workers must be stopped before migration")
        if _active_actor_work(database):
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
            "service-apify-actor-resilience-v21-",
            1,
        )
    )
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    connection = None
    try:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        _install_columns_and_constraints(connection)
        connection.close()
        connection = None

        store = ServiceStore(data_dir, db_path=database)
        store.initialize(prepare_apify_actor_resilience_v21=True)
        store.mark_apify_actor_resilience_v21_migrated()
        store.close()

        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        _backfill(connection)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        marker_valid = _marker_exists(connection)
        shape_valid = apify_actor_resilience_v21_schema_shapes_valid(connection)
        if integrity != "ok" or foreign_keys or not marker_valid or not shape_valid:
            raise RuntimeError(
                "post-migration integrity checks failed: "
                f"integrity={integrity!r} foreign_keys={len(foreign_keys)} "
                f"marker={marker_valid} shape={shape_valid}"
            )
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
