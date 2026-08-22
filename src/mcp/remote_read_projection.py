"""Pure allowlist projections shared by Remote MCP read services."""

from __future__ import annotations

from copy import deepcopy
from collections.abc import Iterable
from typing import Any

from ..services.content_presentation import complete_content_presentation


class RemoteMCPNotFound(LookupError):
    """A requested object does not exist inside the caller's own scope."""


_PRESENTATION_FIELDS: dict[str, tuple[str, ...]] = {
    "source": ("id", "catalog_type", "platform", "name"),
    "author": ("name", "kind"),
    "timing": ("published_at", "fetched_at"),
    "links": ("canonical_url", "source_url"),
    "content": (
        "title",
        "title_origin",
        "excerpt",
        "content_kind",
        "excerpt_truncated",
    ),
    "taxonomy": (
        "channel",
        "configured_topics",
        "inferred_topics",
        "topics",
        "entities",
    ),
    "engagement": (
        "native_score",
        "likes",
        "comments",
        "reposts",
        "shares",
        "upvote_ratio",
    ),
    "analysis": (
        "status",
        "score",
        "signal_strength",
        "signal_type",
        "summary_zh",
    ),
}
_USER_STATE_FIELDS = (
    "is_read",
    "is_saved",
    "is_later",
    "read_at",
    "saved_at",
    "later_at",
)
_JOB_RESULT_FIELDS = (
    "fetched_count",
    "item_count",
    "snapshot_id",
    "run_status",
    "partial",
    "issue_count",
)


def _pick(mapping: Any, fields: Iterable[str]) -> dict[str, Any]:
    if not isinstance(mapping, dict):
        return {}
    return {key: deepcopy(mapping[key]) for key in fields if key in mapping}


def safe_presentation(item: dict[str, Any], *, version: int = 1) -> dict[str, Any]:
    presentation = complete_content_presentation(item)
    return {
        "version": version,
        **{
            section: _pick(presentation.get(section), fields)
            for section, fields in _PRESENTATION_FIELDS.items()
        },
    }


def safe_state(item: dict[str, Any]) -> dict[str, Any]:
    return _pick(item.get("user_state"), _USER_STATE_FIELDS)


def safe_feed_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": str(item.get("id") or ""),
        "presentation": safe_presentation(item),
        "user_state": safe_state(item),
    }


def safe_job_result_summary(job: dict[str, Any]) -> dict[str, Any]:
    """Project the shared fixed allowlist from one internal job row."""
    return _pick(job.get("result_json"), _JOB_RESULT_FIELDS)


def page(items: list[dict[str, Any]], *, limit: int, offset: int) -> dict[str, Any]:
    selected = items[offset : offset + limit]
    return {
        "items": selected,
        "page": {
            "limit": limit,
            "offset": offset,
            "returned": len(selected),
            "total": len(items),
            "has_more": offset + len(selected) < len(items),
        },
    }


def validate_pagination(limit: int, offset: int) -> tuple[int, int]:
    if isinstance(limit, bool) or not 1 <= int(limit) <= 50:
        raise ValueError("limit must be between 1 and 50")
    if isinstance(offset, bool) or int(offset) < 0 or int(offset) > 10_000:
        raise ValueError("offset must be between 0 and 10000")
    return int(limit), int(offset)
