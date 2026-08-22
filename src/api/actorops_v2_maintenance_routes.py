"""Owner/Admin maintenance-policy endpoints for the default-off v2 facade."""

from __future__ import annotations

from typing import Any, Protocol

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from .responses import ApiError, ok
from .system_auth import current_admin
from ..services.actorops.admin_service import (
    ActorOpsAdminMigrationRequired,
    ActorOpsAdminService,
    ActorOpsAdminUnavailable,
)
from ..services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from ..services.operation_log import safe_emit_operation_event


class ActorOpsV2MaintenanceContext(Protocol):
    store: Any


MUTATION_OPERATION_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("PATCH", "/api/admin/apify-maintenance-policy"): (
        "source", "actorops_v2_workspace_maintenance_policy_update",
    ),
    ("PATCH", "/api/admin/apify-routes/{route_id}/maintenance-policy"): (
        "source", "actorops_v2_route_maintenance_policy_update",
    ),
}


class MaintenancePolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    expected_generation: StrictInt = Field(ge=1)


def register_actorops_v2_maintenance_policy_routes(
    app: FastAPI, context: ActorOpsV2MaintenanceContext
) -> None:
    """Register non-billable policy CAS endpoints under established admin paths."""

    @app.get("/api/admin/apify-maintenance-policy")
    async def get_workspace_policy(
        response: Response, user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return ok(_workspace_policy(context.store, str(user["workspace_id"])))

    @app.patch("/api/admin/apify-maintenance-policy")
    async def patch_workspace_policy(
        payload: MaintenancePolicyPatch, request: Request, response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        result = _set_policy(
            context.store, str(user["workspace_id"]), None, bool(payload.enabled),
            int(payload.expected_generation), str(user["id"]),
        )
        request.state.operation_changed_fields = ["actorops_v2_workspace_maintenance"]
        _record_policy_mutation(
            request,
            user,
            action="actorops_v2_workspace_maintenance_policy_update",
            route="/api/admin/apify-maintenance-policy",
        )
        response.headers["Cache-Control"] = "no-store"
        return ok(result)

    @app.get("/api/admin/apify-routes/{route_id}/maintenance-policy")
    async def get_route_policy(
        route_id: str, response: Response, user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return ok(_route_policy(context.store, str(user["workspace_id"]), route_id))

    @app.patch("/api/admin/apify-routes/{route_id}/maintenance-policy")
    async def patch_route_policy(
        route_id: str, payload: MaintenancePolicyPatch, request: Request,
        response: Response, user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        result = _set_policy(
            context.store, str(user["workspace_id"]), route_id, bool(payload.enabled),
            int(payload.expected_generation), str(user["id"]),
        )
        request.state.operation_changed_fields = ["actorops_v2_route_maintenance"]
        _record_policy_mutation(
            request,
            user,
            action="actorops_v2_route_maintenance_policy_update",
            route="/api/admin/apify-routes/{route_id}/maintenance-policy",
        )
        response.headers["Cache-Control"] = "no-store"
        return ok(result)


def _set_policy(
    store: Any, workspace_id: str, route_id: str | None, enabled: bool,
    expected_generation: int, actor_user_id: str,
) -> dict[str, object]:
    _workspace_policy(store, workspace_id)
    repository = ActorOpsRepository(store.connect(), workspace_id)
    try:
        with repository.transaction():
            policy = repository.maintenance.set_enabled(
                route_id, enabled,
                authorized_by_user_id=actor_user_id if enabled else None,
                expected_generation=expected_generation,
            )
    except ActorOpsConflict as error:
        raise ApiError("actorops_v2_policy_conflict", str(error), status_code=409) from error
    if route_id is None:
        return _workspace_policy(store, workspace_id)
    return _route_policy(store, workspace_id, route_id)


def _record_policy_mutation(
    request: Request, user: dict[str, Any], *, action: str, route: str,
) -> None:
    """Log only the committed, value-free policy transition."""

    safe_emit_operation_event(
        category="source",
        action=action,
        outcome="succeeded",
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        changed_fields=list(request.state.operation_changed_fields),
        route=route,
        method="PATCH",
        status_code=200,
    )
    request.state.operation_logged = True


def _workspace_policy(store: Any, workspace_id: str) -> dict[str, object]:
    try:
        return ActorOpsAdminService(
            store, workspace_id=workspace_id
        ).workspace_maintenance_policy()
    except RuntimeError as error:
        raise _unavailable(error) from error


def _route_policy(store: Any, workspace_id: str, route_id: str) -> dict[str, object]:
    try:
        return ActorOpsAdminService(
            store, workspace_id=workspace_id
        ).route_maintenance_policy(route_id)
    except RuntimeError as error:
        raise _unavailable(error) from error


def _unavailable(error: RuntimeError) -> ApiError:
    if isinstance(error, ActorOpsAdminMigrationRequired):
        return ApiError(
            "actorops_v2_migration_required", "ActorOps v2 数据库迁移尚未完成。",
            status_code=503,
        )
    if isinstance(error, ActorOpsAdminUnavailable):
        return ApiError("actorops_v2_unavailable", "ActorOps v2 当前不可用。", status_code=503)
    return ApiError("actorops_v2_unavailable", "ActorOps v2 当前不可用。", status_code=503)


__all__ = ["register_actorops_v2_maintenance_policy_routes"]
