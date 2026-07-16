"""Stable user-scoped content index for saved lists and item details."""

from __future__ import annotations

import json
import html
import re
import uuid
from copy import deepcopy
from typing import Any

from ..storage.service_store import ServiceStore
from ..models import ContentItem
from .content_presentation import complete_content_presentation
from .user_item_state import UserItemStateStore
from .media_cache import MediaCacheService
from ..ai.analysis_cache import AnalysisCache


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


def _legacy_body(item: dict[str, Any]) -> tuple[str, bool, str]:
    presentation = item.get("presentation")
    content = presentation.get("content") if isinstance(presentation, dict) else None
    if isinstance(content, dict):
        body = str(content.get("body_text") or "").strip()
        if body:
            return (
                body,
                bool(content.get("body_truncated")),
                str(content.get("body_completeness") or "captured"),
            )
        excerpt = str(content.get("excerpt") or "").strip()
        if excerpt:
            return excerpt, bool(content.get("excerpt_truncated")), "excerpt_only"
    excerpt = str(item.get("excerpt") or item.get("summary_zh") or "").strip()
    return excerpt, False, "excerpt_only"


def service_public_item(value: dict[str, Any]) -> dict[str, Any]:
    """Strip upstream media locations before an item enters user-visible storage."""

    item = deepcopy(value)
    item.pop("remote_image_url", None)
    item.pop("remote_media_urls", None)
    image_url = str(item.get("image_url") or "")
    item["image_url"] = image_url if image_url.startswith("/api/media/") else ""
    media_urls = item.get("media_urls")
    item["media_urls"] = [
        str(url)
        for url in (media_urls if isinstance(media_urls, list) else [])
        if str(url).startswith("/api/media/")
    ]
    presentation = item.get("presentation")
    if isinstance(presentation, dict):
        source = presentation.get("source")
        if isinstance(source, dict) and source.get("avatar_url"):
            avatar_url = str(source["avatar_url"])
            if not avatar_url.startswith("/api/media/"):
                source.pop("avatar_url", None)
        media = presentation.get("media")
        if isinstance(media, dict):
            images = media.get("images")
            public_images: list[dict[str, Any]] = []
            for image in images if isinstance(images, list) else []:
                if not isinstance(image, dict):
                    continue
                url = str(image.get("url") or "")
                if not url.startswith("/api/media/"):
                    continue
                public_images.append(
                    {
                        key: deepcopy(image[key])
                        for key in ("asset_id", "url", "width", "height", "alt")
                        if key in image
                    }
                )
            media["images"] = public_images
            media["count"] = len(public_images)
    return item


_SCRIPT_STYLE_RE = re.compile(
    r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL
)
_BLOCK_BREAK_RE = re.compile(
    r"<(?:br\s*/?|/p|/div|/li|/h[1-6]|/blockquote)>\s*",
    re.IGNORECASE,
)
_TAG_RE = re.compile(r"<[^>]+>")
_SPACE_RE = re.compile(r"[ \t\f\v]+")
_NEWLINES_RE = re.compile(r"\n\s*\n+")
MAX_CAPTURED_BODY_CHARS = 20_000
SOURCE_BODY_NOT_AVAILABLE_REASON = "source_body_not_available"


def clean_captured_body(value: Any, *, limit: int = MAX_CAPTURED_BODY_CHARS) -> tuple[str, bool]:
    """Convert captured HTML/text to bounded plain text with paragraph breaks."""

    text = str(value or "")
    text = _SCRIPT_STYLE_RE.sub("", text)
    text = _BLOCK_BREAK_RE.sub("\n\n", text)
    text = _TAG_RE.sub("", text)
    text = html.unescape(text).replace("\r\n", "\n").replace("\r", "\n")
    lines = [_SPACE_RE.sub(" ", line).strip() for line in text.split("\n")]
    text = _NEWLINES_RE.sub("\n\n", "\n".join(lines)).strip()
    if len(text) <= limit:
        return text, False
    return text[: max(0, limit - 1)].rstrip() + "…", True


def normalize_captured_unresolved_reason(
    value: Any,
    *,
    body_text: Any,
    body_completeness: str,
) -> str | None:
    """Remove stale source-body and blank reason tokens from captured content."""

    if body_completeness != "captured" or not str(body_text or "").strip():
        return None if value is None else str(value)
    raw = str(value or "")
    parts = raw.split(";") if raw else []
    remaining = [
        part
        for part in parts
        if part.strip()
        and part.strip() != SOURCE_BODY_NOT_AVAILABLE_REASON
    ]
    normalized = ";".join(remaining)
    return normalized or None


