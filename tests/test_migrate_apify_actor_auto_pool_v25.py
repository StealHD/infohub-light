from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.migrate_apify_actor_auto_pool_v25 import migrate
from src.storage.apify_actor_auto_pool_schema import (
    apify_actor_auto_pool_v25_schema_shapes_valid,
    migration_marker_exists,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def test_v25_historical_migration_is_explicit_backed_up_and_idempotent(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    assert store.connect().execute(
        "SELECT 1 FROM schema_migrations WHERE version = 25"
    ).fetchone() is None
    store.close()

    assert migrate(data_dir, apply=False)["required"] is True
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert result["applied"] is True
    assert result["backup_mode"] == "0o600"
    assert os.stat(result["backup"]).st_mode & 0o777 == 0o600

    migrated = ServiceStore(data_dir)
    assert migration_marker_exists(migrated.connect())
    assert apify_actor_auto_pool_v25_schema_shapes_valid(migrated.connect())
    migrated.close()
    assert migrate(data_dir, apply=True)["already_migrated"] is True


@pytest.mark.parametrize("damage", ["marker", "checksum", "shape"])
def test_v25_requires_exact_global_24_marker_and_shape(
    tmp_path: Path, damage: str
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    if damage == "marker":
        store.connect().execute("DELETE FROM schema_migrations WHERE version = 24")
    elif damage == "checksum":
        store.connect().execute(
            "UPDATE schema_migrations SET checksum = 'corrupt' WHERE version = 24"
        )
    else:
        store.connect().execute(
            "ALTER TABLE apify_actor_pool_stages DROP COLUMN operation_slot"
        )
    store.connect().commit()
    store.close()

    with pytest.raises(RuntimeError, match="pool_management_v22"):
        migrate(data_dir, apply=False)


def test_v25_refuses_active_actor_work_before_backup(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="v25-history-owner",
        password="safe-test-password",
        role="owner",
    )
    store.connect().execute(
        """INSERT INTO fetch_jobs (
               id, workspace_id, user_id, job_type, status, payload_json,
               created_at, updated_at
           ) VALUES ('v25-history-active', ?, ?, 'apify_actor_canary_batch',
                     'running', '{}', '2030-01-01T00:00:00+00:00',
                     '2030-01-01T00:00:00+00:00')""",
        (DEFAULT_WORKSPACE_ID, owner["id"]),
    )
    store.connect().commit()
    store.close()

    with pytest.raises(RuntimeError, match="active ActorOps jobs"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert not (tmp_path / "backups").exists()
