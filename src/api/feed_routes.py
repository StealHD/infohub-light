"""Feed read models, item state, dashboard, and protected media routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI
from fastapi.responses import FileResponse
from pydantic import BaseModel

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import (
    api_context,
    current_admin,
    current_user,
    is_admin,
    require_mutating_member,
)
from ..services.user_content_store import ContentSearchTimeoutError


class ItemStatePatchRequest(BaseModel):
    is_read: bool | None = None
    is_saved: bool | None = None
    is_later: bool | None = None
    dismissed: bool | None = None


def _target_user_for_scope(
    requested_user_id: str | None,
    user: dict[str, Any],
    context: ApiContext,
) -> dict[str, Any]:
    if not requested_user_id or requested_user_id == user["id"]:
        return user
    if not is_admin(user):
        raise ApiError(
            "forbidden",
            "current user cannot inspect another user's feed or archive",
            status_code=403,
            action="Use your own user scope or ask an admin.",
        )
    target = context.store.get_user(requested_user_id)
    if target is None or target["workspace_id"] != user["workspace_id"]:
        raise ApiError("not_found", "target user not found", status_code=404)
    return target


def _visible_item_or_404(
    article_id: str,
    user: dict[str, Any],
    context: ApiContext,
) -> None:
    if not context.item_state.is_visible(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        article_id=article_id,
    ):
        raise ApiError("not_found", "item not found", status_code=404)


async def me_item_state(
    article_ids: str = "",
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    ids = [part.strip() for part in str(article_ids or "").split(",") if part.strip()]
    return ok(
        {
            "states": context.item_state.get_states(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                article_ids=ids,
            )
        }
    )


async def me_item_state_update(
    article_id: str,
    payload: ItemStatePatchRequest,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    _visible_item_or_404(article_id, user, context)
    return ok(
        context.item_state.update_state(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            article_id=article_id,
            is_read=payload.is_read,
            is_saved=payload.is_saved,
            is_later=payload.is_later,
            dismissed=payload.dismissed,
        )
    )


async def dashboard_summary(
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    sources = context.store.list_visible_sources(user)
    subscriptions = context.store.list_user_subscriptions(user["id"])
    jobs = context.job_queue.list_jobs(
        workspace_id=user["workspace_id"],
        user_id=None if is_admin(user) else user["id"],
    )
    latest = context.feed_reader.latest_feed(
        workspace_id=user["workspace_id"], user_id=user["id"]
    )
    item_state_counts = context.item_state.count_flags(
        workspace_id=user["workspace_id"], user_id=user["id"]
    )
    runtime = context.runtime_status.summary(
        workspace_id=user["workspace_id"], user_id=user["id"]
    )
    return ok(
        {
            "source_count": len(sources),
            "subscription_count": len(subscriptions),
            "queued_job_count": len(
                [job for job in jobs if job["status"] == "queued"]
            ),
            "running_job_count": len(
                [job for job in jobs if job["status"] == "running"]
            ),
            "failed_job_count": len(
                [job for job in jobs if job["status"] == "failed"]
            ),
            "latest_generated_at": latest.get("generated_at"),
            "item_state_counts": item_state_counts,
            "current_user": context.store.sanitize_user(user),
            "runtime": {
                "worker_status": runtime["worker_status"],
                "oldest_queued_age_seconds": runtime["oldest_queued_age_seconds"],
                "stale_running_count": runtime["stale_running_count"],
            },
        }
    )


async def ops_runtime(
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    return ok(context.runtime_status.summary(workspace_id=user["workspace_id"]))


async def feed_latest(
    user_id: str | None = None,
    hide_dismissed: bool = False,
    unread_first: bool = False,
    saved_first: bool = False,
    view: Literal["compat", "canonical"] = "compat",
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    target = _target_user_for_scope(user_id, user, context)
    payload = context.feed_reader.latest_feed(
        workspace_id=target["workspace_id"],
        user_id=target["id"],
        hide_dismissed=hide_dismissed,
        unread_first=unread_first,
        saved_first=saved_first,
        feed_window_days=context.feed_window_days(),
    )
    if view == "canonical":
        payload.pop("today_items", None)
    return ok(payload)


async def feed_search(
    q: str,
    limit: int = 50,
    cursor: str | None = None,
    submitted: bool = False,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    normalized_q = str(q or "").strip()
    if not normalized_q or len(normalized_q) > 160:
        raise ApiError(
            "invalid_query",
            "q must contain between 1 and 160 characters",
            status_code=400,
        )
    if len(normalized_q) == 1 and not submitted:
        raise ApiError(
            "query_requires_submit",
            "single-character searches must be submitted explicitly",
            status_code=400,
        )
    if limit < 1 or limit > 50:
        raise ApiError(
            "invalid_limit",
            "limit must be between 1 and 50",
            status_code=400,
        )
    try:
        result = context.feed_reader.search_feed(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            q=normalized_q,
            limit=limit,
            cursor=str(cursor or "").strip() or None,
            feed_window_days=context.feed_window_days(),
        )
    except ContentSearchTimeoutError as exc:
        raise ApiError(
            "search_timeout",
            "content search exceeded the one-second budget",
            status_code=503,
            action="Retry the search or use a more specific keyword.",
        ) from exc
    except ValueError as exc:
        raise ApiError("invalid_cursor", str(exc), status_code=400) from exc
    return ok(result)


async def feed_saved(
    limit: int = 200,
    offset: int = 0,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    return ok(
        context.user_content.saved_items(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            limit=max(1, min(int(limit), 200)),
            offset=max(0, int(offset)),
        )
    )


async def feed_ignored(
    limit: int = 200,
    offset: int = 0,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    return ok(
        context.user_content.dismissed_items(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            limit=max(1, min(int(limit), 200)),
            offset=max(0, int(offset)),
        )
    )


async def feed_item_detail(
    article_id: str,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    item = context.user_content.detail_item(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        article_id=article_id,
    )
    if item is None:
        raise ApiError("not_found", "item not found", status_code=404)
    return ok(item)


async def media_asset(
    asset_id: str,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> FileResponse:
    asset = context.media_cache.authorized_asset(
        asset_id=asset_id,
        workspace_id=user["workspace_id"],
        user_id=user["id"],
    )
    if asset is None:
        raise ApiError("not_found", "media not found", status_code=404)
    path = (context.data_path / str(asset["local_path"])).resolve()
    media_root = (context.data_path / "media").resolve()
    if media_root not in path.parents or not path.is_file():
        raise ApiError("not_found", "media not found", status_code=404)
    return FileResponse(
        path,
        media_type=str(asset.get("mime_type") or "application/octet-stream"),
        headers={"Cache-Control": "private, max-age=31536000, immutable"},
    )


async def feed_history(
    user_id: str | None = None,
    q: str | None = None,
    source_id: str | None = None,
    limit: int = 200,
    offset: int = 0,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    target = _target_user_for_scope(user_id, user, context)
    normalized_q = str(q or "").strip()
    if len(normalized_q) > 160:
        raise ApiError(
            "invalid_query",
            "q must be at most 160 characters",
            status_code=400,
        )
    if limit < 1 or limit > 200:
        raise ApiError(
            "invalid_limit",
            "limit must be between 1 and 200",
            status_code=400,
        )
    if offset < 0:
        raise ApiError(
            "invalid_offset",
            "offset must be non-negative",
            status_code=400,
        )
    normalized_source_id = str(source_id or "").strip() or None
    if normalized_source_id:
        visible_source_ids = {
            str(source["id"])
            for source in context.store.list_visible_sources(
                target,
                include_disabled=True,
            )
        }
        if normalized_source_id not in visible_source_ids:
            raise ApiError("not_found", "source not found", status_code=404)
    return ok(
        context.feed_reader.history_feed(
            workspace_id=target["workspace_id"],
            user_id=target["id"],
            q=normalized_q or None,
            source_id=normalized_source_id,
            limit=limit,
            offset=offset,
            feed_window_days=context.feed_window_days(),
        )
    )


def register_item_state_routes(app: FastAPI) -> None:
    app.add_api_route("/api/me/item-state", me_item_state, methods=["GET"])
    app.add_api_route(
        "/api/me/items/{article_id}/state", me_item_state_update, methods=["PATCH"]
    )


def register_dashboard_runtime_routes(app: FastAPI) -> None:
    app.add_api_route("/api/dashboard/summary", dashboard_summary, methods=["GET"])
    app.add_api_route("/api/ops/runtime", ops_runtime, methods=["GET"])


def register_feed_latest_route(app: FastAPI) -> None:
    app.add_api_route("/api/feed/latest", feed_latest, methods=["GET"])


def register_feed_collection_routes(app: FastAPI) -> None:
    app.add_api_route("/api/feed/search", feed_search, methods=["GET"])
    app.add_api_route("/api/feed/saved", feed_saved, methods=["GET"])
    app.add_api_route("/api/feed/ignored", feed_ignored, methods=["GET"])
    app.add_api_route(
        "/api/feed/items/{article_id}", feed_item_detail, methods=["GET"]
    )
    app.add_api_route("/api/media/{asset_id}", media_asset, methods=["GET"])
    app.add_api_route("/api/feed/history", feed_history, methods=["GET"])
