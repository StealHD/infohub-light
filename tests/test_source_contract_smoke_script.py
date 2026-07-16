from scripts.source_contract_smoke import (
    build_smoke_config,
    validate_serialized_item,
)


def test_source_contract_smoke_covers_all_eight_catalog_types_without_ai() -> None:
    config = build_smoke_config(include_apify=True)

    assert config.ai.enabled is False
    assert [source.catalog_source_type for source in config.sources.rss] == ["rss"]
    assert {source.catalog_source_type for source in config.sources.github} == {
        "github_release",
        "github_user",
    }
    assert config.sources.hackernews.catalog_source_type == "hackernews"
    assert config.sources.reddit.subreddits[0].catalog_source_type == "reddit_subreddit"
    assert config.sources.reddit.users[0].catalog_source_type == "reddit_user"
    assert config.sources.telegram.channels[0].catalog_source_type == "telegram_channel"
    assert config.sources.apify_social.subscriptions[0].catalog_source_type == "apify_social"
    assert config.sources.apify_social.subscriptions[0].fetch_limit == 1
    assert config.sources.apify_social.subscriptions[0].token_env is None


def test_source_contract_validator_returns_only_field_errors() -> None:
    errors = validate_serialized_item(
        {
            "id": "item-1",
            "presentation": {
                "version": 1,
                "source": {"catalog_type": "rss", "platform": "rss", "name": "RSS"},
                "author": {"name": "Author", "kind": "person"},
                "timing": {"published_at": "2026-07-14T00:00:00+00:00", "fetched_at": "2026-07-14T00:00:01+00:00"},
                "links": {"canonical_url": "https://example.com", "source_url": "https://example.com"},
                "content": {"title": "Title", "title_origin": "native", "excerpt": "x" * 601, "content_kind": "feed_summary", "excerpt_truncated": True},
                "taxonomy": {"channel": "AI", "configured_topics": [], "inferred_topics": [], "topics": [], "entities": []},
                "engagement": {"native_score": None, "likes": None, "comments": None, "reposts": None, "shares": None, "upvote_ratio": None},
                "analysis": {"status": "disabled", "score": 0, "signal_strength": "thin", "signal_type": "other", "summary_zh": "summary", "action_suggestion": ""},
            },
        }
    )

    assert errors == ["presentation.content.excerpt_too_long"]
