from __future__ import annotations

import asyncio

import pytest

from src.services.apify_actor_discovery import (
    ActorDiscoveryError,
    ApifyActorDiscoveryService,
)
from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import ServiceStore


class _Metadata:
    def __init__(
        self,
        *,
        output_fields: dict[str, object],
        actor_name: str = "x-profile-tweets",
        description: str = "Fetch posts from one X profile",
    ) -> None:
        self.output_fields = output_fields
        self.actor_name = actor_name
        self.description = description
        self.inputs: list[dict[str, object]] = []

    async def get_actor(self, _actor_id: str) -> dict[str, object]:
        return {
            "actorId": f"publisher/{self.actor_name}",
            "username": "publisher",
            "name": self.actor_name,
            "description": self.description,
            "isPublic": True,
            "isRunnable": True,
            "isDeprecated": False,
            "actorPermissionLevel": "LIMITED_PERMISSIONS",
            "taggedBuilds": {
                "latest": {"buildId": "x-build", "buildNumber": "2.0.0"}
            },
            "pricingInfos": [{
                "startedAt": "2020-01-01T00:00:00Z",
                "pricingModel": "PAY_PER_EVENT",
                "minimalMaxTotalChargeUsd": 0.01,
                "pricingPerEvent": {
                    "actorChargeEvents": {"item": {"eventPriceUsd": 0.01}}
                },
            }],
        }

    async def get_build(self, _build_id: str) -> dict[str, object]:
        return {
            "status": "SUCCEEDED",
            "buildNumber": "2.0.0",
            "inputSchema": {
                "type": "object",
                "properties": {
                    "profileUrls": {
                        "type": "array", "items": {"type": "string"}
                    },
                    "resultsLimit": {"type": "integer"},
                },
            },
            "datasetSchema": {"fields": self.output_fields},
        }

    async def validate_input(
        self,
        _actor_id: str,
        _build_number: str,
        actor_input: dict[str, object],
    ) -> bool:
        self.inputs.append(dict(actor_input))
        return True


_ITEM_FIELDS: dict[str, object] = {
    "tweetId": {"type": "string"},
    "tweetUrl": {"type": "string"},
    "publishedAt": {"type": "string"},
    "tweetCreatedAt": {"type": "string"},
    "tweetText": {"type": "string"},
    "text": {"type": "string"},
    "authorHandle": {"type": "string"},
}


def _service(tmp_path, metadata: _Metadata) -> ApifyActorDiscoveryService:
    store = ServiceStore(tmp_path)
    store.initialize()
    return ApifyActorDiscoveryService(
        ApifyActorOpsService(store), metadata, lambda _prompt: {}
    )


def test_free_compatibility_preflight_requires_real_x_item_contract(tmp_path) -> None:
    metadata = _Metadata(output_fields=_ITEM_FIELDS)
    candidate = asyncio.run(
        _service(tmp_path, metadata).load_compatibility_candidate(
            "publisher/x-profile-tweets", per_run_cap_usd=0.02
        )
    )
    assert candidate.build_number == "2.0.0"
    assert metadata.inputs == [
        {"profileUrls": ["https://x.com/apify"], "resultsLimit": 1}
    ]

    with pytest.raises(ActorDiscoveryError) as error:
        asyncio.run(
            _service(tmp_path, _Metadata(output_fields={"views": {"type": "object"}}))
            .load_compatibility_candidate(
                "publisher/x-profile-tweets", per_run_cap_usd=0.02
            )
        )
    assert error.value.code == "actor_output_contract_unverifiable"

    with pytest.raises(ActorDiscoveryError) as error:
        asyncio.run(
            _service(
                tmp_path,
                _Metadata(
                    output_fields=_ITEM_FIELDS,
                    actor_name="x-profile-replies",
                    description="Fetch replies to an X profile",
                ),
            ).load_compatibility_candidate(
                "publisher/x-profile-replies", per_run_cap_usd=0.02
            )
        )
    assert error.value.code == "actor_x_profile_semantics_mismatch"
