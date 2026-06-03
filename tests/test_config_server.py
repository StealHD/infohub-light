import json

import pytest

from src.ui.server import (
    apply_config_action,
    build_env_status,
    normalize_config_payload,
    run_source_test,
    validate_config_data,
)


def _minimal_config():
    return {
        "version": "1.0",
        "ai": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
        },
        "sources": {
            "rss": [
                {
                    "name": "Example Feed",
                    "url": "https://example.com/feed.xml",
                    "enabled": True,
                }
            ],
            "hackernews": {"enabled": True},
        },
        "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
        "webhook": {
            "enabled": True,
            "url_env": "HORIZON_WEBHOOK_URL",
            "request_body": {"text": "#{summary}"},
        },
    }


def test_normalize_config_payload_accepts_wrapped_and_plain_json():
    config = _minimal_config()

    assert normalize_config_payload(json.dumps(config).encode()) == config
    assert normalize_config_payload(json.dumps({"config": config}).encode()) == config


def test_validate_config_data_accepts_valid_config():
    validated = validate_config_data(_minimal_config())

    assert validated.ai.provider.value == "openai"
    assert validated.sources.rss[0].name == "Example Feed"


def test_build_env_status_reports_presence_without_secret_values(monkeypatch):
    monkeypatch.setenv("OPENAI_API_KEY", "sk-secret-value")
    monkeypatch.delenv("HORIZON_WEBHOOK_URL", raising=False)
    config = validate_config_data(_minimal_config())

    status = build_env_status(config)

    by_name = {item["name"]: item for item in status}
    assert by_name["OPENAI_API_KEY"] == {
        "name": "OPENAI_API_KEY",
        "set": True,
        "used_by": ["ai.api_key_env"],
    }
    assert by_name["HORIZON_WEBHOOK_URL"] == {
        "name": "HORIZON_WEBHOOK_URL",
        "set": False,
        "used_by": ["webhook.url_env"],
    }
    assert "sk-secret-value" not in json.dumps(status)


def test_apply_config_action_adds_rss_after_url_validation():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "upsert_rss",
        {
            "name": "New Feed",
            "url": "https://example.org/feed.xml",
            "category": "ai-tools",
            "tags": "AI Agent, RAG",
            "enabled": True,
        },
    )

    assert updated["sources"]["rss"][-1] == {
        "name": "New Feed",
        "url": "https://example.org/feed.xml",
        "category": "ai-tools",
        "tags": ["AI Agent", "RAG"],
        "enabled": True,
    }
    assert "AI Agent" in updated["tags"]
    assert "RAG" in updated["tags"]


def test_apply_config_action_rejects_invalid_rss_url():
    config = _minimal_config()

    with pytest.raises(ValueError, match="RSS URL"):
        apply_config_action(
            config,
            "upsert_rss",
            {"name": "Bad Feed", "url": "not-a-url", "enabled": True},
        )


def test_apply_config_action_rejects_invalid_threshold():
    config = _minimal_config()

    with pytest.raises(ValueError, match="featured_score_threshold"):
        apply_config_action(
            config,
            "set_filtering",
            {"featured_score_threshold": 11},
        )


def test_apply_config_action_sets_recent_item_limit():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "set_filtering",
        {"recent_item_limit": 20},
    )

    assert updated["filtering"]["recent_item_limit"] == 20


def test_apply_config_action_rejects_secret_in_api_key_env():
    config = _minimal_config()

    with pytest.raises(ValueError, match="不能直接填写密钥"):
        apply_config_action(
            config,
            "set_ai",
            {
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "api_key_env": "AIza-not-an-env-name",
            },
        )


def test_apply_config_action_sets_tag_library():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "set_tags",
        {"tags": "AI Agent\nRAG，MCP"},
    )

    assert updated["tags"] == ["AI Agent", "RAG", "MCP"]


def test_apply_config_action_adds_github_release():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "upsert_github_release",
        {"owner": "openai", "repo": "codex", "enabled": True, "tags": "Codex"},
    )

    assert updated["sources"]["github"][-1] == {
        "type": "repo_releases",
        "owner": "openai",
        "repo": "codex",
        "enabled": True,
        "tags": ["Codex"],
    }


def test_source_payload_rejects_invalid_rss_url():
    with pytest.raises(ValueError, match="RSS URL"):
        run_source_test({"source_type": "rss", "url": "not-a-url"})


def test_source_payload_parses_rss_feed(monkeypatch):
    monkeypatch.setattr(
        "src.ui.server._fetch_text",
        lambda url, headers=None: """<?xml version="1.0"?>
<rss version="2.0">
  <channel>
    <title>Example</title>
    <item>
      <title>First item</title>
      <link>https://example.com/first</link>
    </item>
  </channel>
</rss>""",
    )

    result = run_source_test(
        {"source_type": "rss", "url": "https://example.com/feed.xml"}
    )

    assert result["ok"] is True
    assert result["count"] == 1
    assert result["sample_title"] == "First item"
