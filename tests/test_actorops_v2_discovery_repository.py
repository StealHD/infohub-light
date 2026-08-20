from __future__ import annotations

import pytest

from src.services.actorops.domain import DiscoveryStage, DiscoveryStatus
from src.services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def test_discovery_checkpoint_uses_status_stage_generation_cas(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = str(store.connect().execute(
        "SELECT route_id FROM actor_routes_v2 WHERE platform='x'"
    ).fetchone()[0])
    repository = ActorOpsRepository(store.connect(), DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        repository.create_discovery_job(
            discovery_id="checkpoint", idempotency_key="checkpoint-key", route_id=route_id,
            trigger_reason="test", input_fingerprint="a" * 64,
        )
    row = repository.discovery.get("checkpoint")
    with repository.transaction():
        repository.discovery.checkpoint(
            "checkpoint", expected_status=DiscoveryStatus.QUEUED,
            expected_stage=DiscoveryStage.STORE_SEARCH, expected_generation=int(row["generation"]),
            status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.STORE_SEARCH,
            checkpoint_hash="b" * 64, search_cursor='{"phase":"metadata"}',
            query_count=1, candidate_count=0, rejection_count=0,
        )
    with repository.transaction(), pytest.raises(ActorOpsConflict):
        repository.discovery.checkpoint(
            "checkpoint", expected_status=DiscoveryStatus.QUEUED,
            expected_stage=DiscoveryStage.STORE_SEARCH, expected_generation=int(row["generation"]),
            status=DiscoveryStatus.RUNNING, stage=DiscoveryStage.STORE_SEARCH,
            checkpoint_hash=None, search_cursor=None, query_count=0,
            candidate_count=0, rejection_count=0,
        )
    store.close()


def test_discovery_idempotency_returns_the_existing_job(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = str(store.connect().execute(
        "SELECT route_id FROM actor_routes_v2 WHERE platform='x'"
    ).fetchone()[0])
    repository = ActorOpsRepository(store.connect(), DEFAULT_WORKSPACE_ID)
    values = {
        "discovery_id": "idempotent", "idempotency_key": "idempotent-key",
        "route_id": route_id, "trigger_reason": "test", "input_fingerprint": "b" * 64,
    }
    with repository.transaction():
        first, created = repository.discovery.ensure(**values)
    with repository.transaction():
        second, repeated = repository.discovery.ensure(**values)

    assert created is True and repeated is False
    assert first["discovery_id"] == second["discovery_id"] == "idempotent"
    store.close()
