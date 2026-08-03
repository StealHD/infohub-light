from __future__ import annotations

import json

import pytest

from src.services.apify_actor_manifest import (
    ActorManifestError,
    actor_manifest_hash,
    canonical_manifest_json,
    map_actor_output,
    parse_actor_manifest,
    render_actor_input,
    summarize_json_paths,
)


def _manifest() -> dict:
    return {
        "version": 1,
        "actor_id": "safe-publisher/profile-items",
        "build_number": "1.2.3",
        "input": {
            "startUrls": [{"url": {"$ref": "target.canonical_url"}}],
            "maxItems": {"$ref": "runtime.max_items"},
        },
        "output": {
            "native_id": {
                "pointers": ["/id"],
                "transforms": ["to_string"],
            },
            "url": {
                "pointers": ["/url"],
                "transforms": ["normalize_url"],
            },
            "published_at": {
                "pointers": ["/createdAt"],
                "transforms": ["parse_datetime"],
            },
            "text": {
                "pointers": ["/text", "/caption"],
                "transforms": ["pick_first", "strip_html"],
            },
            "author_handle": {
                "pointers": ["/author/handle"],
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
            "empty_result_markers": [
                {"pointer": "/status", "equals": "empty"},
            ],
        },
    }


def test_manifest_renders_only_exact_references_and_maps_safe_output() -> None:
    parsed = parse_actor_manifest(_manifest())
    rendered = render_actor_input(
        parsed,
        {
            "canonical_url": "https://x.com/apify?lang=en",
            "native_id": "apify-id",
            "handle": "@Apify",
        },
        {"max_items": 1},
    )
    assert rendered == {
        "startUrls": [{"url": "https://x.com/apify?lang=en"}],
        "maxItems": 1,
    }

    result = map_actor_output(
        parsed,
        [
            {
                "id": 123,
                "url": "https://x.com/apify/status/123#fragment",
                "createdAt": "2030-01-01T08:00:00Z",
                "text": "<p>Hello &amp; safe</p>",
                "author": {"handle": "apify"},
            }
        ],
        {
            "canonical_url": "https://x.com/apify",
            "native_id": "apify-id",
            "handle": "@Apify",
        },
        {
            "max_items": 1,
            "since_iso": "2030-01-01T00:00:00Z",
            "until_iso": "2030-01-02T00:00:00Z",
        },
    )

    assert result.semantic_outcome == "valid_nonempty"
    assert result.items[0].native_id == "123"
    assert result.items[0].text == "Hello & safe"
    assert result.items[0].url == "https://x.com/apify/status/123"
    assert actor_manifest_hash(parsed) == actor_manifest_hash(
        json.loads(canonical_manifest_json(parsed))
    )


@pytest.mark.parametrize(
    "timestamp",
    [1893456000, 1893456000000, "1893456000"],
)
def test_manifest_parse_datetime_accepts_bounded_unix_epochs(timestamp) -> None:
    result = map_actor_output(
        parse_actor_manifest(_manifest()),
        [
            {
                "id": "post-1",
                "url": "https://x.com/apify/status/post-1",
                "createdAt": timestamp,
                "text": "content",
                "author": {"handle": "apify"},
            }
        ],
        {
            "canonical_url": "https://x.com/apify",
            "native_id": "apify",
            "handle": "apify",
        },
        {"max_items": 1},
    )

    assert result.semantic_outcome == "valid_nonempty"
    assert result.items[0].published_at.isoformat() == "2030-01-01T00:00:00+00:00"


def test_manifest_skips_metadata_row_before_valid_content() -> None:
    parsed = parse_actor_manifest(_manifest())
    target = {
        "canonical_url": "https://x.com/apify",
        "native_id": "apify",
        "handle": "apify",
    }
    result = map_actor_output(
        parsed,
        [
            {
                "profileName": "metadata row",
                "author": {"handle": "apify"},
            },
            {
                "id": "post-1",
                "url": "https://x.com/apify/status/post-1",
                "createdAt": "2030-01-01T00:00:00Z",
                "text": "content row",
                "author": {"handle": "apify"},
            },
        ],
        target,
        {"max_items": 1},
    )

    assert result.semantic_outcome == "valid_nonempty"
    assert result.excluded_rows == 1
    assert [item.native_id for item in result.items] == ["post-1"]


def test_manifest_rejects_dataset_containing_only_metadata_rows() -> None:
    with pytest.raises(ActorManifestError) as caught:
        map_actor_output(
            parse_actor_manifest(_manifest()),
            [{"profileName": "metadata", "author": {"handle": "apify"}}],
            {
                "canonical_url": "https://x.com/apify",
                "native_id": "apify",
                "handle": "apify",
            },
            {"max_items": 1},
        )

    assert caught.value.code == "apify_actor_metadata_only"


@pytest.mark.parametrize("timestamp", [True, -1, 4_102_444_800_001])
def test_manifest_rejects_unsafe_epoch_values(timestamp) -> None:
    with pytest.raises(ActorManifestError) as caught:
        map_actor_output(
            parse_actor_manifest(_manifest()),
            [
                {
                    "id": "post-1",
                    "url": "https://x.com/apify/status/post-1",
                    "createdAt": timestamp,
                    "text": "content",
                    "author": {"handle": "apify"},
                }
            ],
            {
                "canonical_url": "https://x.com/apify",
                "native_id": "apify",
                "handle": "apify",
            },
            {"max_items": 1},
        )

    assert caught.value.code == "apify_actor_contract_mismatch"


def test_manifest_does_not_skip_partially_mapped_content_rows() -> None:
    with pytest.raises(ActorManifestError) as caught:
        map_actor_output(
            parse_actor_manifest(_manifest()),
            [{"id": "post-1", "author": {"handle": "apify"}}],
            {
                "canonical_url": "https://x.com/apify",
                "native_id": "apify",
                "handle": "apify",
            },
            {"max_items": 1},
        )

    assert caught.value.code == "apify_actor_contract_mismatch"


@pytest.mark.parametrize(
    ("mutate", "code"),
    [
        (
            lambda value: value["input"].update(
                {"token": {"$ref": "target.handle"}}
            ),
            "apify_manifest_invalid",
        ),
        (
            lambda value: value["input"].update(
                {"script": "eval(user_input)"}
            ),
            "apify_manifest_invalid",
        ),
        (
            lambda value: value["input"].update(
                {
                    "requests": [
                        {"url": {"$ref": "target.canonical_url"}}
                    ]
                }
            ),
            "apify_manifest_invalid",
        ),
        (
            lambda value: value["input"].update(
                {"url": {"$ref": "runtime.since_iso"}}
            ),
            "apify_manifest_invalid",
        ),
        (
            lambda value: value["output"]["url"].update(
                {"pointers": ["$.url"]}
            ),
            "apify_manifest_invalid",
        ),
        (
            lambda value: value["output"]["url"].update(
                {"transforms": ["custom_transform"]}
            ),
            "apify_manifest_invalid",
        ),
    ],
)
def test_manifest_rejects_credentials_code_unknown_refs_and_jsonpath(
    mutate,
    code: str,
) -> None:
    manifest = _manifest()
    mutate(manifest)
    with pytest.raises(ActorManifestError) as caught:
        parse_actor_manifest(manifest)
    assert caught.value.code == code


def test_manifest_rejects_identity_host_and_time_contract_drift() -> None:
    parsed = parse_actor_manifest(_manifest())
    base = {
        "id": "1",
        "url": "https://evil.example/item/1",
        "createdAt": "2030-01-03T08:00:00Z",
        "text": "not placeholder",
        "author": {"handle": "someone-else"},
    }
    with pytest.raises(ActorManifestError) as caught:
        map_actor_output(
            parsed,
            [base],
            {
                "canonical_url": "https://x.com/apify",
                "native_id": "apify",
                "handle": "apify",
            },
            {"max_items": 1},
        )
    assert caught.value.code == "apify_actor_output_host_disallowed"

    manifest = _manifest()
    manifest["semantics"]["url_host_allowlist"] = ["127.0.0.1"]
    with pytest.raises(ActorManifestError) as caught:
        parse_actor_manifest(manifest)
    assert caught.value.code == "apify_manifest_invalid"


def test_manifest_distinguishes_valid_and_suspicious_empty_and_redacts_values() -> None:
    parsed = parse_actor_manifest(_manifest())
    target = {
        "canonical_url": "https://x.com/apify",
        "native_id": "apify",
        "handle": "apify",
    }
    assert (
        map_actor_output(
            parsed,
            [{"status": "empty", "author": {"handle": "apify"}}],
            target,
            {"max_items": 1},
        ).semantic_outcome
        == "valid_empty"
    )
    assert (
        map_actor_output(parsed, [], target, {"max_items": 1}).semantic_outcome
        == "suspicious_empty"
    )
    summary = summarize_json_paths(
        {"author": {"handle": "private-target"}, "text": "secret body"}
    )
    serialized = json.dumps(summary)
    assert "/author/handle" in serialized
    assert "private-target" not in serialized
    assert "secret body" not in serialized


def test_explicit_empty_requires_matching_target_identity() -> None:
    parsed = parse_actor_manifest(_manifest())
    target = {
        "canonical_url": "https://x.com/apify",
        "native_id": "apify",
        "handle": "apify",
    }
    for row in (
        {"noResults": True},
        {"type": "empty", "author": {"handle": "someone-else"}},
    ):
        with pytest.raises(ActorManifestError) as caught:
            map_actor_output(parsed, [row], target, {"max_items": 1})
        assert caught.value.code == "apify_actor_target_identity_mismatch"

    result = map_actor_output(
        parsed,
        [{"noResults": True, "author": {"handle": "@Apify"}}],
        target,
        {"max_items": 1},
    )
    assert result.semantic_outcome == "valid_empty"


def test_empty_marker_cannot_match_missing_pointer_with_null() -> None:
    manifest = _manifest()
    manifest["semantics"]["empty_result_markers"] = [
        {"pointer": "/missing", "equals": None}
    ]

    with pytest.raises(ActorManifestError) as caught:
        parse_actor_manifest(manifest)

    assert caught.value.code == "apify_manifest_invalid"


def test_exact_build_number_accepts_zero_patch() -> None:
    manifest = _manifest()
    manifest["build_number"] = "1.0.0"
    assert parse_actor_manifest(manifest).build_number == "1.0.0"


def test_manifest_url_identity_preserves_youtube_query_and_id_case() -> None:
    manifest = _manifest()
    manifest["output"]["source_url"] = {
        "pointers": ["/sourceUrl"],
        "transforms": ["normalize_url"],
    }
    manifest["semantics"]["identity"] = {
        "output_field": "source_url",
        "target_ref": "target.canonical_url",
        "match": "url",
    }
    manifest["semantics"]["url_host_allowlist"] = ["youtube.com"]
    parsed = parse_actor_manifest(manifest)
    row = {
        "id": "video-1",
        "url": "https://www.youtube.com/watch?v=video-1",
        "createdAt": "2030-01-01T08:00:00Z",
        "text": "video",
        "author": {"handle": "channel"},
        "sourceUrl": (
            "https://www.youtube.com/feeds/videos.xml?"
            "channel_id=UCAabcdefghijklmnopqrstu"
        ),
    }
    with pytest.raises(ActorManifestError) as caught:
        map_actor_output(
            parsed,
            [row],
            {
                "canonical_url": (
                    "https://www.youtube.com/feeds/videos.xml?"
                    "channel_id=UCabcdefghijklmnopqrstuv"
                ),
                "native_id": "UCabcdefghijklmnopqrstuv",
                "handle": None,
            },
            {"max_items": 1},
        )
    assert caught.value.code == "apify_actor_target_identity_mismatch"
