#!/usr/bin/env python3
"""Offline, fail-closed retirement controls for ActorOps v1 facts."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import stat
import subprocess
import sys
import time
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable


REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
RETIREMENT_CODE = "actorops_v1_retired"
RECEIPT_SCHEMA = "actorops_v1_retirement_receipt_v1"
V1_JOB_TYPES = (
    "apify_actor_discovery",
    "apify_actor_validation",
    "apify_actor_canary_batch",
    "apify_actor_freshness_check",
)
V1_TABLES = (
    "apify_actor_routes", "apify_actor_candidates", "apify_actor_attempts",
    "apify_actor_target_health", "apify_actor_route_profiles",
    "apify_actor_adapter_revisions", "apify_route_active_slots",
    "apify_actor_metadata_observations", "apify_source_route_bindings",
    "apify_actor_discovery_runs", "apify_actor_discovery_run_revisions",
    "apify_actor_discovery_settings", "apify_actor_validations",
    "apify_actor_canary_batches", "apify_actor_canary_batch_items",
    "apify_actor_pool_stages", "apify_actor_pool_stage_sources",
    "apify_actor_pool_stage_candidate_settings", "apify_actor_freshness_checks",
    "apify_actor_freshness_results", "apify_actor_evaluation_history",
    "apify_actor_diagnostic_events", "apify_actor_auto_pool_runs",
)
NONTERMINAL = {
    "apify_actor_discovery_runs": ("stage", ("queued", "searching", "metadata", "ranking", "static_validation", "input_validation")),
    "apify_actor_validations": ("status", ("queued", "running", "blocked_unknown_start")),
    "apify_actor_canary_batches": ("status", ("queued", "preflighting", "running", "blocked_unknown_start")),
    "apify_actor_pool_stages": ("status", ("queued", "validating_route", "validating_sources", "apply_ready", "blocked_unknown_start")),
    "apify_actor_freshness_checks": ("status", ("queued", "running", "blocked_unknown_start")),
    "apify_actor_auto_pool_runs": ("status", ("running",)),
}


class RetirementError(RuntimeError):
    """Stable, value-safe error for the offline retirement workflow."""


def _database(data_dir: Path | str) -> Path:
    database = Path(data_dir) / "service.db"
    if not database.is_file():
        raise RetirementError("service database does not exist")
    return database


def _connect(database: Path, *, read_only: bool) -> sqlite3.Connection:
    if read_only:
        connection = sqlite3.connect(
            f"file:{database.resolve()}?mode=ro", uri=True
        )
        connection.execute("PRAGMA query_only = ON")
    else:
        connection = sqlite3.connect(database)
    connection.row_factory = sqlite3.Row
    return connection


def _names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type IN ('table', 'view')"
        )
    }


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _count(connection: sqlite3.Connection, table: str, where: str = "", values: Iterable[Any] = ()) -> int:
    return int(connection.execute(
        f"SELECT COUNT(*) FROM {table}{where}", tuple(values)
    ).fetchone()[0])


def _placeholders(values: Iterable[Any]) -> str:
    return ", ".join("?" for _ in values)


def _now(value: datetime | None = None) -> datetime:
    resolved = value or datetime.now(timezone.utc)
    return resolved.astimezone(timezone.utc)


def _active_workers(connection: sqlite3.Connection, *, now: datetime, stale_seconds: float) -> int:
    if "worker_heartbeats" not in _names(connection):
        return 0
    active = 0
    for row in connection.execute("SELECT heartbeat_at FROM worker_heartbeats"):
        try:
            heartbeat = datetime.fromisoformat(str(row[0]).replace("Z", "+00:00"))
            heartbeat = heartbeat.replace(tzinfo=timezone.utc) if heartbeat.tzinfo is None else heartbeat
        except (TypeError, ValueError):
            active += 1
            continue
        if (now - heartbeat.astimezone(timezone.utc)).total_seconds() < stale_seconds:
            active += 1
    return active


def _job_counts(connection: sqlite3.Connection, tables: set[str]) -> dict[str, int]:
    if "fetch_jobs" not in tables:
        return {"v1_job_count": 0, "safe_cancellable_v1_job_count": 0, "isolated_v1_job_count": 0}
    types = _placeholders(V1_JOB_TYPES)
    total = _count(connection, "fetch_jobs", f" WHERE job_type IN ({types})", V1_JOB_TYPES)
    safe_where = (
        f" WHERE job_type IN ({types}) AND status='queued' AND attempts=0 "
        "AND started_at IS NULL"
    )
    safe = _count(connection, "fetch_jobs", safe_where, V1_JOB_TYPES)
    isolated_where = (
        f" WHERE job_type IN ({types}) AND status IN ('queued', 'running') "
        "AND NOT (status='queued' AND attempts=0 AND started_at IS NULL)"
    )
    isolated = _count(connection, "fetch_jobs", isolated_where, V1_JOB_TYPES)
    return {"v1_job_count": total, "safe_cancellable_v1_job_count": safe, "isolated_v1_job_count": isolated}


def _legacy_counts(connection: sqlite3.Connection, tables: set[str]) -> tuple[dict[str, int], int]:
    counts = {table: _count(connection, table) for table in V1_TABLES if table in tables}
    nonterminal = 0
    for table, (column, states) in NONTERMINAL.items():
        if table in tables and column in _columns(connection, table):
            nonterminal += _count(
                connection, table, f" WHERE {column} IN ({_placeholders(states)})", states
            )
    return counts, nonterminal


def _unknown_and_unsettled(connection: sqlite3.Connection, tables: set[str]) -> tuple[int, int]:
    unknown = unsettled = 0
    if "apify_actor_attempts" in tables:
        columns = _columns(connection, "apify_actor_attempts")
        values = ["start_outcome_unknown"]
        predicates = ["status=?"] if "status" in columns else []
        if "last_error_code" in columns:
            predicates.append(
                "COALESCE(last_error_code, '') LIKE '%unknown_start%' "
                "OR COALESCE(last_error_code, '') LIKE '%start_outcome_unknown%'"
            )
        if predicates:
            unknown += _count(connection, "apify_actor_attempts", f" WHERE {' OR '.join(predicates)}", values)
        if {"cost_final", "reserved_usd", "actual_cost_usd"} <= columns:
            unsettled += _count(
                connection, "apify_actor_attempts",
                " WHERE cost_final=0 AND (COALESCE(reserved_usd, 0)>0 OR actual_cost_usd IS NOT NULL)",
            )
    if "apify_actor_runs" in tables:
        columns = _columns(connection, "apify_actor_runs")
        if "apify_actor_attempts" not in tables or "logical_run_id" not in columns:
            return unknown, unsettled
        join = " WHERE logical_run_id IN (SELECT id FROM apify_actor_attempts)"
        predicates = ["status='start_outcome_unknown'"] if "status" in columns else []
        if "last_error_code" in columns:
            predicates.append(
                "COALESCE(last_error_code, '') LIKE '%unknown_start%' "
                "OR COALESCE(last_error_code, '') LIKE '%start_outcome_unknown%'"
            )
        if predicates:
            unknown += _count(connection, "apify_actor_runs", f"{join} AND ({' OR '.join(predicates)})")
        if {"charge_final", "charge_reserved_usd", "charge_actual_usd"} <= columns:
            unsettled += _count(
                connection, "apify_actor_runs",
                f"{join} AND charge_final=0 AND (COALESCE(charge_reserved_usd, 0)>0 OR charge_actual_usd IS NOT NULL)",
            )
    for table in (
        "apify_actor_validations", "apify_actor_canary_batches",
        "apify_actor_canary_batch_items", "apify_actor_freshness_checks",
        "apify_actor_freshness_results",
    ):
        if table not in tables:
            continue
        columns = _columns(connection, table)
        if "status" in columns:
            unknown += _count(connection, table, " WHERE status='blocked_unknown_start'")
        if "cost_final" in columns:
            unsettled += _count(connection, table, " WHERE cost_final=0")
    return unknown, unsettled


def _v1_run_count(connection: sqlite3.Connection, tables: set[str]) -> int:
    if not {"apify_actor_runs", "apify_actor_attempts"} <= tables:
        return 0
    if "logical_run_id" not in _columns(connection, "apify_actor_runs"):
        return 0
    return _count(
        connection, "apify_actor_runs",
        " WHERE logical_run_id IN (SELECT id FROM apify_actor_attempts)",
    )


def _standing_authorizations(connection: sqlite3.Connection, tables: set[str]) -> int:
    count = 0
    if "apify_actor_discovery_settings" in tables and "enabled" in _columns(connection, "apify_actor_discovery_settings"):
        count += _count(connection, "apify_actor_discovery_settings", " WHERE enabled=1")
    if "apify_actor_route_profiles" in tables and "freshness_enabled" in _columns(connection, "apify_actor_route_profiles"):
        count += _count(connection, "apify_actor_route_profiles", " WHERE freshness_enabled=1")
    return count


def _legacy_source_ids(connection: sqlite3.Connection, tables: set[str]) -> list[str]:
    required = {"source_catalog", "actor_source_bindings_v2"}
    if not required <= tables:
        return []
    catalog_columns = _columns(connection, "source_catalog")
    binding_columns = _columns(connection, "actor_source_bindings_v2")
    if not {"id", "type", "enabled", "config_json"} <= catalog_columns or not {"source_id", "status"} <= binding_columns:
        return []
    legacy_bound: set[str] = set()
    if "apify_source_route_bindings" in tables and "source_id" in _columns(connection, "apify_source_route_bindings"):
        legacy_bound = {
            str(row[0]) for row in connection.execute(
                "SELECT source_id FROM apify_source_route_bindings"
            )
        }
    rows = connection.execute(
        """SELECT source.id, source.type, source.config_json, binding.status AS binding_status
           FROM source_catalog AS source
           LEFT JOIN actor_source_bindings_v2 AS binding ON binding.source_id=source.id
           WHERE source.enabled=1"""
    ).fetchall()
    result: list[str] = []
    for row in rows:
        try:
            config = json.loads(str(row["config_json"] or "{}"))
        except (TypeError, ValueError, json.JSONDecodeError):
            config = {}
        if not isinstance(config, dict):
            continue
        profile_hint = (
            str(row["type"] or "") == "apify_social"
            and str(config.get("profile_id") or "").strip()
        )
        if (profile_hint or str(row["id"]) in legacy_bound) and str(row["binding_status"] or "") != "ready":
            result.append(str(row["id"]))
    return sorted(set(result))


def _snapshot(connection: sqlite3.Connection, *, now: datetime, heartbeat_stale_seconds: float) -> dict[str, Any]:
    tables = _names(connection)
    jobs = _job_counts(connection, tables)
    history, nonterminal = _legacy_counts(connection, tables)
    unknown, unsettled = _unknown_and_unsettled(connection, tables)
    shadow = _count(connection, "actor_routes_v2", " WHERE runtime_mode='shadow'") if "actor_routes_v2" in tables else 0
    sources = _legacy_source_ids(connection, tables)
    active_workers = _active_workers(connection, now=now, stale_seconds=heartbeat_stale_seconds)
    return {
        **jobs,
        "v1_discovery_count": history.get("apify_actor_discovery_runs", 0),
        "v1_validation_count": history.get("apify_actor_validations", 0),
        "v1_batch_count": history.get("apify_actor_canary_batches", 0),
        "v1_stage_count": history.get("apify_actor_pool_stages", 0),
        "v1_attempt_count": history.get("apify_actor_attempts", 0),
        "v1_run_count": _v1_run_count(connection, tables),
        "legacy_table_counts": history,
        "legacy_fact_count": sum(history.values()),
        "nonterminal_v1_fact_count": nonterminal,
        "unknown_start_count": unknown,
        "unsettled_cost_count": unsettled,
        "standing_authorization_count": _standing_authorizations(connection, tables),
        "shadow_route_count": shadow,
        "v1_enabled_source_count": len(sources),
        "active_worker_count": active_workers,
        "_legacy_source_ids": sources,
    }


def _public(summary: dict[str, Any]) -> dict[str, Any]:
    return {key: value for key, value in summary.items() if not key.startswith("_")}


def status(data_dir: Path | str, *, now: datetime | None = None, heartbeat_stale_seconds: float = 35.0) -> dict[str, Any]:
    """Read a redacted summary without creating a database or journal."""

    connection = _connect(_database(data_dir), read_only=True)
    try:
        return _public(_snapshot(connection, now=_now(now), heartbeat_stale_seconds=heartbeat_stale_seconds))
    finally:
        connection.close()


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for block in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(block)
    return digest.hexdigest()


def _schema_shape(connection: sqlite3.Connection) -> dict[str, Any]:
    entries = [
        (str(row["type"]), str(row["name"]), str(row["sql"] or ""))
        for row in connection.execute(
            "SELECT type, name, sql FROM sqlite_master WHERE type IN ('table', 'index', 'trigger') ORDER BY type, name"
        )
    ]
    encoded = json.dumps(entries, ensure_ascii=True, separators=(",", ":")).encode()
    return {"entry_count": len(entries), "sha256": hashlib.sha256(encoded).hexdigest()}


def _backup(database: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(parents=True, exist_ok=True)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    backup = backup_dir / f"service-actorops-v1-retire-{stamp}.db"
    descriptor = os.open(backup, os.O_CREAT | os.O_EXCL | os.O_RDWR, 0o600)
    os.close(descriptor)
    source = destination = None
    try:
        source = _connect(database, read_only=True)
        destination = sqlite3.connect(backup)
        source.backup(destination)
    except Exception:
        backup.unlink(missing_ok=True)
        raise
    finally:
        if destination is not None:
            destination.close()
        if source is not None:
            source.close()
    os.chmod(backup, 0o600)
    return backup


def _code_sha() -> str:
    try:
        return subprocess.check_output(
            ("git", "rev-parse", "HEAD"), cwd=REPOSITORY_ROOT, text=True
        ).strip()
    except (OSError, subprocess.CalledProcessError):
        return "unavailable"


def _write_receipt(path: Path, receipt: dict[str, Any], *, replace: bool) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    flags = os.O_WRONLY | os.O_CREAT | (os.O_TRUNC if replace else os.O_EXCL)
    descriptor = os.open(path, flags, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
        json.dump(receipt, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
        handle.write("\n")
    os.chmod(path, 0o600)


def _read_receipt(path: Path) -> dict[str, Any]:
    try:
        receipt = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, ValueError, json.JSONDecodeError) as exc:
        raise RetirementError("retirement receipt is unreadable") from exc
    if not isinstance(receipt, dict) or receipt.get("schema") != RECEIPT_SCHEMA:
        raise RetirementError("retirement receipt has an invalid schema")
    return receipt


def _quiet_guard(database: Path, *, services_stopped: bool, heartbeat_window_seconds: float, now: datetime) -> None:
    if not services_stopped:
        raise RetirementError("explicit --services-stopped confirmation is required")
    if heartbeat_window_seconds < 0 or heartbeat_window_seconds > 60:
        raise RetirementError("heartbeat window must be between 0 and 60 seconds")
    if status(database.parent, now=now)["active_worker_count"]:
        raise RetirementError("worker heartbeat safety window has not elapsed")
    if heartbeat_window_seconds:
        time.sleep(heartbeat_window_seconds)
    if status(database.parent)["active_worker_count"]:
        raise RetirementError("worker heartbeat appeared during safety window")


def snapshot(data_dir: Path | str, *, receipt_path: Path, backup_dir: Path | None = None, services_stopped: bool, heartbeat_window_seconds: float = 35.0, now: datetime | None = None) -> dict[str, Any]:
    """Create a private backup and receipt after the API/Worker quiet guard."""

    database = _database(data_dir)
    resolved_now = _now(now)
    _quiet_guard(database, services_stopped=services_stopped, heartbeat_window_seconds=heartbeat_window_seconds, now=resolved_now)
    connection = _connect(database, read_only=True)
    try:
        summary = _snapshot(connection, now=resolved_now, heartbeat_stale_seconds=35.0)
        shape = _schema_shape(connection)
    finally:
        connection.close()
    backup = _backup(database, backup_dir or Path(data_dir) / "backups")
    receipt = {
        "schema": RECEIPT_SCHEMA,
        "created_at": resolved_now.isoformat(),
        "code_sha": _code_sha(),
        "database_sha256": _sha256(database),
        "backup_sha256": _sha256(backup),
        "schema_shape": shape,
        "blocker_counts": _public(summary),
    }
    _write_receipt(receipt_path, receipt, replace=False)
    return {"status": "snapshotted", "backup_path": str(backup), "backup_mode": oct(stat.S_IMODE(backup.stat().st_mode)), "receipt_path": str(receipt_path)}


def _require_apply_safe(summary: dict[str, Any], *, isolate_v1_job_count: int | None, isolate_v1_source_count: int | None) -> None:
    if summary["active_worker_count"]:
        raise RetirementError("worker heartbeat safety window has not elapsed")
    if summary["unknown_start_count"]:
        raise RetirementError("unknown-start evidence remains")
    if summary["unsettled_cost_count"]:
        raise RetirementError("unsettled ActorOps cost remains")
    if summary["nonterminal_v1_fact_count"]:
        raise RetirementError("nonterminal v1 ActorOps facts remain")
    isolated = int(summary["isolated_v1_job_count"])
    if isolated and isolate_v1_job_count != isolated:
        raise RetirementError("isolated v1 jobs require the exact isolation count")
    sources = int(summary["v1_enabled_source_count"])
    if sources and isolate_v1_source_count != sources:
        raise RetirementError("enabled v1 source requires the exact isolation count")
    if isolate_v1_job_count not in (None, isolated) or isolate_v1_source_count not in (None, sources):
        raise RetirementError("isolation count does not match current retirement state")


def _cancel_safe_jobs(connection: sqlite3.Connection, *, stamp: str) -> int:
    if "fetch_jobs" not in _names(connection):
        return 0
    types = _placeholders(V1_JOB_TYPES)
    cursor = connection.execute(
        f"""UPDATE fetch_jobs SET status='cancelled', worker_id=NULL, claim_token=NULL,
               locked_until=NULL, result_json=?, error_code=?, error_message=NULL,
               cancelled_at=COALESCE(cancelled_at, ?), finished_at=COALESCE(finished_at, ?), updated_at=?
            WHERE job_type IN ({types}) AND status='queued' AND attempts=0 AND started_at IS NULL""",
        (json.dumps({"invalidation_reason": RETIREMENT_CODE}, sort_keys=True), RETIREMENT_CODE, stamp, stamp, stamp, *V1_JOB_TYPES),
    )
    return int(cursor.rowcount)


def _disable_standing_authorizations(connection: sqlite3.Connection, *, stamp: str) -> int:
    changed = 0
    tables = _names(connection)
    if "apify_actor_discovery_settings" in tables and "enabled" in _columns(connection, "apify_actor_discovery_settings"):
        cursor = connection.execute("UPDATE apify_actor_discovery_settings SET enabled=0, updated_at=? WHERE enabled=1", (stamp,))
        changed += int(cursor.rowcount)
    if "apify_actor_route_profiles" in tables and "freshness_enabled" in _columns(connection, "apify_actor_route_profiles"):
        cursor = connection.execute(
            """UPDATE apify_actor_route_profiles SET freshness_enabled=0, freshness_authorized_at=NULL,
                   freshness_authorized_by_user_id=NULL, freshness_status='disabled', freshness_next_check_at=NULL,
                   updated_at=? WHERE freshness_enabled=1""", (stamp,)
        )
        changed += int(cursor.rowcount)
    return changed


def _disable_shadow_routes(connection: sqlite3.Connection, *, stamp: str) -> int:
    if "actor_routes_v2" not in _names(connection):
        return 0
    cursor = connection.execute(
        "UPDATE actor_routes_v2 SET runtime_mode='disabled', generation=generation+1, updated_at=? WHERE runtime_mode='shadow'",
        (stamp,),
    )
    return int(cursor.rowcount)


def _isolate_sources(connection: sqlite3.Connection, source_ids: list[str], *, stamp: str) -> int:
    if not source_ids:
        return 0
    placeholders = _placeholders(source_ids)
    connection.execute(
        f"UPDATE source_catalog SET enabled=0, updated_at=? WHERE id IN ({placeholders}) AND enabled=1",
        (stamp, *source_ids),
    )
    if "actor_source_bindings_v2" in _names(connection):
        connection.execute(
            f"""UPDATE actor_source_bindings_v2 SET status='disabled', binding_version=binding_version+1,
                   preferred_candidate_id=NULL, updated_at=? WHERE source_id IN ({placeholders})
                 AND status!='disabled'""",
            (stamp, *source_ids),
        )
    return len(source_ids)


def apply(data_dir: Path | str, *, receipt_path: Path, backup_dir: Path | None = None, services_stopped: bool, heartbeat_window_seconds: float = 35.0, isolate_v1_job_count: int | None = None, isolate_v1_source_count: int | None = None, now: datetime | None = None) -> dict[str, Any]:
    """Disable only safe v1 standing work; never rewrite paid or ambiguous facts."""

    database = _database(data_dir)
    resolved_now = _now(now)
    _quiet_guard(database, services_stopped=services_stopped, heartbeat_window_seconds=heartbeat_window_seconds, now=resolved_now)
    receipt = _read_receipt(receipt_path)
    if receipt.get("post_apply_database_sha256"):
        if receipt["post_apply_database_sha256"] != _sha256(database):
            raise RetirementError("database hash no longer matches the retirement receipt")
        return {"applied": False, "already_retired": True, "backup_path": None}
    if receipt.get("database_sha256") != _sha256(database):
        raise RetirementError("database hash no longer matches the snapshot receipt")
    before_connection = _connect(database, read_only=True)
    try:
        before = _snapshot(before_connection, now=resolved_now, heartbeat_stale_seconds=35.0)
    finally:
        before_connection.close()
    _require_apply_safe(before, isolate_v1_job_count=isolate_v1_job_count, isolate_v1_source_count=isolate_v1_source_count)
    backup = _backup(database, backup_dir or Path(data_dir) / "backups")
    connection = _connect(database, read_only=False)
    try:
        connection.execute("BEGIN IMMEDIATE")
        current = _snapshot(connection, now=resolved_now, heartbeat_stale_seconds=35.0)
        _require_apply_safe(current, isolate_v1_job_count=isolate_v1_job_count, isolate_v1_source_count=isolate_v1_source_count)
        stamp = resolved_now.isoformat()
        result = {
            "jobs_cancelled": _cancel_safe_jobs(connection, stamp=stamp),
            "standing_authorizations_disabled": _disable_standing_authorizations(connection, stamp=stamp),
            "shadow_routes_disabled": _disable_shadow_routes(connection, stamp=stamp),
            "sources_isolated": _isolate_sources(connection, current["_legacy_source_ids"], stamp=stamp),
            "isolated_v1_jobs": current["isolated_v1_job_count"],
        }
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
        if integrity.casefold() != "ok" or foreign_keys:
            raise RetirementError("post-retirement database verification failed")
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.close()
    receipt["applied_at"] = resolved_now.isoformat()
    receipt["post_apply_database_sha256"] = _sha256(database)
    receipt["isolation"] = {"v1_job_count": int(isolate_v1_job_count or 0), "v1_source_count": int(isolate_v1_source_count or 0)}
    _write_receipt(receipt_path, receipt, replace=True)
    return {"applied": True, "already_retired": False, "backup_path": str(backup), "backup_mode": oct(stat.S_IMODE(backup.stat().st_mode)), **result}


def verify(data_dir: Path | str, *, receipt_path: Path, now: datetime | None = None) -> dict[str, Any]:
    """Validate the receipt, current shape, integrity and online retirement boundary."""

    database = _database(data_dir)
    receipt = _read_receipt(receipt_path)
    expected_hash = receipt.get("post_apply_database_sha256") or receipt.get("database_sha256")
    if expected_hash != _sha256(database):
        raise RetirementError("database hash does not match the retirement receipt")
    connection = _connect(database, read_only=True)
    try:
        summary = _snapshot(connection, now=_now(now), heartbeat_stale_seconds=35.0)
        shape = _schema_shape(connection)
        integrity = str(connection.execute("PRAGMA integrity_check").fetchone()[0])
        foreign_keys = connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        connection.close()
    if shape != receipt.get("schema_shape"):
        raise RetirementError("schema shape does not match the retirement receipt")
    if integrity.casefold() != "ok" or foreign_keys:
        raise RetirementError("database integrity or foreign-key verification failed")
    allowed_isolated = int((receipt.get("isolation") or {}).get("v1_job_count") or 0)
    if summary["active_worker_count"] or summary["unknown_start_count"] or summary["unsettled_cost_count"] or summary["nonterminal_v1_fact_count"]:
        raise RetirementError("online v1 retirement blockers remain")
    if summary["isolated_v1_job_count"] != allowed_isolated or summary["v1_enabled_source_count"] or summary["shadow_route_count"] or summary["standing_authorization_count"]:
        raise RetirementError("online v1 retirement blockers remain")
    return {"status": "verified", "isolated_v1_job_count": allowed_isolated, "legacy_fact_count": summary["legacy_fact_count"]}


def main() -> int:
    parser = argparse.ArgumentParser(description="Offline ActorOps v1 retirement controls")
    parser.add_argument("command", choices=("status", "snapshot", "apply", "verify"))
    parser.add_argument("--data-dir", type=Path, default=REPOSITORY_ROOT / "data")
    parser.add_argument("--backup-dir", type=Path)
    parser.add_argument("--receipt", type=Path, default=REPOSITORY_ROOT / "data" / "backups" / "actorops-v1-retirement-receipt.json")
    parser.add_argument("--services-stopped", action="store_true")
    parser.add_argument("--heartbeat-window-seconds", type=float, default=35.0)
    parser.add_argument("--isolate-v1-job-count", type=int)
    parser.add_argument("--isolate-v1-source-count", type=int)
    args = parser.parse_args()
    try:
        if args.command == "status":
            result = status(args.data_dir)
        elif args.command == "snapshot":
            result = snapshot(args.data_dir, receipt_path=args.receipt, backup_dir=args.backup_dir, services_stopped=args.services_stopped, heartbeat_window_seconds=args.heartbeat_window_seconds)
        elif args.command == "apply":
            result = apply(args.data_dir, receipt_path=args.receipt, backup_dir=args.backup_dir, services_stopped=args.services_stopped, heartbeat_window_seconds=args.heartbeat_window_seconds, isolate_v1_job_count=args.isolate_v1_job_count, isolate_v1_source_count=args.isolate_v1_source_count)
        else:
            result = verify(args.data_dir, receipt_path=args.receipt)
    except (RetirementError, OSError, sqlite3.Error, ValueError) as error:
        print(json.dumps({"status": "failed", "error": str(error)}, ensure_ascii=False))
        return 1
    print(json.dumps(result, ensure_ascii=False, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
