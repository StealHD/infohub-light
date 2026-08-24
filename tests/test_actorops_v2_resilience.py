from __future__ import annotations

from pathlib import Path

import pytest

import scripts.migrate_actorops_v2_resilience as resilience_migration
from scripts.migrate_actorops_v2_resilience import migrate, preview
from src.apify_actor_identity import source_target_fingerprint
from src.services.actorops.domain import CandidateLifecycle
from src.services.actorops.repository import ActorOpsRepository
from src.storage.actorops_v2_resilience_schema import (
    MIGRATION_VERSION,
    migration_marker_exists,
    schema_shapes_valid,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _repository(tmp_path: Path):
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    route = connection.execute(
        "SELECT * FROM actor_routes_v2 WHERE platform='x'"
    ).fetchone()
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace", owner_user_id=None,
        source_type="apify_social", display_name="Resilience source",
        config={"platform": "x", "kind": "profile", "target": "openai"},
    )
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    fingerprint = source_target_fingerprint(
        DEFAULT_WORKSPACE_ID, str(route["route_id"]), "openai", platform="x",
    )
    with repository.transaction():
        for index in range(2):
            candidate_id = f"candidate-{index}"
            repository.create_candidate(
                candidate_id=candidate_id, route_id=str(route["route_id"]),
                actor_id=f"publisher/actor-{index}", publisher="publisher",
                build_id=f"build-{index}", build_number="1",
                manifest_json="{}", manifest_hash="a" * 64,
                input_schema_hash="b" * 64, output_schema_hash="c" * 64,
                lifecycle=CandidateLifecycle.CERTIFIED,
            )
            connection.execute(
                "UPDATE actor_candidates_v2 SET assignment_role=?, priority=? WHERE candidate_id=?",
                ("active" if index == 0 else "standby", index, candidate_id),
            )
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                   binding_id, workspace_id, source_id, route_id, target_fingerprint,
                   status, binding_version, created_at, updated_at
               ) VALUES ('binding-resilience', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
            (DEFAULT_WORKSPACE_ID, source_id, route["route_id"], fingerprint,
             "2026-08-24T00:00:00+00:00", "2026-08-24T00:00:00+00:00"),
        )
    return store, repository, str(route["route_id"]), source_id


def test_global_31_is_explicit_for_existing_store_and_fresh_for_new_store(tmp_path: Path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    assert migration_marker_exists(connection)
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    for table in (
        "actor_execution_events_v2", "actor_route_repairs_v2",
        "actor_source_candidate_freshness_v2",
    ):
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,))
    connection.commit()
    connection.execute("PRAGMA foreign_keys=ON")
    store.close()

    assert preview(tmp_path / "data")["status"] == "migration_required"
    result = migrate(tmp_path / "data", apply=True, backup_dir=tmp_path / "backups")
    assert result["status"] == "applied"
    assert result["backup_mode"] == "0o600"
    assert migrate(tmp_path / "data", apply=True, backup_dir=tmp_path / "backups")["status"] == "already_migrated"
    reopened = ServiceStore(tmp_path / "data")
    reopened.initialize()
    try:
        assert migration_marker_exists(reopened.connect())
        assert schema_shapes_valid(reopened.connect())
    finally:
        reopened.close()


def test_migration_failure_restores_the_previous_global_30_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    for table in (
        "actor_execution_events_v2", "actor_route_repairs_v2",
        "actor_source_candidate_freshness_v2",
    ):
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,))
    connection.commit()
    connection.execute("PRAGMA foreign_keys=ON")
    store.close()

    original = resilience_migration.apply_migration

    def fail_after_apply(db):
        original(db)
        raise RuntimeError("forced migration verification failure")

    monkeypatch.setattr(resilience_migration, "apply_migration", fail_after_apply)
    with pytest.raises(RuntimeError, match="forced migration verification failure"):
        resilience_migration.migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    restored = ServiceStore(data_dir)
    restored.initialize()
    try:
        assert not migration_marker_exists(restored.connect())
        assert preview(data_dir)["status"] == "migration_required"
    finally:
        restored.close()


