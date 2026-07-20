import asyncio
import json
from datetime import datetime, timezone
from types import MethodType, SimpleNamespace
from tenacity import wait_none

import src.ai.analyzer as analyzer_module
from src.ai.analysis_cache import AnalysisCache, apply_analysis_result
from src.ai.analyzer import ContentAnalyzer
from src.ai.prompts import content_analysis_system
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


def test_legacy_cache_without_content_format_clears_stale_ai_format() -> None:
    item = _make_item("rss:test:legacy-format")
    item.metadata["ai_content_format"] = "video"

    apply_analysis_result(item, {"summary_zh": "旧缓存摘要"})

    assert "ai_content_format" not in item.metadata


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

        async def complete(self, system, user, **kwargs):
            calls.append((user, kwargs))
            return (
                '{"score": 8, "reason": "ok", "channel": "AI", '
                '"topics": ["AI 编程", "Codex"], '
                '"signal_strength": "strong", "signal_type": "release", '
                '"entities": ["OpenAI", "Codex"], '
                '"is_featured": true, "content_format": "video", "summary_zh": "摘要", '
                '"action_suggestion": "阅读"}'
            )

    item = _make_item("rss:test:limited")
    item.content = "abcdefghijklmnopqrstuvwxyz--- Top Comments ---1234567890"
    item.metadata["tags"] = ["AI Agent"]
    item.metadata["personal_tags"] = ["能黄通"]

    asyncio.run(ContentAnalyzer(FakeClient())._analyze_item(item))

    assert "Content: abcdefghijkl" in calls[0][0]
    assert "Community Comments:\n12345678" in calls[0][0]
    assert "AI Agent" in calls[0][0]
    assert "能黄通" not in calls[0][0]
    assert item.ai_channel == "AI"
    assert item.ai_category == "AI"
    assert item.ai_topics == ["AI 编程", "Codex", "AI Agent"]
    assert item.ai_tags == ["AI 编程", "Codex", "AI Agent"]
    assert item.metadata["inferred_topics"] == ["AI 编程", "Codex"]
    assert item.metadata["configured_topics"] == ["AI Agent"]
    assert item.ai_signal_strength == "strong"
    assert item.ai_signal_type == "release"
    assert item.ai_entities == ["OpenAI", "Codex"]
    assert item.metadata["ai_content_format"] == "video"


def test_analyze_batch_reuses_analysis_cache(tmp_path):
    calls = 0

    class FakeClient:
        config = SimpleNamespace(
            analysis_concurrency=1,
            throttle_sec=0,
            model="fake-model",
        )

        async def complete(self, system, user, **kwargs):
            nonlocal calls
            calls += 1
            return (
                '{"score": 8.2, "reason": "cached", "channel": "AI", '
                '"topics": ["Agent", "Codex"], "signal_strength": "strong", '
                '"signal_type": "release", "entities": ["OpenAI"], '
                '"is_featured": true, "content_format": "article", "summary_zh": "缓存摘要", '
                '"action_suggestion": "收藏"}'
            )

    cache = AnalysisCache(tmp_path / "analysis-cache.jsonl")
    first = _make_item("rss:test:cache")
    first.content = "same body"
    second = _make_item("rss:test:cache")
    second.content = "same body"

    first_analyzer = ContentAnalyzer(FakeClient(), cache=cache)
    second_analyzer = ContentAnalyzer(FakeClient(), cache=cache)
    asyncio.run(first_analyzer.analyze_batch([first]))
    asyncio.run(second_analyzer.analyze_batch([second]))

    assert calls == 1
    assert second.ai_score == 8.2
    assert second.ai_summary_zh == "缓存摘要"
    assert second.ai_channel == "AI"
    assert second.ai_topics == ["Agent", "Codex"]
    assert second.ai_signal_strength == "strong"
    assert second.ai_signal_type == "release"
    assert second.ai_entities == ["OpenAI"]
    assert second.metadata["ai_content_format"] == "article"
    assert first_analyzer.usage == {
        "item_count": 1,
        "cache_hits": 0,
        "ai_calls": 1,
        "provider_attempts": 1,
        "fallbacks": 0,
        "skipped": 0,
    }
    assert second_analyzer.usage == {
        "item_count": 1,
        "cache_hits": 1,
        "ai_calls": 0,
        "provider_attempts": 0,
        "fallbacks": 0,
        "skipped": 0,
    }


def test_analyze_batch_admits_ai_usage_only_after_cache_miss():
    admitted = []

    class FakeCache:
        def apply(self, _item, **_kwargs):
            return False

        def before_ai_attempt(self, *, provider):
            admitted.append(provider)

        def store(self, _item, **_kwargs):
            return None

    class FakeClient:
        config = SimpleNamespace(
            analysis_concurrency=1,
            throttle_sec=0,
            model="gemini-test",
            provider="gemini",
        )

        async def complete(self, **_kwargs):
            return (
                '{"score": 8, "channel": "AI", "topics": [], '
                '"signal_strength": "strong", "signal_type": "release", '
                '"entities": [], "summary_zh": "摘要"}'
            )

    analyzer = ContentAnalyzer(FakeClient(), cache=FakeCache())

    asyncio.run(analyzer.analyze_batch([_make_item("rss:test:quota")]))

    assert admitted == ["gemini"]


