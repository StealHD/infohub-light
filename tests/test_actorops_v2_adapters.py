from __future__ import annotations

import asyncio
import inspect
import json
from copy import deepcopy
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.services.actorops.adapters import build_default_registry
from src.services.actorops.adapter_rows import prepare_adapter_rows
from src.services.apify_actor_manifest import ActorManifestError
from src.services.actorops.domain import RouteKey
from src.services.actorops.ports import ActorManifest, DiscoveryRevision, FetchWindow
from src.services.actorops.presentation_mapping import avatar_pointer_from_rows
from src.services.actorops.presentation_row_paths import (
    PRESENTATION_AVATAR_FALLBACK_POINTER,
)


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


@pytest.mark.parametrize(
    ("key", "config", "container", "host", "identity_field", "identity_pointer"),
    [
        (
            RouteKey("x", "profile", "items"), {"target": "openai"},
            "timeline", "x.com", "author_handle", "/root/author/username",
        ),
        (
            RouteKey("instagram", "profile", "items"), {"target": "openai"},
            "posts", "instagram.com", "author_handle", "/root/profile/username",
        ),
        (
            RouteKey("youtube", "channel", "items"),
            {"target": "https://youtube.com/@openai"},
            "videos", "youtube.com", "source_url", "/root/channel/url",
        ),
    ],
)
def test_platform_adapters_validate_nested_publications_with_parent_identity(
    key, config, container, host, identity_field, identity_pointer,
) -> None:
    adapter = build_default_registry().require(key)
    target = adapter.normalize_target(config)
    item_url = {
        "x": "https://x.com/openai/status/1",
        "instagram": "https://instagram.com/p/one/",
        "youtube": "https://youtube.com/watch?v=one",
    }[key.platform]
    root_identity = {
        "x": {"author": {"username": "openai"}},
        "instagram": {"profile": {"username": "openai"}},
            "youtube": {"channel": {"url": "https://www.youtube.com/@openai"}},
    }[key.platform]
    manifest_json = json.dumps({
        "version": 1, "actor_id": f"publisher/{key.platform}-nested",
        "build_number": "1.0.0",
        "input": {"target": {"$ref": "target.canonical_url"}},
        "row_extraction": {
            "mode": "nested_array", "pointers": [f"/{container}"],
            "filters": [],
        },
        "output": {
            "native_id": {"pointers": ["/item/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/item/url"], "transforms": ["normalize_url"]},
            "published_at": {"pointers": ["/item/publishedAt"], "transforms": ["parse_datetime"]},
            "text": {"pointers": ["/item/text"], "transforms": ["to_string"]},
            identity_field: {"pointers": [identity_pointer], "transforms": ["to_string"]},
            "thumbnail_url": {"pointers": ["/item/image"], "transforms": ["normalize_url"]},
        },
        "semantics": {
            "identity": {
                "output_field": identity_field,
                "target_ref": "target.canonical_url" if key.platform == "youtube" else "target.handle",
                "match": "url" if key.platform == "youtube" else "handle",
            },
            "url_host_allowlist": [host],
        },
    })
    manifest = ActorManifest(
        actor_id=f"publisher/{key.platform}-nested", build_id="build",
        build_number="1.0.0", manifest_json=manifest_json,
        manifest_hash="f" * 64,
    )
    rows = ({
        **root_identity,
        container: [{
            "id": "one", "url": item_url,
            "publishedAt": "2026-08-29T01:00:00Z", "text": "new",
            "image": "https://images.example/one.jpg",
        }],
    },)
    prepared = prepare_adapter_rows(adapter, rows, target, manifest)

    batch = adapter.validate_output(
        prepared, target, manifest,
        FetchWindow(3, datetime(2026, 8, 28, tzinfo=timezone.utc), None),
    )

    assert batch.semantic_outcome == "valid_nonempty"
    assert batch.items[0].metadata["native_id"] == "one"
    assert batch.items[0].metadata["image_url"].endswith("one.jpg")


