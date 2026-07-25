import json
import socket
from contextlib import asynccontextmanager
from types import SimpleNamespace
from pathlib import Path

import httpx
import pytest

from src.services import network_policy

from src.ui.server import (
    _APIFY_SOCIAL_DEFAULT_ACTORS,
    RadarWebHandler,
    apply_config_action,
    build_env_status,
    migrate_config_tag_layers,
    normalize_config_payload,
    run_source_test,
    source_update_payload,
    validate_config_data,
)
from src.tag_policy import (
    normalize_channel,
    normalize_signal_strength,
    normalize_signal_type,
    normalize_tags,
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
    assert validated.ai.enabled is True
    assert validated.sources.rss[0].name == "Example Feed"
    assert validated.premium_analysis.enabled is False
    assert validated.article_graph.enabled is False


def test_apify_social_ui_default_uses_single_item_capable_x_actor():
    assert _APIFY_SOCIAL_DEFAULT_ACTORS["x"] == "xquik/x-tweet-scraper"


def test_validate_config_data_accepts_article_graph_config():
    config = _minimal_config()
    config["premium_analysis"] = {
        "enabled": True,
        "full_fetch_score_threshold": 8.5,
        "max_full_fetch_per_run": 6,
        "max_full_text_chars": 8000,
    }
    config["article_graph"] = {
        "enabled": True,
        "premium_score_threshold": 8.5,
        "relation_top_k": 3,
        "min_relation_score": 0.45,
    }

    validated = validate_config_data(config)

    assert validated.premium_analysis.enabled is True
    assert validated.premium_analysis.max_full_fetch_per_run == 6
    assert validated.article_graph.enabled is True
    assert validated.article_graph.min_relation_score == 0.45


def test_hub_taxonomy_normalizes_channels_topics_and_signals():
    assert normalize_channel("AI 编程") == "AI"
    assert normalize_channel("美股") == "投资"
    assert normalize_channel("价格监控") == "产品机会"
    assert normalize_channel("unknown") == "其他"

    assert normalize_tags(
        ["Codex", "价格监控", "投资信号"],
        max_tags=None,
    ) == ["Codex", "价格监控", "投资信号"]

    assert normalize_signal_strength("Strong signal") == "strong"
    assert normalize_signal_strength("弱信号") == "thin"
    assert normalize_signal_type("融资") == "funding"
    assert normalize_signal_type("教程") == "tutorial"


def test_migrate_config_tag_layers_keeps_custom_tags_as_reading_topics():
    config = _minimal_config()
    config["tags"] = ["AI Agent", "价格监控", "RAG/MCP"]
    config["personal_tags"] = ["能黄通"]
    config["sources"]["rss"][0]["tags"] = ["AI Agent", "价格监控"]

    migrated = migrate_config_tag_layers(config)

    assert migrated["tags"] == ["AI Agent", "价格监控", "RAG/MCP"]
    assert migrated["personal_tags"] == ["能黄通"]
    assert migrated["sources"]["rss"][0]["tags"] == ["AI Agent", "价格监控"]
    assert "personal_tags" not in migrated["sources"]["rss"][0]


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


def test_env_status_hides_ai_key_when_ai_disabled(monkeypatch):
    monkeypatch.delenv("XIAOMI_API_KEY", raising=False)
    config_data = _minimal_config()
    config_data["ai"]["enabled"] = False
    config_data["ai"]["provider"] = "xiaomi"
    config_data["ai"]["api_key_env"] = "XIAOMI_API_KEY"
    config = validate_config_data(config_data)

    names = {item["name"] for item in build_env_status(config)}

    assert "XIAOMI_API_KEY" not in names


def test_env_status_hides_apify_tokens_when_apify_social_disabled(monkeypatch):
    monkeypatch.delenv("APIFY_TOKEN", raising=False)
    monkeypatch.delenv("APIFY_TOKEN_2", raising=False)
    config_data = _minimal_config()
    config_data["sources"]["apify_social"] = {
        "enabled": False,
        "token_env": "APIFY_TOKEN",
        "token_envs": ["APIFY_TOKEN", "APIFY_TOKEN_2"],
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

    names = {item["name"] for item in build_env_status(config)}

    assert "APIFY_TOKEN" not in names
    assert "APIFY_TOKEN_2" not in names


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


def test_build_env_status_reports_apify_social_subscription_token_env(monkeypatch):
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
                "token_env": "APIFY_TOKEN_2",
                "fetch_limit": 1,
                "enabled": True,
            }
        ],
    }
    config = validate_config_data(config_data)

    status = build_env_status(config)

    by_name = {item["name"]: item for item in status}
    assert "APIFY_TOKEN" not in by_name
    assert by_name["APIFY_TOKEN_2"] == {
        "name": "APIFY_TOKEN_2",
        "set": True,
        "used_by": ["sources.apify_social.subscriptions[0].token_env"],
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
        "channel": "AI",
        "category": "AI",
        "topics": ["AI Agent", "RAG/MCP"],
        "tags": ["AI Agent", "RAG/MCP"],
        "enabled": True,
    }
    assert "AI Agent" in updated["tags"]
    assert "RAG/MCP" in updated["tags"]


