from datetime import datetime, timezone

from src.models import Config
from src.services.feed_run import RunIssue, SourceOutcome
from src.services.job_queue import JobQueue
from src.services.source_health import SourceHealthService
from src.services.source_schedule import SourceScheduleService
from src.services.source_type_registry import validate_source_config
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
    assert rss.service_fetch_window_hours == 168
    assert data["sources"]["rss"][0]["analysis_mode"] == "personal_only"
    assert data["sources"]["rss"][0]["source_priority"] == 7
    assert data["sources"]["rss"][0]["source_display_name"] == "AI Feed"
    assert data["sources"]["rss"][0]["catalog_source_type"] == "rss"
    assert data["sources"]["rss"][0]["keep_latest_item"] is True
    assert data["sources"]["rss"][0]["service_fetch_window_hours"] == 168
    assert data["sources"]["rss"][0]["token_env"] == "RSS_TOKEN"
    assert rss.enforce_public_network is False
    assert "service_fetch_window_hours" not in config.model_dump(mode="json")["sources"]["rss"][0]

    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=member["id"],
        source_id=source_id,
        subscription_id=subscription_id["id"],
        job_type="source_fetch",
        payload={},
    )
    SourceHealthService(store).apply_outcomes(
        workspace_id=workspace["id"],
        user_id=member["id"],
        job_id=job["id"],
        attempted_at=datetime.now(timezone.utc).isoformat(),
        outcomes=(
            SourceOutcome(
                source_id=source_id,
                subscription_id=subscription_id["id"],
                source_key="rss:https://example.com/feed.xml",
                analysis_mode="personal_only",
                status="failed",
                fetched_count=0,
                issue=RunIssue(
                    stage="fetch",
                    code="TimeoutError",
                    message="temporary timeout",
                    retryable=True,
                ),
            ),
        ),
    )
    after_failure = Config.model_validate(build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=member["id"],
        base_config=_base_config(),
    ))
    assert after_failure.sources.rss[0].service_fetch_window_hours == 168

    successful_job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=member["id"],
        source_id=source_id,
        subscription_id=subscription_id["id"],
        job_type="source_fetch",
        payload={},
    )
    SourceHealthService(store).apply_outcomes(
        workspace_id=workspace["id"],
        user_id=member["id"],
        job_id=successful_job["id"],
        attempted_at=datetime.now(timezone.utc).isoformat(),
        outcomes=(
            SourceOutcome(
                source_id=source_id,
                subscription_id=subscription_id["id"],
                source_key="rss:https://example.com/feed.xml",
                analysis_mode="personal_only",
                status="succeeded",
                fetched_count=0,
            ),
        ),
    )
    refreshed = Config.model_validate(build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=member["id"],
        base_config=_base_config(),
    ))
    assert refreshed.sources.rss[0].service_fetch_window_hours is None


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


def test_existing_owner_youtube_rss_always_uses_public_network_policy(
    tmp_path,
    monkeypatch,
):
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
        source_type="rss",
        display_name="Legacy YouTube RSS",
        config=validate_source_config(
            "rss",
            {
                "url": (
                    "https://www.youtube.com/feeds/videos.xml?"
                    "channel_id=UCabcdefghijklmnopqrstuv"
                ),
                "keep_latest_item": True,
            },
        ),
        enforce_public_network=False,
    )
    store.create_subscription(user_id=owner["id"], source_id=source_id)

    data = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        base_config=_base_config(),
    )

    assert data["sources"]["rss"][0]["enforce_public_network"] is True
    assert data["sources"]["rss"][0]["keep_latest_item"] is True


def test_user_config_builder_applies_30_day_window_to_managed_rsshub(
    tmp_path,
    monkeypatch,
):
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
        source_type="rss",
        display_name="Bilibili RSSHub",
        config=validate_source_config("rss", {
            "provider": "rsshub",
            "site": "bilibili",
            "route_key": "user_video",
            "params": {"uid": "39627524"},
        }),
    )
    store.create_subscription(user_id=owner["id"], source_id=source_id)
    base = _base_config()
    base["filtering"]["rss_initial_fetch_window_hours"] = 720

    data = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        base_config=base,
    )

    assert data["sources"]["rss"][0]["provider"] == "rsshub"
    assert data["sources"]["rss"][0]["service_fetch_window_hours"] == 720


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


def test_user_config_builder_ignores_legacy_apify_source_secret_in_pool_mode(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")

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
        config={
            "platform": "x",
            "kind": "profile",
            "target": "OpenAI",
            "fetch_limit": 5,
        },
        secret_env="APIFY_TOKEN_2",
    )
    store.create_subscription(user_id=owner["id"], source_id=source_id)

    data = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        base_config=_base_config(),
    )

    subscription = data["sources"]["apify_social"]["subscriptions"][0]
    assert "token_env" not in subscription
    assert data["sources"]["apify_social"]["token_envs"] == ["APIFY_TOKEN"]


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


def test_global_schedule_scope_excludes_only_enabled_source_schedules(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_ids = []
    subscriptions = []
    for suffix in ("global", "custom"):
        source_id = store.create_source(
            workspace_id=workspace["id"],
            scope="private",
            owner_user_id=owner["id"],
            source_type="rss",
            display_name=f"{suffix.title()} Feed",
            config={
                "name": f"{suffix.title()} Feed",
                "url": f"https://example.com/{suffix}.xml",
            },
            source_key=f"rss:https://example.com/{suffix}.xml",
        )
        source_ids.append(source_id)
        subscriptions.append(
            store.create_subscription(user_id=owner["id"], source_id=source_id)
        )
    SourceScheduleService(store).update_subscription_schedule(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        subscription_id=subscriptions[1]["id"],
        enabled=True,
        interval_minutes=60,
        now=datetime(2026, 7, 28, tzinfo=timezone.utc),
    )

    all_sources = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        base_config=_base_config(),
    )
    global_sources = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        base_config=_base_config(),
        schedule_scope="global",
    )

    assert {
        source["source_id"] for source in all_sources["sources"]["rss"]
    } == set(source_ids)
    assert [
        source["source_id"] for source in global_sources["sources"]["rss"]
    ] == [source_ids[0]]


def test_user_config_builder_limits_manual_member_scope_to_owned_private_sources(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member-scope",
        password="member-password",
        role="member",
    )
    source_ids = {}
    for scope in ("private", "public", "workspace"):
        source_id = store.create_source(
            workspace_id=workspace["id"],
            scope=scope,
            owner_user_id=member["id"] if scope == "private" else None,
            source_type="rss",
            display_name=f"{scope.title()} Feed",
            config={"url": f"https://example.com/{scope}.xml"},
        )
        source_ids[scope] = source_id
        store.create_subscription(user_id=member["id"], source_id=source_id)

    private = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=member["id"],
        base_config=_base_config(),
        source_scope="private",
    )
    all_sources = build_user_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=member["id"],
        base_config=_base_config(),
        source_scope="all",
    )

    assert [source["source_id"] for source in private["sources"]["rss"]] == [
        source_ids["private"]
    ]
    assert {source["source_id"] for source in all_sources["sources"]["rss"]} == set(
        source_ids.values()
    )
