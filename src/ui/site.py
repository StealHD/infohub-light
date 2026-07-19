"""Generate the static private AI radar web UI."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..config_migration import normalize_personal_tags
from ..models import ContentItem
from ..services.content_presentation import build_content_presentation
from ..tag_policy import (
    HUB_CHANNELS,
    normalize_channel,
    normalize_entities,
    normalize_signal_strength,
    normalize_signal_type,
    normalize_tags,
    order_tags,
)
from .media_cache import cache_payload_media


STATIC_DIR = Path(__file__).resolve().parent / "static"
HISTORY_ITEM_LIMIT = 2000
HISTORY_RUN_LIMIT = 60
RECENT_ITEM_LIMIT = 20


def _score(item: ContentItem) -> float:
    return float(item.ai_score or 0)


def _source_label(item: ContentItem) -> str:
    meta = item.metadata
    if meta.get("feed_name"):
        return str(meta["feed_name"])
    if meta.get("subreddit"):
        return f"r/{meta['subreddit']}"
    if meta.get("channel"):
        return f"@{meta['channel']}"
    if meta.get("repo"):
        return str(meta["repo"])
    if meta.get("watchlist"):
        return str(meta["watchlist"])
    return item.author or item.source_type.value


def _isoformat(dt: datetime | None) -> str:
    if not dt:
        return ""
    if dt.tzinfo is None:
        dt = dt.replace(tzinfo=timezone.utc)
    return dt.isoformat()


def _merge_tags(*tag_groups: Iterable[Any]) -> list[str]:
    tags: list[str] = []
    for group in tag_groups:
        for tag in group:
            tag_text = str(tag).strip()
            if tag_text and tag_text not in tags:
                tags.append(tag_text)
    return tags


def _legacy_category_topic(value: Any) -> list[str]:
    if not value:
        return []
    text = str(value).strip()
    return [] if text in HUB_CHANNELS else [text]


def _coerce_float(value: Any, default: float = 0.0) -> float:
    try:
        return float(value)
    except (TypeError, ValueError):
        return default


def _personal_interest_score(
    *,
    personal_tags: Iterable[str],
    explicit_score: Any = None,
) -> float:
    score = _coerce_float(explicit_score, default=0.0)
    if score > 0:
        return max(0.0, min(score, 10.0))
    return 8.0 if list(personal_tags) else 0.0


def serialize_item(
    item: ContentItem,
    *,
    featured_threshold: float,
    homepage_min_score: float = 6.0,
    tag_library: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Serialize a ContentItem for the browser UI."""
    score = _score(item)
    source = _source_label(item)
    discussion_url = item.metadata.get("discussion_url")
    summary = (
        item.ai_summary_zh
        or item.metadata.get("detailed_summary_zh")
        or item.ai_summary
        or ""
    )
    metadata_tags = item.metadata.get("topics") or item.metadata.get("tags") or []
    if not isinstance(metadata_tags, list):
        metadata_tags = []
    metadata_personal_tags = item.metadata.get("personal_tags") or []
    if not isinstance(metadata_personal_tags, list):
        metadata_personal_tags = []
    image_url = str(item.metadata.get("image_url") or "").strip()
    media_urls_raw = item.metadata.get("media_urls") or []
    media_urls = [
        str(url).strip()
        for url in media_urls_raw
        if isinstance(url, str) and str(url).strip()
    ]
    if image_url and image_url not in media_urls:
        media_urls.insert(0, image_url)
    remote_image_url = str(item.metadata.get("remote_image_url") or "").strip()
    remote_media_urls_raw = item.metadata.get("remote_media_urls") or []
    remote_media_urls = [
        str(url).strip()
        for url in remote_media_urls_raw
        if isinstance(url, str) and str(url).strip()
    ]
    channel = normalize_channel(
        item.ai_channel
        or item.metadata.get("channel")
        or item.metadata.get("category")
        or item.ai_category,
        fallback=item.source_type.value,
    )
    tags = normalize_tags(
        _merge_tags(
            item.ai_topics,
            item.ai_tags,
            metadata_tags,
            _legacy_category_topic(item.ai_category),
        ),
        fallback=channel,
        max_tags=6,
        allowed_tags=tag_library,
        allow_custom=True,
    )
    personal_tags = normalize_personal_tags(metadata_personal_tags)
    interest_score = _personal_interest_score(
        personal_tags=personal_tags,
        explicit_score=item.metadata.get("interest_score"),
    )
    show_in_personal_feed = bool(
        item.metadata.get("show_in_personal_feed")
        or interest_score > 0
        or personal_tags
    )
    source_ids = list(dict.fromkeys(
        str(value)
        for value in [
            *(item.metadata.get("source_ids") or []),
            item.metadata.get("source_id"),
        ]
        if value
    ))
    subscription_ids = list(dict.fromkeys(
        str(value)
        for value in [
            *(item.metadata.get("subscription_ids") or []),
            item.metadata.get("subscription_id"),
        ]
        if value
    ))
    source_keys = list(dict.fromkeys(
        str(value)
        for value in [
            *(item.metadata.get("source_keys") or []),
            item.metadata.get("source_key"),
        ]
        if value
    ))
    presentation = build_content_presentation(item)
    presentation["taxonomy"]["channel"] = channel
    presentation["taxonomy"]["topics"] = tags
    presentation["analysis"]["signal_strength"] = normalize_signal_strength(
        item.ai_signal_strength,
        score=score,
    )
    presentation["analysis"]["signal_type"] = normalize_signal_type(
        item.ai_signal_type
    )
    explicit_retention = str(item.metadata.get("retention_policy") or "")
    if explicit_retention in {"latest_per_source", "time_window"}:
        retention_policy = explicit_retention
    else:
        retention_policy = "time_window"

    return {
        "id": item.id,
        "title": item.metadata.get("title_zh") or item.title,
        "source_type": item.source_type.value,
        "source": source,
        "author": item.author or "",
        "url": str(item.url),
        "discussion_url": str(discussion_url) if discussion_url else "",
        "published_at": _isoformat(item.published_at),
        "fetched_at": _isoformat(item.fetched_at),
        "score": score,
        "reason": item.ai_reason or "",
        "channel": channel,
        "topics": tags,
        "tags": tags,
        "category": channel,
        "signal_strength": normalize_signal_strength(
            item.ai_signal_strength,
            score=score,
        ),
        "signal_type": normalize_signal_type(item.ai_signal_type),
        "entities": normalize_entities(item.ai_entities),
        "is_featured": bool(item.ai_is_featured or score >= featured_threshold),
        "show_on_featured_home": score >= featured_threshold and score >= homepage_min_score,
        "summary_zh": str(summary),
        "action_suggestion": item.ai_action_suggestion or "",
        "image_url": image_url,
        "media_urls": media_urls,
        "remote_image_url": remote_image_url,
        "remote_media_urls": remote_media_urls,
        "personal_tags": personal_tags,
        "interest_score": interest_score,
        "show_in_personal_feed": show_in_personal_feed,
        "scoring_disabled": bool(item.metadata.get("scoring_disabled")),
        "source_id": str(item.metadata.get("source_id") or ""),
        "subscription_id": str(item.metadata.get("subscription_id") or ""),
        "source_key": str(item.metadata.get("source_key") or ""),
        "source_ids": source_ids,
        "subscription_ids": subscription_ids,
        "source_keys": source_keys,
        "analysis_mode": str(item.metadata.get("analysis_mode") or "full"),
        "retention_policy": retention_policy,
        "retention_policy_explicit": bool(explicit_retention),
        "presentation": presentation,
    }


