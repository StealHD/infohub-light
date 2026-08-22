"""Target-aware extension for the shared ActorOps alert ledger."""

from __future__ import annotations

import sqlite3


def ensure_actorops_shared_alert_target_schema(connection: sqlite3.Connection) -> None:
    """Install target indexes only after the notification v16 shape exists."""

    tables = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }
    delivery_columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(apify_actor_alert_deliveries)"
        )
    }
    required = {
        "target_id", "target_name_snapshot", "target_config_generation",
        "target_activation_generation", "binding_generation",
    }
    if "notification_targets" not in tables or not required <= delivery_columns:
        return
    connection.executescript(
        """
        CREATE UNIQUE INDEX IF NOT EXISTS idx_apify_actor_alert_delivery_legacy_unique
            ON apify_actor_alert_deliveries(incident_id, event_type, channel)
            WHERE target_id IS NULL;
        CREATE UNIQUE INDEX IF NOT EXISTS idx_apify_actor_alert_delivery_target_unique
            ON apify_actor_alert_deliveries(incident_id, event_type, target_id)
            WHERE target_id IS NOT NULL;
        CREATE TABLE IF NOT EXISTS apify_actor_alert_target_bindings (
            workspace_id TEXT NOT NULL,
            target_id TEXT NOT NULL,
            position INTEGER NOT NULL DEFAULT 0 CHECK(position >= 0),
            enabled INTEGER NOT NULL DEFAULT 0 CHECK(enabled IN (0, 1)),
            enabled_at TEXT,
            generation INTEGER NOT NULL DEFAULT 0 CHECK(generation >= 0),
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL,
            PRIMARY KEY(workspace_id, target_id),
            FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
            FOREIGN KEY(target_id) REFERENCES notification_targets(id) ON DELETE RESTRICT
        );
        CREATE INDEX IF NOT EXISTS idx_apify_actor_alert_target_bindings_enabled
            ON apify_actor_alert_target_bindings(workspace_id, enabled, position);
        """
    )


__all__ = ["ensure_actorops_shared_alert_target_schema"]
