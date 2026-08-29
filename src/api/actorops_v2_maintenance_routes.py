"""Owner/Admin controls for bounded, default-on v2 maintenance."""

from __future__ import annotations

from typing import Any, Literal, Protocol

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from .responses import ApiError, ok
from .system_auth import current_admin
from ..services.actorops.admin_service import (
    ActorOpsAdminMigrationRequired,
    ActorOpsAdminService,
    ActorOpsAdminUnavailable,
)
from ..services.actorops.recovery_probe import (
    RECOVERY_INTENT,
    recovery_job_payload,
    recovery_target_is_current,
)
from ..services.actorops.repository import (
    ActorOpsConflict,
    ActorOpsNotFound,
    ActorOpsRepository,
)
from ..services.operation_log import safe_emit_operation_event
from ..services.system_settings import resolve_system_setting


class ActorOpsV2MaintenanceContext(Protocol):
    store: Any
    job_queue: Any


MUTATION_OPERATION_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("PATCH", "/api/admin/apify-maintenance-policy"): (
        "source", "actorops_v2_workspace_maintenance_policy_update",
    ),
    ("PATCH", "/api/admin/apify-routes/{route_id}/maintenance-policy"): (
        "source", "actorops_v2_route_maintenance_policy_update",
    ),
    (
        "POST",
        "/api/admin/apify-routes/{route_id}/v2-candidates/{candidate_id}/recovery-probe",
    ): ("source", "actorops_v2_candidate_recovery_probe"),
}


class MaintenancePolicyPatch(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool
    expected_generation: StrictInt = Field(ge=1)


class CandidateRecoveryProbeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    source_id: str = Field(min_length=1, max_length=128)
    expected_route_generation: StrictInt = Field(ge=1)
    expected_candidate_generation: StrictInt = Field(ge=1)
    expected_binding_version: StrictInt = Field(ge=1)
    expected_last_failure_at: str = Field(min_length=1, max_length=64)
    idempotency_key: str = Field(
        min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    confirmation: Literal["确认实测恢复 Actor"]


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

    @app.post(
        "/api/admin/apify-routes/{route_id}/v2-candidates/{candidate_id}/recovery-probe"
    )
    async def create_candidate_recovery_probe(
        route_id: str,
        candidate_id: str,
        payload: CandidateRecoveryProbeRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        try:
            job, created = _queue_recovery_probe(
                context,
                workspace_id=str(user["workspace_id"]),
                user_id=str(user["id"]),
                route_id=route_id,
                candidate_id=candidate_id,
                payload=payload,
            )
        except (ActorOpsConflict, ActorOpsNotFound) as error:
            raise ApiError(
                "actorops_v2_recovery_probe_conflict",
                "候选、来源、故障状态或维护预算已变化，请刷新后重试。",
                status_code=409,
            ) from error
        except RuntimeError as error:
            raise _unavailable(error) from error
        _record_recovery_probe(request, user, job=job, created=created)
        response.headers["Cache-Control"] = "no-store"
        return ok({
            "route_id": route_id,
            "candidate_id": candidate_id,
            "source_id": payload.source_id,
            "job_id": str(job["id"]),
            "status": str(job["status"]),
            "queued": str(job["status"]) == "queued",
            "deduplicated": not created,
        })


def _queue_recovery_probe(
    context: ActorOpsV2MaintenanceContext,
    *,
    workspace_id: str,
    user_id: str,
    route_id: str,
    candidate_id: str,
    payload: CandidateRecoveryProbeRequest,
) -> tuple[dict[str, Any], bool]:
    _workspace_policy(context.store, workspace_id)
    repository = ActorOpsRepository(context.store.connect(), workspace_id)
    job_payload = recovery_job_payload(
        route_id=route_id,
        candidate_id=candidate_id,
        source_id=payload.source_id,
        binding_version=payload.expected_binding_version,
        expected_route_generation=payload.expected_route_generation,
        expected_candidate_generation=payload.expected_candidate_generation,
        expected_last_failure_at=payload.expected_last_failure_at,
        idempotency_key=payload.idempotency_key,
    )
    with repository.transaction():
        existing = _existing_recovery_job(
            context, workspace_id, payload.idempotency_key
        )
        if existing is not None:
            if existing.get("payload_json") != job_payload:
                raise ActorOpsConflict("recovery Probe idempotency key changed")
            return existing, False
        route = repository.get_route(route_id)
        candidate = repository.get_candidate(candidate_id)
        binding = repository.get_binding(payload.source_id)
        policy = repository.maintenance.effective_policy(route_id)
        if (
            route.generation != payload.expected_route_generation
            or candidate.generation != payload.expected_candidate_generation
            or candidate.route_id != route_id
            or binding.route_id != route_id
            or binding.status != "ready"
            or binding.binding_version != payload.expected_binding_version
            or not policy.authorized
            or policy.max_charge_usd <= 0
            or not recovery_target_is_current(
                repository,
                candidate,
                expected_last_failure_at=payload.expected_last_failure_at,
            )
        ):
            raise ActorOpsConflict("recovery Probe target changed")
        job = context.job_queue.create_job(
            workspace_id=workspace_id,
            user_id=user_id,
            source_id=payload.source_id,
            job_type="actorops_v2_maintenance",
            payload=job_payload,
            priority=-10,
            max_attempts=1,
            retention_days=int(resolve_system_setting(
                context.store, workspace_id, "jobs.retention_days",
                connection=repository.connection,
            )),
            commit=False,
        )
    return job, True


def _existing_recovery_job(
    context: ActorOpsV2MaintenanceContext,
    workspace_id: str,
    idempotency_key: str,
) -> dict[str, Any] | None:
    row = context.store.connect().execute(
        """SELECT id FROM fetch_jobs WHERE workspace_id=?
             AND job_type='actorops_v2_maintenance'
             AND json_extract(payload_json, '$.intent')=?
             AND json_extract(payload_json, '$.idempotency_key')=?
             ORDER BY created_at, id LIMIT 1""",
        (workspace_id, RECOVERY_INTENT, idempotency_key),
    ).fetchone()
    return context.job_queue.get_job(str(row["id"])) if row is not None else None


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


def _record_recovery_probe(
    request: Request,
    user: dict[str, Any],
    *,
    job: dict[str, Any],
    created: bool,
) -> None:
    request.state.operation_job_id = str(job["id"])
    request.state.operation_source_id = str(job.get("source_id") or "") or None
    safe_emit_operation_event(
        category="source",
        action="actorops_v2_candidate_recovery_probe",
        outcome="queued" if created else "skipped",
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        job_id=str(job["id"]),
        source_id=request.state.operation_source_id,
        counts={"deduplicated": int(not created)},
        route=(
            "/api/admin/apify-routes/{route_id}/v2-candidates/"
            "{candidate_id}/recovery-probe"
        ),
        method="POST",
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
