from __future__ import annotations

from pathlib import Path

from scripts.migrate_actorops_v2_verified_replacement import migrate
from src.storage.actorops_v2_verified_replacement_schema import (
    MIGRATION_VERSION,
    migration_marker_exists,
    schema_shapes_valid,
)
from src.storage.service_store import ServiceStore


def test_fresh_store_enables_only_proof_gated_route_replacement(tmp_path: Path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()

    assert migration_marker_exists(connection)
    assert schema_shapes_valid(connection)
    rows = connection.execute(
        """SELECT auto_replace_non_last, authorization_origin
           FROM actor_maintenance_policies_v2 WHERE route_id IS NOT NULL"""
    ).fetchall()
    assert rows
    assert all(tuple(row) == (1, "system_default") for row in rows)
    store.close()


def test_global_36_preserves_operator_policy_and_enables_untouched_routes(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    route_ids = [str(row[0]) for row in connection.execute(
        "SELECT route_id FROM actor_maintenance_policies_v2 "
        "WHERE route_id IS NOT NULL ORDER BY route_id"
    )]
    assert len(route_ids) >= 2
    connection.execute(
        "DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    )
    connection.execute(
        "UPDATE actor_maintenance_policies_v2 "
        "SET auto_replace_non_last=0 WHERE route_id IS NOT NULL"
    )
    connection.execute(
        """UPDATE actor_maintenance_policies_v2
           SET authorization_origin='operator' WHERE route_id=?""",
        (route_ids[0],),
    )
    connection.commit()
    store.close()

    assert migrate(data_dir, apply=False)["status"] == "migration_required"
    result = migrate(data_dir, apply=True)

    assert result["status"] == "applied"
    store = ServiceStore(data_dir)
    rows = store.connect().execute(
        """SELECT route_id,auto_replace_non_last,authorization_origin
           FROM actor_maintenance_policies_v2 WHERE route_id IS NOT NULL
           ORDER BY route_id"""
    ).fetchall()
    assert tuple(rows[0]) == (route_ids[0], 0, "operator")
    assert all(row["auto_replace_non_last"] == 1 for row in rows[1:])
    store.close()
