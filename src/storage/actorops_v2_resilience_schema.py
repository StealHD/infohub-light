"""Global 31 storage for ActorOps source freshness, repair, and safe traces."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .actorops_v2_single_track_schema import (
    migration_marker_exists as v30_marker,
    schema_shapes_valid as v30_shapes,
)


MIGRATION_VERSION = 31
MIGRATION_NAME = "actorops_v2_resilience"
MIGRATION_CHECKSUM = "actorops-v2-resilience-v1"

TABLES = {
    "actor_source_candidate_freshness_v2",
    "actor_route_repairs_v2",
    "actor_execution_events_v2",
}
INDEXES = {
    "idx_actor_freshness_source_state",
    "idx_actor_repairs_due",
    "idx_actor_repairs_route",
    "idx_actor_execution_events_query",
    "idx_actor_execution_events_retention",
    "idx_actor_repairs_one_open_source",
}

SCHEMA_SQL = """
CREATE TABLE actor_source_candidate_freshness_v2 (
    workspace_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    candidate_id TEXT NOT NULL,
    binding_version INTEGER NOT NULL CHECK(binding_version >= 1),
    consecutive_scheduled_no_advance INTEGER NOT NULL DEFAULT 0
        CHECK(consecutive_scheduled_no_advance >= 0),
    state TEXT NOT NULL DEFAULT 'neutral'
        CHECK(state IN ('neutral','suspected_stale','source_stale','confirmed_no_change')),
    cooldown_until TEXT,
    last_outcome TEXT,
    last_job_id TEXT,
    last_checked_at TEXT,
    last_confirmed_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    PRIMARY KEY(workspace_id, source_id, candidate_id, binding_version),
    FOREIGN KEY(workspace_id, source_id)
        REFERENCES actor_source_bindings_v2(workspace_id, source_id)
        ON DELETE CASCADE,
    FOREIGN KEY(workspace_id, candidate_id)
        REFERENCES actor_candidates_v2(workspace_id, candidate_id)
        ON DELETE CASCADE
);
CREATE INDEX idx_actor_freshness_source_state
    ON actor_source_candidate_freshness_v2(
        workspace_id, source_id, binding_version, state, cooldown_until
    );

CREATE TABLE actor_route_repairs_v2 (
    repair_id TEXT PRIMARY KEY,
    workspace_id TEXT NOT NULL,
    route_id TEXT NOT NULL,
    source_id TEXT NOT NULL,
    origin_job_id TEXT,
    trigger_code TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN ('queued','discovering','awaiting_probe','recovered','blocked','failed','cancelled')),
    discovery_id TEXT,
    candidate_id TEXT,
    error_code TEXT,
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    next_attempt_at TEXT,
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    terminal_at TEXT,
    FOREIGN KEY(workspace_id, route_id)
        REFERENCES actor_routes_v2(workspace_id, route_id)
        ON DELETE CASCADE,
    FOREIGN KEY(workspace_id, source_id)
        REFERENCES actor_source_bindings_v2(workspace_id, source_id)
        ON DELETE CASCADE,
    FOREIGN KEY(workspace_id, candidate_id)
        REFERENCES actor_candidates_v2(workspace_id, candidate_id)
        ON DELETE SET NULL
);
CREATE UNIQUE INDEX idx_actor_repairs_one_open_source
    ON actor_route_repairs_v2(workspace_id, route_id, source_id)
    WHERE status IN ('queued','discovering','awaiting_probe','blocked');
CREATE INDEX idx_actor_repairs_due
    ON actor_route_repairs_v2(workspace_id, status, next_attempt_at, updated_at);
CREATE INDEX idx_actor_repairs_route
    ON actor_route_repairs_v2(workspace_id, route_id, updated_at DESC);

