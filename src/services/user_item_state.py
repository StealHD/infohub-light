"""User-scoped item state storage."""

from __future__ import annotations

import uuid
from datetime import datetime, timezone
from typing import TYPE_CHECKING, Any

if TYPE_CHECKING:
    from ..storage.service_store import ServiceStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _bool(value: Any) -> bool:
    return bool(int(value or 0))


class UserItemStateStore:
    """Repository for per-user read/save/later state."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    def is_visible(self, *, workspace_id: str, user_id: str, article_id: str) -> bool:
        row = self.store.connect().execute(
            """
            SELECT 1 FROM user_content_items
            WHERE workspace_id = ? AND user_id = ? AND article_id = ?
            UNION ALL
            SELECT 1 FROM user_feed_items
            WHERE workspace_id = ? AND user_id = ? AND article_id = ?
            LIMIT 1
            """,
            (workspace_id, user_id, article_id, workspace_id, user_id, article_id),
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
