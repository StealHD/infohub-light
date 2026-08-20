"""HTTP endpoints for automated Actor slot replacement/add orchestration."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .responses import ok
from .system_auth import current_admin


MUTATION_OPERATION_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("POST", "/api/admin/apify-routes/{route_id}/auto-pool"): (
        "source", "actor_route_auto_pool_start",
    ),
}


class ApifyAutoPoolStartRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    goal: Literal["add_slot", "replace_slot"]
    target_slot: Literal["primary", "backup_1", "backup_2"]
    expected_generation: StrictInt = Field(ge=1)
    budget_cap_usd: float = Field(default=0.50, gt=0, le=5.0)


def register_actor_ops_auto_pool_routes(app: FastAPI, context: Any) -> None:
    """Register the one-shot automated slot replacement endpoints."""

    from ..services.apify_actor_auto_pool import (
        get_auto_pool_run,
        start_auto_pool,
    )

    @app.post("/api/admin/apify-routes/{route_id}/auto-pool")
    async def start_auto_pool_run(
        route_id: str,
        payload: ApifyAutoPoolStartRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        ops = context.apify_actor_ops_for(str(user["workspace_id"]))
        result = start_auto_pool(
            ops,
            route_id=route_id,
            slot_name=payload.target_slot,
            goal=payload.goal,
            expected_generation=int(payload.expected_generation),
            admin_user_id=str(user["id"]),
            budget_cap_usd=float(payload.budget_cap_usd),
        )
        request.state.operation_changed_fields = ["auto_pool_start"]
        request.state.operation_outcome = "ok"
        response.headers["Cache-Control"] = "no-store"
        return ok({"schema_version": 1, "run": result})

    @app.get("/api/admin/apify-auto-pool-runs/{run_id}")
    async def read_auto_pool_run(
        run_id: str,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        ops = context.apify_actor_ops_for(str(user["workspace_id"]))
        result = get_auto_pool_run(ops, run_id)
        response.headers["Cache-Control"] = "no-store"
        return ok({"schema_version": 1, "run": result})


__all__ = ["register_actor_ops_auto_pool_routes"]