def _unique_sorted(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value})


def _unique_tags(
    values: Iterable[str],
    *,
    tag_library: Iterable[str] | None = None,
) -> list[str]:
    return order_tags(
        (value for value in values if value),
        allowed_tags=tag_library,
    )


def _parse_dt(value: str) -> datetime:
    try:
        return datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return datetime.min.replace(tzinfo=timezone.utc)


def _history_snapshot_name(payload: dict[str, Any]) -> str:
    generated = _parse_dt(str(payload.get("generated_at") or ""))
    if generated == datetime.min.replace(tzinfo=timezone.utc):
        generated = datetime.now(timezone.utc)
    return generated.strftime("%Y%m%d-%H%M%S") + ".json"


def _read_json_payload(path: Path) -> dict[str, Any] | None:
    if not path.exists():
        return None
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return None
    return payload if isinstance(payload, dict) else None


def _write_json_payload(path: Path, payload: dict[str, Any]) -> None:
    path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


def _normalize_payload_item(
    item: dict[str, Any],
    *,
    tag_library: Iterable[str] | None = None,
) -> dict[str, Any]:
    normalized = dict(item)
    tags = normalized.get("topics") or normalized.get("tags") or []
    if not isinstance(tags, list):
        tags = []
    channel = normalize_channel(
        normalized.get("channel") or normalized.get("category"),
        fallback=tags[0] if tags else None,
    )
    normalized["topics"] = normalize_tags(
        [*tags, *_legacy_category_topic(normalized.get("category"))],
        fallback=channel,
        max_tags=6,
        allowed_tags=tag_library,
        allow_custom=True,
    )
    normalized["tags"] = list(normalized["topics"])
    normalized["channel"] = channel
    normalized["category"] = channel
    normalized["signal_strength"] = normalize_signal_strength(
        normalized.get("signal_strength"),
        score=_coerce_float(normalized.get("score")),
    )
    normalized["signal_type"] = normalize_signal_type(normalized.get("signal_type"))
    raw_entities = normalized.get("entities") or []
    normalized["entities"] = normalize_entities(raw_entities if isinstance(raw_entities, list) else [])
    personal_tags = normalize_personal_tags(normalized.get("personal_tags") or [])
    normalized["personal_tags"] = personal_tags
    normalized["interest_score"] = _personal_interest_score(
        personal_tags=personal_tags,
        explicit_score=normalized.get("interest_score"),
    )
    normalized["show_in_personal_feed"] = bool(
        normalized.get("show_in_personal_feed")
        or normalized["interest_score"] > 0
        or personal_tags
    )
    return normalized


