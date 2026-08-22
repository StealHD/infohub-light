"""Global schema 26 marker, validation, and fresh-store bootstrap."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .actorops_v2_backfill import backfill_v1
from .actorops_v2_schema_sql import (
    REQUIRED_INDEXES,
    SCHEMA_SQL,
    V2_TABLES,
)
from .actorops_v2_trigger_sql import REQUIRED_TRIGGERS, TRIGGER_SQL
from .apify_actor_pool_management_schema import (
    APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_CHECKSUM,
    apify_actor_pool_management_v22_schema_shapes_valid,
)


ACTOROPS_V2_MIGRATION_VERSION = 26
ACTOROPS_V2_MIGRATION_NAME = "actorops_v2"
ACTOROPS_V2_MIGRATION_CHECKSUM = "actorops-v2-stable-fetch-domain-v1"


def prerequisite_ready(connection: sqlite3.Connection) -> bool:
    marker = connection.execute(
        """SELECT 1 FROM schema_migrations
           WHERE version = 24 AND name = 'apify_actor_pool_management_v22'
             AND checksum = ?""",
        (APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_CHECKSUM,),
    ).fetchone()
    return bool(marker and apify_actor_pool_management_v22_schema_shapes_valid(connection))


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(
        connection.execute(
            """SELECT 1 FROM schema_migrations
               WHERE version = ? AND name = ? AND checksum = ?""",
            (
                ACTOROPS_V2_MIGRATION_VERSION,
                ACTOROPS_V2_MIGRATION_NAME,
                ACTOROPS_V2_MIGRATION_CHECKSUM,
            ),
        ).fetchone()
    )


def existing_v2_tables(connection: sqlite3.Connection) -> set[str]:
    names = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        )
    }
    return names & set(V2_TABLES)


def schema_shapes_valid(connection: sqlite3.Connection) -> bool:
    if existing_v2_tables(connection) != set(V2_TABLES):
        return False
    indexes = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'index'"
        )
    }
    triggers = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'trigger'"
        )
    }
    return REQUIRED_INDEXES <= indexes and REQUIRED_TRIGGERS <= triggers


def migration_required(connection: sqlite3.Connection) -> bool:
    return not (migration_marker_exists(connection) and schema_shapes_valid(connection))


def install_schema(connection: sqlite3.Connection) -> None:
    if existing_v2_tables(connection):
        raise RuntimeError("partial ActorOps v2 schema must be restored before migration")
    statement = ""
    for line in f"{SCHEMA_SQL}\n{TRIGGER_SQL}".splitlines():
        statement = f"{statement}\n{line}".strip()
        if statement and sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement:
        raise RuntimeError("incomplete ActorOps v2 schema statement")


def mark_migrated(connection: sqlite3.Connection) -> None:
    existing = connection.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version = ?",
        (ACTOROPS_V2_MIGRATION_VERSION,),
    ).fetchone()
    if existing is not None and (
        str(existing["name"]) != ACTOROPS_V2_MIGRATION_NAME
        or str(existing["checksum"]) != ACTOROPS_V2_MIGRATION_CHECKSUM
    ):
        raise RuntimeError("global schema migration version 26 is already occupied")
    connection.execute(
        """INSERT INTO schema_migrations (version, name, checksum, applied_at)
           VALUES (?, ?, ?, ?)
           ON CONFLICT(version) DO NOTHING""",
        (
            ACTOROPS_V2_MIGRATION_VERSION,
            ACTOROPS_V2_MIGRATION_NAME,
            ACTOROPS_V2_MIGRATION_CHECKSUM,
            datetime.now(timezone.utc).isoformat(),
        ),
    )


def bootstrap_fresh_schema(connection: sqlite3.Connection) -> dict[str, int]:
    if not prerequisite_ready(connection):
        raise RuntimeError("global schema 24 is required before ActorOps v2")
    install_schema(connection)
    mark_migrated(connection)
    return {"routes": 0, "candidates": 0, "bindings": 0, "policies": 0}


def bootstrap_service_store_schema(
    connection: sqlite3.Connection, *, existing_schema: bool
) -> None:
    if not existing_schema:
        bootstrap_fresh_schema(connection)


__all__ = [
    "ACTOROPS_V2_MIGRATION_CHECKSUM",
    "ACTOROPS_V2_MIGRATION_NAME",
    "ACTOROPS_V2_MIGRATION_VERSION",
    "V2_TABLES",
    "backfill_v1",
    "bootstrap_service_store_schema",
    "existing_v2_tables",
    "install_schema",
    "mark_migrated",
    "migration_marker_exists",
    "migration_required",
    "prerequisite_ready",
    "schema_shapes_valid",
]
