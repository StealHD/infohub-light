from __future__ import annotations

import asyncio

import pytest

from src.services.apify_actor_ops import (
    ActorOpsError,
    ApifyActorOpsService,
    RouteInvocationResult,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def test_stale_response_only_degrades_the_affected_source(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = next(item for item in ops.list_routes() if item["route_key"] == "x/profile")
    route_id = str(route["route_id"])
    active = [slot for slot in ops.get_route(route_id)["slots"] if slot["candidate_state"] != "disabled"]
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Target scope test",
        config={"platform": "x", "kind": "profile", "target": "example"},
    )
    ops.bind_source(
        source_id=source_id,
        route_id=route_id,
        target_fingerprint="a" * 64,
        mode="primary",
    )
    store.connect().execute(
        """UPDATE apify_source_route_bindings
           SET watermark_latest_published_at = ?, validation_status = 'legacy_validation_pending'
           WHERE workspace_id = ? AND source_id = ?""",
        ("2030-01-02T00:00:00+00:00", DEFAULT_WORKSPACE_ID, source_id),
    )
    store.connect().commit()

    async def invoke(slot, _snapshot):
        if slot.candidate_id == str(active[0]["candidate_id"]):
            return RouteInvocationResult(
                value=["old-result"], semantic_outcome="valid_nonempty",
                latest_published_at="2030-01-01T00:00:00+00:00",
                latest_item_id="old-result", cost_usd=0.01,
            )
        return RouteInvocationResult(value=[], semantic_outcome="valid_empty", cost_usd=0.01)

    snapshot = ops.freeze_execution(route_id, source_id=source_id, enforce_gate=False)
    with pytest.raises(ActorOpsError) as exhausted:
        asyncio.run(ops.execute_route(route_id, source_id, invoke, frozen_snapshot=snapshot))
    assert exhausted.value.code == "apify_actor_route_exhausted"

    primary = next(
        slot for slot in ops.get_route(route_id)["slots"]
        if slot["candidate_id"] == active[0]["candidate_id"]
    )
    assert primary["candidate_state"] != "open"
    health = store.connect().execute(
        """SELECT last_semantic_outcome FROM apify_actor_target_health
           WHERE workspace_id = ? AND route_key = ? AND candidate_id = ? AND source_id = ?""",
        (DEFAULT_WORKSPACE_ID, "x/profile", active[0]["candidate_id"], source_id),
    ).fetchone()
    assert health["last_semantic_outcome"] == "stale_regression"