def _payload_score(item: dict[str, Any]) -> float:
    return float(item.get("score") or 0)


def _payload_date(item: dict[str, Any]) -> datetime:
    return _parse_dt(str(item.get("published_at") or item.get("fetched_at") or ""))


def _payload_tag_library(
    primary: dict[str, Any],
    fallback: Iterable[str] | None = None,
) -> list[str]:
    if "tag_library" in primary:
        value = primary.get("tag_library")
        return list(value) if isinstance(value, list) else []
    return list(fallback or [])


def _payload_personal_tag_library(
    primary: dict[str, Any],
    fallback: Iterable[str] | None = None,
) -> list[str]:
    if "personal_tag_library" in primary:
        value = primary.get("personal_tag_library")
        return list(value) if isinstance(value, list) else []
    return list(fallback or [])


def _daily_push_payload_items(
    items: Iterable[dict[str, Any]],
    *,
    threshold: float,
) -> list[dict[str, Any]]:
    daily_items = [item for item in items if _payload_score(item) > threshold]
    return sorted(
        daily_items,
        key=lambda item: (_payload_score(item), _payload_date(item)),
        reverse=True,
    )


def _personal_payload_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    personal_items = [
        item
        for item in items
        if item.get("show_in_personal_feed") or _coerce_float(item.get("interest_score")) > 0
    ]
    return sorted(
        personal_items,
        key=lambda item: (
            _coerce_float(item.get("interest_score")),
            _payload_date(item),
        ),
        reverse=True,
    )