def test_apply_config_action_accepts_explicit_channel_and_topics_fields():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "upsert_rss",
        {
            "name": "Investment Feed",
            "url": "https://example.org/investing.xml",
            "channel": "投资",
            "topics": "美股, 估值",
            "enabled": True,
        },
    )

    assert updated["sources"]["rss"][-1] == {
        "name": "Investment Feed",
        "url": "https://example.org/investing.xml",
        "channel": "投资",
        "category": "投资",
        "topics": ["美股", "估值"],
        "tags": ["美股", "估值"],
        "enabled": True,
    }
    assert "美股" in updated["tags"]
    assert "估值" in updated["tags"]


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


def test_apply_config_action_sets_switchable_rsshub_base_url():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "set_rsshub",
        {"base_url": "https://rsshub.example.com/"},
    )

    assert updated["rsshub"] == {
        "base_url": "https://rsshub.example.com"
    }


@pytest.mark.parametrize(
    "base_url",
    [
        "file:///tmp/rsshub",
        "http://user:password@example.com",
        "https://example.com/rsshub",
    ],
)
def test_apply_config_action_rejects_unsafe_rsshub_base_url(base_url):
    with pytest.raises(ValueError, match="RSSHub Base URL"):
        apply_config_action(
            _minimal_config(),
            "set_rsshub",
            {"base_url": base_url},
        )


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


def test_apply_config_action_saves_ai_enabled_toggle():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "set_ai",
        {
            "enabled": False,
            "provider": "xiaomi",
            "model": "mimo-v2.5-pro",
            "api_key_env": "XIAOMI_API_KEY",
            "base_url": "https://token-plan-cn.xiaomimimo.com/v1",
            "languages": "zh",
        },
    )

    assert updated["ai"]["enabled"] is False
    assert updated["ai"]["provider"] == "xiaomi"
    assert updated["ai"]["api_key_env"] == "XIAOMI_API_KEY"


def test_apply_config_action_saves_ai_summary_and_output_limits():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "set_ai",
        {
            "enabled": True,
            "provider": "gemini",
            "model": "gemini-2.5-flash",
            "api_key_env": "GOOGLE_API_KEY",
            "languages": "zh",
            "summary_max_chars": 200,
            "analysis_max_output_tokens": 800,
        },
    )

    assert updated["ai"]["summary_max_chars"] == 200
    assert updated["ai"]["analysis_max_output_tokens"] == 800