def test_three_scheduled_no_advance_cross_checks_and_demotes_per_source(tmp_path: Path) -> None:
    store, repository, _route_id, source_id = _repository(tmp_path)
    try:
        binding = repository.get_binding(source_id)
        repository.resilience.record_regular_result(
            binding=binding, candidate_id="candidate-0", outcome="no_advance",
            logical_job_id="manual-fetch", natural_schedule=False,
        )
        assert repository.connection.execute(
            "SELECT COUNT(*) FROM actor_source_candidate_freshness_v2"
        ).fetchone()[0] == 0
        for index in range(3):
            repository.resilience.record_regular_result(
                binding=binding, candidate_id="candidate-0", outcome="no_advance",
                logical_job_id=f"scheduled-{index}", natural_schedule=True,
            )
        plan = repository.resilience.plan_candidates(
            binding=binding, candidates=repository.freeze_execution(
                binding.route_id, source_id, binding.target_fingerprint,
            ).candidates, natural_schedule=True,
        )
        assert plan.cross_check is True
        assert plan.primary_candidate_id == "candidate-0"
        assert plan.candidates[0].candidate_id == "candidate-1"

        result = repository.resilience.record_cross_check(
            binding=binding, primary_candidate_id="candidate-0",
            candidate_id="candidate-1", outcome="advanced", logical_job_id="scheduled-4",
        )
        assert result == "source_stale"
        assert repository.get_binding(source_id).preferred_candidate_id == "candidate-1"
        row = repository.connection.execute(
            """SELECT state, cooldown_until FROM actor_source_candidate_freshness_v2
               WHERE source_id=? AND candidate_id='candidate-0'""", (source_id,),
        ).fetchone()
        assert tuple(row)[0] == "source_stale"
        assert row["cooldown_until"] is not None
        repository.connection.execute(
            "UPDATE actor_source_bindings_v2 SET binding_version=2 WHERE source_id=?",
            (source_id,),
        )
        repository.connection.commit()
        rebound = repository.get_binding(source_id)
        reset = repository.resilience.plan_candidates(
            binding=rebound, candidates=repository.freeze_execution(
                rebound.route_id, source_id, rebound.target_fingerprint,
            ).candidates, natural_schedule=True,
        )
        assert reset.cross_check is False
    finally:
        store.close()