def _sort_payload_items(items: Iterable[dict[str, Any]]) -> list[dict[str, Any]]:
    return sorted(
        items,
        key=lambda item: (
            _payload_date(item),
            _payload_score(item),
        ),
        reverse=True,
    )


def _payload_item_collections(
    items: list[dict[str, Any]],
    *,
    thresholds: dict[str, Any],
) -> tuple[list[dict[str, Any]], list[dict[str, Any]], list[dict[str, Any]]]:
    featured_threshold = float(thresholds.get("featured", 7.5))
    daily_threshold = float(thresholds.get("daily_push", 8.5))
    featured_items = [item for item in items if _payload_score(item) >= featured_threshold]
    daily_push_items = _daily_push_payload_items(items, threshold=daily_threshold)
    personal_items = _personal_payload_items(items)
    return featured_items, daily_push_items, personal_items


def _merge_payload_personal_tags(
    item: dict[str, Any],
    existing_item: dict[str, Any] | None,
) -> dict[str, Any]:
    if not existing_item:
        return item
    personal_tags = normalize_personal_tags(
        [
            *(item.get("personal_tags") or []),
            *(existing_item.get("personal_tags") or []),
        ]
    )
    if not personal_tags:
        return item
    merged = dict(item)
    merged["personal_tags"] = personal_tags
    merged["interest_score"] = _personal_interest_score(
        personal_tags=personal_tags,
        explicit_score=merged.get("interest_score"),
    )
    merged["show_in_personal_feed"] = True
    return merged


def _merge_payload_items(
    existing_items: Iterable[dict[str, Any]],
    current_items: Iterable[dict[str, Any]],
    *,
    tag_library: Iterable[str] | None = None,
) -> list[dict[str, Any]]:
    by_id: dict[str, dict[str, Any]] = {}
    for item in existing_items:
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = _normalize_payload_item(
                item,
                tag_library=tag_library,
            )
    for item in current_items:
        if isinstance(item, dict) and item.get("id"):
            item_id = str(item["id"])
            normalized_item = _normalize_payload_item(
                item,
                tag_library=tag_library,
            )
            by_id[item_id] = _merge_payload_personal_tags(
                normalized_item,
                by_id.get(item_id),
            )
    return _sort_payload_items(by_id.values())


def _empty_history_payload(
    reference: dict[str, Any],
    *,
    tag_library: Iterable[str] | None = None,
    personal_tag_library: Iterable[str] | None = None,
) -> dict[str, Any]:
    return {
        "generated_at": reference.get("generated_at"),
        "date": reference.get("date"),
        "total_fetched": 0,
        "thresholds": reference.get("thresholds") or {},
        "items": [],
        "featured_items": [],
        "daily_push_items": [],
        "personal_items": [],
        "tags": [],
        "tag_library": list(tag_library or []),
        "personal_tags": [],
        "personal_tag_library": list(personal_tag_library or []),
        "sources": [],
        "channels": [],
        "categories": [],
        "runs": [],
        "history": True,
    }


