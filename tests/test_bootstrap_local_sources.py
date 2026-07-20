from __future__ import annotations

import json

from scripts.bootstrap_local_sources import bootstrap_local_sources
from src.services.secret_store import SecretStore
from src.services.feed_schedule import FeedScheduleService
from src.services.source_schedule import SourceScheduleService
from src.storage.service_store import ServiceStore


def _config() -> dict:
    return {
        "version": "1.0",
        "ai": {
            "enabled": True,
            "provider": "xiaomi",
            "model": "wrong-model",
            "api_key_env": "XIAOMI_API_KEY",
        },
        "tags": ["AI Agent", "AI 编程", "模型发布", "行业动态"],
        "personal_tags": [],
        "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
        "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
    }


def test_bootstrap_registers_write_only_keys_ai_config_and_four_sources(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    data_dir = tmp_path / "data"
    data_dir.mkdir()
    (data_dir / "config.json").write_text(json.dumps(_config()), encoding="utf-8")
    ServiceStore(data_dir).initialize()
    values = {
        "GOOGLE_API_KEY": "fake-google-private-value",
        "APIFY_TOKEN": "fake-apify-one-private-value",
        "APIFY_TOKEN_2": "fake-apify-two-private-value",
    }

    result = bootstrap_local_sources(data_dir, values)

    config = json.loads((data_dir / "config.json").read_text())
    assert config["ai"].items() >= {
        "enabled": True,
        "provider": "gemini",
        "model": "gemini-3.5-flash",
        "api_key_env": "GOOGLE_API_KEY",
        "summary_max_chars": 200,
        "analysis_max_output_tokens": 800,
        "analysis_content_chars": 1000,
        "analysis_comments_chars": 1500,
        "throttle_sec": 6.5,
    }.items()
    store = ServiceStore(data_dir)
    store.initialize()
    refs = store.list_secret_refs(workspace_id=store.get_default_workspace()["id"])
    assert [(item["name"], item["kind"], item["provider"], item["env_name"]) for item in refs] == [
        ("Gemini Primary", "ai", "gemini", "GOOGLE_API_KEY"),
        ("Apify Primary", "apify", "apify", "APIFY_TOKEN"),
        ("Apify Secondary", "apify", "apify", "APIFY_TOKEN_2"),
    ]
    assert all("value" not in item for item in refs)
    sources = store.list_visible_sources(store.get_user_by_username("owner"))
    source_shape = {
        source["display_name"]: (source["type"], source["scope"])
        for source in sources
    }
    assert source_shape == {
        "Apple Developer News": ("rss", "workspace"),
        "OpenAI News": ("rss", "workspace"),
        "Claude Code Releases": ("github_release", "workspace"),
        "X · @thsottiaux": ("apify_social", "private"),
    }
    subscriptions = store.list_user_subscriptions(store.get_user_by_username("owner")["id"])
    assert sorted(item["priority"] for item in subscriptions) == [50, 80, 80, 80]
    x_source = next(source for source in sources if source["type"] == "apify_social")
    assert x_source["secret_env"] == "APIFY_TOKEN_2"
    assert x_source["config"] == {
        "analysis_mode": "full", "enabled": True, "fetch_limit": 1,
        "kind": "profile", "platform": "x", "target": "thsottiaux",
    }
    x_subscription = next(
        item for item in subscriptions if item["source_id"] == x_source["id"]
    )
    source_schedule = SourceScheduleService(store).get_subscription_schedule(
        workspace_id=store.get_default_workspace()["id"],
        user_id=store.get_user_by_username("owner")["id"],
        subscription_id=x_subscription["id"],
    )
    feed_schedule = FeedScheduleService(store).get_user_schedule(
        workspace_id=store.get_default_workspace()["id"],
        user_id=store.get_user_by_username("owner")["id"],
    )
    assert source_schedule["enabled"] is True
    assert source_schedule["interval_minutes"] == 30
    assert feed_schedule["enabled"] is True
    assert feed_schedule["interval_minutes"] == 360
    assert SecretStore(data_dir).read() == values
    serialized = json.dumps(result)
    assert all(secret not in serialized for secret in values.values())
    assert result["source_count"] == 4
    assert result["subscription_count"] == 4
