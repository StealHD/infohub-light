from __future__ import annotations

import asyncio
import inspect
import json
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.services.actorops.adapters import build_default_registry
from src.services.actorops.domain import RouteKey
from src.services.actorops.ports import ActorManifest, DiscoveryRevision, FetchWindow


@pytest.mark.parametrize(
    ("key", "config", "canonical"),
    [
        (RouteKey("x", "profile", "items"), {"target": "@OpenAI"}, "https://x.com/OpenAI"),
        (
            RouteKey("instagram", "profile", "items"),
            {"target": "https://www.instagram.com/openai/"},
            "https://www.instagram.com/openai/",
        ),
        (
            RouteKey("youtube", "channel", "items"),
            {"target": "https://www.youtube.com/channel/UC1234567890123456789012"},
            "https://www.youtube.com/channel/UC1234567890123456789012",
        ),
    ],
)
def test_platform_adapters_normalize_targets_idempotently(key, config, canonical) -> None:
    adapter = build_default_registry().require(key)
    first = adapter.normalize_target(config)
    second = adapter.normalize_target({"target": first.canonical_url})
    assert first == second
    assert first.canonical_url == canonical


@pytest.mark.parametrize(
    ("key", "target"),
    [
        (RouteKey("x", "profile", "items"), "https://evil.example/openai"),
        (RouteKey("x", "profile", "items"), "https://x.com/home"),
        (RouteKey("instagram", "profile", "items"), "https://instagram.com/explore"),
        (RouteKey("youtube", "channel", "items"), "http://youtube.com/@openai"),
    ],
)
def test_platform_adapters_reject_unsafe_or_reserved_targets(key, target) -> None:
    with pytest.raises(ValueError):
        build_default_registry().require(key).normalize_target({"target": target})


def test_only_youtube_declares_a_native_fallback() -> None:
    async def native_fetcher(target, window):
        from src.services.actorops.ports import NativeFallbackResult

        return NativeFallbackResult(supported=True)

    registry = build_default_registry(youtube_native_fetcher=native_fetcher)
    window = FetchWindow(
        max_items=3,
        since=datetime(2026, 8, 20, tzinfo=timezone.utc),
        until=None,
    )
    for key, config, supported in (
        (RouteKey("x", "profile", "items"), {"target": "openai"}, False),
        (RouteKey("instagram", "profile", "items"), {"target": "openai"}, False),
        (RouteKey("youtube", "channel", "items"), {"target": "https://youtube.com/@openai"}, True),
    ):
        adapter = registry.require(key)
        result = asyncio.run(
            adapter.fetch_native_fallback(adapter.normalize_target(config), window)
        )
        assert result.supported is supported


def test_instagram_discovery_uses_its_own_plural_input_and_post_fields() -> None:
    adapter = build_default_registry().require(RouteKey("instagram", "profile", "items"))
    revision = DiscoveryRevision(
        actor_id="actor", publisher="publisher", build_id="build", build_number="1.0.0",
        price_per_run_usd=0.01,
        input_schema={"properties": {"usernames": {"type": "array"}}},
        output_schema={"properties": {
            "postId": {}, "url": {}, "timestamp": {}, "caption": {}, "authorUsername": {},
        }},
    )

    mapped = adapter.map_discovery_manifest(revision)
    assert mapped.manifest_json is not None
    value = json.loads(mapped.manifest_json)
    assert value["input"] == {"usernames": [{"$ref": "target.handle"}]}
    assert value["output"]["native_id"]["pointers"] == ["/postId"]
    assert value["output"]["author_handle"]["pointers"] == ["/authorUsername"]


def test_adapters_do_not_depend_on_storage_secrets_jobs_or_feed() -> None:
    root = Path(__file__).resolve().parents[1] / "src" / "services" / "actorops" / "adapters"
    forbidden = ("sqlite3", "ServiceStore", "SecretStore", "fetch_jobs", "FeedProduction")
    for path in root.rglob("*.py"):
        source = path.read_text(encoding="utf-8")
        assert all(token not in source for token in forbidden), path
    assert "if platform" not in inspect.getsource(build_default_registry).casefold()


@pytest.mark.parametrize(
    ("key", "config", "identity_field", "identity_ref", "host", "identity"),
    [
        (RouteKey("x", "profile", "items"), {"target": "openai"}, "author_handle", "target.handle", "x.com", "openai"),
        (RouteKey("instagram", "profile", "items"), {"target": "openai"}, "author_handle", "target.handle", "instagram.com", "openai"),
        (
            RouteKey("youtube", "channel", "items"),
            {"target": "https://youtube.com/channel/UC1234567890123456789012"},
            "source_native_id",
            "target.native_id",
            "youtube.com",
            "UC1234567890123456789012",
        ),
    ],
)
def test_adapter_mapping_rejects_cross_target_output_and_keeps_ids_stable(
    key, config, identity_field, identity_ref, host, identity
) -> None:
    adapter = build_default_registry().require(key)
    target = adapter.normalize_target(config)
    pointer = "/sourceId" if identity_field == "source_native_id" else "/author"
    manifest_json = json.dumps(
        {
            "version": 1,
            "actor_id": "publisher/actor",
            "build_number": "1.0.0",
            "input": {"target": {"$ref": identity_ref}, "limit": {"$ref": "runtime.max_items"}},
            "output": {
                "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
                "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
                "published_at": {"pointers": ["/createdAt"], "transforms": ["parse_datetime"]},
                "text": {"pointers": ["/text"], "transforms": ["to_string"]},
                identity_field: {"pointers": [pointer], "transforms": ["to_string"]},
            },
            "semantics": {
                "identity": {"output_field": identity_field, "target_ref": identity_ref, "match": "handle" if identity_ref.endswith("handle") else "exact"},
                "url_host_allowlist": [host],
            },
        }
    )
    manifest = ActorManifest(
        actor_id="publisher/actor",
        build_id="build",
        build_number="1.0.0",
        manifest_json=manifest_json,
        manifest_hash="a" * 64,
    )
    window = FetchWindow(3, datetime(2026, 8, 19, tzinfo=timezone.utc), None)
    actor_input = adapter.build_actor_input(target, manifest, window)
    assert actor_input == {"target": identity, "limit": 3}
    assert "token" not in json.dumps(actor_input).casefold()
    row = {
        "id": "item-1",
        "url": f"https://{host}/item-1",
        "createdAt": "2026-08-20T00:00:00Z",
        "text": "item",
        pointer.lstrip("/"): identity,
    }
    first = adapter.validate_output((row,), target, manifest, window)
    second = adapter.validate_output((row,), target, manifest, window)
    assert first.items[0].id == second.items[0].id
    with pytest.raises(Exception):
        adapter.validate_output(
            ({**row, pointer.lstrip("/"): "another-account"},),
            target,
            manifest,
            window,
        )
