"""Global 33 schema for ActorOps circuits, maintenance, and presentation."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .actorops_v2_presentation_schema_sql import (
    PRESENTATION_TABLE,
    REQUIRED_COLUMNS as PRESENTATION_COLUMNS,
    REQUIRED_INDEXES as PRESENTATION_INDEXES,
    SCHEMA_SQL as PRESENTATION_SCHEMA_SQL,
)
from .actorops_v2_stability_backfill import backfill_source_circuits
from .system_settings_v32_schema import (
    migration_marker_exists as v32_marker,
    schema_shapes_valid as v32_shapes,
)


MIGRATION_VERSION = 33
MIGRATION_NAME = "actorops_v2_stability"
MIGRATION_CHECKSUM = "actorops-v2-stability-v1"
FRESHNESS_COLUMNS = frozenset({
    "failure_streak", "cooldown_reason", "half_open_lease_until",
    "half_open_lease_token",
})


def _names(connection: sqlite3.Connection, kind: str) -> set[str]:
    return {
        str(row[0]) for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type=?", (kind,)
        )
    }


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def prerequisite_ready(connection: sqlite3.Connection) -> bool:
    return v32_marker(connection) and v32_shapes(connection)


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection: sqlite3.Connection) -> bool:
    tables = _names(connection, "table")
    indexes = _names(connection, "index")
    return bool(
        prerequisite_ready(connection)
        and PRESENTATION_TABLE in tables
        and PRESENTATION_COLUMNS <= _columns(connection, PRESENTATION_TABLE)
        and PRESENTATION_INDEXES <= indexes
        and "authorization_origin"
        in _columns(connection, "actor_maintenance_policies_v2")
        and FRESHNESS_COLUMNS
        <= _columns(connection, "actor_source_candidate_freshness_v2")
    )


def migration_required(connection: sqlite3.Connection) -> bool:
    return not (migration_marker_exists(connection) and schema_shapes_valid(connection))


def partial_schema_present(connection: sqlite3.Connection) -> bool:
    return bool(
        "authorization_origin"
        in _columns(connection, "actor_maintenance_policies_v2")
        or FRESHNESS_COLUMNS
        & _columns(connection, "actor_source_candidate_freshness_v2")
        or PRESENTATION_TABLE in _names(connection, "table")
        or PRESENTATION_INDEXES & _names(connection, "index")
    )


def _assert_unmodified_prerequisite(connection: sqlite3.Connection) -> None:
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global schema 32 is required before ActorOps stability")
    if partial_schema_present(connection):
        raise RuntimeError("partial ActorOps stability schema must be restored")


def _execute_schema(connection: sqlite3.Connection, sql: str) -> None:
    statement = ""
    for line in sql.splitlines():
        statement = f"{statement}\n{line}".strip()
        if statement and sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement:
        raise RuntimeError("incomplete ActorOps stability schema statement")


def apply_migration(connection: sqlite3.Connection) -> dict[str, int]:
    if connection.in_transaction:
        raise RuntimeError("ActorOps stability migration requires a committed connection")
    existing = connection.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,),
    ).fetchone()
    if existing is not None and (
        str(existing["name"]) != MIGRATION_NAME
        or str(existing["checksum"]) != MIGRATION_CHECKSUM
    ):
        raise RuntimeError("global schema migration version 33 is already occupied")
    if migration_marker_exists(connection):
        if not schema_shapes_valid(connection):
            raise RuntimeError("ActorOps stability marker exists with an invalid schema")
        return {
            "policies_default_enabled": 0,
            "auto_replacement_disabled": 0,
            "source_circuits_backfilled": 0,
        }
    _assert_unmodified_prerequisite(connection)
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.execute(
            """ALTER TABLE actor_maintenance_policies_v2
               ADD COLUMN authorization_origin TEXT NOT NULL DEFAULT 'none'
               CHECK(authorization_origin IN ('system_default','operator','none'))"""
        )
        connection.execute(
            """ALTER TABLE actor_source_candidate_freshness_v2
               ADD COLUMN failure_streak INTEGER NOT NULL DEFAULT 0
               CHECK(failure_streak >= 0)"""
        )
        connection.execute(
            "ALTER TABLE actor_source_candidate_freshness_v2 ADD COLUMN cooldown_reason TEXT"
        )
        connection.execute(
            "ALTER TABLE actor_source_candidate_freshness_v2 ADD COLUMN half_open_lease_until TEXT"
        )
        connection.execute(
            "ALTER TABLE actor_source_candidate_freshness_v2 ADD COLUMN half_open_lease_token TEXT"
        )
        _execute_schema(connection, PRESENTATION_SCHEMA_SQL)
        circuits_backfilled = backfill_source_circuits(
            connection, now=datetime.fromisoformat(stamp)
        )
        default_count = int(connection.execute(
            "SELECT COUNT(*) FROM actor_maintenance_policies_v2 WHERE generation=1"
        ).fetchone()[0])
        replacement_count = int(connection.execute(
            """SELECT COUNT(*) FROM actor_maintenance_policies_v2
               WHERE route_id IS NOT NULL AND auto_replace_non_last!=0"""
        ).fetchone()[0])
        connection.execute(
            """UPDATE actor_maintenance_policies_v2
               SET enabled=CASE WHEN generation=1 THEN 1 ELSE enabled END,
                   authorized_by_user_id=CASE
                       WHEN generation=1 THEN COALESCE(authorized_by_user_id, 'system_default')
                       ELSE authorized_by_user_id END,
                   authorized_at=CASE
                       WHEN generation=1 THEN COALESCE(authorized_at, ?)
                       ELSE authorized_at END,
                   authorization_origin=CASE
                       WHEN generation=1 THEN 'system_default'
                       WHEN enabled=1 THEN 'operator' ELSE 'none' END,
                   auto_replace_non_last=CASE
                       WHEN route_id IS NOT NULL THEN 0 ELSE auto_replace_non_last END,
                   generation=generation+CASE
                       WHEN generation=1 OR COALESCE(auto_replace_non_last,0)!=0 THEN 1
                       ELSE 0 END,
                   updated_at=CASE
                       WHEN generation=1 OR COALESCE(auto_replace_non_last,0)!=0 THEN ?
                       ELSE updated_at END""",
            (stamp, stamp),
        )
        connection.execute(
            """INSERT INTO schema_migrations (version,name,checksum,applied_at)
               VALUES (?,?,?,?)""",
            (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM, stamp),
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return {
        "policies_default_enabled": default_count,
        "auto_replacement_disabled": replacement_count,
        "source_circuits_backfilled": circuits_backfilled,
    }


def bootstrap_service_store_schema(
    connection: sqlite3.Connection, *, existing_schema: bool
) -> None:
    if not existing_schema:
        apply_migration(connection)


__all__ = [
    "FRESHNESS_COLUMNS", "MIGRATION_CHECKSUM", "MIGRATION_NAME",
    "MIGRATION_VERSION", "apply_migration", "bootstrap_service_store_schema",
    "migration_marker_exists", "migration_required", "partial_schema_present",
    "prerequisite_ready", "schema_shapes_valid",
]
