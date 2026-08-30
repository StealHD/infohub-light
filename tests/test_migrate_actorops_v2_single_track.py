"""Offline global 30 coverage for the final ActorOps v2 schema."""

from __future__ import annotations

import sqlite3
import re
from pathlib import Path

from scripts.migrate_actorops_v2_single_track import migrate, preview
from src.storage.actorops_v2_single_track_schema import (
    MIGRATION_CHECKSUM,
    MIGRATION_NAME,
    MIGRATION_VERSION,
    migration_marker_exists,
    schema_shapes_valid,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from tests.test_actorops_v1_retirement_boundary import (
    HISTORICAL_ACTOROPS_V1_TABLES,
)


def _columns(connection: sqlite3.Connection, table: str) -> set[str]:
    return {str(row[1]) for row in connection.execute(f"PRAGMA table_info({table})")}


def _runtime_mode_sql(connection: sqlite3.Connection) -> str:
    row = connection.execute(
        "SELECT sql FROM sqlite_master WHERE type='table' AND name='actor_routes_v2'"
    ).fetchone()
    return re.sub(r"\s+", "", str(row[0])).casefold()


def _restore_pre_global_30_shape(connection: sqlite3.Connection) -> None:
    """Build the pre-30 v2 table shape without using any historical schema DDL."""

    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        connection.executescript(
            """
            CREATE TABLE actor_routes_v2_pre30 (
                route_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                platform TEXT NOT NULL, target_type TEXT NOT NULL,
                capability TEXT NOT NULL,
                runtime_mode TEXT NOT NULL CHECK(runtime_mode IN ('disabled','shadow','active')),
                per_run_cap_usd REAL NOT NULL, generation INTEGER NOT NULL,
                source_v1_generation INTEGER NOT NULL,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, route_id),
                UNIQUE(workspace_id, platform, target_type, capability)
            );
            CREATE TABLE actor_source_bindings_v2_pre30 (
                binding_id TEXT PRIMARY KEY, workspace_id TEXT NOT NULL,
                source_id TEXT NOT NULL, route_id TEXT NOT NULL,
                target_fingerprint TEXT NOT NULL, status TEXT NOT NULL,
                binding_version INTEGER NOT NULL, source_v1_generation INTEGER NOT NULL,
                preferred_candidate_id TEXT, last_known_good_candidate_id TEXT,
                last_success_at TEXT, watermark_latest_published_at TEXT,
                watermark_item_id_hash TEXT, watermark_last_advanced_at TEXT,
                created_at TEXT NOT NULL, updated_at TEXT NOT NULL,
                UNIQUE(workspace_id, source_id), UNIQUE(workspace_id, binding_id)
            );
            """
        )
        connection.execute(
            """INSERT INTO actor_routes_v2_pre30
               SELECT route_id, workspace_id, platform, target_type, capability,
                      runtime_mode, per_run_cap_usd, generation, 1, created_at, updated_at
                 FROM actor_routes_v2"""
        )
        connection.execute(
            """INSERT INTO actor_source_bindings_v2_pre30
               SELECT binding_id, workspace_id, source_id, route_id, target_fingerprint,
                      status, binding_version, 1, preferred_candidate_id,
                      last_known_good_candidate_id, last_success_at,
                      watermark_latest_published_at, watermark_item_id_hash,
                      watermark_last_advanced_at, created_at, updated_at
                 FROM actor_source_bindings_v2"""
        )
        connection.execute("DROP TABLE actor_source_bindings_v2")
        connection.execute("DROP TABLE actor_routes_v2")
        connection.execute("ALTER TABLE actor_routes_v2_pre30 RENAME TO actor_routes_v2")
        connection.execute(
            "ALTER TABLE actor_source_bindings_v2_pre30 RENAME TO actor_source_bindings_v2"
        )
        connection.execute("DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,))
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys=ON")


def test_global_30_rebuilds_v2_tables_and_normalizes_shadow_routes(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    route_id = str(connection.execute("SELECT route_id FROM actor_routes_v2 LIMIT 1").fetchone()[0])
    _restore_pre_global_30_shape(connection)
    connection.execute(
        "UPDATE actor_routes_v2 SET runtime_mode='shadow' WHERE route_id=?",
        (route_id,),
    )
    connection.commit()
    store.close()

    assert preview(data_dir)["status"] == "migration_required"
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["status"] == "applied"
    assert result["shadow_routes_disabled"] == 1
    connection = sqlite3.connect(data_dir / "service.db")
    try:
        marker = connection.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version=?",
            (MIGRATION_VERSION,),
        ).fetchone()
        assert marker == (MIGRATION_NAME, MIGRATION_CHECKSUM)
        assert _columns(connection, "actor_routes_v2").isdisjoint({"source_v1_generation"})
        assert _columns(connection, "actor_source_bindings_v2").isdisjoint({"source_v1_generation"})
        assert "check(runtime_modein('active','disabled'))" in _runtime_mode_sql(connection)
        assert connection.execute(
            "SELECT runtime_mode FROM actor_routes_v2 WHERE route_id=?", (route_id,)
        ).fetchone() == ("disabled",)
        triggers = {
            str(row[0]) for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='trigger'"
            )
        }
        assert {
            "trg_actor_bindings_v2_candidate_route",
            "trg_actor_routes_v2_generation",
        } <= triggers
        assert migration_marker_exists(connection)
        assert schema_shapes_valid(connection)
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()

    again = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert again["status"] == "already_migrated"


def test_fresh_store_seeds_v2_routes_with_safe_default_maintenance(
    tmp_path: Path,
) -> None:
    store = ServiceStore(tmp_path / "fresh")
    store.initialize()
    connection = store.connect()
    try:
        assert migration_marker_exists(connection)
        assert schema_shapes_valid(connection)
        routes = connection.execute(
            """SELECT platform, target_type, capability, runtime_mode, per_run_cap_usd
               FROM actor_routes_v2 WHERE workspace_id=?
               ORDER BY platform""",
            (DEFAULT_WORKSPACE_ID,),
        ).fetchall()
        assert [tuple(row) for row in routes] == [
            ("instagram", "profile", "items", "disabled", 0.02),
            ("x", "profile", "items", "disabled", 0.02),
            ("youtube", "channel", "items", "disabled", 0.02),
        ]
        policies = connection.execute(
            """SELECT route_id, enabled, authorization_origin,
                      auto_replace_non_last
                 FROM actor_maintenance_policies_v2
               WHERE workspace_id=? ORDER BY route_id""",
            (DEFAULT_WORKSPACE_ID,),
        ).fetchall()
        assert len(policies) == 4
        assert all(int(row["enabled"]) == 1 for row in policies)
        assert all(
            row["authorization_origin"] == "system_default" for row in policies
        )
        workspace_policy = next(
            row for row in policies if row["route_id"] is None
        )
        route_policies = [
            row for row in policies if row["route_id"] is not None
        ]
        assert workspace_policy["auto_replace_non_last"] is None
        assert route_policies
        assert all(
            row["auto_replace_non_last"] == 1 for row in route_policies
        )
        installed_tables = {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table'"
            )
        }
        assert installed_tables.isdisjoint(HISTORICAL_ACTOROPS_V1_TABLES)
        assert {
            "apify_actor_runs",
            "apify_key_pool_state",
            "apify_actor_alert_settings",
            "apify_actor_alert_incidents",
            "apify_actor_alert_deliveries",
        } <= installed_tables
    finally:
        store.close()
