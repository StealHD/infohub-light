"""Global schema 25 helpers for automated Actor slot replacement.

Kept outside :mod:`service_store` so this new ActorOps behavior does not
extend the legacy storage façade.  It installs one table that tracks a
bounded, self-advancing ``discovery -> paid canary -> activation`` loop for a
single slot operation (add or replace), including its spend ledger.
"""

from __future__ import annotations

import re
import sqlite3
from datetime import datetime, timezone


APIFY_ACTOR_AUTO_POOL_MIGRATION_VERSION = 25
APIFY_ACTOR_AUTO_POOL_MIGRATION_NAME = "apify_actor_auto_pool_v25"
APIFY_ACTOR_AUTO_POOL_MIGRATION_CHECKSUM = (
    "apify-actor-auto-pool-v25-bounded-slot-replacement"
)


def _normalized_schema_sql(value: object) -> str:
    return re.sub(r"\s+", "", str(value or "").casefold())


def apify_actor_auto_pool_v25_schema_shapes_valid(
    connection: sqlite3.Connection,
) -> bool:
    from .service_store import apify_actor_resilience_v21_schema_shapes_valid

    if not apify_actor_resilience_v21_schema_shapes_valid(connection):
        return False
    sql = {
        str(row[0]): _normalized_schema_sql(row[1])
        for row in connection.execute(
            "SELECT name, sql FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    table_sql = sql.get("apify_actor_auto_pool_runs", "")
    return all(
        fragment in table_sql
        for fragment in (
            "run_id",
            "slot_name",
            "goal",
            "status",
            "budget_cap_usd",
            "total_spent_usd",
            "last_discovery_run_id",
            "last_canary_batch_id",
        )
    )


def migration_marker_exists(connection: sqlite3.Connection) -> bool:
    return bool(
        connection.execute(
            """SELECT 1 FROM schema_migrations
               WHERE version = ? AND name = ? AND checksum = ?""",
            (
                APIFY_ACTOR_AUTO_POOL_MIGRATION_VERSION,
                APIFY_ACTOR_AUTO_POOL_MIGRATION_NAME,
                APIFY_ACTOR_AUTO_POOL_MIGRATION_CHECKSUM,
            ),
        ).fetchone()
    )


def migration_required(connection: sqlite3.Connection) -> bool:
    return not (
        migration_marker_exists(connection)
        and apify_actor_auto_pool_v25_schema_shapes_valid(connection)
    )


def mark_migrated(
    connection: sqlite3.Connection,
    *,
    commit: bool = True,
) -> None:
    existing = connection.execute(
        "SELECT name FROM schema_migrations WHERE version = ?",
        (APIFY_ACTOR_AUTO_POOL_MIGRATION_VERSION,),
    ).fetchone()
    if existing is not None and str(existing["name"]) != (
        APIFY_ACTOR_AUTO_POOL_MIGRATION_NAME
    ):
        raise RuntimeError("global schema migration version 25 is already occupied")
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
            APIFY_ACTOR_AUTO_POOL_MIGRATION_VERSION,
            APIFY_ACTOR_AUTO_POOL_MIGRATION_NAME,
            APIFY_ACTOR_AUTO_POOL_MIGRATION_CHECKSUM,
            datetime.now(timezone.utc).isoformat(),
        ),
    )
    if commit:
        connection.commit()


def install_schema(connection: sqlite3.Connection) -> None:
    """Install the auto-pool ledger inside a caller-owned offline transaction."""

    connection.execute(
        """
        CREATE TABLE IF NOT EXISTS apify_actor_auto_pool_runs (
            run_id TEXT PRIMARY KEY,
            workspace_id TEXT NOT NULL,
            route_id TEXT NOT NULL,
            slot_name TEXT NOT NULL
                CHECK(slot_name IN ('primary', 'backup_1', 'backup_2')),
            goal TEXT NOT NULL
                CHECK(goal IN ('add_slot', 'replace_slot')),
            status TEXT NOT NULL
                CHECK(status IN ('running', 'succeeded', 'budget_exhausted',
                                 'failed', 'cancelled')),
            budget_cap_usd REAL NOT NULL
                CHECK(budget_cap_usd > 0),
            total_spent_usd REAL NOT NULL DEFAULT 0
                CHECK(total_spent_usd >= 0),
            last_discovery_run_id TEXT,
            last_canary_batch_id TEXT,
            error_code TEXT,
            created_by_user_id TEXT,
            created_at TEXT NOT NULL,
            updated_at TEXT NOT NULL
        )
        """
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_apify_actor_auto_pool_runs_route
           ON apify_actor_auto_pool_runs(workspace_id, route_id, updated_at DESC)"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_apify_actor_auto_pool_runs_discovery
           ON apify_actor_auto_pool_runs(last_discovery_run_id)"""
    )
    connection.execute(
        """CREATE INDEX IF NOT EXISTS idx_apify_actor_auto_pool_runs_canary
           ON apify_actor_auto_pool_runs(last_canary_batch_id)"""
    )


def bootstrap_fresh_schema(connection: sqlite3.Connection) -> None:
    install_schema(connection)
    mark_migrated(connection, commit=False)


def bootstrap_service_store_schema(
    connection: sqlite3.Connection,
    *,
    existing_schema: bool,
) -> None:
    if not existing_schema:
        bootstrap_fresh_schema(connection)
