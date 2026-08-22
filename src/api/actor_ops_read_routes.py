"""Read-only Apify ActorOps HTTP adapters."""

from typing import Any, Literal

from fastapi import Depends, FastAPI, Query, Response

from .actor_ops_projection import public_canary_batch, public_canary_plan
from .context import ApiContext
from .responses import ok
from .system_auth import api_context, current_admin
from ..services.apify_actor_ops import ApifyActorOpsService


async def admin_apify_pool_candidates(
    route_id: str,
    response: Response,
    goal: Literal[
        "initial_pool",
        "complete_third",
        "upgrade_legacy",
        "compatibility_single",
        "add_slot",
        "replace_slot",
    ] = Query(...),
    target_slot: Literal["primary", "backup_1", "backup_2"] | None = Query(default=None),
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    result = _legacy_ops(context, str(user["workspace_id"])).list_verified_pool_candidates(
        route_id, goal=goal, target_slot=target_slot
    )
    response.headers["Cache-Control"] = "no-store"
    return ok(result)


async def admin_apify_freshness_plan(
    route_id: str,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    result = context.apify_actor_resilience_for(
        str(user["workspace_id"])
    ).freshness_plan(route_id)
    response.headers["Cache-Control"] = "no-store"
    return ok({"schema_version": 1, **result})


async def admin_apify_freshness_check_detail(
    check_id: str,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    result = context.apify_actor_resilience_for(
        str(user["workspace_id"])
    ).get_freshness_check(check_id)
    response.headers["Cache-Control"] = "no-store"
    return ok({"schema_version": 1, **result})


async def admin_apify_canary_plan(
    run_id: str,
    response: Response,
    goal: Literal[
        "initial_pool",
        "complete_third",
        "upgrade_legacy",
        "compatibility_single",
        "add_slot",
        "replace_slot",
    ] = Query(default="initial_pool"),
    target_slot: Literal["primary", "backup_1", "backup_2"] | None = Query(default=None),
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    plan = _legacy_ops(context, str(user["workspace_id"])).get_canary_plan(
        run_id, goal=goal, target_slot=target_slot
    )
    response.headers["Cache-Control"] = "no-store"
    return ok(public_canary_plan(plan))


async def admin_apify_canary_batch(
    batch_id: str,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    batch = _legacy_ops(context, str(user["workspace_id"])).get_canary_batch(batch_id)
    response.headers["Cache-Control"] = "no-store"
    return ok(public_canary_batch(batch))


def register_actor_ops_legacy_read_routes(app: FastAPI) -> None:
    """Keep only pre-retirement Pool/Canary reads on the legacy service."""

    app.add_api_route(
        "/api/admin/apify-routes/{route_id}/pool-candidates",
        admin_apify_pool_candidates,
        methods=["GET"],
    )


def register_actor_ops_freshness_plan_route(app: FastAPI) -> None:
    """Register the freshness plan query at its stable position."""

    app.add_api_route(
        "/api/admin/apify-routes/{route_id}/freshness-plan",
        admin_apify_freshness_plan,
        methods=["GET"],
    )


def register_actor_ops_freshness_detail_route(app: FastAPI) -> None:
    """Register the freshness check detail query at its stable position."""

    app.add_api_route(
        "/api/admin/apify-freshness-checks/{check_id}",
        admin_apify_freshness_check_detail,
        methods=["GET"],
    )


def register_actor_ops_canary_plan_read_route(app: FastAPI) -> None:
    """Register the Canary plan query at its stable position."""

    app.add_api_route(
        "/api/admin/apify-discovery-runs/{run_id}/canary-plan",
        admin_apify_canary_plan,
        methods=["GET"],
    )


def register_actor_ops_canary_batch_read_route(app: FastAPI) -> None:
    """Register the Canary batch query at its stable position."""

    app.add_api_route(
        "/api/admin/apify-canary-batches/{batch_id}",
        admin_apify_canary_batch,
        methods=["GET"],
    )


def _legacy_ops(context: ApiContext, workspace_id: str) -> ApifyActorOpsService:
    return ApifyActorOpsService(context.store, workspace_id=workspace_id)