def test_second_source_confirmation_is_required_for_global_stale_demotion(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    try:
        binding = repository.get_binding(source_id)
        for index in range(3):
            repository.resilience.record_regular_result(
                binding=binding, candidate_id="candidate-0", outcome="no_advance",
                logical_job_id=f"first-{index}", natural_schedule=True,
            )
        assert repository.resilience.record_cross_check(
            binding=binding, primary_candidate_id="candidate-0", candidate_id="candidate-1",
            outcome="advanced", logical_job_id="first-cross-check",
        ) == "source_stale"
        assert repository.get_candidate("candidate-0").lifecycle is CandidateLifecycle.CERTIFIED

        second_source = store.create_source(
            workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace", owner_user_id=None,
            source_type="apify_social", display_name="Second resilience source",
            config={"platform": "x", "kind": "profile", "target": "second"},
        )
        second_fingerprint = source_target_fingerprint(
            DEFAULT_WORKSPACE_ID, route_id, "second", platform="x",
        )
        with repository.transaction():
            repository.connection.execute(
                """INSERT INTO actor_source_bindings_v2 (
                       binding_id, workspace_id, source_id, route_id, target_fingerprint,
                       status, binding_version, created_at, updated_at
                   ) VALUES ('binding-resilience-second', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
                (DEFAULT_WORKSPACE_ID, second_source, route_id, second_fingerprint,
                 "2026-08-24T00:00:00+00:00", "2026-08-24T00:00:00+00:00"),
            )
        second_binding = repository.get_binding(second_source)
        for index in range(3):
            repository.resilience.record_regular_result(
                binding=second_binding, candidate_id="candidate-0", outcome="no_advance",
                logical_job_id=f"second-{index}", natural_schedule=True,
            )
        assert repository.resilience.record_cross_check(
            binding=second_binding, primary_candidate_id="candidate-0", candidate_id="candidate-1",
            outcome="advanced", logical_job_id="second-cross-check",
        ) == "source_stale"
        assert repository.get_candidate("candidate-0").lifecycle is CandidateLifecycle.QUARANTINED
    finally:
        store.close()


def test_repair_and_trace_are_durable_and_redacted(tmp_path: Path, monkeypatch) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    try:
        monkeypatch.setattr(
            "src.services.actorops.repository_resilience.safe_emit_operation_event",
            lambda **_values: True,
        )
        repair = repository.resilience.ensure_repair(
            route_id=route_id, source_id=source_id, origin_job_id="job-safe",
            trigger_code="actorops_route_exhausted",
        )
        assert repair["status"] == "blocked"
        assert repair["error_code"] == "actorops_repair_not_authorized"
        repository.resilience.emit(
            root_job_id="job-safe", route_id=route_id, source_id=source_id,
            candidate_id="candidate-0", repair_id=str(repair["repair_id"]),
            phase="candidate_selection", outcome="selected", counts={"candidate_count": 2},
        )
        events, cursor, completeness = repository.resilience.execution_events(root_job_id="job-safe")
        assert cursor is None
        assert completeness == "complete"
        assert events[0]["counts"] == {"candidate_count": 2}
        assert "target" not in events[0]
        assert "input" not in events[0]
    finally:
        store.close()


def test_authorized_repair_creates_free_discovery_without_a_remote_call(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    try:
        store.create_user(
            workspace_id=DEFAULT_WORKSPACE_ID, username="resilience-owner",
            password="safe-test-password", role="owner",
        )
        owner = store.connect().execute(
            "SELECT id FROM users WHERE workspace_id=? ORDER BY created_at LIMIT 1",
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()
        assert owner is not None
        store.connect().execute(
            """UPDATE actor_maintenance_policies_v2 SET enabled=1,
                   authorized_by_user_id=?, authorized_at='2026-08-24T00:00:00+00:00'
               WHERE workspace_id=?""",
            (owner["id"], DEFAULT_WORKSPACE_ID),
        )
        store.connect().commit()
        repair = repository.resilience.ensure_repair(
            route_id=route_id, source_id=source_id, origin_job_id="job-repair",
            trigger_code="actorops_route_exhausted",
        )
        assert repair["status"] == "queued"
        advanced = repository.resilience.advance_repair(str(repair["repair_id"]))
        assert advanced["status"] == "discovering"
        assert advanced["discovery_id"]
        discovery = repository.discovery.get(str(advanced["discovery_id"]))
        assert discovery["trigger_reason"] == "production_exhausted"
    finally:
        store.close()


def test_repair_records_budget_block_without_remote_activity(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    try:
        owner = store.create_user(
            workspace_id=DEFAULT_WORKSPACE_ID, username="budget-owner",
            password="safe-test-password", role="owner",
        )
        store.connect().execute(
            """UPDATE actor_maintenance_policies_v2 SET enabled=1,
                   authorized_by_user_id=?, authorized_at='2026-08-24T00:00:00+00:00'
               WHERE workspace_id=?""",
            (owner["id"], DEFAULT_WORKSPACE_ID),
        )
        store.connect().execute(
            """UPDATE actor_maintenance_policies_v2 SET monthly_budget_usd=0.01
               WHERE workspace_id=? AND route_id IS NULL""",
            (DEFAULT_WORKSPACE_ID,),
        )
        store.connect().commit()

        repair = repository.resilience.ensure_repair(
            route_id=route_id, source_id=source_id, origin_job_id="job-budget",
            trigger_code="actorops_route_exhausted",
        )

        assert repair["status"] == "blocked"
        assert repair["error_code"] == "actorops_repair_monthly_budget_exhausted"
        assert repository.connection.execute(
            "SELECT COUNT(*) FROM actor_attempts_v2 WHERE kind='probe'"
        ).fetchone()[0] == 0
    finally:
        store.close()