def test_youtube_adapter_accepts_the_native_rss_url_source_shape() -> None:
    adapter = build_default_registry().require(
        RouteKey("youtube", "channel", "items")
    )
    url = "https://www.youtube.com/channel/UC1234567890123456789012"

    assert adapter.normalize_target({"url": url}) == adapter.normalize_target(
        {"target": url}
    )


def test_instagram_discovery_uses_its_own_plural_input_and_post_fields() -> None:
    adapter = build_default_registry().require(RouteKey("instagram", "profile", "items"))
    revision = DiscoveryRevision(
        actor_id="actor", publisher="publisher", build_id="build", build_number="1.0.0",
        price_per_run_usd=0.01,
        input_schema={"properties": {"usernames": {"type": "array"}}},
        output_schema={"properties": {
            "postId": {}, "url": {}, "timestamp": {}, "caption": {}, "authorUsername": {},
            "profilePicUrlHD": {},
        }},
    )

    mapped = adapter.map_discovery_manifest(revision)
    assert mapped.manifest_json is not None
    value = json.loads(mapped.manifest_json)
    assert value["input"] == {"usernames": [{"$ref": "target.handle"}]}
    assert value["output"]["native_id"]["pointers"] == ["/postId"]
    assert value["output"]["author_handle"]["pointers"] == ["/authorUsername"]
    assert value["output"]["author_avatar_url"]["pointers"] == ["/profilePicUrlHD"]


def test_youtube_discovery_maps_channel_id_date_and_result_limit_aliases() -> None:
    adapter = build_default_registry().require(
        RouteKey("youtube", "channel", "items")
    )
    revision = DiscoveryRevision(
        actor_id="actor",
        publisher="publisher",
        build_id="build",
        build_number="1.0.0",
        price_per_run_usd=0.01,
        input_schema={"properties": {
            "channelUrls": {"type": "array", "items": {"type": "string"}},
            "channelId": {"type": "string"},
            "maxResults": {"type": "integer"},
        }},
        output_schema={"properties": {
            "id": {"type": "string"},
            "url": {"type": "string"},
            "date": {"type": "string"},
            "title": {"type": "string"},
            "channelId": {"type": "string"},
            "thumbnailUrl": {"type": "string"},
        }},
    )

    mapped = adapter.map_discovery_manifest(revision)

    assert mapped.manifest_json is not None
    value = json.loads(mapped.manifest_json)
    assert value["input"] == {
        "channelId": {"$ref": "target.native_id"},
        "maxResults": {"$ref": "runtime.max_items"},
    }
    assert value["output"]["published_at"]["pointers"] == ["/date"]
    assert value["output"]["source_url"]["pointers"] == [
        "/__actorops_target_url"
    ]
    assert value["output"]["thumbnail_url"]["pointers"] == ["/thumbnailUrl"]


