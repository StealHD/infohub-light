#!/usr/bin/env python3
"""Install multi-channel notification settings with a verified backup."""

from __future__ import annotations

import argparse
import json
import os
import sqlite3
import sys
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.migrate_user_feed_v2 import _active_workers
from src.storage.service_store import ServiceStore


NOTIFICATION_CHANNELS = ("email", "webhook", "telegram")
REQUIRED_TABLES = {
    "user_notification_channels",
    "workspace_telegram_transports",
    "apify_actor_alert_channels",
}
COUNTED_TABLES = (
    "user_notification_settings",
    "preferred_source_notification_deliveries",
    "apify_actor_alert_settings",
    "apify_actor_alert_incidents",
    "apify_actor_alert_deliveries",
)


def _table_exists(connection: sqlite3.Connection, table: str) -> bool:
    return bool(
        connection.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table,),
        ).fetchone()
    )


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})")
    }


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        )
        for table in COUNTED_TABLES
    }


def _has_unique_columns(
    connection: sqlite3.Connection,
    table: str,
    expected: tuple[str, ...],
) -> bool:
    for index_row in connection.execute(
        f"PRAGMA index_list({table})"
    ).fetchall():
        unique = bool(index_row[2])
        origin = str(index_row[3])
        partial = bool(index_row[4])
        if (
            not unique
            or partial
            or origin not in {"u", "pk"}
        ):
            continue
        columns = tuple(
            str(row[2])
            for row in connection.execute(
                f"PRAGMA index_info({index_row[1]})"
            ).fetchall()
        )
        if columns == expected:
            return True
    return False


