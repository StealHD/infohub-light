"""Stable, authenticated 410 responses for retired ActorOps v1 admin APIs."""

from __future__ import annotations

from collections.abc import Sequence
from typing import Any

from fastapi import Depends, FastAPI, Request

from .responses import ApiError
from .system_auth import current_admin


RETIRED_ACTOROPS_V1_ROUTES: tuple[tuple[str, str], ...] = (
    ("GET", "/api/admin/apify-routes/{route_id}/pool-candidates"),
    ("PUT", "/api/admin/apify-routes/{route_id}/active-pool"),
    ("POST", "/api/admin/apify-routes/{route_id}/active-pool/remove"),
    ("POST", "/api/admin/apify-routes/{route_id}/active-pool/activate"),
    ("POST", "/api/admin/apify-routes/{route_id}/verified-pool-activation"),
    ("PATCH", "/api/admin/apify-routes/{route_id}/freshness-settings"),
    ("GET", "/api/admin/apify-routes/{route_id}/freshness-plan"),
    ("POST", "/api/admin/apify-routes/{route_id}/freshness-checks"),
    ("GET", "/api/admin/apify-freshness-checks/{check_id}"),
    ("POST", "/api/admin/apify-support-checks"),
    ("GET", "/api/admin/apify-discovery-runs/{run_id}"),
    ("GET", "/api/admin/apify-discovery-runs/{run_id}/canary-plan"),
    ("POST", "/api/admin/apify-discovery-runs/{run_id}/canary-plan"),
    ("POST", "/api/admin/apify-discovery-runs/{run_id}/canary-batches"),
    (
        "POST",
        "/api/admin/apify-discovery-runs/{run_id}/candidates/{revision_id}/canary",
    ),
    ("GET", "/api/admin/apify-canary-batches/{batch_id}"),
    ("PATCH", "/api/admin/sources/{source_id}/apify-preference"),
    (
        "POST",
        "/api/admin/sources/{source_id}/apify-validations/{revision_id}/canary",
    ),
    ("POST", "/api/admin/apify-actor-evaluations/{evaluation_id}/retry"),
    ("POST", "/api/admin/apify-routes/{route_id}/validations/reconcile"),
    ("GET", "/api/admin/apify-discovery-settings"),
    ("PATCH", "/api/admin/apify-discovery-settings"),
    ("POST", "/api/admin/apify-discovery-measurements"),
    ("GET", "/api/admin/apify-actor-routes/x/profile"),
    ("PUT", "/api/admin/apify-actor-routes/x/profile/order"),
    (
        "POST",
        "/api/admin/apify-actor-routes/x/profile/candidates/{candidate_id}/enable",
    ),
    (
        "POST",
        "/api/admin/apify-actor-routes/x/profile/candidates/{candidate_id}/disable",
    ),
    (
        "POST",
        "/api/admin/apify-actor-routes/x/profile/candidates/{candidate_id}/canary",
    ),
)


async def _retired_actorops_v1_endpoint(
    _request: Request,
    _user: dict[str, Any] = Depends(current_admin),
) -> None:
    raise ApiError(
        "actorops_v1_retired",
        "ActorOps v1 admin API 已退役。",
        status_code=410,
        retryable=False,
        action="Use the ActorOps v2 Route, Discovery, Binding or Replacement API.",
    )


def register_actorops_retired_routes(
    app: FastAPI,
    *,
    routes: Sequence[tuple[str, str]] = RETIRED_ACTOROPS_V1_ROUTES,
) -> None:
    """Register retired methods without retaining legacy request schemas."""

    for method, path in routes:
        app.add_api_route(
            path,
            _retired_actorops_v1_endpoint,
            methods=[method],
            name=f"actorops_v1_retired_{method.lower()}_{len(app.routes)}",
            include_in_schema=False,
        )


__all__ = ["RETIRED_ACTOROPS_V1_ROUTES", "register_actorops_retired_routes"]
