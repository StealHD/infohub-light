"""ActorOps pool-management HTTP mutation adapters."""

from __future__ import annotations

import os
import uuid
from typing import Any, Literal, Protocol

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .actor_ops_pool_operator_routes import register_actor_ops_pool_operator_routes
from .actor_ops_verified_catalog_routes import register_actor_ops_verified_catalog_routes
from .actor_ops_auto_pool_routes import register_actor_ops_auto_pool_routes
from .responses import ok
from .system_auth import current_admin
from ..services.apify_actor_ops import ActorOpsError


class ActorOpsPoolManagementContext(Protocol):
    store: Any
    job_queue: Any
    quota: Any

    def apify_actor_ops_for(self, workspace_id: str) -> Any: ...

    def public_actor_ops_detail(self, ops: Any, route_id: str) -> dict[str, Any]: ...


class ApifyActivePoolRemoveRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_slot: Literal["primary", "backup_1", "backup_2"]
    expected_generation: StrictInt = Field(ge=1)
    confirmation: Literal["确认移出 Actor 主备池"]


class ApifyActorCandidateRefreshRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_generation: StrictInt = Field(ge=1)
    goal: Literal[
        "initial_pool", "complete_third", "upgrade_legacy",
        "compatibility_single", "add_slot", "replace_slot",
    ] = "initial_pool"
    target_slot: Literal["primary", "backup_1", "backup_2"] | None = None


class ApifyActorValidationProfileRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    candidate_id: str = Field(min_length=1, max_length=128)
    timeout_seconds: StrictInt = Field(ge=180, le=900)
    sample_items: Literal[1, 3, 5]
    max_charge_usd: float = Field(gt=0, le=0.10)
    options_hash: str = Field(
        min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"
    )


class ApifyActorCanaryBatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_generation: StrictInt = Field(ge=1)
    expected_plan_hash: str = Field(
        min_length=64, max_length=64, pattern=r"^[a-f0-9]{64}$"
    )
    approval_id: str = Field(
        min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    confirmation: Literal["确认付费验证主备"]
    goal: Literal[
        "initial_pool", "complete_third", "upgrade_legacy", "compatibility_single",
        "add_slot", "replace_slot",
    ] = "initial_pool"
    target_slot: Literal["primary", "backup_1", "backup_2"] | None = None
    max_candidates: StrictInt = Field(default=3, ge=1, le=3)
    max_total_charge_usd: float = Field(default=0.06, gt=0, le=6.06)
    candidate_ids: list[str] | None = Field(default=None, min_length=1, max_length=3)
    candidate_validation_profiles: list[ApifyActorValidationProfileRequest] | None = Field(
        default=None, min_length=1, max_length=3
    )
    target_slot_count: StrictInt | None = Field(default=None, ge=1, le=3)


class ApifyActorManualCanaryPlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: Literal[
        "initial_pool", "complete_third", "upgrade_legacy", "compatibility_single",
        "add_slot", "replace_slot",
    ]
    target_slot: Literal["primary", "backup_1", "backup_2"] | None = None
    candidate_ids: list[str] = Field(min_length=1, max_length=3)
    candidate_validation_profiles: list[ApifyActorValidationProfileRequest] = Field(
        min_length=1, max_length=3
    )
    expected_generation: StrictInt = Field(ge=1)
    target_slot_count: Literal[1, 2, 3] = 3


def validate_pool_candidate_refresh(
    ops: Any, route_id: str, *, expected_generation: int, goal: str, target_slot: str | None
) -> None:
    """Make the server authoritative for a requested add/replace refresh."""

    route = ops.get_route(route_id)
    if int(route["generation"]) != expected_generation:
        raise ActorOpsError(
            "apify_actor_route_generation_conflict",
            "Actor route changed; reload before refreshing candidates",
        )
    if goal not in {"add_slot", "replace_slot"}:
        return
    if target_slot is None:
        raise ActorOpsError(
            "apify_actor_pool_target_slot_invalid",
            "A safe target slot is required for this operation",
            status_code=422,
        )
    action = ops.slot_operations(route_id).get(target_slot, {})
    allowed = action.get("add" if goal == "add_slot" else "replace", False)
    if not allowed:
        raise ActorOpsError(
            "apify_actor_pool_slot_operation_blocked",
            "The requested Actor slot operation is currently blocked",
            status_code=409,
        )


def register_actor_ops_pool_management_routes(
    app: FastAPI, context: ActorOpsPoolManagementContext
) -> None:
    """Register the free, atomic active-pool removal endpoint."""

    register_actor_ops_pool_operator_routes(app, context)
    register_actor_ops_verified_catalog_routes(app, context)
    register_actor_ops_auto_pool_routes(app, context)

    @app.post("/api/admin/apify-routes/{route_id}/active-pool/remove")
    async def remove_active_pool_slot(
        route_id: str,
        payload: ApifyActivePoolRemoveRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        ops = context.apify_actor_ops_for(str(user["workspace_id"]))
        result = ops.remove_active_pool_slot(
            route_id,
            target_slot=payload.target_slot,
            expected_generation=int(payload.expected_generation),
            confirmation=str(payload.confirmation),
        )
        request.state.operation_changed_fields = ["active_pool_remove"]
        request.state.operation_outcome = "ok"
        response.headers["Cache-Control"] = "no-store"
        return ok({
            "schema_version": 1,
            **context.public_actor_ops_detail(ops, str(result["route_id"])),
        })

    @app.post("/api/admin/apify-routes/{route_id}/pool-candidates/refresh")
    async def refresh_pool_candidates(
        route_id: str,
        payload: ApifyActorCandidateRefreshRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        ops = context.apify_actor_ops_for(str(user["workspace_id"]))
        validate_pool_candidate_refresh(
            ops,
            route_id,
            expected_generation=int(payload.expected_generation),
            goal=payload.goal,
            target_slot=payload.target_slot,
        )
        context.quota.ensure_job_allowed(
            workspace_id=str(user["workspace_id"]), user_id=str(user["id"])
        )
        connection = context.store.connect()
        owns_transaction = not connection.in_transaction
        savepoint = f"actor_candidate_refresh_{uuid.uuid4().hex}"
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            else:
                connection.execute(f"SAVEPOINT {savepoint}")
            active_discovery = connection.execute(
                """
                SELECT run_id
                FROM apify_actor_discovery_runs
                WHERE workspace_id = ? AND route_id = ?
                  AND stage IN (
                      'queued', 'searching', 'metadata', 'ranking',
                      'static_validation', 'input_validation'
                  )
                ORDER BY created_at, rowid
                LIMIT 1
                """,
                (str(user["workspace_id"]), route_id),
            ).fetchone()
            if active_discovery is not None:
                raise ActorOpsError(
                    "apify_actor_discovery_active",
                    "The current Actor upgrade inspection is already running",
                    status_code=409,
                )
            prefer_existing = payload.goal == "upgrade_legacy"
            discovery = ops.create_discovery_run(
                route_id,
                trigger_reason=(
                    "manual_legacy_upgrade_refresh"
                    if prefer_existing
                    else (
                        "manual_compatibility_candidate_refresh"
                        if payload.goal == "compatibility_single"
                        else (
                            "manual_slot_candidate_refresh"
                            if payload.goal in {"add_slot", "replace_slot"}
                            else "manual_candidate_refresh"
                        )
                    )
                ),
                expected_generation=int(payload.expected_generation),
            )
            queued = context.job_queue.create_job(
                workspace_id=str(user["workspace_id"]),
                user_id=str(user["id"]),
                job_type="apify_actor_discovery",
                payload={
                    "run_id": str(discovery["run_id"]),
                    "prefer_existing_legacy_actors": prefer_existing,
                },
                priority=50,
                max_attempts=1,
                retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
                commit=False,
            )
            if owns_transaction:
                connection.commit()
            else:
                connection.execute(f"RELEASE {savepoint}")
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            elif not owns_transaction:
                connection.execute(f"ROLLBACK TO {savepoint}")
                connection.execute(f"RELEASE {savepoint}")
            raise
        request.state.operation_job_id = str(queued["id"])
        request.state.operation_changed_fields = ["candidate_refresh"]
        request.state.operation_outcome = "queued"
        response.headers["Cache-Control"] = "no-store"
        return ok(
            {
                "schema_version": 1,
                "route_id": route_id,
                "run_id": str(discovery["run_id"]),
                "status": "refreshing",
            }
        )
