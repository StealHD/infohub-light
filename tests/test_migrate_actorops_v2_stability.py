from __future__ import annotations

import sqlite3
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.migrate_actorops_v2_stability as migration_module
from scripts.migrate_actorops_v2_stability import migrate, preview
from src.services.actorops.domain import AttemptStatus, CandidateLifecycle
from src.services.actorops.repository import ActorOpsRepository
from src.storage.actorops_v2_stability_schema import (
    FRESHNESS_COLUMNS,
    MIGRATION_CHECKSUM,
    MIGRATION_NAME,
    MIGRATION_VERSION,
    migration_marker_exists,
    schema_shapes_valid,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _restore_global_32(data_dir: Path) -> None:
    connection = sqlite3.connect(data_dir / "service.db")
    connection.row_factory = sqlite3.Row
    try:
        connection.execute("DROP TABLE actor_candidate_presentation_mappings_v2")
        for column in (
            "half_open_lease_token", "half_open_lease_until",
            "cooldown_reason", "failure_streak",
        ):
            connection.execute(
                f"ALTER TABLE actor_source_candidate_freshness_v2 DROP COLUMN {column}"
            )
        connection.execute(
            "ALTER TABLE actor_maintenance_policies_v2 DROP COLUMN authorization_origin"
        )
        connection.execute("DROP TRIGGER trg_actor_policies_v2_generation")
        policies = connection.execute(
            """SELECT policy_id, route_id FROM actor_maintenance_policies_v2
               WHERE workspace_id=? ORDER BY route_id""",
            (DEFAULT_WORKSPACE_ID,),
        ).fetchall()
        for index, policy in enumerate(policies):
            untouched = index < 2
            connection.execute(
                """UPDATE actor_maintenance_policies_v2
                   SET enabled=0, authorized_by_user_id=NULL, authorized_at=NULL,
                       auto_replace_non_last=CASE WHEN route_id IS NULL THEN NULL ELSE 1 END,
                       generation=?, updated_at='2026-08-20T00:00:00+00:00'
                   WHERE policy_id=?""",
                (1 if untouched else 2, policy["policy_id"]),
            )
        connection.execute(
            """CREATE TRIGGER trg_actor_policies_v2_generation
               BEFORE UPDATE ON actor_maintenance_policies_v2
               WHEN NEW.generation < OLD.generation
               BEGIN SELECT RAISE(ABORT, 'actorops_v2_generation_regression'); END"""
        )
        connection.execute(
            "DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
        )
        connection.commit()
    finally:
        connection.close()


def _prepare_failed_global_32(
    data_dir: Path, *, later_success: bool = False, active_worker: bool = False
) -> tuple[str, str]:
    store = ServiceStore(data_dir)
    store.initialize()
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="global 33 circuit source",
        config={"platform": "x", "kind": "profile", "target": "openai"},
    )
    connection = store.connect()
    route = connection.execute(
        "SELECT route_id, generation FROM actor_routes_v2 WHERE platform='x' LIMIT 1"
    ).fetchone()
    assert route is not None
    route_id = str(route["route_id"])
    candidate_id = "global-33-circuit-candidate"
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        repository.create_candidate(
            candidate_id=candidate_id,
            route_id=route_id,
            actor_id="publisher/global-33-circuit",
            publisher="publisher",
            build_id="build-global-33",
            build_number="1",
            manifest_json="{}",
            manifest_hash="a" * 64,
            input_schema_hash="b" * 64,
            output_schema_hash="c" * 64,
            lifecycle=CandidateLifecycle.CERTIFIED,
        )
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                   binding_id, workspace_id, source_id, route_id,
                   target_fingerprint, status, binding_version,
                   created_at, updated_at
               ) VALUES ('global-33-binding',?,?,?,?, 'ready',1,?,?)""",
            (
                DEFAULT_WORKSPACE_ID,
                source_id,
                route_id,
                "f" * 64,
                "2026-08-27T00:00:00+00:00",
                "2026-08-27T00:00:00+00:00",
            ),
        )
    _terminal_attempt(
        repository,
        route_id=route_id,
        source_id=source_id,
        candidate_id=candidate_id,
        attempt_id="global-33-paid-failure",
        status=AttemptStatus.FAILED,
    )
    failure_at = datetime.now(timezone.utc) - timedelta(hours=1)
    connection.execute(
        """UPDATE actor_attempts_v2 SET terminal_at=?, updated_at=?
             WHERE attempt_id='global-33-paid-failure'""",
        (failure_at.isoformat(), failure_at.isoformat()),
    )
    if later_success:
        _terminal_attempt(
            repository,
            route_id=route_id,
            source_id=source_id,
            candidate_id=candidate_id,
            attempt_id="global-33-later-success",
            status=AttemptStatus.SUCCEEDED,
        )
    if active_worker:
        store.upsert_worker_heartbeat("global-33-worker", "idle")
    connection.commit()
    store.close()
    _restore_global_32(data_dir)
    return source_id, candidate_id


def _terminal_attempt(
    repository: ActorOpsRepository,
    *,
    route_id: str,
    source_id: str,
    candidate_id: str,
    attempt_id: str,
    status: AttemptStatus,
) -> None:
    with repository.transaction():
        route = repository.get_route(route_id)
        repository.create_attempt(
            attempt_id=attempt_id,
            idempotency_key=f"key-{attempt_id}",
            route_id=route_id,
            source_id=source_id,
            candidate_id=candidate_id,
            kind="fetch",
            attempt_group_id=f"group-{attempt_id}",
            attempt_index=0,
            route_generation=route.generation,
            binding_version=1,
            target_fingerprint="f" * 64,
            reserved_usd=0.05,
            logical_job_id=f"job-{attempt_id}",
            request_fingerprint=f"request-{attempt_id}",
            max_items=1,
        )
        repository.transition_attempt(
            attempt_id,
            AttemptStatus.CREATED,
            AttemptStatus.STARTING,
        )
        if status is AttemptStatus.SUCCEEDED:
            repository.register_attempt_run(
                attempt_id,
                expected_generation=2,
                remote_run_id=f"remote-{attempt_id}",
                dataset_id=f"dataset-{attempt_id}",
            )
        repository.complete_attempt(
            attempt_id,
            status=status,
            semantic_outcome="advanced" if status is AttemptStatus.SUCCEEDED else None,
            actual_cost_usd=0.02,
            cost_final=True,
            failure_class=("candidate" if status is AttemptStatus.FAILED else None),
            error_code=(
                "actorops_v2_candidate_contract_invalid"
                if status is AttemptStatus.FAILED
                else None
            ),
        )


def test_global_33_is_explicit_atomic_idempotent_and_preserves_opt_out(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    store.close()
    _restore_global_32(data_dir)

    assert preview(data_dir)["status"] == "migration_required"
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert result["status"] == "applied"
    assert result["policies_default_enabled"] == 2
    assert result["auto_replacement_disabled"] >= 1
    assert result["backup_mode"] == "0o600"

    connection = sqlite3.connect(data_dir / "service.db")
    connection.row_factory = sqlite3.Row
    try:
        marker = connection.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version=?",
            (MIGRATION_VERSION,),
        ).fetchone()
        assert tuple(marker) == (MIGRATION_NAME, MIGRATION_CHECKSUM)
        assert migration_marker_exists(connection)
        assert schema_shapes_valid(connection)
        policies = connection.execute(
            """SELECT enabled, generation, authorization_origin,
                      auto_replace_non_last
                 FROM actor_maintenance_policies_v2
                WHERE workspace_id=? ORDER BY route_id""",
            (DEFAULT_WORKSPACE_ID,),
        ).fetchall()
        assert policies[0]["enabled"] == 1
        assert policies[0]["authorization_origin"] == "system_default"
        assert policies[1]["enabled"] == 1
        assert policies[1]["authorization_origin"] == "system_default"
        assert all(
            row["auto_replace_non_last"] in {None, 0} for row in policies
        )
        assert all(
            row["enabled"] == 0 and row["authorization_origin"] == "none"
            for row in policies[2:]
        )
        freshness_columns = {
            str(row[1]) for row in connection.execute(
                "PRAGMA table_info(actor_source_candidate_freshness_v2)"
            )
        }
        assert FRESHNESS_COLUMNS <= freshness_columns
        assert connection.execute(
            "SELECT COUNT(*) FROM actor_candidate_presentation_mappings_v2"
        ).fetchone()[0] == 0
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()

    assert migrate(data_dir, apply=True)["status"] == "already_migrated"


def test_fresh_store_defaults_maintenance_on_without_auto_replacement(
    tmp_path: Path,
) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    rows = store.connect().execute(
        """SELECT enabled, authorization_origin, auto_replace_non_last
             FROM actor_maintenance_policies_v2 ORDER BY route_id"""
    ).fetchall()
    assert rows
    assert all(bool(row["enabled"]) for row in rows)
    assert all(row["authorization_origin"] == "system_default" for row in rows)
    assert all(row["auto_replace_non_last"] in {None, 0} for row in rows)
    store.close()


def test_global_33_backfills_active_paid_failure_circuit(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    source_id, candidate_id = _prepare_failed_global_32(data_dir)

    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["source_circuits_backfilled"] == 1
    connection = sqlite3.connect(data_dir / "service.db")
    connection.row_factory = sqlite3.Row
    row = connection.execute(
        """SELECT state, failure_streak, cooldown_reason, cooldown_until
             FROM actor_source_candidate_freshness_v2
            WHERE source_id=? AND candidate_id=? AND binding_version=1""",
        (source_id, candidate_id),
    ).fetchone()
    assert row is not None
    assert tuple(row)[:3] == (
        "source_stale",
        1,
        "paid_candidate_failure",
    )
    assert datetime.fromisoformat(str(row["cooldown_until"])) > datetime.now(timezone.utc)
    connection.close()


def test_global_33_does_not_backfill_failure_followed_by_success(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    source_id, candidate_id = _prepare_failed_global_32(
        data_dir, later_success=True
    )

    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["source_circuits_backfilled"] == 0
    connection = sqlite3.connect(data_dir / "service.db")
    assert connection.execute(
        """SELECT COUNT(*) FROM actor_source_candidate_freshness_v2
            WHERE source_id=? AND candidate_id=?""",
        (source_id, candidate_id),
    ).fetchone()[0] == 0
    connection.close()


def test_global_33_orders_late_settled_success_by_terminal_time(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    source_id, candidate_id = _prepare_failed_global_32(
        data_dir, later_success=True
    )
    now = datetime.now(timezone.utc)
    connection = sqlite3.connect(data_dir / "service.db")
    connection.execute(
        """UPDATE actor_attempts_v2
              SET terminal_at=?, updated_at=?
            WHERE attempt_id='global-33-later-success'""",
        ((now - timedelta(hours=2)).isoformat(), now.isoformat()),
    )
    connection.execute(
        """UPDATE actor_attempts_v2
              SET terminal_at=?, updated_at=?
            WHERE attempt_id='global-33-paid-failure'""",
        (
            (now - timedelta(hours=1)).isoformat(),
            (now - timedelta(hours=1)).isoformat(),
        ),
    )
    connection.commit()
    connection.close()

    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["source_circuits_backfilled"] == 1
    connection = sqlite3.connect(data_dir / "service.db")
    assert connection.execute(
        """SELECT COUNT(*) FROM actor_source_candidate_freshness_v2
            WHERE source_id=? AND candidate_id=?""",
        (source_id, candidate_id),
    ).fetchone()[0] == 1
    connection.close()


def test_global_33_orders_late_settled_failure_by_terminal_time(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    source_id, candidate_id = _prepare_failed_global_32(
        data_dir, later_success=True
    )
    now = datetime.now(timezone.utc)
    connection = sqlite3.connect(data_dir / "service.db")
    connection.execute(
        """UPDATE actor_attempts_v2
              SET terminal_at=?, updated_at=?
            WHERE attempt_id='global-33-paid-failure'""",
        ((now - timedelta(hours=2)).isoformat(), now.isoformat()),
    )
    connection.execute(
        """UPDATE actor_attempts_v2
              SET terminal_at=?, updated_at=?
            WHERE attempt_id='global-33-later-success'""",
        (
            (now - timedelta(hours=1)).isoformat(),
            (now - timedelta(hours=1)).isoformat(),
        ),
    )
    connection.commit()
    connection.close()

    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["source_circuits_backfilled"] == 0
    connection = sqlite3.connect(data_dir / "service.db")
    assert connection.execute(
        """SELECT COUNT(*) FROM actor_source_candidate_freshness_v2
            WHERE source_id=? AND candidate_id=?""",
        (source_id, candidate_id),
    ).fetchone()[0] == 0
    connection.close()


def test_global_33_preview_rejects_partial_schema(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _prepare_failed_global_32(data_dir)
    connection = sqlite3.connect(data_dir / "service.db")
    connection.execute(
        """ALTER TABLE actor_source_candidate_freshness_v2
           ADD COLUMN failure_streak INTEGER NOT NULL DEFAULT 0"""
    )
    connection.commit()
    connection.close()

    with pytest.raises(RuntimeError, match="partial ActorOps stability schema"):
        preview(data_dir)


def test_global_33_blocks_active_worker(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    _prepare_failed_global_32(data_dir, active_worker=True)

    result = preview(data_dir)
    assert result["status"] == "blocked"
    assert result["blocker_counts"] == {"workers": 1}
    with pytest.raises(RuntimeError, match="API and Worker must stop"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")


def test_global_33_keeps_writes_when_worker_starts_after_backup(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    _prepare_failed_global_32(data_dir)
    checks = 0

    def worker_check(database: Path) -> list[str]:
        nonlocal checks
        checks += 1
        if checks == 1:
            return []
        stamp = datetime.now(timezone.utc).isoformat()
        connection = sqlite3.connect(database)
        connection.execute(
            """INSERT INTO worker_heartbeats (
                   worker_id, state, started_at, heartbeat_at, updated_at
               ) VALUES (?,?,?,?,?)""",
            ("global-33-race-worker", "idle", stamp, stamp, stamp),
        )
        connection.commit()
        connection.close()
        return ["global-33-race-worker"]

    monkeypatch.setattr(
        migration_module, "active_workers_fail_closed", worker_check
    )
    with pytest.raises(RuntimeError, match="API and Worker must stop"):
        migration_module.migrate(
            data_dir, apply=True, backup_dir=tmp_path / "backups"
        )

    connection = sqlite3.connect(data_dir / "service.db")
    try:
        assert connection.execute(
            "SELECT state FROM worker_heartbeats WHERE worker_id=?",
            ("global-33-race-worker",),
        ).fetchone() == ("idle",)
        assert connection.execute(
            "SELECT COUNT(*) FROM schema_migrations WHERE version=?",
            (MIGRATION_VERSION,),
        ).fetchone()[0] == 0
    finally:
        connection.close()


def test_global_33_restores_backup_after_post_apply_failure(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    _prepare_failed_global_32(data_dir)
    original = migration_module.apply_migration

    def fail_after_apply(connection: sqlite3.Connection) -> dict[str, int]:
        original(connection)
        raise RuntimeError("forced global 33 verification failure")

    monkeypatch.setattr(migration_module, "apply_migration", fail_after_apply)
    with pytest.raises(RuntimeError, match="forced global 33 verification failure"):
        migration_module.migrate(
            data_dir, apply=True, backup_dir=tmp_path / "backups"
        )

    connection = sqlite3.connect(data_dir / "service.db")
    columns = {
        str(row[1])
        for row in connection.execute(
            "PRAGMA table_info(actor_source_candidate_freshness_v2)"
        )
    }
    assert "failure_streak" not in columns
    assert connection.execute(
        "SELECT COUNT(*) FROM schema_migrations WHERE version=?",
        (MIGRATION_VERSION,),
    ).fetchone()[0] == 0
    connection.close()
