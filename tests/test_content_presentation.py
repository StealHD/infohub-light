from datetime import datetime, timezone

from src.models import ContentItem, SourceType
from src.services.content_presentation import (
    build_content_presentation,
    complete_content_presentation,
)
from src.services.feed_payload import serialize_feed_item


NOW = datetime(2026, 7, 14, 9, 30, tzinfo=timezone.utc)


def _item(**overrides) -> ContentItem:
    data = {
        "id": "rss:test:1",
        "source_type": SourceType.RSS,
        "title": "A native title",
        "url": "https://example.com/article",
        "content": "<p>First   paragraph.</p>\n<script>secret()</script>Second paragraph.",
        "author": "Example Author",
        "published_at": NOW,
        "fetched_at": NOW,
        "metadata": {
            "source_id": "src-1",
            "source_display_name": "Example Feed",
            "catalog_source_type": "rss",
            "topics": ["AI", "Agents"],
            "channel": "AI",
            "analysis_status": "ai",
        },
        "ai_score": 8.2,
        "ai_summary_zh": "一条受控概括。",
        "ai_reason": "不应进入新模板",
        "ai_topics": ["Codex"],
        "ai_entities": ["OpenAI"],
        "ai_signal_strength": "strong",
        "ai_signal_type": "release",
        "ai_action_suggestion": "保存后测试。",
    }
    data.update(overrides)
    return ContentItem.model_validate(data)


def test_builds_stable_rss_presentation_without_reason() -> None:
    presentation = build_content_presentation(_item())

    assert presentation == {
        "version": 1,
        "source": {
            "id": "src-1",
            "catalog_type": "rss",
            "platform": "rss",
            "name": "Example Feed",
        },
        "author": {"name": "Example Author", "kind": "person"},
        "timing": {
            "published_at": "2026-07-14T09:30:00+00:00",
            "fetched_at": "2026-07-14T09:30:00+00:00",
        },
        "links": {
            "canonical_url": "https://example.com/article",
            "source_url": "https://example.com/article",
        },
        "content": {
            "title": "A native title",
            "title_origin": "native",
            "excerpt": "First paragraph. Second paragraph.",
            "content_kind": "feed_summary",
            "excerpt_truncated": False,
            "format": "article",
            "format_origin": "fallback",
        },
        "taxonomy": {
            "channel": "AI",
            "configured_topics": ["AI", "Agents"],
            "inferred_topics": ["Codex"],
            "topics": ["Codex", "AI", "Agents"],
            "entities": ["OpenAI"],
        },
        "engagement": {
            "native_score": None,
            "likes": None,
            "comments": None,
            "reposts": None,
            "shares": None,
            "upvote_ratio": None,
        },
        "analysis": {
            "status": "ai",
            "score": 8.2,
            "signal_strength": "strong",
            "signal_type": "release",
            "summary_zh": "一条受控概括。",
            "action_suggestion": "保存后测试。",
        },
    }


def test_presentation_uses_the_cached_source_avatar_url() -> None:
    presentation = build_content_presentation(
        _item(metadata={
            "source_id": "src-1",
            "source_display_name": "Example Feed",
            "catalog_source_type": "rss",
            "avatar_url": "/api/media/med_avatar",
        })
    )

    assert presentation["source"]["avatar_url"] == "/api/media/med_avatar"


def test_maps_discussion_link_and_native_engagement() -> None:
    presentation = build_content_presentation(
        _item(
            source_type=SourceType.REDDIT,
            url="https://example.com/external",
            metadata={
                "source_id": "src-reddit",
                "source_display_name": "r/LocalLLaMA",
                "catalog_source_type": "reddit_subreddit",
                "subreddit": "LocalLLaMA",
                "discussion_url": "https://www.reddit.com/r/LocalLLaMA/comments/1",
                "score": 42,
                "num_comments": 7,
                "upvote_ratio": 0.91,
                "topics": [],
            },
        )
    )

    assert presentation["source"]["platform"] == "reddit"
    assert presentation["links"] == {
        "canonical_url": "https://example.com/external",
        "source_url": "https://www.reddit.com/r/LocalLLaMA/comments/1",
    }
    assert presentation["content"]["content_kind"] == "discussion"
    assert presentation["engagement"] == {
        "native_score": 42,
        "likes": None,
        "comments": 7,
        "reposts": None,
        "shares": None,
        "upvote_ratio": 0.91,
    }


