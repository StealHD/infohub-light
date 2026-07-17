import pytest

from src.services.source_type_registry import (
    SourceConfigError,
    get_source_setup_guide,
    list_source_types,
    normalize_source_setup_input,
)


SOURCE_TYPES = {
    "rss",
    "telegram",
    "github",
    "reddit",
    "twitter",
    "website",
    "youtube",
    "apify",
}


def test_setup_guide_is_complete_bilingual_and_secret_safe():
    zh = get_source_setup_guide(None, "zh-CN")
    en = get_source_setup_guide(None, "en")

    assert {item["type"] for item in zh["source_types"]} == SOURCE_TYPES
    assert {item["type"] for item in en["source_types"]} == SOURCE_TYPES
    for locale, payload in (("zh-CN", zh), ("en", en)):
        assert payload["locale"] == locale
        for summary in payload["source_types"]:
            detail = get_source_setup_guide(summary["type"], locale)["source_type"]
            assert set(detail) >= {
                "type",
                "label",
                "description",
                "self_service",
                "requires_web_setup",
                "required_fields",
                "fields",
            }
            for field in detail["fields"]:
                assert set(field) >= {
                    "name",
                    "label",
                    "required",
                    "input_type",
                    "default",
                    "options",
                    "min",
                    "max",
                    "help",
                    "accepted_formats",
                    "examples",
                    "how_to_find",
                }

    serialized = repr((zh, en)).lower()
    assert "secret_env" not in serialized
    assert "token_env" not in serialized
    assert "sk-" not in serialized


def test_agent_setup_contract_is_distinct_from_the_rest_catalog_projection():
    guide_types = {
        item["type"] for item in get_source_setup_guide(None, "en")["source_types"]
    }
    rest_types = {item["type"] for item in list_source_types()}

    assert guide_types == SOURCE_TYPES
    assert rest_types == {
        "rss",
        "github_release",
        "github_user",
        "reddit_subreddit",
        "reddit_user",
        "telegram_channel",
        "apify_social",
        "hackernews",
    }


def test_agent_normalization_maps_public_types_to_catalog_types():
    github = normalize_source_setup_input(
        "github", {"repository": "https://github.com/openai/codex"}
    )
    reddit = normalize_source_setup_input(
        "reddit", {"subreddit": "https://reddit.com/r/LocalLLaMA/"}
    )
    telegram = normalize_source_setup_input(
        "telegram", {"channel": "https://t.me/durov"}
    )
    twitter = normalize_source_setup_input("twitter", {"handle": "@openai"})
    website = normalize_source_setup_input(
        "website", {"url": "https://example.com/feed.xml"}
    )
    youtube = normalize_source_setup_input(
        "youtube", {"url": "https://www.youtube.com/feeds/videos.xml?channel_id=UC123"}
    )
    apify = normalize_source_setup_input(
        "apify", {"platform": "x", "kind": "profile", "target": "openai"}
    )

    assert github == {
        "catalog_source_type": "github_release",
        "config": {
            "enabled": True,
            "owner": "openai",
            "repo": "codex",
            "type": "repo_releases",
        },
    }
    assert reddit["catalog_source_type"] == "reddit_subreddit"
    assert reddit["config"]["subreddit"] == "LocalLLaMA"
    assert telegram["catalog_source_type"] == "telegram_channel"
    assert telegram["config"]["channel"] == "durov"
    assert twitter == {
        "catalog_source_type": "apify_social",
        "config": {
            "enabled": True,
            "platform": "x",
            "kind": "profile",
            "target": "openai",
            "fetch_limit": 20,
            "analysis_mode": "full",
        },
    }
    assert website["catalog_source_type"] == "rss"
    assert youtube["catalog_source_type"] == "rss"
    assert apify["catalog_source_type"] == "apify_social"


