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
from src.storage.actorops_v2_single_track_schema import MIGRATION_VERSION


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


def test_v2_discovery_handler_runs_with_injected_catalog(tmp_path) -> None:
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


def test_v2_discovery_keeps_store_identity_for_mapping_pending_candidate(
    tmp_path,
) -> None:
    class _PendingCatalog(_Catalog):
        async def get_revision(self, actor_id):
            revision = await super().get_revision(actor_id)
            return DiscoveryRevision(
                actor_id=revision.actor_id,
                publisher=revision.publisher,
                build_id=revision.build_id,
                build_number=revision.build_number,
                price_per_run_usd=revision.price_per_run_usd,
                input_schema=revision.input_schema,
                output_schema={"properties": {"results": {"type": "string"}}},
            )

    store = ServiceStore(tmp_path / "data")
    store.initialize()
    job, _route_id = _job(store)
    catalog = _PendingCatalog()

    result = run_actorops_v2_discovery(
        job, data_dir=str(store.data_dir), store=store,
        ports=WorkerActorOpsV2DiscoveryPorts(lambda *_args: catalog),
    )
    row = store.connect().execute(
        """SELECT candidate.lifecycle, metadata.display_name
             FROM actor_candidates_v2 AS candidate
             JOIN actor_candidate_store_metadata_v2 AS metadata
               ON metadata.candidate_id=candidate.candidate_id"""
    ).fetchone()

    assert result["status"] == "completed"
    assert dict(row) == {
        "lifecycle": "mapping_pending",
        "display_name": "Public Actor",
    }
    store.close()


def test_discovery_queue_requires_global_30(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    store.connect().execute(
        "DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    )
    store.connect().commit()

    with pytest.raises(RuntimeError, match="migration_required"):
        enqueue_due_actorops_v2_discoveries(store, JobQueue(store))
    store.close()


def test_due_v2_discovery_enqueues_once_without_touching_v1_runs(tmp_path) -> None:
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
    assert store.connect().execute(
        "SELECT 1 FROM sqlite_master WHERE type='table' AND name='apify_actor_discovery_runs'"
    ).fetchone() is None
    store.close()


def test_handler_requires_global_30_before_discovery_access(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    job, _route_id = _job(store)
    store.connect().execute(
        "DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
    )
    store.connect().commit()

    with pytest.raises(RuntimeError, match="migration_required"):
        run_actorops_v2_discovery(job, data_dir=str(store.data_dir), store=store)
    store.close()
