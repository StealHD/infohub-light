import json
from datetime import datetime, timezone

from src.models import ContentItem, SourceType
from src.services.feed_run import FeedRunResult, SourceOutcome
from src.services.job_queue import JobQueue
from src.services.catalog_source_runner import (
    build_catalog_source_config_data,
    run_catalog_source_fetch,
)
from src.services.user_feed_store import UserFeedStore
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
        "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
        "filtering": {"time_window_hours": 24},
    }


def _write_config(data_dir):
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "config.json").write_text(json.dumps(_base_config()), encoding="utf-8")


def _store_with_rss_source(tmp_path, monkeypatch):
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
        display_name="Runner RSS",
        default_channel="AI",
        default_topics=["Codex"],
        config={"name": "Runner RSS", "url": "https://github.blog/feed/"},
        source_key="rss:https://github.blog/feed/",
    )
    subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source_id,
        override_channel="产品机会",
        override_topics=["价格监控"],
        personal_tags=["高定"],
        analysis_mode="personal_only",
    )
    return store, workspace, owner, source_id, subscription


def test_build_catalog_source_config_data_uses_subscription_overrides(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _store_with_rss_source(tmp_path, monkeypatch)

    data = build_catalog_source_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        base_config=_base_config(),
    )

    rss = data["sources"]["rss"]
    assert len(rss) == 1
    assert rss[0]["name"] == "Runner RSS"
    assert rss[0]["url"] == "https://github.blog/feed/"
    assert rss[0]["channel"] == "产品机会"
    assert rss[0]["category"] == "产品机会"
    assert rss[0]["topics"] == ["价格监控"]
    assert rss[0]["tags"] == ["价格监控"]
    assert rss[0]["personal_tags"] == ["高定"]
    assert rss[0]["analysis_mode"] == "personal_only"
    assert data["sources"]["github"] == []
    assert data["sources"]["hackernews"]["enabled"] is False


def test_catalog_rss_config_disables_global_hackernews(tmp_path, monkeypatch):
    store, workspace, owner, source_id, subscription = _store_with_rss_source(tmp_path, monkeypatch)
    base = _base_config()
    base["sources"]["hackernews"] = {
        "enabled": True,
        "fetch_top_stories": 20,
        "min_score": 100,
    }

    data = build_catalog_source_config_data(
        store=store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        base_config=base,
    )

    assert data["sources"]["hackernews"] == {
        "enabled": False,
        "fetch_top_stories": 20,
        "min_score": 100,
    }


def test_run_catalog_source_fetch_saves_snapshot_and_returns_source_metadata(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_SHARED_ACQUISITION_ENABLED", "true")
    _write_config(tmp_path)
    store, workspace, owner, source_id, subscription = _store_with_rss_source(tmp_path, monkeypatch)
    calls = []
    acquisition_coordinators = []

    class FakeOrchestrator:
        def __init__(self, config, _storage):
            self.config = config
            calls.append(config.sources.rss[0].channel)

        def set_service_acquisition_coordinator(self, coordinator):
            acquisition_coordinators.append(coordinator)

        async def execute(self, **kwargs):
            assert kwargs["enrich"] is False
            item = ContentItem(
                id="rss:item:runner",
                source_type=SourceType.RSS,
                title="Runner",
                url="https://example.com/runner",
                published_at=datetime.now(timezone.utc),
                metadata={
                    "feed_name": "Runner RSS",
                    "source_id": source_id,
                    "subscription_id": subscription["id"],
                    "channel": "产品机会",
                    "topics": ["价格监控"],
                },
                ai_score=8.1,
            )
            return FeedRunResult(
                run_id="run_catalog",
                status="succeeded",
                started_at=datetime.now(timezone.utc).isoformat(),
                finished_at=datetime.now(timezone.utc).isoformat(),
                items=(item,),
                source_outcomes=(
                    SourceOutcome(
                        source_id=source_id,
                        subscription_id=subscription["id"],
                        source_key="rss:https://github.blog/feed/",
                        analysis_mode="personal_only",
                        status="succeeded",
                        fetched_count=1,
                    ),
                ),
            )

    monkeypatch.setattr("src.services.catalog_source_runner.HorizonOrchestrator", FakeOrchestrator)

    job = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=source_id,
        subscription_id=subscription["id"],
        job_type="source_fetch",
        payload={"hours": 6},
    )
    result = run_catalog_source_fetch(
        job,
        data_dir=str(tmp_path),
        store=store,
    )
    latest = UserFeedStore(store).latest_snapshot(workspace_id=workspace["id"], user_id=owner["id"])

    assert calls == ["产品机会"]
    assert len(acquisition_coordinators) == 1
    assert acquisition_coordinators[0].user_id == owner["id"]
    assert result["ok"] is True
    assert result["job_type"] == "source_fetch"
    assert result["source_id"] == source_id
    assert result["source_type"] == "rss"
    assert result["source_key"] == "rss:https://github.blog/feed/"
    assert result["snapshot_id"] == latest["id"]
    assert result["fetched_count"] == 1
    assert result["item_count"] == 1
    assert result["acquisition_usage"] == {
        "cache_hits": 0,
        "cache_misses": 0,
        "upstream_attempts": 0,
        "waits": 0,
    }
