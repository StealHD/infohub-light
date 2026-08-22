from __future__ import annotations

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

from scripts.migrate_webhook_providers_v14 import (
    migrate_webhook_providers_v14,
)
from src.api.server import create_app
from src.services.worker import run_worker_once
from src.storage.service_store import (
    DEFAULT_WORKSPACE_ID,
    ServiceStore,
    WEBHOOK_PROVIDER_TRIGGER_NAMES,
)


def _unmark_v14(data_dir) -> ServiceStore:
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    for trigger in WEBHOOK_PROVIDER_TRIGGER_NAMES:
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    connection.execute("DELETE FROM schema_migrations WHERE version = 14")
    connection.commit()
    return store


def _create_legacy_test_rows(store: ServiceStore) -> str:
    user = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="webhook-migration-user",
        password="safe-test-password",
        role="member",
    )
    store.upsert_user_notification_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=str(user["id"]),
        enabled=False,
        channel="webhook",
    )
    store.record_user_notification_test(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=str(user["id"]),
        status="sent",
        tested_at="2026-07-30T00:00:00+00:00",
    )
    now = "2026-07-30T00:00:00+00:00"
    store.connect().execute(
        """
        INSERT INTO apify_actor_alert_settings (
            workspace_id, enabled, channel, events_json, generation,
            last_test_status, last_test_generation, last_tested_at,
            created_at, updated_at
        ) VALUES (?, 0, 'webhook', '[]', 1, 'sent', 1, ?, ?, ?)
        """,
        (DEFAULT_WORKSPACE_ID, now, now, now),
    )
    store.connect().commit()
    return str(user["id"])


def test_v14_dry_run_does_not_create_database(tmp_path) -> None:
    result = migrate_webhook_providers_v14(
        data_dir=tmp_path / "data",
        backup_dir=tmp_path / "backups",
        apply=False,
    )

    assert result == {
        "applied": False,
        "database_exists": False,
        "v13_migrated": False,
        "migrated": False,
        "schema_ready": False,
        "backup_path": None,
    }
    assert not (tmp_path / "data" / "service.db").exists()


def test_v14_backs_up_preserves_legacy_rows_and_installs_constraints(
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    store = _unmark_v14(data_dir)
    user_id = _create_legacy_test_rows(store)
    store.close()

    result = migrate_webhook_providers_v14(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )

    assert result["applied"] is True
    assert result["migrated"] is True
    assert result["schema_ready"] is True
    assert result["user_setting_count"] == 1
    assert result["apify_setting_count"] == 1
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_errors"] == 0
    assert result["backup_path"]
    assert os.stat(result["backup_path"]).st_mode & 0o777 == 0o600

    migrated = ServiceStore(data_dir)
    migrated.initialize()
    assert migrated.webhook_providers_v14_migration_required() is False
    personal = migrated.get_user_notification_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=user_id,
    )
    assert personal is not None
    assert personal["webhook_provider"] == "legacy_auto"
    assert personal["last_test_status"] is None
    apify = migrated.connect().execute(
        """
        SELECT * FROM apify_actor_alert_settings
        WHERE workspace_id = ?
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    assert apify is not None
    assert apify["webhook_provider"] == "legacy_auto"
    assert apify["last_test_status"] is None
    installed_triggers = {
        str(row["name"])
        for row in migrated.connect().execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'trigger'
            """
        ).fetchall()
    }
    assert WEBHOOK_PROVIDER_TRIGGER_NAMES <= installed_triggers

    with pytest.raises(sqlite3.IntegrityError):
        migrated.connect().execute(
            """
            UPDATE user_notification_settings
            SET webhook_provider = 'bogus'
            WHERE user_id = ?
            """,
            (user_id,),
        )
    migrated.connect().rollback()
    with pytest.raises(sqlite3.IntegrityError):
        migrated.connect().execute(
            """
            UPDATE apify_actor_alert_settings
            SET webhook_provider = 'slack',
                webhook_signing_env_name = 'UNSAFE',
                webhook_signing_secret_digest = ?
            WHERE workspace_id = ?
            """,
            ("a" * 64, DEFAULT_WORKSPACE_ID),
        )
    migrated.connect().rollback()
    migrated.close()

    repeated = migrate_webhook_providers_v14(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )
    assert repeated["applied"] is False
    assert repeated["reason"] == "already_migrated"
    assert repeated["schema_ready"] is True


