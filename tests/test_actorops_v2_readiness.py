from __future__ import annotations

import pytest

from src.services.actorops.readiness import (
    actorops_v2_startup_migration_required,
    require_actorops_v2_schema,
)
from src.storage.actorops_v2_operator_schema import OPERATOR_TABLES
from src.storage.actorops_v2_single_track_schema import MIGRATION_VERSION
from src.storage.service_store import ServiceStore


def test_missing_global_30_is_always_migration_required(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    connection.execute(
        "DELETE FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,),
    )
    connection.commit()

    assert actorops_v2_startup_migration_required(store) is True
    with pytest.raises(RuntimeError, match="actorops_v2 migration_required"):
        require_actorops_v2_schema(store)
    store.close()


def test_global_30_requires_its_full_schema_shape(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(f"DROP TABLE {OPERATOR_TABLES[-1]}")
    connection.commit()
    connection.execute("PRAGMA foreign_keys = ON")

    assert actorops_v2_startup_migration_required(store) is True
    with pytest.raises(RuntimeError, match="actorops_v2 migration_required"):
        require_actorops_v2_schema(store)
    store.close()
