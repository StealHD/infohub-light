import pytest

from src.services.source_type_registry import (
    SourceConfigError,
    build_source_payload,
    list_source_types,
    source_key,
    validate_secret_env_name,
    validate_source_config,
)


def test_source_type_registry_lists_supported_types_and_templates():
    types = list_source_types()
    by_type = {item["type"]: item for item in types}

    assert {
        "rss",
        "github_release",
        "github_user",
        "reddit_subreddit",
        "reddit_user",
        "telegram_channel",
        "apify_social",
        "hackernews",
    }.issubset(by_type)
    assert by_type["github_release"]["required_fields"] == ["owner", "repo"]
    assert by_type["apify_social"]["template"]["platform"] == "x"


def test_source_type_registry_validates_config_and_builds_stable_keys():
    rss = validate_source_config("rss", {"url": "https://example.com/feed.xml"})
    github = validate_source_config("github_release", {"owner": "OpenAI", "repo": "Codex"})
    reddit = validate_source_config("reddit_subreddit", {"subreddit": "r/LocalLLaMA"})
    telegram = validate_source_config("telegram_channel", {"channel": "@durov"})

    assert rss["name"] == "https://example.com/feed.xml"
    assert github["type"] == "repo_releases"
    assert reddit["subreddit"] == "LocalLLaMA"
    assert telegram["channel"] == "durov"
    assert source_key("rss", rss) == "rss:https://example.com/feed.xml"
    assert source_key("github_release", github) == "github_release:openai/codex"
    assert source_key("reddit_subreddit", reddit) == "reddit_subreddit:localllama"
    assert source_key("telegram_channel", telegram) == "telegram_channel:durov"


def test_source_type_registry_rejects_invalid_configs_and_secret_values():
    with pytest.raises(SourceConfigError):
        validate_source_config("rss", {"url": "ftp://example.com/feed.xml"})
    with pytest.raises(SourceConfigError):
        validate_source_config("github_release", {"owner": "OpenAI"})
    with pytest.raises(SourceConfigError):
        validate_secret_env_name("sk-real-secret-value")


def test_source_type_registry_builds_worker_payload_without_expanding_secret(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "real-token-value")

    payload = build_source_payload(
        {
            "type": "github_release",
            "config": {"owner": "OpenAI", "repo": "Codex"},
            "secret_env": "GITHUB_TOKEN",
        }
    )

    assert payload == {
        "source_type": "github_release",
        "type": "repo_releases",
        "owner": "OpenAI",
        "repo": "Codex",
        "enabled": True,
        "token_env": "GITHUB_TOKEN",
    }
    assert "real-token-value" not in repr(payload)
