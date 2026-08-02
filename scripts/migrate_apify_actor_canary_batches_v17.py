#!/usr/bin/env python3
"""Install batch Canary approval ledgers and repair proven no-start costs."""

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

from scripts.migrate_apify_actor_ops_v15 import (  # noqa: E402
    _backup_database,
    _restore_database,
)
from scripts.migrate_user_feed_v2 import _active_workers  # noqa: E402
from src.storage.service_store import (  # noqa: E402
    ServiceStore,
    apify_actor_canary_batches_v17_schema_shapes_valid,
    apify_discovery_limits_v16_schema_shapes_valid,
)


_ACTIVE_ACTOR_JOB_TYPES = (
    "apify_actor_discovery",
    "apify_actor_validation",
    "apify_actor_canary_batch",
)


def _active_jobs(database: Path) -> list[dict[str, str]]:
    connection = sqlite3.connect(f"file:{database}?mode=ro", uri=True)
    connection.row_factory = sqlite3.Row
    try:
        placeholders = ",".join("?" for _value in _ACTIVE_ACTOR_JOB_TYPES)
        rows = connection.execute(
            f"""
            SELECT id, job_type, status
            FROM fetch_jobs
            WHERE job_type IN ({placeholders})
              AND status IN ('queued', 'running')
            ORDER BY created_at, id
            """,
            _ACTIVE_ACTOR_JOB_TYPES,
        ).fetchall()
        return [dict(row) for row in rows]
    finally:
        connection.close()


def _latest_actor_run(
    connection: sqlite3.Connection,
    attempt_id: str,
) -> sqlite3.Row | None:
    return connection.execute(
        """
        SELECT *
        FROM apify_actor_runs
        WHERE logical_run_id = ?
        ORDER BY updated_at DESC, id DESC
        LIMIT 1
        """,
        (attempt_id,),
    ).fetchone()


