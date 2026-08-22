"""Global 30 ActorOps v2 single-track schema and fresh-store catalog seed."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone
from typing import Any

from ..services.actorops.adapters import build_default_registry
from ..services.actorops.route_catalog import (
    catalog_entries,
    catalog_route_id,
    maintenance_policy_id,
)
from .actorops_v2_attempt_recovery_schema import (
    migration_marker_exists as v29_marker,
)
from .actorops_v2_attempt_recovery_schema import schema_shapes_valid as v29_shapes
from .actorops_v2_operator_schema import (
    migration_marker_exists as v28_marker,
)
from .actorops_v2_operator_schema import schema_shapes_valid as v28_shapes
from .actorops_v2_schema_sql import V2_TABLES
from .actorops_v2_single_track_schema_sql import (
    BINDING_COLUMNS,
    BINDING_TABLE_SQL,
    RETIRED_COLUMNS,
    REQUIRED_TRIGGERS,
    ROUTE_COLUMNS,
    ROUTE_TABLE_SQL,
    TRIGGER_SQL,
)


MIGRATION_VERSION = 30
MIGRATION_NAME = "actorops_v2_single_track"
MIGRATION_CHECKSUM = "actorops-v2-single-track-v1"


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='table'"
        )
    }


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})")
    }


def _normalized_table_sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name=?", (table,)
    ).fetchone()
    return re.sub(r"\s+", "", str(row[0] if row else "")).casefold()


def prerequisite_ready(connection: sqlite3.Connection) -> bool:
    return v29_marker(connection) and v29_shapes(connection)


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection: sqlite3.Connection) -> bool:
    if not set(V2_TABLES) <= _table_names(connection):
        return False
    route_columns = _columns(connection, "actor_routes_v2")
    binding_columns = _columns(connection, "actor_source_bindings_v2")
    triggers = {
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
    }
    return (
        v28_marker(connection)
        and v28_shapes(connection)
        and v29_marker(connection)
        and v29_shapes(connection)
        and ROUTE_COLUMNS <= route_columns
        and BINDING_COLUMNS <= binding_columns
        and not (RETIRED_COLUMNS & route_columns)
        and not (RETIRED_COLUMNS & binding_columns)
        and REQUIRED_TRIGGERS <= triggers
        and "check(runtime_modein('active','disabled'))"
        in _normalized_table_sql(connection, "actor_routes_v2")
    )


def migration_required(connection: sqlite3.Connection) -> bool:
    return not (migration_marker_exists(connection) and schema_shapes_valid(connection))


def _require_rebuildable_schema(connection: sqlite3.Connection) -> None:
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global schema 29 is required before single-track migration")
    if migration_marker_exists(connection):
        if not schema_shapes_valid(connection):
            raise RuntimeError("single-track marker exists with an invalid schema")
        return
    tables = _table_names(connection)
    if not {"actor_routes_v2", "actor_source_bindings_v2"} <= tables:
        raise RuntimeError("ActorOps v2 tables must be restored before single-track migration")
    route_columns = _columns(connection, "actor_routes_v2")
    binding_columns = _columns(connection, "actor_source_bindings_v2")
    if schema_shapes_valid(connection):
        raise RuntimeError("single-track schema is present without its migration marker")
    if not (
        ROUTE_COLUMNS | RETIRED_COLUMNS <= route_columns
        and BINDING_COLUMNS | RETIRED_COLUMNS <= binding_columns
    ):
        raise RuntimeError("partial ActorOps v2 single-track schema must be restored")


def _rebuild_tables(connection: sqlite3.Connection) -> int:
    """Rebuild only current v2 Route/Binding tables with foreign keys disabled."""

    connection.execute(ROUTE_TABLE_SQL)
    connection.execute(BINDING_TABLE_SQL)
    shadow_routes = int(connection.execute(
        "SELECT COUNT(*) FROM actor_routes_v2 WHERE runtime_mode='shadow'"
    ).fetchone()[0])
    connection.execute(
        """INSERT INTO actor_routes_v2_single_track_new (
               route_id, workspace_id, platform, target_type, capability,
               runtime_mode, per_run_cap_usd, generation, created_at, updated_at
           ) SELECT route_id, workspace_id, platform, target_type, capability,
                    CASE WHEN runtime_mode='active' THEN 'active' ELSE 'disabled' END,
                    per_run_cap_usd, generation, created_at, updated_at
             FROM actor_routes_v2"""
    )
    connection.execute(
        """INSERT INTO actor_source_bindings_v2_single_track_new (
               binding_id, workspace_id, source_id, route_id, target_fingerprint,
               status, binding_version, preferred_candidate_id,
               last_known_good_candidate_id, last_success_at,
               watermark_latest_published_at, watermark_item_id_hash,
               watermark_last_advanced_at, created_at, updated_at
           ) SELECT binding_id, workspace_id, source_id, route_id, target_fingerprint,
                    status, binding_version, preferred_candidate_id,
                    last_known_good_candidate_id, last_success_at,
                    watermark_latest_published_at, watermark_item_id_hash,
                    watermark_last_advanced_at, created_at, updated_at
             FROM actor_source_bindings_v2"""
    )
    connection.execute("DROP TABLE actor_source_bindings_v2")
    connection.execute("DROP TABLE actor_routes_v2")
    connection.execute(
        "ALTER TABLE actor_routes_v2_single_track_new RENAME TO actor_routes_v2"
    )
    connection.execute(
        "ALTER TABLE actor_source_bindings_v2_single_track_new "
        "RENAME TO actor_source_bindings_v2"
    )
    statement = ""
    for line in TRIGGER_SQL.splitlines():
        statement = f"{statement}\n{line}".strip()
        if statement and sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement:
        raise RuntimeError("incomplete single-track trigger statement")
    return shadow_routes


def seed_default_catalog(connection: sqlite3.Connection) -> dict[str, int]:
    """Seed disabled Route and Maintenance facts from the registered adapters."""

    stamp = datetime.now(timezone.utc).isoformat()
    registry = build_default_registry()
    workspaces = [
        str(row[0]) for row in connection.execute("SELECT id FROM workspaces ORDER BY id")
    ]
    routes = policies = 0
    for workspace_id in workspaces:
        for entry in catalog_entries(registry):
            cursor = connection.execute(
                """INSERT OR IGNORE INTO actor_routes_v2 (
                       route_id, workspace_id, platform, target_type, capability,
                       runtime_mode, per_run_cap_usd, generation, created_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, 'disabled', ?, 1, ?, ?)""",
                (
                    catalog_route_id(workspace_id, entry.route_key),
                    workspace_id,
                    entry.route_key.platform,
                    entry.route_key.target_type,
                    entry.route_key.capability,
                    entry.per_run_cap_usd,
                    stamp,
                    stamp,
                ),
            )
            routes += int(cursor.rowcount)
        cursor = connection.execute(
            """INSERT OR IGNORE INTO actor_maintenance_policies_v2 (
                   policy_id, workspace_id, route_id, enabled, monthly_budget_usd,
                   generation, created_at, updated_at
               ) VALUES (?, ?, NULL, 0, 3.0, 1, ?, ?)""",
            (maintenance_policy_id(workspace_id, None), workspace_id, stamp, stamp),
        )
        policies += int(cursor.rowcount)
        for row in connection.execute(
            "SELECT route_id FROM actor_routes_v2 WHERE workspace_id=? ORDER BY route_id",
            (workspace_id,),
        ):
            route_id = str(row[0])
            cursor = connection.execute(
                """INSERT OR IGNORE INTO actor_maintenance_policies_v2 (
                       policy_id, workspace_id, route_id, enabled, max_probe_usd,
                       max_probes_per_utc_day, auto_add_standby,
                       auto_replace_non_last, generation, created_at, updated_at
                   ) VALUES (?, ?, ?, 0, 0.05, 5, 1, 1, 1, ?, ?)""",
                (maintenance_policy_id(workspace_id, route_id), workspace_id, route_id, stamp, stamp),
            )
            policies += int(cursor.rowcount)
    return {"routes_seeded": routes, "policies_seeded": policies}


def mark_migrated(connection: sqlite3.Connection) -> None:
    existing = connection.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,),
    ).fetchone()
    if existing is not None and (
        str(existing["name"]) != MIGRATION_NAME
        or str(existing["checksum"]) != MIGRATION_CHECKSUM
    ):
        raise RuntimeError("global schema migration version 30 is already occupied")
    connection.execute(
        """INSERT INTO schema_migrations (version, name, checksum, applied_at)
           VALUES (?, ?, ?, ?) ON CONFLICT(version) DO NOTHING""",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM,
         datetime.now(timezone.utc).isoformat()),
    )


def apply_migration(connection: sqlite3.Connection) -> dict[str, int]:
    """Atomically rebuild v2 tables, seed the catalog, and write global 30."""

    if connection.in_transaction:
        raise RuntimeError("single-track migration requires a committed connection")
    _require_rebuildable_schema(connection)
    if migration_marker_exists(connection):
        return {"shadow_routes_disabled": 0, "routes_seeded": 0, "policies_seeded": 0}
    foreign_keys = int(connection.execute("PRAGMA foreign_keys").fetchone()[0])
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        shadows = _rebuild_tables(connection)
        seeded = seed_default_catalog(connection)
        mark_migrated(connection)
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    finally:
        connection.execute(f"PRAGMA foreign_keys={foreign_keys}")
    return {"shadow_routes_disabled": shadows, **seeded}


def bootstrap_service_store_schema(
    connection: sqlite3.Connection, *, existing_schema: bool
) -> None:
    if not existing_schema:
        apply_migration(connection)


__all__ = [
    "MIGRATION_CHECKSUM",
    "MIGRATION_NAME",
    "MIGRATION_VERSION",
    "apply_migration",
    "bootstrap_service_store_schema",
    "mark_migrated",
    "migration_marker_exists",
    "migration_required",
    "prerequisite_ready",
    "schema_shapes_valid",
    "seed_default_catalog",
]
