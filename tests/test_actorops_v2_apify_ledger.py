from __future__ import annotations

import asyncio
from pathlib import Path

from src.services.actorops.apify_ledger import ApifyRunLedger
from src.services.actorops.domain import AttemptStatus, CandidateLifecycle
from src.services.actorops.ports import ReconciliationRunLink
from src.services.actorops.repository import ActorOpsRepository
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _attempt(tmp_path: Path) -> tuple[ServiceStore, ActorOpsRepository, object]:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    route_id = str(connection.execute(
        "SELECT route_id FROM actor_routes_v2 WHERE platform='youtube'"
    ).fetchone()[0])
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        repository.create_candidate(
            candidate_id="candidate-ledger",
            route_id=route_id,
            actor_id="publisher/ledger",
            publisher="publisher",
            build_id="build-ledger",
            build_number="1",
            manifest_json='{"version":1}',
            manifest_hash="a" * 64,
            input_schema_hash="b" * 64,
            output_schema_hash="c" * 64,
            lifecycle=CandidateLifecycle.PROBATIONARY,
        )
        repository.create_attempt(
            attempt_id="attempt-ledger",
            idempotency_key="ledger-key",
            route_id=route_id,
            candidate_id="candidate-ledger",
            kind="fetch",
            attempt_group_id="group",
            attempt_index=0,
            route_generation=1,
            binding_version=None,
            target_fingerprint="1" * 64,
            reserved_usd=0.05,
        )
        repository.transition_attempt("attempt-ledger", AttemptStatus.CREATED, AttemptStatus.STARTING)
        repository.transition_attempt("attempt-ledger", AttemptStatus.STARTING, AttemptStatus.START_UNKNOWN)
    return store, repository, repository.get_attempt("attempt-ledger")


def _reservation(store: ServiceStore, reservation_id: str, *, remote_run_id: str | None = None) -> None:
    stamp = "2026-08-20T00:00:00+00:00"
    store.connect().execute(
        """INSERT INTO apify_actor_runs (
               id, workspace_id, logical_run_id, purpose, secret_id, secret_version,
               pool_generation, remote_run_id, dataset_id, status, created_at, updated_at
           ) VALUES (?, ?, 'attempt-ledger', 'acquisition', 'secret-ledger', 1,
                     1, ?, ?, ?, ?, ?)""",
        (
            reservation_id,
            DEFAULT_WORKSPACE_ID,
            remote_run_id,
            "dataset-ledger" if remote_run_id else None,
            "running" if remote_run_id else "reserved",
            stamp,
            stamp,
        ),
    )
    store.connect().commit()


def test_apify_ledger_links_one_exact_reservation_and_fails_closed_on_duplicates(tmp_path: Path) -> None:
    store, _repository, attempt = _attempt(tmp_path)
    _reservation(store, "reservation-a")
    ledger = ApifyRunLedger(store, workspace_id=DEFAULT_WORKSPACE_ID)

    result = asyncio.run(ledger.resolve(attempt))

    assert result.ambiguous is False
    assert result.link and result.link.reservation_id == "reservation-a"
    _reservation(store, "reservation-b")
    duplicate = asyncio.run(ledger.resolve(attempt))
    assert duplicate.link is None
    assert duplicate.ambiguous is True
    store.close()


def test_apify_ledger_reads_existing_run_and_settles_only_its_reservation(tmp_path: Path, monkeypatch) -> None:
    store, _repository, attempt = _attempt(tmp_path)
    _reservation(store, "reservation-known", remote_run_id="remote-known")
    calls: list[str] = []

    class _Coordinator:
        def lease_for_run(self, reservation_id):
            assert reservation_id in {"reservation-known", "reservation-empty"}
            return object()

        def get_run(self, reservation_id):
            assert reservation_id == "reservation-known"
            return {
                "status": "succeeded",
                "charge_actual_usd": 0.04,
                "charge_final": 1,
                "dataset_id": "dataset-known",
            }

    class _Client:
        def __init__(self, **_kwargs):
            pass

        async def refresh_registered_run_status(self, _lease, run_id):
            calls.append(f"get:{run_id}")
            return "succeeded"

        async def prove_no_user_run_in_window(self, *_args, **_kwargs):
            calls.append("prove")
            return True

    monkeypatch.setattr("src.services.actorops.apify_ledger.apify_coordinator_for_workspace", lambda *_args, **_kwargs: _Coordinator())
    monkeypatch.setattr("src.services.actorops.apify_ledger.ApifyClient", _Client)
    ledger = ApifyRunLedger(store, workspace_id=DEFAULT_WORKSPACE_ID)
    link = asyncio.run(ledger.resolve(attempt)).link
    assert link is not None
    observation = asyncio.run(ledger.read_known(link))
    assert calls == ["get:remote-known"]
    assert observation.status == "succeeded"
    assert observation.actual_cost_usd == 0.04

    _reservation(store, "reservation-empty")
    no_start = ReconciliationRunLink(
        reservation_id="reservation-empty",
        remote_run_id=None,
        dataset_id=None,
        status="reserved",
        created_at="2026-08-20T00:00:00+00:00",
        updated_at="2026-08-20T00:00:00+00:00",
    )
    assert asyncio.run(ledger.prove_no_start(no_start)) is True
    asyncio.run(ledger.settle_proven_no_start(no_start))
    row = store.connect().execute(
        "SELECT status, charge_actual_usd, charge_final FROM apify_actor_runs WHERE id='reservation-empty'"
    ).fetchone()
    assert tuple(row) == ("start_rejected", 0.0, 1)
    assert calls == ["get:remote-known", "prove"]
    source = Path("src/services/actorops/apify_ledger.py").read_text()
    assert "run_actor_detailed" not in source
    assert ".abort" not in source
    store.close()
