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
    proofs = {item.candidate_id: successful_probe_targets(item.candidate_id) for item in candidates}
    repair_candidates = {
        str(row[0]) for row in repository.connection.execute(
            """SELECT DISTINCT candidate_id FROM actor_route_repairs_v2
               WHERE workspace_id=? AND route_id=? AND status='awaiting_probe'
                 AND candidate_id IS NOT NULL""",
            (repository.workspace_id, route_id),
        )
    }
    warm_reserve = any(
        item.assignment_role is AssignmentRole.INACTIVE
        and item.lifecycle in {
            CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED,
        }
        and candidate_has_exact_execution_contract(item)
        and not states[item.candidate_id].confirmed_failure
        and proofs[item.candidate_id] >= required_proofs
        for item in candidates
    )
    pool = [
        item for item in candidates
        if (item.lifecycle in {
            CandidateLifecycle.STATIC_VALID, CandidateLifecycle.PROBATIONARY,
        } or (item.lifecycle is CandidateLifecycle.CERTIFIED
              and item.candidate_id in repair_candidates))
        and candidate_has_exact_execution_contract(item)
        and not states[item.candidate_id].confirmed_failure
    ]
    if stable_count >= 2 and warm_reserve:
        pool = [
            item for item in pool
            if item.candidate_id in repair_candidates or (
                item.assignment_role is not AssignmentRole.INACTIVE
                and proofs[item.candidate_id] < required_proofs)
        ]
    pool.sort(key=lambda item: (
        str(item.publisher).casefold() in assigned_publishers,
        item.assignment_role is not AssignmentRole.INACTIVE,
        item.lifecycle is CandidateLifecycle.STATIC_VALID,
        int(item.priority or 0), item.candidate_id,
    ))
    targets = []
    for candidate_index, candidate in enumerate(pool):
        for binding_index, binding in enumerate(bindings):
            evidence = repository.connection.execute(
                """SELECT MAX(CASE WHEN status='succeeded'
                              AND semantic_outcome='valid_nonempty' AND cost_final=1
                              THEN 1 ELSE 0 END) AS proved,
                          MAX(CASE WHEN status IN ('succeeded','failed','cancelled')
                              AND cost_final=1 THEN created_at END) AS last_probe_at
                   FROM actor_attempts_v2
                   WHERE workspace_id=? AND candidate_id=? AND kind='probe'
                     AND source_id=? AND binding_version=?
                     AND target_fingerprint=?""",
                (
                    repository.workspace_id, candidate.candidate_id,
                    binding["source_id"], binding["binding_version"],
                    binding["target_fingerprint"],
                ),
            ).fetchone()
            if not evidence["proved"]:
                targets.append((
                    evidence["last_probe_at"],
                    -min(proofs[candidate.candidate_id], required_proofs),
                    candidate.candidate_id not in repair_candidates,
                    candidate_index, binding_index,
                    candidate.candidate_id, binding,
                ))
    if not targets:
        return None
    targets.sort(key=lambda target: (
        target[0] is not None, target[0] or "", target[1:5],
    ))
    return targets[0][5], targets[0][6]


def certified_repair_probe_allowed(repository, candidate, binding):
    """Permit only an awaited reserve's still-unproved current Binding."""
    if (candidate.lifecycle is not CandidateLifecycle.CERTIFIED
            or candidate.assignment_role is not AssignmentRole.INACTIVE
            or not candidate_has_exact_execution_contract(candidate)
            or candidate_operational_states(repository, (candidate,))[candidate.candidate_id].confirmed_failure):
        return False
    return repository.connection.execute(
        """SELECT 1 FROM actor_route_repairs_v2 AS repair
           WHERE repair.workspace_id=? AND repair.route_id=? AND repair.candidate_id=?
             AND repair.status='awaiting_probe' AND NOT EXISTS (
                 SELECT 1 FROM actor_attempts_v2 AS attempt
                 WHERE attempt.workspace_id=repair.workspace_id
                   AND attempt.candidate_id=repair.candidate_id AND attempt.kind='probe'
                   AND attempt.source_id=? AND attempt.binding_version=?
                   AND attempt.target_fingerprint=? AND attempt.status='succeeded'
                   AND attempt.semantic_outcome='valid_nonempty' AND attempt.cost_final=1
             ) LIMIT 1""",
        (repository.workspace_id, candidate.route_id, candidate.candidate_id,
         binding.source_id, binding.binding_version, binding.target_fingerprint),
    ).fetchone() is not None


__all__ = ["select_probe_target", "certified_repair_probe_allowed"]
