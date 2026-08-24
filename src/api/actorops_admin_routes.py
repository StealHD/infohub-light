"""v2-only ActorOps administration reads and redacted operation events."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from fastapi import Depends, FastAPI, Query, Response

from .responses import ApiError, ok
from .system_auth import current_admin
from ..services.actorops.admin_service import (
    ActorOpsAdminMigrationRequired,
    ActorOpsAdminService,
    ActorOpsAdminUnavailable,
)
from ..services.actorops.repository import ActorOpsNotFound


def register_actorops_admin_routes(
    app: FastAPI,
    *,
    store: Any,
    operation_logs: Any,
) -> None:
    """Register the v2 Admin list/detail and Operation Log views."""

    @app.get("/api/admin/apify-routes")
    async def routes(
        response: Response, user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        service = ActorOpsAdminService(store, workspace_id=str(user["workspace_id"]))
        try:
            payload = service.list_routes()
        except (ActorOpsAdminMigrationRequired, ActorOpsAdminUnavailable) as error:
            raise _admin_error(error) from error
        response.headers["Cache-Control"] = "no-store"
        return ok({"schema_version": 2, "routes": payload})

    @app.get("/api/admin/apify-routes/{route_id}")
    async def route_detail(
        route_id: str, response: Response, user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        service = ActorOpsAdminService(store, workspace_id=str(user["workspace_id"]))
        try:
            payload = service.route_detail(route_id)
        except ActorOpsNotFound as error:
            raise ApiError("not_found", "ActorOps Route 不存在。", status_code=404) from error
        except (ActorOpsAdminMigrationRequired, ActorOpsAdminUnavailable) as error:
            raise _admin_error(error) from error
        response.headers["Cache-Control"] = "no-store"
        return ok({"schema_version": 2, **payload})

    @app.get("/api/admin/apify-actor-events")
    async def actorops_events(
        response: Response,
        action: str | None = Query(default=None, min_length=1, max_length=96),
        job_id: str | None = Query(default=None, max_length=128),
        route_id: str | None = Query(default=None, max_length=128),
        repair_id: str | None = Query(default=None, max_length=128),
        phase: str | None = Query(default=None, max_length=96),
        outcome: str | None = Query(default=None, max_length=96),
        cursor: str | None = Query(default=None, max_length=128),
        source_id: str | None = Query(default=None, max_length=128),
        since: datetime | None = Query(default=None),
        until: datetime | None = Query(default=None),
        limit: int = Query(default=50, ge=1, le=100),
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        now = datetime.now(timezone.utc)
        start = _utc(since) if since is not None else now - timedelta(hours=24)
        end = _utc(until) if until is not None else now
        if start > end or end > now + timedelta(minutes=1):
            raise ApiError("actorops_events_window_invalid", "ActorOps 事件时间窗口无效。", status_code=422)
        trace: list[dict[str, object]] = []
        next_cursor: str | None = None
        completeness = "not_recorded"
        service = ActorOpsAdminService(store, workspace_id=str(user["workspace_id"]))
        try:
            service.repository()
            if action in {None, "actorops_v2_execution_trace"}:
                trace, next_cursor, completeness = service.execution_events(
                    root_job_id=job_id, route_id=route_id, source_id=source_id,
                    repair_id=repair_id, phase=phase, outcome=outcome,
                    since=start.isoformat(), until=end.isoformat(), before=cursor,
                    limit=limit,
                )
        except (ActorOpsAdminMigrationRequired, ActorOpsAdminUnavailable) as error:
            raise _admin_error(error) from error
        lookback = max(1, min(720, int((now - start).total_seconds() // 3600) + 1))
        result = operation_logs.query(
            workspace_id=str(user["workspace_id"]), user_id=str(user["id"]),
            scope="workspace", lookback_hours=lookback, source_id=source_id,
            job_id=job_id, limit=100,
        )
        filtered = [
            event for event in result["events"]
            if str(event.get("action") or "").startswith("actorops_v2_")
            and (action is None or event.get("action") == action)
            and _inside_window(event.get("timestamp"), start, end)
        ]
        legacy = [
            {"kind": "operation", **event}
            for event in filtered
            # The database record is the canonical timeline entry.  Its JSONL
            # mirror remains useful for operational recovery but would otherwise
            # duplicate every execution stage in the admin timeline.
            if event.get("action") != "actorops_v2_execution_trace"
            if not any((route_id, repair_id, phase, outcome, cursor))
        ]
        execution = [
            {
                "kind": "execution", "timestamp": event.pop("created_at"),
                "action": "actorops_v2_execution_trace", "level": "info", **event,
            }
            for event in trace
        ]
        selected = sorted(
            [*execution, *legacy],
            key=lambda event: str(event.get("timestamp") or ""), reverse=True,
        )[:limit]
        response.headers["Cache-Control"] = "no-store"
        return ok(
            {
                "schema_version": 3,
                "availability": "available" if trace else result["availability"],
                "events": selected,
                "returned": len(selected),
                "truncated": bool(result["truncated"]) or len(filtered) > limit or bool(next_cursor),
                "next_cursor": next_cursor,
                "completeness": completeness,
                "window": {"from": start.isoformat(), "to": end.isoformat()},
            }
        )


def _admin_error(error: ActorOpsAdminMigrationRequired | ActorOpsAdminUnavailable) -> ApiError:
    if isinstance(error, ActorOpsAdminMigrationRequired):
        return ApiError(
            "actorops_v2_migration_required",
            "ActorOps v2 数据库迁移尚未完成。",
            status_code=503,
            action="Stop ActorOps API and Worker, then apply the required ActorOps v2 migrations.",
        )
    return ApiError(
        "actorops_v2_unavailable",
        "ActorOps v2 当前不可用。",
        status_code=503,
        action="Check the ActorOps v2 store and retry after it becomes available.",
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _inside_window(value: object, start: datetime, end: datetime) -> bool:
    if not isinstance(value, str):
        return False
    try:
        stamp = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return False
    return start <= _utc(stamp) <= end


__all__ = ["register_actorops_admin_routes"]
