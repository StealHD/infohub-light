"""Candidate assignment SQL for ActorOpsRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .domain import AssignmentRole, CandidateLifecycle, ensure_candidate_transition
from .policy import candidate_is_runnable, derive_route_health
from .repository_errors import ActorOpsConflict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def route_health(repository: Any, route_id: str):
    repository.get_route(route_id)
    count = int(
        repository.connection.execute(
            """SELECT COUNT(*) FROM actor_candidates_v2
               WHERE workspace_id=? AND route_id=?
                 AND assignment_role IN ('active','standby')
                 AND lifecycle IN ('probationary','certified')
                 AND build_id IS NOT NULL AND manifest_hash IS NOT NULL""",
            (repository.workspace_id, route_id),
        ).fetchone()[0]
    )
    return derive_route_health(count)


def create(repository: Any, **values: Any):
    repository._require_transaction()
    stamp = _now()
    repository.connection.execute(
        """INSERT INTO actor_candidates_v2 (
               candidate_id, workspace_id, route_id, actor_id, publisher,
               build_id, build_number, manifest_json, manifest_hash,
               input_schema_hash, output_schema_hash, lifecycle,
               assignment_role, generation, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'inactive', 1, ?, ?)""",
        (
            values["candidate_id"], repository.workspace_id, values["route_id"],
            values["actor_id"], values["publisher"], values["build_id"],
            values["build_number"], values["manifest_json"],
            values["manifest_hash"], values["input_schema_hash"],
            values["output_schema_hash"], values["lifecycle"].value, stamp, stamp,
        ),
    )
    return repository.get_candidate(values["candidate_id"])


def transition(repository: Any, candidate_id: str, current, target, **values: Any):
    repository._require_transaction()
    ensure_candidate_transition(current, target)
    stamp = _now()
    changed = repository.connection.execute(
        """UPDATE actor_candidates_v2
           SET lifecycle=?, assignment_role=CASE
                 WHEN ? IN ('rejected','quarantined','disabled','superseded')
                 THEN 'inactive' ELSE assignment_role END,
               priority=CASE
                 WHEN ? IN ('rejected','quarantined','disabled','superseded')
                 THEN NULL ELSE priority END,
               last_error_class=?, last_error_code=?,
               generation=generation+1, updated_at=?
           WHERE workspace_id=? AND candidate_id=? AND lifecycle=? AND generation=?""",
        (
            target.value, target.value, target.value, values["error_class"],
            values["error_code"], stamp, repository.workspace_id, candidate_id,
            current.value, values["expected_generation"],
        ),
    ).rowcount
    if changed != 1:
        raise ActorOpsConflict("candidate changed before transition")
    return repository.get_candidate(candidate_id)


def assign(
    repository: Any,
    route_id: str,
    candidate_id: str,
    role: AssignmentRole,
    **values: Any,
) -> None:
    repository._require_transaction()
    candidate = repository.get_candidate(candidate_id)
    if candidate.route_id != route_id or not candidate_is_runnable(
        candidate.lifecycle,
        build_id=candidate.build_id,
        manifest_hash=candidate.manifest_hash,
    ):
        raise ActorOpsConflict("candidate is not runnable for this route")
    priority = values["priority"]
    if role is AssignmentRole.ACTIVE and priority != 0:
        raise ValueError("active candidate priority must be zero")
    if role is AssignmentRole.STANDBY and (priority is None or priority < 1):
        raise ValueError("standby priority must be positive")
    if role is AssignmentRole.INACTIVE:
        priority = None
    stamp = _now()
    candidate_changed = repository.connection.execute(
        """UPDATE actor_candidates_v2 SET assignment_role=?, priority=?,
               generation=generation+1, updated_at=?
           WHERE workspace_id=? AND candidate_id=? AND route_id=? AND generation=?""",
        (
            role.value, priority, stamp, repository.workspace_id, candidate_id,
            route_id, values["expected_candidate_generation"],
        ),
    ).rowcount
    route_changed = repository.connection.execute(
        """UPDATE actor_routes_v2 SET generation=generation+1, updated_at=?
           WHERE workspace_id=? AND route_id=? AND generation=?""",
        (
            stamp, repository.workspace_id, route_id,
            values["expected_route_generation"],
        ),
    ).rowcount
    if candidate_changed != 1 or route_changed != 1:
        raise ActorOpsConflict("route or candidate changed before assignment")
