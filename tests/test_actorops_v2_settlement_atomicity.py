from __future__ import annotations

import asyncio
from datetime import timedelta
from pathlib import Path

import httpx
import pytest

from src.scrapers.apify_client import ApifyClient
from src.services.actorops.domain import AttemptStatus, CandidateLifecycle
from src.services.actorops.errors import ActorOpsRuntimeError
from src.services.actorops.ports import (
    FetchWindow,
    ReconciliationRunObservation,
    ReconciliationRunResolution,
)
from src.services.actorops.reconciliation import ActorOpsReconciler
from src.services.actorops.reconciliation_lifecycle import (
    settle_unstarted_after_terminal_job,
)
from src.services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from src.services.actorops.source_candidate_circuit import SourceCandidateCircuit
from src.services.apify_key_pool import ApifyKeyDrainPendingError
from src.storage.service_store import DEFAULT_WORKSPACE_ID
from tests.test_actorops_v2_reconciliation import (
    _Ledger,
    _attempt,
    _link,
    _repository,
)
from tests.test_actorops_v2_runtime import _runtime
from tests.test_apify_key_pool import FIXED_NOW, _pool


def _failed_candidate_attempt(tmp_path: Path):
    store, repository, route_id = _repository(tmp_path)
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Atomic settlement source",
        config={"platform": "youtube", "kind": "channel", "target": "safe"},
    )
    fingerprint = "f" * 64
    with repository.transaction():
        repository.connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                   binding_id, workspace_id, source_id, route_id,
                   target_fingerprint, status, binding_version,
                   created_at, updated_at
               ) VALUES ('binding-atomic', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
            (
                DEFAULT_WORKSPACE_ID,
                source_id,
                route_id,
                fingerprint,
                "2026-08-20T00:00:00+00:00",
                "2026-08-20T00:00:00+00:00",
            ),
        )
        repository.create_attempt(
            attempt_id="attempt-atomic-circuit",
            idempotency_key="key-atomic-circuit",
            route_id=route_id,
            source_id=source_id,
            candidate_id="candidate-reconcile",
            kind="fetch",
            attempt_group_id="group-atomic-circuit",
            attempt_index=0,
            route_generation=repository.get_route(route_id).generation,
            binding_version=1,
            target_fingerprint=fingerprint,
            reserved_usd=0.05,
            logical_job_id="job-atomic-circuit",
        )
        repository.transition_attempt(
            "attempt-atomic-circuit", AttemptStatus.CREATED, AttemptStatus.STARTING
        )
        repository.complete_attempt(
            "attempt-atomic-circuit",
            status=AttemptStatus.FAILED,
            semantic_outcome="actorops_candidate_failed",
            actual_cost_usd=None,
            cost_final=False,
            failure_class="candidate",
            error_code="actorops_candidate_failed",
        )
    ledger = _Ledger(
        {
            "attempt-atomic-circuit": ReconciliationRunResolution(
                _link("reservation-atomic-circuit", remote="remote-atomic-circuit")
            )
        },
        {
            "reservation-atomic-circuit": ReconciliationRunObservation(
                "failed", 0.01, True, "dataset-atomic-circuit"
            )
        },
    )
    return store, repository, source_id, ledger


def test_reconciler_rolls_back_cost_when_candidate_circuit_write_fails(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, repository, source_id, ledger = _failed_candidate_attempt(tmp_path)
    original = SourceCandidateCircuit.record_failure_in_transaction

    def fail_circuit(_self, **_values):
        raise RuntimeError("circuit write failed")

    monkeypatch.setattr(
        SourceCandidateCircuit, "record_failure_in_transaction", fail_circuit
    )
    first = asyncio.run(ActorOpsReconciler(repository, ledger).reconcile())

    unsettled = repository.get_attempt("attempt-atomic-circuit")
    assert (first.remote_reads, first.errors) == (1, 1)
    assert (unsettled["actual_cost_usd"], unsettled["cost_final"]) == (None, 0)
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM actor_source_candidate_freshness_v2 WHERE source_id=?",
        (source_id,),
    ).fetchone()[0] == 0

    monkeypatch.setattr(
        SourceCandidateCircuit, "record_failure_in_transaction", original
    )
    second = asyncio.run(ActorOpsReconciler(repository, ledger).reconcile())
    settled = repository.get_attempt("attempt-atomic-circuit")
    circuit = repository.connection.execute(
        """SELECT failure_streak, last_outcome
             FROM actor_source_candidate_freshness_v2 WHERE source_id=?""",
        (source_id,),
    ).fetchone()
    assert second.settled == 1
    assert (settled["actual_cost_usd"], settled["cost_final"]) == (0.01, 1)
    assert tuple(circuit) == (1, "paid_candidate_failure")
    store.close()