def test_analyze_batch_uses_source_aware_admission_before_item_and_network():
    admitted = []

    class FakeCache:
        def apply(self, _item, **_kwargs):
            return False

        def before_ai_item_for_source(self, *, provider, source_id):
            admitted.append(("item", provider, source_id))

        def before_ai_network_attempt(self, *, provider, source_id):
            admitted.append(("attempt", provider, source_id))

        def store(self, _item, **_kwargs):
            return None

    class FakeClient:
        config = SimpleNamespace(
            analysis_concurrency=1,
            throttle_sec=0,
            model="gemini-test",
            provider="gemini",
        )

        async def complete(self, **_kwargs):
            return (
                '{"score": 8, "channel": "AI", "topics": [], '
                '"signal_strength": "strong", "signal_type": "release", '
                '"entities": [], "summary_zh": "摘要"}'
            )

    item = _make_item("rss:test:source-aware")
    item.metadata["source_id"] = "src_source_aware"
    analyzer = ContentAnalyzer(FakeClient(), cache=FakeCache())

    asyncio.run(analyzer.analyze_batch([item]))

    assert admitted == [
        ("item", "gemini", "src_source_aware"),
        ("attempt", "gemini", "src_source_aware"),
    ]


def test_ai_retry_admits_and_reports_every_provider_attempt(monkeypatch):
    admitted = []
    calls = 0

    class FakeCache:
        def apply(self, _item, **_kwargs):
            return False

        def before_ai_attempt(self, *, provider):
            admitted.append(provider)

        def store(self, _item, **_kwargs):
            return None

    class FakeClient:
        config = SimpleNamespace(
            analysis_concurrency=1,
            throttle_sec=0,
            model="gemini-retry",
            provider="gemini",
        )

        async def complete(self, **_kwargs):
            nonlocal calls
            calls += 1
            if calls < 3:
                raise TimeoutError("temporary provider timeout")
            return (
                '{"score": 8, "channel": "AI", "topics": [], '
                '"signal_strength": "strong", "signal_type": "release", '
                '"entities": [], "summary_zh": "摘要"}'
            )

    analyzer = ContentAnalyzer(FakeClient(), cache=FakeCache())
    monkeypatch.setattr(
        analyzer,
        "_analyze_item",
        MethodType(
            ContentAnalyzer._analyze_item.retry_with(wait=wait_none()),
            analyzer,
        ),
    )

    asyncio.run(analyzer.analyze_batch([_make_item("rss:test:provider-retry")]))

    assert admitted == ["gemini", "gemini", "gemini"]
    assert calls == 3
    assert analyzer.usage == {
        "item_count": 1,
        "cache_hits": 0,
        "ai_calls": 1,
        "provider_attempts": 3,
        "fallbacks": 0,
        "skipped": 0,
    }


def test_analysis_cache_fingerprint_tracks_rendered_prompt_and_runtime_limits(
    tmp_path, monkeypatch
):
    calls = 0

    class FakeClient:
        def __init__(self, *, summary_max_chars):
            self.config = SimpleNamespace(
                analysis_concurrency=1,
                throttle_sec=0,
                model="prompt-fingerprint-model",
                provider="gemini",
                summary_max_chars=summary_max_chars,
                analysis_content_chars=1000,
                analysis_comments_chars=1500,
                analysis_max_output_tokens=800,
            )

        async def complete(self, **_kwargs):
            nonlocal calls
            calls += 1
            return (
                '{"score": 8, "channel": "AI", "topics": [], '
                '"signal_strength": "strong", "signal_type": "release", '
                '"entities": [], "summary_zh": "摘要"}'
            )

    cache = AnalysisCache(tmp_path / "rendered-prompt-cache.jsonl")

    asyncio.run(
        ContentAnalyzer(FakeClient(summary_max_chars=200), cache=cache).analyze_batch(
            [_make_item("rss:test:rendered-prompt")]
        )
    )
    asyncio.run(
        ContentAnalyzer(FakeClient(summary_max_chars=220), cache=cache).analyze_batch(
            [_make_item("rss:test:rendered-prompt")]
        )
    )
    marker = "PROMPT-FINGERPRINT-MARKER"
    monkeypatch.setattr(
        analyzer_module,
        "CONTENT_ANALYSIS_USER",
        analyzer_module.CONTENT_ANALYSIS_USER + f"\n{marker}",
    )
    asyncio.run(
        ContentAnalyzer(FakeClient(summary_max_chars=220), cache=cache).analyze_batch(
            [_make_item("rss:test:rendered-prompt")]
        )
    )

    assert calls == 3
    persisted = (tmp_path / "rendered-prompt-cache.jsonl").read_text(
        encoding="utf-8"
    )
    assert marker not in persisted


