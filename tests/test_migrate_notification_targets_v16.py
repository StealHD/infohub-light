from __future__ import annotations

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

import scripts.migrate_notification_targets_v16 as migration_module
from scripts.migrate_notification_channels_v15 import (
    migrate_notification_channels_v15,
)
from scripts.migrate_notification_targets_v16 import (
    migrate_notification_targets_v16,
)
from src.api.server import create_app
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore
from tests.test_migrate_notification_channels_v15 import (
    _create_v14_fixture,
)


def _create_v15_fixture(data_dir, backup_dir) -> None:
    _create_v14_fixture(data_dir)
    migrate_notification_channels_v15(
        data_dir=data_dir,
        backup_dir=backup_dir,
        apply=True,
    )
    connection = sqlite3.connect(data_dir / "service.db")
    try:
        connection.execute(
            "DELETE FROM schema_migrations WHERE version = 16"
        )
        for table in (
            "user_notification_target_bindings",
            "apify_actor_alert_target_bindings",
            "notification_targets",
        ):
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        connection.commit()
    finally:
        connection.close()


def test_v16_preserves_v15_settings_bindings_and_delivery_history(
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    _create_v15_fixture(data_dir, tmp_path / "backups-v15")
    result = migrate_notification_targets_v16(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups-v16",
        apply=True,
    )
    assert result["applied"] is True
    assert result["schema_ready"] is True
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_errors"] == 0
    assert result["target_count"] >= 2
    assert os.stat(result["backup_path"]).st_mode & 0o777 == 0o600

    store = ServiceStore(data_dir)
    store.initialize()
    assert store.notification_targets_v16_migration_required() is False
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM notification_targets
        WHERE scope = 'private'
        """
    ).fetchone()[0] >= 1
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM notification_targets
        WHERE scope = 'shared'
        """
    ).fetchone()[0] >= 1
    for table in (
        "preferred_source_notification_deliveries",
        "apify_actor_alert_deliveries",
    ):
        assert store.connect().execute(
            f"SELECT COUNT(*) FROM {table} WHERE target_id IS NULL"
        ).fetchone()[0] == 0
    assert store.connect().execute(
        "PRAGMA foreign_key_check"
    ).fetchall() == []
    store.close()

    repeated = migrate_notification_targets_v16(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups-v16",
        apply=True,
    )
    assert repeated["applied"] is False
    assert repeated["reason"] == "already_migrated"


def test_v16_rejects_active_worker_and_restores_on_validation_failure(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    _create_v15_fixture(data_dir, tmp_path / "backups-v15")
    store = ServiceStore(data_dir)
    store.initialize(prepare_notification_targets_v16=True)
    store.upsert_worker_heartbeat("active-v16-worker", "idle")
    store.close()
    with pytest.raises(RuntimeError, match="stop all horizon-worker"):
        migrate_notification_targets_v16(
            data_dir=data_dir,
            backup_dir=tmp_path / "backups-v16",
            apply=True,
        )

    connection = sqlite3.connect(data_dir / "service.db")
    connection.execute(
        """
        UPDATE worker_heartbeats
        SET heartbeat_at = '2000-01-01T00:00:00+00:00'
        """
    )
    connection.commit()
    connection.close()
    original_validate = migration_module._validate_v16_schema

    def fail_validation(*_args, **_kwargs):
        raise RuntimeError("simulated v16 validation failure")

    monkeypatch.setattr(
        migration_module,
        "_validate_v16_schema",
        fail_validation,
    )
    with pytest.raises(RuntimeError, match="simulated v16"):
        migrate_notification_targets_v16(
            data_dir=data_dir,
            backup_dir=tmp_path / "backups-v16",
            apply=True,
        )
    monkeypatch.setattr(
        migration_module,
        "_validate_v16_schema",
        original_validate,
    )
    restored = sqlite3.connect(data_dir / "service.db")
    try:
        assert restored.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 16"
        ).fetchone() is None
        assert restored.execute(
            "PRAGMA integrity_check"
        ).fetchone()[0] == "ok"
        assert restored.execute(
            """
            SELECT COUNT(*) FROM preferred_source_notification_deliveries
            """
        ).fetchone()[0] == 1
        assert restored.execute(
            """
            SELECT COUNT(*) FROM apify_actor_alert_deliveries
            """
        ).fetchone()[0] == 1
    finally:
        restored.close()


def test_v16_readiness_and_worker_fail_closed_until_migrated(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    _create_v15_fixture(data_dir, tmp_path / "backups-v15")
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    static_dir.joinpath("index.html").write_text(
        "<!doctype html>",
        encoding="utf-8",
    )
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    client = TestClient(
        create_app(data_dir=data_dir, static_dir=static_dir)
    )
    ready = client.get("/api/health/ready")
    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "migration_required"
    assert "notification targets v16" in ready.json()["error"]["message"]

    worker = run_worker_once(
        data_dir=str(data_dir),
        worker_id="v16-fail-closed-worker",
    )
    assert worker == {
        "ok": False,
        "error_code": "migration_required",
        "migration": "notification_targets_v16",
    }
