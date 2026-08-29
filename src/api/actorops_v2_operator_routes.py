"""Owner/Admin HTTP adapters for v2 metadata, price caps, and replacements."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timezone
from typing import Any, Literal, Protocol

import httpx
from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .actorops_v2_projection import actorops_v2_candidate_projection
from .responses import ApiError, ok
from .system_auth import current_admin
from ..services.actorops.domain import AssignmentRole, ReplacementStatus
from ..services.actorops.adapters import build_default_registry
from ..services.actorops.binding_reconciliation import ActorOpsBindingReconciler
from ..services.actorops.discovery_search import DISCOVERY_SEARCH_STRATEGY
from ..services.actorops.discovery_ai_prompt import DISCOVERY_MAPPING_STRATEGY
from ..services.actorops.admin_service import (
    ActorOpsAdminMigrationRequired,
    ActorOpsAdminService,
    ActorOpsAdminUnavailable,
)
from ..services.actorops.repository import ActorOpsConflict, ActorOpsNotFound, ActorOpsRepository
from ..services.actorops.replacement_preview import (
    check_replacement_preview,
    settle_replacement_preview_failure,
    validation_catalog,
)
from ..scrapers.apify_client import ApifyClient
from ..services.actorops.apify_remote import ApifyV2RemoteClient
from ..services.actorops.replacement_revalidation import (
    ReplacementRevalidationError,
    revalidate_failed_replacement,
)
from ..services.actorops.workflow_projection import replacement_workflow_additions
from ..services.apify_pool_runtime import apify_coordinator_for_workspace
from ..services.operation_log import safe_emit_operation_event
from ..services.system_settings import resolve_system_setting


class ActorOpsV2OperatorContext(Protocol):
    store: Any
    job_queue: Any


MUTATION_OPERATION_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("POST", "/api/admin/apify-routes/{route_id}/v2-metadata/refresh"): (
        "source", "actorops_v2_metadata_refresh",
    ),
    ("POST", "/api/admin/apify-routes/{route_id}/v2-discoveries"): (
        "source", "actorops_v2_discovery_create",
    ),
    ("PATCH", "/api/admin/apify-routes/{route_id}/v2-price-cap"): (
        "source", "actorops_v2_price_cap",
    ),
    ("POST", "/api/admin/apify-routes/{route_id}/v2-replacements"): (
        "source", "actorops_v2_replacement_preview",
    ),
    ("POST", "/api/admin/apify-routes/{route_id}/v2-replacements/{plan_id}/authorize"): (
        "source", "actorops_v2_replacement_authorize",
    ),
    ("POST", "/api/admin/apify-routes/{route_id}/v2-replacements/{plan_id}/apply"): (
        "source", "actorops_v2_replacement_apply",
    ),
    ("POST", "/api/admin/apify-routes/{route_id}/v2-replacements/{plan_id}/cancel"): (
        "source", "actorops_v2_replacement_cancel",
    ),
    ("POST", "/api/admin/apify-routes/{route_id}/v2-replacements/{plan_id}/revalidate"): (
        "source", "actorops_v2_replacement_revalidate",
    ),
}


class RouteGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_route_generation: StrictInt = Field(ge=1)


class SetPriceCapRequest(RouteGenerationRequest):
    cap_usd: float = Field(gt=0, le=0.20)
    confirmation: Literal["确认提高 Actor 费用上限"] | None = None


class CreateReplacementRequest(RouteGenerationRequest):
    target_assignment: Literal["active", "standby"]
    target_priority: StrictInt = Field(ge=0, le=2)
    candidate_id: str = Field(min_length=1, max_length=128)
    expected_candidate_generation: StrictInt = Field(ge=1)
    idempotency_key: str = Field(min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$")
    per_probe_cap_usd: float = Field(gt=0, le=0.20)
    total_cap_usd: float = Field(gt=0, le=0.60)


class PlanGenerationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")
    expected_generation: StrictInt = Field(ge=1)


class RevalidateReplacementRequest(PlanGenerationRequest):
    idempotency_key: str = Field(
        min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )


class AuthorizeReplacementRequest(PlanGenerationRequest):
    confirmation: Literal["确认实测替换 Actor"]


class ApplyReplacementRequest(PlanGenerationRequest):
    confirmation: Literal["确认替换 Actor"]


def register_actorops_v2_operator_routes(
    app: FastAPI, context: ActorOpsV2OperatorContext,
) -> None:
    _register_candidate_routes(app, context)
    _register_replacement_routes(app, context)
    _register_revalidation_route(app, context)


def _register_candidate_routes(app: FastAPI, context: ActorOpsV2OperatorContext) -> None:
    @app.get("/api/admin/apify-routes/{route_id}/v2-candidates")
    async def candidates(route_id: str, response: Response, user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        try:
            repository = _repository(context.store, str(user["workspace_id"]))
            items = [actorops_v2_candidate_projection(repository, item) for item in repository.list_route_candidates(route_id)]
        except (ActorOpsNotFound, RuntimeError) as error:
            raise _unavailable(error) from error
        response.headers["Cache-Control"] = "no-store"
        return ok({"route_id": route_id, "candidates": items})

    @app.post("/api/admin/apify-routes/{route_id}/v2-metadata/refresh")
    async def refresh_metadata(route_id: str, payload: RouteGenerationRequest, request: Request, response: Response, user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        try:
            repository = _repository(context.store, workspace_id)
            route = repository.get_route(route_id)
            if route.generation != payload.expected_route_generation:
                raise ActorOpsConflict("route changed before metadata refresh")
            job = context.job_queue.create_job(workspace_id=workspace_id, user_id=str(user["id"]), job_type="actorops_v2_metadata_refresh", payload={"route_id": route_id}, priority=-10, max_attempts=1, retention_days=int(resolve_system_setting(context.store, workspace_id, "jobs.retention_days")))
        except (ActorOpsConflict, ActorOpsNotFound) as error:
            raise _conflict("actorops_v2_metadata_conflict", "路线已更新，请刷新后再更新商城信息。", error) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record(request, user, "actorops_v2_metadata_refresh")
        response.headers["Cache-Control"] = "no-store"
        return ok({"route_id": route_id, "job_id": str(job["id"]), "queued": True})

    @app.post("/api/admin/apify-routes/{route_id}/v2-discoveries")
    async def create_discovery(route_id: str, payload: RouteGenerationRequest, request: Request, response: Response, user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        try:
            repository = _repository(context.store, workspace_id)
            discovery_id, created = ensure_operator_discovery(
                repository,
                route_id=route_id,
                expected_route_generation=payload.expected_route_generation,
            )
        except (ActorOpsConflict, ActorOpsNotFound) as error:
            raise _conflict("actorops_v2_discovery_conflict", "路线已更新，请刷新后再搜索候选。", error) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record(request, user, "actorops_v2_discovery_create")
        response.headers["Cache-Control"] = "no-store"
        return ok({"route_id": route_id, "discovery_id": discovery_id, "created": created, "queued": True})

    @app.patch("/api/admin/apify-routes/{route_id}/v2-price-cap")
    async def set_price_cap(route_id: str, payload: SetPriceCapRequest, request: Request, response: Response, user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        try:
            repository = _repository(context.store, workspace_id)
            route = repository.get_route(route_id)
            if payload.cap_usd > route.per_run_cap_usd and payload.confirmation != "确认提高 Actor 费用上限":
                raise ApiError("actorops_v2_price_cap_confirmation_required", "提高单次费用上限需要确认。", status_code=422)
            with repository.transaction():
                repository.operator.set_route_cap(route_id, cap_usd=payload.cap_usd, expected_generation=payload.expected_route_generation)
        except (ActorOpsConflict, ActorOpsNotFound) as error:
            raise _conflict("actorops_v2_price_cap_conflict", "路线已更新，请刷新后再修改费用上限。", error) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record(request, user, "actorops_v2_price_cap")
        response.headers["Cache-Control"] = "no-store"
        return ok(_route(context.store, workspace_id, route_id))


def ensure_operator_discovery(
    repository: ActorOpsRepository,
    *,
    route_id: str,
    expected_route_generation: int,
) -> tuple[str, bool]:
    """Create or safely reuse the free v2 operator Discovery fact."""

    with repository.transaction():
        route = repository.get_route(route_id)
        if route.generation != int(expected_route_generation):
            raise ActorOpsConflict("route changed before discovery")
        bucket = datetime.now(timezone.utc).strftime("%Y%m%d%H")
        key = _hash(
            "operator-discovery", DISCOVERY_SEARCH_STRATEGY,
            DISCOVERY_MAPPING_STRATEGY,
            route_id, str(route.generation), bucket,
        )
        discovery_id = f"operator-discovery-{uuid.uuid4().hex}"
        row, created = repository.discovery.ensure(
            discovery_id=discovery_id,
            idempotency_key=key,
            route_id=route_id,
            trigger_reason="operator_refresh",
            input_fingerprint=_hash(
                "route", str(route.route_key), DISCOVERY_MAPPING_STRATEGY
            ),
        )
        no_selectable_candidate = (
            str(row["status"]) == "completed"
            and not repository.discovery.list_accepted_candidate_ids(
                str(row["discovery_id"])
            )
        )
        if not created and (
            str(row["status"]) in {"failed", "cancelled"}
            or no_selectable_candidate
        ):
            # A retry is a new explicit free operator action. A completed
            # search with no selectable candidate remains retryable because
            # public Store schemas and pricing can change within an hour.
            key = _hash(
                "operator-discovery-retry",
                route_id,
                str(route.generation),
                bucket,
                uuid.uuid4().hex,
            )
            discovery_id = f"operator-discovery-{uuid.uuid4().hex}"
            row, created = repository.discovery.ensure(
                discovery_id=discovery_id,
                idempotency_key=key,
                route_id=route_id,
                trigger_reason="operator_refresh",
                input_fingerprint=_hash(
                    "route", str(route.route_key), DISCOVERY_MAPPING_STRATEGY
                ),
            )
    return str(row["discovery_id"]), created


def _register_replacement_routes(app: FastAPI, context: ActorOpsV2OperatorContext) -> None:
    @app.post("/api/admin/apify-routes/{route_id}/v2-replacements")
    async def create_replacement(route_id: str, payload: CreateReplacementRequest, request: Request, response: Response, user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        try:
            repository = _repository(context.store, workspace_id)
            target = AssignmentRole(payload.target_assignment)
            if (target is AssignmentRole.ACTIVE and payload.target_priority != 0) or (target is AssignmentRole.STANDBY and payload.target_priority < 1):
                raise ApiError("actorops_replacement_slot_invalid", "请选择一个有效的主用或备用位置。", status_code=422)
            route = repository.get_route(route_id)
            candidate = repository.get_candidate(payload.candidate_id)
            if (
                route.generation != payload.expected_route_generation
                or candidate.generation != payload.expected_candidate_generation
            ):
                raise ActorOpsConflict(
                    "route or candidate changed before replacement preview"
                )
            check = await check_replacement_preview(
                context.store,
                repository,
                build_default_registry(),
                validation_catalog(
                    context.store,
                    workspace_id=workspace_id,
                    data_dir=str(context.data_path),
                ),
                route_id=route_id,
                candidate_id=payload.candidate_id,
                max_charge_usd=payload.per_probe_cap_usd,
            )
            if not check.allowed:
                settle_replacement_preview_failure(
                    repository,
                    check,
                    route_id=route_id,
                    candidate_id=payload.candidate_id,
                    expected_candidate_generation=payload.expected_candidate_generation,
                )
                raise ApiError(
                    str(check.error_code),
                    _replacement_preview_message(str(check.error_code)),
                    status_code=409,
                )
            with repository.transaction():
                if repository.get_route(route_id).generation != payload.expected_route_generation:
                    raise ActorOpsConflict("route changed before replacement preview")
                candidate = repository.get_candidate(payload.candidate_id)
                if candidate.generation != payload.expected_candidate_generation:
                    raise ActorOpsConflict("candidate changed before replacement preview")
                plan = repository.operator.create_plan(plan_id=f"replacement-{uuid.uuid4().hex}", route_id=route_id, target_assignment=target, target_priority=payload.target_priority, proposed_candidate_id=payload.candidate_id, idempotency_key=payload.idempotency_key, created_by_user_id=str(user["id"]), per_probe_cap_usd=payload.per_probe_cap_usd, total_cap_usd=payload.total_cap_usd)
                if repository.operator.proofs_complete(plan):
                    plan = repository.operator.transition_plan(plan.plan_id, current=ReplacementStatus.PREVIEWED, target=ReplacementStatus.READY, expected_generation=plan.generation)
        except (ActorOpsConflict, ActorOpsNotFound) as error:
            raise _conflict("actorops_replacement_preview_conflict", "候选、来源或费用上限已变化，请刷新后重试。", error) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record(request, user, "actorops_v2_replacement_preview")
        response.headers["Cache-Control"] = "no-store"
        return ok(_plan_view(repository, plan))

    @app.get("/api/admin/apify-routes/{route_id}/v2-replacements/{plan_id}")
    async def replacement(route_id: str, plan_id: str, response: Response, user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        try:
            repository = _repository(context.store, str(user["workspace_id"]))
            plan = repository.operator.get_plan(plan_id)
            if plan.route_id != route_id:
                raise ActorOpsNotFound("replacement plan not found")
        except (ActorOpsNotFound, RuntimeError) as error:
            raise _unavailable(error) from error
        response.headers["Cache-Control"] = "no-store"
        return ok(_plan_view(repository, plan))

    @app.post("/api/admin/apify-routes/{route_id}/v2-replacements/{plan_id}/authorize")
    async def authorize_replacement(route_id: str, plan_id: str, payload: AuthorizeReplacementRequest, request: Request, response: Response, user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        repository, plan = _plan_for_mutation(context.store, str(user["workspace_id"]), route_id, plan_id)
        try:
            with repository.transaction():
                plan = repository.operator.transition_plan(plan_id, current=ReplacementStatus.PREVIEWED, target=ReplacementStatus.AUTHORIZED, expected_generation=payload.expected_generation)
        except ActorOpsConflict as error:
            raise _conflict("actorops_replacement_authorize_conflict", "替换计划已变化，请刷新后再确认。", error) from error
        _record(request, user, "actorops_v2_replacement_authorize")
        response.headers["Cache-Control"] = "no-store"
        return ok(_plan_view(repository, plan))

    @app.post("/api/admin/apify-routes/{route_id}/v2-replacements/{plan_id}/apply")
    async def apply_replacement(route_id: str, plan_id: str, payload: ApplyReplacementRequest, request: Request, response: Response, user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        repository, _plan = _plan_for_mutation(context.store, workspace_id, route_id, plan_id)
        try:
            with repository.transaction():
                plan = repository.operator.apply_plan(plan_id, expected_generation=payload.expected_generation)
        except ActorOpsConflict as error:
            raise _conflict("actorops_replacement_apply_conflict", "替换条件已变化或尚未完成实测。", error) from error
        _record(request, user, "actorops_v2_replacement_apply")
        response.headers["Cache-Control"] = "no-store"
        reconciliation = ActorOpsBindingReconciler(
            context.store, workspace_id=workspace_id
        ).reconcile_route(route_id)
        return ok({"plan": _plan_view(repository, plan), "route": _route(context.store, workspace_id, route_id), "binding_reconciliation": reconciliation.public()})

    @app.post("/api/admin/apify-routes/{route_id}/v2-replacements/{plan_id}/cancel")
    async def cancel_replacement(route_id: str, plan_id: str, payload: PlanGenerationRequest, request: Request, response: Response, user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        repository, _plan = _plan_for_mutation(context.store, str(user["workspace_id"]), route_id, plan_id)
        try:
            with repository.transaction():
                plan = repository.operator.cancel_plan(plan_id, expected_generation=payload.expected_generation)
        except ActorOpsConflict as error:
            raise _conflict("actorops_replacement_cancel_conflict", "替换计划已变化，请刷新后重试。", error) from error
        _record(request, user, "actorops_v2_replacement_cancel")
        response.headers["Cache-Control"] = "no-store"
        return ok(_plan_view(repository, plan))

def _register_revalidation_route(
    app: FastAPI, context: ActorOpsV2OperatorContext,
) -> None:
    @app.post("/api/admin/apify-routes/{route_id}/v2-replacements/{plan_id}/revalidate")
    async def revalidate_replacement(route_id: str, plan_id: str, payload: RevalidateReplacementRequest, request: Request, response: Response, user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        workspace_id = str(user["workspace_id"])
        repository, plan = _plan_for_mutation(
            context.store, workspace_id, route_id, plan_id
        )
        catalog = validation_catalog(
            context.store, workspace_id=workspace_id,
            data_dir=str(context.data_path),
        )
        coordinator = apify_coordinator_for_workspace(
            context.store, workspace_id=workspace_id,
            data_dir=str(context.data_path), purpose="validation",
            require_validation_key=False,
        )
        if catalog is None or coordinator is None:
            raise ApiError(
                "actorops_replacement_credential_unavailable",
                "当前没有可用的 validation 凭据，未读取历史 Dataset。",
                status_code=409,
            )
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False,
            ) as client:
                result = await revalidate_failed_replacement(
                    context.store,
                    repository,
                    build_default_registry(),
                    ApifyV2RemoteClient(
                        ApifyClient(coordinator=coordinator, http_client=client)
                    ),
                    catalog,
                    plan_id=plan.plan_id,
                    expected_generation=payload.expected_generation,
                    idempotency_key=payload.idempotency_key,
                    created_by_user_id=str(user["id"]),
                )
        except ReplacementRevalidationError as error:
            raise ApiError(
                error.code, _revalidation_message(error.code), status_code=409,
            ) from error
        except ActorOpsConflict as error:
            raise _conflict(
                "actorops_revalidation_conflict",
                "候选、来源或原实测记录已变化，请刷新后重试。",
                error,
            ) from error
        _record(request, user, "actorops_v2_replacement_revalidate")
        response.headers["Cache-Control"] = "no-store"
        return ok({
            "plan": _plan_view(repository, result.plan),
            "revalidated_attempt_count": result.proof_count,
            "new_actor_run_count": 0,
            "new_actor_cost_usd": 0,
        })


def _repository(store: Any, workspace_id: str) -> ActorOpsRepository:
    return ActorOpsAdminService(store, workspace_id=workspace_id).repository()


def _plan_for_mutation(store: Any, workspace_id: str, route_id: str, plan_id: str) -> tuple[ActorOpsRepository, Any]:
    try:
        repository = _repository(store, workspace_id)
        plan = repository.operator.get_plan(plan_id)
    except (ActorOpsNotFound, RuntimeError) as error:
        raise _unavailable(error) from error
    if plan.route_id != route_id:
        raise ApiError("not_found", "替换计划不存在。", status_code=404)
    return repository, plan


def _route(store: Any, workspace_id: str, route_id: str) -> dict[str, object]:
    return ActorOpsAdminService(store, workspace_id=workspace_id).route_summary(route_id)


def _plan_view(repository: ActorOpsRepository, plan: Any) -> dict[str, object]:
    candidate = repository.get_candidate(plan.proposed_candidate_id)
    return {
        "plan_id": plan.plan_id,
        "route_id": plan.route_id,
        "target_assignment": plan.target_assignment.value,
        "target_priority": plan.target_priority,
        "status": plan.status.value,
        "generation": plan.generation,
        "per_probe_cap_usd": plan.per_probe_cap_usd,
        "total_cap_usd": plan.total_cap_usd,
        "binding_count": plan.binding_count,
        "error_code": plan.error_code,
        **replacement_workflow_additions(
            repository,
            plan.plan_id,
            binding_count=plan.binding_count,
            status=plan.status.value,
        ),
        "candidate": actorops_v2_candidate_projection(repository, candidate),
    }


def _replacement_preview_message(code: str) -> str:
    return {
        "actorops_maintenance_actor_unavailable": "该 Actor 已不可用，未创建实测计划。",
        "actorops_maintenance_revision_changed": "固定 Build 已不可用或身份已变化，未创建实测计划。",
        "actorops_v2_candidate_contract_invalid": "候选的固定输出合同与当前 Build 不一致，未创建实测计划。",
        "actorops_replacement_contract_invalid": "候选与当前来源合同不兼容，未创建实测计划。",
        "actorops_replacement_target_native_id_missing": "候选输入要求目标平台原生用户 ID，但当前来源只保存了账号 handle/URL；请改选支持 handle 的 Actor。",
        "actorops_replacement_target_handle_missing": "候选输入要求账号 handle，但当前来源没有可验证的 handle；请先修复来源目标或改选 Actor。",
        "actorops_replacement_target_url_missing": "候选输入要求账号主页 URL，但当前来源没有可验证的 URL；请先修复来源目标或改选 Actor。",
        "actorops_replacement_target_context_missing": "候选输入依赖当前来源没有提供的目标字段，无法安全生成请求。",
        "actorops_replacement_manifest_invalid": "候选的固定 Manifest 无效，无法安全生成请求。",
        "actorops_replacement_input_contract_invalid": "候选输入模板无法转换为当前来源所需的安全请求。",
        "actorops_replacement_candidate_unavailable": "该候选已确认故障，不能用于替换。",
        "actorops_replacement_credential_unavailable": "当前没有可用的 validation 凭据，未创建实测计划。",
        "actorops_maintenance_pricing_unavailable": "无法确认该 Actor 的运行价格，未创建实测计划。",
        "actorops_maintenance_price_cap_exceeded": "该 Actor 的价格超过当前单次上限，未创建实测计划。",
        "actorops_replacement_source_missing": "替换计划包含不可用来源，未创建实测计划。",
        "actorops_replacement_target_changed": "来源目标已变化，请刷新后重新选择。",
        "actorops_replacement_route_not_ready": "路线没有可用于验证的就绪来源。",
    }.get(code, "候选未通过免费预检，未创建实测计划。")


def _revalidation_message(code: str) -> str:
    return {
        "actorops_revalidation_plan_ineligible": "只有因输出映射失败且费用已结算的替换计划可以重验。",
        "actorops_revalidation_candidate_ineligible": "原候选的失败状态不允许安全重验。",
        "actorops_revalidation_dataset_unavailable": "原实测没有可只读重验的已结算 Dataset。",
        "actorops_revalidation_binding_changed": "来源 Binding 已变化，历史结果不能作为当前证明。",
        "actorops_revalidation_source_missing": "原来源已不可用，无法核验目标身份。",
        "actorops_revalidation_target_invalid": "原来源目标已无法按当前平台规则解析。",
        "actorops_revalidation_adapter_unavailable": "当前平台 Adapter 不可用，不能安全重验。",
        "actorops_revalidation_revision_unavailable": "候选固定 Build 当前无法通过免费预检。",
        "actorops_revalidation_revision_changed": "候选固定 Manifest 已变化，不能复用历史结果。",
        "actorops_revalidation_no_evidence": "历史 Dataset 仍未产生可证明的目标账号更新。",
        "actorops_replacement_published_at_invalid": "返回的帖子发布时间字段无法解析。",
        "actorops_replacement_target_identity_mismatch": "返回的作者用户名与订阅账号不一致。",
        "actorops_replacement_output_url_invalid": "返回或派生的帖子 URL 不符合平台地址规则。",
        "actorops_replacement_output_outside_window": "返回的帖子发布时间不在原实测窗口内。",
    }.get(code, "历史 Dataset 未通过当前字段映射规则。")


def _unavailable(_error: Exception) -> ApiError:
    if isinstance(_error, ActorOpsAdminMigrationRequired):
        return ApiError(
            "actorops_v2_migration_required", "ActorOps v2 数据库迁移尚未完成。",
            status_code=503,
        )
    if isinstance(_error, ActorOpsAdminUnavailable):
        return ApiError("actorops_v2_unavailable", "ActorOps v2 当前不可用。", status_code=503)
    return ApiError("actorops_v2_unavailable", "ActorOps v2 当前不可用。", status_code=503)


def _conflict(code: str, message: str, _error: Exception) -> ApiError:
    return ApiError(code, message, status_code=409)


def _record(request: Request, user: dict[str, Any], action: str) -> None:
    request.state.operation_changed_fields = [action]
    safe_emit_operation_event(category="source", action=action, outcome="succeeded", workspace_id=str(user["workspace_id"]), actor_user_id=str(user["id"]), changed_fields=[action], route=request.scope.get("route").path, method=str(request.method), status_code=200)
    request.state.operation_logged = True


def _hash(*parts: str) -> str:
    return hashlib.sha256(json.dumps(parts, separators=(",", ":")).encode()).hexdigest()


__all__ = [
    "ensure_operator_discovery",
    "register_actorops_v2_operator_routes",
]
