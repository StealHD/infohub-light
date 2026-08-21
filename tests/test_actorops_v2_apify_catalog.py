from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

from src.services.actorops.apify_catalog import ApifyDiscoveryCatalog
from src.services.actorops.domain import AssignmentRole, CandidateLifecycle, CandidateRecord


class _Metadata:
    async def search_store(self, _query):
        return ({"username": "publisher", "name": "actor"}, {"actorId": "publisher~actor"})

    async def get_actor(self, actor_id):
        assert actor_id == "publisher/actor"
        return {
            "username": "Publisher",
            "taggedBuilds": {"latest": {"buildId": "build-1", "buildNumber": "1.0.0"}},
            "pricingInfos": [{"pricePerRunUsd": 0.02}],
        }

    async def get_build(self, build_id):
        assert build_id == "build-1"
        return {
            "inputSchema": {"properties": {"profile": {"type": "string"}}},
            "datasetSchema": {"properties": {"id": {"type": "string"}}},
        }


def test_apify_catalog_reads_only_public_actor_build_metadata() -> None:
    catalog = ApifyDiscoveryCatalog(_Metadata())

    assert asyncio.run(catalog.search("profile actor")) == ("publisher/actor",)
    revision = asyncio.run(catalog.get_revision("publisher/actor"))

    assert revision.publisher == "publisher"
    assert revision.build_id == "build-1"
    assert revision.price_per_run_usd == 0.02
    assert revision.input_schema["properties"]
    source = Path("src/services/actorops/apify_catalog.py").read_text()
    assert "run_actor" not in source
    assert ".abort" not in source
    assert "dataset_items" not in source


def test_apify_catalog_estimates_nested_public_event_pricing() -> None:
    class _NestedPricing(_Metadata):
        async def get_actor(self, actor_id):
            actor = await super().get_actor(actor_id)
            actor["pricingInfos"] = [{
                "pricingModel": "PAY_PER_EVENT",
                "startedAt": "2026-01-01T00:00:00.000Z",
                "pricingPerEvent": {"actorChargeEvents": {
                    "apify-actor-start": {
                        "eventPriceUsd": 0.005,
                        "eventTitle": "Actor start",
                        "isOneTimeEvent": True,
                    },
                    "apify-default-dataset-item": {
                        "eventTitle": "Dataset item",
                        "isPrimaryEvent": True,
                        "eventTieredPricingUsd": {
                            "FREE": {"tieredEventPriceUsd": 0},
                            "BRONZE": {"tieredEventPriceUsd": 0.003},
                            "ENTERPRISE": {"tieredEventPriceUsd": 0.009},
                        },
                    },
                }},
            }]
            return actor

    revision = asyncio.run(ApifyDiscoveryCatalog(_NestedPricing()).get_revision("publisher/actor"))

    # The public Store payload has a one-time start charge plus a tiered primary
    # dataset event.  Discovery must use a conservative finite estimate rather
    # than rejecting the exact revision merely because the old flat price field
    # is absent.
    assert revision.price_per_run_usd == 0.014


def test_candidate_probe_preflight_rechecks_exact_public_revision_and_cap() -> None:
    catalog = ApifyDiscoveryCatalog(_Metadata())
    candidate = CandidateRecord(
        candidate_id="candidate", route_id="route", lifecycle=CandidateLifecycle.PROBATIONARY,
        assignment_role=AssignmentRole.INACTIVE, priority=None, generation=1,
        build_id="build-1", manifest_hash="m" * 64, actor_id="publisher/actor",
        publisher="publisher", build_number="1.0.0", manifest_json="{}",
        input_schema_hash=_hash({"properties": {"profile": {"type": "string"}}}),
        output_schema_hash=_hash({"properties": {"id": {"type": "string"}}}),
    )

    assert asyncio.run(catalog.verify_candidate(candidate, max_charge_usd=0.02)).allowed is True
    result = asyncio.run(catalog.verify_candidate(candidate, max_charge_usd=0.01))
    assert result.allowed is False
    assert result.error_code == "actorops_maintenance_revision_changed"


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()
