from __future__ import annotations

from datetime import datetime, timezone

from src.ai.summary_policy import normalize_item_summary, truncate_summary
from src.models import ContentItem, SourceType


def _item(**values) -> ContentItem:
    defaults = {
        "id": "rss:summary:1",
        "source_type": SourceType.RSS,
        "title": "Fallback title",
        "url": "https://example.com/item",
        "published_at": datetime(2026, 7, 13, tzinfo=timezone.utc),
    }
    defaults.update(values)
    return ContentItem(**defaults)


def test_truncate_summary_prefers_a_nearby_sentence_boundary() -> None:
    text = "第一句话提供完整信息。第二句话包含很多补充细节并且会超过限制。"

    result = truncate_summary(text, 18)

    assert result == "第一句话提供完整信息。"
    assert len(result) <= 18


def test_truncate_summary_hard_cuts_without_late_sentence_boundary() -> None:
    result = truncate_summary("这是一段完全没有标点并且非常长的中文概括文本", 12)

    assert result.endswith("…")
    assert len(result) == 12


def test_truncate_summary_collapses_whitespace_and_counts_ellipsis_in_limit() -> None:
    result = truncate_summary("  多余   空格\n换行\t都要压缩而且最终仍然受限  ", 15)

    assert "  " not in result
    assert "\n" not in result
    assert len(result) <= 15


def test_normalize_item_summary_uses_ai_then_source_summary_then_content_then_title() -> None:
    ai_item = _item(ai_summary_zh="AI 概括")
    normalize_item_summary(ai_item, 200)
    assert ai_item.ai_summary_zh == "AI 概括"

    source_item = _item(content="正文内容")
    source_item.metadata["source_summary"] = "<p>来源 <strong>摘要</strong></p>"
    normalize_item_summary(source_item, 200)
    assert source_item.ai_summary_zh == "来源 摘要"

    content_item = _item(content="<div>正文 <em>片段</em></div>")
    normalize_item_summary(content_item, 200)
    assert content_item.ai_summary_zh == "正文 片段"

    title_item = _item()
    normalize_item_summary(title_item, 200)
    assert title_item.ai_summary_zh == "Fallback title"


def test_normalize_item_summary_enforces_limit_on_model_output() -> None:
    item = _item(ai_summary_zh="没有标点" * 80)

    normalize_item_summary(item, 200)

    assert len(item.ai_summary_zh or "") == 200
    assert item.ai_summary_zh.endswith("…")
    assert item.ai_summary == item.ai_summary_zh
