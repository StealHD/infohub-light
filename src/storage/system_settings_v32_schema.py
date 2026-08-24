"""Global 32 workspace runtime settings schema."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

MIGRATION_VERSION = 32
MIGRATION_NAME = "workspace_system_settings"
MIGRATION_CHECKSUM = "workspace-system-settings-v1"
REQUIRED_TABLES = {"workspace_system_settings", "system_setting_change_proposals"}

_SCHEMA_SQL = """
CREATE TABLE workspace_system_settings (
    workspace_id TEXT PRIMARY KEY,
    overrides_json TEXT NOT NULL DEFAULT '{}',
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    updated_by_user_id TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(updated_by_user_id) REFERENCES users(id) ON DELETE SET NULL
);
CREATE TABLE system_setting_change_proposals (
    id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    actor_user_id TEXT NOT NULL,
    delegation_id TEXT,
    actor_channel TEXT NOT NULL CHECK(actor_channel IN ('web', 'mcp')),
    base_generation INTEGER NOT NULL CHECK(base_generation >= 1),
    changes_json TEXT NOT NULL,
    preview_json TEXT NOT NULL,
    confirmation_hash TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'applied', 'expired')),
    created_at TEXT NOT NULL,
    expires_at TEXT NOT NULL,
    applied_at TEXT,
    result_summary_json TEXT,
    updated_at TEXT NOT NULL,
    FOREIGN KEY(workspace_id) REFERENCES workspaces(id) ON DELETE CASCADE,
    FOREIGN KEY(actor_user_id) REFERENCES users(id) ON DELETE CASCADE,
    FOREIGN KEY(delegation_id) REFERENCES agent_delegations(id) ON DELETE SET NULL
);
CREATE INDEX idx_system_setting_proposals_actor_status
    ON system_setting_change_proposals(
        workspace_id, actor_user_id, actor_channel, status, expires_at
    );
CREATE INDEX idx_system_setting_proposals_status_updated
    ON system_setting_change_proposals(status, updated_at);
CREATE TRIGGER trg_workspace_system_settings_seed
AFTER INSERT ON workspaces
BEGIN
    INSERT INTO workspace_system_settings (
        workspace_id, overrides_json, generation, created_at, updated_at
    ) VALUES (NEW.id, '{}', 1, NEW.created_at, NEW.updated_at);
END;
"""


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def prerequisite_ready(connection: sqlite3.Connection) -> bool:
    from .actorops_v2_resilience_schema import (
        migration_marker_exists as v31_marker,
        schema_shapes_valid as v31_shapes,
    )

    return v31_marker(connection) and v31_shapes(connection)


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection: sqlite3.Connection) -> bool:
    if not REQUIRED_TABLES <= _table_names(connection):
        return False
    settings_columns = {
        str(row[1]) for row in connection.execute(
            "PRAGMA table_info(workspace_system_settings)"
        )
    }
    proposal_columns = {
        str(row[1]) for row in connection.execute(
            "PRAGMA table_info(system_setting_change_proposals)"
        )
    }
    return (
        prerequisite_ready(connection)
        and {"workspace_id", "overrides_json", "generation", "updated_by_user_id"}
        <= settings_columns
        and {"workspace_id", "actor_user_id", "actor_channel", "base_generation",
             "changes_json", "preview_json", "confirmation_hash", "status"}
        <= proposal_columns
    )


def migration_required(connection: sqlite3.Connection) -> bool:
    return not (migration_marker_exists(connection) and schema_shapes_valid(connection))


def _assert_available_version(connection: sqlite3.Connection) -> None:
    row = connection.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,),
    ).fetchone()
    if row is not None and (
        str(row[0]) != MIGRATION_NAME or str(row[1]) != MIGRATION_CHECKSUM
    ):
        raise RuntimeError("global schema migration version 32 is already occupied")


def apply_migration(connection: sqlite3.Connection) -> dict[str, int]:
    if connection.in_transaction:
        raise RuntimeError("system settings migration requires a committed connection")
    _assert_available_version(connection)
    if migration_marker_exists(connection):
        if not schema_shapes_valid(connection):
            raise RuntimeError("system settings marker exists with an invalid schema")
        return {"workspace_rows_seeded": 0}
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global schema 31 is required before system settings migration")
    if REQUIRED_TABLES & _table_names(connection):
        raise RuntimeError("partial system settings schema must be restored")
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute("BEGIN IMMEDIATE")
        statement = ""
        for line in _SCHEMA_SQL.splitlines():
            statement = f"{statement}\n{line}".strip()
            if statement and sqlite3.complete_statement(statement):
                connection.execute(statement)
                statement = ""
        if statement:
            raise RuntimeError("incomplete system settings schema statement")
        cursor = connection.execute(
            """INSERT INTO workspace_system_settings (
                   workspace_id, overrides_json, generation, created_at, updated_at
               ) SELECT id, '{}', 1, ?, ? FROM workspaces""",
            (stamp, stamp),
        )
        connection.execute(
            """INSERT INTO schema_migrations (version, name, checksum, applied_at)
               VALUES (?, ?, ?, ?)""",
            (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM, stamp),
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return {"workspace_rows_seeded": int(cursor.rowcount)}


def bootstrap_service_store_schema(
    connection: sqlite3.Connection, *, existing_schema: bool
) -> None:
    if not existing_schema:
        apply_migration(connection)


__all__ = [
    "MIGRATION_CHECKSUM", "MIGRATION_NAME", "MIGRATION_VERSION", "REQUIRED_TABLES",
    "apply_migration", "bootstrap_service_store_schema", "migration_marker_exists",
    "migration_required", "prerequisite_ready", "schema_shapes_valid",
]
