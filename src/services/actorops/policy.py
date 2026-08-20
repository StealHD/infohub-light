"""Pure ActorOps v2 health and assignment policy helpers."""

from __future__ import annotations

from .domain import CandidateLifecycle, RouteHealth, RUNNABLE_LIFECYCLES


def derive_route_health(runnable_assignments: int) -> RouteHealth:
    if runnable_assignments < 0:
        raise ValueError("runnable assignment count cannot be negative")
    if runnable_assignments == 0:
        return RouteHealth.UNAVAILABLE
    if runnable_assignments == 1:
        return RouteHealth.DEGRADED
    return RouteHealth.HEALTHY


def candidate_is_runnable(
    lifecycle: CandidateLifecycle,
    *,
    build_id: str | None,
    manifest_hash: str | None,
) -> bool:
    return bool(
        lifecycle in RUNNABLE_LIFECYCLES
        and str(build_id or "").strip()
        and str(manifest_hash or "").strip()
    )
