"""Feed and per-subscription schedule HTTP routes and projections."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel

from .context import ApiContext
from .job_routes import public_job
from .responses import ApiError, ok
from .system_auth import api_context, current_user, require_mutating_member
from ..services.feed_schedule import ALLOWED_INTERVALS, NoEnabledSubscriptionsError
from ..services.source_schedule import (
    SOURCE_ALLOWED_INTERVALS,
    SourceScheduleUnavailableError,
)
from ..services.subscription_mutation import SubscriptionActor
from ..storage.service_store import ServiceStore


class FeedSchedulePatchRequest(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None


class SourceSchedulePatchRequest(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None


def feed_schedule_response(
    user: dict[str, Any],
    context: ApiContext,
    *,
    view: Literal["full", "summary"] = "full",
) -> dict[str, Any]:
    schedule = context.feed_schedules.get_user_schedule(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
    )
    availability = context.runtime_status.availability()
    response = {
        "schema_version": 1,
        "enabled": bool(schedule["enabled"]),
        "interval_minutes": int(schedule["interval_minutes"]),
        "allowed_intervals": list(ALLOWED_INTERVALS),
        "next_run_at": schedule.get("next_run_at"),
        "last_evaluated_at": schedule.get("last_evaluated_at"),
        "last_enqueued_at": schedule.get("last_enqueued_at"),
        "last_skip_reason": schedule.get("last_skip_reason"),
        "worker_status": availability["worker_status"],
    }
    if view == "summary":
        return response
    last_job = context.job_queue.get_job(str(schedule.get("last_job_id") or ""))
    if last_job and (
        last_job.get("workspace_id") != user["workspace_id"]
        or last_job.get("user_id") != user["id"]
    ):
        last_job = None
    active_row = context.store.connect().execute(
        """
        SELECT * FROM fetch_jobs
        WHERE workspace_id = ?
          AND user_id = ?
          AND job_type = 'user_feed_refresh'
          AND status IN ('queued', 'running')
        ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
        LIMIT 1
        """,
        (user["workspace_id"], user["id"]),
    ).fetchone()
    active_job = context.store._job(active_row)
    response.update(
        {
            "last_job": public_job(last_job) if last_job else None,
            "active_job": public_job(active_job) if active_job else None,
        }
    )
    return response


def source_schedule_payload(
    schedule: dict[str, Any],
    *,
    worker_status: str,
    view: Literal["full", "summary"],
    last_job: dict[str, Any] | None = None,
    active_job: dict[str, Any] | None = None,
) -> dict[str, Any]:
    response = {
        "schema_version": 1,
        "subscription_id": str(schedule["subscription_id"]),
        "source_id": schedule["source_id"],
        "enabled": bool(schedule["enabled"]),
        "interval_minutes": int(schedule["interval_minutes"]),
        "allowed_intervals": list(SOURCE_ALLOWED_INTERVALS),
        "next_run_at": schedule.get("next_run_at"),
        "last_evaluated_at": schedule.get("last_evaluated_at"),
        "last_enqueued_at": schedule.get("last_enqueued_at"),
        "last_skip_reason": schedule.get("last_skip_reason"),
        "worker_status": worker_status,
    }
    if view == "full":
        response.update(
            {
                "last_job": public_job(last_job) if last_job else None,
                "active_job": public_job(active_job) if active_job else None,
            }
        )
    return response


def source_schedule_response(
    user: dict[str, Any],
    subscription_id: str,
    context: ApiContext,
) -> dict[str, Any]:
    try:
        schedule = context.source_schedules.get_subscription_schedule(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            subscription_id=subscription_id,
        )
    except LookupError as exc:
        raise ApiError("not_found", "subscription not found", status_code=404) from exc
    last_job = context.job_queue.get_job(str(schedule.get("last_job_id") or ""))
    if last_job and (
        last_job.get("workspace_id") != user["workspace_id"]
        or last_job.get("user_id") != user["id"]
        or last_job.get("subscription_id") != subscription_id
    ):
        last_job = None
    active_row = context.store.connect().execute(
        """
        SELECT * FROM fetch_jobs
        WHERE workspace_id = ?
          AND user_id = ?
          AND subscription_id = ?
          AND job_type = 'source_fetch'
          AND status IN ('queued', 'running')
        ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
        LIMIT 1
        """,
        (user["workspace_id"], user["id"], subscription_id),
    ).fetchone()
    active_job = context.store._job(active_row)
    availability = context.runtime_status.availability()
    return source_schedule_payload(
        schedule,
        worker_status=str(availability["worker_status"]),
        view="full",
        last_job=last_job,
        active_job=active_job,
    )


def bulk_source_schedule_jobs(
    user: dict[str, Any],
    schedules: dict[str, dict[str, Any]],
    store: ServiceStore,
) -> tuple[dict[str, dict[str, Any]], dict[str, dict[str, Any]]]:
    last_job_ids = sorted(
        {
            str(schedule["last_job_id"])
            for schedule in schedules.values()
            if schedule.get("last_job_id")
        }
    )
    jobs_by_id: dict[str, dict[str, Any]] = {}
    if last_job_ids:
        placeholders = ", ".join("?" for _job_id in last_job_ids)
        rows = store.connect().execute(
            f"""
            SELECT *
            FROM fetch_jobs
            WHERE workspace_id = ?
              AND user_id = ?
              AND id IN ({placeholders})
            """,
            [user["workspace_id"], user["id"], *last_job_ids],
        ).fetchall()
        for row in rows:
            job = store._job(row)
            if job is not None:
                jobs_by_id[str(job["id"])] = job

    last_jobs_by_subscription: dict[str, dict[str, Any]] = {}
    for subscription_id, schedule in schedules.items():
        job = jobs_by_id.get(str(schedule.get("last_job_id") or ""))
        if job is not None and str(job.get("subscription_id") or "") == str(
            subscription_id
        ):
            last_jobs_by_subscription[subscription_id] = job

    active_rows = store.connect().execute(
        """
        SELECT *
        FROM fetch_jobs
        WHERE workspace_id = ?
          AND user_id = ?
          AND job_type = 'source_fetch'
          AND status IN ('queued', 'running')
        ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
        """,
        (user["workspace_id"], user["id"]),
    ).fetchall()
    active_jobs_by_subscription: dict[str, dict[str, Any]] = {}
    for row in active_rows:
        job = store._job(row)
        if job is None:
            continue
        subscription_id = str(job.get("subscription_id") or "")
        if subscription_id in schedules:
            active_jobs_by_subscription.setdefault(subscription_id, job)
    return last_jobs_by_subscription, active_jobs_by_subscription


async def feed_schedule_get(
    view: Literal["full", "summary"] = "full",
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    return ok(feed_schedule_response(user, context, view=view))


async def feed_schedule_patch(
    payload: FeedSchedulePatchRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    if payload.enabled is None and payload.interval_minutes is None:
        raise ApiError(
            "invalid_feed_schedule",
            "enabled or interval_minutes is required",
            status_code=400,
        )
    if (
        payload.interval_minutes is not None
        and payload.interval_minutes not in ALLOWED_INTERVALS
    ):
        raise ApiError(
            "invalid_feed_schedule",
            "interval_minutes must be one of "
            + ", ".join(str(value) for value in ALLOWED_INTERVALS),
            status_code=400,
        )
    try:
        context.feed_schedules.update_user_schedule(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            enabled=payload.enabled,
            interval_minutes=payload.interval_minutes,
        )
    except NoEnabledSubscriptionsError as exc:
        raise ApiError(
            exc.code,
            str(exc),
            status_code=409,
            action="Enable at least one subscription and retry.",
        ) from exc
    except ValueError as exc:
        raise ApiError("invalid_feed_schedule", str(exc), status_code=400) from exc
    request.state.operation_changed_fields = sorted(payload.model_fields_set)
    return ok(feed_schedule_response(user, context))


async def subscription_schedule_get(
    subscription_id: str,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    return ok(source_schedule_response(user, subscription_id, context))


async def subscription_schedule_patch(
    subscription_id: str,
    payload: SourceSchedulePatchRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    if payload.enabled is None and payload.interval_minutes is None:
        raise ApiError(
            "invalid_source_schedule",
            "enabled or interval_minutes is required",
            status_code=400,
        )
    if (
        payload.interval_minutes is not None
        and payload.interval_minutes not in SOURCE_ALLOWED_INTERVALS
    ):
        raise ApiError(
            "invalid_source_schedule",
            "interval_minutes must be one of "
            + ", ".join(str(value) for value in SOURCE_ALLOWED_INTERVALS),
            status_code=400,
        )
    try:
        context.subscription_mutations.rest_update_schedule(
            SubscriptionActor.from_user(user),
            subscription_id=subscription_id,
            updates={
                "enabled": payload.enabled,
                "interval_minutes": payload.interval_minutes,
            },
        )
    except LookupError as exc:
        raise ApiError("not_found", "subscription not found", status_code=404) from exc
    except SourceScheduleUnavailableError as exc:
        raise ApiError(
            exc.code,
            str(exc),
            status_code=409,
            action="Enable the subscription and source before enabling its schedule.",
        ) from exc
    request.state.operation_changed_fields = sorted(payload.model_fields_set)
    return ok(source_schedule_response(user, subscription_id, context))


def register_feed_schedule_routes(app: FastAPI) -> None:
    app.add_api_route("/api/me/feed-schedule", feed_schedule_get, methods=["GET"])
    app.add_api_route(
        "/api/me/feed-schedule", feed_schedule_patch, methods=["PATCH"]
    )


def register_subscription_schedule_routes(app: FastAPI) -> None:
    app.add_api_route(
        "/api/me/subscriptions/{subscription_id}/schedule",
        subscription_schedule_get,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/me/subscriptions/{subscription_id}/schedule",
        subscription_schedule_patch,
        methods=["PATCH"],
    )
