"""Zero-cost, CAS-protected manual selection controls for ActorOps v2."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .domain import AssignmentRole
from .policy import candidate_is_runnable
from .repository_errors import ActorOpsConflict


def promote_standby_candidate(
    repository: Any,
    route_id: str,
    candidate_id: str,
    *,
    expected_route_generation: int,
    expected_candidate_generation: int,
) -> None:
    """Atomically make one runnable manual selection the route's active Candidate.

    This only changes the frozen selection order.  It never starts a Run,
    changes a Manifest, or touches a source Binding.
    """

    repository._require_transaction()
    route = repository.get_route(route_id)
    target = repository.get_candidate(candidate_id)
    if route.generation != int(expected_route_generation):
        raise ActorOpsConflict("route changed before Candidate selection")
    if (
        target.route_id != route_id
        or target.assignment_role not in {AssignmentRole.STANDBY, AssignmentRole.INACTIVE}
        or target.generation != int(expected_candidate_generation)
        or (target.assignment_role is AssignmentRole.STANDBY and target.priority is None)
        or not candidate_is_runnable(target)
    ):
        raise ActorOpsConflict("Candidate is not an eligible standby")
    active = next(
        (
            item for item in repository.list_route_candidates(route_id)
            if item.assignment_role is AssignmentRole.ACTIVE
        ),
        None,
    )
    if active is None or not candidate_is_runnable(active):
        raise ActorOpsConflict("route has no runnable active Candidate")

    stamp = datetime.now(timezone.utc).isoformat()
    prior_priority = target.priority
    _set_assignment(
        repository, target.candidate_id, AssignmentRole.INACTIVE, None,
        expected_generation=target.generation, stamp=stamp,
    )
    _set_assignment(
        repository, active.candidate_id, AssignmentRole.INACTIVE, None,
        expected_generation=active.generation, stamp=stamp,
    )
    _set_assignment(
        repository, target.candidate_id, AssignmentRole.ACTIVE, 0,
        expected_generation=target.generation + 1, stamp=stamp,
    )
    if prior_priority is None:
        # This is a zero-cost restore of a previously active Candidate (for
        # example after an operator has proved a more expensive replacement).
        # Do not invent a standby priority for the transient replacement.
        pass
    else:
        _set_assignment(
            repository, active.candidate_id, AssignmentRole.STANDBY, prior_priority,
            expected_generation=active.generation + 1, stamp=stamp,
        )
    changed = repository.connection.execute(
        """UPDATE actor_routes_v2 SET generation=generation+1, updated_at=?
           WHERE workspace_id=? AND route_id=? AND generation=?""",
        (stamp, repository.workspace_id, route_id, int(expected_route_generation)),
    ).rowcount
    if changed != 1:
        raise ActorOpsConflict("route changed before Candidate selection")


def _set_assignment(
    repository: Any,
    candidate_id: str,
    role: AssignmentRole,
    priority: int | None,
    *,
    expected_generation: int,
    stamp: str,
) -> None:
    changed = repository.connection.execute(
        """UPDATE actor_candidates_v2
           SET assignment_role=?, priority=?, generation=generation+1, updated_at=?
           WHERE workspace_id=? AND candidate_id=? AND generation=?""",
        (
            role.value, priority, stamp, repository.workspace_id, candidate_id,
            int(expected_generation),
        ),
    ).rowcount
    if changed != 1:
        raise ActorOpsConflict("Candidate changed before selection")


__all__ = ["promote_standby_candidate"]