def _validate_v15_schema(
    connection: sqlite3.Connection,
) -> dict[str, Any]:
    installed = {
        str(row[0])
        for row in connection.execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table'
            """
        ).fetchall()
    }
    missing_tables = sorted(REQUIRED_TABLES - installed)
    if missing_tables:
        raise RuntimeError(
            "notification channels v15 is missing table(s): "
            + ", ".join(missing_tables)
        )

    required_columns = {
        "user_notification_settings": {"channel"},
        "apify_actor_alert_settings": {
            "channel",
            "notification_enabled_at",
        },
        "preferred_source_notification_deliveries": {
            "channel",
            "channel_notification_generation",
        },
        "apify_actor_alert_deliveries": {
            "channel",
            "channel_generation",
        },
        "workspace_telegram_transports": {
            "workspace_id",
            "enabled",
            "token_env_name",
            "token_secret_digest",
            "generation",
            "last_test_status",
            "last_test_generation",
            "last_test_attempted_at",
            "last_tested_at",
            "last_test_error_code",
        },
    }
    for table, expected in required_columns.items():
        missing = sorted(expected - _columns(connection, table))
        if missing:
            raise RuntimeError(
                f"{table} is missing v15 column(s): {', '.join(missing)}"
            )

    placeholders = ",".join("?" for _channel in NOTIFICATION_CHANNELS)
    for table in (
        "user_notification_settings",
        "apify_actor_alert_settings",
        "preferred_source_notification_deliveries",
        "apify_actor_alert_deliveries",
    ):
        invalid = connection.execute(
            f"""
            SELECT COUNT(*) FROM {table}
            WHERE channel NOT IN ({placeholders})
            """,
            NOTIFICATION_CHANNELS,
        ).fetchone()
        if invalid and int(invalid[0]):
            raise RuntimeError(
                f"{table} contains {int(invalid[0])} invalid channel row(s)"
            )
        table_sql_row = connection.execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'table' AND name = ?
            """,
            (table,),
        ).fetchone()
        table_sql = str(table_sql_row[0] if table_sql_row else "")
        if "'telegram'" not in table_sql:
            raise RuntimeError(
                f"{table} does not accept the Telegram channel"
            )

    for table in (
        "user_notification_channels",
        "apify_actor_alert_channels",
    ):
        invalid = connection.execute(
            f"""
            SELECT COUNT(*) FROM {table}
            WHERE channel NOT IN ({placeholders})
               OR enabled NOT IN (0, 1)
               OR position < 0
               OR (
                    (destination_env_name IS NULL)
                    != (destination_secret_digest IS NULL)
               )
               OR (
                    destination_secret_digest IS NOT NULL
                    AND (
                        length(destination_secret_digest) != 64
                        OR destination_secret_digest GLOB '*[^0-9a-f]*'
                    )
               )
            """,
            NOTIFICATION_CHANNELS,
        ).fetchone()
        if invalid and int(invalid[0]):
            raise RuntimeError(
                f"{table} contains {int(invalid[0])} invalid row(s)"
            )

    invalid_transport = connection.execute(
        """
        SELECT COUNT(*) FROM workspace_telegram_transports
        WHERE enabled NOT IN (0, 1)
           OR generation < 0
           OR (
                (token_env_name IS NULL)
                != (token_secret_digest IS NULL)
           )
           OR (
                token_secret_digest IS NOT NULL
                AND (
                    length(token_secret_digest) != 64
                    OR token_secret_digest GLOB '*[^0-9a-f]*'
                )
           )
        """
    ).fetchone()
    if invalid_transport and int(invalid_transport[0]):
        raise RuntimeError(
            "workspace_telegram_transports contains "
            f"{int(invalid_transport[0])} invalid row(s)"
        )

    if not _has_unique_columns(
        connection,
        "preferred_source_notification_deliveries",
        ("subscription_id", "article_id", "channel"),
    ):
        raise RuntimeError(
            "preferred-source delivery channel uniqueness is missing"
        )
    if not _has_unique_columns(
        connection,
        "apify_actor_alert_deliveries",
        ("incident_id", "event_type", "channel"),
    ):
        raise RuntimeError(
            "Apify alert delivery channel uniqueness is missing"
        )

    integrity_row = connection.execute("PRAGMA integrity_check").fetchone()
    integrity_check = str(
        integrity_row[0] if integrity_row else "unknown"
    )
    foreign_key_errors = connection.execute(
        "PRAGMA foreign_key_check"
    ).fetchall()
    if integrity_check.casefold() != "ok":
        raise RuntimeError(f"integrity check failed: {integrity_check}")
    if foreign_key_errors:
        raise RuntimeError(
            "foreign key check failed: "
            f"{len(foreign_key_errors)} row(s)"
        )
    return {
        "counts": _counts(connection),
        "integrity_check": integrity_check,
        "foreign_key_errors": len(foreign_key_errors),
    }


