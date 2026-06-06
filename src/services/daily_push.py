"""Helpers for selecting daily push content."""

from __future__ import annotations

from typing import Sequence

from ..models import ContentItem


def select_daily_push_items(
    items: Sequence[ContentItem],
    *,
    threshold: float = 8.5,
    limit: int | None = None,
) -> list[ContentItem]:
    """Return all score-sorted daily push items strictly above threshold.

    ``limit`` is accepted for backward compatibility with existing callers, but
    daily push selection intentionally keeps every item above the configured
    threshold.
    """
    selected = [
        item for item in items
        if item.ai_score is not None and item.ai_score > threshold
    ]
    selected.sort(key=lambda item: item.ai_score or 0, reverse=True)
    return selected
