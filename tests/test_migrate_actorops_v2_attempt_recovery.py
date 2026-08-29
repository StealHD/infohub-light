from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

import scripts.migrate_actorops_v2_attempt_recovery as migration_module
from scripts.migrate_actorops_v2_attempt_recovery import migrate
from src.storage.actorops_v2_attempt_recovery_schema import (
    MIGRATION_NAME,
    MIGRATION_VERSION,
    schema_shapes_valid,
)
from src.storage.actorops_v2_attempt_recovery_schema_sql import (
    REQUIRED_COLUMNS,
    REQUIRED_INDEXES,
    REQUIRED_TRIGGERS,
)
from src.storage.service_store import ServiceStore


def _downgrade_to_v28(store: ServiceStore) -> None:
    connection = store.connect()
    # Latest initialization includes the later revalidation transition trigger,
    # which references the v29 logical_job_id column.  A real v28 database did
    # not have that trigger, so remove it before dropping v29 columns.
    connection.execute(
        "DROP TRIGGER IF EXISTS trg_actor_candidates_v2_transition"
    )
    for trigger in REQUIRED_TRIGGERS:
        connection.execute(f"DROP TRIGGER {trigger}")
    for index in REQUIRED_INDEXES:
        connection.execute(f"DROP INDEX {index}")
    for column in REQUIRED_COLUMNS:
        connection.execute(f"ALTER TABLE actor_attempts_v2 DROP COLUMN {column}")
    connection.execute(
        "DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    )
    connection.commit()


def _prepare_v28(data_dir: Path) -> None:
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    route = connection.execute("SELECT route_id FROM actor_routes_v2 LIMIT 1").fetchone()
    candidate = connection.execute(
        "SELECT candidate_id FROM actor_candidates_v2 LIMIT 1"
    ).fetchone()
    if candidate is None:
        connection.execute(
            """INSERT INTO actor_candidates_v2 (
                   candidate_id, workspace_id, route_id, actor_id, publisher,
                   lifecycle, assignment_role, generation, created_at, updated_at
               ) VALUES ('legacy-candidate', 'default', ?, 'publisher/legacy',
                         'publisher', 'discovered', 'inactive', 1, ?, ?)""",
            (
                route[0],
                "2026-08-20T00:00:00+00:00",
                "2026-08-20T00:00:00+00:00",
            ),
        )
        candidate = ("legacy-candidate",)
    connection.execute(
            """INSERT INTO actor_attempts_v2 (
                   attempt_id, workspace_id, idempotency_key, route_id,
                   candidate_id, kind, attempt_group_id, attempt_index,
                   route_generation, target_fingerprint, status, reserved_usd,
                   cost_final, generation, created_at, updated_at,
                   logical_job_id, request_schema_version, request_fingerprint,
                   window_since, max_items, result_state
               ) VALUES ('legacy-attempt', 'default', 'legacy-key', ?, ?, 'probe',
                         'legacy-group', 0, 1, ?, 'created', 0, 0, 1, ?, ?,
                         'old-job', 2, 'old-request', ?, 1, 'pending')""",
            (
                route[0], candidate[0], "f" * 64,
                "2026-08-20T00:00:00+00:00",
                "2026-08-20T00:00:00+00:00",
                "2026-08-20T00:00:00+00:00",
            ),
        )
    connection.commit()
    _downgrade_to_v28(store)
    store.close()


def test_global_29_dry_run_apply_and_legacy_backfill(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _prepare_v28(data_dir)

    preview = migrate(data_dir, apply=False)
    assert preview["status"] == "migration_required"
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["status"] == "applied"
    assert result["backup_mode"] == "0o600"
    assert Path(result["backup"]).stat().st_mode & 0o777 == 0o600
    connection = sqlite3.connect(data_dir / "service.db")
    connection.row_factory = sqlite3.Row
    assert schema_shapes_valid(connection)
    assert connection.execute(
        "SELECT name FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    ).fetchone()[0] == MIGRATION_NAME
    row = connection.execute(
        """SELECT logical_job_id, request_schema_version, request_fingerprint
           FROM actor_attempts_v2 WHERE attempt_id='legacy-attempt'"""
    ).fetchone()
    assert tuple(row) == ("legacy:legacy-attempt", 1, "legacy:legacy-key")
    connection.close()
    assert migrate(data_dir, apply=True)["status"] == "already_migrated"


def test_global_29_restores_backup_after_failed_postcheck(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    _prepare_v28(data_dir)
    monkeypatch.setattr(migration_module, "schema_shapes_valid", lambda _db: False)

    with pytest.raises(RuntimeError, match="post-migration checks failed"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    connection = sqlite3.connect(data_dir / "service.db")
    columns = {
        row[1] for row in connection.execute("PRAGMA table_info(actor_attempts_v2)")
    }
    assert "logical_job_id" not in columns
    assert connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    ).fetchone() is None
    connection.close()
