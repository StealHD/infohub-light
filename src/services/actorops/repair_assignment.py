"""Assign proved repair reserves without starting another paid probe."""

from .domain import AssignmentRole, CandidateLifecycle, RuntimeMode
from .policy import candidate_has_exact_execution_contract
from .repository_errors import ActorOpsConflict
from .repository_maintenance import _route_capabilities_proven
from .runtime_candidate_health import candidate_operational_states


def assign_proved_repair_candidate(repository, repair):
    """Return assigned, needs_probe, or a stable admission blocker."""
    with repository.transaction():
        current = repository.resilience.get_repair(str(repair['repair_id']))
        if current['updated_at'] != repair['updated_at'] or current['status'] != 'awaiting_probe':
            raise ActorOpsConflict('repair changed before assignment')
        route = repository.get_route(str(current['route_id']))
        candidate = repository.get_candidate(str(current['candidate_id']))
        policy = repository.maintenance.effective_policy(route.route_id)
        if not policy.authorized or not policy.route.auto_add_standby:
            return 'actorops_repair_assignment_not_authorized'
        if route.runtime_mode is not RuntimeMode.ACTIVE:
            return 'actorops_v2_route_disabled'
        if (candidate.route_id != route.route_id
                or not candidate_has_exact_execution_contract(candidate)
                or candidate_operational_states(repository, (candidate,))[candidate.candidate_id].confirmed_failure):
            return 'actorops_repair_candidate_changed'
        count = repository.connection.execute(
            """SELECT COUNT(*) FROM actor_source_bindings_v2
               WHERE workspace_id=? AND route_id=? AND status='ready'""",
            (repository.workspace_id, route.route_id),
        ).fetchone()[0]
        if (not count or candidate.lifecycle not in {
                CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED}
                or repository.maintenance.successful_probe_targets(candidate.candidate_id) < min(2, count)):
            return 'needs_probe'
        if not _route_capabilities_proven(route, candidate):
            return 'actorops_repair_capability_unproven'
        if candidate.assignment_role is not AssignmentRole.INACTIVE:
            return 'assigned'
        args = dict(expected_route_generation=route.generation,
                    expected_candidate_generation=candidate.generation)
        if policy.route.auto_replace_non_last and repository.maintenance.replace_unhealthy_non_last(
                route.route_id, candidate.candidate_id, **args):
            return 'assigned'
        if repository.maintenance.add_standby(route.route_id, candidate.candidate_id, **args):
            return 'assigned'
        return 'actorops_repair_assignment_unavailable'