def test_youtube_discovery_derives_known_channel_identity_when_rows_omit_it() -> None:
    adapter = build_default_registry().require(
        RouteKey("youtube", "channel", "items")
    )
    revision = DiscoveryRevision(
        actor_id="publisher/channel-videos",
        publisher="publisher",
        build_id="build",
        build_number="1.0.0",
        price_per_run_usd=0.01,
        input_schema={"properties": {
            "channelUrls": {"type": "array", "items": {"type": "string"}},
            "maxItemsPerUrl": {"type": "integer"},
        }},
        output_schema={"properties": {
            "Video ID": {"type": "string"},
            "URL": {"type": "string"},
            "Published Time": {"type": "string"},
            "Title": {"type": "string"},
            "Thumbnail URL": {"type": "string"},
        }},
    )

    mapped = adapter.map_discovery_manifest(revision)

    assert mapped.manifest_json is not None
    value = json.loads(mapped.manifest_json)
    assert value["input"] == {
        "channelUrls": [{"$ref": "target.canonical_url"}],
        "maxItemsPerUrl": {"$ref": "runtime.max_items"},
    }
    assert value["output"]["source_url"]["pointers"] == [
        "/__actorops_target_url"
    ]
    target = adapter.normalize_target({
        "target": "https://youtube.com/channel/UC1234567890123456789012"
    })
    manifest = ActorManifest(
        actor_id=revision.actor_id,
        build_id=revision.build_id,
        build_number=revision.build_number,
        manifest_json=mapped.manifest_json,
        manifest_hash="a" * 64,
    )
    batch = adapter.validate_output(
        ({
            "Video ID": "video-1",
            "URL": "https://youtube.com/watch?v=video-1",
            "Published Time": "2026-08-29T01:00:00Z",
            "Title": "New video",
            "Thumbnail URL": "https://i.ytimg.com/vi/video-1/hqdefault.jpg",
            "__actorops_target_url": "https://youtube.com/@spoofed",
        },),
        target,
        manifest,
        FetchWindow(3, datetime(2026, 8, 28, tzinfo=timezone.utc), None),
    )

    assert batch.semantic_outcome == "valid_nonempty"
    assert batch.items[0].metadata["image_url"].endswith("hqdefault.jpg")

    handle_target = adapter.normalize_target({
        "target": "https://youtube.com/@openai"
    })
    handle_batch = adapter.validate_output(
        ({
            "Video ID": "video-2",
            "URL": "https://youtube.com/watch?v=video-2",
            "Published Time": "2026-08-29T02:00:00Z",
            "Title": "Handle channel video",
        },),
        handle_target,
        manifest,
        FetchWindow(3, datetime(2026, 8, 28, tzinfo=timezone.utc), None),
    )
    assert handle_batch.semantic_outcome == "valid_nonempty"


@pytest.mark.parametrize(
    ("input_schema", "output_schema", "expected_input", "identity_pointer"),
    [
        (
            {"properties": {"handles": {"type": "array"}, "maxPosts": {"type": "integer"}}},
            {"properties": {"id": {}, "url": {}, "createdAt": {}, "text": {}, "userName": {}}},
            {
                "handles": [{"$ref": "target.handle"}],
                "maxPosts": {"$ref": "runtime.max_items"},
            },
            "/userName",
        ),
        (
            {"properties": {"profileUrls": {"type": "array"}, "numberOfTweets": {"type": "integer"}}},
            {"properties": {"id": {}, "url": {}, "created_at": {}, "text": {}, "profileHandle": {}}},
            {
                "profileUrls": [{"$ref": "target.canonical_url"}],
                "numberOfTweets": {"$ref": "runtime.max_items"},
            },
            "/profileHandle",
        ),
    ],
)
def test_x_discovery_maps_schema_proven_plural_targets_and_limits(
    input_schema, output_schema, expected_input, identity_pointer,
) -> None:
    adapter = build_default_registry().require(RouteKey("x", "profile", "items"))
    revision = DiscoveryRevision(
        actor_id="actor", publisher="publisher", build_id="build",
        build_number="1.0.0", price_per_run_usd=0.01,
        input_schema=input_schema, output_schema=output_schema,
    )

    mapped = adapter.map_discovery_manifest(revision)
    assert mapped.manifest_json is not None
    value = json.loads(mapped.manifest_json)
    assert value["input"] == expected_input
    assert value["output"]["author_handle"]["pointers"] == [identity_pointer]


def test_x_discovery_uses_post_url_when_author_object_is_ambiguous() -> None:
    adapter = build_default_registry().require(RouteKey("x", "profile", "items"))
    revision = DiscoveryRevision(
        actor_id="actor", publisher="publisher", build_id="build",
        build_number="1.0.0", price_per_run_usd=0.01,
        input_schema={"properties": {
            "handles": {"type": "array"},
            "maxPosts": {"type": "integer"},
        }},
        output_schema={"properties": {
            "id": {"type": "string"}, "url": {"type": "string"},
            "createdAt": {"type": "string"}, "text": {"type": "string"},
            "author": {"type": ["object", "null"]},
            "userName": {"type": ["string", "null"]},
        }},
    )

    mapped = adapter.map_discovery_manifest(revision)

    assert mapped.manifest_json is not None
    assert json.loads(mapped.manifest_json)["output"]["author_handle"]["pointers"] == [
        "/url"
    ]


