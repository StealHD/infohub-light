from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.services.actorops.attempt_recovery import (
    attempt_group_identity,
    attempt_identity,
    request_fingerprint,
)
from src.services.actorops.domain import AttemptStatus
from src.services.actorops.errors import ActorOpsRuntimeError
from src.services.actorops.ports import (
    FetchWindow,
    ReconciliationRunObservation,
    ReconciliationRunResolution,
)
from src.services.actorops.reconciliation import ActorOpsReconciler
from src.storage.service_store import DEFAULT_WORKSPACE_ID
from tests.test_actorops_v2_reconciliation import _Ledger, _job, _link, _repository
from tests.test_actorops_v2_runtime import _runtime


def _observed_attempt(repository, route_id, source_id, *, job_id: str) -> None:
    with repository.transaction():
        repository.create_attempt(
            attempt_id="attempt-result-recovery",
            idempotency_key="key-result-recovery",
            route_id=route_id,
            source_id=source_id,
            candidate_id="candidate-reconcile",
            kind="fetch",
            attempt_group_id="group-result-recovery",
            attempt_index=0,
            route_generation=1,
            binding_version=1,
            target_fingerprint="1" * 64,
            reserved_usd=0.05,
            logical_job_id=job_id,
        )
        repository.transition_attempt(
            "attempt-result-recovery", AttemptStatus.CREATED, AttemptStatus.STARTING
        )
        repository.register_attempt_run(
            "attempt-result-recovery",
            expected_generation=2,
            remote_run_id="remote-result-recovery",
            dataset_id="dataset-result-recovery",
        )
        repository.observe_attempt_result(
            "attempt-result-recovery",
            remote_run_id="remote-result-recovery",
            dataset_id="dataset-result-recovery",
            actual_cost_usd=0.000996,
            cost_final=True,
        )


@pytest.mark.parametrize(
    ("job_status", "expected_job_status", "expected_attempt_status", "expected_code"),
    [
        ("failed", "queued", "registered", "actorops_result_recovery_queued"),
        (
            "cancelled",
            "cancelled",
            "cancelled",
            "actorops_result_recovery_cancelled",
        ),
    ],
)
def test_reconciler_recovers_observed_final_result_without_another_actor_start(
    tmp_path,
    job_status,
    expected_job_status,
    expected_attempt_status,
    expected_code,
) -> None:
    store, repository, route_id = _repository(tmp_path)
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Result recovery source",
        config={"platform": "youtube", "kind": "channel", "target": "safe"},
    )
    job_id = "job-result-recovery"
    _job(store, job_id, status=job_status, source_id=source_id)
    _observed_attempt(repository, route_id, source_id, job_id=job_id)
    observed = repository.get_attempt("attempt-result-recovery")
    ledger = _Ledger(
        {
            "attempt-result-recovery": ReconciliationRunResolution(
                _link("reservation-result-recovery", remote="remote-result-recovery")
            )
        },
        {
            "reservation-result-recovery": ReconciliationRunObservation(
                "succeeded", 0.000996, True, "dataset-result-recovery"
            )
        },
    )

    summary = asyncio.run(
        ActorOpsReconciler(
            repository,
            ledger,
            now=lambda: datetime.fromisoformat(str(observed["updated_at"]))
            + timedelta(seconds=61),
        ).reconcile()
    )

    attempt = repository.get_attempt("attempt-result-recovery")
    job = store.connect().execute(
        "SELECT status,attempts,error_code FROM fetch_jobs WHERE id=?", (job_id,)
    ).fetchone()
    assert summary.settled == 1
    assert attempt["status"] == expected_attempt_status
    assert attempt["result_state"] == "observed"
    assert attempt["actual_cost_usd"] == pytest.approx(0.000996)
    assert attempt["cost_final"] == 1
    assert attempt["error_code"] == expected_code
    assert tuple(job) == (expected_job_status, 0, None)
    assert ledger.reads == ["reservation-result-recovery"]
    assert asyncio.run(ActorOpsReconciler(repository, ledger).reconcile()).scanned == 0
    store.close()


