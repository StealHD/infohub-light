import asyncio
import json
from datetime import datetime, timezone
from types import SimpleNamespace

from src.ai.analyzer import ContentAnalyzer
from src.ai.summarizer import DailySummarizer
from src.models import ContentItem, SourceType
from src.services.scheduler import select_daily_push_items
from src.ui.site import build_site_payload, load_history_item_ids, write_static_site


class FakeAIClient:
    def __init__(self, payload: dict):
        self.payload = payload
        self.config = SimpleNamespace(throttle_sec=0, analysis_concurrency=1)

    async def complete(self, system: str, user: str) -> str:
        return json.dumps(self.payload, ensure_ascii=False)


def _make_item(idx: int, score: float = 8.0, source: SourceType = SourceType.RSS) -> ContentItem:
    item = ContentItem(
        id=f"{source.value}:item-{idx}",
        source_type=source,
        title=f"AI Radar Item {idx}",
        url=f"https://example.com/items/{idx}",
        content="A new AI coding workflow was released with practical developer implications.",
        author="Example Source",
        published_at=datetime(2026, 6, 3, 8, idx, tzinfo=timezone.utc),
        metadata={
            "feed_name": "Example Feed",
            "discussion_url": f"https://news.ycombinator.com/item?id={idx}",
        },
    )
    item.ai_score = score
    item.ai_reason = "官方发布，直接影响 AI 开发者工作流。"
    item.ai_summary = "A concise English summary."
    item.ai_summary_zh = "这是一个面向 AI 编程工作流的新发布，值得开发者了解并评估是否引入日常实践。"
    item.ai_action_suggestion = "阅读原文并评估是否加入工具链。"
    item.ai_category = "AI 编程"
    item.ai_is_featured = score >= 7.5
    item.ai_tags = ["AI Agent", "AI 编程", "RAG/MCP"]
    return item


def test_analyzer_stores_private_radar_fields():
    analyzer = ContentAnalyzer(
        FakeAIClient(
            {
                "score": 8.7,
                "reason": "重要发布，可信来源，值得立即测试。",
                "tags": ["AI Agent", "Codex", "workflow", "RandomVendorTag"],
                "category": "AI 编程",
                "is_featured": True,
                "summary_zh": "该动态说明 AI 编程工具链出现了明确变化，开发者可以据此调整自动化流程。",
                "action_suggestion": "阅读发布说明，并在一个小项目中测试。",
            }
        )
    )
    item = _make_item(1)

    asyncio.run(analyzer._analyze_item(item))

    assert item.ai_score == 8.7
    assert item.ai_category == "AI"
    assert item.ai_channel == "AI"
    assert item.ai_is_featured is True
    assert item.ai_summary_zh.startswith("该动态说明")
    assert item.ai_action_suggestion == "阅读发布说明，并在一个小项目中测试。"
    assert item.ai_topics == ["AI Agent", "Codex", "AI 编程", "RandomVendorTag"]
    assert item.ai_tags == ["AI Agent", "Codex", "AI 编程", "RandomVendorTag"]


def test_chinese_summary_renders_private_radar_card_fields():
    summarizer = DailySummarizer()
    item = _make_item(1, score=8.6)

    result = asyncio.run(
        summarizer.generate_summary(
            [item],
            date="2026-06-03",
            total_fetched=12,
            language="zh",
        )
    )

    assert "## AI Radar Item 1" in result
    assert "**来源**: rss · Example Feed · 6月3日 08:01" in result
    assert "**分数**: 8.6/10" in result
    assert "**150-250 字中文摘要**" in result
    assert item.ai_summary_zh in result
    assert "**推荐理由**: 官方发布，直接影响 AI 开发者工作流。" in result
    assert "**我该关注什么**: 阅读原文并评估是否加入工具链。" in result
    assert "**原文链接**: https://example.com/items/1" in result
    assert "**关联讨论**: https://news.ycombinator.com/item?id=1" in result


