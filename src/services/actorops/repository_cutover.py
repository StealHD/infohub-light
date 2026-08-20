"""Route-local mode CAS and observation blockers for offline cutover."""

from __future__ import annotations

from typing import Any

from .domain import RuntimeMode
from .repository_errors import ActorOpsConflict


_MODE_TRANSITIONS = frozenset(
    {
        (RuntimeMode.DISABLED, RuntimeMode.SHADOW),
        (RuntimeMode.SHADOW, RuntimeMode.ACTIVE),
        (RuntimeMode.ACTIVE, RuntimeMode.SHADOW),
        (RuntimeMode.SHADOW, RuntimeMode.DISABLED),
    }
)


def transition_route_mode(
    repository: Any,
    route_id: str,
    *,
    current: RuntimeMode,
    target: RuntimeMode,
    expected_generation: int,
):
    """Atomically move one Route by one explicit cutover step."""

    repository._require_transaction()
    if (current, target) not in _MODE_TRANSITIONS:
        raise ActorOpsConflict("ActorOps route mode transition is invalid")
    if (current, target) in {
        (RuntimeMode.DISABLED, RuntimeMode.SHADOW),
        (RuntimeMode.SHADOW, RuntimeMode.ACTIVE),
    } and any(cutover_blockers(repository, route_id).values()):
        raise ActorOpsConflict("ActorOps route has unsettled cutover facts")
    changed = repository.connection.execute(
        """UPDATE actor_routes_v2
           SET runtime_mode=?, generation=generation+1,
               updated_at=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
           WHERE workspace_id=? AND route_id=? AND runtime_mode=? AND generation=?""",
        (
            target.value,
            repository.workspace_id,
            route_id,
            current.value,
            int(expected_generation),
        ),
    ).rowcount
    if changed != 1:
        raise ActorOpsConflict("ActorOps route changed before mode transition")
    return repository.get_route(route_id)


def cutover_blockers(repository: Any, route_id: str) -> dict[str, int]:
    """Return route-local facts that prohibit a forward mode transition."""

    repository.get_route(route_id)
    active = repository.connection.execute(
        """SELECT COUNT(*) FROM actor_attempts_v2
           WHERE workspace_id=? AND route_id=?
             AND status IN ('created','starting','registered','running','start_unknown')""",
        (repository.workspace_id, route_id),
    ).fetchone()[0]
    unsettled = repository.connection.execute(
        """SELECT COUNT(*) FROM actor_attempts_v2
           WHERE workspace_id=? AND route_id=? AND cost_final=0
             AND (reserved_usd > 0 OR actual_cost_usd IS NOT NULL OR remote_run_id IS NOT NULL)""",
        (repository.workspace_id, route_id),
    ).fetchone()[0]
    return {"active_attempts": int(active), "unsettled_costs": int(unsettled)}


def route_mode_transition_allowed(current: RuntimeMode, target: RuntimeMode) -> bool:
    return (current, target) in _MODE_TRANSITIONS


__all__ = [
    "cutover_blockers",
    "route_mode_transition_allowed",
    "transition_route_mode",
]