def test_x_discovery_uses_schema_proven_nested_author_handle() -> None:
    adapter = build_default_registry().require(RouteKey("x", "profile", "items"))
    revision = DiscoveryRevision(
        actor_id="actor", publisher="publisher", build_id="build",
        build_number="1.0.0", price_per_run_usd=0.01,
        input_schema={"properties": {"handles": {"type": "array"}}},
        output_schema={"properties": {
            "id": {}, "url": {}, "createdAt": {}, "text": {},
            "author": {"type": "object", "properties": {
                "userName": {"type": "string"},
            }},
        }},
    )

    mapped = adapter.map_discovery_manifest(revision)

    assert mapped.manifest_json is not None
    value = json.loads(mapped.manifest_json)
    assert value["output"]["author_handle"]["pointers"] == [
        "/author/userName"
    ]


def test_x_actor_user_profile_image_is_target_bound_avatar_evidence() -> None:
    adapter = build_default_registry().require(RouteKey("x", "profile", "items"))
    target = adapter.normalize_target({"target": "openai"})
    manifest = ActorManifest(
        actor_id="publisher/x-profile",
        build_id="build",
        build_number="1.0.0",
        manifest_json=json.dumps({
            "version": 1,
            "actor_id": "publisher/x-profile",
            "build_number": "1.0.0",
            "input": {"query": {"$ref": "target.handle"}},
            "output": {
                "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
                "url": {
                    "pointers": ["/__actorops_x_post_url"],
                    "transforms": ["normalize_url"],
                },
                "published_at": {
                    "pointers": ["/created_at"],
                    "transforms": ["parse_datetime"],
                },
                "text": {"pointers": ["/full_text"], "transforms": ["to_string"]},
                "author_handle": {
                    "pointers": ["/username"],
                    "transforms": ["to_string"],
                },
            },
            "semantics": {
                "identity": {
                    "output_field": "author_handle",
                    "target_ref": "target.handle",
                    "match": "handle",
                },
                "url_host_allowlist": ["x.com"],
            },
        }),
        manifest_hash="f" * 64,
    )

    batch = adapter.validate_output(
        ({
            "id": "123",
            "created_at": "2026-08-29T01:00:00Z",
            "full_text": "target post",
            "username": "openai",
            "user_profile_image_url": "https://cdn.example/openai.jpg",
        },),
        target,
        manifest,
        FetchWindow(1, datetime(2026, 8, 28, tzinfo=timezone.utc), None),
    )

    assert batch.source_avatar_url == "https://cdn.example/openai.jpg"
    assert batch.presentation_evidence is not None
    assert avatar_pointer_from_rows(batch.presentation_evidence.rows, "x") == (
        "/user_profile_image_url"
    )
    assert "author_avatar_url" not in batch.items[0].metadata


def test_x_discovery_maps_user_profile_image_url() -> None:
    adapter = build_default_registry().require(RouteKey("x", "profile", "items"))
    revision = DiscoveryRevision(
        actor_id="actor",
        publisher="publisher",
        build_id="build",
        build_number="1.0.0",
        price_per_run_usd=0.01,
        input_schema={"properties": {"handles": {"type": "array"}}},
        output_schema={"properties": {
            "id": {}, "url": {}, "created_at": {}, "full_text": {},
            "username": {}, "user_profile_image_url": {},
        }},
    )

    mapped = adapter.map_discovery_manifest(revision)

    assert mapped.manifest_json is not None
    assert json.loads(mapped.manifest_json)["output"]["author_avatar_url"] == {
        "pointers": ["/user_profile_image_url"],
        "transforms": ["normalize_url"],
    }


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


