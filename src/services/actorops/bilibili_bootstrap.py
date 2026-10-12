"""Initial Bilibili setup admits pending targets only into explicit paid plans."""

from .domain import AssignmentRole, RouteKey, RuntimeMode


def initial_bilibili_setup(repository, route_id):
    route = repository.get_route(route_id)
    return (route.route_key == RouteKey('bilibili', 'profile', 'items')
            and route.runtime_mode is RuntimeMode.DISABLED
            and not any(candidate.assignment_role is AssignmentRole.ACTIVE
                        for candidate in repository.list_route_candidates(route_id)))


def replacement_binding_set(repository, route_id):
    statuses = ('ready', 'pending') if initial_bilibili_setup(repository, route_id) else ('ready',)
    placeholders = ','.join('?' for _ in statuses)
    rows = repository.connection.execute(
        f"""SELECT source_id,binding_version,target_fingerprint FROM actor_source_bindings_v2
            WHERE workspace_id=? AND route_id=? AND status IN ({placeholders}) ORDER BY source_id""",
        (repository.workspace_id, route_id, *statuses),
    ).fetchall()
    return tuple((str(row['source_id']), int(row['binding_version']), str(row['target_fingerprint'])) for row in rows)
