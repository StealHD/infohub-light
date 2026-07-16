import asyncio
import json
from datetime import datetime, timezone

import pytest

from src.models import Config, ContentItem, SourceType
from src.orchestrator import HorizonOrchestrator
from src.services.feed_run import FeedRunResult
from src.source_selection import SourceRef
from src.storage.manager import StorageManager


def _item(item_id: str, analysis_mode: str) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.INSTAGRAM,
        title=item_id,
        url="https://www.instagram.com/p/example/",
        published_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
        metadata={"analysis_mode": analysis_mode, "personal_tags": ["能黄通"]},
    )


def _ai_disabled_config() -> Config:
    return Config.model_validate(
        {
            "version": "1.0",
            "ai": {
                "enabled": False,
                "provider": "openai",
                "model": "gpt-4o-mini",
                "api_key_env": "MISSING_TEST_API_KEY",
            },
            "sources": {"hackernews": {"enabled": True}},
            "filtering": {
                "ai_score_threshold": 7.5,
                "featured_score_threshold": 7.5,
                "daily_push_score_threshold": 8.5,
                "time_window_hours": 24,
                "recent_item_limit": 20,
            },
        }
    )


def _news_item(item_id: str = "hackernews:item:1") -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.HACKERNEWS,
        title="No AI key required",
        url="https://news.ycombinator.com/item?id=1",
        content="Fetched content should still be published when AI scoring is disabled.",
        author="hn-user",
        published_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
        metadata={"tags": ["AI Agent"], "category": "AI Agent"},
    )


def test_partition_analysis_items_keeps_personal_only_out_of_ai_queue():
    full = _item("instagram:post:full", "full")
    personal = _item("instagram:post:personal", "personal_only")
    personal.ai_action_suggestion = "旧建议动作"

    analysis_items, passthrough_items = HorizonOrchestrator.partition_analysis_items(
        [full, personal]
    )

    assert analysis_items == [full]
    assert passthrough_items == [personal]
    assert personal.ai_score == 0.0
    assert personal.ai_reason is None
    assert personal.ai_action_suggestion is None
    assert personal.metadata["analysis_status"] == "personal_only"
    assert personal.metadata["show_in_personal_feed"] is True


def test_run_publishes_without_ai_when_global_scoring_disabled(tmp_path, monkeypatch):
    storage = StorageManager(data_dir=str(tmp_path))
    orchestrator = HorizonOrchestrator(_ai_disabled_config(), storage)

    async def fake_fetch_all_sources(since):
        return [_news_item()]

    async def fail_analyze(items):
        raise AssertionError("AI analysis should not run when ai.enabled=false")

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fake_fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", fail_analyze)

    asyncio.run(
        orchestrator.run(
            send_notifications=False,
            write_summaries=False,
            enrich=True,
        )
    )

    today = json.loads((tmp_path / "site" / "today-data.json").read_text())
    assert today["items"][0]["title"] == "No AI key required"
    assert today["items"][0]["score"] == 0.0
    assert today["items"][0]["summary_zh"].startswith("Fetched content")
    assert today["items"][0]["presentation"]["analysis"]["status"] == "disabled"
    assert today["items"][0]["action_suggestion"] == ""
    assert today["items"][0]["presentation"]["analysis"]["action_suggestion"] == ""


def test_legacy_run_delegates_structured_execution_to_legacy_publisher(tmp_path, monkeypatch):
    storage = StorageManager(data_dir=str(tmp_path))
    orchestrator = HorizonOrchestrator(_ai_disabled_config(), storage)
    result = FeedRunResult(
        run_id="run_legacy",
        status="succeeded",
        started_at="2026-07-10T00:00:00+00:00",
        finished_at="2026-07-10T00:00:01+00:00",
        items=(_news_item("hackernews:item:legacy"),),
    )
    calls = []

    async def fake_execute(*args, **kwargs):
        calls.append(("execute", args, kwargs))
        return result

    async def forbidden_fetch(_since):
        raise AssertionError("legacy run bypassed execute")

    class FakeLegacyPublisher:
        def __init__(self, owner):
            assert owner is orchestrator

        def prepare(self):
            calls.append(("prepare",))

        async def publish(self, published_result, **kwargs):
            calls.append(("publish", published_result, kwargs))

    monkeypatch.setattr(orchestrator, "execute", fake_execute)
    monkeypatch.setattr(orchestrator, "fetch_all_sources", forbidden_fetch)
    monkeypatch.setattr("src.orchestrator.LegacyPublisher", FakeLegacyPublisher, raising=False)

    asyncio.run(
        orchestrator.run(
            force_hours=6,
            send_notifications=False,
            write_summaries=False,
            incremental=True,
            enrich=False,
        )
    )

    assert [call[0] for call in calls] == ["prepare", "execute", "publish"]
    assert calls[1][2]["legacy_sources"] is True
    assert calls[2][1] is result


