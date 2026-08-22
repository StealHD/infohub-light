"""Global 28 marker and validation for ActorOps v2 operator controls."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .actorops_v2_operator_schema_sql import OPERATOR_TABLES, REQUIRED_INDEXES, SCHEMA_SQL
from .actorops_v2_schema import migration_marker_exists as v26_marker
from .actorops_v2_schema import schema_shapes_valid as v26_shapes


ACTOROPS_V2_OPERATOR_MIGRATION_VERSION = 28
ACTOROPS_V2_OPERATOR_MIGRATION_NAME = "actorops_v2_operator_controls"
ACTOROPS_V2_OPERATOR_MIGRATION_CHECKSUM = "actorops-v2-operator-controls-v1"


def prerequisite_ready(connection: sqlite3.Connection) -> bool:
    """global 28 only depends on the valid v2 schema, never 25 or 27."""

    if v26_marker(connection) and v26_shapes(connection):
        return True
    return bool(connection.execute(
        """SELECT 1 FROM schema_migrations
           WHERE version=30 AND name='actorops_v2_single_track'
             AND checksum='actorops-v2-single-track-v1'"""
    ).fetchone())


def existing_operator_tables(connection: sqlite3.Connection) -> set[str]:
    names = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='table'")}
    return names & set(OPERATOR_TABLES)


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
        (ACTOROPS_V2_OPERATOR_MIGRATION_VERSION, ACTOROPS_V2_OPERATOR_MIGRATION_NAME, ACTOROPS_V2_OPERATOR_MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection: sqlite3.Connection) -> bool:
    if existing_operator_tables(connection) != set(OPERATOR_TABLES):
        return False
    indexes = {str(row[0]) for row in connection.execute("SELECT name FROM sqlite_master WHERE type='index'")}
    return REQUIRED_INDEXES <= indexes


def migration_required(connection: sqlite3.Connection) -> bool:
    return not (migration_marker_exists(connection) and schema_shapes_valid(connection))


def install_schema(connection: sqlite3.Connection) -> None:
    if existing_operator_tables(connection):
        raise RuntimeError("partial ActorOps v2 operator schema must be restored before migration")
    statement = ""
    for line in SCHEMA_SQL.splitlines():
        statement = f"{statement}\n{line}".strip()
        if statement and sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement:
        raise RuntimeError("incomplete ActorOps v2 operator schema statement")


def mark_migrated(connection: sqlite3.Connection) -> None:
    existing = connection.execute("SELECT name, checksum FROM schema_migrations WHERE version=?", (ACTOROPS_V2_OPERATOR_MIGRATION_VERSION,)).fetchone()
    if existing is not None and (str(existing["name"]) != ACTOROPS_V2_OPERATOR_MIGRATION_NAME or str(existing["checksum"]) != ACTOROPS_V2_OPERATOR_MIGRATION_CHECKSUM):
        raise RuntimeError("global schema migration version 28 is already occupied")
    connection.execute(
        "INSERT INTO schema_migrations (version,name,checksum,applied_at) VALUES (?,?,?,?) ON CONFLICT(version) DO NOTHING",
        (ACTOROPS_V2_OPERATOR_MIGRATION_VERSION, ACTOROPS_V2_OPERATOR_MIGRATION_NAME, ACTOROPS_V2_OPERATOR_MIGRATION_CHECKSUM, datetime.now(timezone.utc).isoformat()),
    )


def bootstrap_service_store_schema(connection: sqlite3.Connection, *, existing_schema: bool) -> None:
    if not existing_schema:
        if not prerequisite_ready(connection):
            raise RuntimeError("global schema 26 is required before ActorOps operator controls")
        install_schema(connection)
        mark_migrated(connection)


__all__ = [
    "ACTOROPS_V2_OPERATOR_MIGRATION_CHECKSUM", "ACTOROPS_V2_OPERATOR_MIGRATION_NAME",
    "ACTOROPS_V2_OPERATOR_MIGRATION_VERSION", "OPERATOR_TABLES", "bootstrap_service_store_schema",
    "existing_operator_tables", "install_schema", "mark_migrated", "migration_marker_exists",
    "migration_required", "prerequisite_ready", "schema_shapes_valid",
]
