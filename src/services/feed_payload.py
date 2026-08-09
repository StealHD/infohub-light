"""Build and normalize Service Feed payloads without filesystem I/O."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Iterable

from ..config_migration import normalize_personal_tags
from ..models import ContentItem
from ..services.canonical_content import INTERNAL_SOURCE_NATIVE_TITLE_KEY
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


def serialize_feed_item(
    item: ContentItem,
    *,
    featured_threshold: float,
    homepage_min_score: float = 6.0,
    tag_library: Iterable[str] | None = None,
) -> dict[str, Any]:
    """Serialize a ContentItem into the stable Service Feed wire shape."""
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
        INTERNAL_SOURCE_NATIVE_TITLE_KEY: item.title,
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


def build_feed_payload(
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
    include_internal_storage_fields: bool = False,
) -> dict[str, Any]:
    """Build an in-memory Service Feed payload."""
    serialized = [
        serialize_feed_item(
            item,
            featured_threshold=featured_threshold,
            homepage_min_score=homepage_min_score,
            tag_library=tag_library,
        )
        for item in sorted(all_items, key=_score, reverse=True)
    ]
    if not include_internal_storage_fields:
        for item in serialized:
            item.pop(INTERNAL_SOURCE_NATIVE_TITLE_KEY, None)
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
