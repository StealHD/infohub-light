#!/usr/bin/env python3
"""Install reusable notification targets with a verified private backup."""

from __future__ import annotations

import argparse
import hashlib
import json
import os
import sqlite3
import sys
import unicodedata
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

REPOSITORY_ROOT = Path(__file__).resolve().parents[1]
if str(REPOSITORY_ROOT) not in sys.path:
    sys.path.insert(0, str(REPOSITORY_ROOT))

from scripts.migrate_notification_channels_v15 import _validate_v15_schema
from scripts.migrate_user_feed_v2 import _active_workers
from src.storage.service_store import ServiceStore


COUNTED_TABLES = (
    "user_notification_settings",
    "preferred_source_notification_deliveries",
    "apify_actor_alert_settings",
    "apify_actor_alert_incidents",
    "apify_actor_alert_deliveries",
)
TARGET_TABLES = {
    "notification_targets",
    "user_notification_target_bindings",
    "apify_actor_alert_target_bindings",
}
CHANNEL_LABELS = {
    "email": "邮箱",
    "webhook": "Webhook",
    "telegram": "Telegram",
}


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


def _counts(connection: sqlite3.Connection) -> dict[str, int]:
    return {
        table: int(
            connection.execute(
                f"SELECT COUNT(*) FROM {table}"
            ).fetchone()[0]
        )
        for table in COUNTED_TABLES
    }


def _inspect(db_path: Path) -> dict[str, Any]:
    if not db_path.exists():
        return {
            "database_exists": False,
            "v15_migrated": False,
            "migrated": False,
            "schema_ready": False,
        }
    connection = sqlite3.connect(f"file:{db_path}?mode=ro", uri=True)
    try:
        versions = (
            {
                int(row[0])
                for row in connection.execute(
                    "SELECT version FROM schema_migrations"
                ).fetchall()
            }
            if _table_exists(connection, "schema_migrations")
            else set()
        )
        ready = False
        if 16 in versions:
            connection.row_factory = sqlite3.Row
            store = ServiceStore(db_path.parent)
            store._connection = connection
            try:
                ready = not store.notification_targets_v16_migration_required()
            finally:
                store._connection = None
        return {
            "database_exists": True,
            "v15_migrated": 15 in versions,
            "migrated": 16 in versions,
            "schema_ready": ready,
        }
    finally:
        connection.close()


def _backup_database(db_path: Path, backup_dir: Path) -> Path:
    backup_dir.mkdir(mode=0o700, parents=True, exist_ok=True)
    os.chmod(backup_dir, 0o700)
    stamp = datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%S%fZ")
    target = backup_dir / f"service-notification-targets-v16-{stamp}.db"
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


def _target_id(
    kind: str,
    workspace_id: str,
    owner_user_id: str | None,
    channel: str,
) -> str:
    identity = "\x1f".join(
        (kind, workspace_id, owner_user_id or "", channel)
    )
    return "ntg_" + hashlib.sha256(identity.encode("utf-8")).hexdigest()[:32]


def _name_key(name: str) -> str:
    return unicodedata.normalize("NFKC", name).casefold()


