from __future__ import annotations

import pytest

from src.models import AIProvider, Config
from src.source_selection import (
    SourceSelectionError,
    apply_source_filter,
    filter_config_for_source_ref,
    parse_source_ref,
)


def _config() -> Config:
    return Config.model_validate(
        {
            "ai": {
                "provider": AIProvider.OPENAI,
                "model": "test-model",
                "api_key_env": "OPENAI_API_KEY",
            },
            "sources": {
                "rss": [
                    {"name": "Feed A", "url": "https://a.example/feed.xml"},
                    {"name": "Feed B", "url": "https://b.example/feed.xml"},
                ],
                "github": [
                    {"type": "repo_releases", "owner": "openai", "repo": "codex"},
                    {"type": "user_events", "username": "octocat"},
                ],
                "hackernews": {"enabled": True},
                "reddit": {
                    "enabled": True,
                    "subreddits": [
                        {"subreddit": "LocalLLaMA"},
                        {"subreddit": "Python", "enabled": False},
                    ],
                },
                "telegram": {
                    "enabled": True,
                    "channels": [{"channel": "durov"}],
                },
                "apify_social": {
                    "enabled": True,
                    "token_env": "APIFY_TOKEN",
                    "subscriptions": [
                        {"platform": "x", "kind": "profile", "target": "OpenAI"},
                        {"platform": "instagram", "kind": "profile", "target": "openai"},
                    ],
                },
                "ossinsight": {"enabled": True, "languages": ["Python"]},
            },
            "filtering": {},
        }
    )


def test_parse_source_ref_requires_index_for_indexed_sources() -> None:
    assert parse_source_ref("rss", 1).ref == "rss:1"
    assert parse_source_ref("rss:1").ref == "rss:1"
    assert parse_source_ref("hackernews").ref == "hackernews"

    with pytest.raises(SourceSelectionError, match="index"):
        parse_source_ref("rss")


def test_filter_config_for_source_ref_keeps_only_one_apify_subscription() -> None:
    filtered = filter_config_for_source_ref(_config(), parse_source_ref("apify_social", 1))

    assert filtered.sources.apify_social.enabled is True
    assert len(filtered.sources.apify_social.subscriptions) == 1
    assert filtered.sources.apify_social.subscriptions[0].target == "openai"
    assert filtered.sources.rss == []
    assert filtered.sources.github == []
    assert filtered.sources.hackernews.enabled is False
    assert filtered.sources.reddit.enabled is False
    assert filtered.sources.telegram.enabled is False
    assert filtered.sources.ossinsight.enabled is False


def test_filter_config_for_source_ref_rejects_disabled_item() -> None:
    with pytest.raises(SourceSelectionError, match="disabled"):
        filter_config_for_source_ref(_config(), parse_source_ref("reddit_subreddit", 1))


def test_apply_source_filter_supports_apify_social_and_ossinsight() -> None:
    filtered, chosen, unknown = apply_source_filter(
        _config(),
        ["apify_social", "ossinsight", "unknown"],
    )

    assert chosen == ["apify_social", "ossinsight"]
    assert unknown == ["unknown"]
    assert filtered.sources.apify_social.enabled is True
    assert filtered.sources.ossinsight.enabled is True
    assert filtered.sources.rss == []
    assert filtered.sources.hackernews.enabled is False
