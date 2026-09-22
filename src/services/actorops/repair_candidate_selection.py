"""Prefer reserves with current target proof over stalled discovery choices."""

from .domain import AssignmentRole, CandidateLifecycle
from .policy import candidate_has_exact_execution_contract
from .runtime_candidate_health import candidate_operational_states


def prefer_proved_reserve(repository, route_id, current):
    """Keep equal choices stable; retarget only to strictly better proof."""
    candidates = tuple(repository.list_route_candidates(route_id))
    states = candidate_operational_states(repository, candidates)
    best = current
    best_proofs = (
        min(2, repository.maintenance.successful_probe_targets(current.candidate_id))
        if current is not None else 0
    )
    for candidate in candidates:
        if (
            candidate.assignment_role is not AssignmentRole.INACTIVE
            or candidate.lifecycle not in {
                CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED,
            }
            or not candidate_has_exact_execution_contract(candidate)
            or states[candidate.candidate_id].confirmed_failure
        ):
            continue
        proofs = min(2, repository.maintenance.successful_probe_targets(candidate.candidate_id))
        if proofs > best_proofs:
            best, best_proofs = candidate, proofs
    return best
