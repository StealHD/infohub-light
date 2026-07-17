"""Strictly read-only, user-scoped projections for Remote MCP tools."""

from __future__ import annotations

from copy import deepcopy
from typing import Any, Iterable

from ..services.content_presentation import complete_content_presentation
from ..services.feed_archive import FeedArchiveService
from ..services.job_queue import JobQueue
from ..services.source_health import SourceHealthService
from ..services.user_content_store import UserContentStore
from ..storage.service_store import JOB_STATUSES, ServiceStore


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


def _safe_presentation(item: dict[str, Any], *, version: int = 1) -> dict[str, Any]:
    presentation = complete_content_presentation(item)
    return {
        "version": version,
        **{
            section: _pick(presentation.get(section), fields)
            for section, fields in _PRESENTATION_FIELDS.items()
        },
    }


def _safe_state(item: dict[str, Any]) -> dict[str, Any]:
    return _pick(item.get("user_state"), _USER_STATE_FIELDS)


def _safe_feed_item(item: dict[str, Any]) -> dict[str, Any]:
    return {
        "article_id": str(item.get("id") or ""),
        "presentation": _safe_presentation(item),
        "user_state": _safe_state(item),
    }


def safe_job_result_summary(job: dict[str, Any]) -> dict[str, Any]:
    """Project the shared fixed allowlist from one internal job row."""
    return _pick(job.get("result_json"), _JOB_RESULT_FIELDS)


def _page(items: list[dict[str, Any]], *, limit: int, offset: int) -> dict[str, Any]:
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