def _insert_target(
    connection: sqlite3.Connection,
    *,
    target_id: str,
    workspace_id: str,
    scope: str,
    owner_user_id: str | None,
    name: str,
    channel: str,
    enabled: bool,
    enabled_at: str | None,
    config_generation: int,
    activation_generation: int,
    destination_env_name: str | None,
    destination_secret_digest: str | None,
    secret_binding_kind: str,
    webhook_provider: str | None,
    webhook_signing_env_name: str | None,
    webhook_signing_secret_digest: str | None,
    last_test_status: str | None,
    last_test_config_generation: int | None,
    last_test_attempted_at: str | None,
    last_tested_at: str | None,
    last_test_error_code: str | None,
    archived_at: str | None,
    created_at: str,
    updated_at: str,
) -> None:
    connection.execute(
        """
        INSERT INTO notification_targets (
            id, workspace_id, scope, owner_user_id, name, name_key,
            channel, enabled, enabled_at, config_generation,
            activation_generation, destination_env_name,
            destination_secret_digest, secret_binding_kind,
            webhook_provider, webhook_signing_env_name,
            webhook_signing_secret_digest, last_test_status,
            last_test_config_generation, last_test_attempted_at,
            last_tested_at, last_test_error_code, archived_at,
            created_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
            ?, ?, ?, ?, ?
        )
        """,
        (
            target_id,
            workspace_id,
            scope,
            owner_user_id,
            name,
            _name_key(name),
            channel,
            1 if enabled else 0,
            enabled_at if enabled else None,
            max(1, int(config_generation)),
            max(0, int(activation_generation)),
            destination_env_name,
            destination_secret_digest,
            secret_binding_kind,
            webhook_provider if channel == "webhook" else None,
            webhook_signing_env_name if channel == "webhook" else None,
            (
                webhook_signing_secret_digest
                if channel == "webhook"
                else None
            ),
            last_test_status,
            last_test_config_generation,
            last_test_attempted_at,
            last_tested_at,
            last_test_error_code,
            archived_at,
            created_at,
            updated_at,
        ),
    )


