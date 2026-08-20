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
