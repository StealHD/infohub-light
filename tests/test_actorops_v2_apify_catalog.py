from __future__ import annotations

import asyncio
from pathlib import Path

from src.services.actorops.apify_catalog import ApifyDiscoveryCatalog


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