def test_site_payload_keeps_all_items_and_splits_featured_and_daily_top():
    items = [_make_item(i, score=score) for i, score in enumerate([9.2, 8.6, 7.6, 6.4, 5.2], start=1)]

    payload = build_site_payload(
        all_items=items,
        date="2026-06-03",
        total_fetched=20,
        featured_threshold=7.5,
        daily_push_threshold=8.5,
        daily_push_limit=10,
    )

    assert len(payload["items"]) == 5
    assert [item["score"] for item in payload["featured_items"]] == [9.2, 8.6, 7.6]
    assert [item["score"] for item in payload["daily_push_items"]] == [9.2, 8.6]
    assert payload["items"][-1]["show_on_featured_home"] is False
    assert payload["tags"] == ["AI Agent", "AI 编程", "RAG/MCP"]
    assert payload["sources"] == ["Example Feed"]


def test_select_daily_push_items_uses_strict_threshold_without_limit():
    items = [_make_item(i, score=score) for i, score in enumerate([9.8, 9.1, 8.8, 8.5, 8.4, 7.9], start=1)]

    selected = select_daily_push_items(items, threshold=8.5, limit=2)

    assert [item.ai_score for item in selected] == [9.8, 9.1, 8.8]


def test_write_static_site_keeps_same_day_items_in_today_file(tmp_path):
    first = build_site_payload(
        all_items=[_make_item(1, score=8.0)],
        date="2026-06-03",
        total_fetched=1,
    )
    second = build_site_payload(
        all_items=[_make_item(2, score=6.8)],
        date="2026-06-03",
        total_fetched=1,
    )
    first["generated_at"] = "2026-06-03T08:00:00+00:00"
    second["generated_at"] = "2026-06-03T09:00:00+00:00"

    write_static_site(tmp_path, first)
    write_static_site(tmp_path, second)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))
    today = json.loads((tmp_path / "today-data.json").read_text(encoding="utf-8"))

    assert [item["id"] for item in today["items"]] == ["rss:item-2", "rss:item-1"]
    assert [item["id"] for item in today["today_items"]] == ["rss:item-2", "rss:item-1"]
    assert today["today_total_items"] == 2
    assert today["history_total_items"] == 0
    assert [item["id"] for item in current["today_items"]] == ["rss:item-2", "rss:item-1"]
    assert current["today_total_items"] == 2
    assert current["items"] == []
    assert history["items"] == []
    assert history["runs"] == []
    assert (tmp_path / "today" / "20260603-080000.json").exists()
    assert (tmp_path / "today" / "20260603-090000.json").exists()


def test_write_static_site_archives_today_file_when_date_changes(tmp_path):
    first = build_site_payload(
        all_items=[_make_item(1, score=8.0)],
        date="2026-06-03",
        total_fetched=1,
    )
    second = build_site_payload(
        all_items=[_make_item(2, score=6.8)],
        date="2026-06-04",
        total_fetched=1,
    )
    first["generated_at"] = "2026-06-03T08:00:00+00:00"
    second["generated_at"] = "2026-06-04T09:00:00+00:00"

    write_static_site(tmp_path, first)
    write_static_site(tmp_path, second)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))
    today = json.loads((tmp_path / "today-data.json").read_text(encoding="utf-8"))

    assert [item["id"] for item in today["items"]] == ["rss:item-2"]
    assert [item["id"] for item in current["today_items"]] == ["rss:item-2"]
    assert [item["id"] for item in current["items"]] == ["rss:item-1"]
    assert [item["id"] for item in history["items"]] == ["rss:item-1"]
    assert len(history["runs"]) == 1
    assert history["runs"][0]["date"] == "2026-06-03"