def test_generated_social_title_and_excerpt_are_bounded() -> None:
    presentation = build_content_presentation(
        _item(
            source_type=SourceType.TWITTER,
            title="@thsottiaux: generated",
            url="https://x.com/thsottiaux/status/1",
            content="a" * 700,
            metadata={
                "source_id": "src-x",
                "source_display_name": "X · @thsottiaux",
                "catalog_source_type": "apify_social",
                "apify_platform": "x",
                "favorite_count": 9,
                "retweet_count": 3,
                "reply_count": 2,
                "analysis_status": "fallback",
            },
        )
    )

    assert presentation["content"]["title_origin"] == "generated"
    assert presentation["content"]["content_kind"] == "post_body"
    assert len(presentation["content"]["excerpt"]) == 600
    assert presentation["content"]["excerpt"].endswith("…")
    assert presentation["content"]["excerpt_truncated"] is True
    assert presentation["engagement"]["likes"] == 9
    assert presentation["engagement"]["reposts"] == 3
    assert presentation["engagement"]["comments"] == 2
    assert presentation["analysis"]["status"] == "fallback"


def test_direct_media_and_source_rules_override_ai_format() -> None:
    social = build_content_presentation(
        _item(
            source_type=SourceType.INSTAGRAM,
            url="https://www.instagram.com/p/example/",
            metadata={
                "catalog_source_type": "apify_social",
                "apify_platform": "instagram",
                "upstream_content_format": "gallery",
                "media_image_count": 8,
                "media_urls": [f"/api/media/image-{index}" for index in range(6)],
                "ai_content_format": "article",
            },
        )
    )

    assert social["content"]["format"] == "gallery"
    assert social["content"]["format_origin"] == "upstream"
    assert social["media"]["count"] == 6
    assert social["media"]["total_image_count"] == 8
    assert social["media"]["truncated"] is True

    for url in (
        "https://www.youtube.com/watch?v=example",
        "https://www.bilibili.com/video/BV1example",
    ):
        video = build_content_presentation(
            _item(
                url=url,
                metadata={"catalog_source_type": "rss", "ai_content_format": "article"},
            )
        )
        assert video["content"]["format"] == "video"
        assert video["content"]["format_origin"] == "deterministic"
        if "youtube.com" in url:
            assert video["source"]["platform"] == "youtube"
            assert video["author"]["kind"] == "channel"


def test_ai_format_is_reused_only_when_stronger_evidence_is_absent() -> None:
    presentation = build_content_presentation(
        _item(metadata={"catalog_source_type": "rss", "ai_content_format": "audio"})
    )

    assert presentation["content"]["format"] == "audio"
    assert presentation["content"]["format_origin"] == "ai"


def test_missing_failed_or_legacy_ai_format_uses_safe_source_fallbacks() -> None:
    rss = build_content_presentation(
        _item(metadata={"catalog_source_type": "rss", "analysis_status": "fallback"})
    )
    social = build_content_presentation(
        _item(
            source_type=SourceType.TWITTER,
            metadata={"catalog_source_type": "apify_social", "apify_platform": "x"},
        )
    )
    unknown = build_content_presentation(_item(source_type=SourceType.OPENBB, metadata={}))

    assert (rss["content"]["format"], rss["content"]["format_origin"]) == ("article", "fallback")
    assert (social["content"]["format"], social["content"]["format_origin"]) == ("social_post", "fallback")
    assert (unknown["content"]["format"], unknown["content"]["format_origin"]) == ("other", "fallback")


def test_release_discussion_and_legacy_snapshot_formats_are_compatible() -> None:
    release = build_content_presentation(
        _item(
            source_type=SourceType.GITHUB,
            metadata={"catalog_source_type": "github_release", "tag": "v1.0.0"},
        )
    )
    discussion = build_content_presentation(
        _item(source_type=SourceType.HACKERNEWS, metadata={})
    )
    legacy = complete_content_presentation(
        {
            "id": "twitter:tweet:legacy",
            "source_type": "twitter",
            "source": "X · @legacy",
            "url": "https://x.com/legacy/status/1",
            "title": "Legacy post",
            "media_urls": ["/api/media/one"],
        }
    )
    legacy_youtube = complete_content_presentation(
        {
            "id": "rss:youtube:legacy",
            "source_type": "rss",
            "source": "Example Channel",
            "author": "Example Channel",
            "url": "https://www.youtube.com/watch?v=legacy",
            "title": "Legacy video",
            "presentation": {
                "source": {"platform": "rss"},
                "author": {"kind": "person"},
            },
        }
    )

    assert release["content"]["format"] == "release"
    assert discussion["content"]["format"] == "discussion"
    assert legacy["content"]["format"] == "image"
    assert legacy["content"]["format_origin"] == "deterministic"
    assert legacy["media"]["total_image_count"] == 1
    assert legacy_youtube["source"]["platform"] == "youtube"
    assert legacy_youtube["author"]["kind"] == "channel"
    assert legacy_youtube["content"]["format"] == "video"


def test_feed_serializer_includes_presentation_and_keeps_raw_content_out() -> None:
    payload = serialize_feed_item(_item(), featured_threshold=7.5)

    assert payload["presentation"]["version"] == 1
    assert payload["presentation"]["content"]["excerpt"] == "First paragraph. Second paragraph."
    assert "content" not in payload
    assert "reason" in payload  # legacy projection remains, React does not consume it
