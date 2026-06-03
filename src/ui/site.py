"""Generate the static private AI radar web UI."""

from __future__ import annotations

import json
import shutil
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Iterable

from ..models import ContentItem


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


def serialize_item(
    item: ContentItem,
    *,
    featured_threshold: float,
    homepage_min_score: float = 6.0,
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
    metadata_tags = item.metadata.get("tags") or []
    if not isinstance(metadata_tags, list):
        metadata_tags = []
    tags = _merge_tags(item.ai_tags, metadata_tags)

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
        "tags": tags,
        "category": item.ai_category or "",
        "is_featured": bool(item.ai_is_featured or score >= featured_threshold),
        "show_on_featured_home": score >= featured_threshold and score >= homepage_min_score,
        "summary_zh": str(summary),
        "action_suggestion": item.ai_action_suggestion or "",
    }


def _unique_sorted(values: Iterable[str]) -> list[str]:
    return sorted({value for value in values if value})


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


def _build_history_payload(
    current: dict[str, Any],
    existing: dict[str, Any] | None,
) -> dict[str, Any]:
    existing = existing or {}
    by_id: dict[str, dict[str, Any]] = {}
    for item in existing.get("items", []):
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = item
    for item in current.get("items", []):
        if isinstance(item, dict) and item.get("id"):
            by_id[str(item["id"])] = item

    items = sorted(
        by_id.values(),
        key=lambda item: (
            _parse_dt(str(item.get("published_at") or item.get("fetched_at") or "")),
            float(item.get("score") or 0),
        ),
        reverse=True,
    )[:HISTORY_ITEM_LIMIT]

    thresholds = current.get("thresholds") or existing.get("thresholds") or {}
    featured_threshold = float(thresholds.get("featured", 7.5))
    daily_threshold = float(thresholds.get("daily_push", 8.5))
    daily_limit = int(current.get("daily_push_limit") or 10)
    featured_items = [item for item in items if float(item.get("score") or 0) >= featured_threshold]
    daily_push_items = [
        item for item in items if float(item.get("score") or 0) >= daily_threshold
    ][:daily_limit]

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
        "tags": _unique_sorted(tag for item in items for tag in item.get("tags", [])),
        "sources": _unique_sorted(str(item.get("source")) for item in items),
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
    items = history_items[:recent_item_limit]
    thresholds = current.get("thresholds") or history.get("thresholds") or {}
    featured_threshold = float(thresholds.get("featured", 7.5))
    daily_threshold = float(thresholds.get("daily_push", 8.5))
    daily_limit = int(current.get("daily_push_limit") or history.get("daily_push_limit") or 10)
    featured_items = [
        item for item in history_items if float(item.get("score") or 0) >= featured_threshold
    ][:recent_item_limit]
    daily_push_items = [
        item for item in items if float(item.get("score") or 0) >= daily_threshold
    ][:daily_limit]
    visible_items = items + featured_items + daily_push_items

    return {
        **current,
        "items": items,
        "featured_items": featured_items,
        "daily_push_items": daily_push_items,
        "tags": _unique_sorted(tag for item in visible_items for tag in item.get("tags", [])),
        "sources": _unique_sorted(str(item.get("source")) for item in visible_items),
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
) -> dict[str, Any]:
    """Build the JSON payload consumed by the static web UI."""
    serialized = [
        serialize_item(
            item,
            featured_threshold=featured_threshold,
            homepage_min_score=homepage_min_score,
        )
        for item in sorted(all_items, key=_score, reverse=True)
    ]
    featured_items = [
        item for item in serialized if item["score"] >= featured_threshold
    ]
    daily_push_items = [
        item for item in serialized if item["score"] >= daily_push_threshold
    ][:daily_push_limit]

    return {
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "date": date,
        "total_fetched": total_fetched,
        "recent_item_limit": recent_item_limit,
        "thresholds": {
            "featured": featured_threshold,
            "daily_push": daily_push_threshold,
            "homepage_min_score": homepage_min_score,
        },
        "items": serialized,
        "featured_items": featured_items,
        "daily_push_items": daily_push_items,
        "daily_push_limit": daily_push_limit,
        "tags": _unique_sorted(tag for item in serialized for tag in item["tags"]),
        "sources": _unique_sorted(item["source"] for item in serialized),
        "categories": _unique_sorted(item["category"] for item in serialized),
    }


def write_static_site(output_dir: Path, payload: dict[str, Any]) -> Path:
    """Copy static UI files and write recent + historical radar data."""
    output_dir.mkdir(parents=True, exist_ok=True)
    for asset in ("index.html", "app.js", "styles.css"):
        shutil.copy2(STATIC_DIR / asset, output_dir / asset)

    history_dir = output_dir / "history"
    history_dir.mkdir(parents=True, exist_ok=True)
    snapshot_path = history_dir / _history_snapshot_name(payload)
    snapshot_path.write_text(
        json.dumps(payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    history_path = output_dir / "history-data.json"
    existing_history = None
    if history_path.exists():
        try:
            existing_history = json.loads(history_path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            existing_history = None
    history_payload = _build_history_payload(payload, existing_history)
    history_path.write_text(
        json.dumps(history_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )

    recent_item_limit = int(payload.get("recent_item_limit") or RECENT_ITEM_LIMIT)
    current_payload = _build_recent_payload(
        payload,
        history_payload,
        recent_item_limit=max(recent_item_limit, 1),
    )
    data_path = output_dir / "radar-data.json"
    data_path.write_text(
        json.dumps(current_payload, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    return data_path


def load_history_item_ids(output_dir: Path) -> set[str]:
    """Return item IDs already published into the static UI history."""
    history_path = output_dir / "history-data.json"
    if not history_path.exists():
        return set()
    try:
        history = json.loads(history_path.read_text(encoding="utf-8"))
    except json.JSONDecodeError:
        return set()
    return {
        str(item["id"])
        for item in history.get("items", [])
        if isinstance(item, dict) and item.get("id")
    }