def _build_history_payload_from_existing(
    reference: dict[str, Any],
    existing: dict[str, Any] | None,
    *,
    exclude_item_ids: Iterable[str] | None = None,
) -> dict[str, Any]:
    existing = existing or {}
    tag_library = _payload_tag_library(
        reference,
        existing.get("tag_library") or [],
    )
    personal_tag_library = _payload_personal_tag_library(
        reference,
        existing.get("personal_tag_library") or [],
    )
    excluded = {str(item_id) for item_id in (exclude_item_ids or []) if item_id}
    items = _merge_payload_items(
        [
            item
            for item in existing.get("items", [])
            if isinstance(item, dict) and str(item.get("id") or "") not in excluded
        ],
        [],
        tag_library=tag_library,
    )[:HISTORY_ITEM_LIMIT]

    thresholds = reference.get("thresholds") or existing.get("thresholds") or {}
    featured_items, daily_push_items, personal_items = _payload_item_collections(
        items,
        thresholds=thresholds,
    )
    runs = list(existing.get("runs", []))[:HISTORY_RUN_LIMIT]
    if not items and not runs:
        return _empty_history_payload(
            reference,
            tag_library=tag_library,
            personal_tag_library=personal_tag_library,
        )

    return {
        "generated_at": reference.get("generated_at") or existing.get("generated_at"),
        "date": reference.get("date") or existing.get("date"),
        "total_fetched": sum(int(run.get("total_fetched") or 0) for run in runs),
        "thresholds": thresholds,
        "items": items,
        "featured_items": featured_items,
        "daily_push_items": daily_push_items,
        "personal_items": personal_items,
        "tags": _unique_tags(
            (tag for item in items for tag in item.get("tags", [])),
            tag_library=tag_library,
        ),
        "tag_library": list(tag_library or []),
        "personal_tags": _unique_sorted(
            tag for item in items for tag in item.get("personal_tags", [])
        ),
        "personal_tag_library": list(personal_tag_library or []),
        "sources": _unique_sorted(str(item.get("source")) for item in items),
        "channels": _unique_sorted(str(item.get("channel") or item.get("category")) for item in items),
        "categories": _unique_sorted(str(item.get("category")) for item in items),
        "runs": runs,
        "history": True,
    }


def _build_today_payload(
    current: dict[str, Any],
    existing_today: dict[str, Any] | None,
) -> dict[str, Any]:
    existing_today = existing_today or {}
    same_date = existing_today.get("date") == current.get("date")
    tag_library = _payload_tag_library(
        current,
        existing_today.get("tag_library") or [],
    )
    personal_tag_library = _payload_personal_tag_library(
        current,
        existing_today.get("personal_tag_library") or [],
    )
    items = _merge_payload_items(
        existing_today.get("items", []) if same_date else [],
        current.get("items", []),
        tag_library=tag_library,
    )
    thresholds = current.get("thresholds") or existing_today.get("thresholds") or {}
    featured_items, daily_push_items, personal_items = _payload_item_collections(
        items,
        thresholds=thresholds,
    )
    base = dict(current)
    for transient_key in (
        "history",
        "history_total_items",
        "today_items",
        "today_total_items",
        "runs",
    ):
        base.pop(transient_key, None)

    return {
        **base,
        "items": items,
        "today_items": items,
        "today_total_items": len(items),
        "featured_items": featured_items,
        "daily_push_items": daily_push_items,
        "personal_items": personal_items,
        "history_total_items": 0,
        "total_fetched": (int(existing_today.get("total_fetched") or 0) if same_date else 0)
        + int(current.get("total_fetched") or 0),
        "tags": _unique_tags(
            (tag for item in items for tag in item.get("tags", [])),
            tag_library=tag_library,
        ),
        "tag_library": list(tag_library or []),
        "personal_tags": _unique_sorted(
            tag for item in items for tag in item.get("personal_tags", [])
        ),
        "personal_tag_library": list(personal_tag_library or []),
        "sources": _unique_sorted(str(item.get("source")) for item in items),
        "channels": _unique_sorted(str(item.get("channel") or item.get("category")) for item in items),
        "categories": _unique_sorted(str(item.get("category")) for item in items),
        "today": True,
    }