def _repair_validation_costs(connection: sqlite3.Connection) -> dict[str, int]:
    """Normalize authorization caps away from actual-cost evidence.

    A deterministic start rejection is free only when the durable Run ledger
    proves that no remote Run or Dataset identifier was ever registered.
    """

    now = datetime.now(timezone.utc).isoformat()
    counts = {
        "no_start_repaired": 0,
        "final_costs_reconciled": 0,
        "unstarted_finalized": 0,
        "revisions_stopped": 0,
    }
    connection.execute(
        """
        UPDATE apify_actor_validations
        SET cost_final = 0,
            counts_toward_canary = CASE
                WHEN attempt_id IS NULL THEN 0 ELSE 1 END
        """
    )
    validation_rows = connection.execute(
        """
        SELECT validation_id, revision_id, attempt_id, status,
               cost_usd, approved_max_cost_usd
        FROM apify_actor_validations
        ORDER BY created_at, validation_id
        """
    ).fetchall()
    for validation in validation_rows:
        validation_id = str(validation["validation_id"])
        attempt_id = (
            str(validation["attempt_id"])
            if validation["attempt_id"] is not None
            else None
        )
        if attempt_id is None:
            if str(validation["status"]) in {"failed", "cancelled"}:
                connection.execute(
                    """
                    UPDATE apify_actor_validations
                    SET cost_usd = 0, cost_final = 1,
                        counts_toward_canary = 0
                    WHERE validation_id = ?
                    """,
                    (validation_id,),
                )
                counts["unstarted_finalized"] += 1
            else:
                connection.execute(
                    """
                    UPDATE apify_actor_validations
                    SET cost_usd = NULL, cost_final = 0,
                        counts_toward_canary = 0
                    WHERE validation_id = ?
                    """,
                    (validation_id,),
                )
            continue

        attempt = connection.execute(
            """
            SELECT status, actual_cost_usd, cost_final
            FROM apify_actor_attempts
            WHERE id = ?
            """,
            (attempt_id,),
        ).fetchone()
        actor_run = _latest_actor_run(connection, attempt_id)
        proven_no_start = bool(
            actor_run is not None
            and str(actor_run["status"]) == "start_rejected"
            and actor_run["remote_run_id"] is None
            and actor_run["dataset_id"] is None
            and float(actor_run["charge_reserved_usd"] or 0) == 0
            and actor_run["charge_actual_usd"] in {None, 0, 0.0}
        )
        if proven_no_start:
            connection.execute(
                """
                UPDATE apify_actor_runs
                SET charge_reserved_usd = 0, charge_actual_usd = 0,
                    charge_final = 1, updated_at = ?
                WHERE id = ?
                """,
                (now, str(actor_run["id"])),
            )
            connection.execute(
                """
                UPDATE apify_actor_attempts
                SET status = 'cancelled', actual_cost_usd = 0,
                    cost_final = 1,
                    last_error_code = COALESCE(
                        last_error_code, 'apify_actor_revision_unavailable'
                    ),
                    updated_at = ?
                WHERE id = ? AND status != 'running'
                """,
                (now, attempt_id),
            )
            connection.execute(
                """
                UPDATE apify_actor_validations
                SET cost_usd = 0, cost_final = 1,
                    counts_toward_canary = 0,
                    semantic_outcome = 'apify_actor_revision_unavailable'
                WHERE validation_id = ?
                """,
                (validation_id,),
            )
            revision = connection.execute(
                """
                SELECT candidate_id, lifecycle
                FROM apify_actor_adapter_revisions
                WHERE revision_id = ?
                """,
                (str(validation["revision_id"]),),
            ).fetchone()
            if revision is not None and str(revision["lifecycle"]) in {
                "static_valid",
                "probationary",
            }:
                next_lifecycle = (
                    "rejected"
                    if str(revision["lifecycle"]) == "static_valid"
                    else "quarantined"
                )
                connection.execute(
                    """
                    UPDATE apify_actor_adapter_revisions
                    SET lifecycle = ?
                    WHERE revision_id = ?
                    """,
                    (next_lifecycle, str(validation["revision_id"])),
                )
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET state = 'disabled',
                        last_error_code = 'apify_actor_revision_unavailable',
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now, str(revision["candidate_id"])),
                )
                counts["revisions_stopped"] += 1
            counts["no_start_repaired"] += 1
            continue

        final_cost: float | None = None
        if (
            actor_run is not None
            and int(actor_run["charge_final"] or 0) == 1
            and actor_run["charge_actual_usd"] is not None
        ):
            final_cost = float(actor_run["charge_actual_usd"])
        elif (
            attempt is not None
            and int(attempt["cost_final"] or 0) == 1
            and attempt["actual_cost_usd"] is not None
        ):
            final_cost = float(attempt["actual_cost_usd"])
        if final_cost is not None:
            connection.execute(
                """
                UPDATE apify_actor_validations
                SET cost_usd = ?, cost_final = 1,
                    counts_toward_canary = 1
                WHERE validation_id = ?
                """,
                (final_cost, validation_id),
            )
            counts["final_costs_reconciled"] += 1
        else:
            no_started_run = actor_run is None or (
                actor_run["remote_run_id"] is None
                and actor_run["dataset_id"] is None
            )
            cancelled_without_start = bool(
                attempt is not None
                and str(attempt["status"]) == "cancelled"
                and no_started_run
            )
            connection.execute(
                """
                UPDATE apify_actor_validations
                SET cost_usd = ?, cost_final = ?,
                    counts_toward_canary = ?
                WHERE validation_id = ?
                """,
                (
                    0 if cancelled_without_start else None,
                    int(cancelled_without_start),
                    int(not cancelled_without_start),
                    validation_id,
                ),
            )
    return counts


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
        if not apify_discovery_limits_v16_schema_shapes_valid(connection):
            raise RuntimeError("apify_discovery_limits_v16 migration is required first")
        marker = connection.execute(
            """
            SELECT 1 FROM schema_migrations
            WHERE version = 19
              AND name = 'apify_actor_canary_batches_v17'
            """
        ).fetchone()
        already_ready = bool(
            marker
            and apify_actor_canary_batches_v17_schema_shapes_valid(connection)
        )
        if not apply:
            return {"required": not already_ready, "database": str(database)}
        workers = _active_workers(database)
        jobs = _active_jobs(database)
        if workers:
            raise RuntimeError("active workers must be stopped before migration")
        if jobs:
            raise RuntimeError("active ActorOps jobs must finish before migration")
    finally:
        connection.close()

    destination = backup_dir or data_dir / "backups"
    original_mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, destination)
    backup = raw_backup.with_name(
        raw_backup.name.replace(
            "service-apify-actor-ops-v15-",
            "service-apify-actor-canary-batches-v17-",
            1,
        )
    )
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    repair_counts: dict[str, int] = {}
    store: ServiceStore | None = None
    connection: sqlite3.Connection | None = None
    try:
        store = ServiceStore(data_dir)
        store.initialize(prepare_apify_actor_canary_batches_v17=True)
        connection = store.connect()
        if not apify_actor_canary_batches_v17_schema_shapes_valid(connection):
            raise RuntimeError("v17 batch schema validation failed")
        repair_counts = _repair_validation_costs(connection)
        store.mark_apify_actor_canary_batches_v17_migrated(commit=False)
        integrity = connection.execute("PRAGMA integrity_check").fetchone()[0]
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity != "ok" or foreign_keys:
            raise RuntimeError("post-migration integrity checks failed")
        connection.commit()
        store.close()
    except Exception:
        if connection is not None and connection.in_transaction:
            connection.rollback()
        if store is not None:
            store.close()
        try:
            _restore_database(
                backup_path=backup,
                db_path=database,
                original_mode=original_mode,
            )
        except Exception as restore_error:
            raise RuntimeError(
                "v17 migration failed and the pre-migration database "
                "could not be restored"
            ) from restore_error
        raise
    os.chmod(backup, 0o600)
    return {
        "required": False,
        "applied": True,
        "backup": str(backup),
        "backup_mode": oct(backup.stat().st_mode & 0o777),
        "integrity_check": "ok",
        "foreign_key_violations": 0,
        "repairs": repair_counts,
        "applied_at": datetime.now(timezone.utc).isoformat(),
    }


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--data-dir", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(json.dumps(migrate(args.data_dir, apply=args.apply, backup_dir=args.backup_dir)))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