CREATE TABLE actor_execution_events_v2 (
    event_id TEXT PRIMARY KEY,
    occurrence_key TEXT NOT NULL,
    workspace_id TEXT NOT NULL,
    root_job_id TEXT,
    job_id TEXT,
    route_id TEXT,
    source_id TEXT,
    candidate_id TEXT,
    repair_id TEXT,
    phase TEXT NOT NULL,
    outcome TEXT NOT NULL,
    reason_code TEXT,
    counts_json TEXT NOT NULL DEFAULT '{}',
    final_cost_usd REAL CHECK(final_cost_usd IS NULL OR final_cost_usd >= 0),
    mirror_state TEXT NOT NULL DEFAULT 'complete'
        CHECK(mirror_state IN ('complete','partial')),
    created_at TEXT NOT NULL,
    UNIQUE(workspace_id, occurrence_key),
    FOREIGN KEY(workspace_id, route_id)
        REFERENCES actor_routes_v2(workspace_id, route_id)
        ON DELETE SET NULL,
    FOREIGN KEY(workspace_id, source_id)
        REFERENCES actor_source_bindings_v2(workspace_id, source_id)
        ON DELETE SET NULL,
    FOREIGN KEY(workspace_id, candidate_id)
        REFERENCES actor_candidates_v2(workspace_id, candidate_id)
        ON DELETE SET NULL,
    FOREIGN KEY(repair_id) REFERENCES actor_route_repairs_v2(repair_id)
        ON DELETE SET NULL
);
CREATE INDEX idx_actor_execution_events_query
    ON actor_execution_events_v2(
        workspace_id, root_job_id, route_id, source_id, repair_id, created_at DESC, event_id DESC
    );
CREATE INDEX idx_actor_execution_events_retention
    ON actor_execution_events_v2(created_at);
"""


def _names(connection: sqlite3.Connection, kind: str) -> set[str]:
    return {
        str(row[0])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type=?", (kind,)
        )
    }


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def prerequisite_ready(connection: sqlite3.Connection) -> bool:
    return v30_marker(connection) and v30_shapes(connection)


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection: sqlite3.Connection) -> bool:
    if not TABLES <= _names(connection, "table") or not INDEXES <= _names(connection, "index"):
        return False
    required = {
        "actor_source_candidate_freshness_v2": {
            "source_id", "candidate_id", "binding_version",
            "consecutive_scheduled_no_advance", "state", "cooldown_until",
        },
        "actor_route_repairs_v2": {
            "repair_id", "route_id", "source_id", "status", "discovery_id",
            "candidate_id", "next_attempt_at",
        },
        "actor_execution_events_v2": {
            "event_id", "occurrence_key", "root_job_id", "repair_id", "phase",
            "outcome", "counts_json", "mirror_state",
        },
    }
    return prerequisite_ready(connection) and all(
        fields <= _columns(connection, table) for table, fields in required.items()
    )


def migration_required(connection: sqlite3.Connection) -> bool:
    return not (migration_marker_exists(connection) and schema_shapes_valid(connection))


def install_schema(connection: sqlite3.Connection) -> None:
    existing = _names(connection, "table") & TABLES
    if existing:
        raise RuntimeError("partial ActorOps v2 resilience schema must be restored")
    connection.executescript(SCHEMA_SQL)


def mark_migrated(connection: sqlite3.Connection) -> None:
    existing = connection.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,),
    ).fetchone()
    if existing is not None and (
        str(existing["name"]) != MIGRATION_NAME
        or str(existing["checksum"]) != MIGRATION_CHECKSUM
    ):
        raise RuntimeError("global schema migration version 31 is already occupied")
    connection.execute(
        """INSERT INTO schema_migrations (version,name,checksum,applied_at)
           VALUES (?,?,?,?) ON CONFLICT(version) DO NOTHING""",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM,
         datetime.now(timezone.utc).isoformat()),
    )


def apply_migration(connection: sqlite3.Connection) -> dict[str, int]:
    if connection.in_transaction:
        raise RuntimeError("ActorOps resilience migration requires a committed connection")
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global schema 30 is required before resilience migration")
    if migration_marker_exists(connection):
        if not schema_shapes_valid(connection):
            raise RuntimeError("resilience marker exists with an invalid schema")
        return {"freshness_rows": 0, "repair_rows": 0, "event_rows": 0}
    if _names(connection, "table") & TABLES:
        raise RuntimeError("partial ActorOps v2 resilience schema must be restored")
    connection.execute("BEGIN IMMEDIATE")
    try:
        install_schema(connection)
        mark_migrated(connection)
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    return {"freshness_rows": 0, "repair_rows": 0, "event_rows": 0}


def bootstrap_service_store_schema(
    connection: sqlite3.Connection, *, existing_schema: bool
) -> None:
    if not existing_schema:
        apply_migration(connection)


__all__ = [
    "INDEXES", "MIGRATION_CHECKSUM", "MIGRATION_NAME", "MIGRATION_VERSION", "TABLES",
    "apply_migration", "bootstrap_service_store_schema", "install_schema", "mark_migrated",
    "migration_marker_exists", "migration_required", "prerequisite_ready", "schema_shapes_valid",
]