def test_write_static_site_keeps_only_recent_items_in_current_payload(tmp_path):
    payload = build_site_payload(
        all_items=[_make_item(i, score=8.0) for i in range(1, 26)],
        date="2026-06-03",
        total_fetched=25,
    )
    payload["generated_at"] = "2026-06-03T10:00:00+00:00"

    write_static_site(tmp_path, payload)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))
    today = json.loads((tmp_path / "today-data.json").read_text(encoding="utf-8"))

    assert current["items"] == []
    assert len(current["today_items"]) == 25
    assert current["today_total_items"] == 25
    assert [item["id"] for item in today["items"][:3]] == [
        "rss:item-25",
        "rss:item-24",
        "rss:item-23",
    ]
    assert current["recent_item_limit"] == 20
    assert history["items"] == []


def test_write_static_site_builds_current_payload_from_cumulative_history(tmp_path):
    first = build_site_payload(
        all_items=[_make_item(i, score=8.0) for i in range(1, 26)],
        date="2026-06-03",
        total_fetched=25,
    )
    second = build_site_payload(
        all_items=[_make_item(26, score=8.0)],
        date="2026-06-03",
        total_fetched=1,
    )
    first["generated_at"] = "2026-06-03T10:00:00+00:00"
    second["generated_at"] = "2026-06-03T11:00:00+00:00"

    write_static_site(tmp_path, first)
    write_static_site(tmp_path, second)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))
    today = json.loads((tmp_path / "today-data.json").read_text(encoding="utf-8"))

    assert current["items"] == []
    assert [item["id"] for item in current["today_items"][:3]] == [
        "rss:item-26",
        "rss:item-25",
        "rss:item-24",
    ]
    assert current["today_total_items"] == 26
    assert today["items"][-1]["id"] == "rss:item-1"
    assert history["items"] == []


def test_write_static_site_accumulates_today_featured_until_archive(tmp_path):
    first = build_site_payload(
        all_items=[_make_item(i, score=8.0) for i in range(1, 26)],
        date="2026-06-03",
        total_fetched=25,
    )
    second = build_site_payload(
        all_items=[_make_item(i, score=6.8) for i in range(26, 51)],
        date="2026-06-03",
        total_fetched=25,
    )
    first["generated_at"] = "2026-06-03T10:00:00+00:00"
    second["generated_at"] = "2026-06-03T11:00:00+00:00"

    write_static_site(tmp_path, first)
    write_static_site(tmp_path, second)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))

    assert current["items"] == []
    assert len(current["today_items"]) == 50
    assert len(current["featured_items"]) == 25
    assert all(item["score"] >= 7.5 for item in current["featured_items"])


def test_write_static_site_accumulates_today_daily_push_until_archive(tmp_path):
    first = build_site_payload(
        all_items=[_make_item(i, score=score) for i, score in enumerate([9.2, 8.6, 8.3, 8.0, 7.9], start=1)],
        date="2026-06-03",
        total_fetched=5,
        daily_push_threshold=8.0,
        daily_push_limit=1,
    )
    second = build_site_payload(
        all_items=[_make_item(i, score=6.8) for i in range(6, 31)],
        date="2026-06-03",
        total_fetched=25,
        daily_push_threshold=8.0,
        daily_push_limit=1,
    )
    first["generated_at"] = "2026-06-03T10:00:00+00:00"
    second["generated_at"] = "2026-06-03T11:00:00+00:00"

    write_static_site(tmp_path, first)
    write_static_site(tmp_path, second)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))

    assert [item["score"] for item in current["daily_push_items"]] == [9.2, 8.6, 8.3]
    assert history["daily_push_items"] == []


def test_write_static_site_preserves_custom_tags_from_tag_library(tmp_path):
    item = _make_item(1, score=8.0)
    item.ai_tags = []
    item.ai_category = "行业动态"
    item.metadata["tags"] = ["价格监控"]
    payload = build_site_payload(
        all_items=[item],
        date="2026-06-03",
        total_fetched=1,
        tag_library=["AI Agent", "行业动态", "价格监控"],
    )
    payload["generated_at"] = "2026-06-03T10:00:00+00:00"

    write_static_site(tmp_path, payload)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))

    assert current["today_items"][0]["tags"] == ["价格监控", "行业动态"]
    assert "价格监控" in current["tags"]
    assert history["items"] == []