def _build_history_payload(
    current: dict[str, Any],
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    existing = existing or {}
    by_id: dict[str, dict[str, Any]] = {}
    tag_library = _payload_tag_library(
        current,
        existing.get("tag_library") or [],
    )
    personal_tag_library = _payload_personal_tag_library(
        current,
        existing.get("personal_tag_library") or [],
    )
    for item in existing.get("items", []):
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = _normalize_payload_item(
                item,
                tag_library=tag_library,
            )
    for item in current.get("items", []):
        if isinstance(item, dict) and item.get("id"):
            item_id = str(item["id"])
            normalized_item = _normalize_payload_item(
                item,
                tag_library=tag_library,
            )
            by_id[item_id] = _merge_payload_personal_tags(
                normalized_item,
                by_id.get(item_id),
            )

    items = _sort_payload_items(by_id.values())[:HISTORY_ITEM_LIMIT]

    thresholds = current.get("thresholds") or existing.get("thresholds") or {}
    featured_items, daily_push_items, personal_items = _payload_item_collections(
        items,
        thresholds=thresholds,
    )

    runs = list(existing.get("runs", []))
    runs.insert(
        0,
        {
            "generated_at": current.get("generated_at"),
            "date": current.get("date"),
            "total_fetched": current.get("total_fetched", 0),
            "items": len(current.get("items", [])),
            "featured": len(current.get("featured_items", [])),
        },
    )

    return {
        "generated_at": current.get("generated_at"),
        "date": current.get("date"),
        "total_fetched": sum(int(run.get("total_fetched") or 0) for run in runs[:HISTORY_RUN_LIMIT]),
        "thresholds": thresholds,
        "items": items,
        "featured_items": featured_items,
        "daily_push_items": daily_push_items,
        "personal_items": personal_items,
        "tags": _unique_tags(
            (tag for item in items for tag in item.get("tags", [])),
            tag_library=tag_library,
        ),
        "tag_library": list(tag_library or []),
        "personal_tags": _unique_sorted(
            tag for item in items for tag in item.get("personal_tags", [])
        ),
        "personal_tag_library": list(personal_tag_library or []),
        "sources": _unique_sorted(str(item.get("source")) for item in items),
        "channels": _unique_sorted(str(item.get("channel") or item.get("category")) for item in items),
        "categories": _unique_sorted(str(item.get("category")) for item in items),
        "runs": runs[:HISTORY_RUN_LIMIT],
        "history": True,
    }


def _build_recent_payload(
    current: dict[str, Any],
    history: dict[str, Any],
    *,
    recent_item_limit: int,
) -> dict[str, Any]:
    history_items = list(history.get("items", []))
    history_by_id = {
        str(item.get("id")): item
        for item in history_items
        if isinstance(item, dict) and item.get("id")
    }
    today_items = [
        _merge_payload_personal_tags(item, history_by_id.get(str(item.get("id"))))
        for item in current.get("items", [])
        if isinstance(item, dict)
    ]
    items = history_items[:recent_item_limit]
    thresholds = current.get("thresholds") or history.get("thresholds") or {}
    featured_items = [
        _merge_payload_personal_tags(item, history_by_id.get(str(item.get("id"))))
        for item in current.get("featured_items", [])
        if isinstance(item, dict)
    ]
    daily_push_items = [
        _merge_payload_personal_tags(item, history_by_id.get(str(item.get("id"))))
        for item in current.get("daily_push_items", [])
        if isinstance(item, dict)
    ]
    personal_items = _personal_payload_items(today_items)
    visible_items = today_items + items + featured_items + daily_push_items + personal_items
    tag_library = _payload_tag_library(
        history,
        _payload_tag_library(current),
    )
    personal_tag_library = _payload_personal_tag_library(
        history,
        _payload_personal_tag_library(current),
    )

    return {
        **current,
        "today_items": today_items,
        "today_total_items": len(today_items),
        "items": items,
        "featured_items": featured_items,
        "daily_push_items": daily_push_items,
        "personal_items": personal_items,
        "tags": _unique_tags(
            (tag for item in visible_items for tag in item.get("tags", [])),
            tag_library=tag_library,
        ),
        "tag_library": tag_library,
        "personal_tags": _unique_sorted(
            tag for item in visible_items for tag in item.get("personal_tags", [])
        ),
        "personal_tag_library": personal_tag_library,
        "sources": _unique_sorted(str(item.get("source")) for item in visible_items),
        "channels": _unique_sorted(str(item.get("channel") or item.get("category")) for item in visible_items),
        "categories": _unique_sorted(str(item.get("category")) for item in visible_items),
        "recent_item_limit": recent_item_limit,
        "history_total_items": len(history.get("items", [])),
    }


def build_site_payload(
    *,
    all_items: list[ContentItem],
    date: str,
    total_fetched: int,
    featured_threshold: float = 7.5,
    daily_push_threshold: float = 8.5,
    daily_push_limit: int = 10,
    homepage_min_score: float = 6.0,
    recent_item_limit: int = RECENT_ITEM_LIMIT,
    tag_library: Iterable[str] | None = None,
    personal_tag_library: Iterable[str] | None = None,
    ai_enabled: bool = True,
) -> dict[str, Any]:
    """Build the JSON payload consumed by the static web UI."""
    serialized = [
        serialize_item(
            item,
            featured_threshold=featured_threshold,
            homepage_min_score=homepage_min_score,
            tag_library=tag_library,
        )
        for item in sorted(all_items, key=_score, reverse=True)
    ]
    featured_items = [
        item for item in serialized if item["score"] >= featured_threshold
    ]
    daily_push_items = _daily_push_payload_items(serialized, threshold=daily_push_threshold)
    personal_items = _personal_payload_items(serialized)

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": date,
        "total_fetched": total_fetched,
        "ai_enabled": ai_enabled,
        "recent_item_limit": recent_item_limit,
        "thresholds": {
            "featured": featured_threshold,
            "daily_push": daily_push_threshold,
            "homepage_min_score": homepage_min_score,
        },
        "items": serialized,
        "featured_items": featured_items,
        "daily_push_items": daily_push_items,
        "personal_items": personal_items,
        "daily_push_limit": daily_push_limit,
        "tags": _unique_tags(
            (tag for item in serialized for tag in item["tags"]),
            tag_library=tag_library,
        ),
        "tag_library": list(tag_library or []),
        "personal_tags": _unique_sorted(
            tag for item in serialized for tag in item.get("personal_tags", [])
        ),
        "personal_tag_library": list(personal_tag_library or []),
        "sources": _unique_sorted(item["source"] for item in serialized),
        "channels": _unique_sorted(item["channel"] for item in serialized),
        "categories": _unique_sorted(item["category"] for item in serialized),
    }


