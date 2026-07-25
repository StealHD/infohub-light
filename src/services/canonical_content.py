"""Canonical URL identity and provenance-preserving Feed merges."""

from __future__ import annotations

from copy import deepcopy
from datetime import datetime, timezone
from typing import Any, Iterable
from urllib.parse import urlsplit


INTERNAL_SOURCE_NATIVE_TITLE_KEY = "_source_native_title"


def canonical_url_key(url: Any) -> str:
    """Normalize URL identity while preserving the complete query string."""

    parsed = urlsplit(str(url or ""))
    hostname = (parsed.hostname or "").lower()
    if hostname.startswith("www."):
        hostname = hostname[4:]
    port = f":{parsed.port}" if parsed.port else ""
    path = parsed.path.rstrip("/")
    query = f"?{parsed.query}" if parsed.query else ""
    return f"{hostname}{port}{path}{query}"


def feed_item_identity(item: dict[str, Any]) -> str:
    url = item.get("url")
    return f"url:{canonical_url_key(url)}" if url else f"id:{item.get('id') or ''}"


def _values(item: dict[str, Any], plural: str, singular: str) -> list[str]:
    values = item.get(plural) if isinstance(item.get(plural), list) else []
    return list(
        dict.fromkeys(
            str(value)
            for value in [*values, item.get(singular)]
            if value
        )
    )


def _published_timestamp(item: dict[str, Any]) -> float:
    value = item.get("published_at") or item.get("fetched_at")
    if not value:
        return 0.0
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return 0.0
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.timestamp()


def _primary_sort_key(item: dict[str, Any]) -> tuple[Any, ...]:
    """Prefer priority, then deterministic source/native identity."""

    source_ids = _values(item, "source_ids", "source_id")
    source_key = source_ids[0] if source_ids else str(item.get("source") or "")
    return (
        -int(item.get("source_priority") or 0),
        source_key,
        str(item.get("id") or ""),
        -_published_timestamp(item),
    )


def merge_feed_items(
    *,
    previous_items: Iterable[dict[str, Any]],
    current_items: Iterable[dict[str, Any]],
    include_previous: bool,
    identity_items: Iterable[dict[str, Any]] | None = None,
) -> list[dict[str, Any]]:
    """Merge Feed dictionaries with current data and latest-Feed stable IDs."""

    previous = [deepcopy(item) for item in previous_items if item.get("id")]
    current = [deepcopy(item) for item in current_items if item.get("id")]
    preferred_ids: dict[str, str] = {}
    for item in identity_items if identity_items is not None else previous:
        if item.get("id"):
            preferred_ids.setdefault(feed_item_identity(item), str(item["id"]))

    groups: dict[str, dict[str, list[dict[str, Any]]]] = {}
    if include_previous:
        for item in previous:
            groups.setdefault(feed_item_identity(item), {"previous": [], "current": []})[
                "previous"
            ].append(item)
    for item in current:
        groups.setdefault(feed_item_identity(item), {"previous": [], "current": []})[
            "current"
        ].append(item)

    merged: list[dict[str, Any]] = []
    for identity, group in groups.items():
        all_items = [*group["previous"], *group["current"]]
        candidates = group["current"] or group["previous"]
        primary = deepcopy(sorted(candidates, key=_primary_sort_key)[0])
        for item in all_items:
            for key, value in item.items():
                if key not in primary or primary[key] in (None, "", [], {}):
                    primary[key] = deepcopy(value)
        for plural, singular in (
            ("source_ids", "source_id"),
            ("subscription_ids", "subscription_id"),
            ("source_keys", "source_key"),
        ):
            values = list(
                dict.fromkeys(
                    value
                    for item in all_items
                    for value in _values(item, plural, singular)
                )
            )
            primary[plural] = values
            if values and not primary.get(singular):
                primary[singular] = values[0]
        primary["source_priority"] = max(
            (int(item.get("source_priority") or 0) for item in all_items),
            default=0,
        )
        if any(item.get("analysis_mode") == "personal_only" for item in all_items):
            primary["analysis_mode"] = "personal_only"
            primary["show_in_personal_feed"] = True
        if identity in preferred_ids:
            primary["id"] = preferred_ids[identity]
        merged.append(primary)
    return merged
