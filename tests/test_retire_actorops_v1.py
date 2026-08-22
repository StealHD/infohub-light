"""Offline safety coverage for ActorOps v1 retirement."""

from __future__ import annotations

import json
import os
import sqlite3
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts.retire_actorops_v1 import (
    RetirementError,
    apply,
    snapshot,
    status,
    verify,
)
from src.storage.service_store import ServiceStore


NOW = datetime(2026, 8, 23, 8, 0, tzinfo=timezone.utc)


def _database(data_dir: Path) -> Path:
    data_dir.mkdir(exist_ok=True)
    database = data_dir / "service.db"
    if database.exists():
        return database
    connection = sqlite3.connect(database)
    connection.executescript(
        """
        CREATE TABLE schema_migrations (
            version INTEGER PRIMARY KEY, name TEXT, checksum TEXT, applied_at TEXT
        );
        CREATE TABLE worker_heartbeats (worker_id TEXT, heartbeat_at TEXT);
        CREATE TABLE fetch_jobs (
            id TEXT PRIMARY KEY, job_type TEXT, status TEXT, attempts INTEGER,
            started_at TEXT, worker_id TEXT, claim_token TEXT, locked_until TEXT,
            result_json TEXT, error_code TEXT, error_message TEXT, cancelled_at TEXT,
            finished_at TEXT, updated_at TEXT
        );
        CREATE TABLE apify_actor_discovery_settings (
            workspace_id TEXT, enabled INTEGER, updated_at TEXT
        );
        CREATE TABLE apify_actor_route_profiles (
            route_id TEXT, freshness_enabled INTEGER, freshness_authorized_at TEXT,
            freshness_authorized_by_user_id TEXT, freshness_status TEXT,
            freshness_next_check_at TEXT, updated_at TEXT
        );
        CREATE TABLE apify_actor_discovery_runs (run_id TEXT, stage TEXT);
        CREATE TABLE apify_actor_validations (
            validation_id TEXT, status TEXT, cost_final INTEGER, attempt_id TEXT
        );
        CREATE TABLE apify_actor_canary_batches (
            batch_id TEXT, status TEXT, cost_final INTEGER
        );
        CREATE TABLE apify_actor_canary_batch_items (
            batch_id TEXT, ordinal INTEGER, status TEXT, cost_final INTEGER
        );
        CREATE TABLE apify_actor_pool_stages (stage_id TEXT, status TEXT);
        CREATE TABLE apify_actor_freshness_checks (
            check_id TEXT, status TEXT, cost_final INTEGER
        );
        CREATE TABLE apify_actor_attempts (
            id TEXT, status TEXT, cost_final INTEGER, reserved_usd REAL,
            actual_cost_usd REAL, last_error_code TEXT
        );
        CREATE TABLE apify_actor_runs (
            id TEXT, logical_run_id TEXT, status TEXT, charge_final INTEGER,
            charge_reserved_usd REAL, charge_actual_usd REAL, last_error_code TEXT
        );
        CREATE TABLE apify_actor_auto_pool_runs (run_id TEXT, status TEXT);
        CREATE TABLE source_catalog (
            id TEXT PRIMARY KEY, type TEXT, enabled INTEGER, config_json TEXT,
            updated_at TEXT
        );
        CREATE TABLE actor_routes_v2 (
            route_id TEXT PRIMARY KEY, runtime_mode TEXT, generation INTEGER,
            updated_at TEXT
        );
        CREATE TABLE actor_source_bindings_v2 (
            source_id TEXT PRIMARY KEY, status TEXT, binding_version INTEGER,
            preferred_candidate_id TEXT, updated_at TEXT
        );
        """
    )
    connection.commit()
    connection.close()
    return database


def _connection(data_dir: Path) -> sqlite3.Connection:
    connection = sqlite3.connect(_database(data_dir))
    connection.row_factory = sqlite3.Row
    return connection