@pytest.mark.parametrize(
    ("field", "value"),
    [("summary_max_chars", 99), ("summary_max_chars", 501), ("analysis_max_output_tokens", 255), ("analysis_max_output_tokens", 2049)],
)
def test_apply_config_action_rejects_out_of_range_ai_limits(field, value):
    config = _minimal_config()

    with pytest.raises(ValueError, match=field):
        apply_config_action(
            config,
            "set_ai",
            {
                "enabled": True,
                "provider": "gemini",
                "model": "gemini-2.5-flash",
                "api_key_env": "GOOGLE_API_KEY",
                field: value,
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


def test_apply_config_action_sets_topic_library_from_array_and_allows_empty():
    config = _minimal_config()
    config["tags"] = ["Old Topic"]

    updated = apply_config_action(
        config,
        "set_tags",
        {"topics": [" AI Agent ", "ai agent", "RAG/MCP"]},
    )

    assert updated["tags"] == ["AI Agent", "RAG/MCP"]
    assert apply_config_action(updated, "set_tags", {"topics": []})["tags"] == []


def test_apply_config_action_limits_topic_library_size_and_topic_length():
    config = _minimal_config()

    accepted = apply_config_action(config, "set_tags", {"topics": ["x" * 40]})
    assert accepted["tags"] == ["x" * 40]

    with pytest.raises(ValueError, match="主题数量不能超过 100"):
        apply_config_action(config, "set_tags", {"topics": [f"Topic {index}" for index in range(101)]})

    with pytest.raises(ValueError, match="主题长度不能超过 40"):
        apply_config_action(config, "set_tags", {"topics": ["x" * 41]})


def test_apply_config_action_sets_tag_library_from_literal_backslash_n():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "set_tags",
        {"tags": "AI Agent\\nRAG/MCP"},
    )

    assert updated["tags"] == ["AI Agent", "RAG/MCP"]


def test_apply_config_action_allows_custom_reading_topics_in_tag_library():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "set_tags",
        {"tags": "AI Agent\n价格监控\n投资信号"},
    )

    assert updated["tags"] == ["AI Agent", "价格监控", "投资信号"]


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


def test_apply_config_action_allows_custom_source_reading_topics():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "upsert_rss",
        {
            "name": "New Feed",
            "url": "https://example.org/feed.xml",
            "tags": "RandomVendorTag",
            "enabled": True,
        },
    )

    assert updated["sources"]["rss"][-1]["topics"] == ["RandomVendorTag"]
    assert updated["sources"]["rss"][-1]["tags"] == ["RandomVendorTag"]


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
        "topics": ["AI Agent", "行业动态"],
        "tags": ["AI Agent", "行业动态"],
        "personal_tags": ["能黄通"],
        "analysis_mode": "personal_only",
    }


def test_apply_config_action_adds_apify_social_subscription_token_env():
    config = _minimal_config()

    updated = apply_config_action(
        config,
        "upsert_apify_social_subscription",
        {
            "platform": "x",
            "kind": "profile",
            "target": "OpenAI",
            "token_env": "APIFY_TOKEN_2",
            "fetch_limit": 10,
            "enabled": True,
        },
    )

    item = updated["sources"]["apify_social"]["subscriptions"][-1]
    assert item["token_env"] == "APIFY_TOKEN_2"


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


