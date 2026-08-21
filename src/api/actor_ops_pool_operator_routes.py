"""Atomic, zero-run ActorOps pool operator endpoints."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .responses import ok
from .system_auth import current_admin


MUTATION_OPERATION_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("POST", "/api/admin/apify-routes/{route_id}/active-pool/promote"): (
        "source", "actor_route_pool_promote",
    ),
    ("PATCH", "/api/admin/apify-routes/{route_id}/price-cap"): (
        "source", "actor_route_price_cap_update",
    ),
}

class ApifyActivePoolPromoteRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    target_slot: Literal["backup_1", "backup_2"]
    expected_generation: StrictInt = Field(ge=1)
    confirmation: Literal["确认设为主用 Actor"]


class ApifyRoutePriceCapRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_generation: StrictInt = Field(ge=1)
    per_run_cap_usd: float = Field(gt=0, le=0.20)


def register_actor_ops_pool_operator_routes(app: FastAPI, context: Any) -> None:
    """Register non-billable primary selection and future-run cap controls."""

    @app.post("/api/admin/apify-routes/{route_id}/active-pool/promote")
    async def promote_active_pool_slot(
        route_id: str,
        payload: ApifyActivePoolPromoteRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        ops = context.apify_actor_ops_for(str(user["workspace_id"]))
        result = ops.promote_active_pool_slot(
            route_id,
            target_slot=payload.target_slot,
            expected_generation=int(payload.expected_generation),
            confirmation=str(payload.confirmation),
        )
        request.state.operation_changed_fields = ["active_pool_primary"]
        request.state.operation_outcome = "ok"
        response.headers["Cache-Control"] = "no-store"
        return ok({
            "schema_version": 1,
            **context.public_actor_ops_detail(ops, str(result["route_id"])),
        })

    @app.patch("/api/admin/apify-routes/{route_id}/price-cap")
    async def set_route_price_cap(
        route_id: str,
        payload: ApifyRoutePriceCapRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        ops = context.apify_actor_ops_for(str(user["workspace_id"]))
        result = ops.set_route_price_cap(
            route_id,
            per_run_cap_usd=float(payload.per_run_cap_usd),
            expected_generation=int(payload.expected_generation),
        )
        request.state.operation_changed_fields = ["per_run_cap_usd"]
        request.state.operation_outcome = "ok"
        response.headers["Cache-Control"] = "no-store"
        return ok({
            "schema_version": 1,
            **context.public_actor_ops_detail(ops, str(result["route_id"])),
        })


__all__ = ["register_actor_ops_pool_operator_routes"]
