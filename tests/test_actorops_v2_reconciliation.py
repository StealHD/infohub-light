from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

from src.services.actorops.domain import AttemptStatus, CandidateLifecycle
from src.services.actorops.ports import (
    ReconciliationRunLink,
    ReconciliationRunObservation,
    ReconciliationRunResolution,
)
from src.services.actorops.reconciliation import ActorOpsReconciler
from src.services.actorops.repository import ActorOpsRepository
from src.services.actorops.repository_resilience import ResilienceRepository
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


@dataclass
class _Ledger:
    links: dict[str, ReconciliationRunResolution]
    observations: dict[str, ReconciliationRunObservation] = field(default_factory=dict)
    no_start: set[str] = field(default_factory=set)
    fail_reads: set[str] = field(default_factory=set)
    reads: list[str] = field(default_factory=list)
    settled: list[str] = field(default_factory=list)

    async def resolve(self, attempt):
        return self.links[str(attempt["attempt_id"])]

    async def read_known(self, link):
        self.reads.append(link.reservation_id)
        if link.reservation_id in self.fail_reads:
            raise RuntimeError("read failed")
        return self.observations[link.reservation_id]

    async def prove_no_start(self, link):
        self.reads.append(link.reservation_id)
        return link.reservation_id in self.no_start

    async def settle_proven_no_start(self, link):
        self.settled.append(link.reservation_id)


def _link(name: str, *, remote: str | None = "remote-1") -> ReconciliationRunLink:
    return ReconciliationRunLink(
        reservation_id=name,
        remote_run_id=remote,
        dataset_id="dataset" if remote else None,
        status="running" if remote else "reserved",
        created_at="2026-08-20T00:00:00+00:00",
        updated_at="2026-08-20T00:00:31+00:00",
    )


def _repository(tmp_path: Path) -> tuple[ServiceStore, ActorOpsRepository, str]:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = str(store.connect().execute(
        "SELECT route_id FROM actor_routes_v2 WHERE platform='youtube'"
    ).fetchone()[0])
    repository = ActorOpsRepository(store.connect(), DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        repository.create_candidate(
            candidate_id="candidate-reconcile",
            route_id=route_id,
            actor_id="publisher/reconcile",
            publisher="publisher",
            build_id="build-reconcile",
            build_number="1",
            manifest_json='{"version":1}',
            manifest_hash="a" * 64,
            input_schema_hash="b" * 64,
            output_schema_hash="c" * 64,
            lifecycle=CandidateLifecycle.PROBATIONARY,
        )
    return store, repository, route_id


def _job(store: ServiceStore, job_id: str, *, status: str) -> None:
    user = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username=f"owner-{job_id}",
        password="safe-test-password",
        role="owner",
    )
    stamp = "2026-08-20T00:00:00+00:00"
    store.connect().execute(
        """INSERT INTO fetch_jobs (
               id, workspace_id, user_id, job_type, status, payload_json,
               finished_at, created_at, updated_at
           ) VALUES (?, ?, ?, 'source_fetch', ?, '{}', ?, ?, ?)""",
        (
            job_id,
            DEFAULT_WORKSPACE_ID,
            str(user["id"]),
            status,
            stamp if status not in {"queued", "running"} else None,
            stamp,
            stamp,
        ),
    )
    store.connect().commit()


def _attempt(repository: ActorOpsRepository, route_id: str, attempt_id: str, status: AttemptStatus) -> None:
    with repository.transaction():
        repository.create_attempt(
            attempt_id=attempt_id,
            idempotency_key=f"key-{attempt_id}",
            route_id=route_id,
            candidate_id="candidate-reconcile",
            kind="fetch",
            attempt_group_id="group",
            attempt_index=0,
            route_generation=1,
            binding_version=None,
            target_fingerprint="1" * 64,
            reserved_usd=0.05,
        )
        repository.transition_attempt(attempt_id, AttemptStatus.CREATED, AttemptStatus.STARTING)
        if status is AttemptStatus.START_UNKNOWN:
            repository.transition_attempt(attempt_id, AttemptStatus.STARTING, status)
            return
        repository.register_attempt_run(
            attempt_id,
            expected_generation=2,
            remote_run_id=f"remote-{attempt_id}",
            dataset_id="dataset",
        )
        if status is AttemptStatus.REGISTERED:
            return
        repository.transition_attempt(attempt_id, AttemptStatus.REGISTERED, AttemptStatus.RUNNING)
        if status is AttemptStatus.RUNNING:
            return
        repository.complete_attempt(
            attempt_id,
            status=status,
            semantic_outcome="advanced",
            actual_cost_usd=None,
            cost_final=False,
        )


