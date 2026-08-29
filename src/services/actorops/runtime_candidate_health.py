"""Shared operational health for Actor candidates and ready bindings."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .domain import AssignmentRole, RouteHealth
from .policy import candidate_is_runnable
from .runtime_health_evidence import (
    active_cooldowns,
    attempt_evidence,
    candidate_retry_at,
    candidate_rows,
    next_repair_at,
    ready_bindings,
    recent_fallback_sources,
    stale_evidence,
)


_PUBLIC_HARD_FAILURE_CODES = {
    "apify_actor_deleted": "actor_deleted",
    "apify_actor_build_unavailable": "build_unavailable",
    "actorops_v2_candidate_contract_invalid": "contract_invalid",
}
_REPEATED_START_REJECTION_LIMIT = 2
_FLAPPING_MIN_ATTEMPTS = 5
_FLAPPING_FAILURE_RATIO = 0.20


@dataclass(frozen=True, slots=True)
class CandidateOperationalState:
    status: str
    issue_code: str | None
    last_success_at: str | None
    last_failure_at: str | None
    retry_at: str | None = None
    stable: bool = True
    deprioritized: bool = False

    @property
    def confirmed_failure(self) -> bool:
        return self.status == "confirmed_failure"

    def public(self) -> dict[str, object]:
        return {
            "operational_status": self.status,
            "issue_code": self.issue_code,
            "last_success_at": self.last_success_at,
            "last_failure_at": self.last_failure_at,
            "retry_at": self.retry_at,
        }


@dataclass(frozen=True, slots=True)
class RouteOperationalSummary:
    health: RouteHealth
    health_reason: str
    stable_candidate_count: int
    cooling_candidate_count: int
    at_risk_source_count: int
    unavailable_source_count: int
    fallback_source_count: int
    next_repair_at: str | None

    def public(self) -> dict[str, object]:
        return {
            "health": self.health.value,
            "health_reason": self.health_reason,
            "stable_candidate_count": self.stable_candidate_count,
            "cooling_candidate_count": self.cooling_candidate_count,
            "at_risk_source_count": self.at_risk_source_count,
            "unavailable_source_count": self.unavailable_source_count,
            "fallback_source_count": self.fallback_source_count,
            "next_repair_at": self.next_repair_at,
        }


def candidate_operational_states(
    repository: Any,
    candidates: tuple[Any, ...],
    *,
    now: datetime | None = None,
) -> dict[str, CandidateOperationalState]:
    """Classify current Candidate failures from persisted, settled evidence."""

    if not candidates:
        return {}
    current = _as_utc(now or datetime.now(timezone.utc))
    candidate_ids = tuple(dict.fromkeys(str(item.candidate_id) for item in candidates))
    rows = candidate_rows(repository, candidate_ids)
    evidence = attempt_evidence(repository, candidate_ids, current)
    stale = stale_evidence(repository, candidate_ids, current)
    retry_at = candidate_retry_at(repository, candidate_ids, current)
    states = {
        str(row["candidate_id"]): _state(
            row,
            attempts=evidence.get(str(row["candidate_id"]), ()),
            stale_sources=stale.get(str(row["candidate_id"]), frozenset()),
            retry_at=retry_at.get(str(row["candidate_id"])),
            now=current,
        )
        for row in rows
    }
    return {
        candidate_id: states.get(candidate_id, _normal_state())
        for candidate_id in candidate_ids
    }


def eligible_runtime_candidates(
    repository: Any,
    candidates: tuple[Any, ...],
    *,
    now: datetime | None = None,
) -> tuple[Any, ...]:
    """Exclude confirmed failures while leaving transient errors selectable."""

    states = candidate_operational_states(repository, candidates, now=now)
    return tuple(
        item
        for item in candidates
        if not states[str(item.candidate_id)].confirmed_failure
    )


def operational_route_summary(
    repository: Any,
    candidates: tuple[Any, ...],
    *,
    route_id: str | None = None,
    source_id: str | None = None,
    now: datetime | None = None,
) -> RouteOperationalSummary:
    """Summarize paths that ready bindings can actually use right now."""

    current = _as_utc(now or datetime.now(timezone.utc))
    states = candidate_operational_states(repository, candidates, now=current)
    runnable = {
        str(item.candidate_id): item
        for item in candidates
        if candidate_is_runnable(item)
        and not states[str(item.candidate_id)].confirmed_failure
    }
    assigned_ids = {
        candidate_id
        for candidate_id, item in runnable.items()
        if item.assignment_role is not AssignmentRole.INACTIVE
    }
    stable_ids = {
        candidate_id
        for candidate_id in runnable
        if states[candidate_id].stable and states[candidate_id].status == "normal"
    }
    resolved_route_id = str(
        route_id or (candidates[0].route_id if candidates else "")
    )
    bindings = ready_bindings(
        repository, resolved_route_id, source_id=source_id
    )
    cooldowns = active_cooldowns(
        repository, resolved_route_id, current, source_id=source_id
    )
    fallback_sources = recent_fallback_sources(
        repository, resolved_route_id, current, source_id=source_id
    )
    at_risk = 0
    unavailable = 0
    route_path_ids: set[str] = set()
    if bindings:
        for binding in bindings:
            binding_source_id = str(binding["source_id"])
            path_ids = set(assigned_ids)
            lkg_id = str(binding["last_known_good_candidate_id"] or "")
            if lkg_id in runnable:
                path_ids.add(lkg_id)
            route_path_ids.update(path_ids)
            eligible_ids = {
                candidate_id
                for candidate_id in path_ids
                if (binding_source_id, candidate_id, int(binding["binding_version"]))
                not in cooldowns
            }
            stable_paths = len(eligible_ids & stable_ids)
            if not eligible_ids:
                if binding_source_id in fallback_sources:
                    at_risk += 1
                else:
                    unavailable += 1
            elif stable_paths < 2:
                at_risk += 1
    else:
        route_path_ids.update(assigned_ids)
        if not assigned_ids:
            unavailable = 1
        elif len(assigned_ids & stable_ids) < 2:
            at_risk = 1
    if unavailable:
        health = RouteHealth.UNAVAILABLE
        reason = "source_unavailable"
    elif at_risk:
        health = RouteHealth.DEGRADED
        reason = (
            "source_fallback_only"
            if fallback_sources and not stable_ids
            else "insufficient_stable_paths"
        )
    else:
        health = RouteHealth.HEALTHY
        reason = "all_sources_redundant"
    return RouteOperationalSummary(
        health=health,
        health_reason=reason,
        stable_candidate_count=len(route_path_ids & stable_ids),
        cooling_candidate_count=len({candidate_id for _, candidate_id, _ in cooldowns}),
        at_risk_source_count=at_risk,
        unavailable_source_count=unavailable,
        fallback_source_count=len(fallback_sources),
        next_repair_at=next_repair_at(
            repository, resolved_route_id, source_id=source_id
        ),
    )


def operational_route_health(
    repository: Any,
    candidates: tuple[Any, ...],
    *,
    route_id: str | None = None,
    source_id: str | None = None,
) -> RouteHealth:
    return operational_route_summary(
        repository, candidates, route_id=route_id, source_id=source_id
    ).health


def _state(
    row: Any,
    *,
    attempts: tuple[Any, ...],
    stale_sources: frozenset[str],
    retry_at: str | None,
    now: datetime,
) -> CandidateOperationalState:
    success = str(row["last_success_at"] or "") or None
    failure = str(row["last_failure_at"] or "") or None
    current_attempts = tuple(
        attempt
        for attempt in attempts
        if not success or str(attempt["updated_at"] or "") > success
    )
    current_stale = stale_sources
    if success:
        current_stale = frozenset(
            str(item["source_id"])
            for item in current_attempts
            if str(item["error_code"] or "") == "actorops_stale_regression"
        )
    hard_issue = _hard_issue(row, current_attempts, success)
    settled_rejections = tuple(
        item for item in current_attempts
        if str(item["status"]) == "failed"
        and str(item["failure_class"] or "") == "candidate"
        and str(item["error_code"] or "") == "apify_actor_start_rejected"
        and bool(item["cost_final"])
        and float(item["actual_cost_usd"] or 0) == 0
        and _recent(item["updated_at"], now, hours=24)
    )
    paid_failures_48h = tuple(
        item for item in current_attempts
        if str(item["status"]) == "failed"
        and str(item["failure_class"] or "") == "candidate"
        and bool(item["cost_final"])
        and float(item["actual_cost_usd"] or 0) > 0
        and _recent(item["updated_at"], now, hours=48)
    )
    paid_failures_24h = tuple(
        item for item in paid_failures_48h
        if _recent(item["updated_at"], now, hours=24)
    )
    candidate_failures = tuple(
        item for item in current_attempts
        if str(item["status"]) == "failed"
        and str(item["failure_class"] or "") == "candidate"
    )
    binding_keys_24h = {
        (str(item["source_id"] or ""), int(item["binding_version"] or 0))
        for item in paid_failures_24h
    }
    binding_keys_48h = {
        (str(item["source_id"] or ""), int(item["binding_version"] or 0))
        for item in paid_failures_48h
    }
    repeated_single_binding = (
        len(binding_keys_48h) == 1
        and _three_separated_failures(paid_failures_48h)
    )
    confirmed = bool(
        hard_issue
        or len(settled_rejections) >= _REPEATED_START_REJECTION_LIMIT
        or len(binding_keys_24h) >= 2
        or repeated_single_binding
        or len(current_stale) >= 2
    )
    current_failure = _failure_is_current(row) or bool(
        candidate_failures or current_stale
    )
    totals_24h = tuple(
        item for item in attempts if _recent(item["updated_at"], now, hours=24)
    )
    failures_24h = tuple(item for item in totals_24h if str(item["status"]) == "failed")
    flapping = (
        len(totals_24h) >= _FLAPPING_MIN_ATTEMPTS
        and len(failures_24h) / len(totals_24h) > _FLAPPING_FAILURE_RATIO
    )
    if confirmed:
        issue = hard_issue
        if issue is None and len(settled_rejections) >= _REPEATED_START_REJECTION_LIMIT:
            issue = "repeated_start_rejection"
        elif issue is None and len(current_stale) >= 2:
            issue = "stale_regression"
        return CandidateOperationalState(
            "confirmed_failure", issue or "candidate_failure", success, failure,
            retry_at=retry_at, stable=False, deprioritized=True,
        )
    if current_failure:
        issue = (
            "stale_regression"
            if str(row["last_error_code"] or "") == "actorops_stale_regression"
            or current_stale
            else "candidate_failure"
        )
        return CandidateOperationalState(
            "recent_failure", issue, success, failure,
            retry_at=retry_at, stable=False, deprioritized=flapping,
        )
    return CandidateOperationalState(
        "normal", None, success, failure, retry_at=retry_at,
        stable=not flapping, deprioritized=flapping,
    )


def _hard_issue(row: Any, attempts: tuple[Any, ...], success: str | None) -> str | None:
    code = str(row["last_error_code"] or "")
    if _failure_is_current(row) and code in _PUBLIC_HARD_FAILURE_CODES:
        return _PUBLIC_HARD_FAILURE_CODES[code]
    for attempt in reversed(attempts):
        attempt_code = str(attempt["error_code"] or "")
        if attempt_code in _PUBLIC_HARD_FAILURE_CODES and (
            not success or str(attempt["updated_at"] or "") > success
        ):
            return _PUBLIC_HARD_FAILURE_CODES[attempt_code]
    return None


def _three_separated_failures(attempts: tuple[Any, ...]) -> bool:
    stamps = sorted(
        stamp for stamp in (_parse_time(item["updated_at"]) for item in attempts)
        if stamp is not None
    )
    if len(stamps) < 3:
        return False
    selected = [stamps[0]]
    for stamp in stamps[1:]:
        if stamp - selected[-1] >= timedelta(hours=5):
            selected.append(stamp)
    return len(selected) >= 3


def _normal_state() -> CandidateOperationalState:
    return CandidateOperationalState("normal", None, None, None)


def _failure_is_current(row: Any) -> bool:
    failure = str(row["last_failure_at"] or "")
    success = str(row["last_success_at"] or "")
    return bool(failure and (not success or failure > success))


def _recent(value: object, now: datetime, *, hours: int) -> bool:
    stamp = _parse_time(value)
    return bool(stamp and now - timedelta(hours=hours) <= stamp <= now)


def _parse_time(value: object) -> datetime | None:
    try:
        return _as_utc(datetime.fromisoformat(str(value or "").replace("Z", "+00:00")))
    except ValueError:
        return None


def _as_utc(value: datetime) -> datetime:
    return (
        value.replace(tzinfo=timezone.utc)
        if value.tzinfo is None
        else value.astimezone(timezone.utc)
    )


__all__ = [
    "CandidateOperationalState",
    "RouteOperationalSummary",
    "candidate_operational_states",
    "eligible_runtime_candidates",
    "operational_route_health",
    "operational_route_summary",
]
