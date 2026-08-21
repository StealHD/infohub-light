from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.services.actorops.ports import DiscoveryRevision
from src.services.actorops.repository import ActorOpsRepository
from src.services.actorops.store_metadata import normalize_store_metadata
from src.services.job_queue import JobQueue
from src.services.worker_actorops_v2_discovery import (
    WorkerActorOpsV2DiscoveryPorts,
    enqueue_due_actorops_v2_discoveries,
    run_actorops_v2_discovery,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


@dataclass
class _Catalog:
    def __init__(self) -> None:
        self.metadata_candidate_ids: list[str] = []

    async def search(self, _query):
        return ("publisher/actor",)

    async def get_revision(self, _actor_id):
        return DiscoveryRevision(
            actor_id="publisher/actor", publisher="publisher", build_id="build-1",
            build_number="1.0.0", price_per_run_usd=0.01,
            input_schema={"properties": {"profile": {}}},
            output_schema={"properties": {
                "id": {}, "url": {}, "createdAt": {}, "text": {}, "author": {},
            }},
        )

    async def store_metadata(self, candidate):
        self.metadata_candidate_ids.append(candidate.candidate_id)
        return normalize_store_metadata(
            {"actorId": candidate.actor_id, "title": "Public Actor"},
            fallback_slug=candidate.actor_id,
        )


def _job(store: ServiceStore) -> tuple[dict, str]:
    connection = store.connect()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="v2-discovery-owner",
        password="safe-test-password",
        role="owner",
    )
    route_id = str(connection.execute(
        "SELECT route_id FROM actor_routes_v2 WHERE platform='x'"
    ).fetchone()[0])
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        repository.create_discovery_job(
            discovery_id="worker-discovery", idempotency_key="worker-key",
            route_id=route_id, trigger_reason="test", input_fingerprint="a" * 64,
        )
    return {
        "workspace_id": DEFAULT_WORKSPACE_ID,
        "user_id": owner["id"],
        "payload_json": {"discovery_id": "worker-discovery"},
    }, route_id


def test_v2_discovery_handler_runs_with_injected_catalog(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "true")
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    job, _route_id = _job(store)

    catalog = _Catalog()
    result = run_actorops_v2_discovery(
        job, data_dir=str(store.data_dir), store=store,
        ports=WorkerActorOpsV2DiscoveryPorts(lambda *_args: catalog),
    )

    assert result["status"] == "completed"
    assert result["job_type"] == "actorops_v2_discovery"
    linked = store.connect().execute(
        "SELECT candidate_id, status, rejection_code FROM actor_discovery_job_candidates_v2"
    ).fetchall()
    assert catalog.metadata_candidate_ids, [dict(row) for row in linked]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM actor_candidate_store_metadata_v2"
    ).fetchone()[0] == 1
    store.close()


def test_flag_off_discovery_queue_is_inert_and_does_not_query_v2(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ACTOROPS_V2_ENABLED", raising=False)
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    _job(store)
    statements: list[str] = []
    store.connect().set_trace_callback(statements.append)

    summary = enqueue_due_actorops_v2_discoveries(store, JobQueue(store))

    assert summary == {"enqueued": 0, "deferred": 0}
    assert not any("actor_discovery_jobs_v2" in statement for statement in statements)
    store.close()


def test_due_v2_discovery_enqueues_once_without_touching_v1_runs(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "true")
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    _job(store)
    queue = JobQueue(store)

    first = enqueue_due_actorops_v2_discoveries(store, queue)
    second = enqueue_due_actorops_v2_discoveries(store, queue)

    rows = store.connect().execute(
        "SELECT job_type, payload_json FROM fetch_jobs WHERE job_type='actorops_v2_discovery'"
    ).fetchall()
    assert first["enqueued"] == 1
    assert second["enqueued"] == 0
    assert len(rows) == 1 and "worker-discovery" in rows[0]["payload_json"]
    assert store.connect().execute("SELECT COUNT(*) FROM apify_actor_discovery_runs").fetchone()[0] == 0
    store.close()


def test_flag_off_handler_fails_before_global_v2_access(tmp_path, monkeypatch) -> None:
    monkeypatch.delenv("ACTOROPS_V2_ENABLED", raising=False)
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    job, _route_id = _job(store)
    statements: list[str] = []
    store.connect().set_trace_callback(statements.append)

    with pytest.raises(RuntimeError, match="actorops_v2_disabled"):
        run_actorops_v2_discovery(job, data_dir=str(store.data_dir), store=store)

    assert not any("actor_discovery_jobs_v2" in statement for statement in statements)
    store.close()
