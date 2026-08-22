"""Stable legacy URLs implemented exclusively with ActorOps v2 facts."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .actorops_v2_operator_routes import ensure_operator_discovery
from .responses import ApiError, ok
from .system_auth import current_admin
from ..services.actorops.admin_service import (
    ActorOpsAdminMigrationRequired,
    ActorOpsAdminService,
    ActorOpsAdminUnavailable,
)
from ..services.actorops.binding_service import (
    ActorOpsBindingError,
    ActorOpsBindingService,
)
from ..services.actorops.repository import ActorOpsConflict, ActorOpsNotFound
from ..services.operation_log import safe_emit_operation_event


class ActorOpsV2AliasContext(Protocol):
    store: Any


MUTATION_OPERATION_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("POST", "/api/admin/apify-routes/{route_id}/pool-candidates/refresh"): (
        "source",
        "actorops_v2_discovery_create",
    ),
    ("POST", "/api/admin/apify-routes/{route_id}/active-pool/promote"): (
        "source",
        "actorops_v2_candidate_promote",
    ),
    ("PATCH", "/api/admin/apify-routes/{route_id}/price-cap"): (
        "source",
        "actorops_v2_price_cap",
    ),
    ("POST", "/api/admin/sources/{source_id}/apify-binding/activate"): (
        "source",
        "actorops_v2_binding_enable",
    ),
}


class RefreshPoolCandidatesRequest(BaseModel):
    """Accept the safe subset of the retired refresh request."""

    model_config = ConfigDict(extra="forbid")

    expected_generation: StrictInt = Field(ge=1)
    goal: str | None = Field(default=None, max_length=48)
    target_slot: Literal["primary", "backup_1", "backup_2"] | None = None


class PromoteActivePoolRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_slot: Literal["backup_1", "backup_2"]
    expected_generation: StrictInt = Field(ge=1)
    confirmation: Literal["确认设为主用 Actor"]


class SetRoutePriceCapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_generation: StrictInt = Field(ge=1)
    per_run_cap_usd: float = Field(gt=0, le=0.20)
    confirmation: Literal["确认提高 Actor 费用上限"] | None = None


class ActivateSourceBindingRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_generation: StrictInt = Field(ge=1)
    confirmation: Literal["确认首次启用"]


def register_actorops_v2_alias_routes(
    app: FastAPI, context: ActorOpsV2AliasContext
) -> None:
    """Register stable URLs that have a complete v2 equivalent."""

    _register_route_aliases(app, context)
    _register_source_aliases(app, context)


def _register_route_aliases(
    app: FastAPI, context: ActorOpsV2AliasContext
) -> None:
    @app.post("/api/admin/apify-routes/{route_id}/pool-candidates/refresh")
    async def refresh_pool_candidates(
        route_id: str,
        payload: RefreshPoolCandidatesRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        try:
            repository = _repository(context.store, workspace_id)
            discovery_id, created = ensure_operator_discovery(
                repository,
                route_id=route_id,
                expected_route_generation=int(payload.expected_generation),
            )
        except (ActorOpsConflict, ActorOpsNotFound) as error:
            raise ApiError(
                "actorops_v2_discovery_conflict",
                "路线已更新，请刷新后再搜索候选。",
                status_code=409,
            ) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record(request, user, "actorops_v2_discovery_create")
        response.headers["Cache-Control"] = "no-store"
        return ok(
            {
                "schema_version": 2,
                "route_id": route_id,
                "discovery_id": discovery_id,
                "created": created,
                "queued": True,
            }
        )

    @app.post("/api/admin/apify-routes/{route_id}/active-pool/promote")
    async def promote_active_pool_slot(
        route_id: str,
        payload: PromoteActivePoolRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        try:
            repository = _repository(context.store, workspace_id)
            with repository.transaction():
                route = repository.get_route(route_id)
                if route.generation != int(payload.expected_generation):
                    raise ActorOpsConflict("route changed before candidate promotion")
                target_priority = 1 if payload.target_slot == "backup_1" else 2
                candidate = next(
                    (
                        item
                        for item in repository.list_route_candidates(route_id)
                        if item.assignment_role.value == "standby"
                        and item.priority == target_priority
                    ),
                    None,
                )
                if candidate is None:
                    raise ActorOpsConflict("selected v2 standby candidate is unavailable")
                repository.promote_standby_candidate(
                    route_id,
                    candidate.candidate_id,
                    expected_route_generation=route.generation,
                    expected_candidate_generation=candidate.generation,
                )
            result = _route_summary(context.store, workspace_id, route_id)
        except (ActorOpsConflict, ActorOpsNotFound) as error:
            raise ApiError(
                "actorops_v2_candidate_switch_conflict",
                "The selected Candidate changed; reload before switching.",
                status_code=409,
            ) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record(request, user, "actorops_v2_candidate_promote")
        response.headers["Cache-Control"] = "no-store"
        return ok({"schema_version": 2, **result})

    @app.patch("/api/admin/apify-routes/{route_id}/price-cap")
    async def set_route_price_cap(
        route_id: str,
        payload: SetRoutePriceCapRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        try:
            repository = _repository(context.store, workspace_id)
            route = repository.get_route(route_id)
            if (
                payload.per_run_cap_usd > route.per_run_cap_usd
                and payload.confirmation != "确认提高 Actor 费用上限"
            ):
                raise ApiError(
                    "actorops_v2_price_cap_confirmation_required",
                    "提高单次费用上限需要确认。",
                    status_code=422,
                )
            with repository.transaction():
                repository.operator.set_route_cap(
                    route_id,
                    cap_usd=float(payload.per_run_cap_usd),
                    expected_generation=int(payload.expected_generation),
                )
            result = _route_summary(context.store, workspace_id, route_id)
        except (ActorOpsConflict, ActorOpsNotFound) as error:
            raise ApiError(
                "actorops_v2_price_cap_conflict",
                "路线已更新，请刷新后再修改费用上限。",
                status_code=409,
            ) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record(request, user, "actorops_v2_price_cap")
        response.headers["Cache-Control"] = "no-store"
        return ok({"schema_version": 2, **result})


def _register_source_aliases(
    app: FastAPI, context: ActorOpsV2AliasContext
) -> None:
    @app.get("/api/admin/sources/{source_id}/apify-support")
    async def source_support(
        source_id: str,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        _source_for_workspace(context.store, source_id, workspace_id)
        try:
            _repository(context.store, workspace_id)
            bindings = ActorOpsBindingService(
                context.store, workspace_id=workspace_id
            )
            binding = bindings.repository.get_binding(source_id)
            state = bindings.execution_state(source_id)
        except ActorOpsNotFound as error:
            raise ApiError(
                "actorops_v2_binding_not_found",
                "当前来源没有 ActorOps v2 Binding。",
                status_code=404,
            ) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        response.headers["Cache-Control"] = "no-store"
        return ok(
            {
                "schema_version": 2,
                "source_id": source_id,
                "route_id": binding.route_id,
                "binding_version": binding.binding_version,
                "binding_status": binding.status,
                "enabled": bool(_source_for_workspace(context.store, source_id, workspace_id)["enabled"]),
                "execution_mode": state.execution_mode,
                "reason": state.reason,
            }
        )

    @app.post("/api/admin/sources/{source_id}/apify-binding/activate")
    async def activate_source_binding(
        source_id: str,
        payload: ActivateSourceBindingRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        _source_for_workspace(context.store, source_id, workspace_id)
        try:
            repository = _repository(context.store, workspace_id)
            bindings = ActorOpsBindingService(
                context.store, workspace_id=workspace_id
            )
            with repository.transaction():
                binding = bindings.repository.get_binding(source_id)
                if binding.binding_version != int(payload.expected_generation):
                    raise ActorOpsBindingError("actorops_v2_binding_conflict")
                bindings.enable_ready(source_id)
                binding = bindings.repository.get_binding(source_id)
            state = bindings.execution_state(source_id)
        except ActorOpsBindingError as error:
            code = (
                "actorops_v2_binding_not_ready"
                if error.code == "actorops_v2_binding_not_ready"
                else "actorops_v2_binding_conflict"
            )
            raise ApiError(
                code,
                "ActorOps v2 Binding 尚未就绪。"
                if code.endswith("not_ready")
                else "ActorOps v2 Binding 已变化，请刷新后重试。",
                status_code=409,
            ) from error
        except ActorOpsNotFound as error:
            raise ApiError(
                "actorops_v2_binding_not_found",
                "当前来源没有 ActorOps v2 Binding。",
                status_code=404,
            ) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record(request, user, "actorops_v2_binding_enable")
        response.headers["Cache-Control"] = "no-store"
        return ok(
            {
                "schema_version": 2,
                "source_id": source_id,
                "route_id": binding.route_id,
                "binding_version": binding.binding_version,
                "binding_status": binding.status,
                "enabled": True,
                "execution_mode": state.execution_mode,
                "reason": state.reason,
            }
        )


def _repository(store: Any, workspace_id: str):
    return ActorOpsAdminService(store, workspace_id=workspace_id).repository()


def _route_summary(store: Any, workspace_id: str, route_id: str) -> dict[str, object]:
    return ActorOpsAdminService(store, workspace_id=workspace_id).route_summary(route_id)


def _source_for_workspace(store: Any, source_id: str, workspace_id: str) -> dict[str, Any]:
    source = store.get_source(source_id)
    if source is None or str(source.get("workspace_id")) != workspace_id:
        raise ApiError("not_found", "source not found", status_code=404)
    return source


def _unavailable(error: RuntimeError) -> ApiError:
    if isinstance(error, ActorOpsAdminMigrationRequired):
        return ApiError(
            "actorops_v2_migration_required",
            "ActorOps v2 数据库迁移尚未完成。",
            status_code=503,
        )
    if isinstance(error, ActorOpsAdminUnavailable):
        return ApiError(
            "actorops_v2_unavailable", "ActorOps v2 当前不可用。", status_code=503
        )
    return ApiError("actorops_v2_unavailable", "ActorOps v2 当前不可用。", status_code=503)


def _record(request: Request, user: dict[str, Any], action: str) -> None:
    request.state.operation_changed_fields = [action]
    safe_emit_operation_event(
        category="source",
        action=action,
        outcome="succeeded",
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        changed_fields=list(request.state.operation_changed_fields),
        route=request.scope.get("route").path,
        method=request.method,
        status_code=200,
    )
    request.state.operation_logged = True


__all__ = ["register_actorops_v2_alias_routes"]
