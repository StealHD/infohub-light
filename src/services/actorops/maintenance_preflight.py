"""Settle free maintenance preflight failures without creating paid facts."""

from __future__ import annotations

from typing import Any, Literal

from .domain import FailureClass
from .repository_errors import ActorOpsConflict


PreflightDisposition = Literal["deferred", "hard_failed", "candidate_changed"]

_HARD_FAILURE_CODES = {
    "actorops_v2_candidate_contract_invalid": "actorops_v2_candidate_contract_invalid",
    "actorops_discovery_actor_unavailable": "apify_actor_deleted",
    "actorops_discovery_catalog_not_found": "apify_actor_deleted",
    "actorops_maintenance_actor_unavailable": "apify_actor_deleted",
    "actorops_discovery_exact_build_missing": "apify_actor_build_unavailable",
    "actorops_discovery_revision_changed": "apify_actor_build_unavailable",
    "actorops_maintenance_revision_changed": "apify_actor_build_unavailable",
}


def settle_preflight_rejection(
    repository: Any,
    *,
    route_id: str,
    source_id: str,
    candidate_id: str,
    expected_candidate_generation: int,
    maintenance_slot: str,
    error_code: str,
) -> PreflightDisposition:
    """Persist only deterministic Candidate failures and open one repair.

    Catalog outages and credential failures are deliberately absent from the
    hard-failure map, so a transient metadata read can never punish a Candidate.
    This path runs before Attempt reservation and therefore cannot create an
    Apify Run ledger row or a paid fact.
    """

    normalized = _HARD_FAILURE_CODES.get(error_code)
    if normalized is None:
        return "deferred"
    try:
        with repository.transaction():
            repository.record_candidate_outcome(
                candidate_id,
                expected_generation=expected_candidate_generation,
                succeeded=False,
                error_class=FailureClass.CANDIDATE.value,
                error_code=normalized,
            )
            repository.resilience.ensure_repair(
                route_id=route_id,
                source_id=source_id,
                origin_job_id=f"maintenance:{maintenance_slot}",
                trigger_code="actorops_candidate_preflight_failed",
            )
    except ActorOpsConflict:
        return "candidate_changed"
    return "hard_failed"


__all__ = ["PreflightDisposition", "settle_preflight_rejection"]
