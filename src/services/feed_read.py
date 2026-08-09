"""Current Service Feed read facade backed only by ServiceStore."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..storage.service_store import ServiceStore
from .content_timeline import DEFAULT_FEED_WINDOW_DAYS, feed_window
from .user_feed_store import UserFeedStore
from .user_content_store import UserContentStore, service_public_item


HISTORY_ITEM_LIMIT = 200
_HISTORY_ITEM_COLLECTION_KEYS = {
    "items",
    "today_items",
    "featured_items",
    "featured_item_ids",
    "daily_push_items",
    "daily_push_item_ids",
    "personal_items",
    "personal_item_ids",
    "item_count",
    "today_total_items",
    "snapshot_id",
    "schema_version",
    "scope",
}
_PUBLIC_ITEM_COLLECTION_KEYS = (
    "items",
    "today_items",
    "featured_items",
    "daily_push_items",
    "personal_items",
)


def _sanitize_public_item_collections(payload: dict[str, Any]) -> dict[str, Any]:
    for key in _PUBLIC_ITEM_COLLECTION_KEYS:
        values = payload.get(key)
        if not isinstance(values, list):
            continue
        payload[key] = [
            service_public_item(value) if isinstance(value, dict) else value
            for value in values
        ]
    return payload


class FeedReadService:
    """Read current per-user Feed data exclusively from ServiceStore."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    def latest_feed(
        self,
        *,
        workspace_id: str,
        user_id: str,
        hide_dismissed: bool = False,
        unread_first: bool = False,
        saved_first: bool = False,
        feed_window_days: int = DEFAULT_FEED_WINDOW_DAYS,
    ) -> dict[str, Any]:
        if self.store is not None and workspace_id and user_id:
            window = feed_window(feed_window_days)
            snapshot = UserFeedStore(self.store).latest_snapshot(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            payload = (
                _sanitize_public_item_collections(deepcopy(snapshot["payload"]))
                if snapshot
                else {
                    "schema_version": 2,
                    "generated_at": "",
                    "ai_enabled": False,
                }
            )
            active_source_rows = self.store.connect().execute(
                """
                SELECT source_id
                FROM user_subscriptions
                WHERE user_id = ? AND enabled = 1
                """,
                (user_id,),
            ).fetchall()
            active_source_ids = {
                str(row["source_id"]) for row in active_source_rows if row["source_id"]
            }
            items = UserContentStore(self.store).feed_items(
                workspace_id=workspace_id,
                user_id=user_id,
                window=window,
                active_source_ids=active_source_ids,
            )
            if hide_dismissed:
                items[:] = [
                    item
                    for item in items
                    if not ((item.get("user_state") or {}).get("dismissed"))
                ]
            if unread_first:
                items.sort(
                    key=lambda item: (
                        1 if (item.get("user_state") or {}).get("is_read") else 0
                    )
                )
            if saved_first:
                items.sort(
                    key=lambda item: (
                        0 if (item.get("user_state") or {}).get("is_saved") else 1
                    )
                )

            collection_ids = {
                key: self._collection_item_ids(payload, key)
                for key in ("featured", "daily_push", "personal")
            }
            if not collection_ids["featured"]:
                collection_ids["featured"] = self._snapshot_featured_ids(payload)
            item_by_id = {str(item["id"]): item for item in items if item.get("id")}
            for key in ("featured", "daily_push", "personal"):
                ids = collection_ids[key]
                payload[f"{key}_items"] = [
                    deepcopy(item_by_id[article_id])
                    for article_id in ids
                    if article_id in item_by_id
                ]
                payload[f"{key}_item_ids"] = [
                    article_id for article_id in ids if article_id in item_by_id
                ]
            payload["items"] = items
            payload["today_items"] = [
                deepcopy(item)
                for item in items
                if item.get("timeline_bucket") == "today"
            ]
            payload["today_total_items"] = len(payload["today_items"])
            payload["item_count"] = len(items)
            payload["scope"] = "user"
            payload["window"] = window.as_dict()
            payload["channels"] = self._stable_item_values(items, "channel")
            payload["topics"] = self._stable_item_values(items, "topics")
            payload["sources"] = self._stable_item_values(items, "source")
            if snapshot:
                payload["snapshot_id"] = snapshot["id"]
            elif not items:
                payload["degraded"] = True
                payload["reason"] = "no_user_snapshot"
            else:
                payload.pop("degraded", None)
                payload.pop("reason", None)
            return payload
        raise ValueError("workspace_id and user_id are required")

    def history_feed(
        self,
        *,
        workspace_id: str | None = None,
        user_id: str | None = None,
        q: str | None = None,
        source_id: str | None = None,
        limit: int = HISTORY_ITEM_LIMIT,
        offset: int = 0,
        feed_window_days: int = DEFAULT_FEED_WINDOW_DAYS,
    ) -> dict[str, Any]:
        if self.store is not None and workspace_id and user_id:
            window = feed_window(feed_window_days)
            snapshots = UserFeedStore(self.store).recent_snapshots(
                workspace_id=workspace_id,
                user_id=user_id,
                limit=20,
            )
            summaries = [
                {
                    "snapshot_id": snapshot["id"],
                    "generated_at": snapshot["generated_at"],
                    "item_count": snapshot["item_count"],
                    "job_id": snapshot["job_id"],
                }
                for snapshot in snapshots
            ]
            latest_payload = snapshots[0].get("payload") if snapshots else {}
            if not isinstance(latest_payload, dict):
                latest_payload = {}
            payload = {
                key: deepcopy(value)
                for key, value in latest_payload.items()
                if key not in _HISTORY_ITEM_COLLECTION_KEYS
            }
            featured_ids: set[str] = set()
            for snapshot in snapshots:
                historical_payload = snapshot.get("payload")
                if not isinstance(historical_payload, dict):
                    continue
                featured_ids.update(self._snapshot_featured_ids(historical_payload))

            result = UserContentStore(self.store).history_items(
                workspace_id=workspace_id,
                user_id=user_id,
                window=window,
                q=q,
                source_id=source_id,
                limit=limit,
                offset=offset,
            )
            items = result["items"]

            filter_collections = {
                "sources": self._stable_item_values(items, "source"),
                "channels": self._stable_item_values(items, "channel"),
                "categories": self._stable_item_values(items, "category"),
                "tags": self._stable_item_values(items, "tags"),
                "topics": self._stable_item_values(items, "topics"),
                "personal_tags": self._stable_item_values(items, "personal_tags"),
            }
            if not snapshots and not items:
                filter_collections = {}
            payload.update(
                {
                    "schema_version": 2,
                    "scope": "user",
                    "snapshots": summaries,
                    "items": items,
                    "featured_items": [
                        item for item in items if str(item["id"]) in featured_ids
                    ],
                    "item_count": result["item_count"],
                    "total_count": result["total_count"],
                    "limit": result["limit"],
                    "offset": result["offset"],
                    "has_more": result["has_more"],
                    "window": window.as_dict(),
                    **filter_collections,
                }
            )
            return payload
        raise ValueError("workspace_id and user_id are required")

    def search_feed(
        self,
        *,
        workspace_id: str,
        user_id: str,
        q: str,
        limit: int = 50,
        cursor: str | None = None,
        feed_window_days: int = DEFAULT_FEED_WINDOW_DAYS,
    ) -> dict[str, Any]:
        window = feed_window(feed_window_days)
        result = UserContentStore(self.store).search_items(
            workspace_id=workspace_id,
            user_id=user_id,
            q=q,
            window=window,
            limit=limit,
            cursor=cursor,
        )
        return {
            "schema_version": 1,
            "scope": "user",
            **result,
            "window": window.as_dict(),
        }

    @staticmethod
    def _snapshot_featured_ids(payload: dict[str, Any]) -> set[str]:
        featured_ids: set[str] = set()
        featured_items = payload.get("featured_items")
        if isinstance(featured_items, list):
            for item in featured_items:
                article_id = item.get("id") if isinstance(item, dict) else item
                if article_id:
                    featured_ids.add(str(article_id))
        stored_ids = payload.get("featured_item_ids")
        if isinstance(stored_ids, list):
            featured_ids.update(str(article_id) for article_id in stored_ids if article_id)
        return featured_ids

    @staticmethod
    def _collection_item_ids(payload: dict[str, Any], prefix: str) -> list[str]:
        ordered: list[str] = []
        seen: set[str] = set()
        values = payload.get(f"{prefix}_items")
        if isinstance(values, list):
            for value in values:
                article_id = value.get("id") if isinstance(value, dict) else value
                normalized = str(article_id or "")
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    ordered.append(normalized)
        stored_ids = payload.get(f"{prefix}_item_ids")
        if isinstance(stored_ids, list):
            for article_id in stored_ids:
                normalized = str(article_id or "")
                if normalized and normalized not in seen:
                    seen.add(normalized)
                    ordered.append(normalized)
        return ordered

    @staticmethod
    def _stable_item_values(items: list[dict[str, Any]], key: str) -> list[str]:
        values: list[str] = []
        seen: set[str] = set()
        for item in items:
            stored = item.get(key)
            candidates = stored if isinstance(stored, list) else [stored]
            for candidate in candidates:
                value = str(candidate or "").strip()
                if not value or value in seen:
                    continue
                seen.add(value)
                values.append(value)
        return values
