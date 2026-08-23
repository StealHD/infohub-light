from __future__ import annotations

import json
from datetime import datetime, timezone

import pytest

from src.services.actorops.adapters import build_default_registry
from src.services.actorops.domain import RouteKey
from src.services.actorops.ports import ActorManifest, FetchWindow
from src.services.apify_actor_manifest import ActorManifestError


def _manifest() -> ActorManifest:
    value = {
        "version": 1,
        "actor_id": "publisher/x-profile-items",
        "build_number": "1.0.0",
        "input": {
            "startUrls": [{"url": {"$ref": "target.canonical_url"}}],
            "maxItems": {"$ref": "runtime.max_items"},
        },
        "output": {
            "native_id": {"pointers": ["/tweetId"], "transforms": ["to_string"]},
            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
            "published_at": {
                "pointers": ["/createdAt"],
                "transforms": ["parse_datetime"],
            },
            "text": {"pointers": ["/text"], "transforms": ["to_string"]},
            "author_handle": {
                "pointers": ["/sourceUsername"],
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
    }
    return ActorManifest(
        actor_id="publisher/x-profile-items",
        build_id="build",
        build_number="1.0.0",
        manifest_json=json.dumps(value),
        manifest_hash="a" * 64,
    )


def _row(tweet_id: str, created_at: str, **values: object) -> dict[str, object]:
    return {
        "tweetId": tweet_id,
        "url": f"https://x.com/openai/status/{tweet_id}",
        "createdAt": created_at,
        "text": f"post {tweet_id}",
        "sourceUsername": "openai",
        **values,
    }


def _validate(rows: tuple[dict[str, object], ...], *, max_items: int = 20):
    adapter = build_default_registry().require(RouteKey("x", "profile", "items"))
    target = adapter.normalize_target({"target": "openai"})
    return adapter.validate_output(
        rows,
        target,
        _manifest(),
        FetchWindow(
            max_items=max_items,
            since=datetime(2030, 1, 1, tzinfo=timezone.utc),
            until=datetime(2030, 1, 2, tzinfo=timezone.utc),
        ),
    )


def test_x_adapter_excludes_reply_before_limit_and_watermark() -> None:
    result = _validate(
        (
            _row("reply", "2030-01-01T10:00:00Z", isReply=True),
            _row(
                "original",
                "2030-01-01T09:00:00Z",
                isReply=False,
                replyCount=500,
                text="@someone standalone announcement",
            ),
        ),
        max_items=1,
    )

    assert [item.metadata["native_id"] for item in result.items] == ["original"]
    assert result.latest_item_id == "original"
    assert result.latest_published_at == "2030-01-01T09:00:00+00:00"


@pytest.mark.parametrize(
    "reply_evidence",
    [
        {"is_reply": "true"},
        {"inReplyToStatusId": "root-post"},
        {"legacy": {"in_reply_to_status_id_str": "root-post"}},
        {"relationshipType": "tweet_reply"},
    ],
)
def test_x_adapter_excludes_supported_explicit_reply_evidence(
    reply_evidence: dict[str, object],
) -> None:
    result = _validate((_row("reply", "2030-01-01T10:00:00Z", **reply_evidence),))

    assert result.items == ()
    assert result.semantic_outcome == "valid_empty"
    assert result.latest_item_id is None


def test_x_adapter_keeps_quote_repost_and_unknown_relationship_rows() -> None:
    result = _validate(
        (
            _row("quote", "2030-01-01T10:00:00Z", isReply=False, quotedTweetId="quoted"),
            _row("repost", "2030-01-01T09:00:00Z", isReply=False, isRepost=True),
            _row("unknown", "2030-01-01T08:00:00Z"),
        )
    )

    assert [item.metadata["native_id"] for item in result.items] == [
        "quote",
        "repost",
        "unknown",
    ]


def test_x_adapter_treats_reply_only_result_with_profile_metadata_as_empty() -> None:
    result = _validate(
        (
            {"recordType": "profile", "sourceUsername": "openai"},
            _row("reply", "2030-01-01T10:00:00Z", isReply=True),
        )
    )

    assert result.items == ()
    assert result.semantic_outcome == "valid_empty"


def test_x_adapter_does_not_hide_placeholder_rows_marked_as_replies() -> None:
    with pytest.raises(ActorManifestError) as caught:
        _validate(
            (
                _row(
                    "placeholder",
                    "2030-01-01T10:00:00Z",
                    isReply=True,
                    demo=True,
                ),
            )
        )

    assert caught.value.code == "apify_actor_placeholder"
