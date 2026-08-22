"""Global 29 marker, installation, and validation for Attempt recovery."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .actorops_v2_attempt_recovery_schema_sql import (
    ALTER_SQL,
    INDEX_SQL,
    REQUIRED_COLUMNS,
    REQUIRED_INDEXES,
    REQUIRED_TRIGGERS,
    TRIGGER_SQL,
)
from .actorops_v2_operator_schema import migration_marker_exists as v28_marker
from .actorops_v2_operator_schema import schema_shapes_valid as v28_shapes


MIGRATION_VERSION = 29
MIGRATION_NAME = "actorops_v2_attempt_recovery"
MIGRATION_CHECKSUM = "actorops-v2-attempt-recovery-v1"


def prerequisite_ready(connection: sqlite3.Connection) -> bool:
    return v28_marker(connection) and v28_shapes(connection)


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection: sqlite3.Connection) -> bool:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(actor_attempts_v2)")
    }
    indexes = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='index'"
        )
    }
    triggers = {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type='trigger'"
        )
    }
    return (
        REQUIRED_COLUMNS <= columns
        and REQUIRED_INDEXES <= indexes
        and REQUIRED_TRIGGERS <= triggers
    )


def migration_required(connection: sqlite3.Connection) -> bool:
    return not (migration_marker_exists(connection) and schema_shapes_valid(connection))


def install_schema(connection: sqlite3.Connection) -> None:
    columns = {
        str(row[1])
        for row in connection.execute("PRAGMA table_info(actor_attempts_v2)")
    }
    if columns & REQUIRED_COLUMNS:
        raise RuntimeError("partial ActorOps v2 Attempt recovery schema must be restored")
    for statement in ALTER_SQL:
        connection.execute(statement)
    connection.execute(
        """UPDATE actor_attempts_v2
           SET logical_job_id='legacy:' || attempt_id,
               request_fingerprint='legacy:' || idempotency_key"""
    )
    connection.execute(INDEX_SQL)
    statement = ""
    for line in TRIGGER_SQL.splitlines():
        statement = f"{statement}\n{line}".strip()
        if statement and sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement:
        raise RuntimeError("incomplete Attempt recovery trigger statement")


def mark_migrated(connection: sqlite3.Connection) -> None:
    existing = connection.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,),
    ).fetchone()
    if existing is not None and (
        str(existing["name"]) != MIGRATION_NAME
        or str(existing["checksum"]) != MIGRATION_CHECKSUM
    ):
        raise RuntimeError("global schema migration version 29 is already occupied")
    connection.execute(
        """INSERT INTO schema_migrations (version,name,checksum,applied_at)
           VALUES (?,?,?,?) ON CONFLICT(version) DO NOTHING""",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM,
         datetime.now(timezone.utc).isoformat()),
    )


def bootstrap_service_store_schema(
    connection: sqlite3.Connection, *, existing_schema: bool
) -> None:
    if existing_schema:
        return
    if not prerequisite_ready(connection):
        raise RuntimeError("global schema 28 is required before Attempt recovery")
    install_schema(connection)
    mark_migrated(connection)


__all__ = [
    "MIGRATION_CHECKSUM",
    "MIGRATION_NAME",
    "MIGRATION_VERSION",
    "bootstrap_service_store_schema",
    "install_schema",
    "mark_migrated",
    "migration_marker_exists",
    "migration_required",
    "prerequisite_ready",
    "schema_shapes_valid",
]
