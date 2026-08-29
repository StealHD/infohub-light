from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.services.apify_actor_manifest import ActorManifestError
from src.services.actorops.adapters import build_default_registry
from src.services.actorops.discovery_manifest import validate_schema_proven_manifest
from src.services.actorops.domain import RouteKey
from src.services.actorops.ports import (
    ActorManifest,
    DiscoveryMapping,
    DiscoveryRevision,
    FetchWindow,
)


def _value() -> dict[str, object]:
    return {
        "version": 1,
        "actor_id": "publisher/x-search",
        "build_number": "1.0.0",
        "input": {
            "mode": "Advanced Search",
            "query": {"$ref": "target.handle"},
            "query_type": "Latest",
            "max_results": {"$ref": "runtime.max_items"},
        },
        "output": {
            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/__actorops_x_post_url"], "transforms": ["normalize_url"]},
            "published_at": {"pointers": ["/created_at"], "transforms": ["parse_datetime"]},
            "text": {"pointers": ["/full_text"], "transforms": ["to_string"]},
            "author_handle": {"pointers": ["/username"], "transforms": ["to_string"]},
        },
        "semantics": {
            "identity": {
                "output_field": "author_handle",
                "target_ref": "target.handle",
                "match": "handle",
            },
            "url_host_allowlist": ["x.com"],
        },
    }


def _revision() -> DiscoveryRevision:
    return DiscoveryRevision(
        actor_id="publisher/x-search",
        publisher="publisher",
        build_id="build-x-search",
        build_number="1.0.0",
        price_per_run_usd=0.01,
        input_schema={
            "type": "object",
            "required": ["mode"],
            "properties": {
                "mode": {"type": "string", "enum": ["Advanced Search"]},
                "query": {"type": "string"},
                "query_type": {"type": "string", "enum": ["Top", "Latest"]},
                "max_results": {"type": "integer"},
            },
        },
        output_schema={
            "type": "object",
            "properties": {
                "id": {"type": "string"},
                "created_at": {"type": "string"},
                "full_text": {"type": "string"},
                "username": {"type": "string"},
            },
        },
    )


def test_schema_proof_accepts_bounded_x_search_and_derived_post_url() -> None:
    manifest, error = validate_schema_proven_manifest(
        _revision(), DiscoveryMapping(json.dumps(_value()))
    )

    assert manifest is not None
    assert error is None


def test_x_adapter_compiles_query_and_derives_url_without_mutating_row() -> None:
    adapter = build_default_registry().require(RouteKey("x", "profile", "items"))
    target = adapter.normalize_target({"target": "openai"})
    manifest_json = json.dumps(_value())
    manifest = ActorManifest(
        actor_id="publisher/x-search",
        build_id="build-x-search",
        build_number="1.0.0",
        manifest_json=manifest_json,
        manifest_hash="a" * 64,
    )
    window = FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None)
    row = {
        "id": "123",
        "created_at": "2026-08-20T00:00:00Z",
        "full_text": "post",
        "username": "openai",
    }

    assert adapter.build_actor_input(target, manifest, window) == {
        "mode": "Advanced Search",
        "query": "from:openai",
        "query_type": "Latest",
        "max_results": 3,
    }
    batch = adapter.validate_output((row,), target, manifest, window)
    assert row == {
        "id": "123",
        "created_at": "2026-08-20T00:00:00Z",
        "full_text": "post",
        "username": "openai",
    }
    assert str(batch.items[0].url) == "https://x.com/openai/status/123"
    assert batch.items[0].author == "openai"

    with pytest.raises(ActorManifestError):
        adapter.validate_output(({
            **row,
            "id": "../foreign",
            "__actorops_x_post_url": "https://x.com/openai/status/forged",
        },), target, manifest, window)


def test_x_adapter_accepts_twitter_api_timestamp() -> None:
    adapter = build_default_registry().require(RouteKey("x", "profile", "items"))
    target = adapter.normalize_target({"target": "openai"})
    manifest_json = json.dumps(_value())
    manifest = ActorManifest(
        actor_id="publisher/x-search",
        build_id="build-x-search",
        build_number="1.0.0",
        manifest_json=manifest_json,
        manifest_hash="a" * 64,
    )
    window = FetchWindow(1, datetime(2026, 8, 19, tzinfo=timezone.utc), None)

    batch = adapter.validate_output(({
        "id": "123",
        "created_at": "Fri Aug 28 06:24:06 +0000 2026",
        "full_text": "post",
        "username": "openai",
    },), target, manifest, window)

    assert batch.semantic_outcome == "valid_nonempty"
    assert batch.items[0].published_at.isoformat() == "2026-08-28T06:24:06+00:00"
