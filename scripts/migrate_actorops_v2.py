#!/usr/bin/env python3
"""Install the inert ActorOps v2 domain schema as global version 26."""

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
from src.storage.actorops_v2_backfill import (
    backfill_v1,
    legacy_fingerprints,
)
from src.storage.actorops_v2_schema import (
    ACTOROPS_V2_MIGRATION_CHECKSUM,
    ACTOROPS_V2_MIGRATION_NAME,
    ACTOROPS_V2_MIGRATION_VERSION,
    existing_v2_tables,
    install_schema,
    mark_migrated,
    migration_marker_exists,
    prerequisite_ready,
    schema_shapes_valid,
)


_BLOCKER_QUERIES = {
    "jobs": """SELECT COUNT(*) FROM fetch_jobs
        WHERE job_type IN ('apify_actor_discovery','apify_actor_validation',
            'apify_actor_canary_batch','apify_actor_freshness_check')
          AND status IN ('queued','running')""",
    "attempts": """SELECT COUNT(*) FROM apify_actor_attempts
        WHERE status NOT IN (
            'succeeded','valid_empty','actor_failed','target_failed',
            'failed','cancelled'
        )""",
    "attempt_costs": """SELECT COUNT(*) FROM apify_actor_attempts
        WHERE cost_final = 0 AND (actual_cost_usd IS NOT NULL OR reserved_usd > 0)
          AND NOT (
              status IN ('succeeded','valid_empty','actor_failed','target_failed','failed','cancelled')
              AND (
                  (
                      COALESCE(last_error_code, '') = 'apify_historical_cost_quarantined'
                      AND EXISTS (
                          SELECT 1 FROM apify_actor_runs AS run
                          WHERE run.logical_run_id = apify_actor_attempts.id
                            AND run.remote_run_id IS NOT NULL
                            AND run.status IN ('succeeded','failed','aborted','timed_out','cancelled','start_rejected')
                            AND run.last_error_code = 'apify_historical_cost_quarantined'
                      )
                  )
                  OR (
                      COALESCE(last_error_code, '') = 'apify_historical_attempt_ledger_missing'
                      AND NOT EXISTS (
                          SELECT 1 FROM apify_actor_runs AS run
                          WHERE run.logical_run_id = apify_actor_attempts.id
                            AND run.remote_run_id IS NOT NULL
                      )
                  )
              )
          )""",
    "runs": """SELECT COUNT(*) FROM apify_actor_runs
        WHERE status IN ('reserved','starting','running','aborting','start_outcome_unknown')""",
    "run_costs": """SELECT COUNT(*) FROM apify_actor_runs
        WHERE charge_final = 0
          AND (remote_run_id IS NOT NULL OR charge_actual_usd IS NOT NULL
               OR charge_reserved_usd > 0)
          AND NOT (
              status IN ('succeeded','failed','aborted','timed_out','cancelled','start_rejected')
              AND remote_run_id IS NOT NULL
              AND COALESCE(last_error_code, '') = 'apify_historical_cost_quarantined'
          )""",
    "validations": """SELECT COUNT(*) FROM apify_actor_validations
        WHERE status IN ('queued','running','blocked_unknown_start')""",
    "batches": """SELECT COUNT(*) FROM apify_actor_canary_batches
        WHERE status IN ('queued','preflighting','running','blocked_unknown_start')""",
    "stages": """SELECT COUNT(*) FROM apify_actor_pool_stages
        WHERE status IN ('queued','validating_route','validating_sources',
                         'apply_ready','blocked_unknown_start')""",
    "freshness": """SELECT COUNT(*) FROM apify_actor_freshness_checks
        WHERE status IN ('queued','running','blocked_unknown_start')""",
}


def _connect(database: Path, *, read_only: bool) -> sqlite3.Connection:
    connection = sqlite3.connect(
        f"file:{database}?mode=ro" if read_only else database,
        uri=read_only,
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA foreign_keys = ON")
    return connection


def _version_26_row(connection: sqlite3.Connection):
    return connection.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version = ?",
        (ACTOROPS_V2_MIGRATION_VERSION,),
    ).fetchone()


def _assert_migration_state(connection: sqlite3.Connection) -> str:
    row = _version_26_row(connection)
    tables = existing_v2_tables(connection)
    if row is not None:
        if (
            str(row["name"]) != ACTOROPS_V2_MIGRATION_NAME
            or str(row["checksum"]) != ACTOROPS_V2_MIGRATION_CHECKSUM
        ):
            raise RuntimeError("global schema migration version 26 is already occupied")
        if not schema_shapes_valid(connection):
            raise RuntimeError("ActorOps v2 marker exists with an invalid schema")
        return "ready"
    if tables:
        raise RuntimeError("partial ActorOps v2 schema must be restored before migration")
    if not prerequisite_ready(connection):
        raise RuntimeError("global schema 24 is required before ActorOps v2")
    return "required"


