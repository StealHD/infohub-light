"""Global schema 27 for the explicit ActorOps validation cost ceiling."""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone


APIFY_ACTOR_VALIDATION_CAP_MIGRATION_VERSION = 27
APIFY_ACTOR_VALIDATION_CAP_MIGRATION_NAME = "apify_actor_validation_cap_v27"
APIFY_ACTOR_VALIDATION_CAP_MIGRATION_CHECKSUM = (
    "apify-actor-validation-cap-v27-twenty-cents"
)

_TABLE_CAP_REPLACEMENTS = {
    "apify_actor_pool_stage_candidate_settings": ((
        r"max_charge_usd\s*<=\s*0\.10", "max_charge_usd <= 0.20"
    ),),
    "apify_actor_canary_batches": (
        (r"max_total_charge_usd\s*<=\s*0\.30", "max_total_charge_usd <= 0.60"),
        (r"per_candidate_cap_usd\s*<=\s*0\.10", "per_candidate_cap_usd <= 0.20"),
    ),
    "apify_actor_canary_batch_items": ((
        r"authorized_cap_usd\s*<=\s*0\.10", "authorized_cap_usd <= 0.20"
    ),),
}


def _normalized_schema_sql(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").casefold())


def schema_shapes_valid(connection: sqlite3.Connection) -> bool:
    sql = {
        str(row[0]): _normalized_schema_sql(row[1])
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
        )
    }
    return (
        "max_charge_usd<=0.20"
        in sql.get("apify_actor_pool_stage_candidate_settings", "")
        and "max_total_charge_usd<=0.60"
        in sql.get("apify_actor_canary_batches", "")
        and "per_candidate_cap_usd<=0.20"
        in sql.get("apify_actor_canary_batches", "")
        and "authorized_cap_usd<=0.20"
        in sql.get("apify_actor_canary_batch_items", "")
    )


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(
        connection.execute(
            """SELECT 1 FROM schema_migrations
               WHERE version = ? AND name = ? AND checksum = ?""",
            (
                APIFY_ACTOR_VALIDATION_CAP_MIGRATION_VERSION,
                APIFY_ACTOR_VALIDATION_CAP_MIGRATION_NAME,
                APIFY_ACTOR_VALIDATION_CAP_MIGRATION_CHECKSUM,
            ),
        ).fetchone()
    )


def migration_required(connection: sqlite3.Connection) -> bool:
    return not (migration_marker_exists(connection) and schema_shapes_valid(connection))


def _table_sql(connection: sqlite3.Connection, table: str) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
    ).fetchone()
    if row is None or not row[0]:
        raise RuntimeError(f"missing required ActorOps table: {table}")
    return str(row[0])


def _rebuild_table(connection: sqlite3.Connection, table: str) -> None:
    create_sql = _table_sql(connection, table)
    for before, after in _TABLE_CAP_REPLACEMENTS[table]:
        create_sql, replacement_count = re.subn(before, after, create_sql, count=1)
        if replacement_count != 1:
            raise RuntimeError(f"unexpected validation-cap constraint: {table}")
    temporary = f"{table}_v27"
    if connection.execute(
        "SELECT 1 FROM sqlite_master WHERE name = ?", (temporary,)
    ).fetchone():
        raise RuntimeError(f"partial validation-cap rebuild exists: {temporary}")
    create_sql, table_count = re.subn(
        rf'^CREATE\s+TABLE\s+(?:"?{re.escape(table)}"?)',
        f"CREATE TABLE {temporary}",
        create_sql,
        count=1,
        flags=re.IGNORECASE,
    )
    if table_count != 1:
        raise RuntimeError(f"unexpected create statement: {table}")
    objects = connection.execute(
        """SELECT type, sql FROM sqlite_master
           WHERE tbl_name = ? AND type IN ('index', 'trigger') AND sql IS NOT NULL
           ORDER BY type, name""",
        (table,),
    ).fetchall()
    columns = [
        str(row[1])
        for row in connection.execute(f"PRAGMA table_info({table})").fetchall()
    ]
    if not columns:
        raise RuntimeError(f"missing columns for ActorOps table: {table}")
    copied_columns = ", ".join(columns)
    connection.execute(create_sql)
    connection.execute(
        f"INSERT INTO {temporary} ({copied_columns}) "
        f"SELECT {copied_columns} FROM {table}"
    )
    connection.execute(f"DROP TABLE {table}")
    connection.execute(f"ALTER TABLE {temporary} RENAME TO {table}")
    for row in objects:
        connection.execute(str(row[1]))


def install_schema(connection: sqlite3.Connection) -> None:
    """Upgrade the three bounded-cost tables inside an offline transaction."""

    if schema_shapes_valid(connection):
        return
    for table in (
        "apify_actor_pool_stage_candidate_settings",
        "apify_actor_canary_batch_items",
        "apify_actor_canary_batches",
    ):
        _rebuild_table(connection, table)
    if not schema_shapes_valid(connection):
        raise RuntimeError("ActorOps validation-cap schema shape is invalid")


def mark_migrated(connection: sqlite3.Connection, *, commit: bool = True) -> None:
    existing = connection.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version = ?",
        (APIFY_ACTOR_VALIDATION_CAP_MIGRATION_VERSION,),
    ).fetchone()
    if existing is not None and (
        str(existing["name"]) != APIFY_ACTOR_VALIDATION_CAP_MIGRATION_NAME
        or str(existing["checksum"]) != APIFY_ACTOR_VALIDATION_CAP_MIGRATION_CHECKSUM
    ):
        raise RuntimeError("global schema migration version 27 is already occupied")
    connection.execute(
        """INSERT INTO schema_migrations (version, name, checksum, applied_at)
           VALUES (?, ?, ?, ?) ON CONFLICT(version) DO NOTHING""",
        (
            APIFY_ACTOR_VALIDATION_CAP_MIGRATION_VERSION,
            APIFY_ACTOR_VALIDATION_CAP_MIGRATION_NAME,
            APIFY_ACTOR_VALIDATION_CAP_MIGRATION_CHECKSUM,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    if commit:
        connection.commit()


def bootstrap_fresh_schema(connection: sqlite3.Connection) -> None:
    install_schema(connection)
    mark_migrated(connection, commit=False)


def bootstrap_service_store_schema(
    connection: sqlite3.Connection, *, existing_schema: bool
) -> None:
    if not existing_schema:
        bootstrap_fresh_schema(connection)


__all__ = [
    "APIFY_ACTOR_VALIDATION_CAP_MIGRATION_CHECKSUM",
    "APIFY_ACTOR_VALIDATION_CAP_MIGRATION_NAME",
    "APIFY_ACTOR_VALIDATION_CAP_MIGRATION_VERSION",
    "bootstrap_service_store_schema",
    "install_schema",
    "mark_migrated",
    "migration_marker_exists",
    "migration_required",
    "schema_shapes_valid",
]
