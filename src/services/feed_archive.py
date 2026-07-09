"""Feed and archive facade services for the service API."""

from __future__ import annotations

import json
from collections import Counter, defaultdict
from copy import deepcopy
from datetime import datetime
from pathlib import Path
from typing import Any

from ..storage.article_store import ArticleStore
from ..storage.service_store import ServiceStore
from .user_item_state import UserItemStateStore
from .user_feed_store import UserFeedStore


class FeedArchiveService:
    """Read static-compatible feed payloads and archive analytics."""

    def __init__(self, data_dir: Path | str, store: ServiceStore | None = None) -> None:
        self.data_dir = Path(data_dir)
        self.site_dir = self.data_dir / "site"
        self.store = store

    def _read_site_json(self, name: str, fallback: dict[str, Any]) -> dict[str, Any]:
        path = self.site_dir / name
        if not path.exists():
            return fallback
        try:
            payload = json.loads(path.read_text(encoding="utf-8"))
        except json.JSONDecodeError:
            return fallback
        return payload if isinstance(payload, dict) else fallback

    def latest_feed(self, *, workspace_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
        if self.store is not None and workspace_id and user_id:
            snapshot = UserFeedStore(self.store).latest_snapshot(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            if snapshot:
                payload = deepcopy(snapshot["payload"])
                payload["scope"] = "user"
                payload["snapshot_id"] = snapshot["id"]
                payload["item_count"] = snapshot["item_count"]
                items = payload.get("items") if isinstance(payload.get("items"), list) else []
                article_ids = [str(item.get("id")) for item in items if isinstance(item, dict) and item.get("id")]
                states = UserItemStateStore(self.store).get_states(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    article_ids=article_ids,
                )
                for item in items:
                    if isinstance(item, dict) and item.get("id"):
                        item["user_state"] = states.get(str(item["id"]))
                return payload
            return {
                "items": [],
                "channels": [],
                "topics": [],
                "generated_at": "",
                "ai_enabled": False,
                "scope": "user",
                "degraded": True,
                "reason": "no_user_snapshot",
            }
        return self._read_site_json(
            "radar-data.json",
            {"items": [], "generated_at": "", "ai_enabled": False},
        )

    def history_feed(self, *, workspace_id: str | None = None, user_id: str | None = None) -> dict[str, Any]:
        if self.store is not None and workspace_id and user_id:
            return {
                "snapshots": UserFeedStore(self.store).snapshot_history(
                    workspace_id=workspace_id,
                    user_id=user_id,
                ),
                "scope": "user",
            }
        return self._read_site_json("history-data.json", {"items": []})

    def article_graph(self) -> dict[str, Any]:
        return self._read_site_json("article-graph.json", {"nodes": [], "edges": []})

    def _articles(self, *, min_score: float = 0.0, limit: int | None = None) -> list[dict[str, Any]]:
        store = ArticleStore(self.data_dir)
        store.initialize()
        try:
            return store.load_articles_light(min_score=min_score, limit=limit)
        finally:
            store.close()

    def _visible_article_ids(self, user_id: str) -> list[str]:
        if self.store is None:
            return []
        return UserFeedStore(self.store).visible_article_ids(user_id=user_id)

    def _latest_user_snapshot_items(self, user_id: str) -> list[dict[str, Any]]:
        if self.store is None:
            return []
        user = self.store.get_user(user_id)
        if not user:
            return []
        snapshot = UserFeedStore(self.store).latest_snapshot(
            workspace_id=user["workspace_id"],
            user_id=user_id,
        )
        if not snapshot:
            return []
        payload = snapshot.get("payload") or {}
        items = payload.get("items") or payload.get("today_items") or []
        return [item for item in items if isinstance(item, dict)]

    def archive_items(
        self,
        *,
        user_id: str | None = None,
        channel: str | None = None,
        topic: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float = 0.0,
        limit: int = 100,
        offset: int = 0,
        sort: str = "published_at",
        order: str = "desc",
    ) -> dict[str, Any] | list[dict[str, Any]]:
        if user_id:
            article_store = ArticleStore(self.data_dir)
            article_store.initialize()
            try:
                result = article_store.query_archive_items(
                    article_ids=self._visible_article_ids(user_id),
                    channel=channel,
                    topic=topic,
                    source=source,
                    date_from=date_from,
                    date_to=date_to,
                    min_score=min_score,
                    limit=limit,
                    offset=offset,
                    sort=sort,
                    order=order,
                )
            finally:
                article_store.close()
            total = int(result["total"])
            return {
                "items": result["items"],
                "page": {
                    "limit": max(int(limit), 1),
                    "offset": max(int(offset), 0),
                    "total": total,
                    "has_more": max(int(offset), 0) + max(int(limit), 1) < total,
                },
                "filters": {
                    "channel": channel,
                    "topic": topic,
                    "source": source,
                    "date_from": date_from,
                    "date_to": date_to,
                    "min_score": min_score,
                    "sort": sort,
                    "order": order,
                },
                "scope": {"user_id": user_id},
            }

        items = self._articles(min_score=min_score, limit=max(limit, 1) * 2)
        filtered = []
        for item in items:
            if channel and item.get("channel") != channel:
                continue
            if topic and topic not in (item.get("topics") or []):
                continue
            if source and item.get("source") != source:
                continue
            filtered.append(item)
            if len(filtered) >= limit:
                break
        return filtered

    def _all_user_archive_items(
        self,
        *,
        user_id: str,
        channel: str | None = None,
        topic: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float = 0.0,
    ) -> list[dict[str, Any]]:
        result = self.archive_items(
            user_id=user_id,
            channel=channel,
            topic=topic,
            source=source,
            date_from=date_from,
            date_to=date_to,
            min_score=min_score,
            limit=5000,
            offset=0,
            sort="published_at",
            order="desc",
        )
        return list(result["items"]) if isinstance(result, dict) else []

    @staticmethod
    def _time_bucket(value: str, bucket: str) -> str:
        if bucket == "none":
            return ""
        if not value:
            return "unknown"
        try:
            parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
        except ValueError:
            return "unknown"
        if bucket == "day":
            return parsed.date().isoformat()
        year, week, _weekday = parsed.isocalendar()
        return f"{year}-W{week:02d}"

    def archive_trends(
        self,
        *,
        group_by: str,
        user_id: str | None = None,
        bucket: str = "none",
    ) -> list[dict[str, Any]]:
        if group_by not in {"channel", "topic", "entity", "source"}:
            raise ValueError("group_by must be channel, topic, entity, or source")
        if bucket not in {"none", "day", "week"}:
            raise ValueError("bucket must be none, day, or week")
        raw_counter: Counter[Any] = Counter()
        source_items = self._all_user_archive_items(user_id=user_id) if user_id else self._articles()
        for item in source_items:
            if group_by == "channel":
                values = [item.get("channel") or "其他"]
            elif group_by == "topic":
                values = item.get("topics") or ["未分类"]
            elif group_by == "entity":
                values = item.get("entities") or ["未识别"]
            else:
                values = [item.get("source") or item.get("source_type") or "unknown"]
            time_bucket = self._time_bucket(str(item.get("published_at") or ""), bucket)
            for value in values:
                if bucket == "none":
                    raw_counter[str(value)] += 1
                else:
                    raw_counter[(time_bucket, str(value))] += 1
        if bucket == "none":
            return [
                {"key": key, "count": count}
                for key, count in sorted(raw_counter.items(), key=lambda row: (-row[1], row[0]))
            ]
        return [
            {"bucket": row_key[0], "key": row_key[1], "count": count}
            for row_key, count in sorted(raw_counter.items(), key=lambda row: (row[0][0], -row[1], row[0][1]))
        ]

    def archive_facets(
        self,
        *,
        user_id: str,
        channel: str | None = None,
        topic: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float = 0.0,
    ) -> dict[str, list[dict[str, Any]]]:
        items = self._all_user_archive_items(
            user_id=user_id,
            channel=channel,
            topic=topic,
            source=source,
            date_from=date_from,
            date_to=date_to,
            min_score=min_score,
        )
        channels: Counter[str] = Counter()
        topics: Counter[str] = Counter()
        sources: Counter[str] = Counter()
        entities: Counter[str] = Counter()
        for item in items:
            channels[str(item.get("channel") or "其他")] += 1
            sources[str(item.get("source") or item.get("source_type") or "unknown")] += 1
            for topic in item.get("topics") or ["未分类"]:
                topics[str(topic)] += 1
            for entity in item.get("entities") or []:
                entities[str(entity)] += 1

        def rows(counter: Counter[str]) -> list[dict[str, Any]]:
            return [
                {"key": key, "count": count}
                for key, count in sorted(counter.items(), key=lambda row: (-row[1], row[0]))
            ]

        return {
            "channels": rows(channels),
            "topics": rows(topics),
            "sources": rows(sources),
            "entities": rows(entities),
        }

    def source_quality(self, *, user_id: str | None = None) -> list[dict[str, Any]]:
        buckets: dict[str, list[dict[str, Any]]] = defaultdict(list)
        source_items = self._all_user_archive_items(user_id=user_id) if user_id else self._articles()
        if user_id and not source_items:
            source_items = self._latest_user_snapshot_items(user_id)
        for item in source_items:
            buckets[str(item.get("source") or item.get("source_type") or "unknown")].append(item)

        results = []
        for source, items in sorted(buckets.items()):
            total = len(items)
            if total == 0:
                continue
            other = sum(1 for item in items if item.get("channel") == "其他")
            empty_topics = sum(1 for item in items if not item.get("topics"))
            thin = sum(1 for item in items if item.get("signal_strength") == "thin")
            strong = sum(1 for item in items if float(item.get("score") or 0) >= 7.5)
            last_seen = max(str(item.get("published_at") or "") for item in items)
            results.append(
                {
                    "source": source,
                    "total_items": total,
                    "hit_rate": strong / total,
                    "other_channel_rate": other / total,
                    "empty_topics_rate": empty_topics / total,
                    "thin_signal_rate": thin / total,
                    "last_seen_at": last_seen,
                }
            )
        return results