def migration_blockers(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        name: int(connection.execute(query).fetchone()[0])
        for name, query in _BLOCKER_QUERIES.items()
    }


def quarantine_summary(connection: sqlite3.Connection) -> dict[str, Any]:
    """Expose retained historical exposure without treating it as settled cost."""

    run_upper = float(connection.execute(
        """SELECT COALESCE(SUM(charge_reserved_usd), 0) FROM apify_actor_runs
           WHERE charge_final=0 AND last_error_code='apify_historical_cost_quarantined'
             AND status IN ('succeeded','failed','aborted','timed_out','cancelled','start_rejected')"""
    ).fetchone()[0] or 0)
    orphan_upper = float(connection.execute(
        """SELECT COALESCE(SUM(reserved_usd), 0) FROM apify_actor_attempts AS attempt
           WHERE cost_final=0 AND last_error_code='apify_historical_attempt_ledger_missing'
             AND NOT EXISTS (
                 SELECT 1 FROM apify_actor_runs AS run
                 WHERE run.logical_run_id=attempt.id AND run.remote_run_id IS NOT NULL
             )"""
    ).fetchone()[0] or 0)
    batch_upper = float(connection.execute(
        """SELECT COALESCE(SUM(max_total_charge_usd), 0) FROM apify_actor_canary_batches
           WHERE status='partial' AND stop_reason='apify_historical_evidence_unrecoverable'
             AND cost_final=0"""
    ).fetchone()[0] or 0)
    return {
        "quarantined_runs": int(connection.execute(
            "SELECT COUNT(*) FROM apify_actor_runs WHERE last_error_code='apify_historical_cost_quarantined'"
        ).fetchone()[0]),
        "quarantined_attempts": int(connection.execute(
            "SELECT COUNT(*) FROM apify_actor_attempts WHERE last_error_code='apify_historical_attempt_ledger_missing'"
        ).fetchone()[0]),
        "historical_unknown_upper_bound_usd": round(run_upper + orphan_upper + batch_upper, 6),
    }


def _preview(database: Path) -> dict[str, Any]:
    connection = _connect(database, read_only=True)
    try:
        state = _assert_migration_state(connection)
        if state == "ready":
            return {"status": "already_migrated", "required": False}
        blockers = migration_blockers(connection)
        quarantine = quarantine_summary(connection)
    finally:
        connection.close()
    workers = active_workers_fail_closed(database)
    if workers:
        blockers["workers"] = len(workers)
    blocking = {name: count for name, count in blockers.items() if count}
    return {
        "status": "blocked" if blocking else "migration_required",
        "required": True,
        "blocker_counts": blocking,
        "quarantine": quarantine,
        "global_24_ready": True,
        "global_25_ignored": True,
    }


def migrate(
    data_dir: Path,
    *,
    apply: bool,
    backup_dir: Path | None = None,
) -> dict[str, Any]:
    database = data_dir / "service.db"
    if not database.exists():
        raise RuntimeError("service database does not exist")
    preview = _preview(database)
    if not apply or preview["status"] == "already_migrated":
        return preview
    if preview["status"] == "blocked":
        raise RuntimeError("ActorOps work must settle before migration")

    destination = backup_dir or data_dir / "backups"
    original_mode = database.stat().st_mode & 0o777
    raw_backup = _backup_database(database, destination)
    backup = raw_backup.with_name(
        raw_backup.name.replace(
            "service-apify-actor-ops-v15-", "service-actorops-v2-v26-", 1
        )
    )
    raw_backup.replace(backup)
    os.chmod(backup, 0o600)
    before: dict[str, str] = {}
    counts: dict[str, int] = {}
    connection: sqlite3.Connection | None = None
    try:
        connection = _connect(database, read_only=False)
        _assert_migration_state(connection)
        if active_workers_fail_closed(database):
            raise RuntimeError("ActorOps work must settle before migration")
        before = legacy_fingerprints(connection)
        connection.execute("BEGIN IMMEDIATE")
        if any(migration_blockers(connection).values()):
            raise RuntimeError("ActorOps work must settle before migration")
        install_schema(connection)
        counts = backfill_v1(connection)
        mark_migrated(connection)
        connection.commit()
        after = legacy_fingerprints(connection)
        if after != before:
            raise RuntimeError("ActorOps v1 facts changed during v2 backfill")
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        valid = migration_marker_exists(connection) and schema_shapes_valid(connection)
        if integrity != "ok" or foreign_keys or not valid:
            raise RuntimeError(
                "post-migration checks failed: "
                f"integrity={integrity!r} foreign_keys={len(foreign_keys)} valid={valid}"
            )
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
        "required": False,
        "backup": str(backup),
        "backup_mode": oct(backup.stat().st_mode & 0o777),
        "backfill_counts": counts,
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
    try:
        result = migrate(
            args.data_dir, apply=bool(args.apply), backup_dir=args.backup_dir
        )
    except RuntimeError as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
