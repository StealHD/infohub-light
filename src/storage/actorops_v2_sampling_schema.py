"""Global 35 private InputPlan sidecar for controlled Actor sampling."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .actorops_v2_revalidation_schema import (
    migration_marker_exists as v34_marker,
    schema_shapes_valid as v34_shapes,
)


MIGRATION_VERSION = 35
MIGRATION_NAME = "actorops_v2_sampling_plans"
MIGRATION_CHECKSUM = "actorops-v2-sampling-plans-v1"
TABLE_NAME = "actor_candidate_sampling_plans_v2"
INDEX_NAME = "idx_actor_candidate_sampling_plans_v2_status"
REQUIRED_COLUMNS = frozenset({
    "workspace_id", "candidate_id", "actor_id", "build_id", "build_number",
    "input_schema_hash", "input_plan_json", "input_plan_hash", "status",
    "generation", "created_at", "updated_at",
})
SCHEMA_SQL = f"""
CREATE TABLE {TABLE_NAME} (
    workspace_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    actor_id TEXT NOT NULL,
    build_id TEXT NOT NULL,
    build_number TEXT NOT NULL,
    input_schema_hash TEXT NOT NULL,
    input_plan_json TEXT NOT NULL,
    input_plan_hash TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('ready','stale','invalid')),
    generation INTEGER NOT NULL DEFAULT 1 CHECK(generation >= 1),
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id, candidate_id),
    FOREIGN KEY(workspace_id, candidate_id)
      REFERENCES actor_candidates_v2(workspace_id, candidate_id) ON DELETE RESTRICT
);
CREATE INDEX {INDEX_NAME}
  ON {TABLE_NAME}(workspace_id, status, updated_at);
"""


def _execute_schema(connection: sqlite3.Connection) -> None:
    statement = ""
    for line in SCHEMA_SQL.splitlines():
        statement = f"{statement}\n{line}".strip()
        if statement and sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement:
        raise RuntimeError("incomplete ActorOps sampling schema statement")


def prerequisite_ready(connection: sqlite3.Connection) -> bool:
    return v34_marker(connection) and v34_shapes(connection)


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection: sqlite3.Connection) -> bool:
    tables = {str(row[0]) for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='table'"
    )}
    indexes = {str(row[0]) for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type='index'"
    )}
    columns = {
        str(row[1]) for row in connection.execute(f"PRAGMA table_info({TABLE_NAME})")
    } if TABLE_NAME in tables else set()
    return bool(
        prerequisite_ready(connection)
        and TABLE_NAME in tables
        and REQUIRED_COLUMNS <= columns
        and INDEX_NAME in indexes
    )


def apply_migration(connection: sqlite3.Connection) -> dict[str, int]:
    if connection.in_transaction:
        raise RuntimeError("ActorOps sampling migration requires a committed connection")
    existing = connection.execute(
        "SELECT name,checksum FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,),
    ).fetchone()
    if existing is not None:
        name = existing["name"] if isinstance(existing, sqlite3.Row) else existing[0]
        checksum = (
            existing["checksum"] if isinstance(existing, sqlite3.Row) else existing[1]
        )
        if str(name) != MIGRATION_NAME or str(checksum) != MIGRATION_CHECKSUM:
            raise RuntimeError("global schema migration version 35 is already occupied")
    if migration_marker_exists(connection):
        if not schema_shapes_valid(connection):
            raise RuntimeError("ActorOps sampling marker exists with invalid schema")
        return {"sampling_plan_tables_created": 0}
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global schema 34 is required before ActorOps sampling")
    try:
        connection.execute("BEGIN IMMEDIATE")
        _execute_schema(connection)
        connection.execute(
            "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
            (
                MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM,
                datetime.now(timezone.utc).isoformat(),
            ),
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    if not schema_shapes_valid(connection):
        raise RuntimeError("ActorOps sampling schema validation failed")
    return {"sampling_plan_tables_created": 1}


def bootstrap_service_store_schema(
    connection: sqlite3.Connection, *, existing_schema: bool,
) -> None:
    if not existing_schema:
        apply_migration(connection)


__all__ = [
    "MIGRATION_CHECKSUM", "MIGRATION_NAME", "MIGRATION_VERSION", "TABLE_NAME",
    "apply_migration", "bootstrap_service_store_schema",
    "migration_marker_exists", "prerequisite_ready", "schema_shapes_valid",
]