class UserContentStore:
    """Persist the latest known item payload independently of Feed snapshots."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    def upsert_items(
        self,
        *,
        workspace_id: str,
        user_id: str,
        items: list[dict[str, Any]],
        seen_at: str,
    ) -> None:
        conn = self.store.connect()
        for raw_item in items:
            item = service_public_item(raw_item) if isinstance(raw_item, dict) else raw_item
            if not isinstance(item, dict) or not item.get("id"):
                continue
            article_id = str(item["id"])
            source_id = str(item.get("source_id") or "") or None
            subscription_id = str(item.get("subscription_id") or "") or None
            if source_id and self.store.get_source(source_id) is None:
                source_id = None
            if subscription_id and self.store.connect().execute(
                "SELECT 1 FROM user_subscriptions WHERE id = ?",
                (subscription_id,),
            ).fetchone() is None:
                subscription_id = None
            body_text, body_truncated, body_completeness = _legacy_body(item)
            conn.execute(
                """
                INSERT INTO user_content_items (
                    id, workspace_id, user_id, article_id, source_id,
                    subscription_id, item_json, body_text, body_truncated,
                    body_completeness, analysis_input_hash, first_seen_at,
                    last_seen_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(workspace_id, user_id, article_id) DO UPDATE SET
                    source_id = excluded.source_id,
                    subscription_id = excluded.subscription_id,
                    item_json = excluded.item_json,
                    body_text = excluded.body_text,
                    body_truncated = excluded.body_truncated,
                    body_completeness = excluded.body_completeness,
                    last_seen_at = excluded.last_seen_at,
                    updated_at = excluded.updated_at
                """,
                (
                    _new_id("uci"),
                    workspace_id,
                    user_id,
                    article_id,
                    source_id,
                    subscription_id,
                    _json_dumps(item),
                    body_text,
                    1 if body_truncated else 0,
                    body_completeness
                    if body_completeness in {"captured", "excerpt_only"}
                    else "excerpt_only",
                    "",
                    seen_at,
                    seen_at,
                    seen_at,
                    seen_at,
                ),
            )
            if body_completeness == "captured" and body_text:
                row = conn.execute(
                    """
                    SELECT unresolved_reason FROM user_content_items
                    WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                    """,
                    (workspace_id, user_id, article_id),
                ).fetchone()
                if row is not None:
                    unresolved_reason = normalize_captured_unresolved_reason(
                        row["unresolved_reason"],
                        body_text=body_text,
                        body_completeness="captured",
                    )
                    conn.execute(
                        """
                        UPDATE user_content_items SET unresolved_reason = ?
                        WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                        """,
                        (
                            unresolved_reason,
                            workspace_id,
                            user_id,
                            article_id,
                        ),
                    )

    def get_item(
        self,
        *,
        workspace_id: str,
        user_id: str,
        article_id: str,
    ) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            """
            SELECT * FROM user_content_items
            WHERE workspace_id = ? AND user_id = ? AND article_id = ?
            """,
            (workspace_id, user_id, article_id),
        ).fetchone()
        return self._stored(row)

    def upsert_captured_items(
        self,
        *,
        workspace_id: str,
        user_id: str,
        items: list[ContentItem],
    ) -> None:
        conn = self.store.connect()
        for item in items:
            analysis_input_hash = AnalysisCache.content_hash(item)
            body_text, body_truncated = clean_captured_body(item.content)
            if not body_text:
                conn.execute(
                    """
                    UPDATE user_content_items
                    SET analysis_input_hash = ?, updated_at = last_seen_at
                    WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                    """,
                    (analysis_input_hash, workspace_id, user_id, item.id),
                )
                continue
            row = conn.execute(
                """
                SELECT unresolved_reason FROM user_content_items
                WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                """,
                (workspace_id, user_id, item.id),
            ).fetchone()
            unresolved_reason = normalize_captured_unresolved_reason(
                row["unresolved_reason"] if row is not None else None,
                body_text=body_text,
                body_completeness="captured",
            )
            conn.execute(
                """
                UPDATE user_content_items
                SET body_text = ?, body_truncated = ?,
                    body_completeness = 'captured', analysis_input_hash = ?,
                    unresolved_reason = ?, updated_at = last_seen_at
                WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                """,
                (
                    body_text,
                    1 if body_truncated else 0,
                    analysis_input_hash,
                    unresolved_reason,
                    workspace_id,
                    user_id,
                    item.id,
                ),
            )

    def saved_items(
        self,
        *,
        workspace_id: str,
        user_id: str,
        limit: int,
        offset: int,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        total_row = conn.execute(
            """
            SELECT COUNT(*) AS total
            FROM user_item_state AS state
            JOIN user_content_items AS content
              ON content.workspace_id = state.workspace_id
             AND content.user_id = state.user_id
             AND content.article_id = state.article_id
            WHERE state.workspace_id = ? AND state.user_id = ? AND state.is_saved = 1
            """,
            (workspace_id, user_id),
        ).fetchone()
        rows = conn.execute(
            """
            SELECT content.*, state.saved_at
            FROM user_item_state AS state
            JOIN user_content_items AS content
              ON content.workspace_id = state.workspace_id
             AND content.user_id = state.user_id
             AND content.article_id = state.article_id
            WHERE state.workspace_id = ? AND state.user_id = ? AND state.is_saved = 1
            ORDER BY state.saved_at DESC, content.article_id DESC
            LIMIT ? OFFSET ?
            """,
            (workspace_id, user_id, limit, offset),
        ).fetchall()
        states = UserItemStateStore(self.store).get_states(
            workspace_id=workspace_id,
            user_id=user_id,
            article_ids=[str(row["article_id"]) for row in rows],
        )
        items: list[dict[str, Any]] = []
        for row in rows:
            item = _json_loads(row["item_json"], {})
            if not isinstance(item, dict):
                continue
            article_id = str(row["article_id"])
            item["user_state"] = states[article_id]
            items.append(item)
        return {
            "schema_version": 1,
            "scope": "user",
            "items": items,
            "item_count": int(total_row["total"] or 0),
            "limit": limit,
            "offset": offset,
        }

    def detail_item(
        self,
        *,
        workspace_id: str,
        user_id: str,
        article_id: str,
    ) -> dict[str, Any] | None:
        stored = self.get_item(
            workspace_id=workspace_id,
            user_id=user_id,
            article_id=article_id,
        )
        if stored is None:
            return None
        item = deepcopy(stored["item"])
        presentation = complete_content_presentation(item)
        source = presentation.get("source")
        if not isinstance(source, dict):
            source = {}
        avatar_url = str(source.get("avatar_url") or "")
        if not avatar_url and stored.get("source_id"):
            avatar = MediaCacheService(
                self.store, data_dir=self.store.data_dir
            ).avatar_for_source(
                workspace_id=workspace_id,
                source_id=str(stored["source_id"]),
            )
            avatar_url = f"/api/media/{avatar['id']}" if avatar else ""
        source["avatar_url"] = avatar_url
        content = presentation.get("content")
        if not isinstance(content, dict):
            content = {}
        content.update(
            {
                "body_text": stored["body_text"],
                "body_truncated": stored["body_truncated"],
                "body_completeness": stored["body_completeness"],
                "unresolved_reason": stored.get("unresolved_reason") or "",
            }
        )
        media_rows = self.store.connect().execute(
            """
            SELECT id, width, height, alt FROM media_assets
            WHERE workspace_id = ? AND user_id = ? AND article_id = ?
              AND asset_kind = 'content_image' AND status = 'ready'
            ORDER BY created_at, id LIMIT 6
            """,
            (workspace_id, user_id, article_id),
        ).fetchall()
        images = [
            {
                "asset_id": str(row["id"]),
                "url": f"/api/media/{row['id']}",
                **({"width": int(row["width"])} if row["width"] else {}),
                **({"height": int(row["height"])} if row["height"] else {}),
                "alt": str(row["alt"] or item.get("title") or "内容图片"),
            }
            for row in media_rows
        ]
        presentation.update(
            {
                "version": 2,
                "source": source,
                "content": content,
                "media": {"images": images, "count": len(images)},
            }
        )
        item["presentation"] = presentation
        item["user_state"] = UserItemStateStore(self.store).get_state(
            workspace_id=workspace_id,
            user_id=user_id,
            article_id=article_id,
        )
        return item

    @staticmethod
    def _stored(row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        data["item"] = _json_loads(data.pop("item_json", None), {})
        data["body_truncated"] = bool(data["body_truncated"])
        return data
