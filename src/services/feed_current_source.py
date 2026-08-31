"""Apply current catalog-owned source presentation to stored Feed items."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any
from urllib.parse import urlparse

from .media_cache import MediaCacheService

if TYPE_CHECKING:
    from ..storage.service_store import ServiceStore


def _is_youtube_item(item: dict[str, Any], source: dict[str, Any]) -> bool:
    if str(source.get("platform") or "").casefold() == "youtube":
        return True
    presentation = item.get("presentation")
    links = presentation.get("links") if isinstance(presentation, dict) else {}
    url = str((links or {}).get("canonical_url") or item.get("url") or "")
    try:
        host = (urlparse(url).hostname or "").casefold()
    except ValueError:
        return False
    return host in {
        "youtu.be",
        "youtube.com",
        "www.youtube.com",
    }


def apply_current_feed_sources(
    store: ServiceStore,
    *,
    workspace_id: str,
    items: list[dict[str, Any]],
) -> None:
    """Refresh avatars and repair YouTube names from the current catalog."""

    item_sources: list[tuple[dict[str, Any], dict[str, Any], str]] = []
    source_ids: set[str] = set()
    for item in items:
        presentation = item.get("presentation")
        source = presentation.get("source") if isinstance(presentation, dict) else None
        if not isinstance(source, dict):
            continue
        source_id = str(source.get("id") or item.get("source_id") or "").strip()
        if not source_id:
            source["avatar_url"] = ""
            continue
        source_ids.add(source_id)
        item_sources.append((item, source, source_id))

    placeholders = ",".join("?" for _ in source_ids)
    names = {
        str(row["id"]): str(row["display_name"] or "")
        for row in (
            store.connect().execute(
                f"SELECT id, display_name FROM source_catalog WHERE workspace_id = ? AND id IN ({placeholders})",
                (workspace_id, *sorted(source_ids)),
            ).fetchall()
            if source_ids
            else []
        )
    }
    urls = MediaCacheService(store, data_dir=store.data_dir).avatar_urls_for_sources(
        workspace_id=workspace_id,
        source_ids=source_ids,
    )
    for item, source, source_id in item_sources:
        source["avatar_url"] = urls.get(source_id, "")
        if _is_youtube_item(item, source) and names.get(source_id):
            source["name"] = names[source_id]
            item["source"] = names[source_id]