def test_reconciler_cas_conflicts_still_consume_default_remote_read_limit(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, repository, route_id = _repository(tmp_path)
    links = {}
    observations = {}
    for index in range(7):
        attempt_id = f"attempt-conflict-{index}"
        reservation_id = f"reservation-conflict-{index}"
        _attempt(repository, route_id, attempt_id, AttemptStatus.RUNNING)
        links[attempt_id] = ReconciliationRunResolution(
            _link(reservation_id, remote=f"remote-conflict-{index}")
        )
        observations[reservation_id] = ReconciliationRunObservation(
            "failed", 0.01, True
        )
    ledger = _Ledger(links, observations)
    original = repository.reconcile_attempt

    def conflict(attempt_id: str, **values):
        if values.get("actual_cost_usd") is not None:
            raise ActorOpsConflict("simulated CAS loss")
        return original(attempt_id, **values)

    monkeypatch.setattr(repository, "reconcile_attempt", conflict)
    summary = asyncio.run(ActorOpsReconciler(repository, ledger).reconcile())

    assert summary.remote_reads == 5
    assert summary.errors == 5
    assert len(ledger.reads) == 5
    assert repository.get_attempt("attempt-conflict-6")["error_code"] == (
        "actorops_reconcile_deferred"
    )
    store.close()


def test_runtime_retries_paid_failure_when_atomic_circuit_write_rolls_back(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, ["suspicious_empty"], candidate_count=1
    )
    original = SourceCandidateCircuit.record_failure_in_transaction

    def fail_circuit(_self, **_values):
        raise RuntimeError("circuit write failed")

    monkeypatch.setattr(
        SourceCandidateCircuit, "record_failure_in_transaction", fail_circuit
    )
    values = dict(
        route_id=route_id,
        source_id=source_id,
        source_config={"target": "openai"},
        window=FetchWindow(3, FIXED_NOW - timedelta(days=1), None),
        logical_job_id="job-runtime-atomic",
    )
    with pytest.raises(RuntimeError, match="circuit write failed"):
        asyncio.run(runtime.fetch(**values))

    pending = repository.connection.execute(
        "SELECT status, cost_final FROM actor_attempts_v2"
    ).fetchone()
    assert tuple(pending) == ("running", 1)
    assert repository.connection.execute(
        "SELECT COUNT(*) FROM actor_source_candidate_freshness_v2"
    ).fetchone()[0] == 0

    monkeypatch.setattr(
        SourceCandidateCircuit, "record_failure_in_transaction", original
    )
    with pytest.raises(ActorOpsRuntimeError) as replay:
        asyncio.run(runtime.fetch(**values))
    terminal = repository.connection.execute(
        "SELECT status, cost_final FROM actor_attempts_v2"
    ).fetchone()
    circuit = repository.connection.execute(
        """SELECT last_outcome FROM actor_source_candidate_freshness_v2
            WHERE source_id=? AND candidate_id=?""",
        (source_id, candidates[0]),
    ).fetchone()
    assert replay.value.code == "actorops_v2_route_unavailable"
    assert tuple(terminal) == ("failed", 1)
    assert circuit["last_outcome"] == "paid_candidate_failure"
    assert len(remote.requests) == 1
    assert remote.dataset_reads == [("dataset", 3)]
    store.close()


def _actorops_pool_attempt(tmp_path: Path):
    store, _secrets, service, _refs = _pool(tmp_path, count=1)
    repository = ActorOpsRepository(store.connect(), DEFAULT_WORKSPACE_ID)
    route_id = str(repository.connection.execute(
        "SELECT route_id FROM actor_routes_v2 WHERE platform='youtube'"
    ).fetchone()[0])
    user = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="start-fence-owner",
        password="safe-test-password",
        role="owner",
    )
    now_iso = FIXED_NOW.isoformat()
    repository.connection.execute(
        """INSERT INTO fetch_jobs (
               id, workspace_id, user_id, job_type, status, priority,
               attempts, max_attempts, worker_id, claim_token, locked_until,
               payload_json, created_at, started_at, updated_at
           ) VALUES ('job-start-fence', ?, ?, 'source_fetch', 'running', 0,
                     1, 3, 'worker-current', 'claim-current', ?, '{}', ?, ?, ?)""",
        (
            DEFAULT_WORKSPACE_ID,
            str(user["id"]),
            (FIXED_NOW + timedelta(minutes=5)).isoformat(),
            now_iso,
            now_iso,
            now_iso,
        ),
    )
    repository.connection.commit()
    with repository.transaction():
        repository.create_candidate(
            candidate_id="candidate-start-fence",
            route_id=route_id,
            actor_id="publisher/start-fence",
            publisher="publisher",
            build_id="build-start-fence",
            build_number="1",
            manifest_json="{}",
            manifest_hash="a" * 64,
            input_schema_hash="b" * 64,
            output_schema_hash="c" * 64,
            lifecycle=CandidateLifecycle.PROBATIONARY,
        )
        repository.create_attempt(
            attempt_id="attempt-start-fence",
            idempotency_key="key-start-fence",
            route_id=route_id,
            candidate_id="candidate-start-fence",
            kind="fetch",
            attempt_group_id="group-start-fence",
            attempt_index=0,
            route_generation=repository.get_route(route_id).generation,
            binding_version=None,
            target_fingerprint="f" * 64,
            reserved_usd=0.05,
            logical_job_id="job-start-fence",
        )
    return store, service, repository


