import pytest

import src.services.source_type_registry as source_type_registry
from src.services.source_type_registry import (
    SourceConfigError,
    build_source_payload,
    list_source_types,
    source_key,
    validate_secret_env_name,
    validate_source_config,
)


def test_agent_source_type_validator_owns_exact_public_enum():
    public_types = {
        "rss",
        "telegram",
        "github",
        "reddit",
        "twitter",
        "website",
        "youtube",
        "apify",
    }

    assert {
        source_type_registry.validate_agent_source_type(item)
        for item in public_types
    } == public_types
    with pytest.raises(SourceConfigError, match="unsupported source type"):
        source_type_registry.validate_agent_source_type("hackernews")


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
    assert set(by_type["rss"]) == {
        "type",
        "label",
        "description",
        "required_fields",
        "template",
        "fields",
        "supports_secret_env",
        "credential_mode",
    }
    assert by_type["rss"]["credential_mode"] == "none"
    assert by_type["apify_social"]["credential_mode"] == "source_secret"


def test_source_type_registry_projects_workspace_apify_pool_mode(monkeypatch):
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")

    by_type = {item["type"]: item for item in list_source_types()}

    assert by_type["apify_social"]["supports_secret_env"] is False
    assert by_type["apify_social"]["credential_mode"] == "workspace_apify_pool"
    assert by_type["rss"]["credential_mode"] == "none"


def test_source_type_registry_exposes_safe_canonical_field_metadata():
    types = {item["type"]: item for item in list_source_types()}
    exact_keys = {
        "name",
        "label",
        "input_type",
        "required",
        "default",
        "options",
        "min",
        "max",
        "help",
    }
    allowed_input_types = {"text", "url", "number", "select", "boolean"}

    assert set(types) == {
        "rss",
        "github_release",
        "github_user",
        "reddit_subreddit",
        "reddit_user",
        "telegram_channel",
        "apify_social",
        "hackernews",
    }
    for source_type in types.values():
        assert source_type["fields"]
        for field in source_type["fields"]:
            assert set(field) == exact_keys
            assert field["input_type"] in allowed_input_types
            assert isinstance(field["required"], bool)
            assert isinstance(field["options"], list)
            assert isinstance(field["help"], str) and field["help"]
            assert field["name"] not in {"secret", "secret_env", "token", "token_env", "api_key"}

    by_field = {
        source_type: {field["name"]: field for field in definition["fields"]}
        for source_type, definition in types.items()
    }
    assert by_field["rss"]["url"] == {
        "name": "url",
        "label": "Feed URL",
        "input_type": "url",
        "required": True,
        "default": None,
        "options": [],
        "min": None,
        "max": None,
        "help": "HTTP or HTTPS RSS/Atom URL without embedded credentials.",
    }
    assert by_field["reddit_subreddit"]["sort"]["default"] == "hot"
    assert by_field["reddit_subreddit"]["sort"]["options"] == [
        "hot",
        "new",
        "top",
        "rising",
        "controversial",
    ]
    assert by_field["reddit_subreddit"]["time_filter"]["default"] == "day"
    assert by_field["reddit_subreddit"]["fetch_limit"] | {
        "name": "fetch_limit",
        "label": "Fetch limit",
        "input_type": "number",
        "required": False,
        "default": 25,
        "options": [],
        "min": 1,
        "max": 100,
        "help": "Maximum posts requested per fetch.",
    } == by_field["reddit_subreddit"]["fetch_limit"]
    assert by_field["reddit_user"]["fetch_limit"]["default"] == 10
    assert by_field["telegram_channel"]["fetch_limit"] | {
        "default": 20,
        "min": 1,
        "max": 100,
    } == by_field["telegram_channel"]["fetch_limit"]
    assert by_field["apify_social"]["platform"]["options"] == [
        "x",
        "instagram",
        "facebook",
        "telegram",
    ]
    assert by_field["apify_social"]["analysis_mode"]["options"] == [
        "full",
        "personal_only",
    ]
    assert by_field["hackernews"]["fetch_top_stories"] | {
        "default": 30,
        "min": 1,
        "max": 500,
    } == by_field["hackernews"]["fetch_top_stories"]
    assert by_field["hackernews"]["min_score"]["default"] == 100
    assert by_field["hackernews"]["min_score"]["min"] == 0


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


def test_rss_latest_item_flag_is_opt_in_and_reaches_worker_payload():
    definition = next(item for item in list_source_types() if item["type"] == "rss")
    field = next(
        item for item in definition["fields"] if item["name"] == "keep_latest_item"
    )
    assert field["input_type"] == "boolean"
    assert field["default"] is False

    default = validate_source_config("rss", {"url": "https://example.com/feed.xml"})
    enabled = validate_source_config(
        "rss",
        {"url": "https://example.com/feed.xml", "keep_latest_item": True},
    )

    assert default["keep_latest_item"] is False
    assert enabled["keep_latest_item"] is True
    assert build_source_payload(
        {
            "id": "src-rss",
            "type": "rss",
            "display_name": "Profile RSS",
            "config": enabled,
        }
    )["keep_latest_item"] is True


def test_source_type_registry_rejects_invalid_configs_and_secret_values():
    with pytest.raises(SourceConfigError):
        validate_source_config("rss", {"url": "ftp://example.com/feed.xml"})
    with pytest.raises(SourceConfigError):
        validate_source_config("github_release", {"owner": "OpenAI"})
    with pytest.raises(SourceConfigError):
        validate_secret_env_name("sk-real-secret-value")
    with pytest.raises(SourceConfigError, match="environment-variable placeholders"):
        validate_source_config(
            "rss",
            {"url": "https://attacker.example/${OPENAI_API_KEY}"},
        )
    with pytest.raises(SourceConfigError, match="credentials"):
        validate_source_config(
            "rss",
            {"url": "https://API_TOKEN@feeds.example.com/private.xml"},
        )


def test_source_type_registry_builds_worker_payload_without_expanding_secret(monkeypatch):
    monkeypatch.setenv("GITHUB_TOKEN", "real-token-value")

    payload = build_source_payload(
        {
            "id": "src-release",
            "type": "github_release",
            "display_name": "OpenAI Codex Releases",
            "config": {"owner": "OpenAI", "repo": "Codex"},
            "secret_env": "GITHUB_TOKEN",
        }
    )

    assert payload == {
        "source_type": "github_release",
        "source_id": "src-release",
        "source_display_name": "OpenAI Codex Releases",
        "catalog_source_type": "github_release",
        "type": "repo_releases",
        "owner": "OpenAI",
        "repo": "Codex",
        "enabled": True,
        "token_env": "GITHUB_TOKEN",
    }
    assert "real-token-value" not in repr(payload)
