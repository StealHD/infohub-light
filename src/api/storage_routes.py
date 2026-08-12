"""Workspace storage-governance API routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field
from starlette.concurrency import run_in_threadpool

from .context import ApiContext
from .responses import ok
from .system_auth import api_context, current_admin


class StoragePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["cleanup", "archive", "restore", "delete_archive"]
    payload: dict[str, Any] = Field(default_factory=dict)


class StoragePlanApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str = Field(default="", max_length=240)


async def admin_storage_summary(
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return ok(
        await run_in_threadpool(
            context.storage_governance.summary,
            workspace_id=str(user["workspace_id"]),
        )
    )


async def admin_storage_plan_create(
    payload: StoragePlanRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    plan = await run_in_threadpool(
        context.storage_governance.create_plan,
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        actor_role=str(user["role"]),
        operation=payload.operation,
        payload=payload.payload,
    )
    request.state.operation_changed_fields = ["operation", "preview"]
    response.headers["Cache-Control"] = "no-store"
    return ok(plan)


async def admin_storage_plan_apply(
    plan_id: str,
    payload: StoragePlanApplyRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    plan = await run_in_threadpool(
        context.storage_governance.apply_plan,
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        actor_role=str(user["role"]),
        plan_id=plan_id,
        confirmation=payload.confirmation,
    )
    request.state.operation_changed_fields = [
        str(plan.get("operation") or "storage"),
        "apply",
    ]
    response.headers["Cache-Control"] = "no-store"
    return ok(plan)


async def admin_storage_archives(
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    response.headers["Cache-Control"] = "no-store"
    return ok(
        await run_in_threadpool(
            context.storage_governance.list_archives,
            workspace_id=str(user["workspace_id"]),
        )
    )


def register_storage_routes(app: FastAPI) -> None:
    """Register storage routes in their compatibility-sensitive order."""

    app.add_api_route(
        "/api/admin/storage/summary", admin_storage_summary, methods=["GET"]
    )
    app.add_api_route(
        "/api/admin/storage/plans", admin_storage_plan_create, methods=["POST"]
    )
    app.add_api_route(
        "/api/admin/storage/plans/{plan_id}/apply",
        admin_storage_plan_apply,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/admin/storage/archives", admin_storage_archives, methods=["GET"]
    )
