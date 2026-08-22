from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from scripts.migrate_apify_actor_validation_tuning_v20 import (
    _rebuild_table,
    migrate,
)
from src.api.server import create_app
from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


_NOW = "2026-08-10T00:00:00+00:00"


def _downgrade_to_v19(store: ServiceStore) -> None:
    connection = store.connect()
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            "DROP INDEX IF EXISTS idx_apify_actor_validation_failure_fingerprint"
        )
        connection.execute("DROP TABLE apify_actor_pool_stage_candidate_settings")
        for column in (
            "mapped_item_count",
            "dataset_row_count",
            "duration_seconds",
            "failure_fingerprint",
            "validation_profile_hash",
            "validation_sample_items",
            "validation_timeout_seconds",
        ):
            connection.execute(
                f"ALTER TABLE apify_actor_validations DROP COLUMN {column}"
            )
        _rebuild_table(
            connection,
            "apify_actor_canary_batches",
            replacements=(
                ("max_total_charge_usd <= 0.60", "max_total_charge_usd <= 0.06"),
                ("per_candidate_cap_usd <= 0.20", "per_candidate_cap_usd <= 0.02"),
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
            replacements=(
                ("authorized_cap_usd <= 0.20", "authorized_cap_usd <= 0.02"),
            ),
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
            replacements=(
                (
                    "route_validation_cap_usd <= 0.30",
                    "route_validation_cap_usd <= 0.06",
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
        connection.execute("DELETE FROM schema_migrations WHERE version = 22")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _seed_v19_validation_and_stage(store: ServiceStore) -> dict[str, str]:
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="v20-migration-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store)
    route = next(
        item for item in ops.list_routes() if item["route_key"] == "x/profile"
    )
    active = next(
        slot for slot in ops.get_route(str(route["route_id"]))["slots"]
        if slot["revision_id"]
    )
    revision_id = str(active["revision_id"])
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="validation-tuning-migration",
        expected_generation=int(route["generation"]),
    )
    failed_id = "migration-validation-failed"
    cancelled_id = "migration-validation-cancelled"
    connection = store.connect()
    for validation_id, status, semantic in (
        (failed_id, "failed", "suspicious_empty"),
        (cancelled_id, "cancelled", "not_needed_no_charge"),
    ):
        connection.execute(
            """
            INSERT INTO apify_actor_validations (
                validation_id, workspace_id, route_id, revision_id,
                discovery_run_id, kind, approved_max_cost_usd,
                target_fingerprint, status, semantic_outcome,
                cost_usd, cost_final, counts_toward_canary,
                created_at, completed_at
            ) VALUES (?, ?, ?, ?, ?, 'route_reference', 0.02, ?, ?, ?,
                      ?, 1, 1, ?, ?)
            """,
            (
                validation_id,
                DEFAULT_WORKSPACE_ID,
                route["route_id"],
                revision_id,
                run["run_id"],
                ("a" if status == "failed" else "b") * 64,
                status,
                semantic,
                0.000445 if status == "failed" else 0.0,
                _NOW,
                "2026-08-10T00:05:00+00:00",
            ),
        )
    batch_id = "migration-validation-tuning-batch"
    stage_id = "migration-validation-tuning-stage"
    connection.execute(
        """
        INSERT INTO apify_actor_canary_batches (
            batch_id, workspace_id, route_id, discovery_run_id,
            approval_key_hash, approved_generation, plan_hash,
            max_candidates, max_total_charge_usd, per_candidate_cap_usd,
            goal, pool_stage_id, status, planned_count, success_count,
            publisher_count, actual_cost_usd, cost_final, stop_reason,
            created_by_user_id, created_at, completed_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 0.02, 0.02,
                  'upgrade_legacy', ?, 'partial', 1, 0, 0, 0.000445, 1,
                  'candidate_failed', ?, ?, ?, ?)
        """,
        (
            batch_id,
            DEFAULT_WORKSPACE_ID,
            route["route_id"],
            run["run_id"],
            "c" * 64,
            route["generation"],
            "d" * 64,
            stage_id,
            owner["id"],
            _NOW,
            "2026-08-10T00:05:00+00:00",
            "2026-08-10T00:05:00+00:00",
        ),
    )
    connection.execute(
        """
        INSERT INTO apify_actor_pool_stages (
            stage_id, workspace_id, route_id, discovery_run_id,
            initial_batch_id, goal, target_slot_count, selection_mode,
            base_generation, base_pool_hash, plan_hash, approval_key_hash,
            max_total_charge_usd, route_validation_cap_usd,
            status, created_by_user_id, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'upgrade_legacy', 3, 'manual', ?, ?, ?, ?,
                  0.02, 0.02, 'failed', ?, ?, ?)
        """,
        (
            stage_id,
            DEFAULT_WORKSPACE_ID,
            route["route_id"],
            run["run_id"],
            batch_id,
            route["generation"],
            "e" * 64,
            "d" * 64,
            "c" * 64,
            owner["id"],
            _NOW,
            "2026-08-10T00:05:00+00:00",
        ),
    )
    connection.execute(
        """
        INSERT INTO apify_actor_canary_batch_items (
            workspace_id, batch_id, ordinal, revision_id, validation_id,
            status, semantic_outcome, authorized_cap_usd,
            actual_cost_usd, cost_final, completed_at, updated_at
        ) VALUES (?, ?, 1, ?, ?, 'failed', 'suspicious_empty', 0.02,
                  0.000445, 1, ?, ?)
        """,
        (
            DEFAULT_WORKSPACE_ID,
            batch_id,
            revision_id,
            failed_id,
            "2026-08-10T00:05:00+00:00",
            "2026-08-10T00:05:00+00:00",
        ),
    )
    connection.commit()
    return {
        "failed_id": failed_id,
        "cancelled_id": cancelled_id,
        "stage_id": stage_id,
    }


def test_v20_migration_backfills_profiles_metrics_and_repeat_guard(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    ids = _seed_v19_validation_and_stage(store)
    _downgrade_to_v19(store)
    store.close()

    assert migrate(data_dir, apply=False)["required"] is True
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["applied"] is True
    assert result["backup_mode"] == "0o600"
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_violations"] == 0
    migrated = ServiceStore(data_dir)
    migrated.initialize()
    assert migrated.apify_actor_validation_tuning_v20_migration_required() is False
    failed = migrated.connect().execute(
        """
        SELECT validation_timeout_seconds, validation_sample_items,
               validation_profile_hash, duration_seconds,
               dataset_row_count, mapped_item_count, failure_fingerprint
        FROM apify_actor_validations WHERE validation_id = ?
        """,
        (ids["failed_id"],),
    ).fetchone()
    assert tuple(failed[:2]) == (300, 1)
    assert len(str(failed["validation_profile_hash"])) == 64
    assert failed["duration_seconds"] == 300
    assert (failed["dataset_row_count"], failed["mapped_item_count"]) == (0, 0)
    assert len(str(failed["failure_fingerprint"])) == 64
    cancelled = migrated.connect().execute(
        "SELECT failure_fingerprint FROM apify_actor_validations WHERE validation_id = ?",
        (ids["cancelled_id"],),
    ).fetchone()
    assert cancelled["failure_fingerprint"] is None
    settings = migrated.connect().execute(
        """
        SELECT timeout_seconds, sample_items, max_charge_usd,
               supports_sample_items, profile_hash
        FROM apify_actor_pool_stage_candidate_settings
        WHERE stage_id = ?
        """,
        (ids["stage_id"],),
    ).fetchone()
    assert tuple(settings[:4]) == (300, 1, 0.02, 0)
    assert len(str(settings["profile_hash"])) == 64
    assert migrated.connect().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert migrated.connect().execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.parametrize("active_kind", ["worker", "job"])
def test_v20_migration_refuses_active_actorops_before_backup(
    tmp_path,
    active_kind: str,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username=f"v20-active-{active_kind}",
        password="safe-test-password",
        role="owner",
    )
    _downgrade_to_v19(store)
    if active_kind == "worker":
        store.upsert_worker_heartbeat("active-v20-worker", "idle")
    else:
        store.connect().execute(
            """
            INSERT INTO fetch_jobs (
                id, workspace_id, user_id, job_type, status, payload_json,
                priority, attempts, max_attempts, created_at, updated_at
            ) VALUES ('active-v20-job', ?, ?, 'apify_actor_canary_batch',
                      'queued', '{}', 100, 0, 1, ?, ?)
            """,
            (DEFAULT_WORKSPACE_ID, owner["id"], _NOW, _NOW),
        )
        store.connect().commit()
    store.close()

    expected = "active workers" if active_kind == "worker" else "active ActorOps jobs"
    with pytest.raises(RuntimeError, match=expected):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert not (tmp_path / "backups").exists()


def test_v20_migration_does_not_block_normal_api_readiness(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    store = ServiceStore(data_dir)
    store.initialize()
    _downgrade_to_v19(store)
    store.close()
    monkeypatch.setenv("HORIZON_AUTH_USER", "v20-readiness-owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "safe-test-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "v20-readiness-secret")

    with TestClient(create_app(data_dir=data_dir, static_dir=static_dir)) as client:
        ready = client.get("/api/health/ready")

    assert ready.status_code == 200, ready.text


def test_v20_migration_restores_v19_database_when_verification_fails(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="v20-restore-owner",
        password="safe-test-password",
        role="owner",
    )
    _downgrade_to_v19(store)
    store.close()

    monkeypatch.setattr(
        "scripts.migrate_apify_actor_validation_tuning_v20."
        "apify_actor_validation_tuning_v20_schema_shapes_valid",
        lambda _connection: False,
    )
    with pytest.raises(RuntimeError, match="integrity checks"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    restored = sqlite3.connect(data_dir / "service.db")
    try:
        assert restored.execute(
            "SELECT username FROM users WHERE id = ?",
            (owner["id"],),
        ).fetchone() == ("v20-restore-owner",)
        columns = {
            str(row[1])
            for row in restored.execute(
                "PRAGMA table_info(apify_actor_validations)"
            ).fetchall()
        }
        assert "validation_timeout_seconds" not in columns
        assert restored.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 22"
        ).fetchone() is None
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        restored.close()
