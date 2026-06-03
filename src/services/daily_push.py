"""Helpers for selecting daily push content."""

from __future__ import annotations

from typing import Sequence

from ..models import ContentItem


def select_daily_push_items(
    items: Sequence[ContentItem],
    *,
    threshold: float = 8.5,
    limit: int = 10,
) -> list[ContentItem]:
    """Return score-sorted daily push items."""
    selected = [
        item for item in items
        if item.ai_score is not None and item.ai_score >= threshold
    ]
    selected.sort(key=lambda item: item.ai_score or 0, reverse=True)
    return selected[:limit]
