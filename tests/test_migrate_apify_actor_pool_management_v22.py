from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.migrate_apify_actor_pool_management_v22 import migrate
from scripts.migrate_apify_actor_validation_tuning_v20 import _rebuild_table
from src.storage.service_store import (
    DEFAULT_WORKSPACE_ID,
    ServiceStore,
)
from src.services.apify_actor_pool_management_runtime import (
    actor_pool_management_migration_required,
)
from src.storage.apify_actor_pool_management_schema import (
    apify_actor_pool_management_v22_schema_shapes_valid,
)


def _downgrade_to_v21_shape(store: ServiceStore) -> None:
    connection = store.connect()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for table, index_sql in (
            (
                "apify_actor_canary_batches",
                """CREATE INDEX idx_apify_actor_canary_batches_route
                   ON apify_actor_canary_batches(
                       workspace_id, route_id, created_at DESC
                   )""",
            ),
            (
                "apify_actor_pool_stages",
                """CREATE UNIQUE INDEX idx_apify_actor_pool_stages_active
                   ON apify_actor_pool_stages(workspace_id, route_id)
                   WHERE status NOT IN ('applied', 'stale', 'failed', 'cancelled')""",
            ),
        ):
            _rebuild_table(
                connection,
                table,
                replacements=((
                    "'compatibility_single', 'add_slot', 'replace_slot'",
                    "'compatibility_single'",
                ),),
                index_sql=(index_sql,),
            )
            connection.execute(
                f"ALTER TABLE {table} DROP COLUMN operation_slot"
            )
        connection.execute("DELETE FROM schema_migrations WHERE version = 24")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def test_v22_migration_backups_restores_shape_and_is_idempotent(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _downgrade_to_v21_shape(store)
    store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="pool-v22-migration-owner",
        password="safe-test-password",
        role="owner",
    )
    store.close()

    gated = ServiceStore(data_dir)
    gated.initialize()
    assert actor_pool_management_migration_required(gated) is True
    assert "operation_slot" not in {
        str(row[1])
        for row in gated.connect().execute(
            "PRAGMA table_info(apify_actor_pool_stages)"
        ).fetchall()
    }
    gated.close()

    assert migrate(data_dir, apply=False)["required"] is True
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert result["applied"] is True
    assert result["backup_mode"] == "0o600"
    assert Path(result["backup"]).stat().st_mode & 0o777 == 0o600

    migrated = ServiceStore(data_dir)
    migrated.initialize()
    assert actor_pool_management_migration_required(migrated) is False
    assert apify_actor_pool_management_v22_schema_shapes_valid(migrated.connect())
    migrated.close()
    assert migrate(data_dir, apply=True)["already_migrated"] is True


def test_v22_migration_refuses_active_actor_work(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _downgrade_to_v21_shape(store)
    store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="pool-v22-active-owner",
        password="safe-test-password",
        role="owner",
    )
    store.connect().execute(
        """INSERT INTO fetch_jobs (
               id, workspace_id, user_id, job_type, status, payload_json,
               created_at, updated_at
           ) SELECT 'pool-v22-active', workspace_id, id,
                    'apify_actor_discovery', 'running', '{}',
                    '2030-01-01T00:00:00+00:00', '2030-01-01T00:00:00+00:00'
           FROM users LIMIT 1"""
    )
    store.connect().commit()
    store.close()

    try:
        migrate(data_dir, apply=True)
    except RuntimeError as exc:
        assert "active ActorOps jobs" in str(exc)
    else:
        raise AssertionError("migration should reject active ActorOps work")
