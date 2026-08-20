"""HTTP endpoint for activating a settled ActorOps catalog entry."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .responses import ok
from .system_auth import current_admin


MUTATION_OPERATION_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("POST", "/api/admin/apify-routes/{route_id}/verified-pool-activation"): (
        "source", "actor_route_verified_catalog_activate",
    ),
}


class ApifyVerifiedPoolActivationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    run_id: str = Field(min_length=1, max_length=128)
    goal: Literal[
        "initial_pool", "complete_third", "upgrade_legacy", "compatibility_single",
        "add_slot", "replace_slot",
    ]
    candidate_ids: list[str] = Field(min_length=1, max_length=3)
    expected_generation: StrictInt = Field(ge=1)
    target_slot_count: Literal[1, 2, 3]
    target_slot: Literal["primary", "backup_1", "backup_2"] | None = None
    apply_id: str = Field(
        min_length=16, max_length=128, pattern=r"^[A-Za-z0-9._:-]+$"
    )
    confirmation: Literal["确认启用 Actor 主备"]


def register_actor_ops_verified_catalog_routes(app: FastAPI, context: Any) -> None:
    """Register the no-Canary activation path for settled catalog items."""

    @app.post("/api/admin/apify-routes/{route_id}/verified-pool-activation")
    async def activate_verified_pool_candidates(
        route_id: str,
        payload: ApifyVerifiedPoolActivationRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        ops = context.apify_actor_ops_for(str(user["workspace_id"]))
        result = ops.activate_verified_pool_candidates(
            route_id,
            run_id=payload.run_id,
            goal=payload.goal,
            candidate_ids=list(payload.candidate_ids),
            expected_generation=int(payload.expected_generation),
            target_slot_count=int(payload.target_slot_count),
            target_slot=payload.target_slot,
            apply_id=payload.apply_id,
            confirmation=str(payload.confirmation),
        )
        request.state.operation_changed_fields = ["verified_actor_pool_activation"]
        request.state.operation_outcome = "ok"
        response.headers["Cache-Control"] = "no-store"
        return ok({
            "schema_version": 1,
            **context.public_actor_ops_detail(ops, str(result["route_id"])),
        })
