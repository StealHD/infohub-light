from __future__ import annotations

from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.services.worker_migration_gate import first_required_worker_startup_migration
from src.storage.apify_actor_auto_pool_schema import (
    install_schema as install_auto_pool_schema,
    mark_migrated as mark_auto_pool_migrated,
)
from src.storage.service_store import ServiceStore


def _ready_response(data_dir: Path, static_dir: Path):
    static_dir.mkdir(exist_ok=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    with TestClient(create_app(data_dir=data_dir, static_dir=static_dir)) as client:
        return client.get("/api/health/ready")


@pytest.mark.parametrize(
    ("version", "damage", "expected_worker_migration"),
    [
        (23, "marker", "apify_actor_resilience_v21"),
        (23, "checksum", "apify_actor_resilience_v21"),
        (23, "shape", "apify_actor_resilience_v21"),
        (24, "marker", "apify_actor_pool_management_v22"),
        (24, "checksum", "apify_actor_pool_management_v22"),
        (24, "shape", "apify_actor_pool_management_v22"),
    ],
)
def test_only_worker_is_gated_by_unretired_actor_schema_chain(
    tmp_path: Path,
    monkeypatch,
    version: int,
    damage: str,
    expected_worker_migration: str,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    if damage == "marker":
        store.connect().execute(
            "DELETE FROM schema_migrations WHERE version = ?", (version,)
        )
    elif damage == "checksum":
        store.connect().execute(
            "UPDATE schema_migrations SET checksum = 'corrupt' WHERE version = ?",
            (version,),
        )
    elif version == 23:
        store.connect().execute("DROP TABLE apify_actor_diagnostic_events")
    else:
        store.connect().execute(
            "ALTER TABLE apify_actor_pool_stages DROP COLUMN operation_slot"
        )
    store.connect().commit()
    store.close()

    gated = ServiceStore(data_dir)
    gated.initialize()
    assert first_required_worker_startup_migration(gated) == expected_worker_migration
    gated.close()
    monkeypatch.setenv("HORIZON_AUTH_USER", "schema-runtime-owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "safe-test-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "schema-runtime-secret")
    ready = _ready_response(data_dir, tmp_path / "static")
    assert ready.status_code == 200, ready.text


def test_global_25_is_inert_for_fresh_bootstrap_api_and_worker(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    store.create_user(
        workspace_id="default",
        username="schema-runtime-owner",
        password="safe-test-password",
        role="owner",
    )
    assert connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version = 25"
    ).fetchone() is None
    assert connection.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type = 'table' AND name = 'apify_actor_auto_pool_runs'"""
    ).fetchone() is None
    assert first_required_worker_startup_migration(store) is None
    store.close()
    assert _ready_response(data_dir, tmp_path / "static-missing").status_code == 200

    historical = ServiceStore(data_dir)
    historical_connection = historical.connect()
    historical_connection.execute("BEGIN IMMEDIATE")
    install_auto_pool_schema(historical_connection)
    mark_auto_pool_migrated(historical_connection, commit=False)
    historical_connection.commit()
    assert first_required_worker_startup_migration(historical) is None
    historical.close()
    assert _ready_response(data_dir, tmp_path / "static-present").status_code == 200