def _seed_safe_retirement(data_dir: Path) -> None:
    connection = _connection(data_dir)
    stamp = NOW.isoformat()
    connection.execute(
        """INSERT INTO fetch_jobs(
               id, job_type, status, attempts, started_at, updated_at
           ) VALUES ('safe-job', 'apify_actor_discovery', 'queued', 0, NULL, ?)""",
        (stamp,),
    )
    connection.execute(
        "INSERT INTO apify_actor_discovery_settings VALUES ('workspace', 1, ?)",
        (stamp,),
    )
    connection.execute(
        """INSERT INTO apify_actor_route_profiles VALUES (
               'legacy-route', 1, ?, 'owner', 'scheduled', ?, ?)""",
        (stamp, stamp, stamp),
    )
    connection.execute(
        "INSERT INTO actor_routes_v2 VALUES ('shadow-route', 'shadow', 3, ?)",
        (stamp,),
    )
    connection.execute(
        """INSERT INTO source_catalog VALUES (
               'legacy-source', 'apify_social', 1, ?, ?)""",
        (json.dumps({"profile_id": "legacy-route", "target": "private-target"}), stamp),
    )
    connection.commit()
    connection.close()


def test_status_is_read_only_and_redacts_operational_values(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    database = _database(data_dir)
    _seed_safe_retirement(data_dir)
    connection = _connection(data_dir)
    connection.execute(
        """INSERT INTO fetch_jobs(
               id, job_type, status, attempts, started_at, updated_at
           ) VALUES ('isolated-job', 'apify_actor_validation', 'running', 1, ?, ?)""",
        (NOW.isoformat(), NOW.isoformat()),
    )
    connection.execute(
        """INSERT INTO apify_actor_attempts VALUES (
               'unknown-attempt', 'start_outcome_unknown', 0, 0.02, NULL,
               'apify_start_outcome_unknown')"""
    )
    connection.execute(
        """INSERT INTO apify_actor_runs VALUES (
               'unknown-run', 'unknown-attempt', 'start_outcome_unknown', 0,
               0.02, NULL, 'apify_start_outcome_unknown')"""
    )
    connection.execute(
        """INSERT INTO apify_actor_validations VALUES (
               'blocked-validation', 'blocked_unknown_start', 0, 'unknown-attempt')"""
    )
    connection.commit()
    connection.close()
    before = (database.stat().st_mtime_ns, database.stat().st_size)

    result = status(data_dir, now=NOW)

    assert result["v1_job_count"] == 2
    assert result["v1_discovery_count"] == 0
    assert result["v1_validation_count"] == 1
    assert result["v1_batch_count"] == 0
    assert result["v1_stage_count"] == 0
    assert result["v1_attempt_count"] == 1
    assert result["v1_run_count"] == 1
    assert result["safe_cancellable_v1_job_count"] == 1
    assert result["isolated_v1_job_count"] == 1
    assert result["standing_authorization_count"] == 2
    assert result["shadow_route_count"] == 1
    assert result["v1_enabled_source_count"] == 1
    assert result["unknown_start_count"] == 3
    assert result["unsettled_cost_count"] == 3
    assert "private-target" not in json.dumps(result)
    assert (database.stat().st_mtime_ns, database.stat().st_size) == before


def test_snapshot_requires_quiet_heartbeat_and_writes_private_redacted_receipt(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    _database(data_dir)
    receipt_path = tmp_path / "receipt.json"

    with pytest.raises(RetirementError, match="services-stopped"):
        snapshot(data_dir, receipt_path=receipt_path, services_stopped=False, now=NOW)

    result = snapshot(
        data_dir,
        receipt_path=receipt_path,
        backup_dir=tmp_path / "backups",
        services_stopped=True,
        heartbeat_window_seconds=0,
        now=NOW,
    )

    receipt = json.loads(receipt_path.read_text())
    assert result["status"] == "snapshotted"
    assert result["backup_mode"] == "0o600"
    assert os.stat(result["backup_path"]).st_mode & 0o777 == 0o600
    assert os.stat(receipt_path).st_mode & 0o777 == 0o600
    assert receipt["schema"] == "actorops_v1_retirement_receipt_v1"
    assert receipt["database_sha256"]
    assert "private-target" not in json.dumps(receipt)


def test_status_and_snapshot_accept_the_current_service_schema(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    store.close()

    result = status(data_dir, now=NOW)
    snapshotted = snapshot(
        data_dir,
        receipt_path=tmp_path / "receipt.json",
        backup_dir=tmp_path / "backups",
        services_stopped=True,
        heartbeat_window_seconds=0,
        now=NOW,
    )

    assert result["active_worker_count"] == 0
    assert result["legacy_table_counts"] == {}
    assert snapshotted["status"] == "snapshotted"


def test_apply_only_cancels_safe_jobs_and_requires_exact_source_isolation(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    _database(data_dir)
    _seed_safe_retirement(data_dir)
    receipt_path = tmp_path / "receipt.json"
    snapshot(
        data_dir,
        receipt_path=receipt_path,
        backup_dir=tmp_path / "snapshots",
        services_stopped=True,
        heartbeat_window_seconds=0,
        now=NOW,
    )

    with pytest.raises(RetirementError, match="enabled v1 source"):
        apply(
            data_dir,
            receipt_path=receipt_path,
            backup_dir=tmp_path / "backups",
            services_stopped=True,
            heartbeat_window_seconds=0,
            now=NOW,
        )
    applied = apply(
        data_dir,
        receipt_path=receipt_path,
        backup_dir=tmp_path / "backups",
        services_stopped=True,
        heartbeat_window_seconds=0,
        isolate_v1_source_count=1,
        now=NOW,
    )

    connection = _connection(data_dir)
    job = connection.execute("SELECT status, error_code FROM fetch_jobs").fetchone()
    discovery = connection.execute(
        "SELECT enabled FROM apify_actor_discovery_settings"
    ).fetchone()
    profile = connection.execute(
        "SELECT freshness_enabled, freshness_status FROM apify_actor_route_profiles"
    ).fetchone()
    route = connection.execute("SELECT runtime_mode FROM actor_routes_v2").fetchone()
    source = connection.execute("SELECT enabled FROM source_catalog").fetchone()
    connection.close()
    assert applied["jobs_cancelled"] == 1
    assert applied["standing_authorizations_disabled"] == 2
    assert applied["shadow_routes_disabled"] == 1
    assert applied["sources_isolated"] == 1
    assert tuple(job) == ("cancelled", "actorops_v1_retired")
    assert discovery["enabled"] == 0
    assert tuple(profile) == (0, "disabled")
    assert route["runtime_mode"] == "disabled"
    assert source["enabled"] == 0
    assert verify(data_dir, receipt_path=receipt_path, now=NOW)["status"] == "verified"
    assert apply(
        data_dir,
        receipt_path=receipt_path,
        backup_dir=tmp_path / "backups",
        services_stopped=True,
        heartbeat_window_seconds=0,
        now=NOW,
    )["already_retired"] is True


def test_apply_fails_closed_for_ambiguous_work_and_verify_detects_drift(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    _database(data_dir)
    connection = _connection(data_dir)
    connection.execute(
        """INSERT INTO fetch_jobs(
               id, job_type, status, attempts, started_at, updated_at
           ) VALUES ('claimed-job', 'apify_actor_canary_batch', 'queued', 1, ?, ?)""",
        (NOW.isoformat(), NOW.isoformat()),
    )
    connection.commit()
    connection.close()
    receipt_path = tmp_path / "receipt.json"
    snapshot(
        data_dir,
        receipt_path=receipt_path,
        backup_dir=tmp_path / "snapshots",
        services_stopped=True,
        heartbeat_window_seconds=0,
        now=NOW,
    )

    with pytest.raises(RetirementError, match="isolated v1 jobs"):
        apply(
            data_dir,
            receipt_path=receipt_path,
            backup_dir=tmp_path / "backups",
            services_stopped=True,
            heartbeat_window_seconds=0,
            now=NOW,
        )
    applied = apply(
        data_dir,
        receipt_path=receipt_path,
        backup_dir=tmp_path / "backups",
        services_stopped=True,
        heartbeat_window_seconds=0,
        isolate_v1_job_count=1,
        now=NOW,
    )
    assert applied["isolated_v1_jobs"] == 1
    connection = _connection(data_dir)
    assert connection.execute(
        "SELECT status FROM fetch_jobs WHERE id='claimed-job'"
    ).fetchone()[0] == "queued"
    connection.close()

    connection = _connection(data_dir)
    connection.execute("UPDATE fetch_jobs SET error_code='drift' WHERE id='claimed-job'")
    connection.commit()
    connection.close()
    with pytest.raises(RetirementError, match="database hash"):
        apply(
            data_dir,
            receipt_path=receipt_path,
            backup_dir=tmp_path / "backups",
            services_stopped=True,
            heartbeat_window_seconds=0,
            isolate_v1_job_count=1,
            now=NOW,
        )
    with pytest.raises(RetirementError, match="database hash"):
        verify(data_dir, receipt_path=receipt_path, now=NOW)