def test_observed_final_attempt_reports_result_recovery_not_cost_settlement(
    tmp_path,
) -> None:
    store, repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, ["valid_nonempty"]
    )
    binding = repository.get_binding(source_id)
    with repository.transaction():
        repository.create_attempt(
            attempt_id="attempt-observed-final",
            idempotency_key="key-observed-final",
            route_id=route_id,
            source_id=source_id,
            candidate_id=candidates[0],
            kind="fetch",
            attempt_group_id="group-observed-final",
            attempt_index=0,
            route_generation=repository.get_route(route_id).generation,
            binding_version=binding.binding_version,
            target_fingerprint=binding.target_fingerprint,
            reserved_usd=0.1,
            logical_job_id="old-observed-job",
        )
        repository.transition_attempt(
            "attempt-observed-final", AttemptStatus.CREATED, AttemptStatus.STARTING
        )
        repository.register_attempt_run(
            "attempt-observed-final",
            expected_generation=2,
            remote_run_id="remote-observed-final",
            dataset_id="dataset-observed-final",
        )
        repository.observe_attempt_result(
            "attempt-observed-final",
            remote_run_id="remote-observed-final",
            dataset_id="dataset-observed-final",
            actual_cost_usd=0.001,
            cost_final=True,
        )

    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(runtime.fetch(
            route_id=route_id,
            source_id=source_id,
            source_config={"target": "openai"},
            window=FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
            logical_job_id="new-job-after-observed-result",
        ))

    assert caught.value.code == "actorops_result_recovery_required"
    assert remote.requests == []
    store.close()


def test_requeued_job_replays_original_dataset_without_paid_post(tmp_path) -> None:
    store, repository, runtime, remote, route_id, source_id, candidates = _runtime(
        tmp_path, ["must-not-run"]
    )
    job_id = "job-dataset-result-recovery"
    _job(store, job_id, status="failed", source_id=source_id)
    candidate = repository.get_candidate(candidates[0])
    route = repository.get_route(route_id)
    binding = repository.get_binding(source_id)
    window = FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None)
    key = attempt_identity(
        DEFAULT_WORKSPACE_ID,
        job_id,
        source_id,
        binding.binding_version,
        candidate.candidate_id,
        kind="fetch",
    )
    with repository.transaction():
        repository.create_attempt(
            attempt_id="attempt-dataset-result-recovery",
            idempotency_key=key,
            route_id=route_id,
            source_id=source_id,
            candidate_id=candidate.candidate_id,
            kind="fetch",
            attempt_group_id=attempt_group_identity(
                DEFAULT_WORKSPACE_ID,
                job_id,
                source_id,
                binding.binding_version,
                kind="fetch",
            ),
            attempt_index=0,
            route_generation=route.generation,
            binding_version=binding.binding_version,
            target_fingerprint=binding.target_fingerprint,
            reserved_usd=route.per_run_cap_usd,
            logical_job_id=job_id,
            request_fingerprint=request_fingerprint(
                target_fingerprint=binding.target_fingerprint,
                candidate=candidate,
                route_cap_usd=route.per_run_cap_usd,
                window=window,
            ),
            window_since=window.since.isoformat(),
            max_items=window.max_items,
        )
        repository.transition_attempt(
            "attempt-dataset-result-recovery",
            AttemptStatus.CREATED,
            AttemptStatus.STARTING,
        )
        repository.register_attempt_run(
            "attempt-dataset-result-recovery",
            expected_generation=2,
            remote_run_id="remote-dataset-result-recovery",
            dataset_id="dataset-result-recovery",
        )
        repository.observe_attempt_result(
            "attempt-dataset-result-recovery",
            remote_run_id="remote-dataset-result-recovery",
            dataset_id="dataset-result-recovery",
            actual_cost_usd=0.000996,
            cost_final=True,
        )
    remote.datasets["dataset-result-recovery"] = ({"semantic": "valid_nonempty"},)
    observed = repository.get_attempt("attempt-dataset-result-recovery")
    ledger = _Ledger(
        {
            "attempt-dataset-result-recovery": ReconciliationRunResolution(
                _link(
                    "reservation-dataset-result-recovery",
                    remote="remote-dataset-result-recovery",
                )
            )
        },
        {
            "reservation-dataset-result-recovery": ReconciliationRunObservation(
                "succeeded", 0.000996, True, "dataset-result-recovery"
            )
        },
    )

    asyncio.run(
        ActorOpsReconciler(
            repository,
            ledger,
            now=lambda: datetime.fromisoformat(str(observed["updated_at"]))
            + timedelta(seconds=61),
        ).reconcile()
    )
    result = asyncio.run(
        runtime.fetch(
            route_id=route_id,
            source_id=source_id,
            source_config={"target": "openai"},
            window=window,
            logical_job_id=job_id,
        )
    )

    assert [item.id for item in result.items] == ["actor:test:openai"]
    assert remote.requests == []
    assert remote.dataset_reads == [("dataset-result-recovery", 3)]
    attempt = repository.get_attempt("attempt-dataset-result-recovery")
    assert attempt["status"] == "succeeded"
    assert attempt["result_state"] == "validated"
    store.close()