def _instagram_profile_manifest(container: str = "user") -> ActorManifest:
    value = json.dumps(
        {
            "version": 1,
            "actor_id": "publisher/instagram-profile",
            "build_number": "1.0.0",
            "input": {"username": {"$ref": "target.handle"}},
            "output": {
                "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
                "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
                "published_at": {
                    "pointers": ["/createdAt"],
                    "transforms": ["parse_datetime"],
                },
                "text": {"pointers": ["/text"], "transforms": ["to_string"]},
                "author_handle": {
                    "pointers": [f"/{container}/username"],
                    "transforms": ["to_string"],
                },
                "author_avatar_url": {
                    "pointers": [
                        "/user/profile_pic_url",
                        "/owner/profile_pic_url",
                    ],
                    "transforms": ["pick_first", "normalize_url"],
                },
            },
            "semantics": {
                "identity": {
                    "output_field": "author_handle",
                    "target_ref": "target.handle",
                    "match": "handle",
                },
                "url_host_allowlist": ["instagram.com"],
            },
        }
    )
    return ActorManifest(
        actor_id="publisher/instagram-profile",
        build_id="build-instagram-profile",
        build_number="1.0.0",
        manifest_json=value,
        manifest_hash="d" * 64,
    )


def _instagram_profile_row(index: int, username: object) -> dict[str, object]:
    return {
        "id": f"item-{index}",
        "url": f"https://www.instagram.com/p/item-{index}/",
        "createdAt": f"2026-08-20T00:0{index}:00Z",
        "text": f"item {index}",
        "user": {"username": username},
    }


@pytest.mark.parametrize("container", ["user", "owner"])
def test_instagram_accepts_direct_and_exact_coauthor_rows_without_mutating_input(
    container: str,
) -> None:
    adapter = build_default_registry().require(
        RouteKey("instagram", "profile", "items")
    )
    target = adapter.normalize_target({"target": "openai"})
    manifest = _instagram_profile_manifest(container)
    collaboration = _instagram_profile_row(0, "main_owner")
    collaboration[container] = {
        "username": "main_owner",
        "profile_pic_url": "https://cdn.example/main-owner.jpg",
        "profile_pic_id": "main-owner-avatar",
    }
    other_container = "owner" if container == "user" else "user"
    collaboration[other_container] = {
        "username": "third_party_owner",
        "profile_pic_url": "https://cdn.example/third-party-owner.jpg",
        "profile_pic_id": "third-party-owner-avatar",
    }
    collaboration["coauthor_producers"] = [
        {
            "username": "@OPENAI",
            "profile_pic_url": "https://cdn.example/coauthor.jpg",
        }
    ]
    direct = [_instagram_profile_row(index, "OpenAI") for index in range(1, 5)]
    if container == "owner":
        for row in direct:
            row["owner"] = row.pop("user")
    direct[0][container]["profile_pic_url"] = (
        "https://cdn.example/target-profile.jpg"
    )
    rows = (collaboration, *direct)
    original = deepcopy(rows)

    prepared = adapter.prepare_output_rows(rows, target, manifest)
    batch = adapter.validate_output(rows, target, manifest, FetchWindow(
        5, datetime(2026, 8, 19, tzinfo=timezone.utc), None
    ))

    assert prepared[0] is not rows[0]
    assert all(prepared[index] is rows[index] for index in range(1, 5))
    assert prepared[0][container]["username"] == "openai"
    assert prepared[0][other_container]["username"] == "third_party_owner"
    for key in ("user", "owner"):
        assert "profile_pic_url" not in prepared[0][key]
        assert "profile_pic_id" not in prepared[0][key]
    assert rows == original
    assert len(batch.items) == 5
    assert batch.source_avatar_url == "https://cdn.example/target-profile.jpg"
    assert avatar_pointer_from_rows(prepared, "instagram") == (
        f"/{container}/profile_pic_url"
    )