def test_write_static_site_splits_personal_tags_without_changing_score(tmp_path):
    item = _make_item(1, score=1.0)
    item.ai_tags = []
    item.ai_category = "行业动态"
    item.metadata["personal_tags"] = ["能黄通"]
    payload = build_site_payload(
        all_items=[item],
        date="2026-06-03",
        total_fetched=1,
        featured_threshold=7.5,
        tag_library=["行业动态"],
        personal_tag_library=["能黄通"],
    )
    payload["generated_at"] = "2026-06-03T10:00:00+00:00"

    write_static_site(tmp_path, payload)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))
    item_payload = current["personal_items"][0]

    assert item_payload["score"] == 1.0
    assert item_payload["interest_score"] == 8.0
    assert item_payload["personal_tags"] == ["能黄通"]
    assert item_payload["show_in_personal_feed"] is True
    assert current["featured_items"] == []
    assert history["personal_items"] == []


def test_write_static_site_preserves_existing_personal_tags_for_same_item(tmp_path):
    first_item = _make_item(1, score=1.0)
    first_item.ai_tags = []
    first_item.ai_category = "行业动态"
    first_item.metadata["personal_tags"] = ["能黄通"]
    first_item.metadata["show_in_personal_feed"] = True
    first = build_site_payload(
        all_items=[first_item],
        date="2026-06-03",
        total_fetched=1,
        tag_library=["行业动态"],
        personal_tag_library=["能黄通"],
    )
    first["generated_at"] = "2026-06-03T10:00:00+00:00"

    second_item = _make_item(1, score=1.0)
    second_item.ai_tags = []
    second_item.ai_category = "行业动态"
    second_item.metadata["show_in_personal_feed"] = True
    second = build_site_payload(
        all_items=[second_item],
        date="2026-06-03",
        total_fetched=1,
        tag_library=["行业动态"],
        personal_tag_library=["能黄通"],
    )
    second["generated_at"] = "2026-06-03T11:00:00+00:00"

    write_static_site(tmp_path, first)
    write_static_site(tmp_path, second)

    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))
    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))

    assert history["items"] == []
    assert history["personal_items"] == []
    assert current["personal_items"][0]["personal_tags"] == ["能黄通"]


def test_write_static_site_drops_removed_custom_tags_from_history(tmp_path):
    item = _make_item(1, score=8.0)
    item.ai_tags = []
    item.ai_category = "行业动态"
    item.metadata["tags"] = ["旧标签"]
    first = build_site_payload(
        all_items=[item],
        date="2026-06-03",
        total_fetched=1,
        tag_library=["行业动态", "旧标签"],
    )
    first["generated_at"] = "2026-06-03T10:00:00+00:00"
    second = build_site_payload(
        all_items=[],
        date="2026-06-03",
        total_fetched=0,
        tag_library=["行业动态"],
    )
    second["generated_at"] = "2026-06-03T11:00:00+00:00"

    write_static_site(tmp_path, first)
    write_static_site(tmp_path, second)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))

    assert current["tag_library"] == ["行业动态"]
    assert history["tag_library"] == ["行业动态"]
    assert "旧标签" in current["tags"]
    assert "旧标签" not in history["tags"]
    assert history["items"] == []


