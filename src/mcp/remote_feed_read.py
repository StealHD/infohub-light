"""User-scoped Feed and item reads for Remote MCP."""

from __future__ import annotations

from typing import Any

from ..services.feed_read import FeedReadService
from ..services.user_content_store import MAX_CAPTURED_BODY_CHARS, UserContentStore
from ..storage.service_store import ServiceStore
from .remote_read_projection import (
    RemoteMCPNotFound,
    page,
    safe_feed_item,
    safe_presentation,
    safe_state,
    validate_pagination,
)


class RemoteMCPFeedReadService:
    def __init__(self, store: ServiceStore) -> None:
        self.feed_reader = FeedReadService(store)
        self.user_content = UserContentStore(store)

    def get_my_feed(
        self,
        *,
        workspace_id: str,
        user_id: str,
        collection: str = "latest",
        limit: int = 20,
        offset: int = 0,
        hide_ignored: bool = True,
        unread_first: bool = True,
    ) -> dict[str, Any]:
        limit, offset = validate_pagination(limit, offset)
        if collection not in {"latest", "history", "saved", "later"}:
            raise ValueError("collection must be latest, history, saved, or later")
        latest = self.feed_reader.latest_feed(
            workspace_id=workspace_id,
            user_id=user_id,
            hide_dismissed=False,
        )
        history = self.feed_reader.history_feed(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if collection == "latest":
            raw_items = latest.get("items", [])
        elif collection == "history":
            raw_items = history.get("items", [])
        elif collection == "saved":
            raw_items = self.user_content.saved_items(
                workspace_id=workspace_id,
                user_id=user_id,
                limit=max(200, offset + limit),
                offset=0,
            ).get("items", [])
        else:
            raw_items = [*latest.get("items", []), *history.get("items", [])]

        unique: list[dict[str, Any]] = []
        seen: set[str] = set()
        for candidate in raw_items if isinstance(raw_items, list) else []:
            if not isinstance(candidate, dict):
                continue
            article_id = str(candidate.get("id") or "")
            if not article_id or article_id in seen:
                continue
            seen.add(article_id)
            state = candidate.get("user_state")
            state = state if isinstance(state, dict) else {}
            if hide_ignored and bool(state.get("dismissed")):
                continue
            if collection == "saved" and not bool(state.get("is_saved")):
                continue
            if collection == "later" and not bool(state.get("is_later")):
                continue
            unique.append(candidate)
        if unread_first:
            unique.sort(
                key=lambda item: 1
                if bool((item.get("user_state") or {}).get("is_read"))
                else 0
            )
        safe_items = [safe_feed_item(item) for item in unique]
        return {"collection": collection, **page(safe_items, limit=limit, offset=offset)}

    def get_item(
        self,
        *,
        workspace_id: str,
        user_id: str,
        article_id: str,
        body_offset: int = 0,
        max_body_chars: int = 4000,
    ) -> dict[str, Any]:
        if (
            isinstance(body_offset, bool)
            or not 0 <= int(body_offset) <= MAX_CAPTURED_BODY_CHARS
        ):
            raise ValueError(
                f"body_offset must be between 0 and {MAX_CAPTURED_BODY_CHARS}"
            )
        if isinstance(max_body_chars, bool) or not 1 <= int(max_body_chars) <= 8000:
            raise ValueError("max_body_chars must be between 1 and 8000")
        item = self.user_content.detail_item(
            workspace_id=workspace_id,
            user_id=user_id,
            article_id=str(article_id),
        )
        if item is None:
            raise RemoteMCPNotFound("not_found")
        presentation = safe_presentation(item, version=2)
        original_content = (item.get("presentation") or {}).get("content") or {}
        body = str(original_content.get("body_text") or "")
        offset = min(int(body_offset), len(body))
        limit = int(max_body_chars)
        body_text = body[offset : offset + limit]
        body_end = offset + len(body_text)
        body_has_more = body_end < len(body)
        content = presentation["content"]
        content.update(
            {
                "body_text": body_text,
                "body_truncated": bool(original_content.get("body_truncated"))
                or body_has_more,
                "body_completeness": str(
                    original_content.get("body_completeness") or "excerpt_only"
                ),
                "body_offset": offset,
                "body_end": body_end,
                "body_total_chars": len(body),
                "body_has_more": body_has_more,
                "next_body_offset": body_end if body_has_more else None,
            }
        )
        return {
            "article_id": str(item.get("id") or article_id),
            "presentation": presentation,
            "user_state": safe_state(item),
        }