def _normalize_payload_collections(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize legacy payload items and rebuild derived filter collections."""
    normalized = dict(payload)
    tag_library = _payload_tag_library(normalized, normalized.get("tags") or [])
    personal_tag_library = _payload_personal_tag_library(
        normalized,
        normalized.get("personal_tags") or [],
    )
    items = _merge_payload_items(
        normalized.get("items", []),
        [],
        tag_library=tag_library,
    )
    thresholds = normalized.get("thresholds") or {}
    featured_items, daily_push_items, personal_items = _payload_item_collections(
        items,
        thresholds=thresholds,
    )
    normalized["items"] = items
    normalized["featured_items"] = featured_items
    normalized["daily_push_items"] = daily_push_items
    normalized["personal_items"] = personal_items
    if "today_items" in normalized:
        normalized["today_items"] = [
            _normalize_payload_item(item, tag_library=tag_library)
            for item in normalized.get("today_items", [])
            if isinstance(item, dict)
        ]
        normalized["today_total_items"] = len(normalized["today_items"])
    normalized["tags"] = _unique_tags(
        (tag for item in items for tag in item.get("tags", [])),
        tag_library=tag_library,
    )
    normalized["tag_library"] = list(tag_library or [])
    normalized["personal_tags"] = _unique_sorted(
        tag for item in items for tag in item.get("personal_tags", [])
    )
    normalized["personal_tag_library"] = list(personal_tag_library or [])
    normalized["sources"] = _unique_sorted(str(item.get("source")) for item in items)
    normalized["channels"] = _unique_sorted(str(item.get("channel") or item.get("category")) for item in items)
    normalized["categories"] = _unique_sorted(str(item.get("category")) for item in items)
    return normalized


def normalize_feed_payload(payload: dict[str, Any]) -> dict[str, Any]:
    """Normalize an in-memory feed payload without writing static files."""
    return _normalize_payload_collections(payload)


def backfill_static_site_taxonomy(output_dir: Path | str) -> int:
    """Rewrite generated site payloads with hub taxonomy compatibility fields.

    This is safe to run repeatedly. It only touches JSON payloads generated by
    the static UI under ``data/site`` and leaves cached media/assets alone.
    """
    root = Path(output_dir)
    candidates = [
        root / "radar-data.json",
        root / "today-data.json",
        root / "history-data.json",
    ]
    history_dir = root / "history"
    if history_dir.exists():
        candidates.extend(sorted(history_dir.glob("*.json")))

    changed = 0
    for path in candidates:
        payload = _read_json_payload(path)
        if not payload:
            continue
        normalized = _normalize_payload_collections(payload)
        if normalized != payload:
            _write_json_payload(path, normalized)
            changed += 1
    return changed


def write_static_site(output_dir: Path, payload: dict[str, Any]) -> Path:
    """Copy static UI files and write today + historical radar data."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for asset in STATIC_DIR.iterdir():
        if asset.suffix in {".html", ".js", ".css"}:
            shutil.copy2(asset, output_dir / asset.name)

    history_dir = output_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    today_dir = output_dir / "today"
    today_dir.mkdir(parents=True, exist_ok=True)
    backfill_static_site_taxonomy(output_dir)

    cache_payload_media(payload, output_dir)
    snapshot_path = today_dir / _history_snapshot_name(payload)
    _write_json_payload(snapshot_path, payload)

    history_path = output_dir / "history-data.json"
    today_path = output_dir / "today-data.json"
    existing_history = _read_json_payload(history_path)
    existing_today = _read_json_payload(today_path)

    history_base = existing_history
    if existing_today and existing_today.get("date") != payload.get("date"):
        archive_snapshot = history_dir / _history_snapshot_name(existing_today)
        _write_json_payload(archive_snapshot, existing_today)
        history_base = _build_history_payload(existing_today, existing_history)

    today_payload = _build_today_payload(payload, existing_today)
    cache_payload_media(today_payload, output_dir)
    _write_json_payload(today_path, today_payload)

    today_item_ids = [
        str(item.get("id"))
        for item in today_payload.get("items", [])
        if isinstance(item, dict) and item.get("id")
    ]
    history_payload = _build_history_payload_from_existing(
        today_payload,
        history_base,
        exclude_item_ids=today_item_ids,
    )
    cache_payload_media(history_payload, output_dir)
    _write_json_payload(history_path, history_payload)

    recent_item_limit = int(payload.get("recent_item_limit") or RECENT_ITEM_LIMIT)
    current_payload = _build_recent_payload(
        today_payload,
        history_payload,
        recent_item_limit=max(recent_item_limit, 1),
    )
    cache_payload_media(current_payload, output_dir)
    data_path = output_dir / "radar-data.json"
    _write_json_payload(data_path, current_payload)
    return data_path


def load_history_item_ids(output_dir: Path) -> set[str]:
    """Return item IDs already published into the static UI history or today file."""
    known_ids: set[str] = set()
    for file_name in ("history-data.json", "today-data.json"):
        payload = _read_json_payload(output_dir / file_name)
        if not payload:
            continue
        known_ids.update(
            str(item["id"])
            for item in payload.get("items", [])
            if isinstance(item, dict) and item.get("id")
        )
    return known_ids