def test_write_static_site_serializes_social_media_urls(tmp_path):
    item = _make_item(1, score=8.0)
    item.metadata["image_url"] = "https://cdn.example.com/main.jpg"
    item.metadata["media_urls"] = [
        "https://cdn.example.com/main.jpg",
        "https://cdn.example.com/second.jpg",
    ]
    payload = build_site_payload(
        all_items=[item],
        date="2026-06-03",
        total_fetched=1,
    )
    payload["generated_at"] = "2026-06-03T10:00:00+00:00"

    write_static_site(tmp_path, payload)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))

    assert current["today_items"][0]["image_url"] == "https://cdn.example.com/main.jpg"
    assert current["today_items"][0]["media_urls"] == [
        "https://cdn.example.com/main.jpg",
        "https://cdn.example.com/second.jpg",
    ]
    assert history["items"] == []


def test_write_static_site_caches_instagram_media_same_origin(tmp_path, monkeypatch):
    image_url = "https://scontent-sea5-1.cdninstagram.com/v/t51.82787-15/main.jpg?oh=signed"

    class FakeResponse:
        headers = {"content-type": "image/jpeg"}

        def raise_for_status(self):
            return None

        def iter_bytes(self):
            yield b"fake-jpeg"

    class FakeClient:
        def __init__(self, *args, **kwargs):
            return None

        def __enter__(self):
            return self

        def __exit__(self, *args):
            return False

        def get(self, url):
            assert url == image_url
            return FakeResponse()

    monkeypatch.setattr("src.ui.media_cache.httpx.Client", FakeClient)

    item = _make_item(1, score=8.0)
    item.metadata["image_url"] = image_url
    item.metadata["media_urls"] = [image_url]
    payload = build_site_payload(
        all_items=[item],
        date="2026-06-03",
        total_fetched=1,
    )
    payload["generated_at"] = "2026-06-03T10:00:00+00:00"

    write_static_site(tmp_path, payload)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))
    cached_url = current["today_items"][0]["image_url"]

    assert cached_url.startswith("media/")
    assert current["today_items"][0]["media_urls"] == [cached_url]
    assert current["today_items"][0]["remote_image_url"] == image_url
    assert history["items"] == []
    assert (tmp_path / cached_url).read_bytes() == b"fake-jpeg"


def test_load_history_item_ids_supports_incremental_polls(tmp_path):
    payload = build_site_payload(
        all_items=[_make_item(1, score=8.0), _make_item(2, score=7.0)],
        date="2026-06-03",
        total_fetched=2,
    )

    write_static_site(tmp_path, payload)

    assert load_history_item_ids(tmp_path) == {"rss:item-1", "rss:item-2"}


def test_load_history_item_ids_reads_archived_and_today_files(tmp_path):
    first = build_site_payload(
        all_items=[_make_item(1, score=8.0)],
        date="2026-06-03",
        total_fetched=1,
    )
    second = build_site_payload(
        all_items=[_make_item(2, score=7.0)],
        date="2026-06-04",
        total_fetched=1,
    )

    write_static_site(tmp_path, first)
    write_static_site(tmp_path, second)

    assert load_history_item_ids(tmp_path) == {"rss:item-1", "rss:item-2"}


def test_write_static_site_normalizes_legacy_history_tags(tmp_path):
    payload = build_site_payload(
        all_items=[_make_item(1, score=8.0)],
        date="2026-06-03",
        total_fetched=1,
    )
    payload["items"][0]["tags"] = ["Codex", "workflow", "RandomVendorTag", "OpenAI"]
    payload["items"][0]["category"] = "AI编程工具"

    write_static_site(tmp_path, payload)

    current = json.loads((tmp_path / "radar-data.json").read_text(encoding="utf-8"))
    history = json.loads((tmp_path / "history-data.json").read_text(encoding="utf-8"))

    assert current["today_items"][0]["tags"] == ["AI Agent", "AI 编程", "RAG/MCP"]
    assert current["today_items"][0]["topics"] == ["AI Agent", "AI 编程", "RAG/MCP"]
    assert current["today_items"][0]["category"] == "AI"
    assert current["today_items"][0]["channel"] == "AI"
    assert current["tags"] == ["AI Agent", "AI 编程", "RAG/MCP"]
    assert history["items"] == []
