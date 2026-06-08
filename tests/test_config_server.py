import json
from pathlib import Path

import pytest

from src.ui.server import (
    RadarWebHandler,
    apply_config_action,
    build_env_status,
    migrate_config_tag_layers,
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


def test_migrate_config_tag_layers_moves_custom_tags_to_personal_tags():
    config = _minimal_config()
    config["tags"] = ["AI Agent", "价格监控", "RAG/MCP"]
    config["personal_tags"] = ["能黄通"]
    config["sources"]["rss"][0]["tags"] = ["AI Agent", "价格监控"]

    migrated = migrate_config_tag_layers(config)

    assert migrated["tags"] == ["AI Agent", "RAG/MCP"]
    assert migrated["personal_tags"] == ["能黄通", "价格监控"]
    assert migrated["sources"]["rss"][0]["tags"] == ["AI Agent"]
    assert migrated["sources"]["rss"][0]["personal_tags"] == ["价格监控"]


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


def test_build_env_status_reports_apify_social_token(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    config_data = _minimal_config()
    config_data["sources"]["apify_social"] = {
        "enabled": True,
        "token_env": "APIFY_TOKEN",
        "subscriptions": [
            {
                "platform": "x",
                "kind": "profile",
                "target": "OpenAI",
                "fetch_limit": 10,
                "enabled": True,
            }
        ],
    }
    config = validate_config_data(config_data)

    status = build_env_status(config)

    by_name = {item["name"]: item for item in status}
    assert by_name["APIFY_TOKEN"] == {
        "name": "APIFY_TOKEN",
        "set": False,
        "used_by": [
            "sources.apify_social.token_env",
            "sources.apify_social.token_envs",
        ],
    }


def test_build_env_status_reports_apify_social_token_envs(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.setenv("APIFY_TOKEN_2", "secret-backup")
    config_data = _minimal_config()
    config_data["sources"]["apify_social"] = {
        "enabled": True,
        "token_env": "APIFY_TOKEN",
        "token_envs": ["APIFY_TOKEN", "APIFY_TOKEN_2"],
        "subscriptions": [
            {
                "platform": "instagram",
                "kind": "profile",
                "target": "tsucha_ri",
                "fetch_limit": 1,
                "enabled": True,
            }
        ],
    }
    config = validate_config_data(config_data)

    status = build_env_status(config)

    by_name = {item["name"]: item for item in status}
    assert by_name["APIFY_TOKEN"] == {
        "name": "APIFY_TOKEN",
        "set": False,
        "used_by": [
            "sources.apify_social.token_env",
            "sources.apify_social.token_envs",
        ],
    }
    assert by_name["APIFY_TOKEN_2"] == {
        "name": "APIFY_TOKEN_2",
        "set": True,
        "used_by": ["sources.apify_social.token_envs"],
    }
    assert "secret-backup" not in json.dumps(status)


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
        "tags": ["AI Agent", "RAG/MCP"],
        "enabled": True,
    }
    assert "AI Agent" in updated["tags"]
    assert "RAG/MCP" in updated["tags"]


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

    assert updated["tags"] == ["AI Agent", "RAG/MCP"]


def test_apply_config_action_sets_tag_library_from_literal_backslash_n():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "set_tags",
        {"tags": "AI Agent\\nRAG/MCP"},
    )

    assert updated["tags"] == ["AI Agent", "RAG/MCP"]


def test_apply_config_action_rejects_custom_tag_in_ai_tag_library():
    config = _minimal_config()

    with pytest.raises(ValueError, match="未知标签"):
        apply_config_action(
            config,
            "set_tags",
            {"tags": "AI Agent\n价格监控\n投资信号"},
        )


def test_apply_config_action_sets_personal_tag_library():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "set_personal_tags",
        {"personal_tags": "价格监控\n能黄通"},
    )

    assert updated["personal_tags"] == ["价格监控", "能黄通"]


def test_apply_config_action_allows_source_personal_tags_from_personal_library():
    config = _minimal_config()
    config["tags"] = ["AI Agent"]
    config["personal_tags"] = ["价格监控"]

    updated = apply_config_action(
        config,
        "upsert_rss",
        {
            "name": "Price Feed",
            "url": "https://example.com/prices.xml",
            "tags": "AI Agent",
            "personal_tags": "价格监控",
            "enabled": True,
        },
    )

    assert updated["sources"]["rss"][-1]["tags"] == ["AI Agent"]
    assert updated["sources"]["rss"][-1]["personal_tags"] == ["价格监控"]


