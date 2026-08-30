"""Global 36 enables proof-gated replacement for untouched maintenance policy."""

from __future__ import annotations

import sqlite3
from datetime import datetime, timezone

from .actorops_v2_sampling_schema import (
    migration_marker_exists as v35_marker,
    schema_shapes_valid as v35_shapes,
)


MIGRATION_VERSION = 36
MIGRATION_NAME = "actorops_v2_verified_auto_replacement"
MIGRATION_CHECKSUM = "actorops-v2-verified-auto-replacement-v1"


def prerequisite_ready(connection: sqlite3.Connection) -> bool:
    return v35_marker(connection) and v35_shapes(connection)


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=? AND name=? AND checksum=?",
        (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM),
    ).fetchone())


def schema_shapes_valid(connection: sqlite3.Connection) -> bool:
    invalid = connection.execute(
        """SELECT 1 FROM actor_maintenance_policies_v2
           WHERE route_id IS NOT NULL AND auto_replace_non_last NOT IN (0,1)
           LIMIT 1"""
    ).fetchone()
    return prerequisite_ready(connection) and invalid is None


def apply_migration(connection: sqlite3.Connection) -> dict[str, int]:
    if connection.in_transaction:
        raise RuntimeError("verified replacement migration requires a committed connection")
    occupied = connection.execute(
        "SELECT name,checksum FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,),
    ).fetchone()
    if occupied is not None and (
        str(occupied["name"]) != MIGRATION_NAME
        or str(occupied["checksum"]) != MIGRATION_CHECKSUM
    ):
        raise RuntimeError("global schema migration version 36 is already occupied")
    if migration_marker_exists(connection):
        if not schema_shapes_valid(connection):
            raise RuntimeError("verified replacement marker exists with invalid schema")
        return {"route_policies_enabled": 0}
    if not prerequisite_ready(connection):
        raise RuntimeError("valid global schema 35 is required before verified replacement")
    stamp = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute("BEGIN IMMEDIATE")
        changed = connection.execute(
            """UPDATE actor_maintenance_policies_v2
               SET auto_replace_non_last=1, generation=generation+1, updated_at=?
               WHERE route_id IS NOT NULL AND enabled=1
                 AND authorization_origin='system_default'
                 AND auto_replace_non_last=0""",
            (stamp,),
        ).rowcount
        connection.execute(
            "INSERT INTO schema_migrations(version,name,checksum,applied_at) VALUES(?,?,?,?)",
            (MIGRATION_VERSION, MIGRATION_NAME, MIGRATION_CHECKSUM, stamp),
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    if not schema_shapes_valid(connection):
        raise RuntimeError("verified replacement schema validation failed")
    return {"route_policies_enabled": int(changed)}


def bootstrap_service_store_schema(
    connection: sqlite3.Connection, *, existing_schema: bool,
) -> None:
    if not existing_schema:
        apply_migration(connection)


__all__ = [
    "MIGRATION_CHECKSUM", "MIGRATION_NAME", "MIGRATION_VERSION",
    "apply_migration", "bootstrap_service_store_schema",
    "migration_marker_exists", "prerequisite_ready", "schema_shapes_valid",
]
