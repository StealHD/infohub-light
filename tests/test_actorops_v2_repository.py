from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.services.actorops.domain import (
    AssignmentRole,
    AttemptStatus,
    CandidateLifecycle,
    DiscoveryStage,
    DiscoveryStatus,
    RouteHealth,
)
from src.services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _repository(tmp_path: Path) -> tuple[ServiceStore, ActorOpsRepository, str]:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = str(
        store.connect().execute(
            "SELECT route_id FROM actor_routes_v2 WHERE platform = 'youtube'"
        ).fetchone()[0]
    )
    return store, ActorOpsRepository(store.connect(), DEFAULT_WORKSPACE_ID), route_id


def test_repository_assigns_exact_candidate_and_derives_health(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    assert repository.route_health(route_id) is RouteHealth.UNAVAILABLE
    with repository.transaction():
        repository.create_candidate(
            candidate_id="candidate-v2-a",
            route_id=route_id,
            actor_id="publisher/actor-a",
            publisher="publisher",
            build_id="build-a",
            build_number="1.0.0",
            manifest_json='{"version":1}',
            manifest_hash="a" * 64,
            input_schema_hash="b" * 64,
            output_schema_hash="c" * 64,
            lifecycle=CandidateLifecycle.PROBATIONARY,
        )
        repository.assign_candidate(
            route_id,
            "candidate-v2-a",
            AssignmentRole.ACTIVE,
            priority=0,
            expected_route_generation=1,
            expected_candidate_generation=1,
        )
    assert repository.route_health(route_id) is RouteHealth.DEGRADED
    assert repository.get_route(route_id).generation == 2
    assert repository.get_candidate("candidate-v2-a").generation == 2
    with pytest.raises(sqlite3.IntegrityError):
        store.connect().execute(
            "UPDATE actor_candidates_v2 SET actor_id = 'changed' WHERE candidate_id = 'candidate-v2-a'"
        )
    store.close()


def test_repository_promotes_existing_standby_without_changing_exact_candidates(
    tmp_path: Path,
) -> None:
    store, repository, route_id = _repository(tmp_path)
    with repository.transaction():
        for candidate_id in ("candidate-v2-primary", "candidate-v2-backup"):
            repository.create_candidate(
                candidate_id=candidate_id,
                route_id=route_id,
                actor_id=f"publisher/{candidate_id}",
                publisher="publisher",
                build_id=f"build-{candidate_id}",
                build_number="1.0.0",
                manifest_json='{"version":1}',
                manifest_hash=("a" if candidate_id.endswith("primary") else "b") * 64,
                input_schema_hash="c" * 64,
                output_schema_hash="d" * 64,
                lifecycle=CandidateLifecycle.PROBATIONARY,
            )
        repository.assign_candidate(
            route_id, "candidate-v2-primary", AssignmentRole.ACTIVE, priority=0,
            expected_route_generation=1, expected_candidate_generation=1,
        )
        repository.assign_candidate(
            route_id, "candidate-v2-backup", AssignmentRole.STANDBY, priority=1,
            expected_route_generation=2, expected_candidate_generation=1,
        )

    with repository.transaction():
        repository.promote_standby_candidate(
            route_id,
            "candidate-v2-backup",
            expected_route_generation=3,
            expected_candidate_generation=2,
        )

    primary = repository.get_candidate("candidate-v2-primary")
    backup = repository.get_candidate("candidate-v2-backup")
    assert backup.assignment_role is AssignmentRole.ACTIVE
    assert backup.priority == 0
    assert primary.assignment_role is AssignmentRole.STANDBY
    assert primary.priority == 1
    assert repository.get_route(route_id).generation == 4
    with repository.transaction(), pytest.raises(ActorOpsConflict):
        repository.promote_standby_candidate(
            route_id,
            "candidate-v2-primary",
            expected_route_generation=3,
            expected_candidate_generation=primary.generation,
        )
    store.close()


def test_repository_enforces_cas_and_terminal_attempts(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    with repository.transaction():
        repository.create_candidate(
            candidate_id="candidate-v2-attempt",
            route_id=route_id,
            actor_id="publisher/attempt",
            publisher="publisher",
            build_id="build-attempt",
            build_number="1",
            manifest_json='{"version":1}',
            manifest_hash="d" * 64,
            input_schema_hash="e" * 64,
            output_schema_hash="f" * 64,
            lifecycle=CandidateLifecycle.PROBATIONARY,
        )
        repository.create_attempt(
            attempt_id="attempt-v2",
            idempotency_key="attempt-idempotency",
            route_id=route_id,
            candidate_id="candidate-v2-attempt",
            kind="probe",
            attempt_group_id="group-v2",
            attempt_index=0,
            route_generation=1,
            binding_version=None,
            target_fingerprint="1" * 64,
            reserved_usd=0.05,
        )
        repository.transition_attempt(
            "attempt-v2", AttemptStatus.CREATED, AttemptStatus.STARTING
        )
        repository.transition_attempt(
            "attempt-v2", AttemptStatus.STARTING, AttemptStatus.FAILED,
            error_class="internal", error_code="test_failure",
        )
    with repository.transaction():
        with pytest.raises(ActorOpsConflict):
            repository.transition_attempt(
                "attempt-v2", AttemptStatus.STARTING, AttemptStatus.FAILED
            )
    row = repository.get_attempt("attempt-v2")
    with repository.transaction():
        with pytest.raises(ActorOpsConflict):
            repository.reconcile_attempt(
                "attempt-v2",
                expected_status=AttemptStatus.FAILED,
                expected_generation=int(row["generation"]),
                target_status=AttemptStatus.RUNNING,
            )
    store.close()


def test_repository_advances_discovery_without_stage_regression(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    with repository.transaction():
        repository.create_discovery_job(
            discovery_id="discovery-v2",
            idempotency_key="discovery-idempotency",
            route_id=route_id,
            trigger_reason="test",
            input_fingerprint="2" * 64,
        )
        repository.transition_discovery(
            "discovery-v2",
            DiscoveryStatus.QUEUED,
            DiscoveryStage.STORE_SEARCH,
            DiscoveryStatus.RUNNING,
            DiscoveryStage.STORE_SEARCH,
        )
        repository.transition_discovery(
            "discovery-v2",
            DiscoveryStatus.RUNNING,
            DiscoveryStage.STORE_SEARCH,
            DiscoveryStatus.RUNNING,
            DiscoveryStage.METADATA,
        )
    with repository.transaction():
        with pytest.raises(ActorOpsConflict):
            repository.transition_discovery(
                "discovery-v2",
                DiscoveryStatus.RUNNING,
                DiscoveryStage.STORE_SEARCH,
                DiscoveryStatus.RUNNING,
                DiscoveryStage.METADATA,
            )
    store.close()


def test_database_triggers_reject_transition_shortcuts(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    with repository.transaction():
        repository.create_candidate(
            candidate_id="candidate-v2-trigger",
            route_id=route_id,
            actor_id="publisher/trigger",
            publisher="publisher",
            build_id="build-trigger",
            build_number="1",
            manifest_json='{"version":1}',
            manifest_hash="9" * 64,
            input_schema_hash="8" * 64,
            output_schema_hash="7" * 64,
            lifecycle=CandidateLifecycle.DISCOVERED,
        )
    with pytest.raises(sqlite3.IntegrityError, match="candidate_transition"):
        store.connect().execute(
            "UPDATE actor_candidates_v2 SET lifecycle = 'certified' WHERE candidate_id = 'candidate-v2-trigger'"
        )
    store.close()


def test_attempt_identity_and_observation_facts_cannot_regress(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    with repository.transaction():
        repository.create_candidate(
            candidate_id="candidate-v2-cost",
            route_id=route_id,
            actor_id="publisher/cost",
            publisher="publisher",
            build_id="build-cost",
            build_number="1",
            manifest_json='{"version":1}',
            manifest_hash="6" * 64,
            input_schema_hash="5" * 64,
            output_schema_hash="4" * 64,
            lifecycle=CandidateLifecycle.PROBATIONARY,
        )
        repository.create_attempt(
            attempt_id="attempt-cost",
            idempotency_key="attempt-cost-key",
            route_id=route_id,
            candidate_id="candidate-v2-cost",
            kind="probe",
            attempt_group_id="group-cost",
            attempt_index=0,
            route_generation=1,
            binding_version=None,
            target_fingerprint="3" * 64,
            reserved_usd=0.05,
            logical_job_id="job-cost",
        )
        repository.transition_attempt(
            "attempt-cost", AttemptStatus.CREATED, AttemptStatus.STARTING
        )
        repository.register_attempt_run(
            "attempt-cost",
            expected_generation=2,
            remote_run_id="remote-cost",
            dataset_id="dataset-cost",
        )
        repository.transition_attempt(
            "attempt-cost", AttemptStatus.REGISTERED, AttemptStatus.RUNNING
        )
        repository.observe_attempt_result(
            "attempt-cost",
            remote_run_id="remote-cost",
            dataset_id="dataset-cost",
            actual_cost_usd=0.01,
            cost_final=False,
        )
        repository.complete_attempt(
            "attempt-cost",
            status=AttemptStatus.SUCCEEDED,
            semantic_outcome="valid_nonempty",
            actual_cost_usd=None,
            cost_final=False,
        )
        current = repository.get_attempt("attempt-cost")
        repository.reconcile_attempt(
            "attempt-cost",
            expected_status=AttemptStatus.SUCCEEDED,
            expected_generation=int(current["generation"]),
            target_status=None,
            remote_run_id="remote-cost",
            dataset_id="dataset-cost",
            semantic_outcome=None,
            actual_cost_usd=0.02,
            cost_final=True,
            failure_class=None,
            error_code=None,
        )

    connection = store.connect()
    for statement in (
        "UPDATE actor_attempts_v2 SET actual_cost_usd=NULL WHERE attempt_id='attempt-cost'",
        "UPDATE actor_attempts_v2 SET actual_cost_usd=0.001 WHERE attempt_id='attempt-cost'",
        "UPDATE actor_attempts_v2 SET cost_final=0 WHERE attempt_id='attempt-cost'",
        "UPDATE actor_attempts_v2 SET dataset_id='changed' WHERE attempt_id='attempt-cost'",
        "UPDATE actor_attempts_v2 SET result_state='observed' WHERE attempt_id='attempt-cost'",
    ):
        with pytest.raises(sqlite3.IntegrityError, match="cannot regress"):
            connection.execute(statement)
    with repository.transaction(), pytest.raises(sqlite3.IntegrityError):
        repository.create_attempt(
            attempt_id="attempt-cost-duplicate",
            idempotency_key="attempt-cost-key-2",
            route_id=route_id,
            candidate_id="candidate-v2-cost",
            kind="probe",
            attempt_group_id="group-cost-2",
            attempt_index=1,
            route_generation=1,
            binding_version=None,
            target_fingerprint="3" * 64,
            reserved_usd=0.05,
            logical_job_id="job-cost",
        )
    row = repository.get_attempt("attempt-cost")
    assert tuple(row[key] for key in (
        "actual_cost_usd", "cost_final", "dataset_id", "result_state"
    )) == (0.02, 1, "dataset-cost", "validated")
    store.close()
