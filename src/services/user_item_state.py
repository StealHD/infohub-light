"""User-scoped item state and feedback storage."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timezone
from typing import Any

from ..storage.service_store import ServiceStore


ALLOWED_FEEDBACK_TYPES = {
    "more_like_this",
    "less_like_this",
    "not_relevant",
    "wrong_topic",
    "quality_issue",
}


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


def _bool(value: Any) -> bool:
    return bool(int(value or 0))


class UserItemStateStore:
    """Repository for per-user read/save/later state and feedback events."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    def is_visible(self, *, workspace_id: str, user_id: str, article_id: str) -> bool:
        row = self.store.connect().execute(
            """
            SELECT 1
            FROM user_feed_items
            WHERE workspace_id = ? AND user_id = ? AND article_id = ?
            LIMIT 1
            """,
            (workspace_id, user_id, article_id),
        ).fetchone()
        return row is not None

    def get_states(
        self,
        *,
        workspace_id: str,
        user_id: str,
        article_ids: list[str],
    ) -> dict[str, dict[str, Any]]:
        ids = [str(article_id) for article_id in article_ids if str(article_id)]
        if not ids:
            return {}
        placeholders = ", ".join("?" for _ in ids)
        rows = self.store.connect().execute(
            f"""
            SELECT *
            FROM user_item_state
            WHERE workspace_id = ? AND user_id = ? AND article_id IN ({placeholders})
            """,
            (workspace_id, user_id, *ids),
        ).fetchall()
        found = {str(row["article_id"]): self._state(row) for row in rows}
        return {article_id: found.get(article_id, self._default_state(article_id)) for article_id in ids}

    def get_state(self, *, workspace_id: str, user_id: str, article_id: str) -> dict[str, Any]:
        return self.get_states(
            workspace_id=workspace_id,
            user_id=user_id,
            article_ids=[article_id],
        ).get(article_id, self._default_state(article_id))

    def count_flags(self, *, workspace_id: str, user_id: str) -> dict[str, int]:
        row = self.store.connect().execute(
            """
            SELECT
                COALESCE(SUM(CASE WHEN is_read = 1 THEN 1 ELSE 0 END), 0) AS read_count,
                COALESCE(SUM(CASE WHEN is_saved = 1 THEN 1 ELSE 0 END), 0) AS saved_count,
                COALESCE(SUM(CASE WHEN is_later = 1 THEN 1 ELSE 0 END), 0) AS later_count,
                COALESCE(SUM(CASE WHEN dismissed_at IS NOT NULL THEN 1 ELSE 0 END), 0) AS dismissed_count
            FROM user_item_state
            WHERE workspace_id = ? AND user_id = ?
            """,
            (workspace_id, user_id),
        ).fetchone()
        return {
            "read_count": int(row["read_count"] or 0),
            "saved_count": int(row["saved_count"] or 0),
            "later_count": int(row["later_count"] or 0),
            "dismissed_count": int(row["dismissed_count"] or 0),
        }

    def update_state(
        self,
        *,
        workspace_id: str,
        user_id: str,
        article_id: str,
        is_read: bool | None = None,
        is_saved: bool | None = None,
        is_later: bool | None = None,
        dismissed: bool | None = None,
    ) -> dict[str, Any]:
        now = _now_iso()
        current = self._row(workspace_id=workspace_id, user_id=user_id, article_id=article_id)
        state = self._state(current) if current else self._default_state(article_id)
        created_at = current["created_at"] if current else now

        if is_read is not None:
            state["is_read"] = bool(is_read)
            state["read_at"] = now if is_read else None
        if is_saved is not None:
            state["is_saved"] = bool(is_saved)
            state["saved_at"] = now if is_saved else None
        if is_later is not None:
            state["is_later"] = bool(is_later)
            state["later_at"] = now if is_later else None
        if dismissed is not None:
            state["dismissed_at"] = now if dismissed else None
            state["dismissed"] = bool(dismissed)

        if current:
            self.store.connect().execute(
                """
                UPDATE user_item_state
                SET is_read = ?, is_saved = ?, is_later = ?,
                    read_at = ?, saved_at = ?, later_at = ?, dismissed_at = ?, updated_at = ?
                WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                """,
                (
                    1 if state["is_read"] else 0,
                    1 if state["is_saved"] else 0,
                    1 if state["is_later"] else 0,
                    state["read_at"],
                    state["saved_at"],
                    state["later_at"],
                    state["dismissed_at"],
                    now,
                    workspace_id,
                    user_id,
                    article_id,
                ),
            )
        else:
            self.store.connect().execute(
                """
                INSERT INTO user_item_state (
                    id, workspace_id, user_id, article_id,
                    is_read, is_saved, is_later,
                    read_at, saved_at, later_at, dismissed_at,
                    created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id("uis"),
                    workspace_id,
                    user_id,
                    article_id,
                    1 if state["is_read"] else 0,
                    1 if state["is_saved"] else 0,
                    1 if state["is_later"] else 0,
                    state["read_at"],
                    state["saved_at"],
                    state["later_at"],
                    state["dismissed_at"],
                    created_at,
                    now,
                ),
            )
        self.store.connect().commit()
        return self.get_state(workspace_id=workspace_id, user_id=user_id, article_id=article_id)

    def record_feedback(
        self,
        *,
        workspace_id: str,
        user_id: str,
        article_id: str,
        feedback_type: str,
        value: int | None = None,
        reason: str = "",
        metadata: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        feedback_type = str(feedback_type or "").strip()
        if feedback_type not in ALLOWED_FEEDBACK_TYPES:
            raise ValueError(f"feedback_type must be one of {', '.join(sorted(ALLOWED_FEEDBACK_TYPES))}")
        now = _now_iso()
        event_id = _new_id("uif")
        self.store.connect().execute(
            """
            INSERT INTO user_item_feedback (
                id, workspace_id, user_id, article_id,
                feedback_type, value, reason, metadata_json, created_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                event_id,
                workspace_id,
                user_id,
                article_id,
                feedback_type,
                value,
                str(reason or ""),
                _json_dumps(metadata or {}),
                now,
            ),
        )
        self.store.connect().commit()
        return {
            "id": event_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "article_id": article_id,
            "feedback_type": feedback_type,
            "value": value,
            "reason": str(reason or ""),
            "metadata": metadata or {},
            "created_at": now,
        }

    def _row(self, *, workspace_id: str, user_id: str, article_id: str) -> Any:
        return self.store.connect().execute(
            """
            SELECT *
            FROM user_item_state
            WHERE workspace_id = ? AND user_id = ? AND article_id = ?
            """,
            (workspace_id, user_id, article_id),
        ).fetchone()

    @staticmethod
    def _default_state(article_id: str) -> dict[str, Any]:
        return {
            "article_id": article_id,
            "is_read": False,
            "is_saved": False,
            "is_later": False,
            "dismissed": False,
            "read_at": None,
            "saved_at": None,
            "later_at": None,
            "dismissed_at": None,
            "updated_at": None,
        }

    @staticmethod
    def _state(row: Any) -> dict[str, Any]:
        return {
            "article_id": str(row["article_id"]),
            "is_read": _bool(row["is_read"]),
            "is_saved": _bool(row["is_saved"]),
            "is_later": _bool(row["is_later"]),
            "dismissed": bool(row["dismissed_at"]),
            "read_at": row["read_at"],
            "saved_at": row["saved_at"],
            "later_at": row["later_at"],
            "dismissed_at": row["dismissed_at"],
            "updated_at": row["updated_at"],
        }
