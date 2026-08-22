from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import scripts.repair_actorops_v2_catalog_bindings as repair_module
from scripts.migrate_actorops_v2 import migrate
from src.apify_actor_identity import source_target_fingerprint
from src.storage.actorops_v2_schema import V2_TABLES
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _drop_v2(store: ServiceStore) -> None:
    connection = store.connect()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for table in reversed(V2_TABLES):
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        connection.execute("DELETE FROM schema_migrations WHERE version = 26")
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _unbound_instagram_source(store: ServiceStore, *, target: str = "openai") -> str:
    return store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Instagram catalog source",
        config={"platform": "instagram", "kind": "profile", "target": target},
        source_key=f"instagram:{target}",
    )


def test_v24_migration_backfills_unbound_catalog_social_source(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    source_id = _unbound_instagram_source(store)
    route_id = str(store.connect().execute(
        "SELECT route_id FROM apify_actor_route_profiles WHERE platform='instagram'"
    ).fetchone()[0])
    _drop_v2(store)
    store.close()

    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["backfill_counts"]["bindings"] == 1
    migrated = ServiceStore(data_dir)
    binding = migrated.connect().execute(
        """SELECT route_id, target_fingerprint, status, source_v1_generation
           FROM actor_source_bindings_v2 WHERE source_id=?""",
        (source_id,),
    ).fetchone()
    assert tuple(binding) == (
        route_id,
        source_target_fingerprint(
            DEFAULT_WORKSPACE_ID, route_id, "openai", platform="instagram"
        ),
        "pending",
        1,
    )
    assert migrated.connect().execute(
        "SELECT COUNT(*) FROM apify_source_route_bindings WHERE source_id=?",
        (source_id,),
    ).fetchone()[0] == 0
    migrated.close()


def test_repair_refuses_single_track_schema_without_writing(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _unbound_instagram_source(store)
    database = data_dir / "service.db"
    store.close()
    before = database.read_bytes()

    with pytest.raises(repair_module.CatalogBindingRepairError, match="actorops_v1_retired"):
        repair_module.repair(data_dir, apply=False)
    assert database.read_bytes() == before


def test_repair_single_track_refusal_hides_catalog_target(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _unbound_instagram_source(store, target="https://example.test/not-instagram")
    database = data_dir / "service.db"
    store.close()
    before = database.read_bytes()

    with pytest.raises(repair_module.CatalogBindingRepairError, match="actorops_v1_retired"):
        repair_module.repair(data_dir, apply=False)
    assert database.read_bytes() == before


def test_repair_never_queries_global_25(tmp_path: Path, monkeypatch: pytest.MonkeyPatch) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _unbound_instagram_source(store)
    store.close()
    statements: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(repair_module.sqlite3, "connect", traced_connect)
    with pytest.raises(repair_module.CatalogBindingRepairError, match="actorops_v1_retired"):
        repair_module.repair(data_dir, apply=False)
    joined = "\n".join(statements).casefold()
    assert "version = 25" not in joined
    assert "apify_actor_auto_pool_runs" not in joined
