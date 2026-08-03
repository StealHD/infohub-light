from __future__ import annotations

import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

from fastapi.testclient import TestClient

from scripts.migrate_apify_actor_routing_v13 import (
    migrate_apify_actor_routing_v13,
)
from scripts.migrate_apify_actor_ops_v15 import (
    V15_INDEXES,
    V15_TRIGGERS,
)
from src.api.server import create_app
from src.services.worker import run_worker_once
from src.storage.service_store import ServiceStore


def _downgrade_to_v12(data_dir) -> None:
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    connection.execute("PRAGMA foreign_keys = OFF")
    # Empty databases install the latest schema. Remove the later ActorOps
    # layer before reconstructing a faithful v12 fixture for this older
    # migration test.
    for trigger in V15_TRIGGERS:
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    for table in (
        "apify_actor_validations",
        "apify_actor_discovery_run_revisions",
        "apify_route_active_slots",
        "apify_source_route_bindings",
        "apify_actor_discovery_runs",
        "apify_actor_discovery_settings",
        "apify_actor_metadata_observations",
        "apify_actor_adapter_revisions",
        "apify_actor_route_profiles",
    ):
        connection.execute(f"DROP TABLE {table}")
    for index in V15_INDEXES:
        connection.execute(f"DROP INDEX IF EXISTS {index}")
    connection.execute("DELETE FROM schema_migrations WHERE version = 17")
    for table in (
        "apify_actor_alert_deliveries",
        "apify_actor_alert_incidents",
        "apify_actor_alert_settings",
        "apify_actor_target_health",
        "apify_actor_attempts",
        "apify_actor_candidates",
        "apify_actor_routes",
    ):
        connection.execute(f"DROP TABLE {table}")
    for column in (
        "charge_reserved_usd",
        "charge_actual_usd",
        "charge_final",
    ):
        connection.execute(
            f"ALTER TABLE apify_actor_runs DROP COLUMN {column}"
        )
    connection.execute("DELETE FROM schema_migrations WHERE version = 13")
    connection.commit()
    store.close()


def test_apify_actor_routing_v13_dry_run_does_not_create_database(tmp_path):
    result = migrate_apify_actor_routing_v13(
        data_dir=tmp_path / "data",
        backup_dir=tmp_path / "backups",
        apply=False,
    )

    assert result == {
        "applied": False,
        "database_exists": False,
        "migrated": False,
        "backup_path": None,
    }
    assert not (tmp_path / "data" / "service.db").exists()


def test_apify_actor_routing_v13_backs_up_and_seeds_routes(tmp_path):
    data_dir = tmp_path / "data"
    _downgrade_to_v12(data_dir)

    result = migrate_apify_actor_routing_v13(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )

    assert result["applied"] is True
    assert result["route_count"] == 1
    assert result["candidate_count"] == 3
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_errors"] == 0
    assert result["backup_path"]
    assert os.stat(result["backup_path"]).st_mode & 0o777 == 0o600

    connection = sqlite3.connect(data_dir / "service.db")
    try:
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 13"
        ).fetchone()
        assert connection.execute(
            "SELECT COUNT(*) FROM apify_actor_alert_settings"
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_apify_actor_routing_v13_cli_imports_its_own_checkout(tmp_path):
    script = (
        Path(__file__).resolve().parents[1]
        / "scripts"
        / "migrate_apify_actor_routing_v13.py"
    )
    environment = dict(os.environ)
    environment["PYTHONPATH"] = ""

    completed = subprocess.run(
        [
            sys.executable,
            str(script),
            "--data-dir",
            str(tmp_path / "data"),
            "--backup-dir",
            str(tmp_path / "backups"),
            "--apply",
        ],
        cwd=tmp_path,
        env=environment,
        check=True,
        capture_output=True,
        text=True,
    )

    result = json.loads(completed.stdout)
    assert result["applied"] is True
    assert result["migrated"] is True
    assert result["route_count"] == 1
    assert result["candidate_count"] == 3


def test_existing_v12_database_requires_explicit_v13_apply(
    tmp_path,
    monkeypatch,
):
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    _downgrade_to_v12(data_dir)

    reopened = ServiceStore(data_dir)
    reopened.initialize()
    assert reopened.apify_actor_routing_v13_migration_required() is True
    assert reopened.connect().execute(
        """
        SELECT 1 FROM sqlite_master
        WHERE type = 'table' AND name = 'apify_actor_routes'
        """
    ).fetchone() is None
    columns = {
        str(row["name"])
        for row in reopened.connect().execute(
            "PRAGMA table_info(apify_actor_runs)"
        ).fetchall()
    }
    assert "charge_reserved_usd" not in columns
    reopened.close()

    client = TestClient(create_app(data_dir=data_dir, static_dir=static_dir))
    ready = client.get("/api/health/ready")
    assert ready.status_code == 503
    assert ready.json()["error"]["code"] == "migration_required"
    assert "Apify Actor routing v13" in ready.json()["error"]["message"]

    worker = run_worker_once(
        data_dir=str(data_dir),
        worker_id="v13-gated-worker",
    )
    assert worker == {
        "ok": False,
        "error_code": "migration_required",
        "migration": "apify_actor_routing_v13",
    }
    check = sqlite3.connect(data_dir / "service.db")
    try:
        assert check.execute(
            """
            SELECT 1 FROM sqlite_master
            WHERE type = 'table' AND name = 'apify_actor_routes'
            """
        ).fetchone() is None
    finally:
        check.close()
