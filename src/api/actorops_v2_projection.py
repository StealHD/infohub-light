"""Safe additive v2 projections for the established ActorOps admin facade."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from ..services.actorops.domain import AssignmentRole, CandidateRecord, RouteHealth
from ..services.actorops.readiness import actorops_v2_enabled, require_actorops_v2_if_enabled
from ..services.actorops.repository import ActorOpsRepository


def actorops_v2_route_additions(
    store: Any, workspace_id: str, route_id: str
) -> dict[str, object] | None:
    """Return no v2 facts at all while the global flag is disabled."""

    if not actorops_v2_enabled():
        return None
    require_actorops_v2_if_enabled(store)
    repository = ActorOpsRepository(store.connect(), str(workspace_id))
    route = repository.get_route(route_id)
    candidates = repository.list_route_candidates(route_id)
    bindings = repository.list_route_bindings(route_id)
    active = next(
        (item for item in candidates if item.assignment_role is AssignmentRole.ACTIVE),
        None,
    )
    standby = [
        item for item in candidates if item.assignment_role is AssignmentRole.STANDBY
    ]
    lkg_ids = {
        str(item.last_known_good_candidate_id)
        for item in bindings if item.last_known_good_candidate_id
    }
    lkg = next((item for item in candidates if item.candidate_id in lkg_ids), None)
    health = repository.route_health(route_id)
    effective = repository.maintenance.effective_policy(route_id)
    budget = repository.maintenance.probe_budget(route_id, datetime.now(timezone.utc))
    return {
        "actorops_version": 2,
        "route_generation": route.generation,
        "health": health.value,
        "runtime_mode": route.runtime_mode.value,
        "active_candidate": _candidate(active),
        "standby_candidates": [_candidate(item) for item in standby],
        "last_known_good": _candidate(lkg),
        "last_success_at": max(
            (str(item.last_success_at) for item in bindings if item.last_success_at),
            default=None,
        ),
        "degraded_reason": _degraded_reason(route.runtime_mode.value, health, bindings),
        "binding_summary": {
            "ready_count": sum(item.status == "ready" for item in bindings),
            "pending_count": sum(item.status != "ready" for item in bindings),
        },
        "maintenance_policy": public_maintenance_policy(
            effective.workspace, effective.route, authorized=effective.authorized,
            spent_usd=budget.spent_usd, reserved_usd=budget.reserved_usd,
            probe_count=budget.probe_count,
        ),
    }


def actorops_v2_workspace_policy(store: Any, workspace_id: str) -> dict[str, object]:
    _require_enabled(store)
    policy = ActorOpsRepository(store.connect(), str(workspace_id)).maintenance.get_policy(None)
    return public_maintenance_policy(policy, None, authorized=False)


def actorops_v2_route_policy(
    store: Any, workspace_id: str, route_id: str
) -> dict[str, object]:
    _require_enabled(store)
    repository = ActorOpsRepository(store.connect(), str(workspace_id))
    effective = repository.maintenance.effective_policy(route_id)
    budget = repository.maintenance.probe_budget(route_id, datetime.now(timezone.utc))
    return public_maintenance_policy(
        effective.workspace, effective.route, authorized=effective.authorized,
        spent_usd=budget.spent_usd, reserved_usd=budget.reserved_usd,
        probe_count=budget.probe_count,
    )


def public_maintenance_policy(
    workspace: Any,
    route: Any | None,
    *,
    authorized: bool,
    spent_usd: float = 0.0,
    reserved_usd: float = 0.0,
    probe_count: int = 0,
) -> dict[str, object]:
    """Expose policy state without identifying the authorizer or a target."""

    workspace_view = {
        "enabled": bool(workspace.enabled),
        "monthly_budget_usd": workspace.monthly_budget_usd,
        "generation": int(workspace.generation),
    }
    if route is None:
        return {"schema_version": 2, **workspace_view, "authorized": bool(authorized)}
    return {
        "schema_version": 2,
        "authorized": bool(authorized),
        "workspace": workspace_view,
        "route": {
            "enabled": bool(route.enabled),
            "max_probe_usd": route.max_probe_usd,
            "max_probes_per_utc_day": route.max_probes_per_utc_day,
            "auto_add_standby": route.auto_add_standby,
            "auto_replace_non_last": route.auto_replace_non_last,
            "generation": int(route.generation),
        },
        "budget": {
            "spent_usd": round(float(spent_usd), 6),
            "reserved_usd": round(float(reserved_usd), 6),
            "probe_count": int(probe_count),
        },
    }


def _require_enabled(store: Any) -> None:
    if not actorops_v2_enabled():
        raise RuntimeError("actorops_v2_disabled")
    require_actorops_v2_if_enabled(store)


def _candidate(candidate: CandidateRecord | None) -> dict[str, object] | None:
    if candidate is None:
        return None
    return {
        "candidate_id": candidate.candidate_id,
        "actor_id": candidate.actor_id,
        "publisher": candidate.publisher,
        "build_number": candidate.build_number,
        "lifecycle": candidate.lifecycle.value,
        "assignment": candidate.assignment_role.value,
        "priority": candidate.priority,
        "generation": candidate.generation,
    }


def _degraded_reason(mode: str, health: RouteHealth, bindings: tuple[Any, ...]) -> str | None:
    if mode == "disabled":
        return "actorops_v2_route_disabled"
    if any(item.status != "ready" for item in bindings):
        return "actorops_v2_binding_not_ready"
    if health is RouteHealth.UNAVAILABLE:
        return "actorops_v2_no_runnable_candidate"
    if health is RouteHealth.DEGRADED:
        return "actorops_v2_single_runnable_candidate"
    return None


__all__ = [
    "actorops_v2_route_additions",
    "actorops_v2_route_policy",
    "actorops_v2_workspace_policy",
    "public_maintenance_policy",
]
