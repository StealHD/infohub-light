"""User-scoped feed snapshots and visible archive item mappings."""

from __future__ import annotations

import json
import uuid
from copy import deepcopy
from datetime import datetime, timezone
from typing import Any

from ..storage.service_store import ServiceStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


class UserFeedStore:
    """Repository for per-user feed snapshots and visible archive boundaries."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    def save_snapshot(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str | None,
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        now = _now_iso()
        snapshot_id = _new_id("ufs")
        normalized_payload = deepcopy(payload)
        items = _list(normalized_payload.get("items")) or _list(normalized_payload.get("today_items"))
        generated_at = str(normalized_payload.get("generated_at") or now)
        normalized_payload["scope"] = "user"
        normalized_payload["snapshot_id"] = snapshot_id
        normalized_payload["generated_at"] = generated_at
        normalized_payload["items"] = items
        normalized_payload["item_count"] = len(items)
        conn = self.store.connect()
        conn.execute(
            """
            INSERT INTO user_feed_snapshots (
                id, workspace_id, user_id, job_id, generated_at,
                item_count, payload_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                snapshot_id,
                workspace_id,
                user_id,
                job_id,
                generated_at,
                len(items),
                _json_dumps(normalized_payload),
                now,
            ),
        )
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            topics = _list(item.get("topics")) or _list(item.get("tags"))
            conn.execute(
                """
                INSERT INTO user_feed_items (
                    id, workspace_id, user_id, snapshot_id, article_id,
                    source, channel, topics_json, score, published_at, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id("ufi"),
                    workspace_id,
                    user_id,
                    snapshot_id,
                    str(item["id"]),
                    str(item.get("source") or item.get("source_type") or ""),
                    str(item.get("channel") or item.get("category") or ""),
                    _json_dumps(topics),
                    _float_or_none(item.get("score")),
                    item.get("published_at"),
                    now,
                ),
            )
        conn.commit()
        return self._snapshot_by_id(snapshot_id) or {
            "id": snapshot_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "job_id": job_id,
            "generated_at": generated_at,
            "item_count": len(items),
            "payload": normalized_payload,
        }

    def latest_snapshot(self, *, workspace_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            """
            SELECT * FROM user_feed_snapshots
            WHERE workspace_id = ? AND user_id = ?
            ORDER BY generated_at DESC, created_at DESC
            LIMIT 1
            """,
            (workspace_id, user_id),
        ).fetchone()
        return self._snapshot(row)

    def snapshot_history(
        self,
        *,
        workspace_id: str,
        user_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self.store.connect().execute(
            """
            SELECT id, generated_at, item_count, job_id
            FROM user_feed_snapshots
            WHERE workspace_id = ? AND user_id = ?
            ORDER BY generated_at DESC, created_at DESC
            LIMIT ?
            """,
            (workspace_id, user_id, max(1, int(limit))),
        ).fetchall()
        return [
            {
                "snapshot_id": row["id"],
                "generated_at": row["generated_at"],
                "item_count": row["item_count"],
                "job_id": row["job_id"],
            }
            for row in rows
        ]

    def visible_article_ids(self, *, user_id: str) -> list[str]:
        rows = self.store.connect().execute(
            """
            SELECT DISTINCT article_id
            FROM user_feed_items
            WHERE user_id = ?
            ORDER BY article_id
            """,
            (user_id,),
        ).fetchall()
        return [str(row["article_id"]) for row in rows]

    def _snapshot_by_id(self, snapshot_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            "SELECT * FROM user_feed_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        return self._snapshot(row)

    @staticmethod
    def _snapshot(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["payload"] = _json_loads(data.pop("payload_json", None), {})
        return data