def test_apply_config_action_rejects_unknown_controlled_tag():
    config = _minimal_config()

    with pytest.raises(ValueError, match="未知标签"):
        apply_config_action(
            config,
            "upsert_rss",
            {
                "name": "New Feed",
                "url": "https://example.org/feed.xml",
                "tags": "RandomVendorTag",
                "enabled": True,
            },
        )


def test_apply_config_action_adds_apify_social_subscription_without_token(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "upsert_apify_social_subscription",
        {
            "platform": "instagram",
            "kind": "hashtag",
            "target": "#aiagents",
            "fetch_limit": 12,
            "tags": "AI Agent, 行业动态",
            "personal_tags": "能黄通",
            "analysis_mode": "personal_only",
            "enabled": True,
        },
    )

    apify_social = updated["sources"]["apify_social"]
    assert apify_social["enabled"] is True
    assert apify_social["token_env"] == "APIFY_TOKEN"
    assert apify_social["subscriptions"][-1] == {
        "platform": "instagram",
        "kind": "hashtag",
        "target": "#aiagents",
        "fetch_limit": 12,
        "enabled": True,
        "tags": ["AI Agent", "行业动态"],
        "personal_tags": ["能黄通"],
        "analysis_mode": "personal_only",
    }


def test_apply_config_action_sets_apify_social_token_envs():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "set_apify_social_settings",
        {
            "enabled": True,
            "token_env": "APIFY_TOKEN",
            "token_envs": "APIFY_TOKEN\nAPIFY_TOKEN_2\nAPIFY_TOKEN_3",
            "timeout_seconds": 120,
            "actor_x": "altimis~scweet",
            "actor_instagram": "apify/instagram-api-scraper",
            "actor_facebook": "whoareyouanas/facebook-group-scraper",
            "actor_telegram": "thescrapelab/apify-telegram-scraper",
        },
    )

    apify = updated["sources"]["apify_social"]
    assert apify["token_env"] == "APIFY_TOKEN"
    assert apify["token_envs"] == ["APIFY_TOKEN", "APIFY_TOKEN_2", "APIFY_TOKEN_3"]
    assert apify["timeout_seconds"] == 120


def test_apply_config_action_rejects_secret_in_apify_token_envs():
    config = _minimal_config()

    with pytest.raises(ValueError, match="Apify Token 环境变量名"):
        apply_config_action(
            config,
            "set_apify_social_settings",
            {
                "enabled": True,
                "token_env": "APIFY_TOKEN",
                "token_envs": "APIFY_TOKEN\nsk-secret-value",
                "timeout_seconds": 120,
            },
        )


def test_apply_config_action_rejects_invalid_apify_social_target():
    config = _minimal_config()

    with pytest.raises(ValueError, match="Facebook"):
        apply_config_action(
            config,
            "upsert_apify_social_subscription",
            {
                "platform": "facebook",
                "kind": "page",
                "target": "openai",
                "fetch_limit": 10,
                "enabled": True,
            },
        )


def test_apply_config_action_deletes_apify_social_subscription():
    config = _minimal_config()
    config["sources"]["apify_social"] = {
        "enabled": True,
        "token_env": "APIFY_TOKEN",
        "subscriptions": [
            {"platform": "x", "kind": "profile", "target": "OpenAI", "fetch_limit": 10}
        ],
    }

    updated = apply_config_action(
        config,
        "delete_apify_social_subscription",
        {"index": 0},
    )

    assert updated["sources"]["apify_social"]["subscriptions"] == []


def test_source_test_apify_social_requires_token(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)

    with pytest.raises(ValueError, match="APIFY_TOKEN"):
        run_source_test(
            {
                "source_type": "apify_social",
                "platform": "x",
                "kind": "profile",
                "target": "OpenAI",
                "fetch_limit": 1,
            }
        )


def test_web_handler_prefers_generated_site_assets(tmp_path):
    data_dir = tmp_path / "data"
    generated_dir = data_dir / "site"
    static_dir = tmp_path / "static"
    generated_dir.mkdir(parents=True)
    static_dir.mkdir()
    (generated_dir / "styles.css").write_text("generated", encoding="utf-8")
    (static_dir / "styles.css").write_text("bundled", encoding="utf-8")

    handler = object.__new__(RadarWebHandler)
    handler.data_dir = data_dir
    handler.static_dir = static_dir

    resolved = Path(handler.translate_path("/styles.css?v=cache"))

    assert resolved.read_text(encoding="utf-8") == "generated"


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
        "tags": ["AI 编程"],
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
