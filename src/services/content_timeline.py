"""Stable content time semantics shared by Feed, History, search, and counts."""

from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any
from zoneinfo import ZoneInfo


FEED_TIMEZONE_NAME = "Asia/Shanghai"
FEED_TIMEZONE = ZoneInfo(FEED_TIMEZONE_NAME)
DEFAULT_FEED_WINDOW_DAYS = 7
ALLOWED_FEED_WINDOW_DAYS = frozenset({7, 14, 30})
MAX_FUTURE_PUBLISHED_SKEW = timedelta(minutes=5)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def parse_timestamp(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _utc(parsed)


def normalize_feed_window_days(value: Any) -> int:
    if isinstance(value, bool) or not isinstance(value, int):
        raise ValueError("feed_window_days 必须是允许的整数选项")
    if value not in ALLOWED_FEED_WINDOW_DAYS:
        choices = "、".join(str(item) for item in sorted(ALLOWED_FEED_WINDOW_DAYS))
        raise ValueError(f"feed_window_days 必须是 {choices}")
    return value


@dataclass(frozen=True)
class FeedWindow:
    days: int
    now: datetime
    today_start: datetime
    feed_start: datetime

    def as_dict(self) -> dict[str, Any]:
        return {
            "timezone": FEED_TIMEZONE_NAME,
            "feed_days": self.days,
            "today_start": self.today_start.isoformat(),
            "feed_start": self.feed_start.isoformat(),
            "now": self.now.isoformat(),
        }


def feed_window(
    days: int = DEFAULT_FEED_WINDOW_DAYS,
    *,
    now: datetime | None = None,
) -> FeedWindow:
    normalized_days = normalize_feed_window_days(days)
    current = _utc(now)
    local_now = current.astimezone(FEED_TIMEZONE)
    local_today_start = local_now.replace(hour=0, minute=0, second=0, microsecond=0)
    local_feed_start = local_today_start - timedelta(days=normalized_days - 1)
    return FeedWindow(
        days=normalized_days,
        now=current,
        today_start=local_today_start.astimezone(timezone.utc),
        feed_start=local_feed_start.astimezone(timezone.utc),
    )


def _published_at(item: dict[str, Any]) -> Any:
    presentation = item.get("presentation")
    timing = presentation.get("timing") if isinstance(presentation, dict) else None
    if isinstance(timing, dict) and timing.get("published_at"):
        return timing.get("published_at")
    return item.get("published_at")


def resolve_effective_at(
    item: dict[str, Any],
    *,
    first_seen_at: Any,
    now: datetime | None = None,
) -> str:
    """Resolve a stable display timestamp without letting refetches revive old items."""

    current = _utc(now)
    published = parse_timestamp(_published_at(item))
    if published is not None and published <= current + MAX_FUTURE_PUBLISHED_SKEW:
        return published.isoformat()
    first_seen = parse_timestamp(first_seen_at) or current
    return first_seen.isoformat()


def timeline_bucket(effective_at: Any, window: FeedWindow) -> str:
    parsed = parse_timestamp(effective_at)
    if parsed is None or parsed < window.feed_start:
        return "history"
    if parsed >= window.today_start:
        return "today"
    return "feed"


def project_timeline(
    item: dict[str, Any],
    *,
    effective_at: Any,
    window: FeedWindow,
) -> dict[str, Any]:
    projected = deepcopy(item)
    presentation = projected.get("presentation")
    presentation = presentation if isinstance(presentation, dict) else {}
    timing = presentation.get("timing")
    timing = timing if isinstance(timing, dict) else {}
    timing["effective_at"] = str(effective_at or "")
    presentation["timing"] = timing
    projected["presentation"] = presentation
    projected["timeline_bucket"] = timeline_bucket(effective_at, window)
    return projected


def _flatten(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [text for nested in value.values() for text in _flatten(nested)]
    if isinstance(value, list):
        return [text for nested in value for text in _flatten(nested)]
    if value is None or isinstance(value, bool):
        return []
    return [str(value)]


def build_search_text(
    item: dict[str, Any],
    *,
    body_text: Any = "",
    source_native_title: Any = "",
    include_body: bool = True,
) -> str:
    presentation = item.get("presentation")
    presentation = presentation if isinstance(presentation, dict) else {}
    source = presentation.get("source")
    source = source if isinstance(source, dict) else {}
    author = presentation.get("author")
    author = author if isinstance(author, dict) else {}
    content = presentation.get("content")
    content = content if isinstance(content, dict) else {}
    taxonomy = presentation.get("taxonomy")
    taxonomy = taxonomy if isinstance(taxonomy, dict) else {}
    fields: list[Any] = [
        item.get("title"),
        item.get("source"),
        item.get("author"),
        item.get("summary_zh"),
        item.get("excerpt"),
        item.get("content"),
        item.get("channel"),
        item.get("category"),
        item.get("topics"),
        item.get("tags"),
        source.get("name"),
        source.get("platform"),
        source.get("catalog_type"),
        author.get("name"),
        content.get("title"),
        content.get("excerpt"),
        content.get("content_kind"),
        taxonomy.get("channel"),
        taxonomy.get("topics"),
        source_native_title,
    ]
    if include_body:
        fields.extend((content.get("body_text"), body_text))
    return "\n".join(
        text.strip()
        for field in fields
        for text in _flatten(field)
        if text.strip()
    ).casefold()
