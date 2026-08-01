#!/usr/bin/env python3
"""Install the generic three-slot Apify ActorOps control plane safely."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import re
import sqlite3
import sys
import tempfile
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.migrate_user_feed_v2 import _active_workers
from src.storage.service_store import (
    APIFY_ACTOR_OPS_MIGRATION_CHECKSUM,
    APIFY_ACTOR_OPS_MIGRATION_NAME,
    APIFY_ACTOR_OPS_MIGRATION_VERSION,
    ServiceStore,
    WEBHOOK_PROVIDERS,
    WEBHOOK_PROVIDER_TRIGGER_NAMES,
    apify_actor_ops_v15_schema_shapes_valid,
)


V15_TABLES = {
    "apify_actor_route_profiles",
    "apify_actor_adapter_revisions",
    "apify_route_active_slots",
    "apify_actor_metadata_observations",
    "apify_source_route_bindings",
    "apify_actor_discovery_runs",
    "apify_actor_discovery_run_revisions",
    "apify_actor_validations",
    "apify_actor_discovery_settings",
}
V15_TRIGGERS = {
    "trg_apify_actor_adapter_revision_immutable",
    "trg_apify_actor_attempt_freeze_immutable",
    "trg_apify_actor_validation_attempt_delete",
    "trg_apify_actor_validation_source_delete",
    "trg_apify_discovery_secret_delete",
    "trg_apify_route_active_slots_validate_insert",
    "trg_apify_route_active_slots_validate_update",
}
V15_INDEXES = {
    "idx_apify_actor_candidates_workspace_id",
    "idx_source_catalog_workspace_id",
    "idx_fetch_jobs_workspace_id",
    "idx_secret_refs_workspace_id",
    "idx_apify_actor_attempts_workspace_id",
    "idx_apify_actor_metadata_observations_checked",
    "idx_apify_discovery_run_revisions_workspace",
    "idx_apify_actor_validations_approval",
}
V13_TABLES = {
    "apify_actor_routes",
    "apify_actor_candidates",
    "apify_actor_attempts",
    "apify_actor_target_health",
    "apify_actor_alert_settings",
    "apify_actor_alert_incidents",
    "apify_actor_alert_deliveries",
}
ATTEMPT_FREEZE_COLUMNS = {
    "adapter_revision_id",
    "build_id",
    "build_number",
    "manifest_hash",
    "target_fingerprint",
}
_ATTEMPT_V13_COLUMNS = (
    "id",
    "workspace_id",
    "route_key",
    "route_generation",
    "candidate_id",
    "source_id",
    "job_id",
    "attempt_group_id",
    "attempt_index",
    "status",
    "semantic_outcome",
    "reserved_usd",
    "actual_cost_usd",
    "cost_final",
    "last_error_code",
    "created_at",
    "started_at",
    "terminal_at",
    "updated_at",
)
_TERMINAL_ACTOR_OPS_JOB_STATUSES = frozenset(
    {"succeeded", "failed", "partial", "cancelled"}
)
_TERMINAL_DISCOVERY_STAGES = frozenset(
    {
        "awaiting_canary_approval",
        "blocked",
        "blocked_ai_unavailable",
        "cancelled",
        "candidate_shortfall",
        "completed",
        "failed",
    }
)


def _tables(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _versions(connection: sqlite3.Connection) -> set[int]:
    if "schema_migrations" not in _tables(connection):
        return set()
    return {
        int(row[0])
        for row in connection.execute(
            "SELECT version FROM schema_migrations"
        ).fetchall()
    }


def _v13_schema_ready(
    connection: sqlite3.Connection,
    *,
    versions: set[int] | None = None,
) -> bool:
    known_versions = versions if versions is not None else _versions(connection)
    if 13 not in known_versions or not V13_TABLES <= _tables(connection):
        return False
    return {
        "charge_reserved_usd",
        "charge_actual_usd",
        "charge_final",
    } <= _columns(connection, "apify_actor_runs")


def _v14_schema_ready(
    connection: sqlite3.Connection,
    *,
    versions: set[int] | None = None,
) -> bool:
    known_versions = versions if versions is not None else _versions(connection)
    if 14 not in known_versions:
        return False
    required_columns = {
        "webhook_provider",
        "webhook_signing_env_name",
        "webhook_signing_secret_digest",
    }
    placeholders = ",".join("?" for _provider in WEBHOOK_PROVIDERS)
    for table in (
        "user_notification_settings",
        "apify_actor_alert_settings",
    ):
        if table not in _tables(connection):
            return False
        if not required_columns <= _columns(connection, table):
            return False
        invalid = connection.execute(
            f"""
            SELECT 1 FROM {table}
            WHERE webhook_provider NOT IN ({placeholders})
               OR (
                    (webhook_signing_env_name IS NULL)
                    != (webhook_signing_secret_digest IS NULL)
               )
               OR (
                    webhook_signing_env_name IS NOT NULL
                    AND webhook_provider NOT IN (
                        'feishu_lark_v2', 'dingtalk'
                    )
               )
               OR (
                    webhook_signing_secret_digest IS NOT NULL
                    AND (
                        length(webhook_signing_secret_digest) != 64
                        OR webhook_signing_secret_digest
                            GLOB '*[^0-9a-f]*'
                    )
               )
            LIMIT 1
            """,
            tuple(sorted(WEBHOOK_PROVIDERS)),
        ).fetchone()
        if invalid:
            return False
    triggers = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        ).fetchall()
    }
    return WEBHOOK_PROVIDER_TRIGGER_NAMES <= triggers


def _v15_schema_ready(
    connection: sqlite3.Connection,
    *,
    require_marker: bool,
) -> bool:
    if require_marker and not connection.execute(
        """
        SELECT 1 FROM schema_migrations
        WHERE version = ? AND name = ? AND checksum = ?
        """,
        (
            APIFY_ACTOR_OPS_MIGRATION_VERSION,
            APIFY_ACTOR_OPS_MIGRATION_NAME,
            APIFY_ACTOR_OPS_MIGRATION_CHECKSUM,
        ),
    ).fetchone():
        return False
    if not V15_TABLES <= _tables(connection):
        return False
    if not {
        "target_fingerprint",
        "approval_key_hash",
        "approved_generation",
        "approved_max_cost_usd",
        "discovery_run_id",
    } <= _columns(connection, "apify_actor_validations"):
        return False
    if not {"candidate_count", "rejection_summary_json"} <= _columns(
        connection,
        "apify_actor_discovery_runs",
    ):
        return False
    if "max_candidates" not in _columns(
        connection,
        "apify_actor_discovery_settings",
    ):
        return False
    if "superseded_from_lifecycle" not in _columns(
        connection,
        "apify_actor_adapter_revisions",
    ):
        return False
    if not ATTEMPT_FREEZE_COLUMNS <= _columns(
        connection,
        "apify_actor_attempts",
    ):
        return False
    schema_row = connection.execute(
        """
        SELECT sql FROM sqlite_master
        WHERE type = 'table' AND name = 'apify_actor_attempts'
        """
    ).fetchone()
    normalized_sql = re.sub(
        r"\s+",
        "",
        str(schema_row[0] if schema_row else "").casefold(),
    )
    if "reserved_usd>=0andreserved_usd<=0.02" in normalized_sql:
        return False
    if not apify_actor_ops_v15_schema_shapes_valid(connection):
        return False
    indexes = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        ).fetchall()
    }
    if not V15_INDEXES <= indexes:
        return False
    invalid_slot_count = connection.execute(
        """
        SELECT 1
        FROM apify_actor_route_profiles AS profile
        LEFT JOIN apify_route_active_slots AS slot
          ON slot.route_id = profile.route_id
        GROUP BY profile.route_id
        HAVING COUNT(slot.slot_name) != 3
        LIMIT 1
        """
    ).fetchone()
    return invalid_slot_count is None


def _inspect(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "database_exists": False,
            "v13_migrated": False,
            "v13_ready": False,
            "v14_migrated": False,
            "v14_ready": False,
            "migrated": False,
            "schema_ready": False,
        }
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        versions = _versions(connection)
        actor_ops_migrated = bool(
            connection.execute(
                """
                SELECT 1 FROM schema_migrations
                WHERE version = ? AND name = ? AND checksum = ?
                """,
                (
                    APIFY_ACTOR_OPS_MIGRATION_VERSION,
                    APIFY_ACTOR_OPS_MIGRATION_NAME,
                    APIFY_ACTOR_OPS_MIGRATION_CHECKSUM,
                ),
            ).fetchone()
        )
        return {
            "database_exists": True,
            "v13_migrated": 13 in versions,
            "v13_ready": _v13_schema_ready(
                connection,
                versions=versions,
            ),
            "v14_migrated": 14 in versions,
            "v14_ready": _v14_schema_ready(
                connection,
                versions=versions,
            ),
            "migrated": actor_ops_migrated,
            "schema_ready": _v15_schema_ready(
                connection,
                require_marker=True,
            ),
        }
    finally:
        connection.close()


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"service-apify-actor-ops-v15-{stamp}.db"
    descriptor = os.open(
        target,
        os.O_CREAT | os.O_EXCL | os.O_RDWR,
        0o600,
    )
    os.close(descriptor)
    source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    succeeded = False
    try:
        source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        destination = sqlite3.connect(target)
        source.backup(destination)
        succeeded = True
    finally:
        if source is not None:
            source.close()
        if destination is not None:
            destination.close()
        if not succeeded:
            target.unlink(missing_ok=True)
    os.chmod(target, 0o600)
    return target


def _restore_database(
    *,
    backup_path: Path,
    db_path: Path,
    original_mode: int,
) -> None:
    """Restore a verified backup through an atomic same-directory replace."""

    descriptor, temporary_name = tempfile.mkstemp(
        prefix=f".{db_path.name}.v15-restore-",
        suffix=".db",
        dir=db_path.parent,
    )
    os.close(descriptor)
    temporary_path = Path(temporary_name)
    source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    try:
        source = sqlite3.connect(
            f"file:{backup_path}?mode=ro",
            uri=True,
        )
        destination = sqlite3.connect(temporary_path)
        source.backup(destination)
        foreign_key_errors = destination.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        integrity_row = destination.execute(
            "PRAGMA integrity_check"
        ).fetchone()
        integrity_check = str(
            integrity_row[0] if integrity_row else "unknown"
        )
        if foreign_key_errors or integrity_check.casefold() != "ok":
            raise RuntimeError("ActorOps v15 backup restore verification failed")
        destination.close()
        destination = None
        source.close()
        source = None
        os.chmod(temporary_path, original_mode)
        os.replace(temporary_path, db_path)
        for suffix in ("-wal", "-shm"):
            Path(f"{db_path}{suffix}").unlink(missing_ok=True)
        directory_fd = os.open(db_path.parent, os.O_RDONLY)
        try:
            os.fsync(directory_fd)
        finally:
            os.close(directory_fd)
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
        temporary_path.unlink(missing_ok=True)
        for suffix in ("-wal", "-shm"):
            Path(f"{temporary_path}{suffix}").unlink(missing_ok=True)


def _remove_failed_new_database(db_path: Path) -> None:
    for target in (
        db_path,
        Path(f"{db_path}-wal"),
        Path(f"{db_path}-shm"),
    ):
        target.unlink(missing_ok=True)


def _active_actor_ops_jobs(db_path: Path) -> list[str]:
    """Return active Discovery/Canary jobs that make offline repair unsafe."""

    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        if "fetch_jobs" not in _tables(connection):
            return []
        rows = connection.execute(
            """
            SELECT id
            FROM fetch_jobs
            WHERE status IN ('queued', 'running')
              AND (
                    job_type IN (
                        'apify_actor_discovery',
                        'apify_actor_validation'
                    )
                    OR (
                        job_type = 'source_test'
                        AND json_valid(payload_json)
                        AND json_extract(payload_json, '$.reason') =
                            'apify_actor_canary'
                    )
              )
            ORDER BY id
            """
        ).fetchall()
        return [str(row[0]) for row in rows]
    finally:
        connection.close()


def _repair_unsupported_youtube_profile_route(
    connection: sqlite3.Connection,
) -> dict[str, int]:
    """Delete the known-invalid YouTube Profile route only when provably empty."""

    result = {
        "invalid_routes_deleted": 0,
        "invalid_route_slots_deleted": 0,
        "invalid_route_discovery_runs_deleted": 0,
        "invalid_route_jobs_deleted": 0,
        "discovery_settings_reset": 0,
        "catalog_generation_bump": 0,
    }
    now = datetime.now(timezone.utc).isoformat()
    profiles = connection.execute(
        """
        SELECT route_id, workspace_id, route_key, generation
        FROM apify_actor_route_profiles
        WHERE platform = 'youtube'
          AND target_type = 'profile'
          AND capability = 'items'
        ORDER BY workspace_id, route_id
        """
    ).fetchall()
    for profile in profiles:
        route_id = str(profile["route_id"])
        workspace_id = str(profile["workspace_id"])
        route_key = str(profile["route_key"])
        slots = connection.execute(
            """
            SELECT candidate_id, revision_id
            FROM apify_route_active_slots
            WHERE workspace_id = ? AND route_id = ?
            ORDER BY slot_name
            """,
            (workspace_id, route_id),
        ).fetchall()
        if len(slots) != 3 or any(
            row["candidate_id"] is not None or row["revision_id"] is not None
            for row in slots
        ):
            raise RuntimeError(
                "unsafe youtube/profile/items repair: active slots are not empty"
            )

        material_checks = {
            "candidate": (
                "SELECT COUNT(*) FROM apify_actor_candidates "
                "WHERE workspace_id = ? AND route_key = ?",
                (workspace_id, route_key),
            ),
            "revision": (
                """
                SELECT COUNT(*)
                FROM apify_actor_adapter_revisions AS revision
                JOIN apify_actor_candidates AS candidate
                  ON candidate.workspace_id = revision.workspace_id
                 AND candidate.id = revision.candidate_id
                WHERE candidate.workspace_id = ? AND candidate.route_key = ?
                """,
                (workspace_id, route_key),
            ),
            "binding": (
                "SELECT COUNT(*) FROM apify_source_route_bindings "
                "WHERE workspace_id = ? AND route_id = ?",
                (workspace_id, route_id),
            ),
            "validation": (
                "SELECT COUNT(*) FROM apify_actor_validations "
                "WHERE workspace_id = ? AND route_id = ?",
                (workspace_id, route_id),
            ),
            "attempt_or_fee": (
                "SELECT COUNT(*) FROM apify_actor_attempts "
                "WHERE workspace_id = ? AND route_key = ?",
                (workspace_id, route_key),
            ),
            "target_health": (
                "SELECT COUNT(*) FROM apify_actor_target_health "
                "WHERE workspace_id = ? AND route_key = ?",
                (workspace_id, route_key),
            ),
            "metadata_observation": (
                "SELECT COUNT(*) FROM apify_actor_metadata_observations "
                "WHERE workspace_id = ? AND route_id = ?",
                (workspace_id, route_id),
            ),
        }
        for evidence, (query, parameters) in material_checks.items():
            count = int(connection.execute(query, parameters).fetchone()[0])
            if count:
                raise RuntimeError(
                    "unsafe youtube/profile/items repair: "
                    f"{evidence} evidence exists"
                )

        runs = connection.execute(
            """
            SELECT run_id, stage, query_count, candidate_count
            FROM apify_actor_discovery_runs
            WHERE workspace_id = ? AND route_id = ?
            ORDER BY run_id
            """,
            (workspace_id, route_id),
        ).fetchall()
        for run in runs:
            if (
                str(run["stage"]) not in _TERMINAL_DISCOVERY_STAGES
                or int(run["query_count"]) != 0
                or int(run["candidate_count"]) != 0
            ):
                raise RuntimeError(
                    "unsafe youtube/profile/items repair: discovery work exists"
                )
            association_count = int(
                connection.execute(
                    """
                    SELECT COUNT(*)
                    FROM apify_actor_discovery_run_revisions
                    WHERE workspace_id = ? AND run_id = ?
                    """,
                    (workspace_id, str(run["run_id"])),
                ).fetchone()[0]
            )
            if association_count:
                raise RuntimeError(
                    "unsafe youtube/profile/items repair: discovery revisions exist"
                )

        run_ids = [str(run["run_id"]) for run in runs]
        jobs: list[sqlite3.Row] = []
        if run_ids:
            placeholders = ", ".join("?" for _run_id in run_ids)
            jobs = connection.execute(
                f"""
                SELECT id, status
                FROM fetch_jobs
                WHERE workspace_id = ?
                  AND job_type = 'apify_actor_discovery'
                  AND json_valid(payload_json)
                  AND json_extract(payload_json, '$.run_id')
                      IN ({placeholders})
                ORDER BY id
                """,
                (workspace_id, *run_ids),
            ).fetchall()
        if any(
            str(job["status"]) not in _TERMINAL_ACTOR_OPS_JOB_STATUSES
            for job in jobs
        ):
            raise RuntimeError(
                "unsafe youtube/profile/items repair: discovery job is active"
            )

        for job in jobs:
            connection.execute(
                "DELETE FROM fetch_jobs WHERE id = ?",
                (str(job["id"]),),
            )
        connection.execute(
            """
            DELETE FROM apify_actor_discovery_runs
            WHERE workspace_id = ? AND route_id = ?
            """,
            (workspace_id, route_id),
        )
        connection.execute(
            """
            DELETE FROM apify_route_active_slots
            WHERE workspace_id = ? AND route_id = ?
            """,
            (workspace_id, route_id),
        )
        connection.execute(
            """
            DELETE FROM apify_actor_route_profiles
            WHERE workspace_id = ? AND route_id = ?
            """,
            (workspace_id, route_id),
        )
        connection.execute(
            """
            DELETE FROM apify_actor_routes
            WHERE workspace_id = ? AND route_key = ?
            """,
            (workspace_id, route_key),
        )
        generation_bump = int(profile["generation"]) + 1
        cursor = connection.execute(
            """
            UPDATE apify_actor_route_profiles
            SET generation = generation + ?, updated_at = ?
            WHERE workspace_id = ?
              AND platform = 'youtube'
              AND target_type = 'channel'
              AND capability = 'items'
            """,
            (generation_bump, now, workspace_id),
        )
        if cursor.rowcount != 1:
            raise RuntimeError(
                "youtube/channel/items route is required for catalog CAS repair"
            )
        result["invalid_routes_deleted"] += 1
        result["invalid_route_slots_deleted"] += len(slots)
        result["invalid_route_discovery_runs_deleted"] += len(runs)
        result["invalid_route_jobs_deleted"] += len(jobs)
        result["catalog_generation_bump"] += generation_bump

    reset = connection.execute(
        """
        UPDATE apify_actor_discovery_settings
        SET enabled = 0, ai_provider = '', ai_model = '',
            secret_ref_id = NULL, generation = generation + 1,
            updated_at = ?
        WHERE enabled != 0 OR ai_provider != '' OR ai_model != ''
           OR secret_ref_id IS NOT NULL
        """,
        (now,),
    )
    result["discovery_settings_reset"] = int(reset.rowcount)
    return result


def _rows_digest(
    connection: sqlite3.Connection,
    table: str,
    *,
    columns: tuple[str, ...] | None = None,
    where: str = "",
) -> tuple[int, str]:
    selected = columns or tuple(
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    )
    query = f"SELECT {', '.join(selected)} FROM {table}"
    if where:
        query += f" WHERE {where}"
    rows = [
        [
            row[index]
            for index in range(len(selected))
        ]
        for row in connection.execute(query).fetchall()
    ]
    encoded_rows = sorted(
        json.dumps(
            row,
            ensure_ascii=False,
            sort_keys=True,
            separators=(",", ":"),
        )
        for row in rows
    )
    digest = hashlib.sha256(
        "\n".join(encoded_rows).encode("utf-8")
    ).hexdigest()
    return len(rows), digest


def _legacy_history_snapshot(
    connection: sqlite3.Connection,
) -> dict[str, tuple[int, str]]:
    return {
        "routes": _rows_digest(
            connection,
            "apify_actor_routes",
        ),
        "candidates": _rows_digest(
            connection,
            "apify_actor_candidates",
        ),
        "attempts": _rows_digest(
            connection,
            "apify_actor_attempts",
            columns=_ATTEMPT_V13_COLUMNS,
        ),
        "target_health": _rows_digest(
            connection,
            "apify_actor_target_health",
        ),
        "actor_runs": _rows_digest(
            connection,
            "apify_actor_runs",
        ),
        "alert_settings": _rows_digest(
            connection,
            "apify_actor_alert_settings",
        ),
        "alert_incidents": _rows_digest(
            connection,
            "apify_actor_alert_incidents",
        ),
        "alert_deliveries": _rows_digest(
            connection,
            "apify_actor_alert_deliveries",
        ),
    }


def migrate_apify_actor_ops_v15(
    *,
    data_dir: Path | str,
    backup_dir: Path | str,
    apply: bool,
) -> dict[str, Any]:
    data_path = Path(data_dir)
    db_path = data_path / "service.db"
    inspection = _inspect(db_path)
    result: dict[str, Any] = {
        "applied": False,
        "database_exists": inspection["database_exists"],
        "v13_migrated": inspection["v13_migrated"],
        "v13_ready": inspection["v13_ready"],
        "v14_migrated": inspection["v14_migrated"],
        "v14_ready": inspection["v14_ready"],
        "migrated": inspection["migrated"],
        "schema_ready": inspection["schema_ready"],
        "backup_path": None,
        "invalid_routes_deleted": 0,
        "invalid_route_slots_deleted": 0,
        "invalid_route_discovery_runs_deleted": 0,
        "invalid_route_jobs_deleted": 0,
        "discovery_settings_reset": 0,
        "catalog_generation_bump": 0,
    }
    if not apply:
        return result
    if db_path.exists() and not inspection["v13_ready"]:
        raise RuntimeError(
            "apply and verify Apify Actor routing v13 before ActorOps v15"
        )
    if db_path.exists() and not inspection["v14_ready"]:
        raise RuntimeError(
            "apply and verify Webhook providers v14 before ActorOps v15"
        )
    if inspection["migrated"] and inspection["schema_ready"]:
        result["reason"] = "already_migrated"
        return result
    if db_path.exists() and _active_workers(db_path):
        raise RuntimeError(
            "stop all horizon-worker processes and wait for the heartbeat "
            "safety window before applying ActorOps v15"
        )
    if db_path.exists():
        active_actor_ops_jobs = _active_actor_ops_jobs(db_path)
        if active_actor_ops_jobs:
            raise RuntimeError(
                "stop active Actor discovery/Canary jobs before applying "
                "ActorOps v15"
            )

    legacy_snapshot: dict[str, tuple[int, str]] | None = None
    database_existed = db_path.exists()
    original_mode = (
        db_path.stat().st_mode & 0o777
        if database_existed
        else 0o600
    )
    if database_existed:
        before = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            legacy_snapshot = _legacy_history_snapshot(before)
        finally:
            before.close()
    data_path.mkdir(parents=True, exist_ok=True)
    backup_path = (
        _backup_database(db_path, Path(backup_dir))
        if database_existed
        else None
    )

    store = ServiceStore(data_path)
    connection: sqlite3.Connection | None = None
    try:
        store.initialize(prepare_apify_actor_ops_v15=True)
        connection = store.connect()
        if legacy_snapshot is not None:
            after_snapshot = _legacy_history_snapshot(connection)
            if after_snapshot != legacy_snapshot:
                raise RuntimeError(
                    "legacy Apify routing history changed during ActorOps v15"
                )
        connection.execute("BEGIN IMMEDIATE")
        if not _v15_schema_ready(connection, require_marker=False):
            raise RuntimeError("ActorOps v15 schema verification failed")
        repair_result = _repair_unsupported_youtube_profile_route(connection)
        foreign_key_errors = connection.execute(
            "PRAGMA foreign_key_check"
        ).fetchall()
        integrity_row = connection.execute(
            "PRAGMA integrity_check"
        ).fetchone()
        integrity_check = str(
            integrity_row[0] if integrity_row else "unknown"
        )
        if foreign_key_errors:
            raise RuntimeError(
                f"foreign key check failed: {len(foreign_key_errors)} row(s)"
            )
        if integrity_check.casefold() != "ok":
            raise RuntimeError(
                f"integrity check failed: {integrity_check}"
            )
        store.mark_apify_actor_ops_v15_migrated(commit=False)
        connection.commit()
        if store.apify_actor_ops_v15_migration_required():
            raise RuntimeError("ActorOps v15 marker verification failed")
        profile_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM apify_actor_route_profiles"
            ).fetchone()[0]
        )
        revision_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM apify_actor_adapter_revisions"
            ).fetchone()[0]
        )
        slot_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM apify_route_active_slots"
            ).fetchone()[0]
        )
        binding_count = int(
            connection.execute(
                "SELECT COUNT(*) FROM apify_source_route_bindings"
            ).fetchone()[0]
        )
    except Exception:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        store.close()
        try:
            if backup_path is not None:
                _restore_database(
                    backup_path=backup_path,
                    db_path=db_path,
                    original_mode=original_mode,
                )
            elif not database_existed:
                _remove_failed_new_database(db_path)
        except Exception as restore_error:
            raise RuntimeError(
                "ActorOps v15 failed and the pre-migration database "
                "could not be restored"
            ) from restore_error
        raise
    else:
        store.close()

    result.update(
        {
            "applied": True,
            "migrated": True,
            "schema_ready": True,
            "backup_path": str(backup_path) if backup_path else None,
            "route_profile_count": profile_count,
            "revision_count": revision_count,
            "slot_count": slot_count,
            "source_binding_count": binding_count,
            "integrity_check": integrity_check,
            "foreign_key_errors": len(foreign_key_errors),
            **repair_result,
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or apply the generic Apify ActorOps v15 migration"
        )
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--backup-dir", default="data/backups")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            migrate_apify_actor_ops_v15(
                data_dir=args.data_dir,
                backup_dir=args.backup_dir,
                apply=bool(args.apply),
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
