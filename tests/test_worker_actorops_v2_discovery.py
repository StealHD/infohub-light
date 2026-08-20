from __future__ import annotations

from dataclasses import dataclass

import pytest

from src.services.actorops.ports import DiscoveryRevision
from src.services.actorops.repository import ActorOpsRepository
from src.services.job_queue import JobQueue
from src.services.worker_actorops_v2_discovery import (
    WorkerActorOpsV2DiscoveryPorts,
    enqueue_due_actorops_v2_discoveries,
    run_actorops_v2_discovery,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


@dataclass
class _Catalog:
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

    result = run_actorops_v2_discovery(
        job, data_dir=str(store.data_dir), store=store,
        ports=WorkerActorOpsV2DiscoveryPorts(lambda *_args: _Catalog()),
    )

    assert result["status"] == "completed"
    assert result["job_type"] == "actorops_v2_discovery"
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
