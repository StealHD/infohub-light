"""Wake capacity-blocked repairs only when existing assignment gates can progress."""
from datetime import datetime, timezone

from .domain import AssignmentRole, RuntimeMode


def wake_assignable_repairs(repository, route_id):
    policy = repository.maintenance.effective_policy(route_id)
    if (not policy.authorized or not policy.route.auto_add_standby
            or repository.get_route(route_id).runtime_mode is not RuntimeMode.ACTIVE):
        return 0
    candidates = repository.list_route_candidates(route_id)
    assigned = {c.candidate_id for c in candidates if c.assignment_role is not AssignmentRole.INACTIVE}
    has_active = any(c.assignment_role is AssignmentRole.ACTIVE for c in candidates)
    room = has_active and len(assigned) < 3
    replaceable = (len(assigned) > 1 and policy.route.auto_replace_non_last
                   and bool(repository.maintenance.unhealthy_assigned(route_id)))
    stamp = datetime.now(timezone.utc).isoformat()
    rows = repository.connection.execute(
        """SELECT repair_id,candidate_id FROM actor_route_repairs_v2
           WHERE workspace_id=? AND route_id=? AND status='blocked'
             AND error_code='actorops_repair_assignment_unavailable' AND next_attempt_at>?""",
        (repository.workspace_id, route_id, stamp),
    ).fetchall()
    changed = 0
    for row in rows:
        if room or replaceable or str(row['candidate_id']) in assigned:
            changed += repository.connection.execute(
                """UPDATE actor_route_repairs_v2 SET next_attempt_at=?,updated_at=?
                   WHERE workspace_id=? AND repair_id=? AND status='blocked'
                     AND error_code='actorops_repair_assignment_unavailable' AND next_attempt_at>?""",
                (stamp, stamp, repository.workspace_id, row['repair_id'], stamp),
            ).rowcount
    return changed
