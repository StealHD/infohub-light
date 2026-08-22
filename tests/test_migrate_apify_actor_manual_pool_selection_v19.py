from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from scripts.migrate_apify_actor_manual_pool_selection_v19 import migrate
from src.api.server import create_app
from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _downgrade_to_v18(store: ServiceStore) -> None:
    connection = store.connect()
    connection.execute("ALTER TABLE apify_actor_pool_stages DROP COLUMN selection_mode")
    connection.execute("ALTER TABLE apify_actor_pool_stages DROP COLUMN target_slot_count")
    connection.execute("DELETE FROM schema_migrations WHERE version = 21")
    connection.commit()


def _seed_old_stage(store: ServiceStore, *, with_backup_2: bool) -> str:
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username=f"v19-owner-{'three' if with_backup_2 else 'two'}",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store)
    route = next(
        route
        for route in ops.list_routes()
        if route["route_key"] == (
            "youtube/channel/items" if with_backup_2 else "x/profile"
        )
    )
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="migration_fixture",
        expected_generation=int(route["generation"]),
    )
    suffix = "three" if with_backup_2 else "two"
    batch_id = f"migration-batch-{suffix}"
    stage_id = f"migration-stage-{suffix}"
    now = "2026-08-10T00:00:00+00:00"
    connection = store.connect()
    connection.execute(
        """
        INSERT INTO apify_actor_canary_batches (
            batch_id, workspace_id, route_id, discovery_run_id,
            approval_key_hash, approved_generation, plan_hash,
            max_candidates, max_total_charge_usd, per_candidate_cap_usd,
            goal, pool_stage_id, status, planned_count, success_count,
            publisher_count, actual_cost_usd, cost_final, stop_reason,
            created_by_user_id, created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, 3, 0.06, 0.02,
            'upgrade_legacy', ?, 'partial', 0, 0, 0, 0, 1, NULL,
            ?, ?, ?
        )
        """,
        (
            batch_id,
            DEFAULT_WORKSPACE_ID,
            route["route_id"],
            run["run_id"],
            ("a" if with_backup_2 else "b") * 64,
            route["generation"],
            ("c" if with_backup_2 else "d") * 64,
            stage_id,
            owner["id"],
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO apify_actor_pool_stages (
            stage_id, workspace_id, route_id, discovery_run_id,
            initial_batch_id, goal, target_slot_count, selection_mode,
            base_generation, base_pool_hash, plan_hash, approval_key_hash,
            max_total_charge_usd, route_validation_cap_usd,
            target_backup_2_revision_id, status, created_by_user_id,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, 'upgrade_legacy', ?, 'server', ?, ?, ?, ?,
            0.06, 0.06, ?, 'applied', ?, ?, ?
        )
        """,
        (
            stage_id,
            DEFAULT_WORKSPACE_ID,
            route["route_id"],
            run["run_id"],
            batch_id,
            3 if with_backup_2 else 2,
            route["generation"],
            ("e" if with_backup_2 else "f") * 64,
            ("c" if with_backup_2 else "d") * 64,
            ("a" if with_backup_2 else "b") * 64,
            "historical-backup-2" if with_backup_2 else None,
            owner["id"],
            now,
            now,
        ),
    )
    connection.commit()
    return stage_id


def test_v19_migration_adds_manual_selection_fields_and_private_backup(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    two_slot_stage = _seed_old_stage(store, with_backup_2=False)
    three_slot_stage = _seed_old_stage(store, with_backup_2=True)
    _downgrade_to_v18(store)
    store.close()

    assert migrate(data_dir, apply=False)["required"] is True
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["applied"] is True
    assert result["backup_mode"] == "0o600"
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_violations"] == 0
    migrated = ServiceStore(data_dir)
    migrated.initialize()
    assert migrated.apify_actor_manual_pool_selection_v19_migration_required() is False
    rows = {
        str(row["stage_id"]): (int(row["target_slot_count"]), str(row["selection_mode"]))
        for row in migrated.connect().execute(
            "SELECT stage_id, target_slot_count, selection_mode FROM apify_actor_pool_stages"
        ).fetchall()
    }
    assert rows[two_slot_stage] == (2, "server")
    assert rows[three_slot_stage] == (3, "server")
    assert migrated.connect().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert migrated.connect().execute("PRAGMA foreign_key_check").fetchall() == []
    migrated.close()


def test_v19_migration_refuses_live_worker_before_backup(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _downgrade_to_v18(store)
    store.upsert_worker_heartbeat("active-v19-worker", "idle")
    store.close()

    with pytest.raises(RuntimeError, match="active workers"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert not (tmp_path / "backups").exists()


def test_v19_migration_refuses_active_actor_job_before_backup(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="v19-active-job-owner",
        password="safe-test-password",
        role="owner",
    )
    _downgrade_to_v18(store)
    store.connect().execute(
        """
        INSERT INTO fetch_jobs (
            id, workspace_id, user_id, job_type, status, payload_json,
            priority, attempts, max_attempts, created_at, updated_at
        ) VALUES (
            'active-manual-pool-migration', ?, ?, 'apify_actor_canary_batch',
            'queued', '{}', 100, 0, 1,
            '2026-08-10T00:00:00+00:00', '2026-08-10T00:00:00+00:00'
        )
        """,
        (DEFAULT_WORKSPACE_ID, owner["id"]),
    )
    store.connect().commit()
    store.close()

    with pytest.raises(RuntimeError, match="active ActorOps jobs"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert not (tmp_path / "backups").exists()


def test_v19_migration_does_not_block_normal_api_readiness(tmp_path) -> None:
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    store = ServiceStore(data_dir)
    store.initialize()
    store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="v19-readiness-owner",
        password="safe-test-password",
        role="owner",
    )
    _downgrade_to_v18(store)
    store.close()

    with TestClient(create_app(data_dir=data_dir, static_dir=static_dir)) as client:
        ready = client.get("/api/health/ready")

    assert ready.status_code == 200, ready.text


def test_v19_migration_restores_v18_database_when_verification_fails(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="v19-restore-owner",
        password="safe-test-password",
        role="owner",
    )
    _downgrade_to_v18(store)
    store.close()

    monkeypatch.setattr(
        "scripts.migrate_apify_actor_manual_pool_selection_v19."
        "apify_actor_manual_pool_selection_v19_schema_shapes_valid",
        lambda _connection: False,
    )
    with pytest.raises(RuntimeError, match="integrity checks"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    restored = sqlite3.connect(data_dir / "service.db")
    try:
        assert restored.execute(
            "SELECT username FROM users WHERE id = ?",
            (owner["id"],),
        ).fetchone() == ("v19-restore-owner",)
        columns = {
            str(row[1])
            for row in restored.execute(
                "PRAGMA table_info(apify_actor_pool_stages)"
            ).fetchall()
        }
        assert "target_slot_count" not in columns
        assert "selection_mode" not in columns
        assert restored.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 21"
        ).fetchone() is None
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        restored.close()
