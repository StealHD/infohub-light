from __future__ import annotations

import os
import sqlite3

import pytest
from fastapi.testclient import TestClient

import scripts.migrate_notification_channels_v15 as migration_module
from scripts.migrate_notification_channels_v15 import (
    migrate_notification_channels_v15,
)
from src.api.server import create_app
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


NOW = "2026-07-30T00:00:00+00:00"


def _has_column(store: ServiceStore, table: str, column: str) -> bool:
    return column in {
        str(row["name"])
        for row in store.connect().execute(
            f"PRAGMA table_info({table})"
        ).fetchall()
    }


def _create_v14_fixture(data_dir) -> tuple[str, str, str]:
    store = ServiceStore(data_dir)
    store.initialize()
    user = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="notification-v15-user",
        password="safe-test-password",
        role="member",
    )
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="private",
        owner_user_id=str(user["id"]),
        source_type="rss",
        display_name="Notification migration fixture",
        config={"url": "https://example.invalid/feed.xml"},
    )
    subscription = store.create_subscription(
        user_id=str(user["id"]),
        source_id=source_id,
        notify_on_new_items=True,
    )
    store.upsert_user_notification_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=str(user["id"]),
        enabled=True,
        channel="email",
        email_address="notify@example.invalid",
        webhook_env_name="HORIZON_TEST_WEBHOOK",
        webhook_secret_digest="a" * 64,
        webhook_provider="generic_event",
    )
    store.record_user_notification_test(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=str(user["id"]),
        status="sent",
        tested_at=NOW,
    )

    preferred_columns = [
        "id",
        "workspace_id",
        "user_id",
        "subscription_id",
        "source_id",
        "snapshot_id",
        "job_id",
        "article_id",
        "channel",
        "payload_json",
        "status",
        "attempts",
        "account_notification_generation",
    ]
    preferred_values: list[object] = [
        "delivery-before-v15",
        DEFAULT_WORKSPACE_ID,
        str(user["id"]),
        str(subscription["id"]),
        source_id,
        "snapshot-before-v15",
        "job-before-v15",
        "article-before-v15",
        "email",
        '{"safe":true}',
        "succeeded",
        1,
        1,
    ]
    if _has_column(
        store,
        "preferred_source_notification_deliveries",
        "channel_notification_generation",
    ):
        preferred_columns.append("channel_notification_generation")
        preferred_values.append(1)
    preferred_columns.extend(
        (
            "subscription_notification_generation",
            "created_at",
            "sent_at",
            "updated_at",
        )
    )
    preferred_values.extend((1, NOW, NOW, NOW))
    store.connect().execute(
        f"""
        INSERT INTO preferred_source_notification_deliveries (
            {", ".join(preferred_columns)}
        ) VALUES ({", ".join("?" for _column in preferred_columns)})
        """,
        preferred_values,
    )

    apify_columns = [
        "workspace_id",
        "enabled",
        "channel",
        "events_json",
        "email_address",
        "webhook_env_name",
        "webhook_secret_digest",
        "webhook_provider",
        "generation",
    ]
    apify_values: list[object] = [
        DEFAULT_WORKSPACE_ID,
        1,
        "webhook",
        '["route_exhausted"]',
        "alerts@example.invalid",
        "HORIZON_TEST_ALERT_WEBHOOK",
        "b" * 64,
        "generic_event",
        4,
    ]
    if _has_column(
        store,
        "apify_actor_alert_settings",
        "notification_enabled_at",
    ):
        apify_columns.append("notification_enabled_at")
        apify_values.append(NOW)
    apify_columns.extend(
        (
            "last_test_status",
            "last_test_generation",
            "last_test_attempted_at",
            "last_tested_at",
            "created_at",
            "updated_at",
        )
    )
    apify_values.extend(("sent", 4, NOW, NOW, NOW, NOW))
    store.connect().execute(
        f"""
        INSERT INTO apify_actor_alert_settings (
            {", ".join(apify_columns)}
        ) VALUES ({", ".join("?" for _column in apify_columns)})
        """,
        apify_values,
    )
    store.connect().execute(
        """
        INSERT INTO apify_actor_alert_incidents (
            id, workspace_id, route_key, incident_key, event_type,
            severity, status, payload_json, opened_at, last_seen_at,
            created_at, updated_at
        ) VALUES (
            'incident-before-v15', ?, 'x/profile', 'migration-fixture',
            'route_exhausted', 'critical', 'open', '{}', ?, ?, ?, ?
        )
        """,
        (DEFAULT_WORKSPACE_ID, NOW, NOW, NOW, NOW),
    )
    alert_columns = [
        "id",
        "workspace_id",
        "incident_id",
        "event_type",
        "channel",
        "settings_generation",
    ]
    alert_values: list[object] = [
        "alert-delivery-before-v15",
        DEFAULT_WORKSPACE_ID,
        "incident-before-v15",
        "route_exhausted",
        "webhook",
        4,
    ]
    if _has_column(
        store,
        "apify_actor_alert_deliveries",
        "channel_generation",
    ):
        alert_columns.append("channel_generation")
        alert_values.append(4)
    alert_columns.extend(
        (
            "payload_json",
            "status",
            "attempts",
            "created_at",
            "sent_at",
            "updated_at",
        )
    )
    alert_values.extend(('{"safe":true}', "succeeded", 1, NOW, NOW, NOW))
    store.connect().execute(
        f"""
        INSERT INTO apify_actor_alert_deliveries (
            {", ".join(alert_columns)}
        ) VALUES ({", ".join("?" for _column in alert_columns)})
        """,
        alert_values,
    )

    for table in (
        "user_notification_channels",
        "workspace_telegram_transports",
        "apify_actor_alert_channels",
    ):
        store.connect().execute(f"DROP TABLE IF EXISTS {table}")
    store.connect().execute(
        "DELETE FROM schema_migrations WHERE version = 15"
    )
    store.connect().commit()
    store.close()
    return str(user["id"]), str(subscription["id"]), source_id


