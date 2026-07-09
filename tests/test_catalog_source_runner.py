import json

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


def test_run_catalog_source_fetch_saves_snapshot_and_returns_source_metadata(tmp_path, monkeypatch):
    _write_config(tmp_path)
    store, workspace, owner, source_id, subscription = _store_with_rss_source(tmp_path, monkeypatch)
    calls = []

    class FakeOrchestrator:
        def __init__(self, config, storage):
            self.config = config
            self.storage = storage
            calls.append(config.sources.rss[0].channel)

        async def run(self, **kwargs):
            assert kwargs["send_notifications"] is False
            assert kwargs["write_summaries"] is False
            assert kwargs["incremental"] is True
            assert kwargs["enrich"] is False
            site_dir = self.storage.data_dir / "site"
            site_dir.mkdir(parents=True, exist_ok=True)
            (site_dir / "radar-data.json").write_text(
                json.dumps(
                    {
                        "generated_at": "2026-07-09T11:30:00+08:00",
                        "items": [
                            {
                                "id": "rss:item:runner",
                                "source": "Runner RSS",
                                "channel": "产品机会",
                                "topics": ["价格监控"],
                                "score": 8.1,
                            }
                        ],
                    }
                ),
                encoding="utf-8",
            )

    monkeypatch.setattr("src.services.catalog_source_runner.HorizonOrchestrator", FakeOrchestrator)

    result = run_catalog_source_fetch(
        {
            "id": "job_catalog_fetch",
            "workspace_id": workspace["id"],
            "user_id": owner["id"],
            "source_id": source_id,
            "subscription_id": subscription["id"],
            "payload_json": {"hours": 6},
        },
        data_dir=str(tmp_path),
        store=store,
    )
    latest = UserFeedStore(store).latest_snapshot(workspace_id=workspace["id"], user_id=owner["id"])

    assert calls == ["产品机会"]
    assert result["ok"] is True
    assert result["job_type"] == "source_fetch"
    assert result["source_id"] == source_id
    assert result["source_type"] == "rss"
    assert result["source_key"] == "rss:https://github.blog/feed/"
    assert result["snapshot_id"] == latest["id"]
    assert result["item_count"] == 1
