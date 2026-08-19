"""Read-only Apify ActorOps HTTP adapters."""

from datetime import datetime
from typing import Any, Literal

from fastapi import Depends, FastAPI, Query, Response

from .actor_ops_projection import (
    public_actor_ops_route,
    public_canary_batch,
    public_canary_plan,
)
from .context import ApiContext
from .responses import ok
from .system_auth import api_context, current_admin
from ..services.apify_actor_ops import supported_route_profiles


async def admin_apify_routes(
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    ops = context.apify_actor_ops_for(str(user["workspace_id"]))
    routes = [
        public_actor_ops_route(ops, ops.get_route(str(route["route_id"])))
        for route in ops.list_routes()
    ]
    response.headers["Cache-Control"] = "no-store"
    return ok(
        {
            "schema_version": 1,
            "generation": ops.catalog_generation(),
            "support_profiles": supported_route_profiles(),
            "routes": routes,
        }
    )


async def admin_apify_route_detail(
    route_id: str,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    result = context.public_actor_ops_detail(
        context.apify_actor_ops_for(str(user["workspace_id"])), route_id
    )
    response.headers["Cache-Control"] = "no-store"
    return ok({"schema_version": 1, **result})


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
    result = context.apify_actor_ops_for(
        str(user["workspace_id"])
    ).list_verified_pool_candidates(route_id, goal=goal, target_slot=target_slot)
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


async def admin_apify_actor_events(
    response: Response,
    route_id: str | None = Query(default=None, max_length=128),
    source_id: str | None = Query(default=None, max_length=128),
    candidate_id: str | None = Query(default=None, max_length=128),
    phase: str | None = Query(default=None, max_length=96),
    outcome: str | None = Query(default=None, max_length=96),
    since: datetime | None = Query(default=None),
    until: datetime | None = Query(default=None),
    cursor: str | None = Query(default=None, max_length=512),
    limit: int = Query(default=50, ge=1, le=100),
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    result = context.apify_actor_resilience_for(
        str(user["workspace_id"])
    ).list_events(
        route_id=route_id,
        source_id=source_id,
        candidate_id=candidate_id,
        phase=phase,
        outcome=outcome,
        since=since,
        until=until,
        cursor=cursor,
        limit=limit,
    )
    response.headers["Cache-Control"] = "no-store"
    return ok(result)


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
    plan = context.apify_actor_ops_for(
        str(user["workspace_id"])
    ).get_canary_plan(run_id, goal=goal, target_slot=target_slot)
    response.headers["Cache-Control"] = "no-store"
    return ok(public_canary_plan(plan))


async def admin_apify_canary_batch(
    batch_id: str,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    batch = context.apify_actor_ops_for(
        str(user["workspace_id"])
    ).get_canary_batch(batch_id)
    response.headers["Cache-Control"] = "no-store"
    return ok(public_canary_batch(batch))


def register_actor_ops_route_read_routes(app: FastAPI) -> None:
    """Register route list/detail/pool queries in their stable order."""

    app.add_api_route(
        "/api/admin/apify-routes", admin_apify_routes, methods=["GET"]
    )
    app.add_api_route(
        "/api/admin/apify-routes/{route_id}",
        admin_apify_route_detail,
        methods=["GET"],
    )
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


def register_actor_ops_events_route(app: FastAPI) -> None:
    """Register the Actor event query at its stable position."""

    app.add_api_route(
        "/api/admin/apify-actor-events",
        admin_apify_actor_events,
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
