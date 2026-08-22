"""Queued-job API routes and compatibility adapters."""

from __future__ import annotations

import os
import re
from typing import Any, Literal

from fastapi import Depends, FastAPI, Query, Request
from pydantic import BaseModel, Field

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import (
    api_context,
    current_user,
    is_admin,
    require_mutating_member,
    visible_source_or_404,
)
from ..services.job_eligibility import JobEligibilityService


_JOB_TYPE_FILTER_RE = re.compile(r"[A-Za-z][A-Za-z0-9_-]{0,63}\Z")
_MAX_JOB_TYPE_FILTERS = 20


class JobCreateRequest(BaseModel):
    source_id: str | None = None
    subscription_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0


def public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Remove worker-internal lease credentials from API responses."""

    return {key: value for key, value in job.items() if key != "claim_token"}


def _bounded_job_type_filters(values: list[str] | None) -> list[str] | None:
    if values is None:
        return None
    if len(values) > _MAX_JOB_TYPE_FILTERS:
        raise ApiError(
            "invalid_request",
            f"at most {_MAX_JOB_TYPE_FILTERS} job_type filters are allowed",
            status_code=400,
        )
    normalized: list[str] = []
    for value in values:
        job_type = str(value).strip()
        if not _JOB_TYPE_FILTER_RE.fullmatch(job_type):
            raise ApiError(
                "invalid_request",
                "job_type filters must be 1 to 64 safe characters",
                status_code=400,
            )
        if job_type not in normalized:
            normalized.append(job_type)
    return normalized


def _compatibility_job_payload(raw_payload: dict[str, Any]) -> JobCreateRequest:
    source_id = str(raw_payload.get("source_id") or "").strip() or None
    subscription_id = str(raw_payload.get("subscription_id") or "").strip() or None
    priority = int(raw_payload.get("priority") or 0)
    payload = {
        key: value
        for key, value in raw_payload.items()
        if key not in {"source_id", "subscription_id", "priority"}
    }
    return JobCreateRequest(
        source_id=source_id,
        subscription_id=subscription_id,
        payload=payload,
        priority=priority,
    )


def _queued_job_response(job: dict[str, Any], message: str) -> dict[str, Any]:
    return {**job, "message": message}


def _job_or_404(
    job_id: str,
    user: dict[str, Any],
    context: ApiContext,
) -> dict[str, Any]:
    job = context.job_queue.get_job(job_id)
    if not job or job["workspace_id"] != user["workspace_id"]:
        raise ApiError("not_found", "job not found", status_code=404)
    if job["user_id"] != user["id"] and not is_admin(user):
        raise ApiError("forbidden", "cannot access another user's job", status_code=403)
    return job


def _create_job(
    payload: JobCreateRequest,
    job_type: str,
    user: dict[str, Any],
    context: ApiContext,
) -> dict[str, Any]:
    require_mutating_member(user)
    store = context.store
    queue = context.job_queue
    quota = context.quota
    if (
        job_type in {"source_test", "source_fetch"}
        and not payload.source_id
        and not is_admin(user)
    ):
        raise ApiError(
            "forbidden",
            "members must run source jobs through a visible catalog source_id",
            status_code=403,
        )
    if payload.source_id:
        visible_source_or_404(store, payload.source_id, user)
    if job_type == "user_feed_refresh":
        refresh_scope = "all" if is_admin(user) else "private"
        refresh_payload = {
            **payload.payload,
            "reason": "manual_service_refresh",
            "refresh_scope": refresh_scope,
        }
        conn = store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            job, created = queue.create_user_feed_refresh_if_absent(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                payload=refresh_payload,
                priority=payload.priority,
                max_attempts=int(os.getenv("HORIZON_JOB_MAX_ATTEMPTS", "3")),
                retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
            )
            if created:
                if not store.has_enabled_user_subscriptions(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                    source_scope=refresh_scope,
                ):
                    raise ApiError(
                        "no_enabled_subscriptions",
                        "no enabled subscriptions are eligible for this refresh",
                        status_code=409,
                        action="Enable an eligible subscription and retry.",
                    )
                quota.ensure_job_allowed(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                )
                quota.record_job_usage(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                    event_type=job_type,
                    commit=False,
                )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        return {**public_job(job), "deduplicated": not created}
    if job_type == "source_fetch" and payload.subscription_id:
        subscription = store.get_subscription(payload.subscription_id)
        if (
            subscription is None
            or subscription["user_id"] != user["id"]
            or subscription["source_id"] != payload.source_id
        ):
            raise ApiError("not_found", "subscription not found", status_code=404)
        conn = store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            job, created = queue.create_source_fetch_if_absent(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                source_id=str(payload.source_id),
                subscription_id=payload.subscription_id,
                payload=payload.payload,
                priority=payload.priority,
                max_attempts=int(os.getenv("HORIZON_JOB_MAX_ATTEMPTS", "3")),
                retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
            )
            if created:
                quota.ensure_job_allowed(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                )
                quota.record_job_usage(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                    event_type=job_type,
                    commit=False,
                )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        return {**public_job(job), "deduplicated": not created}
    quota.ensure_job_allowed(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
    )
    job = queue.create_job(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        source_id=payload.source_id,
        subscription_id=payload.subscription_id,
        job_type=job_type,
        payload=payload.payload,
        priority=payload.priority,
        max_attempts=int(os.getenv("HORIZON_JOB_MAX_ATTEMPTS", "3")),
        retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
    )
    quota.record_job_usage(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        event_type=job_type,
    )
    return public_job(job)


def _mark_queued_job_operation(request: Request, job: dict[str, Any]) -> None:
    request.state.operation_job_id = str(job["id"])
    if job.get("source_id"):
        request.state.operation_source_id = str(job["source_id"])
    if job.get("subscription_id"):
        request.state.operation_subscription_id = str(job["subscription_id"])
    deduplicated = bool(job.get("deduplicated"))
    request.state.operation_outcome = "skipped" if deduplicated else "queued"
    request.state.operation_level = "info"
    request.state.operation_counts = {"deduplicated": int(deduplicated)}


async def jobs_source_test(
    payload: JobCreateRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    job = _create_job(payload, "source_test", user, context)
    _mark_queued_job_operation(request, job)
    return ok(job)


async def jobs_source_fetch(
    payload: JobCreateRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    job = _create_job(payload, "source_fetch", user, context)
    _mark_queued_job_operation(request, job)
    return ok(job)


async def jobs_user_feed_refresh(
    payload: JobCreateRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    job = _create_job(payload, "user_feed_refresh", user, context)
    _mark_queued_job_operation(request, job)
    return ok(job)


async def source_test_compat(
    payload: dict[str, Any],
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    job = _create_job(
        _compatibility_job_payload(payload),
        "source_test",
        user,
        context,
    )
    _mark_queued_job_operation(request, job)
    return ok(_queued_job_response(job, "测试任务已排队，Worker 会异步执行。"))


async def source_update_compat(
    payload: dict[str, Any],
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    job = _create_job(
        _compatibility_job_payload(payload),
        "source_fetch",
        user,
        context,
    )
    _mark_queued_job_operation(request, job)
    return ok(_queued_job_response(job, "更新任务已排队，Worker 会异步执行。"))


async def jobs_get(
    job_id: str,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    return ok(public_job(_job_or_404(job_id, user, context)))


async def jobs_cancel(
    job_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    current = _job_or_404(job_id, user, context)
    try:
        cancelled = public_job(
            context.job_queue.cancel_job(
                job_id,
                user_id=None if is_admin(user) else user["id"],
            )
        )
        request.state.operation_outcome = "cancelled"
        return ok(cancelled)
    except ValueError as exc:
        raise ApiError("job_not_cancelable", str(exc), status_code=409) from exc


async def jobs_retry(
    job_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    store = context.store
    queue = context.job_queue
    quota = context.quota
    conn = store.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = _job_or_404(job_id, user, context)
        eligibility = JobEligibilityService(store).evaluate(current)
        if not eligibility.allowed:
            raise ApiError(
                "job_not_retryable",
                f"job is no longer eligible: {eligibility.reason}",
                status_code=409,
                action="Re-enable the user, source, or subscription before retrying.",
            )
        metered = current.get("job_type") in {
            "source_test",
            "source_fetch",
            "user_feed_refresh",
        }
        if metered:
            quota.ensure_job_allowed(
                workspace_id=current["workspace_id"],
                user_id=current["user_id"],
            )
        retried = queue.retry_job(
            job_id,
            user_id=None if is_admin(user) else user["id"],
            commit=False,
        )
        if metered and retried["id"] == job_id:
            quota.record_job_usage(
                workspace_id=current["workspace_id"],
                user_id=current["user_id"],
                event_type=current["job_type"],
                commit=False,
            )
        conn.commit()
        request.state.operation_outcome = "retried"
        return ok(public_job(retried))
    except ValueError as exc:
        if conn.in_transaction:
            conn.rollback()
        raise ApiError("job_not_retryable", str(exc), status_code=409) from exc
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise


async def jobs_list(
    status: str | None = None,
    limit: int = 50,
    view: Literal["full", "summary"] = "full",
    scope: Literal["workspace", "me"] = "workspace",
    include_active: bool = False,
    job_type: list[str] | None = Query(default=None),
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    queue = context.job_queue
    job_types = _bounded_job_type_filters(job_type)
    scoped_user_id = user["id"] if scope == "me" or not is_admin(user) else None
    bounded_limit = max(1, min(int(limit), 200))
    if view == "summary":
        jobs = queue.list_job_summaries(
            workspace_id=user["workspace_id"],
            user_id=scoped_user_id,
            status=status,
            job_types=job_types,
            limit=bounded_limit,
            include_active=include_active,
        )
        return ok({"jobs": jobs})
    jobs = queue.list_jobs(
        workspace_id=user["workspace_id"],
        user_id=scoped_user_id,
        status=status,
        job_types=job_types,
        limit=bounded_limit,
    )
    if include_active and status is None:
        active_jobs = [
            *queue.list_jobs(
                workspace_id=user["workspace_id"],
                user_id=scoped_user_id,
                status="queued",
                job_types=job_types,
                limit=200,
            ),
            *queue.list_jobs(
                workspace_id=user["workspace_id"],
                user_id=scoped_user_id,
                status="running",
                job_types=job_types,
                limit=200,
            ),
        ]
        jobs_by_id = {str(job["id"]): job for job in jobs}
        jobs_by_id.update({str(job["id"]): job for job in active_jobs})
        jobs = sorted(
            jobs_by_id.values(),
            key=lambda job: str(job.get("created_at") or ""),
            reverse=True,
        )
    return ok({"jobs": [public_job(job) for job in jobs]})


def register_job_routes(app: FastAPI) -> None:
    """Register job routes in their compatibility-sensitive order."""

    app.add_api_route(
        "/api/jobs/source-test", jobs_source_test, methods=["POST"]
    )
    app.add_api_route(
        "/api/jobs/source-fetch", jobs_source_fetch, methods=["POST"]
    )
    app.add_api_route(
        "/api/jobs/user-feed-refresh", jobs_user_feed_refresh, methods=["POST"]
    )
    app.add_api_route("/api/source/test", source_test_compat, methods=["POST"])
    app.add_api_route("/api/source/update", source_update_compat, methods=["POST"])
    app.add_api_route("/api/jobs/{job_id}", jobs_get, methods=["GET"])
    app.add_api_route(
        "/api/jobs/{job_id}/cancel", jobs_cancel, methods=["POST"]
    )
    app.add_api_route(
        "/api/jobs/{job_id}/retry", jobs_retry, methods=["POST"]
    )
    app.add_api_route("/api/jobs", jobs_list, methods=["GET"])
