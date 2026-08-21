"""Owner/Admin, zero-cost manual controls for the ActorOps v2 facade."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .actorops_v2_projection import actorops_v2_route_additions
from .responses import ApiError, ok
from .system_auth import current_admin
from ..services.actorops.legacy_readiness import (
    apply_legacy_ready_bindings,
    legacy_ready_binding_plans,
)
from ..services.actorops.readiness import (
    actorops_v2_enabled,
    require_actorops_v2_if_enabled,
)
from ..services.actorops.repository import (
    ActorOpsConflict,
    ActorOpsNotFound,
    ActorOpsRepository,
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
            _require_enabled(context.store)
            repository = ActorOpsRepository(context.store.connect(), workspace_id)
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
            _require_enabled(context.store)
            repository = ActorOpsRepository(context.store.connect(), workspace_id)
            with repository.transaction():
                route = repository.get_route(route_id)
                if route.generation != int(payload.expected_route_generation):
                    raise ActorOpsConflict("route changed before binding verification")
                plans, report = legacy_ready_binding_plans(
                    repository.connection, workspace_id=workspace_id, route_id=route_id,
                )
                if report.pending_bindings and not plans:
                    raise ApiError(
                        "actorops_v2_binding_evidence_missing",
                        "Current source evidence cannot yet prove this binding.",
                        status_code=409,
                    )
                promoted = apply_legacy_ready_bindings(repository, plans)
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
            "verified_binding_count": promoted,
        })


def _route_projection(store: Any, workspace_id: str, route_id: str) -> dict[str, object]:
    projection = actorops_v2_route_additions(store, workspace_id, route_id)
    if projection is None:
        raise RuntimeError("actorops_v2_disabled")
    return projection


def _require_enabled(store: Any) -> None:
    if not actorops_v2_enabled():
        raise RuntimeError("actorops_v2_disabled")
    require_actorops_v2_if_enabled(store)


def _unavailable(_error: RuntimeError) -> ApiError:
    return ApiError(
        "actorops_v2_unavailable", "ActorOps v2 is not available", status_code=409,
    )


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