def test_v14_requires_stopped_workers_but_not_actorops_v1(tmp_path) -> None:
    active_dir = tmp_path / "active-worker"
    store = _unmark_v14(active_dir)
    store.upsert_worker_heartbeat("active-worker", "idle")
    store.close()

    with pytest.raises(RuntimeError, match="stop all horizon-worker"):
        migrate_webhook_providers_v14(
            data_dir=active_dir,
            backup_dir=tmp_path / "backups-worker",
            apply=True,
        )
    assert not (tmp_path / "backups-worker").exists()


def test_v14_validation_failure_keeps_test_state_and_marker_absent(
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    store = _unmark_v14(data_dir)
    user_id = _create_legacy_test_rows(store)
    connection = store.connect()
    connection.execute("PRAGMA ignore_check_constraints = ON")
    connection.execute(
        """
        UPDATE user_notification_settings
        SET webhook_provider = 'bogus'
        WHERE user_id = ?
        """,
        (user_id,),
    )
    connection.execute("PRAGMA ignore_check_constraints = OFF")
    connection.commit()
    store.close()

    with pytest.raises(RuntimeError, match="invalid provider row"):
        migrate_webhook_providers_v14(
            data_dir=data_dir,
            backup_dir=tmp_path / "backups",
            apply=True,
        )

    check = sqlite3.connect(data_dir / "service.db")
    try:
        assert check.execute(
            """
            SELECT last_test_status
            FROM user_notification_settings
            WHERE user_id = ?
            """,
            (user_id,),
        ).fetchone()[0] == "sent"
        assert check.execute(
            """
            SELECT last_test_status
            FROM apify_actor_alert_settings
            WHERE workspace_id = ?
            """,
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()[0] == "sent"
        assert check.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 14"
        ).fetchone() is None
    finally:
        check.close()


def test_api_and_worker_fail_closed_until_v14_is_applied(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html>",
        encoding="utf-8",
    )
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = _unmark_v14(data_dir)
    store.close()

    client = TestClient(
        create_app(data_dir=data_dir, static_dir=static_dir)
    )
    ready = client.get("/api/health/ready")
    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "migration_required"
    assert "Webhook providers v14" in ready.json()["error"]["message"]

    assert run_worker_once(
        data_dir=str(data_dir),
        worker_id="v14-gated-worker",
    ) == {
        "ok": False,
        "error_code": "migration_required",
        "migration": "webhook_providers_v14",
    }

def test_marker_with_invalid_rows_still_fails_closed(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text(
        "<!doctype html>",
        encoding="utf-8",
    )
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(data_dir)
    store.initialize()
    user_id = _create_legacy_test_rows(store)
    connection = store.connect()
    connection.execute(
        """
        DROP TRIGGER
        trg_user_notification_settings_webhook_v14_update
        """
    )
    connection.execute("PRAGMA ignore_check_constraints = ON")
    connection.execute(
        """
        UPDATE user_notification_settings
        SET webhook_provider = 'bogus'
        WHERE user_id = ?
        """,
        (user_id,),
    )
    connection.execute("PRAGMA ignore_check_constraints = OFF")
    connection.commit()
    store.close()

    client = TestClient(
        create_app(data_dir=data_dir, static_dir=static_dir)
    )
    ready = client.get("/api/health/ready")
    assert ready.status_code == 503
    assert "Webhook providers v14" in ready.json()["error"]["message"]
    assert run_worker_once(
        data_dir=str(data_dir),
        worker_id="v14-corrupt-worker",
    ) == {
        "ok": False,
        "error_code": "migration_required",
        "migration": "webhook_providers_v14",
    }
