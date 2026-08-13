"""Global schema 24 helpers for fixed ActorOps pool management.

Kept outside :mod:`service_store` so new ActorOps schema behavior does not
extend the legacy storage façade.
"""

from __future__ import annotations

import re
import sqlite3
from collections.abc import Iterable
from datetime import datetime, timezone


APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_VERSION = 24
APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_NAME = "apify_actor_pool_management_v22"
APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_CHECKSUM = (
    "apify-actor-pool-management-v22-slot-operations"
)


def _normalized_schema_sql(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").casefold())


def apify_actor_pool_management_v22_schema_shapes_valid(
    connection: sqlite3.Connection,
) -> bool:
    """Validate the per-slot Actor pool operation columns and goal enum."""

    # A local import avoids a service-store import cycle while preserving the
    # preceding migration's fail-closed shape check.
    from .service_store import apify_actor_resilience_v21_schema_shapes_valid

    if not apify_actor_resilience_v21_schema_shapes_valid(connection):
        return False
    sql = {
        str(row[0]): _normalized_schema_sql(row[1])
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    stage_sql = sql.get("apify_actor_pool_stages", "")
    batch_sql = sql.get("apify_actor_canary_batches", "")
    return all(
        fragment in stage_sql and fragment in batch_sql
        for fragment in ("operation_slot", "add_slot", "replace_slot")
    )


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(
        connection.execute(
            """SELECT 1 FROM schema_migrations
               WHERE version = ? AND name = ? AND checksum = ?""",
            (
                APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_VERSION,
                APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_NAME,
                APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_CHECKSUM,
            ),
        ).fetchone()
    )


def migration_required(connection: sqlite3.Connection) -> bool:
    """Return whether global schema 24 is absent or malformed."""

    return not (
        migration_marker_exists(connection)
        and apify_actor_pool_management_v22_schema_shapes_valid(connection)
    )


def mark_migrated(
    connection: sqlite3.Connection,
    *,
    commit: bool = True,
) -> None:
    """Record the immutable global-schema marker, rejecting version reuse."""

    existing = connection.execute(
        "SELECT name FROM schema_migrations WHERE version = ?",
        (APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_VERSION,),
    ).fetchone()
    if existing is not None and str(existing["name"]) != (
        APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_NAME
    ):
        raise RuntimeError("global schema migration version 24 is already occupied")
    connection.execute(
        """
        INSERT INTO schema_migrations (version, name, checksum, applied_at)
        VALUES (?, ?, ?, ?)
        ON CONFLICT(version) DO UPDATE SET
            checksum = excluded.checksum,
            applied_at = excluded.applied_at
        WHERE schema_migrations.name = excluded.name
        """,
        (
            APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_VERSION,
            APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_NAME,
            APIFY_ACTOR_POOL_MANAGEMENT_MIGRATION_CHECKSUM,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    if commit:
        connection.commit()


def _column_names(connection: sqlite3.Connection, table: str) -> set[str]:
    return {
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    }


def _rebuild_table(
    connection: sqlite3.Connection,
    table: str,
    *,
    replacements: Iterable[tuple[str, str]],
    index_sql: Iterable[str],
) -> None:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
        (table,),
    ).fetchone()
    if row is None or not row[0]:
        raise RuntimeError(f"missing required table: {table}")
    create_sql, replacement_count = re.subn(
        rf'^CREATE\s+TABLE\s+"?{re.escape(table)}"?',
        f"CREATE TABLE {table}_v24",
        str(row[0]),
        count=1,
        flags=re.IGNORECASE,
    )
    if replacement_count != 1:
        raise RuntimeError(f"unexpected create statement for {table}")
    for before, after in replacements:
        changed = create_sql.replace(before, after)
        if changed == create_sql:
            raise RuntimeError(f"unexpected constraint for {table}: {before}")
        create_sql = changed
    replacement_name = f"{table}_v24"
    connection.execute(f"DROP TABLE IF EXISTS {replacement_name}")
    connection.execute(create_sql)
    columns = [
        str(item[1])
        for item in connection.execute(f"PRAGMA table_info({table})").fetchall()
    ]
    copied_columns = ", ".join(columns)
    connection.execute(
        f"INSERT INTO {replacement_name} ({copied_columns}) "
        f"SELECT {copied_columns} FROM {table}"
    )
    connection.execute(f"DROP TABLE {table}")
    connection.execute(f"ALTER TABLE {replacement_name} RENAME TO {table}")
    for statement in index_sql:
        connection.execute(statement)


def install_schema(connection: sqlite3.Connection) -> None:
    """Install global schema 24 inside a caller-owned offline transaction."""

    for table in ("apify_actor_canary_batches", "apify_actor_pool_stages"):
        if "operation_slot" not in _column_names(connection, table):
            connection.execute(
                f"ALTER TABLE {table} ADD COLUMN operation_slot TEXT "
                "CHECK(operation_slot IN ('primary', 'backup_1', "
                "'backup_2') OR operation_slot IS NULL)"
            )
    _rebuild_table(
        connection,
        "apify_actor_canary_batches",
        replacements=((
            "'compatibility_single'",
            "'compatibility_single', 'add_slot', 'replace_slot'",
        ),),
        index_sql=(
            """CREATE INDEX idx_apify_actor_canary_batches_route
               ON apify_actor_canary_batches(
                   workspace_id, route_id, created_at DESC
               )""",
        ),
    )
    _rebuild_table(
        connection,
        "apify_actor_pool_stages",
        replacements=((
            "'compatibility_single'",
            "'compatibility_single', 'add_slot', 'replace_slot'",
        ),),
        index_sql=(
            """CREATE UNIQUE INDEX idx_apify_actor_pool_stages_active
               ON apify_actor_pool_stages(workspace_id, route_id)
               WHERE status NOT IN ('applied', 'stale', 'failed', 'cancelled')""",
        ),
    )


def bootstrap_fresh_schema(connection: sqlite3.Connection) -> None:
    """Finish a brand-new database with the global schema 24 marker."""

    install_schema(connection)
    mark_migrated(connection, commit=False)


def bootstrap_service_store_schema(
    connection: sqlite3.Connection,
    *,
    existing_schema: bool,
) -> None:
    """Apply schema-24 finishing work during ServiceStore bootstrap."""

    if not existing_schema:
        bootstrap_fresh_schema(connection)
