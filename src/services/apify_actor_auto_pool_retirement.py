"""Offline inspection and retirement for the unpublished auto-pool workflow."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


RETIREMENT_CODE = "apify_actor_auto_pool_retired"
AUTO_DISCOVERY_REASONS = frozenset({"auto_pool", "auto_pool_replenishment"})
ACTIVE_DISCOVERY_STAGES = frozenset(
    {"queued", "searching", "metadata", "ranking", "static_validation", "input_validation"}
)
NONTERMINAL_BATCH_STATUSES = frozenset({"queued", "preflighting", "running"})
NONTERMINAL_ACTOR_RUN_STATUSES = frozenset(
    {"reserved", "starting", "running", "aborting", "start_outcome_unknown"}
)
UNKNOWN_START_VALUES = frozenset(
    {"blocked_unknown_start", "start_outcome_unknown", "apify_start_outcome_unknown"}
)


def _database(data_dir: Path | str) -> Path:
    return Path(data_dir) / "service.db"


def _ro_connect(database: Path) -> sqlite3.Connection:
    if not database.is_file():
        raise RuntimeError("service database does not exist")
    wal = Path(f"{database}-wal")
    immutable = not wal.exists() or wal.stat().st_size == 0
    options = "mode=ro&immutable=1" if immutable else "mode=ro"
    connection = sqlite3.connect(
        f"file:{database.resolve()}?{options}", uri=True
    )
    connection.row_factory = sqlite3.Row
    connection.execute("PRAGMA query_only = ON")
    return connection


def _table_exists(connection: sqlite3.Connection, name: str) -> bool:
    return bool(
        connection.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?",
            (name,),
        ).fetchone()
    )


def _rows_for_ids(
    connection: sqlite3.Connection,
    table: str,
    column: str,
    identifiers: Iterable[str],
) -> list[dict[str, Any]]:
    values = sorted(set(identifiers))
    if not values or not _table_exists(connection, table):
        return []
    placeholders = ",".join("?" for _ in values)
    rows = connection.execute(
        f"SELECT * FROM {table} WHERE {column} IN ({placeholders})", values
    ).fetchall()
    return [dict(row) for row in rows]


def _auto_graph(connection: sqlite3.Connection) -> dict[str, list[dict[str, Any]]]:
    if not _table_exists(connection, "apify_actor_auto_pool_runs"):
        return {
            "runs": [], "discoveries": [], "batches": [], "items": [],
            "validations": [], "attempts": [], "remote_runs": [], "jobs": [],
        }
    runs = [dict(row) for row in connection.execute(
        "SELECT * FROM apify_actor_auto_pool_runs ORDER BY created_at, run_id"
    ).fetchall()]
    discoveries = [dict(row) for row in connection.execute(
        """SELECT * FROM apify_actor_discovery_runs
           WHERE trigger_reason IN ('auto_pool', 'auto_pool_replenishment')
           ORDER BY created_at, run_id"""
    ).fetchall()]
    discovery_ids = {str(row["run_id"]) for row in discoveries}
    batches = []
    if discovery_ids:
        candidates = _rows_for_ids(
            connection, "apify_actor_canary_batches", "discovery_run_id", discovery_ids
        )
        batches = sorted(candidates, key=lambda row: (str(row["created_at"]), str(row["batch_id"])))
    batch_ids = {str(row["batch_id"]) for row in batches}
    items = _rows_for_ids(
        connection, "apify_actor_canary_batch_items", "batch_id", batch_ids
    )
    validation_ids = {str(row["validation_id"]) for row in items}
    validations = _rows_for_ids(
        connection, "apify_actor_validations", "validation_id", validation_ids
    )
    attempt_ids = {
        str(row["attempt_id"]) for row in validations if row.get("attempt_id")
    }
    attempts = _rows_for_ids(connection, "apify_actor_attempts", "id", attempt_ids)
    remote_runs = _rows_for_ids(
        connection, "apify_actor_runs", "logical_run_id", attempt_ids
    )
    jobs = _auto_jobs(connection, discovery_ids=discovery_ids, batch_ids=batch_ids)
    return {
        "runs": runs, "discoveries": discoveries, "batches": batches,
        "items": items, "validations": validations, "attempts": attempts,
        "remote_runs": remote_runs, "jobs": jobs,
    }


def _auto_jobs(
    connection: sqlite3.Connection,
    *,
    discovery_ids: set[str],
    batch_ids: set[str],
) -> list[dict[str, Any]]:
    if not _table_exists(connection, "fetch_jobs"):
        return []
    rows = connection.execute(
        """SELECT * FROM fetch_jobs
           WHERE job_type IN ('apify_actor_discovery', 'apify_actor_canary_batch')
           ORDER BY created_at, id"""
    ).fetchall()
    result: list[dict[str, Any]] = []
    for raw in rows:
        row = dict(raw)
        try:
            payload = json.loads(str(row.get("payload_json") or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            continue
        if not isinstance(payload, dict):
            continue
        owned = (
            row["job_type"] == "apify_actor_discovery"
            and str(payload.get("run_id") or "") in discovery_ids
        ) or (
            row["job_type"] == "apify_actor_canary_batch"
            and str(payload.get("batch_id") or "") in batch_ids
        )
        if owned:
            result.append(row)
    return result


def _active_workers(
    connection: sqlite3.Connection,
    *,
    now: datetime,
    stale_seconds: float,
) -> list[str]:
    if not _table_exists(connection, "worker_heartbeats"):
        return []
    active: list[str] = []
    for row in connection.execute(
        "SELECT worker_id, heartbeat_at FROM worker_heartbeats ORDER BY worker_id"
    ).fetchall():
        try:
            heartbeat = datetime.fromisoformat(
                str(row["heartbeat_at"]).replace("Z", "+00:00")
            )
            if heartbeat.tzinfo is None:
                heartbeat = heartbeat.replace(tzinfo=timezone.utc)
        except (TypeError, ValueError):
            active.append(str(row["worker_id"]))
            continue
        age = (now - heartbeat.astimezone(timezone.utc)).total_seconds()
        if age < stale_seconds:
            active.append(str(row["worker_id"]))
    return active


def _has_unknown_start(row: dict[str, Any]) -> bool:
    values = {
        str(row.get("status") or ""),
        str(row.get("semantic_outcome") or ""),
        str(row.get("last_error_code") or ""),
        str(row.get("error_code") or ""),
    }
    return bool(values & UNKNOWN_START_VALUES) or any(
        "unknown_start" in value for value in values
    )


def _snapshot(
    connection: sqlite3.Connection,
    *,
    now: datetime,
    stale_seconds: float,
) -> dict[str, Any]:
    graph = _auto_graph(connection)
    active_workers = _active_workers(
        connection, now=now, stale_seconds=stale_seconds
    )
    all_actor_runs = (
        [dict(row) for row in connection.execute(
            "SELECT id, purpose, status FROM apify_actor_runs ORDER BY id"
        ).fetchall()]
        if _table_exists(connection, "apify_actor_runs") else []
    )
    active_actor_runs = [
        row for row in all_actor_runs
        if str(row.get("status") or "") in NONTERMINAL_ACTOR_RUN_STATUSES
    ]
    active_jobs = [
        row for row in graph["jobs"] if row.get("status") in {"queued", "running"}
    ]
    active_discoveries = [
        row for row in graph["discoveries"]
        if row.get("stage") in ACTIVE_DISCOVERY_STAGES
    ]
    nonterminal_batches = [
        row for row in graph["batches"]
        if row.get("status") in NONTERMINAL_BATCH_STATUSES
    ]
    unsettled = [
        row for name in ("batches", "items", "validations", "attempts", "remote_runs")
        for row in graph[name]
        if (
            "cost_final" in row and not bool(row.get("cost_final"))
        ) or (
            "charge_final" in row and not bool(row.get("charge_final"))
        )
    ]
    unknown = [
        row for name in ("batches", "items", "validations", "attempts", "remote_runs")
        for row in graph[name] if _has_unknown_start(row)
    ]
    requires_changes = bool(
        active_jobs or active_discoveries
        or any(row.get("status") == "running" for row in graph["runs"])
    )
    blockers = {
        "active_worker_count": len(active_workers),
        "nonterminal_actor_run_count": len(active_actor_runs),
        "nonterminal_auto_batch_count": len(nonterminal_batches),
        "unknown_start_count": len(unknown),
        "unsettled_auto_cost_count": len(unsettled),
    }
    return {
        "database_exists": True,
        "auto_pool_table_present": _table_exists(
            connection, "apify_actor_auto_pool_runs"
        ),
        "auto_run_count": len(graph["runs"]),
        "running_auto_run_count": sum(
            row.get("status") == "running" for row in graph["runs"]
        ),
        "auto_discovery_count": len(graph["discoveries"]),
        "active_auto_discovery_count": len(active_discoveries),
        "auto_batch_count": len(graph["batches"]),
        "auto_validation_count": len(graph["validations"]),
        "auto_remote_run_count": len(graph["remote_runs"]),
        "auto_job_count": len(graph["jobs"]),
        "active_auto_job_count": len(active_jobs),
        "_active_worker_ids": active_workers,
        "unrelated_nonterminal_actor_run_count": sum(
            str(row.get("purpose") or "") != "validation" for row in active_actor_runs
        ),
        **blockers,
        "requires_changes": requires_changes,
        "safe_to_apply": not any(blockers.values()),
        "_active_job_ids": [str(row["id"]) for row in active_jobs],
        "_active_discovery_ids": [str(row["run_id"]) for row in active_discoveries],
        "_running_auto_ids": [
            str(row["run_id"]) for row in graph["runs"]
            if row.get("status") == "running"
        ],
    }


def _public_snapshot(snapshot: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in snapshot.items() if not key.startswith("_")}


def inspect_retirement(
    data_dir: Path | str,
    *,
    now: datetime | None = None,
    heartbeat_stale_seconds: float = 35.0,
) -> dict[str, Any]:
    """Return a read-only safety summary without creating a database or WAL."""

    connection = _ro_connect(_database(data_dir))
    try:
        snapshot = _snapshot(
            connection,
            now=now or datetime.now(timezone.utc),
            stale_seconds=heartbeat_stale_seconds,
        )
        return _public_snapshot(snapshot)
    finally:
        connection.close()


def _require_safe(snapshot: dict[str, Any]) -> None:
    labels = (
        ("active_worker_count", "worker heartbeat safety window has not elapsed"),
        ("nonterminal_actor_run_count", "nonterminal Actor Runs must be reconciled"),
        ("nonterminal_auto_batch_count", "auto-pool Canary batches are not terminal"),
        ("unknown_start_count", "unknown Actor start evidence remains"),
        ("unsettled_auto_cost_count", "auto-pool costs are not final"),
    )
    for key, message in labels:
        if int(snapshot[key]):
            raise RuntimeError(message)


def _backup_database(database: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"service-apify-actor-auto-pool-retire-{stamp}.db"
    descriptor = os.open(target, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(descriptor)
    source: sqlite3.Connection | None = None
    destination: sqlite3.Connection | None = None
    try:
        source = _ro_connect(database)
        destination = sqlite3.connect(target)
        source.backup(destination)
    except Exception:
        target.unlink(missing_ok=True)
        raise
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
    os.chmod(target, 0o600)
    return target


def _update_ids(
    connection: sqlite3.Connection,
    statement: str,
    identifiers: list[str],
    parameters: tuple[Any, ...],
) -> int:
    if not identifiers:
        return 0
    placeholders = ",".join("?" for _ in identifiers)
    cursor = connection.execute(
        statement.format(placeholders=placeholders), (*parameters, *identifiers)
    )
    return int(cursor.rowcount)


def apply_retirement(
    data_dir: Path | str,
    *,
    backup_dir: Path | str,
    confirm_api_stopped: bool,
    confirm_worker_stopped: bool,
    now: datetime | None = None,
    heartbeat_stale_seconds: float = 35.0,
) -> dict[str, Any]:
    """Atomically terminalize only active auto-owned jobs, discoveries and runs."""

    if not confirm_api_stopped or not confirm_worker_stopped:
        raise RuntimeError("explicit API and Worker stopped confirmations are required")
    resolved_now = now or datetime.now(timezone.utc)
    database = _database(data_dir)
    before_connection = _ro_connect(database)
    try:
        before = _snapshot(
            before_connection,
            now=resolved_now,
            stale_seconds=heartbeat_stale_seconds,
        )
    finally:
        before_connection.close()
    _require_safe(before)
    if not before["requires_changes"]:
        return {"applied": False, "already_retired": True, "backup_path": None}
    backup = _backup_database(database, Path(backup_dir))
    connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = _snapshot(
            connection,
            now=resolved_now,
            stale_seconds=heartbeat_stale_seconds,
        )
        _require_safe(current)
        timestamp = resolved_now.astimezone(timezone.utc).isoformat()
        jobs = _update_ids(
            connection,
            """UPDATE fetch_jobs
               SET status = 'cancelled', worker_id = NULL, claim_token = NULL,
                   locked_until = NULL, error_code = ?, error_message = ?,
                   cancelled_at = COALESCE(cancelled_at, ?),
                   finished_at = COALESCE(finished_at, ?), updated_at = ?
               WHERE status IN ('queued', 'running')
                 AND id IN ({placeholders})""",
            current["_active_job_ids"],
            (RETIREMENT_CODE, "Automated Actor pool workflow was retired", timestamp,
             timestamp, timestamp),
        )
        discoveries = _update_ids(
            connection,
            """UPDATE apify_actor_discovery_runs
               SET stage = 'failed', error_code = ?, updated_at = ?
               WHERE stage IN ('queued', 'searching', 'metadata', 'ranking',
                               'static_validation', 'input_validation')
                 AND run_id IN ({placeholders})""",
            current["_active_discovery_ids"],
            (RETIREMENT_CODE, timestamp),
        )
        runs = _update_ids(
            connection,
            """UPDATE apify_actor_auto_pool_runs
               SET status = 'cancelled', error_code = ?, updated_at = ?
               WHERE status = 'running' AND run_id IN ({placeholders})""",
            current["_running_auto_ids"],
            (RETIREMENT_CODE, timestamp),
        )
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity.casefold() != "ok" or foreign_keys:
            raise RuntimeError("post-retirement database verification failed")
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
    return {
        "applied": True,
        "already_retired": False,
        "backup_path": str(backup),
        "backup_mode": oct(backup.stat().st_mode & 0o777),
        "jobs_cancelled": jobs,
        "discoveries_failed": discoveries,
        "runs_cancelled": runs,
    }


__all__ = [
    "RETIREMENT_CODE", "apply_retirement", "inspect_retirement",
]