def test_apply_config_action_rejects_secret_in_apify_subscription_token_env():
    config = _minimal_config()

    with pytest.raises(ValueError, match="Apify Key 环境变量名"):
        apply_config_action(
            config,
            "upsert_apify_social_subscription",
            {
                "platform": "x",
                "kind": "profile",
                "target": "OpenAI",
                "token_env": "sk-secret-value",
                "fetch_limit": 10,
                "enabled": True,
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


def test_web_handler_serves_bundled_assets_and_generated_data(tmp_path):
    data_dir = tmp_path / "data"
    generated_dir = data_dir / "site"
    static_dir = tmp_path / "static"
    generated_dir.mkdir(parents=True)
    static_dir.mkdir()
    (generated_dir / "styles.css").write_text("generated", encoding="utf-8")
    (static_dir / "styles.css").write_text("bundled", encoding="utf-8")
    (generated_dir / "radar-data.json").write_text('{"ok": true}', encoding="utf-8")

    handler = object.__new__(RadarWebHandler)
    handler.data_dir = data_dir
    handler.static_dir = static_dir

    resolved_asset = Path(handler.translate_path("/styles.css?v=cache"))
    resolved_data = Path(handler.translate_path("/radar-data.json?v=cache"))

    assert resolved_asset.read_text(encoding="utf-8") == "bundled"
    assert resolved_data.read_text(encoding="utf-8") == '{"ok": true}'


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
        "topics": ["Codex"],
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
    response_schema = result["response_schemas"][0]
    assert response_schema["source_id"] == "rss"
    assert response_schema["catalog_type"] == "rss"
    assert response_schema["capture_status"] == "captured"
    assert {field["path"] for field in response_schema["upstream"]["fields"]} >= {
        "entries",
        "entries.title",
        "entries.link",
    }
    assert "sample_title" in {
        field["path"] for field in response_schema["normalized"]["fields"]
    }


def test_source_test_propagates_member_public_network_policy(monkeypatch):
    seen = []

    def fake_fetch(url, *, headers=None, enforce_public_network=False):
        seen.append((url, enforce_public_network))
        return """<?xml version="1.0"?>
<rss version="2.0"><channel><item><title>Safe</title></item></channel></rss>"""

    monkeypatch.setattr("src.ui.server._fetch_text", fake_fetch)

    run_source_test({
        "source_type": "rss",
        "url": "https://example.com/feed.xml",
        "enforce_public_network": True,
    })

    assert seen == [("https://example.com/feed.xml", True)]


def test_source_test_connects_to_validated_ip_with_original_host_and_sni(monkeypatch):
    feed = b"""<?xml version="1.0"?>
<rss version="2.0"><channel><item><title>Safe</title></item></channel></rss>"""
    calls = []

    def resolve(_host, port, *, type):
        return [
            (socket.AF_INET, type, socket.IPPROTO_TCP, "", ("93.184.216.34", port))
        ]

    class FakeAsyncClient:
        def __init__(self, **_kwargs):
            pass

        async def __aenter__(self):
            return self

        async def __aexit__(self, *_args):
            return None

        @asynccontextmanager
        async def stream(self, method, url, **kwargs):
            calls.append((url, kwargs))
            request = httpx.Request(
                method,
                url,
                headers=kwargs.get("headers"),
                extensions=kwargs.get("extensions"),
            )
            yield httpx.Response(200, content=feed, request=request)

    monkeypatch.setattr(socket, "getaddrinfo", resolve)
    monkeypatch.setattr(
        network_policy,
        "httpx",
        SimpleNamespace(
            AsyncClient=FakeAsyncClient,
            Response=httpx.Response,
            TransportError=httpx.TransportError,
        ),
        raising=False,
    )

    result = run_source_test(
        {
            "source_type": "rss",
            "url": "https://feeds.example.test/feed.xml",
            "enforce_public_network": True,
        }
    )

    assert result["sample_title"] == "Safe"
    assert calls[0][0] == "https://93.184.216.34/feed.xml"
    assert calls[0][1]["headers"]["Host"] == "feeds.example.test"
    assert calls[0][1]["extensions"]["sni_hostname"] == "feeds.example.test"


def test_source_test_supports_reddit_user(monkeypatch):
    seen = []

    def fake_fetch_json(url, headers=None):
        seen.append(url)
        return {
            "data": {
                "children": [
                    {
                        "kind": "t3",
                        "data": {
                            "title": "User post",
                            "permalink": "/r/test/comments/abc/user_post/",
                        },
                    }
                ]
            }
        }

    monkeypatch.setattr("src.ui.server._fetch_json", fake_fetch_json)

    result = run_source_test(
        {"source_type": "reddit_user", "username": "spez", "sort": "new"}
    )

    assert seen == ["https://www.reddit.com/user/spez/submitted.json?limit=5&sort=new&raw_json=1"]
    assert result["ok"] is True
    assert result["source_type"] == "reddit_user"
    assert result["sample_title"] == "User post"


def test_source_update_payload_validates_hours_and_index():
    assert source_update_payload({"source_type": "rss", "index": "2", "hours": "48"}) == (
        "rss",
        2,
        48,
    )
    assert source_update_payload({"source_type": "hackernews", "hours": ""}) == (
        "hackernews",
        None,
        24,
    )

    with pytest.raises(ValueError, match="hours"):
        source_update_payload({"source_type": "rss", "index": 0, "hours": 721})

    with pytest.raises(ValueError, match="index"):
        source_update_payload({"source_type": "rss", "hours": 24})
