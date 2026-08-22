"""Shared ActorOps alert tables that remain online after v1 retirement.

The alert, delivery and notification-target binding records are independent of
the retired route, candidate and canary schemas.  They are deliberately kept
out of the historical v13/v15/v16 DDL blocks so a new single-track database
does not need to create a v1 ActorOps table merely to retain alert delivery.
"""

from __future__ import annotations

import sqlite3

from .actorops_shared_alert_target_schema import (
    ensure_actorops_shared_alert_target_schema,
)


def ensure_actorops_shared_alert_schema(connection: sqlite3.Connection) -> None:
    """Create the v2-compatible shared alert ledger idempotently."""

    connection.executescript(
        """
        CREATE TABLE IF NOT EXISTS apify_actor_alert_settings (
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
                CHECK(last_test_status IS NULL OR last_test_status IN ('sent', 'failed')),
            last_test_generation INTEGER,
            last_test_attempted_at TEXT,
            last_tested_at TEXT,
            last_test_error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
            CHECK(
                (webhook_signing_env_name IS NULL)
                = (webhook_signing_secret_digest IS NULL)
            )
        );

        CREATE TABLE IF NOT EXISTS apify_actor_alert_incidents (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            route_key TEXT NOT NULL,
            incident_key TEXT NOT NULL,
            event_type TEXT NOT NULL,
            severity TEXT NOT NULL
                CHECK(severity IN ('info', 'warning', 'critical')),
            status TEXT NOT NULL CHECK(status IN ('open', 'resolved')),
            payload_json TEXT NOT NULL DEFAULT '{}',
            opened_at TEXT NOT NULL,
            last_seen_at TEXT NOT NULL,
            resolved_at TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE
        );
        CREATE UNIQUE INDEX IF NOT EXISTS idx_apify_actor_alert_open_incident
            ON apify_actor_alert_incidents(workspace_id, route_key, incident_key)
            WHERE status = 'open';
        CREATE INDEX IF NOT EXISTS idx_apify_actor_alert_incidents_recent
            ON apify_actor_alert_incidents(workspace_id, opened_at DESC);

        CREATE TABLE IF NOT EXISTS apify_actor_alert_deliveries (
            id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            incident_id TEXT NOT NULL,
            event_type TEXT NOT NULL,
            channel TEXT NOT NULL
                CHECK(channel IN ('email', 'webhook', 'telegram')),
            settings_generation INTEGER NOT NULL CHECK(settings_generation >= 1),
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
                CHECK(status IN ('pending', 'sending', 'succeeded', 'failed')),
            attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts BETWEEN 0 AND 3),
            retry_at TEXT,
            error_code TEXT,
            created_at TEXT NOT NULL,
            started_at TEXT,
            sent_at TEXT,
            updated_at TEXT NOT NULL,
            FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
            FOREIGN KEY(incident_id)
                REFERENCES apify_actor_alert_incidents(id) ON DELETE CASCADE,
            FOREIGN KEY(target_id) REFERENCES notification_targets(id)
                ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_apify_actor_alert_delivery_due
            ON apify_actor_alert_deliveries(status, retry_at, created_at);

        CREATE TABLE IF NOT EXISTS apify_actor_alert_channels (
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
                CHECK(last_test_status IS NULL OR last_test_status IN ('sent', 'failed')),
            last_test_generation INTEGER,
            last_test_attempted_at TEXT,
            last_tested_at TEXT,
            last_test_error_code TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(workspace_id, channel),
            FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
            CHECK(
                (destination_env_name IS NULL)
                = (destination_secret_digest IS NULL)
            )
        );
        CREATE INDEX IF NOT EXISTS idx_apify_actor_alert_channels_enabled
            ON apify_actor_alert_channels(workspace_id, enabled, position);
        """
    )
    ensure_actorops_shared_alert_target_schema(connection)