def _finish_start_fence_job(repository: ActorOpsRepository) -> None:
    repository.connection.execute(
        """UPDATE fetch_jobs SET status='failed', worker_id=NULL,
                  claim_token=NULL, locked_until=NULL, finished_at=?, updated_at=?
            WHERE id='job-start-fence'""",
        (FIXED_NOW.isoformat(), FIXED_NOW.isoformat()),
    )
    repository.connection.commit()


def test_reservation_first_blocks_zero_settlement_and_invalid_job_blocks_post(
    tmp_path: Path,
) -> None:
    store, service, repository = _actorops_pool_attempt(tmp_path)
    lease = service.acquire_credential(logical_run_id="attempt-start-fence")
    stale_attempt = repository.get_attempt("attempt-start-fence")
    _finish_start_fence_job(repository)

    assert settle_unstarted_after_terminal_job(repository, stale_attempt) is False
    with pytest.raises(ApifyKeyDrainPendingError):
        service.assert_lease_startable(lease)
    attempt = repository.get_attempt("attempt-start-fence")
    assert (attempt["status"], attempt["cost_final"]) == ("created", 0)
    assert service.get_run(lease.reservation_id)["status"] == "reserved"
    store.close()


def test_same_attempt_allows_retry_only_after_old_reservation_is_rejected(
    tmp_path: Path,
) -> None:
    store, service, _repository = _actorops_pool_attempt(tmp_path)
    first = service.acquire_credential(logical_run_id="attempt-start-fence")

    with pytest.raises(ApifyKeyDrainPendingError):
        service.acquire_credential(logical_run_id="attempt-start-fence")

    service.release_reservation(first, "apify_explicit_reject")
    second = service.acquire_credential(logical_run_id="attempt-start-fence")
    assert second.reservation_id != first.reservation_id
    assert service.get_run(first.reservation_id)["status"] == "start_rejected"
    assert service.get_run(second.reservation_id)["status"] == "reserved"
    store.close()


def test_generic_acquisition_is_compatible_without_actorops_attempt_table(
    tmp_path: Path,
) -> None:
    store, _secrets, service, _refs = _pool(tmp_path, count=1)
    store.connect().execute("DROP TABLE actor_attempts_v2")
    store.connect().commit()

    lease = service.acquire_credential(logical_run_id="legacy-generic-run")

    assert service.get_run(lease.reservation_id)["status"] == "reserved"
    store.close()


def test_settlement_first_rejects_delayed_worker_before_reservation_or_post(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    store, service, repository = _actorops_pool_attempt(tmp_path)
    _finish_start_fence_job(repository)
    stale_attempt = repository.get_attempt("attempt-start-fence")
    assert settle_unstarted_after_terminal_job(repository, stale_attempt) is True
    calls: list[str] = []
    http_client = httpx.AsyncClient(
        transport=httpx.MockTransport(
            lambda _request: httpx.Response(500, json={"error": "unexpected"})
        ),
        trust_env=False,
    )
    client = ApifyClient(coordinator=service, http_client=http_client)

    async def request(*_args, **_kwargs):
        calls.append("remote")
        raise AssertionError("remote request must remain fenced")

    monkeypatch.setattr(client, "_request_json", request)
    with pytest.raises(ApifyKeyDrainPendingError):
        asyncio.run(client.run_actor_detailed(
            "publisher/start-fence",
            {"target": "safe"},
            logical_run_id="attempt-start-fence",
            max_paid_dataset_items=1,
        ))

    attempt = repository.get_attempt("attempt-start-fence")
    assert (attempt["status"], attempt["actual_cost_usd"], attempt["cost_final"]) == (
        "cancelled",
        0.0,
        1,
    )
    assert calls == []
    assert repository.connection.execute(
        """SELECT COUNT(*) FROM apify_actor_runs
            WHERE logical_run_id='attempt-start-fence'"""
    ).fetchone()[0] == 0
    asyncio.run(http_client.aclose())
    store.close()
