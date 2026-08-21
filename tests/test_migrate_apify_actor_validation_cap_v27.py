from __future__ import annotations

import re
import sqlite3
from pathlib import Path

import pytest

from scripts.migrate_apify_actor_validation_cap_v27 import migrate
from src.services.apify_actor_ops import ActorOpsError, ApifyActorOpsService
from src.storage.apify_actor_validation_cap_v27_schema import (
    migration_marker_exists,
    migration_required,
    schema_shapes_valid,
)
from src.storage.service_store import ServiceStore
from test_apify_actor_pool_staging_v18 import _route


_DOWNGRADE_REPLACEMENTS = {
    "apify_actor_pool_stage_candidate_settings": ((
        "max_charge_usd <= 0.20", "max_charge_usd <= 0.10"
    ),),
    "apify_actor_canary_batches": (
        ("max_total_charge_usd <= 0.60", "max_total_charge_usd <= 0.30"),
        ("per_candidate_cap_usd <= 0.20", "per_candidate_cap_usd <= 0.10"),
    ),
    "apify_actor_canary_batch_items": ((
        "authorized_cap_usd <= 0.20", "authorized_cap_usd <= 0.10"
    ),),
}


def _downgrade_to_v26_shape(store: ServiceStore) -> None:
    connection = store.connect()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for table in (
            "apify_actor_pool_stage_candidate_settings",
            "apify_actor_canary_batch_items",
            "apify_actor_canary_batches",
        ):
            row = connection.execute(
                "SELECT sql FROM sqlite_master WHERE type = 'table' AND name = ?",
                (table,),
            ).fetchone()
            create_sql = str(row["sql"])
            for before, after in _DOWNGRADE_REPLACEMENTS[table]:
                create_sql = create_sql.replace(before, after)
            temporary = f"{table}_test_old_cap"
            create_sql, count = re.subn(
                rf'^CREATE\s+TABLE\s+(?:"?{re.escape(table)}"?)',
                f"CREATE TABLE {temporary}",
                create_sql,
                count=1,
                flags=re.IGNORECASE,
            )
            assert count == 1
            objects = connection.execute(
                """SELECT sql FROM sqlite_master
                   WHERE tbl_name = ? AND type IN ('index', 'trigger')
                     AND sql IS NOT NULL ORDER BY type, name""",
                (table,),
            ).fetchall()
            columns = ", ".join(
                str(item[1])
                for item in connection.execute(f"PRAGMA table_info({table})")
            )
            connection.execute(create_sql)
            connection.execute(
                f"INSERT INTO {temporary} ({columns}) SELECT {columns} FROM {table}"
            )
            connection.execute(f"DROP TABLE {table}")
            connection.execute(f"ALTER TABLE {temporary} RENAME TO {table}")
            for item in objects:
                connection.execute(str(item["sql"]))
        connection.execute("DELETE FROM schema_migrations WHERE version = 27")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def test_v27_migration_rebuilds_cost_constraints_and_is_idempotent(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    assert migration_marker_exists(store.connect()) is True
    assert schema_shapes_valid(store.connect()) is True
    _downgrade_to_v26_shape(store)
    assert migration_required(store.connect()) is True
    store.close()

    assert migrate(data_dir, apply=False)["required"] is True
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert result["applied"] is True
    assert result["backup_mode"] == "0o600"

    reopened = ServiceStore(data_dir)
    reopened.initialize()
    assert migration_marker_exists(reopened.connect()) is True
    assert schema_shapes_valid(reopened.connect()) is True
    reopened.close()
    assert migrate(data_dir, apply=True)["already_migrated"] is True


def test_v27_migration_is_required_before_a_route_can_use_twenty_cents(tmp_path: Path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    _downgrade_to_v26_shape(store)
    ops = ApifyActorOpsService(store)
    route = _route(store, "youtube/channel/items")
    with pytest.raises(ActorOpsError, match="cost-cap migration"):
        ops.set_route_price_cap(
            str(route["route_id"]),
            per_run_cap_usd=0.20,
            expected_generation=int(route["generation"]),
        )
