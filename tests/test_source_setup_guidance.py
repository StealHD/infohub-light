import pytest

from src.services.source_type_registry import (
    SourceConfigError,
    get_source_setup_guide,
    normalize_source_setup_input,
)


SOURCE_TYPES = {
    "rss",
    "github_release",
    "github_user",
    "reddit_subreddit",
    "reddit_user",
    "telegram_channel",
    "apify_social",
    "hackernews",
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


def test_agent_normalization_accepts_public_aliases_and_rejects_credentials():
    assert normalize_source_setup_input(
        "github_release", {"repository": "https://github.com/openai/codex"}
    )["owner"] == "openai"
    assert normalize_source_setup_input(
        "reddit_subreddit", {"subreddit": "https://reddit.com/r/LocalLLaMA/"}
    )["subreddit"] == "LocalLLaMA"
    assert normalize_source_setup_input(
        "telegram_channel", {"channel": "https://t.me/durov"}
    )["channel"] == "durov"

    with pytest.raises(SourceConfigError, match="credentials are not accepted"):
        normalize_source_setup_input(
            "github_user", {"username": "openai", "token": "never-store-this"}
        )
    with pytest.raises(SourceConfigError, match="credentials are not accepted"):
        normalize_source_setup_input(
            "rss",
            {"url": "https://example.com/feed?access_token=never-store-this"},
        )
