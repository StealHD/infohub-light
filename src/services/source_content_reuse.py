"""Seed a new shared-source subscriber from safe existing content."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..models import ContentItem
from .feed_payload import serialize_feed_item
from .media_cache import MediaCacheService


def _proven_native_title(donor: dict[str, Any]) -> str:
    presentation = donor.get("presentation")
    if not isinstance(presentation, dict):
        return ""
    content = presentation.get("content")
    if not isinstance(content, dict) or content.get("title_origin") != "native":
        return ""
    return str(content.get("title") or "").strip()


def _source_cache_candidates(
    feed_store: Any,
    *,
    workspace_id: str,
    source_id: str,
    limit: int,
) -> list[tuple[dict[str, Any], str, str, dict[str, Any]]]:
    """Load canonical neutral items from retained workspace acquisition snapshots."""

    rows = feed_store.store.connect().execute(
        """
        SELECT items.source_item_id, items.item_json
        FROM source_content_items AS items
        JOIN source_content_snapshots AS snapshots
          ON snapshots.id = items.snapshot_id
        WHERE snapshots.workspace_id = ?
          AND snapshots.source_id = ?
          AND snapshots.isolation_scope = ?
        ORDER BY snapshots.generated_at DESC, snapshots.created_at DESC,
                 items.position, items.id
        LIMIT ?
        """,
        (
            workspace_id,
            source_id,
            f"workspace:{workspace_id}",
            max(limit * 4, limit),
        ),
    ).fetchall()
    candidates: list[tuple[dict[str, Any], str, str, dict[str, Any]]] = []
    for row in rows:
        try:
            item = ContentItem.model_validate_json(str(row["item_json"]))
        except (TypeError, ValueError):
            continue
        title = str(item.title or "").strip()
        article_id = str(item.id or row["source_item_id"] or "").strip()
        if not title or not article_id:
            continue
        donor = serialize_feed_item(item, featured_threshold=8.0)
        candidates.append(
            (
                donor,
                article_id,
                title,
                {
                    "body_text": "",
                    "body_truncated": False,
                    "body_completeness": "excerpt_only",
                    "unresolved_reason": "",
                },
            )
        )
    return candidates


def _stable_content_candidates(
    feed_store: Any,
    *,
    workspace_id: str,
    source_id: str,
    limit: int,
) -> list[tuple[dict[str, Any], str, str, Any]]:
    from .user_feed_store import _json_loads

    rows = feed_store.store.connect().execute(
        """
        SELECT item_json, source_native_title, body_text, body_truncated,
               body_completeness, unresolved_reason, article_id
        FROM user_content_items
        WHERE workspace_id = ? AND source_id = ?
        ORDER BY last_seen_at DESC, first_seen_at DESC, id DESC
        LIMIT ?
        """,
        (workspace_id, source_id, limit),
    ).fetchall()
    candidates: list[tuple[dict[str, Any], str, str, Any]] = []
    for row in rows:
        donor = _json_loads(row["item_json"], {})
        if isinstance(donor, dict):
            title = (
                str(row["source_native_title"] or "").strip()
                or _proven_native_title(donor)
            )
        else:
            title = ""
        if title:
            candidates.append((donor, str(row["article_id"]), title, row))
    return candidates


def reuse_source_content(
    feed_store: Any,
    *,
    workspace_id: str,
    user_id: str,
    source_id: str,
    subscription_id: str,
    limit: int = 200,
    allow_disabled_source: bool = False,
    commit: bool = True,
) -> dict[str, Any]:
    """Seed a subscriber Feed from neutral cache, then stable source rows."""

    from .user_feed_store import (
        _list,
        _neutral_reuse_item,
        _now_iso,
        _reuse_projection,
    )

    source = feed_store.store.get_source(source_id)
    subscription = feed_store.store.get_subscription(subscription_id)
    user = feed_store.store.get_user(user_id)
    if (
        source is None
        or subscription is None
        or user is None
        or source.get("workspace_id") != workspace_id
        or user.get("workspace_id") != workspace_id
        or subscription.get("user_id") != user_id
        or subscription.get("source_id") != source_id
        or not bool(subscription.get("enabled"))
        or (not bool(source.get("enabled")) and not allow_disabled_source)
        or (
            source.get("scope") == "private"
            and source.get("owner_user_id") != user_id
        )
    ):
        return {"reused_count": 0, "snapshot": None}

    bounded_limit = max(1, min(int(limit), 1000))
    projection = _reuse_projection(source=source, subscription=subscription)
    avatar = MediaCacheService(
        feed_store.store,
        data_dir=feed_store.store.data_dir,
    ).avatar_for_source(workspace_id=workspace_id, source_id=source_id)
    source_avatar_url = f"/api/media/{avatar['id']}" if avatar is not None else ""
    reused_at = _now_iso()
    reused: list[dict[str, Any]] = []
    seen_ids: set[str] = set()
    candidates: list[tuple[dict[str, Any], str, str, Any]] = []
    if source.get("scope") != "private":
        candidates.extend(
            _source_cache_candidates(
                feed_store,
                workspace_id=workspace_id,
                source_id=source_id,
                limit=bounded_limit,
            )
        )
    candidates.extend(
        _stable_content_candidates(
            feed_store,
            workspace_id=workspace_id,
            source_id=source_id,
            limit=bounded_limit,
        )
    )
    for donor, article_id, title, row in candidates:
        if article_id in seen_ids:
            continue
        seen_ids.add(article_id)
        reused.append(
            _neutral_reuse_item(
                donor=donor,
                article_id=article_id,
                source_native_title=title,
                row=row,
                projection=projection,
                source_avatar_url=source_avatar_url,
                reused_at=reused_at,
            )
        )
        if len(reused) >= bounded_limit:
            break
    if not reused:
        return {"reused_count": 0, "snapshot": None}

    latest = feed_store.latest_snapshot(workspace_id=workspace_id, user_id=user_id)
    existing_items = _list((latest or {}).get("payload", {}).get("items"))
    merged_by_id: dict[str, dict[str, Any]] = {}
    order: list[str] = []
    for original in [*existing_items, *reused]:
        if not isinstance(original, dict) or not original.get("id"):
            continue
        article_id = str(original["id"])
        if article_id not in merged_by_id:
            merged_by_id[article_id] = deepcopy(original)
            order.append(article_id)
            continue
        current = merged_by_id[article_id]
        for plural, singular, incoming in (
            ("source_ids", "source_id", source_id),
            ("subscription_ids", "subscription_id", subscription_id),
        ):
            values = [
                str(value)
                for value in [
                    *_list(current.get(plural)),
                    current.get(singular),
                    incoming,
                ]
                if value
            ]
            current[plural] = list(dict.fromkeys(values))
            current[singular] = current[plural][0]
    generated_at = _now_iso()
    payload = deepcopy((latest or {}).get("payload") or {})
    payload.update(
        {
            "schema_version": max(2, int(payload.get("schema_version") or 2)),
            "generated_at": generated_at,
            "run_id": f"source-reuse:{source_id}:{user_id}:{generated_at}",
            "run_status": "succeeded",
            "items": [merged_by_id[article_id] for article_id in order],
        }
    )
    snapshot = feed_store.save_snapshot(
        workspace_id=workspace_id,
        user_id=user_id,
        job_id=None,
        payload=payload,
        commit=commit,
    )
    return {"reused_count": len(reused), "snapshot": snapshot}