def test_reconciler_observes_lost_success_without_publishing(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    _attempt(repository, route_id, "attempt-lost", AttemptStatus.RUNNING)
    ledger = _Ledger(
        {"attempt-lost": ReconciliationRunResolution(_link("reservation-lost", remote="remote-attempt-lost"))},
        {"reservation-lost": ReconciliationRunObservation("SUCCEEDED", 0.03, True, "dataset")},
    )

    summary = asyncio.run(
        ActorOpsReconciler(
            repository,
            ledger,
            now=lambda: datetime.now(timezone.utc) + timedelta(seconds=61),
        ).reconcile()
    )

    row = repository.get_attempt("attempt-lost")
    assert summary.settled == 1
    assert row["status"] == "running"
    assert row["semantic_outcome"] is None
    assert row["actual_cost_usd"] == pytest.approx(0.03)
    assert row["cost_final"] == 1
    assert row["result_state"] == "observed"
    assert asyncio.run(ActorOpsReconciler(repository, ledger).reconcile()).scanned == 0
    assert store.connect().execute("SELECT COUNT(*) FROM actor_source_bindings_v2").fetchone()[0] == 0
    store.close()


def test_reconciler_does_not_settle_fresh_success_during_runtime_mapping(
    tmp_path: Path,
) -> None:
    store, repository, route_id = _repository(tmp_path)
    _attempt(repository, route_id, "attempt-fresh", AttemptStatus.RUNNING)
    attempt = repository.get_attempt("attempt-fresh")
    observed_at = datetime.fromisoformat(str(attempt["updated_at"]))
    ledger = _Ledger(
        {"attempt-fresh": ReconciliationRunResolution(_link("reservation-fresh", remote="remote-attempt-fresh"))},
        {"reservation-fresh": ReconciliationRunObservation("succeeded", 0.03, True, "dataset")},
    )

    summary = asyncio.run(
        ActorOpsReconciler(
            repository,
            ledger,
            now=lambda: observed_at + timedelta(seconds=59),
        ).reconcile()
    )

    current = repository.get_attempt("attempt-fresh")
    assert summary.pending == 1
    assert summary.settled == 0
    assert current["status"] == "running"
    assert current["error_code"] is None
    store.close()


def test_reconciler_settles_terminal_cost_and_proven_no_start(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    _attempt(repository, route_id, "attempt-terminal", AttemptStatus.SUCCEEDED)
    _attempt(repository, route_id, "attempt-unknown", AttemptStatus.START_UNKNOWN)
    ledger = _Ledger(
        {
            "attempt-terminal": ReconciliationRunResolution(_link("reservation-terminal", remote="remote-attempt-terminal")),
            "attempt-unknown": ReconciliationRunResolution(_link("reservation-unknown", remote=None)),
        },
        {"reservation-terminal": ReconciliationRunObservation("succeeded", 0.02, True)},
        no_start={"reservation-unknown"},
    )

    summary = asyncio.run(ActorOpsReconciler(repository, ledger).reconcile())

    terminal = repository.get_attempt("attempt-terminal")
    unknown = repository.get_attempt("attempt-unknown")
    assert summary.settled == 2
    assert terminal["status"] == "succeeded"
    assert terminal["actual_cost_usd"] == pytest.approx(0.02)
    assert terminal["cost_final"] == 1
    assert unknown["status"] == "failed"
    assert unknown["error_code"] == "actorops_proven_no_start"
    assert unknown["actual_cost_usd"] == 0
    assert ledger.settled == ["reservation-unknown"]
    store.close()


def test_reconciler_repairs_terminal_attempt_from_settled_start_rejection(
    tmp_path: Path,
) -> None:
    store, repository, route_id = _repository(tmp_path)
    with repository.transaction():
        repository.create_attempt(
            attempt_id="attempt-rejected",
            idempotency_key="key-attempt-rejected",
            route_id=route_id,
            candidate_id="candidate-reconcile",
            kind="fetch",
            attempt_group_id="group",
            attempt_index=0,
            route_generation=1,
            binding_version=None,
            target_fingerprint="1" * 64,
            reserved_usd=0.05,
            logical_job_id="job-rejected",
            request_fingerprint="2" * 64,
            window_since="2026-08-20T00:00:00+00:00",
            max_items=1,
            request_schema_version=1,
        )
        repository.transition_attempt(
            "attempt-rejected", AttemptStatus.CREATED, AttemptStatus.STARTING
        )
        repository.complete_attempt(
            "attempt-rejected",
            status=AttemptStatus.FAILED,
            semantic_outcome="apify_actor_start_rejected",
            actual_cost_usd=None,
            cost_final=False,
        )
    stamp = "2026-08-20T00:00:01+00:00"
    store.connect().execute(
        """INSERT INTO apify_actor_runs (
               id, workspace_id, logical_run_id, purpose, secret_id,
               secret_version, pool_generation, status, charge_reserved_usd,
               charge_actual_usd, charge_final, created_at, terminal_at, updated_at
           ) VALUES ('reservation-rejected', ?, 'attempt-rejected', 'acquisition',
                     'secret-rejected', 1, 1, 'start_rejected', 0, 0, 1, ?, ?, ?)""",
        (DEFAULT_WORKSPACE_ID, stamp, stamp, stamp),
    )
    store.connect().commit()
    ledger = _Ledger(
        {
            "attempt-rejected": ReconciliationRunResolution(
                ReconciliationRunLink(
                    reservation_id="reservation-rejected",
                    remote_run_id=None,
                    dataset_id=None,
                    status="start_rejected",
                    created_at="2026-08-20T00:00:00+00:00",
                    updated_at="2026-08-20T00:00:01+00:00",
                )
            )
        }
    )

    summary = asyncio.run(ActorOpsReconciler(repository, ledger).reconcile())

    row = repository.get_attempt("attempt-rejected")
    assert summary.settled == 1
    assert summary.remote_reads == 0
    assert row["status"] == "failed"
    assert row["actual_cost_usd"] == 0
    assert row["cost_final"] == 1
    assert ledger.reads == []
    assert ledger.settled == ["reservation-rejected"]
    store.close()


def test_reconciler_settles_created_only_after_terminal_job_and_no_reservation(
    tmp_path: Path,
) -> None:
    store, repository, route_id = _repository(tmp_path)
    _job(store, "job-ended", status="failed")
    _job(store, "job-active", status="queued")
    _job(store, "job-unresolved", status="failed")
    with repository.transaction():
        for attempt_id, job_id in (
            ("attempt-created-ended", "job-ended"),
            ("attempt-created-active", "job-active"),
            ("attempt-created-unresolved", "job-unresolved"),
        ):
            repository.create_attempt(
                attempt_id=attempt_id,
                idempotency_key=f"key-{attempt_id}",
                route_id=route_id,
                candidate_id="candidate-reconcile",
                kind="fetch",
                attempt_group_id="group-created",
                attempt_index=0,
                route_generation=1,
                binding_version=None,
                target_fingerprint="1" * 64,
                reserved_usd=0.05,
                logical_job_id=job_id,
            )
    stamp = "2026-08-20T00:00:01+00:00"
    store.connect().execute(
        """INSERT INTO apify_actor_runs (
               id, workspace_id, logical_run_id, purpose, secret_id,
               secret_version, pool_generation, status,
               created_at, terminal_at, updated_at
           ) VALUES ('reservation-unresolved', ?, 'attempt-created-unresolved',
                     'acquisition', 'secret-unresolved', 1, 1, 'failed', ?, ?, ?)""",
        (DEFAULT_WORKSPACE_ID, stamp, stamp, stamp),
    )
    store.connect().commit()
    ledger = _Ledger(
        {
            "attempt-created-ended": ReconciliationRunResolution(
                None, reservation_absent=True
            ),
            "attempt-created-unresolved": ReconciliationRunResolution(None),
        }
    )

    summary = asyncio.run(ActorOpsReconciler(repository, ledger).reconcile())

    ended = repository.get_attempt("attempt-created-ended")
    active = repository.get_attempt("attempt-created-active")
    unresolved = repository.get_attempt("attempt-created-unresolved")
    assert summary.scanned == 2
    assert summary.settled == 1
    assert summary.pending == 1
    assert (ended["status"], ended["actual_cost_usd"], ended["cost_final"]) == (
        "cancelled",
        0.0,
        1,
    )
    assert active["status"] == "created"
    assert active["cost_final"] == 0
    assert unresolved["status"] == "created"
    assert unresolved["cost_final"] == 0
    assert unresolved["error_code"] == "actorops_reconcile_run_missing"
    store.close()


def test_reconciler_settles_exact_rejected_start_but_not_missing_start(
    tmp_path: Path,
) -> None:
    store, repository, route_id = _repository(tmp_path)
    _job(store, "job-rejected-start", status="failed")
    _job(store, "job-missing-start", status="failed")
    with repository.transaction():
        for attempt_id, job_id in (
            ("attempt-rejected-start", "job-rejected-start"),
            ("attempt-missing-start", "job-missing-start"),
        ):
            repository.create_attempt(
                attempt_id=attempt_id,
                idempotency_key=f"key-{attempt_id}",
                route_id=route_id,
                candidate_id="candidate-reconcile",
                kind="fetch",
                attempt_group_id="group-starting",
                attempt_index=0,
                route_generation=1,
                binding_version=None,
                target_fingerprint="1" * 64,
                reserved_usd=0.05,
                logical_job_id=job_id,
            )
            repository.transition_attempt(
                attempt_id, AttemptStatus.CREATED, AttemptStatus.STARTING
            )
    ledger = _Ledger(
        {
            "attempt-rejected-start": ReconciliationRunResolution(
                ReconciliationRunLink(
                    reservation_id="reservation-rejected-start",
                    remote_run_id=None,
                    dataset_id=None,
                    status="start_rejected",
                    created_at="2026-08-20T00:00:00+00:00",
                    updated_at="2026-08-20T00:00:01+00:00",
                )
            ),
            "attempt-missing-start": ReconciliationRunResolution(None),
        }
    )

    summary = asyncio.run(ActorOpsReconciler(repository, ledger).reconcile())

    rejected = repository.get_attempt("attempt-rejected-start")
    missing = repository.get_attempt("attempt-missing-start")
    assert summary.scanned == 2
    assert summary.settled == 1
    assert summary.pending == 1
    assert (rejected["status"], rejected["actual_cost_usd"], rejected["cost_final"]) == (
        "failed",
        0.0,
        1,
    )
    assert ledger.settled == ["reservation-rejected-start"]
    assert missing["status"] == "starting"
    assert missing["actual_cost_usd"] is None
    assert missing["cost_final"] == 0
    assert missing["error_code"] == "actorops_reconcile_run_missing"
    store.close()


def test_unknown_start_with_one_known_run_advances_without_reposting(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    _attempt(repository, route_id, "attempt-discovered", AttemptStatus.START_UNKNOWN)
    ledger = _Ledger(
        {"attempt-discovered": ReconciliationRunResolution(_link("reservation-discovered", remote="remote-discovered"))},
        {"reservation-discovered": ReconciliationRunObservation("running", None, False, "dataset-discovered")},
    )

    summary = asyncio.run(ActorOpsReconciler(repository, ledger).reconcile())

    row = repository.get_attempt("attempt-discovered")
    assert summary.pending == 1
    assert ledger.reads == ["reservation-discovered"]
    assert row["status"] == "running"
    assert row["remote_run_id"] == "remote-discovered"
    assert row["dataset_id"] == "dataset-discovered"
    store.close()


def test_reconciler_fails_closed_on_ambiguity_and_bounds_reads(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    links = {}
    observations = {}
    for index in range(7):
        attempt_id = f"attempt-{index}"
        _attempt(repository, route_id, attempt_id, AttemptStatus.RUNNING)
        links[attempt_id] = ReconciliationRunResolution(
            _link(f"reservation-{index}", remote=f"remote-{attempt_id}")
        )
        observations[f"reservation-{index}"] = ReconciliationRunObservation("running", None, False)
    links["attempt-0"] = ReconciliationRunResolution(None, ambiguous=True)
    ledger = _Ledger(links, observations)

    summary = asyncio.run(ActorOpsReconciler(repository, ledger, remote_read_limit=5).reconcile())

    assert summary.scanned == 7
    assert summary.ambiguous == 1
    assert len(ledger.reads) == 5
    assert repository.get_attempt("attempt-0")["error_code"] == "actorops_reconcile_ambiguous_run"
    assert repository.get_attempt("attempt-6")["error_code"] == "actorops_reconcile_deferred"
    store.close()


def test_reconciler_isolates_read_errors_and_uses_no_v1_sql_or_actor_starts(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    _attempt(repository, route_id, "attempt-error", AttemptStatus.RUNNING)
    _attempt(repository, route_id, "attempt-next", AttemptStatus.RUNNING)
    ledger = _Ledger(
        {
            "attempt-error": ReconciliationRunResolution(_link("reservation-error", remote="remote-attempt-error")),
            "attempt-next": ReconciliationRunResolution(_link("reservation-next", remote="remote-attempt-next")),
        },
        {"reservation-next": ReconciliationRunObservation("failed", 0.01, True)},
        fail_reads={"reservation-error"},
    )

    summary = asyncio.run(ActorOpsReconciler(repository, ledger).reconcile())

    assert summary.errors == 1
    assert repository.get_attempt("attempt-error")["error_code"] == "actorops_reconcile_read_failed"
    assert repository.get_attempt("attempt-next")["status"] == "failed"
    source = Path("src/services/actorops/reconciliation.py").read_text()
    assert "apify_actor_runs" not in source
    assert "run_actor" not in source
    assert "publish_success" not in source
    store.close()


def test_reconciler_counts_failed_remote_reads_against_the_bound(tmp_path: Path) -> None:
    store, repository, route_id = _repository(tmp_path)
    links = {}
    for index in range(7):
        attempt_id = f"attempt-read-failure-{index}"
        _attempt(repository, route_id, attempt_id, AttemptStatus.RUNNING)
        links[attempt_id] = ReconciliationRunResolution(
            _link(f"reservation-read-failure-{index}", remote=f"remote-{attempt_id}")
        )
    ledger = _Ledger(links, fail_reads=set(
        f"reservation-read-failure-{index}" for index in range(7)
    ))

    summary = asyncio.run(ActorOpsReconciler(repository, ledger, remote_read_limit=5).reconcile())

    assert summary.remote_reads == 5
    assert summary.errors == 5
    assert len(ledger.reads) == 5
    assert repository.get_attempt("attempt-read-failure-6")["error_code"] == "actorops_reconcile_deferred"
    store.close()


def test_reconciler_cools_only_candidate_failure_and_wakes_settled_repairs(
    tmp_path: Path, monkeypatch
) -> None:
    store, repository, route_id = _repository(tmp_path)
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Reconciliation source",
        config={"platform": "youtube", "kind": "channel", "target": "safe"},
    )
    fingerprint = "f" * 64
    with repository.transaction():
        repository.connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                   binding_id, workspace_id, source_id, route_id,
                   target_fingerprint, status, binding_version, created_at, updated_at
               ) VALUES ('binding-reconcile-cost', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
            (
                DEFAULT_WORKSPACE_ID, source_id, route_id, fingerprint,
                "2026-08-20T00:00:00+00:00", "2026-08-20T00:00:00+00:00",
            ),
        )

    def failed_attempt(attempt_id: str, logical_job_id: str, failure_class: str) -> None:
        with repository.transaction():
            repository.create_attempt(
                attempt_id=attempt_id,
                idempotency_key=f"key-{attempt_id}",
                route_id=route_id,
                source_id=source_id,
                candidate_id="candidate-reconcile",
                kind="fetch",
                attempt_group_id="group-reconcile-cost",
                attempt_index=0,
                route_generation=repository.get_route(route_id).generation,
                binding_version=1,
                target_fingerprint=fingerprint,
                reserved_usd=0.05,
                logical_job_id=logical_job_id,
            )
            repository.transition_attempt(
                attempt_id, AttemptStatus.CREATED, AttemptStatus.STARTING
            )
            repository.complete_attempt(
                attempt_id,
                status=AttemptStatus.FAILED,
                semantic_outcome="actorops_stale_regression",
                actual_cost_usd=None,
                cost_final=False,
                failure_class=failure_class,
                error_code="actorops_stale_regression",
            )

    failed_attempt("attempt-candidate-cost", "job-candidate-cost", "candidate")
    failed_attempt("attempt-remote-cost", "job-remote-cost", "remote_unknown")
    repository.resilience.record_stale_regression(
        binding=repository.get_binding(source_id),
        candidate_id="candidate-reconcile",
        logical_job_id="job-candidate-cost",
    )
    wakes: list[tuple[str, str]] = []

    def wake(_self, *, route_id: str, source_id: str) -> None:
        wakes.append((route_id, source_id))

    monkeypatch.setattr(
        ResilienceRepository,
        "wake_repairs_after_cost_settlement",
        wake,
        raising=False,
    )
    ledger = _Ledger(
        {
            "attempt-candidate-cost": ReconciliationRunResolution(
                _link("reservation-candidate-cost", remote="remote-candidate-cost")
            ),
            "attempt-remote-cost": ReconciliationRunResolution(
                _link("reservation-remote-cost", remote="remote-remote-cost")
            ),
        },
        {
            "reservation-candidate-cost": ReconciliationRunObservation(
                "failed", 0.01, True, "dataset-candidate"
            ),
            "reservation-remote-cost": ReconciliationRunObservation(
                "failed", 0.01, True, "dataset-remote"
            ),
        },
    )

    summary = asyncio.run(ActorOpsReconciler(repository, ledger).reconcile())

    circuit = repository.connection.execute(
        """SELECT failure_streak, last_outcome
             FROM actor_source_candidate_freshness_v2
            WHERE source_id=? AND candidate_id='candidate-reconcile'""",
        (source_id,),
    ).fetchone()
    assert summary.settled == 2
    assert tuple(circuit) == (1, "stale_regression")
    assert wakes == [(route_id, source_id), (route_id, source_id)]
    store.close()