def test_legacy_run_routes_publishing_failures_to_legacy_notifier(tmp_path, monkeypatch):
    orchestrator = HorizonOrchestrator(
        _ai_disabled_config(),
        StorageManager(data_dir=str(tmp_path)),
    )
    result = FeedRunResult(
        run_id="run_publish_failure",
        status="succeeded",
        started_at="2026-07-10T00:00:00+00:00",
        finished_at="2026-07-10T00:00:01+00:00",
        items=(_news_item("hackernews:item:publish-failure"),),
    )
    failures = []

    async def fake_execute(*_args, **_kwargs):
        return result

    class FailingPublisher:
        def __init__(self, _owner):
            pass

        def prepare(self):
            pass

        async def publish(self, _result, **_kwargs):
            raise RuntimeError("publish failed")

        async def notify_failure(self, error, *, send_notifications):
            failures.append((str(error), send_notifications))

    monkeypatch.setattr(orchestrator, "execute", fake_execute)
    monkeypatch.setattr("src.orchestrator.LegacyPublisher", FailingPublisher)

    with pytest.raises(RuntimeError, match="publish failed"):
        asyncio.run(orchestrator.run(send_notifications=True))

    assert failures == [("publish failed", True)]


def test_no_ai_run_skips_all_secondary_cost_pipelines(tmp_path, monkeypatch):
    storage = StorageManager(data_dir=str(tmp_path))
    orchestrator = HorizonOrchestrator(_ai_disabled_config(), storage)
    item = _news_item("hackernews:item:secondary-guard")

    async def fake_fetch_all_sources(since):
        return [item]

    async def fail_analyze(items):
        raise AssertionError("_analyze_content should not run when ai.enabled=false")

    async def fail_enrich(items):
        raise AssertionError("_enrich_important_items should not run when ai.enabled=false")

    async def fail_graph(items):
        raise AssertionError("_run_article_graph_pipeline should not run when ai.enabled=false")

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fake_fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", fail_analyze)
    monkeypatch.setattr(orchestrator, "_enrich_important_items", fail_enrich)
    monkeypatch.setattr(orchestrator, "_run_article_graph_pipeline", fail_graph)

    asyncio.run(
        orchestrator.run(
            send_notifications=True,
            write_summaries=True,
            enrich=True,
        )
    )

    payload = json.loads((tmp_path / "site" / "radar-data.json").read_text())
    assert payload["ai_enabled"] is False
    assert payload["today_items"][0]["scoring_disabled"] is True


def test_single_source_update_publishes_without_ai_when_global_scoring_disabled(
    tmp_path,
    monkeypatch,
):
    storage = StorageManager(data_dir=str(tmp_path))
    orchestrator = HorizonOrchestrator(_ai_disabled_config(), storage)

    async def fake_fetch_all_sources(since):
        return [_news_item()]

    async def fail_analyze(items):
        raise AssertionError("AI analysis should not run when ai.enabled=false")

    monkeypatch.setattr(orchestrator, "fetch_all_sources", fake_fetch_all_sources)
    monkeypatch.setattr(orchestrator, "_analyze_content", fail_analyze)

    result = asyncio.run(
        orchestrator.run_single_source_update(
            SourceRef(source_type="hackernews"),
            force_hours=24,
        )
    )

    assert result["analyzed"] == 0
    assert result["passthrough"] == 1
    assert result["web_ui_updated"] is True
    today = json.loads((tmp_path / "site" / "today-data.json").read_text())
    assert [item["title"] for item in today["items"]] == ["No AI key required"]
