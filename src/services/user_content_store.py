"""Stable user-scoped content index for saved lists and item details."""

from __future__ import annotations

import base64
import binascii
import json
import html
import re
import sqlite3
import time
import uuid
from copy import deepcopy
from typing import TYPE_CHECKING, Any

from ..models import ContentItem
from .content_presentation import complete_content_presentation
from .canonical_content import INTERNAL_SOURCE_NATIVE_TITLE_KEY
from .feed_current_source import apply_current_feed_sources
from .user_item_state import UserItemStateStore
from ..ai.analysis_cache import AnalysisCache
from .content_timeline import (
    FeedWindow,
    build_search_text,
    parse_timestamp,
    project_timeline,
    resolve_effective_at,
    timeline_bucket,
)
if TYPE_CHECKING:
    from ..storage.service_store import ServiceStore

class ContentSearchTimeoutError(RuntimeError):
    """Raised when a bounded SQLite content search exceeds its time budget."""


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


def _flatten_search_values(value: Any) -> list[str]:
    if isinstance(value, dict):
        return [
            text
            for nested in value.values()
            for text in _flatten_search_values(nested)
        ]
    if isinstance(value, list):
        return [
            text
            for nested in value
            for text in _flatten_search_values(nested)
        ]
    if value is None or isinstance(value, bool):
        return []
    return [str(value)]


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
    item.pop(INTERNAL_SOURCE_NATIVE_TITLE_KEY, None)
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
            original_count = media.get("count")
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
            try:
                total_image_count = max(
                    0,
                    int(media.get("total_image_count", original_count) or 0),
                )
            except (TypeError, ValueError):
                total_image_count = 0
            media["total_image_count"] = max(total_image_count, len(public_images))
            media["truncated"] = media["total_image_count"] > len(public_images)
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

    def _replace_search_index(self, row: Any) -> None:
        data = dict(row)
        conn = self.store.connect()
        conn.execute(
            "DELETE FROM user_content_search WHERE content_id = ?",
            (str(data["id"]),),
        )
        conn.execute(
            """
            INSERT INTO user_content_search (
                content_id, workspace_id, user_id, article_id,
                effective_at, search_text
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                str(data["id"]),
                str(data["workspace_id"]),
                str(data["user_id"]),
                str(data["article_id"]),
                str(data["effective_at"] or ""),
                str(data["search_text"] or ""),
            ),
        )

    def rebuild_search_index(self) -> int:
        conn = self.store.connect()
        rows = conn.execute(
            """
            SELECT id, workspace_id, user_id, article_id, effective_at, search_text
            FROM user_content_items
            ORDER BY id
            """
        ).fetchall()
        conn.execute("DELETE FROM user_content_search")
        conn.executemany(
            """
            INSERT INTO user_content_search (
                content_id, workspace_id, user_id, article_id,
                effective_at, search_text
            ) VALUES (?, ?, ?, ?, ?, ?)
            """,
            (
                (
                    str(row["id"]),
                    str(row["workspace_id"]),
                    str(row["user_id"]),
                    str(row["article_id"]),
                    str(row["effective_at"] or ""),
                    str(row["search_text"] or ""),
                )
                for row in rows
            ),
        )
        return len(rows)

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
            source_native_title = (
                str(raw_item.get(INTERNAL_SOURCE_NATIVE_TITLE_KEY) or "").strip()
                if isinstance(raw_item, dict)
                else ""
            ) or None
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
            effective_at = resolve_effective_at(item, first_seen_at=seen_at)
            search_text = build_search_text(
                item,
                body_text=body_text,
                source_native_title=source_native_title,
            )
            conn.execute(
                """
                INSERT INTO user_content_items (
                    id, workspace_id, user_id, article_id, source_id,
                    subscription_id, source_native_title, item_json, body_text,
                    body_truncated, body_completeness, analysis_input_hash,
                    effective_at, search_text,
                    first_seen_at, last_seen_at, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(workspace_id, user_id, article_id) DO UPDATE SET
                    source_id = excluded.source_id,
                    subscription_id = excluded.subscription_id,
                    source_native_title = COALESCE(
                        excluded.source_native_title,
                        user_content_items.source_native_title
                    ),
                    item_json = CASE
                        WHEN user_content_items.archived_at IS NULL
                        THEN excluded.item_json
                        ELSE user_content_items.item_json
                    END,
                    body_text = CASE
                        WHEN user_content_items.archived_at IS NULL
                        THEN excluded.body_text
                        ELSE user_content_items.body_text
                    END,
                    body_truncated = CASE
                        WHEN user_content_items.archived_at IS NULL
                        THEN excluded.body_truncated
                        ELSE user_content_items.body_truncated
                    END,
                    body_completeness = CASE
                        WHEN user_content_items.archived_at IS NULL
                        THEN excluded.body_completeness
                        ELSE user_content_items.body_completeness
                    END,
                    effective_at = CASE
                        WHEN user_content_items.effective_at = ''
                        THEN excluded.effective_at
                        ELSE user_content_items.effective_at
                    END,
                    search_text = CASE
                        WHEN user_content_items.archived_at IS NULL
                        THEN excluded.search_text
                        ELSE user_content_items.search_text
                    END,
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
                    source_native_title,
                    _json_dumps(item),
                    body_text,
                    1 if body_truncated else 0,
                    body_completeness
                    if body_completeness in {"captured", "excerpt_only"}
                    else "excerpt_only",
                    "",
                    effective_at,
                    search_text,
                    seen_at,
                    seen_at,
                    seen_at,
                    seen_at,
                ),
            )
            stored_row = conn.execute(
                """
                SELECT id, workspace_id, user_id, article_id, effective_at, search_text
                FROM user_content_items
                WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                """,
                (workspace_id, user_id, article_id),
            ).fetchone()
            if stored_row is not None:
                self._replace_search_index(stored_row)
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

    def update_source_native_titles(
        self,
        *,
        workspace_id: str,
        user_id: str,
        items: list[dict[str, Any]],
    ) -> int:
        """Persist newly proven native titles without rewriting public item data."""

        updated = 0
        conn = self.store.connect()
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            source_native_title = str(
                item.get(INTERNAL_SOURCE_NATIVE_TITLE_KEY) or ""
            ).strip()
            if not source_native_title:
                continue
            cursor = conn.execute(
                """
                UPDATE user_content_items
                SET source_native_title = ?
                WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                  AND (
                    source_native_title IS NULL
                    OR source_native_title != ?
                  )
                """,
                (
                    source_native_title,
                    workspace_id,
                    user_id,
                    str(item["id"]),
                    source_native_title,
                ),
            )
            changed = max(0, int(cursor.rowcount))
            updated += changed
            if changed:
                stored_row = conn.execute(
                    """
                    SELECT * FROM user_content_items
                    WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                    """,
                    (workspace_id, user_id, str(item["id"])),
                ).fetchone()
                if stored_row is not None:
                    stored_item = _json_loads(stored_row["item_json"], {})
                    search_text = build_search_text(
                        stored_item if isinstance(stored_item, dict) else {},
                        body_text=stored_row["body_text"],
                        source_native_title=source_native_title,
                    )
                    conn.execute(
                        "UPDATE user_content_items SET search_text = ? WHERE id = ?",
                        (search_text, stored_row["id"]),
                    )
                    indexed_row = conn.execute(
                        """
                        SELECT id, workspace_id, user_id, article_id,
                               effective_at, search_text
                        FROM user_content_items WHERE id = ?
                        """,
                        (stored_row["id"],),
                    ).fetchone()
                    if indexed_row is not None:
                        self._replace_search_index(indexed_row)
        return updated

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

    def recent_feed_items(
        self,
        *,
        workspace_id: str,
        user_id: str,
        seen_after: str,
        active_source_ids: set[str] | None = None,
        limit: int = 1000,
    ) -> list[dict[str, Any]]:
        """Return bounded recent indexed items for rebuilding a rolling Feed."""

        rows = self.store.connect().execute(
            """
            SELECT * FROM user_content_items
            WHERE workspace_id = ? AND user_id = ? AND last_seen_at >= ?
            ORDER BY last_seen_at DESC, id DESC
            LIMIT ?
            """,
            (workspace_id, user_id, seen_after, max(1, min(int(limit), 1000))),
        ).fetchall()
        items: list[dict[str, Any]] = []
        for row in rows:
            stored = self._stored(row)
            if stored is None:
                continue
            item = stored["item"]
            source_ids = {
                str(value)
                for value in [
                    *(item.get("source_ids") or []),
                    item.get("source_id"),
                ]
                if value
            }
            if active_source_ids is not None and not source_ids & active_source_ids:
                continue
            items.append(item)
        return items

    @staticmethod
    def _item_source_ids(
        item: dict[str, Any],
        *,
        stored_source_id: Any = None,
    ) -> set[str]:
        presentation = item.get("presentation")
        presentation_source = (
            presentation.get("source")
            if isinstance(presentation, dict)
            else None
        )
        candidates: list[Any] = [stored_source_id, item.get("source_id")]
        source_ids = item.get("source_ids")
        if isinstance(source_ids, list):
            candidates.extend(source_ids)
        if isinstance(presentation_source, dict):
            candidates.append(presentation_source.get("id"))
        return {
            str(value).strip()
            for value in candidates
            if str(value or "").strip()
        }

    def _apply_current_source_avatars(
        self,
        *,
        workspace_id: str,
        items: list[dict[str, Any]],
    ) -> None:
        apply_current_feed_sources(
            self.store,
            workspace_id=workspace_id,
            items=items,
        )

    @staticmethod
    def _history_search_text(item: dict[str, Any], row: Any) -> str:
        presentation = item.get("presentation")
        presentation = presentation if isinstance(presentation, dict) else {}
        presentation_source = presentation.get("source")
        presentation_source = (
            presentation_source
            if isinstance(presentation_source, dict)
            else {}
        )
        presentation_author = presentation.get("author")
        presentation_author = (
            presentation_author
            if isinstance(presentation_author, dict)
            else {}
        )
        presentation_content = presentation.get("content")
        presentation_content = (
            presentation_content
            if isinstance(presentation_content, dict)
            else {}
        )
        presentation_taxonomy = presentation.get("taxonomy")
        presentation_taxonomy = (
            presentation_taxonomy
            if isinstance(presentation_taxonomy, dict)
            else {}
        )
        public_fields = [
            item.get("title"),
            item.get("source"),
            item.get("author"),
            item.get("summary_zh"),
            item.get("excerpt"),
            item.get("content"),
            item.get("channel"),
            item.get("category"),
            item.get("topics"),
            item.get("tags"),
            presentation_source.get("name"),
            presentation_source.get("platform"),
            presentation_source.get("catalog_type"),
            presentation_author.get("name"),
            presentation_content.get("title"),
            presentation_content.get("excerpt"),
            presentation_content.get("body_text"),
            presentation_content.get("content_kind"),
            presentation_taxonomy.get("channel"),
            presentation_taxonomy.get("topics"),
            row["body_text"],
            row["source_native_title"],
        ]
        return "\n".join(
            value
            for field in public_fields
            for value in _flatten_search_values(field)
        ).casefold()

    def history_items(
        self,
        *,
        workspace_id: str,
        user_id: str,
        window: FeedWindow | None = None,
        q: str | None = None,
        source_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
    ) -> dict[str, Any]:
        """Query durable user history using the authoritative time boundary."""

        if window is None:
            from .content_timeline import feed_window

            window = feed_window()
        bounded_limit = max(1, min(int(limit), 200))
        bounded_offset = max(0, int(offset))
        normalized_query = str(q or "").strip().casefold()
        rows = self.store.connect().execute(
            """
            SELECT *
            FROM user_content_items
            WHERE workspace_id = ? AND user_id = ?
              AND (
                effective_at = ''
                OR effective_at < ?
              )
            ORDER BY
                CASE WHEN effective_at = '' THEN first_seen_at ELSE effective_at END DESC,
                article_id ASC
            """,
            (workspace_id, user_id, window.feed_start.isoformat()),
        ).fetchall()
        matching: list[tuple[Any, dict[str, Any]]] = []
        for row in rows:
            article_id = str(row["article_id"] or "")
            if not article_id:
                continue
            item = _json_loads(row["item_json"], {})
            if not isinstance(item, dict):
                continue
            effective_at = self._row_effective_at(row, item)
            parsed_effective_at = parse_timestamp(effective_at)
            if parsed_effective_at is None or parsed_effective_at >= window.feed_start:
                continue
            if source_id and source_id not in self._item_source_ids(
                item,
                stored_source_id=row["source_id"],
            ):
                continue
            if normalized_query and normalized_query not in self._history_search_text(
                item,
                row,
            ):
                continue
            matching.append(
                (
                    row,
                    self._project_row(
                        row,
                        item,
                        effective_at=effective_at,
                        window=window,
                    ),
                )
            )

        total_count = len(matching)
        selected = matching[bounded_offset : bounded_offset + bounded_limit]
        states = UserItemStateStore(self.store).get_states(
            workspace_id=workspace_id,
            user_id=user_id,
            article_ids=[str(item["id"]) for _row, item in selected],
        )
        items: list[dict[str, Any]] = []
        for _row, item in selected:
            article_id = str(item["id"])
            item["user_state"] = states[article_id]
            items.append(item)
        self._apply_current_source_avatars(
            workspace_id=workspace_id,
            items=items,
        )
        return {
            "items": items,
            "item_count": len(items),
            "total_count": total_count,
            "limit": bounded_limit,
            "offset": bounded_offset,
            "has_more": bounded_offset + len(items) < total_count,
        }

    def feed_items(
        self,
        *,
        workspace_id: str,
        user_id: str,
        window: FeedWindow,
        active_source_ids: set[str] | None = None,
        limit: int = 2000,
    ) -> list[dict[str, Any]]:
        """Return the current rolling Feed directly from the stable content index."""

        rows = self.store.connect().execute(
            """
            SELECT *
            FROM user_content_items
            WHERE workspace_id = ? AND user_id = ?
              AND (
                effective_at = ''
                OR (
                    effective_at >= ?
                    AND effective_at <= ?
                )
              )
            ORDER BY
                CASE WHEN effective_at = '' THEN first_seen_at ELSE effective_at END DESC,
                article_id ASC
            LIMIT ?
            """,
            (
                workspace_id,
                user_id,
                window.feed_start.isoformat(),
                window.now.isoformat(),
                max(1, min(int(limit), 5000)),
            ),
        ).fetchall()
        projected: list[dict[str, Any]] = []
        for row in rows:
            item = _json_loads(row["item_json"], {})
            if not isinstance(item, dict) or not item.get("id"):
                continue
            effective_at = self._row_effective_at(row, item)
            parsed_effective_at = parse_timestamp(effective_at)
            if (
                parsed_effective_at is None
                or parsed_effective_at < window.feed_start
                or parsed_effective_at > window.now
            ):
                continue
            source_ids = self._item_source_ids(
                item,
                stored_source_id=row["source_id"],
            )
            if (
                active_source_ids is not None
                and source_ids
                and not source_ids & active_source_ids
            ):
                continue
            projected.append(
                self._project_row(
                    row,
                    item,
                    effective_at=effective_at,
                    window=window,
                )
            )
        states = UserItemStateStore(self.store).get_states(
            workspace_id=workspace_id,
            user_id=user_id,
            article_ids=[str(item["id"]) for item in projected],
        )
        for item in projected:
            item["user_state"] = states[str(item["id"])]
        self._apply_current_source_avatars(
            workspace_id=workspace_id,
            items=projected,
        )
        return projected

    def source_item_counts(
        self,
        *,
        workspace_id: str,
        user_id: str,
        window: FeedWindow | None = None,
    ) -> dict[str, dict[str, int]]:
        """Count today, current Feed, and History by complete provenance."""

        if window is None:
            from .content_timeline import feed_window

            window = feed_window()
        today_by_source: dict[str, set[str]] = {}
        feed_by_source: dict[str, set[str]] = {}
        history_by_source: dict[str, set[str]] = {}
        rows = self.store.connect().execute(
            """
            SELECT article_id, source_id, item_json, effective_at, first_seen_at,
                   archived_at, body_text
            FROM user_content_items
            WHERE workspace_id = ? AND user_id = ?
            """,
            (workspace_id, user_id),
        ).fetchall()
        for row in rows:
            article_id = str(row["article_id"] or "")
            if not article_id:
                continue
            item = _json_loads(row["item_json"], {})
            item = item if isinstance(item, dict) else {}
            effective_at = self._row_effective_at(row, item)
            parsed_effective_at = parse_timestamp(effective_at)
            if parsed_effective_at is None or parsed_effective_at > window.now:
                continue
            bucket = timeline_bucket(effective_at, window)
            target = (
                today_by_source
                if bucket == "today"
                else feed_by_source
                if bucket == "feed"
                else history_by_source
            )
            for provenance_id in self._item_source_ids(
                item,
                stored_source_id=row["source_id"],
            ):
                target.setdefault(provenance_id, set()).add(article_id)
                if bucket == "today":
                    feed_by_source.setdefault(provenance_id, set()).add(article_id)

        source_ids = set(today_by_source) | set(feed_by_source) | set(history_by_source)
        return {
            source_id: {
                "today_item_count": len(today_by_source.get(source_id, set())),
                "feed_item_count": len(feed_by_source.get(source_id, set())),
                "current_item_count": len(feed_by_source.get(source_id, set())),
                "history_item_count": len(history_by_source.get(source_id, set())),
            }
            for source_id in source_ids
        }

    @staticmethod
    def _row_effective_at(row: Any, item: dict[str, Any]) -> str:
        effective_at = str(row["effective_at"] or "")
        if effective_at:
            return effective_at
        return resolve_effective_at(item, first_seen_at=row["first_seen_at"])

    @staticmethod
    def _project_row(
        row: Any,
        item: dict[str, Any],
        *,
        effective_at: str,
        window: FeedWindow,
    ) -> dict[str, Any]:
        public_item = service_public_item(item)
        public_item["presentation"] = complete_content_presentation(public_item)
        projected = project_timeline(
            public_item,
            effective_at=effective_at,
            window=window,
        )
        archived = bool(row["archived_at"])
        projected["storage_state"] = "archived" if archived else "online"
        projected["body_available"] = bool(str(row["body_text"] or "").strip())
        return projected

    @staticmethod
    def _encode_search_cursor(effective_at: str, article_id: str) -> str:
        raw = _json_dumps([effective_at, article_id]).encode("utf-8")
        return base64.urlsafe_b64encode(raw).decode("ascii").rstrip("=")

    @staticmethod
    def _decode_search_cursor(value: str | None) -> tuple[str, str] | None:
        if not value:
            return None
        try:
            padded = value + "=" * (-len(value) % 4)
            decoded = json.loads(
                base64.urlsafe_b64decode(padded.encode("ascii")).decode("utf-8")
            )
        except (ValueError, UnicodeError, binascii.Error, json.JSONDecodeError):
            raise ValueError("invalid search cursor") from None
        if (
            not isinstance(decoded, list)
            or len(decoded) != 2
            or not all(isinstance(part, str) and part for part in decoded)
        ):
            raise ValueError("invalid search cursor")
        return decoded[0], decoded[1]

    @staticmethod
    def _fts_query(value: str) -> str:
        return '"' + value.replace('"', '""') + '"'

    def search_items(
        self,
        *,
        workspace_id: str,
        user_id: str,
        q: str,
        window: FeedWindow,
        limit: int = 50,
        cursor: str | None = None,
        timeout_seconds: float = 1.0,
    ) -> dict[str, Any]:
        normalized_query = str(q or "").strip().casefold()
        if not normalized_query:
            return {
                "items": [],
                "item_count": 0,
                "total_count": 0,
                "has_more": False,
                "next_cursor": None,
            }
        bounded_limit = max(1, min(int(limit), 50))
        decoded_cursor = self._decode_search_cursor(cursor)
        conn = self.store.connect()
        deadline = time.monotonic() + max(float(timeout_seconds), 0.05)

        def progress() -> int:
            return 1 if time.monotonic() >= deadline else 0

        conn.set_progress_handler(progress, 1000)
        try:
            params: list[Any]
            cursor_clause = ""
            if decoded_cursor is not None:
                cursor_clause = """
                  AND (
                    content.effective_at < ?
                    OR (
                      content.effective_at = ?
                      AND content.article_id > ?
                    )
                  )
                """
            if len(normalized_query) >= 3:
                match = self._fts_query(normalized_query)
                count_sql = """
                    SELECT COUNT(*) AS total
                    FROM user_content_search
                    WHERE user_content_search MATCH ?
                      AND workspace_id = ?
                      AND user_id = ?
                """
                total_row = conn.execute(
                    count_sql,
                    (match, workspace_id, user_id),
                ).fetchone()
                params = [match, workspace_id, user_id]
                if decoded_cursor is not None:
                    params.extend(
                        (
                            decoded_cursor[0],
                            decoded_cursor[0],
                            decoded_cursor[1],
                        )
                    )
                params.append(bounded_limit + 1)
                rows = conn.execute(
                    f"""
                    SELECT content.*
                    FROM user_content_search
                    JOIN user_content_items AS content
                      ON content.id = user_content_search.content_id
                    WHERE user_content_search MATCH ?
                      AND user_content_search.workspace_id = ?
                      AND user_content_search.user_id = ?
                      {cursor_clause}
                    ORDER BY content.effective_at DESC, content.article_id ASC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
            else:
                escaped = (
                    normalized_query.replace("\\", "\\\\")
                    .replace("%", "\\%")
                    .replace("_", "\\_")
                )
                pattern = f"%{escaped}%"
                total_row = conn.execute(
                    """
                    SELECT COUNT(*) AS total
                    FROM user_content_items
                    WHERE workspace_id = ? AND user_id = ?
                      AND search_text LIKE ? ESCAPE '\\'
                    """,
                    (workspace_id, user_id, pattern),
                ).fetchone()
                params = [workspace_id, user_id, pattern]
                if decoded_cursor is not None:
                    params.extend(
                        (
                            decoded_cursor[0],
                            decoded_cursor[0],
                            decoded_cursor[1],
                        )
                    )
                params.append(bounded_limit + 1)
                rows = conn.execute(
                    f"""
                    SELECT content.*
                    FROM user_content_items AS content
                    WHERE content.workspace_id = ?
                      AND content.user_id = ?
                      AND content.search_text LIKE ? ESCAPE '\\'
                      {cursor_clause}
                    ORDER BY content.effective_at DESC, content.article_id ASC
                    LIMIT ?
                    """,
                    params,
                ).fetchall()
        except sqlite3.OperationalError as exc:
            if "interrupted" in str(exc).lower():
                raise ContentSearchTimeoutError("content search timed out") from exc
            raise
        finally:
            conn.set_progress_handler(None, 0)

        has_more = len(rows) > bounded_limit
        selected = rows[:bounded_limit]
        items: list[dict[str, Any]] = []
        for row in selected:
            item = _json_loads(row["item_json"], {})
            if not isinstance(item, dict) or not item.get("id"):
                continue
            effective_at = self._row_effective_at(row, item)
            items.append(
                self._project_row(
                    row,
                    item,
                    effective_at=effective_at,
                    window=window,
                )
            )
        states = UserItemStateStore(self.store).get_states(
            workspace_id=workspace_id,
            user_id=user_id,
            article_ids=[str(item["id"]) for item in items],
        )
        for item in items:
            item["user_state"] = states[str(item["id"])]
        self._apply_current_source_avatars(
            workspace_id=workspace_id,
            items=items,
        )
        next_cursor = None
        if has_more and items:
            last = items[-1]
            effective_at = str(
                ((last.get("presentation") or {}).get("timing") or {}).get(
                    "effective_at"
                )
                or ""
            )
            next_cursor = self._encode_search_cursor(
                effective_at,
                str(last["id"]),
            )
        return {
            "items": items,
            "item_count": len(items),
            "total_count": int(total_row["total"] or 0),
            "has_more": has_more,
            "next_cursor": next_cursor,
        }

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
            stored_row = conn.execute(
                """
                SELECT * FROM user_content_items
                WHERE workspace_id = ? AND user_id = ? AND article_id = ?
                """,
                (workspace_id, user_id, item.id),
            ).fetchone()
            if stored_row is None:
                continue
            stored_item = _json_loads(stored_row["item_json"], {})
            search_text = build_search_text(
                stored_item if isinstance(stored_item, dict) else {},
                body_text=body_text,
                source_native_title=stored_row["source_native_title"],
            )
            conn.execute(
                "UPDATE user_content_items SET search_text = ? WHERE id = ?",
                (search_text, stored_row["id"]),
            )
            indexed_row = conn.execute(
                """
                SELECT id, workspace_id, user_id, article_id,
                       effective_at, search_text
                FROM user_content_items WHERE id = ?
                """,
                (stored_row["id"],),
            ).fetchone()
            if indexed_row is not None:
                self._replace_search_index(indexed_row)

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
        self._apply_current_source_avatars(
            workspace_id=workspace_id,
            items=items,
        )
        return {
            "schema_version": 1,
            "scope": "user",
            "items": items,
            "item_count": int(total_row["total"] or 0),
            "limit": limit,
            "offset": offset,
        }

    def dismissed_items(
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
            WHERE state.workspace_id = ? AND state.user_id = ?
              AND state.dismissed_at IS NOT NULL
            """,
            (workspace_id, user_id),
        ).fetchone()
        rows = conn.execute(
            """
            SELECT content.*, state.dismissed_at
            FROM user_item_state AS state
            JOIN user_content_items AS content
              ON content.workspace_id = state.workspace_id
             AND content.user_id = state.user_id
             AND content.article_id = state.article_id
            WHERE state.workspace_id = ? AND state.user_id = ?
              AND state.dismissed_at IS NOT NULL
            ORDER BY state.dismissed_at DESC, content.article_id DESC
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
        self._apply_current_source_avatars(
            workspace_id=workspace_id,
            items=items,
        )
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
        item["presentation"] = presentation
        self._apply_current_source_avatars(
            workspace_id=workspace_id,
            items=[item],
        )
        source = presentation.get("source")
        if not isinstance(source, dict):
            source = {}
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
            SELECT id, width, height, alt, checksum FROM media_assets
            WHERE workspace_id = ? AND (user_id = ? OR user_id IS NULL) AND article_id = ?
              AND asset_kind = 'content_image' AND status = 'ready'
            ORDER BY updated_at DESC, created_at DESC, id DESC
            """,
            (workspace_id, user_id, article_id),
        ).fetchall()
        unique_media_rows = []
        seen_media_identities: set[str] = set()
        for row in media_rows:
            identity = str(row["checksum"] or row["id"])
            if identity in seen_media_identities:
                continue
            seen_media_identities.add(identity)
            unique_media_rows.append(row)
        images = [
            {
                "asset_id": str(row["id"]),
                "url": f"/api/media/{row['id']}",
                **({"width": int(row["width"])} if row["width"] else {}),
                **({"height": int(row["height"])} if row["height"] else {}),
                "alt": str(row["alt"] or item.get("title") or "内容图片"),
            }
            for row in unique_media_rows[:6]
        ]
        existing_media = presentation.get("media")
        if not isinstance(existing_media, dict):
            existing_media = {}
        try:
            total_image_count = max(0, int(existing_media.get("total_image_count") or 0))
        except (TypeError, ValueError):
            total_image_count = 0
        unique_image_count = len(unique_media_rows)
        presentation.update(
            {
                "version": 2,
                "source": source,
                "content": content,
                "media": {
                    "images": images,
                    "count": len(images),
                    "total_image_count": max(total_image_count, unique_image_count),
                    "truncated": max(total_image_count, unique_image_count) > len(images),
                },
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
