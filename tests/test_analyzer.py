import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import src.ai.analyzer as analyzer_module
from src.ai.analysis_cache import AnalysisCache
from src.ai.analyzer import ContentAnalyzer
from src.models import ContentItem, SourceType


def _make_item(item_id: str) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.RSS,
        title=f"Item {item_id}",
        url="https://example.com/item",
        published_at=datetime(2026, 4, 26, tzinfo=timezone.utc),
    )


def test_analyze_batch_does_not_sleep_by_default(monkeypatch):
    analyzer = ContentAnalyzer(SimpleNamespace())
    items = [_make_item("rss:test:1"), _make_item("rss:test:2")]
    sleep_calls = []

    async def fake_analyze_item(item):
        item.ai_score = 8.0

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(analyzer, "_analyze_item", fake_analyze_item)
    monkeypatch.setattr(analyzer_module.asyncio, "sleep", fake_sleep)

    result = asyncio.run(analyzer.analyze_batch(items))

    assert len(result) == 2
    assert sleep_calls == []


def test_analyze_batch_sleeps_between_items_when_throttle_configured(monkeypatch):
    client = SimpleNamespace(config=SimpleNamespace(throttle_sec=1.5))
    analyzer = ContentAnalyzer(client)
    items = [_make_item("rss:test:1"), _make_item("rss:test:2"), _make_item("rss:test:3")]
    sleep_calls = []

    async def fake_analyze_item(item):
        item.ai_score = 8.0

    async def fake_sleep(seconds):
        sleep_calls.append(seconds)

    monkeypatch.setattr(analyzer, "_analyze_item", fake_analyze_item)
    monkeypatch.setattr(analyzer_module.asyncio, "sleep", fake_sleep)

    asyncio.run(analyzer.analyze_batch(items))

    assert sleep_calls == [1.5, 1.5]


def test_analyze_batch_concurrent_processing(monkeypatch):
    """Verify that higher concurrency allows overlapping item processing."""
    client = SimpleNamespace(config=SimpleNamespace(analysis_concurrency=3))
    analyzer = ContentAnalyzer(client)
    items = [_make_item(f"rss:test:{i}") for i in range(5)]
    active_count = 0
    max_active = 0

    async def fake_analyze_item(item):
        nonlocal active_count, max_active
        active_count += 1
        max_active = max(max_active, active_count)
        await asyncio.sleep(0.05)  # Small delay to allow overlap
        active_count -= 1

    monkeypatch.setattr(analyzer, "_analyze_item", fake_analyze_item)

    asyncio.run(analyzer.analyze_batch(items))

    assert max_active == 3
    assert all(item.ai_score is None for item in items)  # None because fake_analyze_item doesn't set it


def test_analyze_batch_concurrent_preserves_order(monkeypatch):
    """Verify that analyze_batch preserves input order in results."""
    client = SimpleNamespace(config=SimpleNamespace(analysis_concurrency=3))
    analyzer = ContentAnalyzer(client)
    items = [_make_item(f"rss:test:{i}") for i in range(5)]

    async def fake_analyze_item(item):
        item.ai_score = float(item.id.split(":")[-1]) * 10

    monkeypatch.setattr(analyzer, "_analyze_item", fake_analyze_item)

    result = asyncio.run(analyzer.analyze_batch(items))

    assert [item.id for item in result] == [item.id for item in items]


def test_analyze_item_uses_configured_prompt_limits_and_ignores_personal_tags():
    calls = []

    class FakeClient:
        config = SimpleNamespace(
            analysis_content_chars=12,
            analysis_comments_chars=8,
            analysis_concurrency=1,
            throttle_sec=0,
        )

        async def complete(self, system, user):
            calls.append(user)
            return (
                '{"score": 8, "reason": "ok", "channel": "AI", '
                '"topics": ["AI 编程", "Codex"], '
                '"signal_strength": "strong", "signal_type": "release", '
                '"entities": ["OpenAI", "Codex"], '
                '"is_featured": true, "summary_zh": "摘要", '
                '"action_suggestion": "阅读"}'
            )

    item = _make_item("rss:test:limited")
    item.content = "abcdefghijklmnopqrstuvwxyz--- Top Comments ---1234567890"
    item.metadata["tags"] = ["AI Agent"]
    item.metadata["personal_tags"] = ["能黄通"]

    asyncio.run(ContentAnalyzer(FakeClient())._analyze_item(item))

    assert "Content: abcdefghijkl" in calls[0]
    assert "Community Comments:\n12345678" in calls[0]
    assert "AI Agent" in calls[0]
    assert "能黄通" not in calls[0]
    assert item.ai_channel == "AI"
    assert item.ai_category == "AI"
    assert item.ai_topics == ["AI 编程", "Codex", "AI Agent"]
    assert item.ai_tags == ["AI 编程", "Codex", "AI Agent"]
    assert item.ai_signal_strength == "strong"
    assert item.ai_signal_type == "release"
    assert item.ai_entities == ["OpenAI", "Codex"]


def test_analyze_batch_reuses_analysis_cache(tmp_path):
    calls = 0

    class FakeClient:
        config = SimpleNamespace(
            analysis_concurrency=1,
            throttle_sec=0,
            model="fake-model",
        )

        async def complete(self, system, user):
            nonlocal calls
            calls += 1
            return (
                '{"score": 8.2, "reason": "cached", "channel": "AI", '
                '"topics": ["Agent", "Codex"], "signal_strength": "strong", '
                '"signal_type": "release", "entities": ["OpenAI"], '
                '"is_featured": true, "summary_zh": "缓存摘要", '
                '"action_suggestion": "收藏"}'
            )

    cache = AnalysisCache(tmp_path / "analysis-cache.jsonl")
    first = _make_item("rss:test:cache")
    first.content = "same body"
    second = _make_item("rss:test:cache")
    second.content = "same body"

    asyncio.run(ContentAnalyzer(FakeClient(), cache=cache).analyze_batch([first]))
    asyncio.run(ContentAnalyzer(FakeClient(), cache=cache).analyze_batch([second]))

    assert calls == 1
    assert second.ai_score == 8.2
    assert second.ai_summary_zh == "缓存摘要"
    assert second.ai_channel == "AI"
    assert second.ai_topics == ["Agent", "Codex"]
    assert second.ai_signal_strength == "strong"
    assert second.ai_signal_type == "release"
    assert second.ai_entities == ["OpenAI"]
