from src.models import Config
from src.services.user_config_builder import build_user_config_data
from src.storage.service_store import ServiceStore


def _base_config():
    return {
        "version": "1.0",
        "ai": {
            "enabled": False,
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
        },
        "sources": {
            "rss": [],
            "github": [],
            "hackernews": {"enabled": False},
            "reddit": {"enabled": False, "subreddits": [], "users": [], "fetch_comments": 5},
            "telegram": {"enabled": False, "channels": []},
            "apify_social": {
                "enabled": False,
                "token_env": "APIFY_TOKEN",
                "token_envs": ["APIFY_TOKEN"],
                "subscriptions": [],
            },
        },
        "filtering": {"ai_score_threshold": 7.0, "time_window_hours": 24},
    }


def test_user_config_builder_merges_catalog_source_with_subscription_overrides(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
        role="member",
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="AI Feed",
        default_channel="产品机会",
        default_topics=["价格监控"],
        config={"name": "AI Feed", "url": "https://example.com/feed.xml", "enabled": True},
        secret_env="RSS_TOKEN",
    )
    store.create_subscription(
        user_id=member["id"],
        source_id=source_id,
        override_channel="AI",
        override_topics=["Codex", "AI Agent"],
        personal_tags=["高定"],
        analysis_mode="personal_only",
        priority=7,
    )

    data = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=member["id"],
        base_config=_base_config(),
    )
    config = Config.model_validate(data)
    rss = config.sources.rss[0]

    assert rss.name == "AI Feed"
    assert str(rss.url) == "https://example.com/feed.xml"
    assert rss.channel == "AI"
    assert rss.topics == ["Codex", "AI Agent"]
    assert rss.tags == ["Codex", "AI Agent"]
    assert rss.personal_tags == ["高定"]
    assert data["sources"]["rss"][0]["analysis_mode"] == "personal_only"
    assert data["sources"]["rss"][0]["token_env"] == "RSS_TOKEN"


def test_user_config_builder_adds_apify_subscription_secret_env(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="OpenAI X",
        config={"platform": "x", "kind": "profile", "target": "OpenAI", "fetch_limit": 5},
        secret_env="APIFY_TOKEN_2",
    )
    store.create_subscription(user_id=owner["id"], source_id=source_id)

    data = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        base_config=_base_config(),
    )

    assert data["sources"]["apify_social"]["enabled"] is True
    assert data["sources"]["apify_social"]["subscriptions"][0]["token_env"] == "APIFY_TOKEN_2"
    assert data["sources"]["apify_social"]["subscriptions"][0]["target"] == "OpenAI"
