from __future__ import annotations

import os
from pathlib import Path

from scripts.migrate_actorops_v2_sampling import migrate
from src.storage.actorops_v2_sampling_schema import (
    MIGRATION_VERSION,
    migration_marker_exists,
    schema_shapes_valid,
)
from src.storage.service_store import ServiceStore


def test_global_35_sampling_migration_is_explicit_and_repeatable(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    connection.execute(
        "DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    )
    connection.execute("DROP TABLE actor_candidate_sampling_plans_v2")
    connection.commit()
    store.close()

    assert migrate(data_dir, apply=False)["status"] == "migration_required"
    result = migrate(data_dir, apply=True)
    assert result["status"] == "applied"
    assert result["sampling_plan_tables_created"] == 1
    assert result["backup_mode"] == "0o600"
    assert (os.stat(result["backup"]).st_mode & 0o777) == 0o600
    assert migrate(data_dir, apply=True)["status"] == "already_migrated"

    store = ServiceStore(data_dir)
    assert migration_marker_exists(store.connect())
    assert schema_shapes_valid(store.connect())
    store.close()