@pytest.mark.parametrize(
    ("source_type", "config"),
    [
        ("rss", {"url": "https://example.com/feed?access_token=never-store-this"}),
        ("telegram", {"channel": "https://t.me/durov?api_key=never-store-this"}),
        ("github", {"repository": "https://github.com/openai/codex?auth=never-store-this"}),
        ("reddit", {"subreddit": "https://reddit.com/r/LocalLLaMA?token=never-store-this"}),
        ("twitter", {"handle": "https://x.com/openai?signature=never-store-this"}),
        ("website", {"url": "https://example.com/feed?credential=never-store-this"}),
        ("youtube", {"url": "https://youtube.com/feed?password=never-store-this"}),
        ("apify", {"platform": "x", "kind": "profile", "target": "https://x.com/openai?token=never-store-this"}),
        ("rss", {"url": "https://example.com/feed?cursor=access_token"}),
    ],
)
def test_agent_normalization_rejects_sensitive_url_queries_for_every_public_type(
    source_type, config
):
    with pytest.raises(SourceConfigError, match="credentials are not accepted") as exc_info:
        normalize_source_setup_input(source_type, config)

    assert "never-store-this" not in str(exc_info.value)


@pytest.mark.parametrize(
    ("source_type", "config"),
    [
        ("rss", {"url": "https://user:do-not-echo-credential@example.com/feed.xml"}),
        ("telegram", {"channel": "https://user:do-not-echo-credential@t.me/durov"}),
        ("github", {"repository": "https://user:do-not-echo-credential@github.com/openai/codex"}),
        ("reddit", {"subreddit": "https://user:do-not-echo-credential@reddit.com/r/LocalLLaMA"}),
        ("twitter", {"handle": "https://user:do-not-echo-credential@x.com/openai"}),
        ("website", {"url": "https://user:do-not-echo-credential@example.com/feed.xml"}),
        ("youtube", {"url": "https://user:do-not-echo-credential@youtube.com/feed"}),
        ("apify", {"platform": "x", "kind": "profile", "target": "https://user:do-not-echo-credential@x.com/openai"}),
    ],
)
def test_agent_normalization_rejects_url_userinfo_for_every_public_type(
    source_type, config
):
    with pytest.raises(SourceConfigError, match="credentials are not accepted") as exc_info:
        normalize_source_setup_input(source_type, config)

    assert "do-not-echo-credential" not in str(exc_info.value)


@pytest.mark.parametrize(
    "config",
    [
        {"url": "https://example.com/feed.xml", "name": {"cookie": "session-value"}},
        {"repository": {"token": "session-value"}},
        {"repository": ["openai/codex", {"authorization": "session-value"}]},
    ],
)
def test_agent_normalization_rejects_nested_credential_shaped_keys_and_values(config):
    with pytest.raises(SourceConfigError, match="credentials are not accepted") as exc_info:
        normalize_source_setup_input("website" if "url" in config else "github", config)

    assert "session-value" not in str(exc_info.value)


def test_agent_normalization_rejects_non_scalar_field_values_before_alias_parsing():
    with pytest.raises(SourceConfigError, match="url must be a string"):
        normalize_source_setup_input("website", {"url": ["https://example.com/feed.xml"]})


@pytest.mark.parametrize(
    "value",
    [
        "https://t.me/+privateinvite",
        "https://t.me/joinchat/privateinvite",
        "+privateinvite",
        "joinchat/privateinvite",
        "https://t.me/durov/preview",
    ],
)
def test_agent_normalization_rejects_private_or_non_channel_telegram_urls(value):
    with pytest.raises(SourceConfigError, match="public Telegram channel"):
        normalize_source_setup_input("telegram", {"channel": value})


def test_agent_normalization_wraps_malformed_url_as_source_config_error():
    with pytest.raises(SourceConfigError) as exc_info:
        normalize_source_setup_input("website", {"url": "https://[broken"})

    assert "https://[broken" not in str(exc_info.value)


def test_agent_normalization_rejects_credentials_without_echoing_them():
    with pytest.raises(SourceConfigError, match="credentials are not accepted"):
        normalize_source_setup_input(
            "github", {"repository": "openai/codex", "token": "never-store-this"}
        )
    with pytest.raises(SourceConfigError, match="credentials are not accepted") as exc_info:
        normalize_source_setup_input(
            "rss",
            {"url": "https://example.com/feed?access_token=never-store-this"},
        )
    assert "never-store-this" not in str(exc_info.value)
