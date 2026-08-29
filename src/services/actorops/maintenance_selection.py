"""Progress-guaranteed Candidate and Binding selection for maintenance."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any

from .domain import AssignmentRole, CandidateLifecycle
from .policy import candidate_has_exact_execution_contract, candidate_is_runnable
from .runtime_candidate_health import candidate_operational_states


def select_probe_target(
    repository: Any,
    route_id: str,
    *,
    successful_probe_targets: Callable[[str], int],
) -> tuple[str, Any] | None:
    bindings = tuple(repository.connection.execute(
        """SELECT source_id, binding_version, target_fingerprint, last_success_at
             FROM actor_source_bindings_v2
            WHERE workspace_id=? AND route_id=? AND status='ready'
            ORDER BY CASE WHEN last_success_at IS NULL THEN 1 ELSE 0 END,
                     last_success_at DESC, source_id""",
        (repository.workspace_id, route_id),
    ).fetchall())
    if not bindings:
        return None
    candidates = tuple(repository.list_route_candidates(route_id))
    states = candidate_operational_states(repository, candidates)
    assigned = tuple(
        item for item in candidates
        if item.assignment_role is not AssignmentRole.INACTIVE
        and candidate_is_runnable(item)
        and not states[item.candidate_id].confirmed_failure
    )
    stable_count = sum(
        1 for item in assigned
        if states[item.candidate_id].status == "normal"
        and states[item.candidate_id].stable
    )
    assigned_publishers = {
        str(item.publisher).casefold()
        for item in assigned
        if str(item.publisher or "").strip()
    }
    required_proofs = min(2, len(bindings))
    warm_reserve = any(
        item.assignment_role is AssignmentRole.INACTIVE
        and item.lifecycle in {
            CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED,
        }
        and candidate_has_exact_execution_contract(item)
        and not states[item.candidate_id].confirmed_failure
        and successful_probe_targets(item.candidate_id) >= required_proofs
        for item in candidates
    )
    pool = [
        item for item in candidates
        if item.lifecycle in {
            CandidateLifecycle.STATIC_VALID, CandidateLifecycle.PROBATIONARY,
        }
        and candidate_has_exact_execution_contract(item)
        and not states[item.candidate_id].confirmed_failure
    ]
    if stable_count >= 2 and warm_reserve:
        pool = [
            item for item in pool
            if item.assignment_role is not AssignmentRole.INACTIVE
            and successful_probe_targets(item.candidate_id) < required_proofs
        ]
    pool.sort(key=lambda item: (
        str(item.publisher).casefold() in assigned_publishers,
        item.assignment_role is not AssignmentRole.INACTIVE,
        item.lifecycle is CandidateLifecycle.STATIC_VALID,
        int(item.priority or 0), item.candidate_id,
    ))
    for candidate in pool:
        for binding in bindings:
            proved = repository.connection.execute(
                """SELECT 1 FROM actor_attempts_v2
                   WHERE workspace_id=? AND candidate_id=? AND kind='probe'
                     AND source_id=? AND binding_version=?
                     AND target_fingerprint=? AND status='succeeded'
                     AND semantic_outcome='valid_nonempty' AND cost_final=1
                   LIMIT 1""",
                (
                    repository.workspace_id, candidate.candidate_id,
                    binding["source_id"], binding["binding_version"],
                    binding["target_fingerprint"],
                ),
            ).fetchone()
            if proved is None:
                return candidate.candidate_id, binding
    return None


__all__ = ["select_probe_target"]
