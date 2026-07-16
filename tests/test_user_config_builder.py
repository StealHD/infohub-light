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
        config={
            "name": "AI Feed",
            "url": "https://example.com/feed.xml",
            "enabled": True,
            "keep_latest_item": True,
        },
        source_key="rss:https://example.com/feed.xml",
        secret_env="RSS_TOKEN",
    )
    subscription_id = store.create_subscription(
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
    assert rss.analysis_mode.value == "personal_only"
    assert rss.source_id == source_id
    assert rss.subscription_id == subscription_id["id"]
    assert rss.source_key == "rss:https://example.com/feed.xml"
    assert rss.source_priority == 7
    assert rss.source_display_name == "AI Feed"
    assert rss.catalog_source_type == "rss"
    assert rss.keep_latest_item is True
    assert data["sources"]["rss"][0]["analysis_mode"] == "personal_only"
    assert data["sources"]["rss"][0]["source_priority"] == 7
    assert data["sources"]["rss"][0]["source_display_name"] == "AI Feed"
    assert data["sources"]["rss"][0]["catalog_source_type"] == "rss"
    assert data["sources"]["rss"][0]["keep_latest_item"] is True
    assert data["sources"]["rss"][0]["token_env"] == "RSS_TOKEN"
    assert rss.enforce_public_network is False


def test_user_config_builder_restricts_member_owned_rss_to_public_network(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
        role="member",
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=member["id"],
        source_type="rss",
        display_name="Member Feed",
        config={"name": "Member Feed", "url": "https://example.com/member.xml"},
    )
    store.create_subscription(user_id=member["id"], source_id=source_id)

    data = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=member["id"],
        base_config=_base_config(),
    )

    assert data["sources"]["rss"][0]["enforce_public_network"] is True


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


def test_instagram_profile_details_is_requested_only_until_avatar_is_cached(tmp_path, monkeypatch):
    from datetime import datetime, timezone

    from src.models import ContentItem, SourceType
    from src.services.media_cache import MediaCacheService

    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"], scope="private", owner_user_id=owner["id"],
        source_type="apify_social", display_name="Instagram",
        config={"platform": "instagram", "kind": "profile", "target": "tsucha_ri", "fetch_limit": 1},
    )
    store.create_subscription(user_id=owner["id"], source_id=source_id)

    first = build_user_config_data(
        store=store, workspace_id=workspace["id"], user_id=owner["id"], base_config=_base_config()
    )
    assert first["sources"]["apify_social"]["subscriptions"][0]["fetch_profile_details"] is True

    MediaCacheService(
        store, data_dir=tmp_path,
        fetch_image=lambda _url: (b"\x89PNG\r\n\x1a\nprofile", "image/png"),
    ).cache_items(
        workspace_id=workspace["id"], user_id=owner["id"],
        items=[ContentItem(
            id="instagram:post:one", source_type=SourceType.INSTAGRAM,
            title="Post", url="https://instagram.com/p/one",
            published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            metadata={"source_id": source_id, "author_avatar_url": "https://cdn.example.com/avatar.png"},
        )],
    )
    second = build_user_config_data(
        store=store, workspace_id=workspace["id"], user_id=owner["id"], base_config=_base_config()
    )
    assert second["sources"]["apify_social"]["subscriptions"][0]["fetch_profile_details"] is False


def test_user_config_builder_disables_non_catalog_global_sources(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    base = _base_config()
    base["sources"].update(
        {
            "twitter": {"enabled": True, "users": ["openai"]},
            "openbb": {"enabled": True, "watchlists": []},
            "ossinsight": {"enabled": True},
        }
    )

    data = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        base_config=base,
    )

    assert data["sources"]["twitter"]["enabled"] is False
    assert data["sources"]["openbb"]["enabled"] is False
    assert data["sources"]["ossinsight"]["enabled"] is False


def test_user_config_builder_disables_unsubscribed_global_hackernews(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    base = _base_config()
    base["sources"]["hackernews"] = {
        "enabled": True,
        "fetch_top_stories": 20,
        "min_score": 100,
    }

    data = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        base_config=base,
    )

    assert data["sources"]["hackernews"] == {
        "enabled": False,
        "fetch_top_stories": 20,
        "min_score": 100,
    }