def test_v15_dry_run_does_not_create_database(tmp_path) -> None:
    result = migrate_notification_channels_v15(
        data_dir=tmp_path / "data",
        backup_dir=tmp_path / "backups",
        apply=False,
    )

    assert result == {
        "applied": False,
        "database_exists": False,
        "v14_migrated": False,
        "migrated": False,
        "schema_ready": False,
        "backup_path": None,
    }
    assert not (tmp_path / "data" / "service.db").exists()


def test_v15_preserves_settings_and_history_and_installs_constraints(
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    user_id, subscription_id, _source_id = _create_v14_fixture(data_dir)

    result = migrate_notification_channels_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )

    assert result["applied"] is True
    assert result["migrated"] is True
    assert result["schema_ready"] is True
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_errors"] == 0
    assert result["counts"] == {
        "user_notification_settings": 1,
        "preferred_source_notification_deliveries": 1,
        "apify_actor_alert_settings": 1,
        "apify_actor_alert_incidents": 1,
        "apify_actor_alert_deliveries": 1,
    }
    assert result["backup_path"]
    assert os.stat(result["backup_path"]).st_mode & 0o777 == 0o600

    migrated = ServiceStore(data_dir)
    migrated.initialize()
    assert (
        migrated.multichannel_notifications_v15_migration_required()
        is False
    )
    settings = migrated.get_user_notification_settings(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=user_id,
    )
    assert settings is not None
    assert settings["channel"] == "email"
    assert settings["email_address"] == "notify@example.invalid"
    assert settings["webhook_env_name"] == "HORIZON_TEST_WEBHOOK"
    personal_channels = migrated.connect().execute(
        """
        SELECT channel, enabled, destination_env_name
        FROM user_notification_channels
        WHERE user_id = ?
        ORDER BY channel
        """,
        (user_id,),
    ).fetchall()
    assert [
        (row["channel"], row["enabled"], row["destination_env_name"])
        for row in personal_channels
    ] == [
        ("email", 1, None),
        ("telegram", 0, None),
        ("webhook", 0, None),
    ]
    alert_channels = migrated.connect().execute(
        """
        SELECT channel, enabled, destination_env_name
        FROM apify_actor_alert_channels
        WHERE workspace_id = ?
        ORDER BY channel
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchall()
    assert [
        (row["channel"], row["enabled"], row["destination_env_name"])
        for row in alert_channels
    ] == [
        ("email", 0, None),
        ("telegram", 0, None),
        ("webhook", 1, None),
    ]

    migrated.connect().execute(
        """
        UPDATE user_notification_settings
        SET channel = 'telegram'
        WHERE user_id = ?
        """,
        (user_id,),
    )
    migrated.connect().execute(
        """
        INSERT INTO preferred_source_notification_deliveries (
            id, workspace_id, user_id, subscription_id, source_id,
            snapshot_id, job_id, article_id, channel, payload_json,
            status, attempts, account_notification_generation,
            channel_notification_generation,
            subscription_notification_generation, created_at, updated_at
        )
        SELECT
            'delivery-telegram-after-v15', workspace_id, user_id,
            subscription_id, source_id, snapshot_id, job_id, article_id,
            'telegram', payload_json, 'pending', 0,
            account_notification_generation, 1,
            subscription_notification_generation, created_at, updated_at
        FROM preferred_source_notification_deliveries
        WHERE id = 'delivery-before-v15'
        """
    )
    migrated.connect().execute(
        """
        INSERT INTO apify_actor_alert_deliveries (
            id, workspace_id, incident_id, event_type, channel,
            settings_generation, channel_generation, payload_json, status,
            attempts, created_at, updated_at
        )
        SELECT
            'alert-delivery-telegram-after-v15', workspace_id, incident_id,
            event_type, 'telegram', settings_generation, 1, payload_json,
            'pending', 0, created_at, updated_at
        FROM apify_actor_alert_deliveries
        WHERE id = 'alert-delivery-before-v15'
        """
    )
    migrated.connect().commit()
    assert migrated.connect().execute(
        """
        SELECT COUNT(*)
        FROM preferred_source_notification_deliveries
        WHERE subscription_id = ? AND article_id = 'article-before-v15'
        """,
        (subscription_id,),
    ).fetchone()[0] == 2
    assert migrated.connect().execute(
        """
        SELECT COUNT(*)
        FROM apify_actor_alert_deliveries
        WHERE incident_id = 'incident-before-v15'
          AND event_type = 'route_exhausted'
        """
    ).fetchone()[0] == 2
    migrated.close()

    repeated = migrate_notification_channels_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )
    assert repeated["applied"] is False
    assert repeated["reason"] == "already_migrated"
    assert repeated["schema_ready"] is True


def test_v15_requires_v14_and_stopped_workers(tmp_path) -> None:
    missing_v14_dir = tmp_path / "missing-v14"
    store = ServiceStore(missing_v14_dir)
    store.initialize()
    store.connect().execute(
        "DELETE FROM schema_migrations WHERE version IN (14, 15)"
    )
    store.connect().commit()
    store.close()

    with pytest.raises(RuntimeError, match="Webhook providers v14"):
        migrate_notification_channels_v15(
            data_dir=missing_v14_dir,
            backup_dir=tmp_path / "backups-v14",
            apply=True,
        )
    assert not (tmp_path / "backups-v14").exists()

    active_dir = tmp_path / "active-worker"
    _create_v14_fixture(active_dir)
    store = ServiceStore(active_dir)
    store.initialize()
    store.upsert_worker_heartbeat("active-worker", "idle")
    store.close()

    with pytest.raises(RuntimeError, match="stop all horizon-worker"):
        migrate_notification_channels_v15(
            data_dir=active_dir,
            backup_dir=tmp_path / "backups-worker",
            apply=True,
        )
    assert not (tmp_path / "backups-worker").exists()


def test_v15_marker_with_missing_constraints_is_not_treated_as_complete(
    tmp_path,
) -> None:
    data_dir = tmp_path / "invalid-marker"
    _create_v14_fixture(data_dir)
    connection = sqlite3.connect(data_dir / "service.db")
    try:
        connection.execute(
            """
            INSERT INTO schema_migrations (
                version, name, checksum, applied_at
            ) VALUES (
                15, 'multichannel_notifications_v15',
                'telegram-multichannel-notifications-v15', ?
            )
            """,
            (NOW,),
        )
        connection.commit()
    finally:
        connection.close()

    dry_run = migrate_notification_channels_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=False,
    )
    assert dry_run["migrated"] is True
    assert dry_run["schema_ready"] is False
    with pytest.raises(RuntimeError, match="marker exists"):
        migrate_notification_channels_v15(
            data_dir=data_dir,
            backup_dir=tmp_path / "backups",
            apply=True,
        )
    assert not (tmp_path / "backups").exists()


def test_v15_validation_failure_restores_database(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    _create_v14_fixture(data_dir)
    db_path = data_dir / "service.db"
    before = sqlite3.connect(db_path)
    try:
        before_sql = before.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table'
              AND name = 'preferred_source_notification_deliveries'
            """
        ).fetchone()[0]
    finally:
        before.close()

    def fail_validation(_connection):
        raise RuntimeError("simulated v15 validation failure")

    monkeypatch.setattr(
        migration_module,
        "_validate_v15_schema",
        fail_validation,
    )
    with pytest.raises(RuntimeError, match="simulated v15"):
        migrate_notification_channels_v15(
            data_dir=data_dir,
            backup_dir=tmp_path / "backups",
            apply=True,
        )

    restored = sqlite3.connect(db_path)
    try:
        assert restored.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 15"
        ).fetchone() is None
        restored_sql = restored.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table'
              AND name = 'preferred_source_notification_deliveries'
            """
        ).fetchone()[0]
        assert restored_sql == before_sql
        assert restored.execute(
            """
            SELECT COUNT(*)
            FROM preferred_source_notification_deliveries
            """
        ).fetchone()[0] == 1
    finally:
        restored.close()


def test_api_readiness_fails_closed_until_v15_is_applied(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    static_dir.joinpath("index.html").write_text(
        "<!doctype html>",
        encoding="utf-8",
    )
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(data_dir)
    store.initialize()
    for table in (
        "user_notification_channels",
        "workspace_telegram_transports",
        "apify_actor_alert_channels",
    ):
        store.connect().execute(f"DROP TABLE IF EXISTS {table}")
    store.connect().execute(
        "DELETE FROM schema_migrations WHERE version = 15"
    )
    store.connect().commit()
    store.close()

    client = TestClient(
        create_app(data_dir=data_dir, static_dir=static_dir)
    )
    ready = client.get("/api/health/ready")
    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "migration_required"
    assert "notification channels v15" in ready.json()["error"]["message"]
