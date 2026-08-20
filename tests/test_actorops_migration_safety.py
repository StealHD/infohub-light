from __future__ import annotations

from datetime import datetime, timezone
from pathlib import Path

from scripts.actorops_migration_safety import (
    active_actor_work,
    active_workers_fail_closed,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def test_worker_guard_treats_fresh_stopping_and_bad_heartbeats_as_active(
    tmp_path: Path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    now = datetime(2026, 8, 20, 3, 0, tzinfo=timezone.utc)
    store.upsert_worker_heartbeat("stopping-worker", "stopping")
    store.connect().execute(
        "UPDATE worker_heartbeats SET heartbeat_at = ? WHERE worker_id = ?",
        (now.isoformat(), "stopping-worker"),
    )
    store.connect().commit()

    assert active_workers_fail_closed(tmp_path / "service.db", now=now) == [
        "stopping-worker"
    ]
    store.connect().execute(
        "UPDATE worker_heartbeats SET heartbeat_at = 'not-a-time' WHERE worker_id = ?",
        ("stopping-worker",),
    )
    store.connect().commit()
    assert active_workers_fail_closed(tmp_path / "service.db", now=now) == [
        "stopping-worker"
    ]
    store.close()


def test_actor_work_guard_includes_aborting_remote_runs(tmp_path: Path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    stamp = "2026-08-20T03:00:00+00:00"
    store.connect().execute(
        """INSERT INTO apify_actor_runs (
               id, workspace_id, logical_run_id, purpose, secret_id,
               secret_version, pool_generation, remote_run_id, dataset_id,
               status, created_at, started_at, updated_at,
               charge_reserved_usd, charge_actual_usd, charge_final
           ) VALUES ('aborting-run', ?, NULL, 'validation', 'validation-key',
                     1, 1, 'remote-aborting', NULL, 'aborting', ?, ?, ?,
                     0.02, NULL, 0)""",
        (DEFAULT_WORKSPACE_ID, stamp, stamp, stamp),
    )
    store.connect().commit()
    store.close()

    work = active_actor_work(tmp_path / "service.db")
    assert [(row["id"], row["status"]) for row in work] == [
        ("aborting-run", "aborting")
    ]