def test_analyze_batch_does_not_cache_truncated_or_invalid_json(tmp_path):
    calls = 0

    class FakeClient:
        config = SimpleNamespace(
            analysis_concurrency=1,
            throttle_sec=0,
            model="fake-model",
        )

        async def complete(self, system, user, **kwargs):
            nonlocal calls
            calls += 1
            if calls == 1:
                return '{"score": 8, "summary_zh": "被截断的响应"'
            return (
                '{"score": 8, "reason": "ok", "channel": "AI", '
                '"topics": [], "signal_strength": "strong", '
                '"signal_type": "release", "entities": [], '
                '"is_featured": true, "summary_zh": "第二次成功", '
                '"action_suggestion": "阅读"}'
            )

    cache = AnalysisCache(tmp_path / "analysis-cache.jsonl")
    first = _make_item("rss:test:invalid-cache")
    second = _make_item("rss:test:invalid-cache")

    asyncio.run(ContentAnalyzer(FakeClient(), cache=cache).analyze_batch([first]))
    asyncio.run(ContentAnalyzer(FakeClient(), cache=cache).analyze_batch([second]))

    assert calls == 2
    assert second.ai_summary_zh == "第二次成功"


def test_analyze_item_uses_configured_summary_and_output_token_limits():
    calls = []

    class FakeClient:
        config = SimpleNamespace(
            analysis_content_chars=1000,
            analysis_comments_chars=1500,
            summary_max_chars=200,
            analysis_max_output_tokens=800,
        )

        async def complete(self, system, user, **kwargs):
            calls.append({"system": system, "user": user, **kwargs})
            return (
                '{"score": 8, "reason": "ok", "channel": "AI", '
                '"topics": [], "signal_strength": "strong", "signal_type": "release", '
                '"entities": [], "is_featured": true, "summary_zh": "短摘要", '
                '"action_suggestion": "阅读"}'
            )

    asyncio.run(ContentAnalyzer(FakeClient())._analyze_item(_make_item("rss:test:limits")))

    assert calls[0]["max_tokens"] == 800
    assert "不超过 200 个中文字符" in calls[0]["user"]


def test_analyze_batch_hard_limits_summary_and_omits_action_before_cache_write(tmp_path):
    long_summary = "很长的模型概括" * 30
    long_action = "建议继续阅读和比较" * 20

    class FakeClient:
        config = SimpleNamespace(
            analysis_concurrency=1,
            throttle_sec=0,
            model="fake-model",
            summary_max_chars=100,
        )

        async def complete(self, system, user, **kwargs):
            return json.dumps({
                "score": 8,
                "channel": "AI",
                "topics": [],
                "signal_strength": "strong",
                "signal_type": "release",
                "entities": [],
                "is_featured": True,
                "summary_zh": long_summary,
                "action_suggestion": long_action,
            }, ensure_ascii=False)

    path = tmp_path / "analysis-cache.jsonl"
    item = _make_item("rss:test:bounded-cache")
    asyncio.run(ContentAnalyzer(FakeClient(), cache=AnalysisCache(path)).analyze_batch([item]))

    cached = json.loads(path.read_text(encoding="utf-8").splitlines()[0])
    assert len(item.ai_summary_zh) == 100
    assert item.ai_summary_zh.endswith("…")
    assert cached["result"]["summary_zh"] == item.ai_summary_zh
    assert item.ai_action_suggestion in (None, "")
    assert "action_suggestion" not in cached["result"]


def test_analysis_prompt_uses_normalized_source_facts_and_drops_reason_and_action_fields():
    calls = []

    class FakeClient:
        config = SimpleNamespace()

        async def complete(self, system, user, **kwargs):
            calls.append({"system": system, "user": user, **kwargs})
            return (
                '{"score": 8, "channel": "AI", "topics": [], '
                '"signal_strength": "strong", "signal_type": "release", '
                '"entities": [], "is_featured": true, "summary_zh": "摘要", '
                '"action_suggestion": "阅读"}'
            )

    item = _make_item("rss:test:facts")
    item.author = "Author"
    item.content = "Body"
    item.metadata.update(
        {
            "source_display_name": "Official Feed",
            "catalog_source_type": "rss",
            "content_kind": "feed_summary",
        }
    )

    asyncio.run(ContentAnalyzer(FakeClient())._analyze_item(item))

    prompt = calls[0]["user"]
    assert "Source name: Official Feed" in prompt
    assert "Catalog source type: rss" in prompt
    assert "Published at: 2026-04-26T00:00:00+00:00" in prompt
    assert "- reason:" not in prompt
    assert '"reason"' not in prompt
    assert "action_suggestion" not in calls[0]["system"]
    assert "action_suggestion" not in prompt
    assert item.ai_reason is None
    assert item.ai_action_suggestion in (None, "")
    assert item.metadata["analysis_status"] == "ai"


def test_explicit_empty_topic_library_does_not_restore_builtin_topic_defaults():
    prompt = content_analysis_system([])

    assert "AI Agent" not in prompt
    assert "No configured preferred topics" in prompt
