#!/usr/bin/env python3
"""Install bounded Actor validation tuning as global schema 22."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

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
    APIFY_ACTOR_VALIDATION_TUNING_MIGRATION_CHECKSUM,
    APIFY_ACTOR_VALIDATION_TUNING_MIGRATION_NAME,
    APIFY_ACTOR_VALIDATION_TUNING_MIGRATION_VERSION,
    apify_actor_manual_pool_selection_v19_schema_shapes_valid,
    apify_actor_validation_tuning_v20_schema_shapes_valid,
)


def _canonical_hash(payload: dict[str, Any]) -> str:
    return hashlib.sha256(
        json.dumps(
            payload,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
    ).hexdigest()


def _profile_hash(timeout_seconds: int, sample_items: int, cap: float) -> str:
    return _canonical_hash(
        {
            "timeout_seconds": int(timeout_seconds),
            "sample_items": int(sample_items),
            "max_charge_usd": round(float(cap), 6),
        }
    )


def _supports_sample_items(value: Any) -> bool:
    if isinstance(value, dict):
        if value.get("$ref") == "runtime.max_items":
            return True
        return any(_supports_sample_items(item) for item in value.values())
    if isinstance(value, list):
        return any(_supports_sample_items(item) for item in value)
    return False


def _marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(
        connection.execute(
            """
            SELECT 1 FROM schema_migrations
            WHERE version = ? AND name = ? AND checksum = ?
            """,
            (
                APIFY_ACTOR_VALIDATION_TUNING_MIGRATION_VERSION,
                APIFY_ACTOR_VALIDATION_TUNING_MIGRATION_NAME,
                APIFY_ACTOR_VALIDATION_TUNING_MIGRATION_CHECKSUM,
            ),
        ).fetchone()
    )


def _require_prerequisite(connection: sqlite3.Connection) -> None:
    marker = connection.execute(
        """
        SELECT 1 FROM schema_migrations
        WHERE version = 21
          AND name = 'apify_actor_manual_pool_selection_v19'
          AND checksum = ?
        """,
        (APIFY_ACTOR_MANUAL_POOL_SELECTION_MIGRATION_CHECKSUM,),
    ).fetchone()
    if not marker or not apify_actor_manual_pool_selection_v19_schema_shapes_valid(
        connection
    ):
        raise RuntimeError(
            "apify_actor_manual_pool_selection_v19 migration is required first"
        )


def _rebuild_table(
    connection: sqlite3.Connection,
    table: str,
    *,
    replacements: Iterable[tuple[str, str]],
    index_sql: Iterable[str],
) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if row is None or not row[0]:
        raise RuntimeError(f"missing required table: {table}")
    original = str(row[0])
    replacement_name = f"{table}_v20"
    create_sql, replacement_count = re.subn(
        rf'^CREATE\s+TABLE\s+"?{re.escape(table)}"?',
        f"CREATE TABLE {replacement_name}",
        original,
        count=1,
        flags=re.IGNORECASE,
    )
    if replacement_count != 1:
        raise RuntimeError(f"unexpected create statement for {table}")
    for before, after in replacements:
        changed = create_sql.replace(before, after)
        if changed == create_sql:
            raise RuntimeError(f"unexpected constraint for {table}: {before}")
        create_sql = changed
    connection.execute(f"DROP TABLE IF EXISTS {replacement_name}")
    connection.execute(create_sql)
    columns = [
        str(item[1])
        for item in connection.execute(f"PRAGMA table_info({table})").fetchall()
    ]
    copied_columns = ", ".join(columns)
    connection.execute(
        f"INSERT INTO {replacement_name} ({copied_columns}) "
        f"SELECT {copied_columns} FROM {table}"
    )
    connection.execute(f"DROP TABLE {table}")
    connection.execute(f"ALTER TABLE {replacement_name} RENAME TO {table}")
    for statement in index_sql:
        connection.execute(statement)


def _install(connection: sqlite3.Connection) -> None:
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        _rebuild_table(
            connection,
            "apify_actor_canary_batches",
            replacements=(
                ("max_total_charge_usd <= 0.06", "max_total_charge_usd <= 0.30"),
                ("per_candidate_cap_usd <= 0.02", "per_candidate_cap_usd <= 0.10"),
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
            "apify_actor_canary_batch_items",
            replacements=(("authorized_cap_usd <= 0.02", "authorized_cap_usd <= 0.10"),),
            index_sql=(
                """
                CREATE INDEX idx_apify_actor_canary_batch_items_status
                ON apify_actor_canary_batch_items(
                    workspace_id, batch_id, status, ordinal
                )
                """,
            ),
        )
        _rebuild_table(
            connection,
            "apify_actor_pool_stages",
            replacements=(("route_validation_cap_usd <= 0.06", "route_validation_cap_usd <= 0.30"),),
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
        for definition in (
            "validation_timeout_seconds INTEGER NOT NULL DEFAULT 300 CHECK(validation_timeout_seconds BETWEEN 180 AND 900)",
            "validation_sample_items INTEGER NOT NULL DEFAULT 1 CHECK(validation_sample_items IN (1, 3, 5))",
            "validation_profile_hash TEXT CHECK(validation_profile_hash IS NULL OR (length(validation_profile_hash) = 64 AND validation_profile_hash NOT GLOB '*[^0-9a-f]*'))",
            "failure_fingerprint TEXT CHECK(failure_fingerprint IS NULL OR (length(failure_fingerprint) = 64 AND failure_fingerprint NOT GLOB '*[^0-9a-f]*'))",
            "duration_seconds INTEGER CHECK(duration_seconds IS NULL OR duration_seconds >= 0)",
            "dataset_row_count INTEGER CHECK(dataset_row_count IS NULL OR dataset_row_count >= 0)",
            "mapped_item_count INTEGER CHECK(mapped_item_count IS NULL OR mapped_item_count >= 0)",
        ):
            connection.execute(
                f"ALTER TABLE apify_actor_validations ADD COLUMN {definition}"
            )
        connection.execute(
            """
            CREATE TABLE apify_actor_pool_stage_candidate_settings (
                workspace_id TEXT NOT NULL,
                stage_id TEXT NOT NULL,
                candidate_id TEXT NOT NULL,
                revision_id TEXT NOT NULL,
                timeout_seconds INTEGER NOT NULL
                    CHECK(timeout_seconds BETWEEN 180 AND 900),
                sample_items INTEGER NOT NULL
                    CHECK(sample_items IN (1, 3, 5)),
                max_charge_usd REAL NOT NULL
                    CHECK(max_charge_usd > 0 AND max_charge_usd <= 0.10),
                supports_sample_items INTEGER NOT NULL DEFAULT 0
                    CHECK(supports_sample_items IN (0, 1)),
                profile_hash TEXT NOT NULL CHECK(
                    length(profile_hash) = 64
                    AND profile_hash NOT GLOB '*[^0-9a-f]*'
                ),
                created_at TEXT NOT NULL,
                PRIMARY KEY(stage_id, revision_id),
                UNIQUE(workspace_id, stage_id, candidate_id),
                FOREIGN KEY(workspace_id, stage_id)
                    REFERENCES apify_actor_pool_stages(
                        workspace_id, stage_id
                    ) ON DELETE CASCADE,
                FOREIGN KEY(workspace_id, candidate_id)
                    REFERENCES apify_actor_candidates(
                        workspace_id, id
                    ) ON DELETE RESTRICT,
                FOREIGN KEY(workspace_id, revision_id)
                    REFERENCES apify_actor_adapter_revisions(
                        workspace_id, revision_id
                    ) ON DELETE RESTRICT
            )
            """
        )
        connection.execute(
            """
            CREATE INDEX idx_apify_actor_stage_candidate_settings
                ON apify_actor_pool_stage_candidate_settings(
                    workspace_id, stage_id, candidate_id
                )
            """
        )
        connection.execute(
            """
            CREATE INDEX idx_apify_actor_validation_failure_fingerprint
                ON apify_actor_validations(workspace_id, failure_fingerprint)
                WHERE failure_fingerprint IS NOT NULL
            """
        )
        validation_rows = connection.execute(
            """
            SELECT validation.validation_id, validation.workspace_id,
                   validation.route_id, validation.revision_id,
                   validation.kind, validation.target_fingerprint,
                   validation.status, validation.semantic_outcome,
                   validation.approved_max_cost_usd,
                   validation.created_at, validation.completed_at,
                   attempt.started_at AS attempt_started_at,
                   attempt.terminal_at AS attempt_terminal_at,
                   revision.candidate_id, revision.build_id,
                   revision.build_number, revision.manifest_hash
            FROM apify_actor_validations AS validation
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = validation.workspace_id
             AND revision.revision_id = validation.revision_id
            LEFT JOIN apify_actor_attempts AS attempt
              ON attempt.workspace_id = validation.workspace_id
             AND attempt.id = validation.attempt_id
            """
        ).fetchall()
        for row in validation_rows:
            cap = min(max(float(row["approved_max_cost_usd"] or 0.02), 0.000001), 0.10)
            profile_hash = _profile_hash(300, 1, cap)
            duration = None
            started_at = row["attempt_started_at"] or row["created_at"]
            completed_at = row["attempt_terminal_at"] or row["completed_at"]
            if completed_at:
                try:
                    started = datetime.fromisoformat(str(started_at).replace("Z", "+00:00"))
                    completed = datetime.fromisoformat(str(completed_at).replace("Z", "+00:00"))
                    duration = max(0, int(round((completed - started).total_seconds())))
                except ValueError:
                    duration = None
            semantic = str(row["semantic_outcome"] or "")
            dataset_rows = 0 if semantic in {"valid_empty", "suspicious_empty"} else None
            mapped_rows = 0 if dataset_rows == 0 else 1 if semantic == "valid_nonempty" else None
            failure_fingerprint = None
            if str(row["status"]) == "failed":
                failure_fingerprint = _canonical_hash(
                    {
                        "route_id": str(row["route_id"]),
                        "candidate_id": str(row["candidate_id"]),
                        "revision_id": str(row["revision_id"]),
                        "build_id": str(row["build_id"] or ""),
                        "build_number": str(row["build_number"] or ""),
                        "manifest_hash": str(row["manifest_hash"] or ""),
                        "target_fingerprint": str(row["target_fingerprint"] or ""),
                        "kind": str(row["kind"]),
                        "profile_hash": profile_hash,
                    }
                )
            connection.execute(
                """
                UPDATE apify_actor_validations
                SET validation_profile_hash = ?, duration_seconds = ?,
                    dataset_row_count = ?, mapped_item_count = ?,
                    failure_fingerprint = ?
                WHERE validation_id = ?
                """,
                (
                    profile_hash,
                    duration,
                    dataset_rows,
                    mapped_rows,
                    failure_fingerprint,
                    str(row["validation_id"]),
                ),
            )
        stage_rows = connection.execute(
            """
            SELECT stage.workspace_id, stage.stage_id,
                   item.authorized_cap_usd, revision.candidate_id,
                   revision.revision_id, revision.manifest_json,
                   stage.created_at
            FROM apify_actor_pool_stages AS stage
            JOIN apify_actor_canary_batch_items AS item
              ON item.workspace_id = stage.workspace_id
             AND item.batch_id = stage.initial_batch_id
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = item.workspace_id
             AND revision.revision_id = item.revision_id
            """
        ).fetchall()
        for row in stage_rows:
            try:
                manifest = json.loads(str(row["manifest_json"] or "{}"))
            except json.JSONDecodeError:
                manifest = {}
            cap = min(max(float(row["authorized_cap_usd"]), 0.000001), 0.10)
            connection.execute(
                """
                INSERT INTO apify_actor_pool_stage_candidate_settings (
                    workspace_id, stage_id, candidate_id, revision_id,
                    timeout_seconds, sample_items, max_charge_usd,
                    supports_sample_items, profile_hash, created_at
                ) VALUES (?, ?, ?, ?, 300, 1, ?, ?, ?, ?)
                """,
                (
                    str(row["workspace_id"]),
                    str(row["stage_id"]),
                    str(row["candidate_id"]),
                    str(row["revision_id"]),
                    cap,
                    int(_supports_sample_items(manifest.get("input", {}))),
                    _profile_hash(300, 1, cap),
                    str(row["created_at"]),
                ),
            )
        connection.execute(
            """
            INSERT INTO schema_migrations (version, name, checksum, applied_at)
            VALUES (?, ?, ?, ?)
            """,
            (
                APIFY_ACTOR_VALIDATION_TUNING_MIGRATION_VERSION,
                APIFY_ACTOR_VALIDATION_TUNING_MIGRATION_NAME,
                APIFY_ACTOR_VALIDATION_TUNING_MIGRATION_CHECKSUM,
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
            and apify_actor_validation_tuning_v20_schema_shapes_valid(connection)
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
            "service-apify-actor-validation-tuning-v20-",
            1,
        )
    )
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    connection = None
    try:
        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        _install(connection)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if (
            integrity != "ok"
            or foreign_keys
            or not apify_actor_validation_tuning_v20_schema_shapes_valid(connection)
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
