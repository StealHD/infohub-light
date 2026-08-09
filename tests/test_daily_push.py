from datetime import datetime, timezone

from src.models import ContentItem, SourceType
from src.services.daily_push import select_daily_push_items


def _item(index: int, score: float) -> ContentItem:
    item = ContentItem(
        id=f"rss:item-{index}",
        source_type=SourceType.RSS,
        title=f"Item {index}",
        url=f"https://example.com/items/{index}",
        published_at=datetime(2026, 6, 3, tzinfo=timezone.utc),
    )
    item.ai_score = score
    return item


def test_select_daily_push_items_uses_strict_threshold_without_legacy_limit() -> None:
    items = [
        _item(index, score)
        for index, score in enumerate([9.8, 9.1, 8.8, 8.5, 8.4, 7.9], start=1)
    ]

    selected = select_daily_push_items(items, threshold=8.5, limit=2)

    assert [item.ai_score for item in selected] == [9.8, 9.1, 8.8]
