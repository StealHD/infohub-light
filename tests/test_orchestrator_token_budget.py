from datetime import datetime, timezone

from src.models import ContentItem, SourceType
from src.orchestrator import HorizonOrchestrator


def _item(item_id: str, analysis_mode: str) -> ContentItem:
    return ContentItem(
        id=item_id,
        source_type=SourceType.INSTAGRAM,
        title=item_id,
        url="https://www.instagram.com/p/example/",
        published_at=datetime(2026, 6, 6, tzinfo=timezone.utc),
        metadata={"analysis_mode": analysis_mode, "personal_tags": ["能黄通"]},
    )


def test_partition_analysis_items_keeps_personal_only_out_of_ai_queue():
    full = _item("instagram:post:full", "full")
    personal = _item("instagram:post:personal", "personal_only")

    analysis_items, passthrough_items = HorizonOrchestrator.partition_analysis_items(
        [full, personal]
    )

    assert analysis_items == [full]
    assert passthrough_items == [personal]
    assert personal.ai_score == 0.0
    assert personal.ai_reason == "Personal-only item skipped AI analysis"
    assert personal.metadata["show_in_personal_feed"] is True
