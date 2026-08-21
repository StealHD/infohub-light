from __future__ import annotations

import asyncio

from test_apify_actor_discovery_v15 import (
    ActorDiscoveryError,
    ApifyActorDiscoveryService,
    FIXED_NOW,
    _Metadata,
)

from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import ServiceStore


def test_ai_failure_preserves_deterministic_youtube_observation_candidate(tmp_path) -> None:
    class MixedMetadata(_Metadata):
        async def get_build(self, build_id: str):
            build = await super().get_build(build_id)
            if build_id == "build-1":
                build["actorDefinition"]["storages"]["dataset"]["fields"] = {}
            return build

    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    ops.patch_discovery_settings(expected_generation=1, enabled=True, call_limit=3)
    route = next(
        item for item in ops.list_routes() if item["route_key"] == "youtube/channel/items"
    )
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="manual_slot_candidate_refresh",
        expected_generation=int(route["generation"]),
    )

    async def unavailable_ai(_prompt: dict):
        raise ActorDiscoveryError("discovery_ai_invalid_json", "invalid JSON")

    outcome = asyncio.run(
        ApifyActorDiscoveryService(ops, MixedMetadata(), unavailable_ai).run_discovery(
            str(run["run_id"]), queries=["youtube channel"]
        )
    )

    assert outcome.stage == "awaiting_canary_approval"
    assert len(outcome.revision_ids) == 1
    assert {entry["reason"] for entry in outcome.rejected} >= {
        "discovery_ai_invalid_json"
    }
