"""Safe additive v2 projections for the established ActorOps admin facade."""

from __future__ import annotations

from datetime import datetime, timezone
import json
from typing import Any

from ..services.actorops.domain import AssignmentRole, CandidateRecord, RouteHealth
from ..services.actorops.presentation_mapping import CandidatePresentationMappings
from ..services.actorops.discovery_mapping_issues import candidate_mapping_issue
from ..services.actorops.compatibility_projection import candidate_compatibility
from ..services.actorops.readiness import require_actorops_v2_schema
from ..services.actorops.repository import ActorOpsRepository
from ..services.actorops.runtime_candidate_health import (
    CandidateOperationalState,
    candidate_operational_states,
    operational_route_summary,
)


def actorops_v2_route_additions(
    store: Any, workspace_id: str, route_id: str
) -> dict[str, object] | None:
    """Return current v2 facts or fail closed when global 30 is absent."""

    require_actorops_v2_schema(store)
    repository = ActorOpsRepository(store.connect(), str(workspace_id))
    route = repository.get_route(route_id)
    candidates = repository.list_route_candidates(route_id)
    bindings = repository.list_route_bindings(route_id)
    metadata = repository.operator.list_metadata(route_id)
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
    states = candidate_operational_states(repository, candidates)
    operational = operational_route_summary(
        repository, candidates, route_id=route_id
    )
    health = operational.health
    effective = repository.maintenance.effective_policy(route_id)
    budget = repository.maintenance.probe_budget(route_id, datetime.now(timezone.utc))
    return {
        "actorops_version": 2,
        "route_generation": route.generation,
        **operational.public(),
        "runtime_mode": route.runtime_mode.value,
        "per_run_cap_usd": route.per_run_cap_usd,
        "active_candidate": _candidate(
            active,
            metadata.get(active.candidate_id) if active else None,
            repository,
            states.get(active.candidate_id) if active else None,
        ),
        "standby_candidates": [
            _candidate(
                item,
                metadata.get(item.candidate_id),
                repository,
                states.get(item.candidate_id),
            )
            for item in standby
        ],
        "last_known_good": _candidate(
            lkg,
            metadata.get(lkg.candidate_id) if lkg else None,
            repository,
            states.get(lkg.candidate_id) if lkg else None,
        ),
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
        "authorization_origin": _authorization_origin(workspace),
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
            "authorization_origin": _authorization_origin(route),
            "generation": int(route.generation),
        },
        "budget": {
            "spent_usd": round(float(spent_usd), 6),
            "reserved_usd": round(float(reserved_usd), 6),
            "probe_count": int(probe_count),
        },
    }


def _require_enabled(store: Any) -> None:
    require_actorops_v2_schema(store)


def _authorization_origin(policy: Any) -> str:
    value = str(getattr(policy, "authorization_origin", "none"))
    return value if value in {"system_default", "operator", "none"} else "none"


def actorops_v2_candidate_projection(
    repository: ActorOpsRepository, candidate: CandidateRecord
) -> dict[str, object]:
    return _candidate(candidate, repository.operator.metadata(candidate.candidate_id), repository) or {}


def _candidate(
    candidate: CandidateRecord | None,
    metadata: Any | None,
    repository: ActorOpsRepository,
    state: CandidateOperationalState | None = None,
) -> dict[str, object] | None:
    if candidate is None:
        return None
    state = state or candidate_operational_states(repository, (candidate,))[
        candidate.candidate_id
    ]
    return {
        "candidate_id": candidate.candidate_id,
        "build_number": candidate.build_number,
        "lifecycle": candidate.lifecycle.value,
        "assignment": candidate.assignment_role.value,
        "priority": candidate.priority,
        "generation": candidate.generation,
        "mapping_issue_code": candidate_mapping_issue(candidate),
        **candidate_compatibility(repository, candidate),
        **state.public(),
        "avatar_mapping_status": CandidatePresentationMappings(repository).status(
            candidate
        ),
        "store_metadata": _metadata(metadata),
        "evidence_progress": _evidence(repository, candidate),
    }


def _metadata(value: Any | None) -> dict[str, object] | None:
    if value is None:
        return None
    try:
        pricing = json.loads(value.pricing_json)
    except (TypeError, ValueError):
        pricing = []
    return {
        "actor_slug": value.actor_slug, "display_name": value.display_name,
        "short_description": value.short_description, "developer_name": value.developer_name,
        "maintained_by_apify": value.maintained_by_apify, "rating": value.rating,
        "review_count": value.review_count, "bookmark_count": value.bookmark_count,
        "total_users": value.total_users, "monthly_active_users": value.monthly_active_users,
        "pricing": pricing if isinstance(pricing, list) else [], "last_modified_at": value.last_modified_at,
        "observed_at": value.observed_at, "generation": value.generation,
    }


def _evidence(repository: ActorOpsRepository, candidate: CandidateRecord) -> dict[str, int]:
    total = len(repository.operator.binding_set(candidate.route_id))
    verified = int(repository.connection.execute(
        """SELECT COUNT(DISTINCT target_fingerprint) FROM actor_attempts_v2
           WHERE workspace_id=? AND candidate_id=? AND kind='probe' AND status='succeeded'
             AND semantic_outcome='valid_nonempty' AND cost_final=1""",
        (repository.workspace_id, candidate.candidate_id),
    ).fetchone()[0])
    return {"verified_bindings": min(verified, total), "required_bindings": total}


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
    "actorops_v2_candidate_projection",
    "actorops_v2_route_policy",
    "actorops_v2_workspace_policy",
    "public_maintenance_policy",
]