def _inspect(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "database_exists": False,
            "v14_migrated": False,
            "migrated": False,
            "schema_ready": False,
        }
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        has_migrations = _table_exists(connection, "schema_migrations")
        versions = (
            {
                int(row[0])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            if has_migrations
            else set()
        )
        schema_ready = False
        if 15 in versions:
            try:
                _validate_v15_schema(connection)
                schema_ready = True
            except (RuntimeError, sqlite3.DatabaseError):
                schema_ready = False
        return {
            "database_exists": True,
            "v14_migrated": 14 in versions,
            "migrated": 15 in versions,
            "schema_ready": schema_ready,
        }
    finally:
        connection.close()


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"service-notification-channels-v15-{stamp}.db"
    descriptor = os.open(
        target,
        os.O_CREAT | os.O_EXCL | os.O_WRONLY,
        0o600,
    )
    os.close(descriptor)
    try:
        source = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
        try:
            destination = sqlite3.connect(target)
            try:
                source.backup(destination)
            finally:
                destination.close()
        finally:
            source.close()
    except Exception:
        target.unlink(missing_ok=True)
        raise
    os.chmod(target, 0o600)
    return target


def _restore_database(backup_path: Path, db_path: Path) -> None:
    for suffix in ("-wal", "-shm"):
        db_path.with_name(db_path.name + suffix).unlink(missing_ok=True)
    source = sqlite3.connect(f"file:{backup_path}?mode=ro", uri=True)
    destination = sqlite3.connect(db_path)
    try:
        source.backup(destination)
    finally:
        source.close()
        destination.close()
    os.chmod(db_path, 0o600)


def _create_channel_tables(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS user_notification_channels")
    connection.execute(
        """
        CREATE TABLE user_notification_channels (
            user_id TEXT NOT NULL,
            workspace_id TEXT NOT NULL,
            channel TEXT NOT NULL
                CHECK(channel IN ('email', 'webhook', 'telegram')),
            position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
            enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
            enabled_at TEXT,
            generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
            destination_env_name TEXT,
            destination_secret_digest TEXT,
            last_test_status TEXT
                CHECK(last_test_status IS NULL OR last_test_status IN (
                    'sent', 'failed'
                )),
            last_test_generation INTEGER,
            last_test_attempted_at TEXT,
            last_tested_at TEXT,
            last_test_error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(user_id, channel),
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(workspace_id)
                REFERENCES workspaces(id) ON DELETE CASCADE,
            CHECK(
                (destination_env_name IS NULL)
                = (destination_secret_digest IS NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_user_notification_channels_workspace
        ON user_notification_channels(
            workspace_id, user_id, enabled, position
        )
        """
    )
    connection.execute(
        """
        INSERT INTO user_notification_channels (
            user_id, workspace_id, channel, position, enabled, enabled_at,
            generation, last_test_status, last_test_generation,
            last_test_attempted_at, last_tested_at, last_test_error_code,
            created_at, updated_at
        )
        SELECT
            settings.user_id,
            settings.workspace_id,
            candidate.channel,
            CASE
                WHEN candidate.channel = settings.channel THEN 0
                ELSE candidate.canonical_position + 1
            END,
            CASE
                WHEN candidate.channel = settings.channel THEN 1
                ELSE 0
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN COALESCE(
                    settings.notification_enabled_at,
                    settings.updated_at,
                    settings.created_at
                )
                ELSE NULL
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN MAX(1, settings.notification_generation)
                ELSE 0
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN settings.last_test_status
                ELSE NULL
            END,
            CASE
                WHEN candidate.channel != settings.channel
                  OR settings.last_test_status IS NULL
                THEN NULL
                ELSE MAX(1, settings.notification_generation)
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN settings.last_test_attempted_at
                ELSE NULL
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN settings.last_tested_at
                ELSE NULL
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN settings.last_test_error_code
                ELSE NULL
            END,
            settings.created_at,
            settings.updated_at
        FROM user_notification_settings AS settings
        CROSS JOIN (
            SELECT 'email' AS channel, 0 AS canonical_position
            UNION ALL SELECT 'webhook', 1
            UNION ALL SELECT 'telegram', 2
        ) AS candidate
        """
    )

    connection.execute("DROP TABLE IF EXISTS apify_actor_alert_channels")
    connection.execute(
        """
        CREATE TABLE apify_actor_alert_channels (
            workspace_id TEXT NOT NULL,
            channel TEXT NOT NULL
                CHECK(channel IN ('email', 'webhook', 'telegram')),
            position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
            enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
            enabled_at TEXT,
            generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
            destination_env_name TEXT,
            destination_secret_digest TEXT,
            last_test_status TEXT
                CHECK(last_test_status IS NULL OR last_test_status IN (
                    'sent', 'failed'
                )),
            last_test_generation INTEGER,
            last_test_attempted_at TEXT,
            last_tested_at TEXT,
            last_test_error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(workspace_id, channel),
            FOREIGN KEY(workspace_id)
                REFERENCES workspaces(id) ON DELETE CASCADE,
            CHECK(
                (destination_env_name IS NULL)
                = (destination_secret_digest IS NULL)
            )
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_apify_actor_alert_channels_enabled
        ON apify_actor_alert_channels(workspace_id, enabled, position)
        """
    )
    connection.execute(
        """
        INSERT INTO apify_actor_alert_channels (
            workspace_id, channel, position, enabled, enabled_at,
            generation, last_test_status, last_test_generation,
            last_test_attempted_at, last_tested_at, last_test_error_code,
            created_at, updated_at
        )
        SELECT
            settings.workspace_id,
            candidate.channel,
            CASE
                WHEN candidate.channel = settings.channel THEN 0
                ELSE candidate.canonical_position + 1
            END,
            CASE
                WHEN candidate.channel = settings.channel THEN 1
                ELSE 0
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN COALESCE(
                    settings.notification_enabled_at,
                    settings.updated_at,
                    settings.created_at
                )
                ELSE NULL
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN MAX(1, settings.generation)
                ELSE 1
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN settings.last_test_status
                ELSE NULL
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN settings.last_test_generation
                ELSE NULL
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN settings.last_test_attempted_at
                ELSE NULL
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN settings.last_tested_at
                ELSE NULL
            END,
            CASE
                WHEN candidate.channel = settings.channel
                THEN settings.last_test_error_code
                ELSE NULL
            END,
            settings.created_at,
            settings.updated_at
        FROM apify_actor_alert_settings AS settings
        CROSS JOIN (
            SELECT 'email' AS channel, 0 AS canonical_position
            UNION ALL SELECT 'webhook', 1
            UNION ALL SELECT 'telegram', 2
        ) AS candidate
        """
    )


def _rebuild_user_settings(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS user_notification_settings_v15")
    connection.execute(
        """
        CREATE TABLE user_notification_settings_v15 (
            user_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
            channel TEXT NOT NULL DEFAULT 'webhook'
                CHECK(channel IN ('email', 'webhook', 'telegram')),
            email_address TEXT,
            webhook_env_name TEXT,
            webhook_secret_digest TEXT,
            webhook_provider TEXT NOT NULL DEFAULT 'legacy_auto'
                CHECK(webhook_provider IN (
                    'legacy_auto', 'generic_event', 'generic_text',
                    'feishu_lark_v2', 'wecom', 'dingtalk', 'slack',
                    'discord'
                )),
            webhook_signing_env_name TEXT,
            webhook_signing_secret_digest TEXT,
            notification_enabled_at TEXT,
            notification_generation INTEGER NOT NULL DEFAULT 0,
            last_test_status TEXT
                CHECK(last_test_status IS NULL OR last_test_status IN (
                    'sent', 'failed'
                )),
            last_test_attempted_at TEXT,
            last_tested_at TEXT,
            last_test_error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(workspace_id)
                REFERENCES workspaces(id) ON DELETE CASCADE,
            CHECK(
                (webhook_signing_env_name IS NULL)
                = (webhook_signing_secret_digest IS NULL)
            )
        )
        """
    )
    connection.execute(
        """
        INSERT INTO user_notification_settings_v15 (
            user_id, workspace_id, enabled, channel, email_address,
            webhook_env_name, webhook_secret_digest, webhook_provider,
            webhook_signing_env_name, webhook_signing_secret_digest,
            notification_enabled_at, notification_generation,
            last_test_status, last_test_attempted_at, last_tested_at,
            last_test_error_code, created_at, updated_at
        )
        SELECT
            user_id, workspace_id, enabled, channel, email_address,
            webhook_env_name, webhook_secret_digest, webhook_provider,
            webhook_signing_env_name, webhook_signing_secret_digest,
            notification_enabled_at, notification_generation,
            last_test_status, last_test_attempted_at, last_tested_at,
            last_test_error_code, created_at, updated_at
        FROM user_notification_settings
        """
    )
    connection.execute("DROP TABLE user_notification_settings")
    connection.execute(
        """
        ALTER TABLE user_notification_settings_v15
        RENAME TO user_notification_settings
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_user_notification_settings_workspace
        ON user_notification_settings(workspace_id, user_id)
        """
    )


def _rebuild_apify_settings(connection: sqlite3.Connection) -> None:
    connection.execute("DROP TABLE IF EXISTS apify_actor_alert_settings_v15")
    connection.execute(
        """
        CREATE TABLE apify_actor_alert_settings_v15 (
            workspace_id TEXT PRIMARY KEY,
            enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
            channel TEXT NOT NULL DEFAULT 'webhook'
                CHECK(channel IN ('email', 'webhook', 'telegram')),
            events_json TEXT NOT NULL DEFAULT '[]',
            email_address TEXT,
            webhook_env_name TEXT,
            webhook_secret_digest TEXT,
            webhook_provider TEXT NOT NULL DEFAULT 'legacy_auto'
                CHECK(webhook_provider IN (
                    'legacy_auto', 'generic_event', 'generic_text',
                    'feishu_lark_v2', 'wecom', 'dingtalk', 'slack',
                    'discord'
                )),
            webhook_signing_env_name TEXT,
            webhook_signing_secret_digest TEXT,
            generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
            notification_enabled_at TEXT,
            last_test_status TEXT
                CHECK(last_test_status IS NULL OR last_test_status IN (
                    'sent', 'failed'
                )),
            last_test_generation INTEGER,
            last_test_attempted_at TEXT,
            last_tested_at TEXT,
            last_test_error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id)
                REFERENCES workspaces(id) ON DELETE CASCADE,
            CHECK(
                (webhook_signing_env_name IS NULL)
                = (webhook_signing_secret_digest IS NULL)
            )
        )
        """
    )
    connection.execute(
        """
        INSERT INTO apify_actor_alert_settings_v15 (
            workspace_id, enabled, channel, events_json, email_address,
            webhook_env_name, webhook_secret_digest, webhook_provider,
            webhook_signing_env_name, webhook_signing_secret_digest,
            generation, notification_enabled_at, last_test_status,
            last_test_generation, last_test_attempted_at, last_tested_at,
            last_test_error_code, created_at, updated_at
        )
        SELECT
            workspace_id, enabled, channel, events_json, email_address,
            webhook_env_name, webhook_secret_digest, webhook_provider,
            webhook_signing_env_name, webhook_signing_secret_digest,
            generation, notification_enabled_at, last_test_status,
            last_test_generation, last_test_attempted_at, last_tested_at,
            last_test_error_code, created_at, updated_at
        FROM apify_actor_alert_settings
        """
    )
    connection.execute("DROP TABLE apify_actor_alert_settings")
    connection.execute(
        """
        ALTER TABLE apify_actor_alert_settings_v15
        RENAME TO apify_actor_alert_settings
        """
    )


def _rebuild_preferred_deliveries(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        "DROP TABLE IF EXISTS preferred_source_notification_deliveries_v15"
    )
    connection.execute(
        """
        CREATE TABLE preferred_source_notification_deliveries_v15 (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            user_id TEXT NOT NULL,
            subscription_id TEXT NOT NULL,
            source_id TEXT NOT NULL,
            snapshot_id TEXT NOT NULL,
            job_id TEXT NOT NULL,
            article_id TEXT NOT NULL,
            channel TEXT NOT NULL
                CHECK(channel IN ('email', 'webhook', 'telegram')),
            payload_json TEXT NOT NULL DEFAULT '{}',
            status TEXT NOT NULL DEFAULT 'pending'
                CHECK(status IN (
                    'pending', 'sending', 'succeeded', 'failed'
                )),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
            account_notification_generation INTEGER NOT NULL DEFAULT 0,
            channel_notification_generation INTEGER NOT NULL DEFAULT 0,
            subscription_notification_generation INTEGER NOT NULL DEFAULT 0,
            error_code TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            sent_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(subscription_id, article_id, channel),
            FOREIGN KEY(workspace_id)
                REFERENCES workspaces(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(subscription_id)
                REFERENCES user_subscriptions(id) ON DELETE CASCADE,
            FOREIGN KEY(source_id)
                REFERENCES source_catalog(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        INSERT INTO preferred_source_notification_deliveries_v15 (
            id, workspace_id, user_id, subscription_id, source_id,
            snapshot_id, job_id, article_id, channel, payload_json,
            status, attempts, account_notification_generation,
            channel_notification_generation,
            subscription_notification_generation, error_code,
            created_at, started_at, sent_at, updated_at
        )
        SELECT
            delivery.id, delivery.workspace_id, delivery.user_id,
            delivery.subscription_id, delivery.source_id,
            delivery.snapshot_id, delivery.job_id, delivery.article_id,
            delivery.channel, delivery.payload_json, delivery.status,
            delivery.attempts,
            delivery.account_notification_generation,
            COALESCE(channel_state.generation, 1),
            delivery.subscription_notification_generation,
            delivery.error_code, delivery.created_at, delivery.started_at,
            delivery.sent_at, delivery.updated_at
        FROM preferred_source_notification_deliveries AS delivery
        LEFT JOIN user_notification_channels AS channel_state
          ON channel_state.user_id = delivery.user_id
         AND channel_state.channel = delivery.channel
        """
    )
    connection.execute("DROP TABLE preferred_source_notification_deliveries")
    connection.execute(
        """
        ALTER TABLE preferred_source_notification_deliveries_v15
        RENAME TO preferred_source_notification_deliveries
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_preferred_source_notifications_pending
        ON preferred_source_notification_deliveries(
            status, created_at, id
        )
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_preferred_source_notifications_job
        ON preferred_source_notification_deliveries(
            job_id, status, created_at
        )
        """
    )


def _rebuild_apify_deliveries(connection: sqlite3.Connection) -> None:
    connection.execute(
        "DROP TABLE IF EXISTS apify_actor_alert_deliveries_v15"
    )
    connection.execute(
        """
        CREATE TABLE apify_actor_alert_deliveries_v15 (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            incident_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            channel TEXT NOT NULL
                CHECK(channel IN ('email', 'webhook', 'telegram')),
            settings_generation INTEGER NOT NULL
                CHECK(settings_generation >= 1),
            channel_generation INTEGER NOT NULL DEFAULT 1
                CHECK(channel_generation >= 1),
            payload_json TEXT NOT NULL,
            status TEXT NOT NULL
                CHECK(status IN (
                    'pending', 'sending', 'succeeded', 'failed'
                )),
            attempts INTEGER NOT NULL DEFAULT 0
                CHECK(attempts BETWEEN 0 AND 3),
            retry_at TEXT,
            error_code TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            sent_at TEXT,
            updated_at TEXT NOT NULL,
            UNIQUE(incident_id, event_type, channel),
            FOREIGN KEY(workspace_id)
                REFERENCES workspaces(id) ON DELETE CASCADE,
            FOREIGN KEY(incident_id)
                REFERENCES apify_actor_alert_incidents(id) ON DELETE CASCADE
        )
        """
    )
    connection.execute(
        """
        INSERT INTO apify_actor_alert_deliveries_v15 (
            id, workspace_id, incident_id, event_type, channel,
            settings_generation, channel_generation, payload_json, status,
            attempts, retry_at, error_code, created_at, started_at, sent_at,
            updated_at
        )
        SELECT
            delivery.id, delivery.workspace_id, delivery.incident_id,
            delivery.event_type, delivery.channel,
            delivery.settings_generation,
            COALESCE(channel_state.generation, 1),
            delivery.payload_json, delivery.status, delivery.attempts,
            delivery.retry_at, delivery.error_code, delivery.created_at,
            delivery.started_at, delivery.sent_at, delivery.updated_at
        FROM apify_actor_alert_deliveries AS delivery
        LEFT JOIN apify_actor_alert_channels AS channel_state
          ON channel_state.workspace_id = delivery.workspace_id
         AND channel_state.channel = delivery.channel
        """
    )
    connection.execute("DROP TABLE apify_actor_alert_deliveries")
    connection.execute(
        """
        ALTER TABLE apify_actor_alert_deliveries_v15
        RENAME TO apify_actor_alert_deliveries
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_apify_actor_alert_delivery_due
        ON apify_actor_alert_deliveries(status, retry_at, created_at)
        """
    )


def _apply_schema(store: ServiceStore) -> dict[str, Any]:
    connection = store.connect()
    before_counts = _counts(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        _create_channel_tables(connection)
        _rebuild_user_settings(connection)
        _rebuild_apify_settings(connection)
        _rebuild_preferred_deliveries(connection)
        _rebuild_apify_deliveries(connection)
        store._ensure_webhook_provider_triggers()
        after_counts = _counts(connection)
        if after_counts != before_counts:
            raise RuntimeError(
                "notification channels v15 changed protected row counts"
            )
        store.mark_multichannel_notifications_v15_migrated(commit=False)
        validation = _validate_v15_schema(connection)
        if validation["counts"] != before_counts:
            raise RuntimeError(
                "notification channels v15 validation count mismatch"
            )
        connection.commit()
        return validation
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise


def migrate_notification_channels_v15(
    *,
    data_dir: Path | str,
    backup_dir: Path | str,
    apply: bool,
) -> dict[str, Any]:
    data_path = Path(data_dir)
    db_path = data_path / "service.db"
    inspection = _inspect(db_path)
    result: dict[str, Any] = {
        "applied": False,
        "database_exists": inspection["database_exists"],
        "v14_migrated": inspection["v14_migrated"],
        "migrated": inspection["migrated"],
        "schema_ready": inspection["schema_ready"],
        "backup_path": None,
    }
    if not apply:
        return result
    if inspection["migrated"]:
        if not inspection["schema_ready"]:
            raise RuntimeError(
                "notification channels v15 marker exists but schema is invalid"
            )
        result["reason"] = "already_migrated"
        return result
    if db_path.exists() and not inspection["v14_migrated"]:
        raise RuntimeError(
            "apply Webhook providers v14 before notification channels v15"
        )
    if db_path.exists() and _active_workers(db_path):
        raise RuntimeError(
            "stop all horizon-worker processes before applying "
            "notification channels v15"
        )

    data_path.mkdir(parents=True, exist_ok=True)
    backup_path = (
        _backup_database(db_path, Path(backup_dir))
        if db_path.exists()
        else None
    )
    created_database = not db_path.exists()
    store = ServiceStore(data_path)
    try:
        store.initialize(prepare_multichannel_notifications_v15=True)
        validation = _apply_schema(store)
        if store.multichannel_notifications_v15_migration_required():
            raise RuntimeError(
                "notification channels v15 schema verification failed"
            )
    except Exception:
        store.close()
        if backup_path is not None:
            _restore_database(backup_path, db_path)
        elif created_database:
            for suffix in ("", "-wal", "-shm"):
                db_path.with_name(db_path.name + suffix).unlink(
                    missing_ok=True
                )
        raise
    else:
        store.close()

    result.update(
        {
            "applied": True,
            "database_exists": True,
            "v14_migrated": True,
            "migrated": True,
            "schema_ready": True,
            "backup_path": str(backup_path) if backup_path else None,
            **validation,
        }
    )
    return result


def main() -> None:
    parser = argparse.ArgumentParser(
        description=(
            "Dry-run or apply the explicit notification channels v15 "
            "migration"
        )
    )
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--backup-dir", default="data/backups")
    mode = parser.add_mutually_exclusive_group()
    mode.add_argument("--dry-run", action="store_true")
    mode.add_argument("--apply", action="store_true")
    args = parser.parse_args()
    print(
        json.dumps(
            migrate_notification_channels_v15(
                data_dir=args.data_dir,
                backup_dir=args.backup_dir,
                apply=bool(args.apply),
            ),
            ensure_ascii=False,
            sort_keys=True,
        )
    )


if __name__ == "__main__":
    main()
