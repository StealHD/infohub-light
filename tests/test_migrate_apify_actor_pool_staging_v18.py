from __future__ import annotations

import sqlite3

import pytest

from scripts.migrate_apify_actor_pool_staging_v18 import migrate
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from tests.actorops_v1_migration_fixture import initialize_historical_actorops


def _remove_v18_schema(store: ServiceStore) -> None:
    connection = store.connect()
    connection.execute("DROP TABLE apify_actor_pool_stage_sources")
    connection.execute("DROP TABLE apify_actor_pool_stages")
    connection.execute("ALTER TABLE apify_actor_canary_batches DROP COLUMN pool_stage_id")
    connection.execute("ALTER TABLE apify_actor_canary_batches DROP COLUMN goal")
    connection.execute("DELETE FROM schema_migrations WHERE version = 20")
    connection.commit()


def test_v18_offline_migration_adds_staging_schema_and_private_backup(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    initialize_historical_actorops(store)
    _remove_v18_schema(store)
    store.close()

    assert migrate(data_dir, apply=False)["required"] is True
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["applied"] is True
    assert result["backup_mode"] == "0o600"
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_violations"] == 0
    migrated = ServiceStore(data_dir)
    migrated.initialize()
    assert migrated.apify_actor_pool_staging_v18_migration_required() is False
    tables = {
        str(row["name"])
        for row in migrated.connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "apify_actor_pool_stages",
        "apify_actor_pool_stage_sources",
    } <= tables
    batch_columns = {
        str(row["name"])
        for row in migrated.connect().execute(
            "PRAGMA table_info(apify_actor_canary_batches)"
        ).fetchall()
    }
    assert {"goal", "pool_stage_id"} <= batch_columns
    assert migrated.connect().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert migrated.connect().execute("PRAGMA foreign_key_check").fetchall() == []
    migrated.close()


def test_v18_migration_refuses_active_actor_job_before_backup(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    initialize_historical_actorops(store)
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="v18-migration-owner",
        password="safe-test-password",
        role="owner",
    )
    _remove_v18_schema(store)
    store.connect().execute(
        """
        INSERT INTO fetch_jobs (
            id, workspace_id, user_id, job_type, status, payload_json,
            priority, attempts, max_attempts, created_at, updated_at
        ) VALUES (
            'active-pool-stage-migration', ?, ?, 'apify_actor_canary_batch',
            'queued', '{}', 100, 0, 1,
            '2026-08-09T00:00:00+00:00', '2026-08-09T00:00:00+00:00'
        )
        """,
        (DEFAULT_WORKSPACE_ID, owner["id"]),
    )
    store.connect().commit()
    store.close()

    with pytest.raises(RuntimeError, match="active ActorOps jobs"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert not (tmp_path / "backups").exists()


def test_v18_migration_refuses_a_live_worker_before_backup(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    initialize_historical_actorops(store)
    _remove_v18_schema(store)
    store.upsert_worker_heartbeat("active-v18-worker", "idle")
    store.close()

    with pytest.raises(RuntimeError, match="active workers"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert not (tmp_path / "backups").exists()


def test_v18_migration_repairs_a_drifted_schema_marker(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    initialize_historical_actorops(store)
    store.connect().execute(
        """
        UPDATE schema_migrations SET checksum = 'drifted-checksum'
        WHERE version = 20 AND name = 'apify_actor_pool_staging_v18'
        """
    )
    store.connect().commit()
    store.close()

    assert migrate(data_dir, apply=False)["required"] is True
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["applied"] is True
    repaired = ServiceStore(data_dir)
    repaired.initialize()
    assert repaired.apify_actor_pool_staging_v18_migration_required() is False
    repaired.close()


def test_v18_migration_restores_v17_database_when_verification_fails(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    initialize_historical_actorops(store)
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="v18-restore-owner",
        password="safe-test-password",
        role="owner",
    )
    _remove_v18_schema(store)
    store.close()

    monkeypatch.setattr(
        "scripts.migrate_apify_actor_pool_staging_v18."
        "apify_actor_pool_staging_v18_schema_shapes_valid",
        lambda _connection: False,
    )
    with pytest.raises(RuntimeError, match="pool staging schema validation"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    restored = sqlite3.connect(data_dir / "service.db")
    try:
        assert restored.execute(
            "SELECT username FROM users WHERE id = ?",
            (owner["id"],),
        ).fetchone() == ("v18-restore-owner",)
        tables = {
            str(row[0])
            for row in restored.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "apify_actor_pool_stages" not in tables
        assert "apify_actor_pool_stage_sources" not in tables
        columns = {
            str(row[1])
            for row in restored.execute(
                "PRAGMA table_info(apify_actor_canary_batches)"
            ).fetchall()
        }
        assert "goal" not in columns
        assert "pool_stage_id" not in columns
        assert restored.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 20"
        ).fetchone() is None
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        restored.close()