def _migrate_current_targets(connection: sqlite3.Connection) -> None:
    private_rows = connection.execute(
        """
        SELECT
            channel_state.*,
            (settings.email_address IS NOT NULL) AS email_configured,
            settings.webhook_env_name, settings.webhook_secret_digest,
            settings.webhook_provider,
            settings.webhook_signing_env_name,
            settings.webhook_signing_secret_digest
        FROM user_notification_channels AS channel_state
        JOIN user_notification_settings AS settings
          ON settings.user_id = channel_state.user_id
         AND settings.workspace_id = channel_state.workspace_id
        WHERE channel_state.enabled = 1
           OR channel_state.destination_env_name IS NOT NULL
           OR channel_state.last_test_status IS NOT NULL
           OR (
                channel_state.channel = 'email'
                AND settings.email_address IS NOT NULL
           )
           OR (
                channel_state.channel = 'webhook'
                AND settings.webhook_env_name IS NOT NULL
           )
           OR EXISTS (
                SELECT 1
                FROM preferred_source_notification_deliveries AS delivery
                WHERE delivery.workspace_id = channel_state.workspace_id
                  AND delivery.user_id = channel_state.user_id
                  AND delivery.channel = channel_state.channel
           )
        ORDER BY channel_state.workspace_id, channel_state.user_id,
                 channel_state.position, channel_state.channel
        """
    ).fetchall()
    for row in private_rows:
        channel = str(row["channel"])
        generation = max(1, int(row["generation"] or 0))
        target_id = _target_id(
            "legacy_user_v15",
            str(row["workspace_id"]),
            str(row["user_id"]),
            channel,
        )
        destination_env = row["destination_env_name"]
        destination_digest = row["destination_secret_digest"]
        if channel == "webhook" and not destination_env:
            destination_env = row["webhook_env_name"]
            destination_digest = row["webhook_secret_digest"]
        _insert_target(
            connection,
            target_id=target_id,
            workspace_id=str(row["workspace_id"]),
            scope="private",
            owner_user_id=str(row["user_id"]),
            name=f"迁移的{CHANNEL_LABELS[channel]}目标",
            channel=channel,
            enabled=bool(row["enabled"]),
            enabled_at=row["enabled_at"],
            config_generation=generation,
            activation_generation=generation,
            destination_env_name=destination_env,
            destination_secret_digest=destination_digest,
            secret_binding_kind="legacy_user_v15",
            webhook_provider=row["webhook_provider"],
            webhook_signing_env_name=row["webhook_signing_env_name"],
            webhook_signing_secret_digest=row[
                "webhook_signing_secret_digest"
            ],
            last_test_status=row["last_test_status"],
            last_test_config_generation=(
                generation if row["last_test_status"] else None
            ),
            last_test_attempted_at=row["last_test_attempted_at"],
            last_tested_at=row["last_tested_at"],
            last_test_error_code=row["last_test_error_code"],
            archived_at=None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
        connection.execute(
            """
            INSERT INTO user_notification_target_bindings (
                user_id, workspace_id, target_id, position, enabled,
                enabled_at, generation, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["user_id"],
                row["workspace_id"],
                target_id,
                row["position"],
                row["enabled"],
                row["enabled_at"] if row["enabled"] else None,
                generation,
                row["created_at"],
                row["updated_at"],
            ),
        )

    shared_rows = connection.execute(
        """
        SELECT
            channel_state.*,
            (settings.email_address IS NOT NULL) AS email_configured,
            settings.webhook_env_name, settings.webhook_secret_digest,
            settings.webhook_provider,
            settings.webhook_signing_env_name,
            settings.webhook_signing_secret_digest
        FROM apify_actor_alert_channels AS channel_state
        JOIN apify_actor_alert_settings AS settings
          ON settings.workspace_id = channel_state.workspace_id
        WHERE channel_state.enabled = 1
           OR channel_state.destination_env_name IS NOT NULL
           OR channel_state.last_test_status IS NOT NULL
           OR (
                channel_state.channel = 'email'
                AND settings.email_address IS NOT NULL
           )
           OR (
                channel_state.channel = 'webhook'
                AND settings.webhook_env_name IS NOT NULL
           )
           OR EXISTS (
                SELECT 1
                FROM apify_actor_alert_deliveries AS delivery
                WHERE delivery.workspace_id = channel_state.workspace_id
                  AND delivery.channel = channel_state.channel
           )
        ORDER BY channel_state.workspace_id, channel_state.position,
                 channel_state.channel
        """
    ).fetchall()
    for row in shared_rows:
        channel = str(row["channel"])
        generation = max(1, int(row["generation"] or 1))
        target_id = _target_id(
            "legacy_apify_v15",
            str(row["workspace_id"]),
            None,
            channel,
        )
        destination_env = row["destination_env_name"]
        destination_digest = row["destination_secret_digest"]
        if channel == "webhook" and not destination_env:
            destination_env = row["webhook_env_name"]
            destination_digest = row["webhook_secret_digest"]
        _insert_target(
            connection,
            target_id=target_id,
            workspace_id=str(row["workspace_id"]),
            scope="shared",
            owner_user_id=None,
            name=f"迁移的 Apify {CHANNEL_LABELS[channel]}目标",
            channel=channel,
            enabled=bool(row["enabled"]),
            enabled_at=row["enabled_at"],
            config_generation=generation,
            activation_generation=generation,
            destination_env_name=destination_env,
            destination_secret_digest=destination_digest,
            secret_binding_kind="legacy_apify_v15",
            webhook_provider=row["webhook_provider"],
            webhook_signing_env_name=row["webhook_signing_env_name"],
            webhook_signing_secret_digest=row[
                "webhook_signing_secret_digest"
            ],
            last_test_status=row["last_test_status"],
            last_test_config_generation=(
                int(row["last_test_generation"] or generation)
                if row["last_test_status"]
                else None
            ),
            last_test_attempted_at=row["last_test_attempted_at"],
            last_tested_at=row["last_tested_at"],
            last_test_error_code=row["last_test_error_code"],
            archived_at=None,
            created_at=str(row["created_at"]),
            updated_at=str(row["updated_at"]),
        )
        connection.execute(
            """
            INSERT INTO apify_actor_alert_target_bindings (
                workspace_id, target_id, position, enabled, enabled_at,
                generation, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                row["workspace_id"],
                target_id,
                row["position"],
                row["enabled"],
                row["enabled_at"] if row["enabled"] else None,
                generation,
                row["created_at"],
                row["updated_at"],
            ),
        )


def _create_historical_placeholders(
    connection: sqlite3.Connection,
) -> None:
    rows = connection.execute(
        """
        SELECT DISTINCT
            delivery.workspace_id, delivery.user_id, delivery.channel,
            delivery.created_at
        FROM preferred_source_notification_deliveries AS delivery
        LEFT JOIN notification_targets AS target
          ON target.workspace_id = delivery.workspace_id
         AND target.owner_user_id = delivery.user_id
         AND target.channel = delivery.channel
         AND target.secret_binding_kind = 'legacy_user_v15'
        WHERE target.id IS NULL
        """
    ).fetchall()
    for row in rows:
        target_id = _target_id(
            "historical_user_v16",
            str(row["workspace_id"]),
            str(row["user_id"]),
            str(row["channel"]),
        )
        name = f"历史{CHANNEL_LABELS[str(row['channel'])]}目标"
        _insert_target(
            connection,
            target_id=target_id,
            workspace_id=str(row["workspace_id"]),
            scope="private",
            owner_user_id=str(row["user_id"]),
            name=name,
            channel=str(row["channel"]),
            enabled=False,
            enabled_at=None,
            config_generation=1,
            activation_generation=0,
            destination_env_name=None,
            destination_secret_digest=None,
            secret_binding_kind="historical_placeholder",
            webhook_provider=(
                "legacy_auto" if row["channel"] == "webhook" else None
            ),
            webhook_signing_env_name=None,
            webhook_signing_secret_digest=None,
            last_test_status=None,
            last_test_config_generation=None,
            last_test_attempted_at=None,
            last_tested_at=None,
            last_test_error_code=None,
            archived_at=str(row["created_at"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["created_at"]),
        )

    rows = connection.execute(
        """
        SELECT DISTINCT
            delivery.workspace_id, delivery.channel, delivery.created_at
        FROM apify_actor_alert_deliveries AS delivery
        LEFT JOIN notification_targets AS target
          ON target.workspace_id = delivery.workspace_id
         AND target.scope = 'shared'
         AND target.channel = delivery.channel
         AND target.secret_binding_kind = 'legacy_apify_v15'
        WHERE target.id IS NULL
        """
    ).fetchall()
    for row in rows:
        target_id = _target_id(
            "historical_apify_v16",
            str(row["workspace_id"]),
            None,
            str(row["channel"]),
        )
        _insert_target(
            connection,
            target_id=target_id,
            workspace_id=str(row["workspace_id"]),
            scope="shared",
            owner_user_id=None,
            name=f"历史 Apify {CHANNEL_LABELS[str(row['channel'])]}目标",
            channel=str(row["channel"]),
            enabled=False,
            enabled_at=None,
            config_generation=1,
            activation_generation=0,
            destination_env_name=None,
            destination_secret_digest=None,
            secret_binding_kind="historical_placeholder",
            webhook_provider=(
                "legacy_auto" if row["channel"] == "webhook" else None
            ),
            webhook_signing_env_name=None,
            webhook_signing_secret_digest=None,
            last_test_status=None,
            last_test_config_generation=None,
            last_test_attempted_at=None,
            last_tested_at=None,
            last_test_error_code=None,
            archived_at=str(row["created_at"]),
            created_at=str(row["created_at"]),
            updated_at=str(row["created_at"]),
        )


def _map_delivery_targets(connection: sqlite3.Connection) -> None:
    connection.execute(
        """
        UPDATE preferred_source_notification_deliveries AS delivery
        SET
            target_id = (
                SELECT target.id FROM notification_targets AS target
                WHERE target.workspace_id = delivery.workspace_id
                  AND target.owner_user_id = delivery.user_id
                  AND target.channel = delivery.channel
                ORDER BY
                    CASE target.secret_binding_kind
                        WHEN 'legacy_user_v15' THEN 0 ELSE 1
                    END
                LIMIT 1
            ),
            target_name_snapshot = (
                SELECT target.name FROM notification_targets AS target
                WHERE target.workspace_id = delivery.workspace_id
                  AND target.owner_user_id = delivery.user_id
                  AND target.channel = delivery.channel
                ORDER BY
                    CASE target.secret_binding_kind
                        WHEN 'legacy_user_v15' THEN 0 ELSE 1
                    END
                LIMIT 1
            ),
            target_config_generation = MAX(
                1, COALESCE(channel_notification_generation, 1)
            ),
            target_activation_generation = MAX(
                0, COALESCE(channel_notification_generation, 0)
            ),
            binding_generation = MAX(
                1, COALESCE(channel_notification_generation, 1)
            )
        """
    )
    connection.execute(
        """
        UPDATE apify_actor_alert_deliveries AS delivery
        SET
            target_id = (
                SELECT target.id FROM notification_targets AS target
                WHERE target.workspace_id = delivery.workspace_id
                  AND target.scope = 'shared'
                  AND target.channel = delivery.channel
                ORDER BY
                    CASE target.secret_binding_kind
                        WHEN 'legacy_apify_v15' THEN 0 ELSE 1
                    END
                LIMIT 1
            ),
            target_name_snapshot = (
                SELECT target.name FROM notification_targets AS target
                WHERE target.workspace_id = delivery.workspace_id
                  AND target.scope = 'shared'
                  AND target.channel = delivery.channel
                ORDER BY
                    CASE target.secret_binding_kind
                        WHEN 'legacy_apify_v15' THEN 0 ELSE 1
                    END
                LIMIT 1
            ),
            target_config_generation = MAX(
                1, COALESCE(channel_generation, 1)
            ),
            target_activation_generation = MAX(
                0, COALESCE(channel_generation, 0)
            ),
            binding_generation = MAX(
                1, COALESCE(channel_generation, 1)
            )
        """
    )


def _rebuild_preferred_deliveries(
    connection: sqlite3.Connection,
) -> None:
    connection.execute(
        "DROP TABLE IF EXISTS preferred_source_notification_deliveries_v16"
    )
    connection.execute(
        """
        CREATE TABLE preferred_source_notification_deliveries_v16 (
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
            target_id TEXT,
            target_name_snapshot TEXT NOT NULL DEFAULT '',
            target_config_generation INTEGER NOT NULL DEFAULT 0
                CHECK(target_config_generation >= 0),
            target_activation_generation INTEGER NOT NULL DEFAULT 0
                CHECK(target_activation_generation >= 0),
            binding_generation INTEGER NOT NULL DEFAULT 0
                CHECK(binding_generation >= 0),
            error_code TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            sent_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id)
                REFERENCES workspaces(id) ON DELETE CASCADE,
            FOREIGN KEY(user_id) REFERENCES users(id) ON DELETE CASCADE,
            FOREIGN KEY(subscription_id)
                REFERENCES user_subscriptions(id) ON DELETE CASCADE,
            FOREIGN KEY(source_id)
                REFERENCES source_catalog(id) ON DELETE CASCADE,
            FOREIGN KEY(target_id)
                REFERENCES notification_targets(id) ON DELETE RESTRICT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO preferred_source_notification_deliveries_v16 (
            id, workspace_id, user_id, subscription_id, source_id,
            snapshot_id, job_id, article_id, channel, payload_json,
            status, attempts, account_notification_generation,
            channel_notification_generation,
            subscription_notification_generation, target_id,
            target_name_snapshot, target_config_generation,
            target_activation_generation, binding_generation, error_code,
            created_at, started_at, sent_at, updated_at
        )
        SELECT
            id, workspace_id, user_id, subscription_id, source_id,
            snapshot_id, job_id, article_id, channel, payload_json,
            status, attempts, account_notification_generation,
            COALESCE(channel_notification_generation, 0),
            subscription_notification_generation, target_id,
            COALESCE(target_name_snapshot, ''),
            COALESCE(target_config_generation, 0),
            COALESCE(target_activation_generation, 0),
            COALESCE(binding_generation, 0), error_code,
            created_at, started_at, sent_at, updated_at
        FROM preferred_source_notification_deliveries
        """
    )
    connection.execute(
        "DROP TABLE preferred_source_notification_deliveries"
    )
    connection.execute(
        """
        ALTER TABLE preferred_source_notification_deliveries_v16
        RENAME TO preferred_source_notification_deliveries
        """
    )
    connection.executescript(
        """
        CREATE INDEX idx_preferred_source_notifications_pending
        ON preferred_source_notification_deliveries(status, created_at, id);
        CREATE INDEX idx_preferred_source_notifications_job
        ON preferred_source_notification_deliveries(
            job_id, status, created_at
        );
        CREATE UNIQUE INDEX
            idx_preferred_source_notification_legacy_unique
        ON preferred_source_notification_deliveries(
            subscription_id, article_id, channel
        ) WHERE target_id IS NULL;
        CREATE UNIQUE INDEX
            idx_preferred_source_notification_target_unique
        ON preferred_source_notification_deliveries(
            subscription_id, article_id, target_id
        ) WHERE target_id IS NOT NULL;
        """
    )


def _rebuild_apify_deliveries(connection: sqlite3.Connection) -> None:
    connection.execute(
        "DROP TABLE IF EXISTS apify_actor_alert_deliveries_v16"
    )
    connection.execute(
        """
        CREATE TABLE apify_actor_alert_deliveries_v16 (
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
            target_id TEXT,
            target_name_snapshot TEXT NOT NULL DEFAULT '',
            target_config_generation INTEGER NOT NULL DEFAULT 0
                CHECK(target_config_generation >= 0),
            target_activation_generation INTEGER NOT NULL DEFAULT 0
                CHECK(target_activation_generation >= 0),
            binding_generation INTEGER NOT NULL DEFAULT 0
                CHECK(binding_generation >= 0),
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
            FOREIGN KEY(workspace_id)
                REFERENCES workspaces(id) ON DELETE CASCADE,
            FOREIGN KEY(incident_id)
                REFERENCES apify_actor_alert_incidents(id) ON DELETE CASCADE,
            FOREIGN KEY(target_id)
                REFERENCES notification_targets(id) ON DELETE RESTRICT
        )
        """
    )
    connection.execute(
        """
        INSERT INTO apify_actor_alert_deliveries_v16 (
            id, workspace_id, incident_id, event_type, channel,
            settings_generation, channel_generation, target_id,
            target_name_snapshot, target_config_generation,
            target_activation_generation, binding_generation,
            payload_json, status, attempts, retry_at, error_code,
            created_at, started_at, sent_at, updated_at
        )
        SELECT
            id, workspace_id, incident_id, event_type, channel,
            settings_generation, COALESCE(channel_generation, 1),
            target_id, COALESCE(target_name_snapshot, ''),
            COALESCE(target_config_generation, 0),
            COALESCE(target_activation_generation, 0),
            COALESCE(binding_generation, 0),
            payload_json, status, attempts, retry_at, error_code,
            created_at, started_at, sent_at, updated_at
        FROM apify_actor_alert_deliveries
        """
    )
    connection.execute("DROP TABLE apify_actor_alert_deliveries")
    connection.execute(
        """
        ALTER TABLE apify_actor_alert_deliveries_v16
        RENAME TO apify_actor_alert_deliveries
        """
    )
    connection.executescript(
        """
        CREATE INDEX idx_apify_actor_alert_delivery_due
        ON apify_actor_alert_deliveries(status, retry_at, created_at);
        CREATE UNIQUE INDEX
            idx_apify_actor_alert_delivery_legacy_unique
        ON apify_actor_alert_deliveries(
            incident_id, event_type, channel
        ) WHERE target_id IS NULL;
        CREATE UNIQUE INDEX
            idx_apify_actor_alert_delivery_target_unique
        ON apify_actor_alert_deliveries(
            incident_id, event_type, target_id
        ) WHERE target_id IS NOT NULL;
        """
    )


def _validate_v16_schema(
    store: ServiceStore,
    expected_counts: dict[str, int],
) -> dict[str, Any]:
    connection = store.connect()
    installed = {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    if not TARGET_TABLES <= installed:
        raise RuntimeError("notification targets v16 tables are incomplete")
    if store.notification_targets_v16_migration_required():
        raise RuntimeError("notification targets v16 constraints are incomplete")
    actual_counts = _counts(connection)
    if actual_counts != expected_counts:
        raise RuntimeError(
            "notification targets v16 changed protected row counts"
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
        "counts": actual_counts,
        "target_count": int(
            connection.execute(
                "SELECT COUNT(*) FROM notification_targets"
            ).fetchone()[0]
        ),
        "integrity_check": integrity_check,
        "foreign_key_errors": len(foreign_key_errors),
    }


def _apply_schema(store: ServiceStore) -> dict[str, Any]:
    connection = store.connect()
    before_counts = _counts(connection)
    connection.execute("BEGIN IMMEDIATE")
    try:
        connection.execute("DELETE FROM user_notification_target_bindings")
        connection.execute("DELETE FROM apify_actor_alert_target_bindings")
        connection.execute("DELETE FROM notification_targets")
        _migrate_current_targets(connection)
        _create_historical_placeholders(connection)
        _map_delivery_targets(connection)
        if connection.execute(
            """
            SELECT 1 FROM preferred_source_notification_deliveries
            WHERE target_id IS NULL
            UNION ALL
            SELECT 1 FROM apify_actor_alert_deliveries
            WHERE target_id IS NULL
            LIMIT 1
            """
        ).fetchone():
            raise RuntimeError(
                "notification targets v16 could not map delivery history"
            )
        _rebuild_preferred_deliveries(connection)
        _rebuild_apify_deliveries(connection)
        store.mark_notification_targets_v16_migrated(commit=False)
        validation = _validate_v16_schema(store, before_counts)
        connection.commit()
        return validation
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise


def migrate_notification_targets_v16(
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
        "v15_migrated": inspection["v15_migrated"],
        "migrated": inspection["migrated"],
        "schema_ready": inspection["schema_ready"],
        "backup_path": None,
    }
    if not apply:
        return result
    if inspection["migrated"]:
        if not inspection["schema_ready"]:
            raise RuntimeError(
                "notification targets v16 marker exists but schema is invalid"
            )
        result["reason"] = "already_migrated"
        return result
    if db_path.exists() and not inspection["v15_migrated"]:
        raise RuntimeError(
            "apply notification channels v15 before notification targets v16"
        )
    if db_path.exists() and _active_workers(db_path):
        raise RuntimeError(
            "stop all horizon-worker processes before applying "
            "notification targets v16"
        )
    if db_path.exists():
        validation_connection = sqlite3.connect(db_path)
        try:
            _validate_v15_schema(validation_connection)
        finally:
            validation_connection.close()

    data_path.mkdir(parents=True, exist_ok=True)
    backup_path = (
        _backup_database(db_path, Path(backup_dir))
        if db_path.exists()
        else None
    )
    created_database = not db_path.exists()
    store = ServiceStore(data_path)
    try:
        store.initialize(prepare_notification_targets_v16=True)
        if created_database:
            validation = _validate_v16_schema(store, _counts(store.connect()))
        else:
            validation = _apply_schema(store)
        if store.notification_targets_v16_migration_required():
            raise RuntimeError(
                "notification targets v16 schema verification failed"
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
            "v15_migrated": True,
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
            "Dry-run or apply the explicit reusable notification targets "
            "v16 migration"
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
            migrate_notification_targets_v16(
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
