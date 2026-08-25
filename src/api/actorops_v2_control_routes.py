"""Owner/Admin, zero-cost manual controls for the ActorOps v2 facade."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .responses import ApiError, ok
from .system_auth import current_admin
from ..services.actorops.binding_reconciliation import ActorOpsBindingReconciler
from ..services.actorops.binding_service import (
    ActorOpsBindingError,
)
from ..services.actorops.admin_service import (
    ActorOpsAdminMigrationRequired,
    ActorOpsAdminService,
    ActorOpsAdminUnavailable,
)
from ..services.actorops.repository import (
    ActorOpsConflict,
    ActorOpsNotFound,
)
from ..services.operation_log import safe_emit_operation_event


class ActorOpsV2ControlContext(Protocol):
    store: Any


MUTATION_OPERATION_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("POST", "/api/admin/apify-routes/{route_id}/v2-candidates/{candidate_id}/promote"): (
        "source", "actorops_v2_candidate_promote",
    ),
    ("POST", "/api/admin/apify-routes/{route_id}/v2-bindings/verify"): (
        "source", "actorops_v2_binding_verify",
    ),
    ("POST", "/api/admin/apify-routes/{route_id}/v2-bindings/reconcile"): (
        "source", "actorops_v2_binding_verify",
    ),
}


class PromoteCandidateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_route_generation: StrictInt = Field(ge=1)
    expected_candidate_generation: StrictInt = Field(ge=1)
    confirmation: Literal["确认设为主用 Actor"]


class VerifyBindingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_route_generation: StrictInt = Field(ge=1)
    confirmation: Literal["确认核验来源绑定"]


class ReconcileBindingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_route_generation: StrictInt = Field(ge=1)


def register_actorops_v2_control_routes(
    app: FastAPI, context: ActorOpsV2ControlContext
) -> None:
    """Register operations that only reorder or prove already-settled facts."""

    @app.post(
        "/api/admin/apify-routes/{route_id}/v2-candidates/{candidate_id}/promote"
    )
    async def promote_candidate(
        route_id: str,
        candidate_id: str,
        payload: PromoteCandidateRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        try:
            repository = ActorOpsAdminService(
                context.store, workspace_id=workspace_id
            ).repository()
            with repository.transaction():
                repository.promote_standby_candidate(
                    route_id,
                    candidate_id,
                    expected_route_generation=int(payload.expected_route_generation),
                    expected_candidate_generation=int(payload.expected_candidate_generation),
                )
        except (ActorOpsConflict, ActorOpsNotFound) as error:
            raise ApiError(
                "actorops_v2_candidate_switch_conflict",
                "The selected Candidate changed; reload before switching.",
                status_code=409,
            ) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record_action(request, user, "actorops_v2_candidate_promote")
        response.headers["Cache-Control"] = "no-store"
        return ok(_route_projection(context.store, workspace_id, route_id))

    @app.post("/api/admin/apify-routes/{route_id}/v2-bindings/verify")
    async def verify_bindings(
        route_id: str,
        payload: VerifyBindingsRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        try:
            repository = ActorOpsAdminService(
                context.store, workspace_id=workspace_id
            ).repository()
            route = repository.get_route(route_id)
            if route.generation != int(payload.expected_route_generation):
                raise ActorOpsConflict("route changed before binding verification")
            summary = ActorOpsBindingReconciler(
                context.store, workspace_id=workspace_id
            ).reconcile_route(route_id, include_ready=False)
            if summary.checked_count and not summary.verified_binding_count:
                raise ActorOpsBindingError(
                    "actorops_v2_binding_evidence_missing"
                )
        except ActorOpsBindingError as error:
            if error.code == "actorops_v2_binding_evidence_missing":
                raise ApiError(
                    error.code,
                    "Current v2 evidence cannot yet prove this binding.",
                    status_code=409,
                ) from error
            raise ApiError(
                "actorops_v2_binding_conflict",
                "The binding changed; reload before verifying it.",
                status_code=409,
            ) from error
        except (ActorOpsConflict, ActorOpsNotFound) as error:
            raise ApiError(
                "actorops_v2_binding_conflict",
                "The route changed; reload before verifying bindings.",
                status_code=409,
            ) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record_action(request, user, "actorops_v2_binding_verify")
        response.headers["Cache-Control"] = "no-store"
        return ok({
            **_route_projection(context.store, workspace_id, route_id),
            **summary.public(),
        })

    @app.post("/api/admin/apify-routes/{route_id}/v2-bindings/reconcile")
    async def reconcile_bindings(
        route_id: str,
        payload: ReconcileBindingsRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        try:
            repository = ActorOpsAdminService(
                context.store, workspace_id=workspace_id
            ).repository()
            route = repository.get_route(route_id)
            if route.generation != int(payload.expected_route_generation):
                raise ActorOpsConflict("route changed before binding reconciliation")
            summary = ActorOpsBindingReconciler(
                context.store, workspace_id=workspace_id
            ).reconcile_route(route_id)
        except (ActorOpsConflict, ActorOpsNotFound) as error:
            raise ApiError(
                "actorops_v2_binding_conflict",
                "The route changed; reload before reconciling bindings.",
                status_code=409,
            ) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record_action(request, user, "actorops_v2_binding_verify")
        response.headers["Cache-Control"] = "no-store"
        return ok({
            **_route_projection(context.store, workspace_id, route_id),
            **summary.public(),
        })


def _route_projection(store: Any, workspace_id: str, route_id: str) -> dict[str, object]:
    return ActorOpsAdminService(store, workspace_id=workspace_id).route_summary(route_id)


def _unavailable(_error: RuntimeError) -> ApiError:
    if isinstance(_error, ActorOpsAdminMigrationRequired):
        return ApiError(
            "actorops_v2_migration_required", "ActorOps v2 数据库迁移尚未完成。",
            status_code=503,
        )
    if isinstance(_error, ActorOpsAdminUnavailable):
        return ApiError("actorops_v2_unavailable", "ActorOps v2 当前不可用。", status_code=503)
    return ApiError("actorops_v2_unavailable", "ActorOps v2 当前不可用。", status_code=503)


def _record_action(request: Request, user: dict[str, Any], action: str) -> None:
    request.state.operation_changed_fields = [action]
    safe_emit_operation_event(
        category="source",
        action=action,
        outcome="succeeded",
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        changed_fields=list(request.state.operation_changed_fields),
        route=request.scope.get("route").path,
        method="POST",
        status_code=200,
    )
    request.state.operation_logged = True


__all__ = ["register_actorops_v2_control_routes"]