class RemoteMCPReadService:
    """Expose only bounded, presentation-safe reads for one authenticated user."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store
        self.feed_archive = FeedArchiveService(store.data_dir, store=store)
        self.user_content = UserContentStore(store)
        self.health = SourceHealthService(store)
        self.jobs = JobQueue(store)

    @staticmethod
    def _pagination(limit: int, offset: int) -> tuple[int, int]:
        if isinstance(limit, bool) or not 1 <= int(limit) <= 50:
            raise ValueError("limit must be between 1 and 50")
        if isinstance(offset, bool) or int(offset) < 0 or int(offset) > 10_000:
            raise ValueError("offset must be between 0 and 10000")
        return int(limit), int(offset)

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
        limit, offset = self._pagination(limit, offset)
        if collection not in {"latest", "history", "saved", "later"}:
            raise ValueError("collection must be latest, history, saved, or later")
        latest = self.feed_archive.latest_feed(
            workspace_id=workspace_id,
            user_id=user_id,
            hide_dismissed=False,
        )
        history = self.feed_archive.history_feed(
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
            raw_items = [
                *latest.get("items", []),
                *history.get("items", []),
            ]

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
        safe_items = [_safe_feed_item(item) for item in unique]
        return {"collection": collection, **_page(safe_items, limit=limit, offset=offset)}

    def get_item(
        self,
        *,
        workspace_id: str,
        user_id: str,
        article_id: str,
        max_body_chars: int = 4000,
    ) -> dict[str, Any]:
        if isinstance(max_body_chars, bool) or not 1 <= int(max_body_chars) <= 8000:
            raise ValueError("max_body_chars must be between 1 and 8000")
        item = self.user_content.detail_item(
            workspace_id=workspace_id,
            user_id=user_id,
            article_id=str(article_id),
        )
        if item is None:
            raise RemoteMCPNotFound("not_found")
        presentation = _safe_presentation(item, version=2)
        original_content = (item.get("presentation") or {}).get("content") or {}
        body = str(original_content.get("body_text") or "")
        limit = int(max_body_chars)
        content = presentation["content"]
        content.update(
            {
                "body_text": body[:limit],
                "body_truncated": bool(original_content.get("body_truncated"))
                or len(body) > limit,
                "body_completeness": str(
                    original_content.get("body_completeness") or "excerpt_only"
                ),
            }
        )
        return {
            "article_id": str(item.get("id") or article_id),
            "presentation": presentation,
            "user_state": _safe_state(item),
        }

    def list_subscriptions(
        self,
        *,
        workspace_id: str,
        user_id: str,
        include_disabled: bool = True,
    ) -> dict[str, Any]:
        records = self.store.list_user_subscriptions_with_sources(
            workspace_id=workspace_id,
            user_id=user_id,
            include_disabled_sources=include_disabled,
        )
        schedule_rows = self.store.connect().execute(
            """
            SELECT subscription_id, enabled, interval_minutes, next_run_at,
                   last_enqueued_at, last_skip_reason
            FROM user_source_schedules
            WHERE workspace_id = ? AND user_id = ?
            """,
            (workspace_id, user_id),
        ).fetchall()
        schedules = {str(row["subscription_id"]): row for row in schedule_rows}
        items: list[dict[str, Any]] = []
        for record in records:
            active = bool(record["subscription_enabled"] and record["source_enabled"])
            if not include_disabled and not active:
                continue
            schedule = schedules.get(str(record["subscription_id"]))
            items.append(
                {
                    "subscription_id": record["subscription_id"],
                    "source_name": record["display_name"],
                    "source_type": record["type"],
                    "channel": record.get("override_channel")
                    or record.get("default_channel")
                    or "",
                    "topics": record.get("override_topics")
                    or record.get("default_topics")
                    or [],
                    "status": "active" if active else "disabled",
                    "analysis_mode": record["analysis_mode"],
                    "priority": int(record["priority"]),
                    "schedule": {
                        "enabled": bool(schedule["enabled"]) if schedule else False,
                        "interval_minutes": int(schedule["interval_minutes"])
                        if schedule
                        else None,
                        "next_run_at": schedule["next_run_at"] if schedule else None,
                        "last_enqueued_at": schedule["last_enqueued_at"]
                        if schedule
                        else None,
                        "last_skip_reason": schedule["last_skip_reason"]
                        if schedule
                        else None,
                    },
                }
            )
        return {"items": items, "count": len(items)}

    def source_health(self, *, workspace_id: str, user_id: str) -> dict[str, Any]:
        return self.health.user_projection(
            workspace_id=workspace_id,
            user_id=user_id,
        )

    @staticmethod
    def _safe_job(job: dict[str, Any]) -> dict[str, Any]:
        error = None
        if job.get("error_code"):
            error = {"code": job.get("error_code")}
        return {
            "id": job["id"],
            "job_type": job["job_type"],
            "status": job["status"],
            "source_id": job.get("source_id"),
            "subscription_id": job.get("subscription_id"),
            "priority": int(job.get("priority") or 0),
            "attempts": int(job.get("attempts") or 0),
            "max_attempts": int(job.get("max_attempts") or 0),
            "next_run_at": job.get("next_run_at"),
            "created_at": job.get("created_at"),
            "started_at": job.get("started_at"),
            "finished_at": job.get("finished_at"),
            "cancelled_at": job.get("cancelled_at"),
            "updated_at": job.get("updated_at"),
            "error": error,
            "result_summary": safe_job_result_summary(job),
        }

    def list_jobs(
        self,
        *,
        workspace_id: str,
        user_id: str,
        status: str | None = None,
        limit: int = 20,
    ) -> dict[str, Any]:
        limit, _ = self._pagination(limit, 0)
        if status is not None and status not in JOB_STATUSES:
            raise ValueError("invalid job status")
        jobs = self.jobs.list_jobs(
            workspace_id=workspace_id,
            user_id=user_id,
            status=status,
            limit=limit,
        )
        return {"items": [self._safe_job(job) for job in jobs], "count": len(jobs)}

    def get_job(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str,
    ) -> dict[str, Any]:
        job = self.jobs.get_job(str(job_id))
        if (
            job is None
            or job.get("workspace_id") != workspace_id
            or job.get("user_id") != user_id
        ):
            raise RemoteMCPNotFound("not_found")
        return self._safe_job(job)