def test_instagram_single_coauthor_row_scrubs_both_third_party_avatar_fallbacks() -> None:
    adapter = build_default_registry().require(
        RouteKey("instagram", "profile", "items")
    )
    target = adapter.normalize_target({"target": "openai"})
    manifest = _instagram_profile_manifest("user")
    row = _instagram_profile_row(1, "main_owner")
    row["user"] = {
        "username": "main_owner",
        "profile_pic_url": "https://cdn.example/main-owner.jpg",
        "profile_pic_id": "main-owner-avatar",
    }
    row["owner"] = {
        "username": "third_party_owner",
        "profile_pic_url": "https://cdn.example/third-party-owner.jpg",
        "profile_pic_id": "third-party-owner-avatar",
    }
    row["coauthor_producers"] = [{"username": "openai"}]
    original = deepcopy(row)

    prepared = adapter.prepare_output_rows((row,), target, manifest)
    batch = adapter.validate_output(
        (row,), target, manifest,
        FetchWindow(1, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
    )

    assert prepared[0]["user"]["username"] == "openai"
    assert prepared[0]["owner"]["username"] == "third_party_owner"
    assert all(
        field not in prepared[0][container]
        for container in ("user", "owner")
        for field in ("profile_pic_url", "profile_pic_id")
    )
    assert avatar_pointer_from_rows(prepared, "instagram") is None
    assert batch.source_avatar_url is None
    assert row == original


def test_instagram_collaboration_only_uses_exact_coauthor_avatar_hint() -> None:
    adapter = build_default_registry().require(
        RouteKey("instagram", "profile", "items")
    )
    target = adapter.normalize_target({"target": "openai"})
    manifest = _instagram_profile_manifest("user")
    row = _instagram_profile_row(1, "main_owner")
    third_party_avatars = {
        "profile_pic_url": "https://cdn.example/snake.jpg",
        "profilePicUrl": "https://cdn.example/camel.jpg",
        "profilePicUrlHD": "https://cdn.example/hd.jpg",
        "profilePicture": "https://cdn.example/picture.jpg",
        "avatar": "https://cdn.example/avatar.jpg",
        "avatarUrl": "https://cdn.example/avatar-url.jpg",
        "profile_pic_id": "third-party-id",
        "profile": {
            "avatar": "https://cdn.example/nested-avatar.jpg",
            "display_name": "owner",
        },
    }
    row["user"] = {"username": "main_owner", **third_party_avatars}
    row["owner"] = {"username": "other_owner", **third_party_avatars}
    row["coauthor_producers"] = [{
        "username": "@OPENAI",
        "profilePicUrlHD": "https://cdn.example/openai-hd.jpg",
    }]
    original = deepcopy(row)

    prepared = adapter.prepare_output_rows((row,), target, manifest)
    batch = adapter.validate_output(
        (row,),
        target,
        manifest,
        FetchWindow(1, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
    )

    for container in ("user", "owner"):
        assert set(prepared[0][container]) == {"username", "profile"}
        assert prepared[0][container]["profile"] == {"display_name": "owner"}
    assert row == original
    assert batch.source_avatar_url == "https://cdn.example/openai-hd.jpg"
    assert "author_avatar_url" not in batch.items[0].metadata
    assert batch.presentation_evidence is not None
    assert avatar_pointer_from_rows(
        batch.presentation_evidence.rows, "instagram"
    ) == PRESENTATION_AVATAR_FALLBACK_POINTER


def test_instagram_presentation_ignores_metadata_and_embedded_foreign_avatar() -> None:
    adapter = build_default_registry().require(
        RouteKey("instagram", "profile", "items")
    )
    target = adapter.normalize_target({"target": "openai"})
    manifest = _instagram_profile_manifest("user")
    value = json.loads(manifest.manifest_json)
    value["output"]["author_avatar_url"] = {
        "pointers": ["/embedded/profilePicUrlHD"],
        "transforms": ["normalize_url"],
    }
    manifest = replace(manifest, manifest_json=json.dumps(value))
    metadata = {
        "user": {"username": "openai"},
        "profilePicUrlHD": "https://cdn.example/metadata.jpg",
    }
    content = _instagram_profile_row(1, "openai")
    content["user"]["avatar"] = "https://cdn.example/target.jpg"
    content["embedded"] = {
        "profilePicUrlHD": "https://cdn.example/other-person.jpg"
    }

    batch = adapter.validate_output(
        (metadata, content),
        target,
        manifest,
        FetchWindow(2, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
    )

    assert len(batch.items) == 1
    assert batch.source_avatar_url == "https://cdn.example/target.jpg"
    assert "author_avatar_url" not in batch.items[0].metadata
    assert batch.presentation_evidence is not None
    serialized = json.dumps(batch.presentation_evidence.rows, sort_keys=True)
    assert "metadata.jpg" not in serialized
    assert "other-person.jpg" not in serialized
    assert "target.jpg" in serialized


@pytest.mark.parametrize(
    "coauthors",
    [
        None,
        [],
        [{"username": "openai.evil"}],
        [{"username": {"nested": "openai"}}],
        [*({"username": f"other-{index}"} for index in range(16)), {"username": "openai"}],
    ],
)
def test_instagram_rejects_cross_owner_rows_without_bounded_exact_coauthor_evidence(
    coauthors: object,
) -> None:
    adapter = build_default_registry().require(
        RouteKey("instagram", "profile", "items")
    )
    target = adapter.normalize_target({"target": "openai"})
    row = _instagram_profile_row(1, "main_owner")
    if coauthors is not None:
        row["coauthor_producers"] = coauthors

    with pytest.raises(ActorManifestError) as caught:
        adapter.validate_output(
            (row,), target, _instagram_profile_manifest(),
            FetchWindow(1, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        )

    assert caught.value.code == "apify_actor_target_identity_mismatch"


def test_instagram_does_not_synthesize_non_string_identity_from_coauthor_evidence() -> None:
    adapter = build_default_registry().require(
        RouteKey("instagram", "profile", "items")
    )
    target = adapter.normalize_target({"target": "openai"})
    row = _instagram_profile_row(1, {"username": "main_owner"})
    row["coauthor_producers"] = [{"username": "openai"}]

    with pytest.raises(ActorManifestError):
        adapter.validate_output(
            (row,), target, _instagram_profile_manifest(),
            FetchWindow(1, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        )


def test_instagram_coauthor_normalization_fails_closed_beyond_row_bound() -> None:
    adapter = build_default_registry().require(
        RouteKey("instagram", "profile", "items")
    )
    target = adapter.normalize_target({"target": "openai"})
    row = _instagram_profile_row(1, "main_owner")
    row["coauthor_producers"] = [{"username": "openai"}]
    row.update({f"noise_{index}": index for index in range(513)})

    with pytest.raises(ActorManifestError) as caught:
        adapter.validate_output(
            (row,), target, _instagram_profile_manifest(),
            FetchWindow(1, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        )

    assert caught.value.code == "apify_actor_target_identity_mismatch"


def test_instagram_rejects_foreign_url_disguised_as_direct_owner_handle() -> None:
    adapter = build_default_registry().require(
        RouteKey("instagram", "profile", "items")
    )
    target = adapter.normalize_target({"target": "openai"})
    row = _instagram_profile_row(1, "https://evil.example/openai")

    with pytest.raises(ActorManifestError) as caught:
        adapter.validate_output(
            (row,), target, _instagram_profile_manifest(),
            FetchWindow(1, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        )

    assert caught.value.code == "apify_actor_target_identity_mismatch"
