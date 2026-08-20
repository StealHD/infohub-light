"""Execution snapshot and publication SQL for ActorOpsRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .domain import ExecutionSnapshot
from .policy import candidate_is_runnable, ordered_candidates
from .ports import PublicationProof
from .repository_errors import ActorOpsConflict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def list_route_candidates(repository: Any, route_id: str):
    rows = repository.connection.execute(
        """SELECT candidate_id FROM actor_candidates_v2
           WHERE workspace_id = ? AND route_id = ? ORDER BY candidate_id""",
        (repository.workspace_id, route_id),
    ).fetchall()
    return tuple(repository.get_candidate(str(row["candidate_id"])) for row in rows)


def freeze_execution(
    repository: Any, route_id: str, source_id: str, fingerprint: str
) -> ExecutionSnapshot:
    route = repository.get_route(route_id)
    binding = repository.get_binding(source_id)
    if binding.route_id != route_id or binding.status != "ready":
        raise ActorOpsConflict("source binding is not ready for this route")
    if binding.target_fingerprint != fingerprint:
        raise ActorOpsConflict("source target changed before execution")
    candidates = ordered_candidates(
        list_route_candidates(repository, route_id),
        last_known_good_candidate_id=binding.last_known_good_candidate_id,
    )
    return ExecutionSnapshot(
        workspace_id=repository.workspace_id,
        route=route,
        binding=binding,
        candidates=candidates,
        target_fingerprint=fingerprint,
    )


def publication_proof(
    repository: Any, snapshot: ExecutionSnapshot, candidate_id: str | None
) -> PublicationProof:
    candidate = (
        next(
            (item for item in snapshot.candidates if item.candidate_id == candidate_id),
            None,
        )
        if candidate_id is not None
        else None
    )
    if candidate_id is not None and candidate is None:
        raise ActorOpsConflict("publication candidate was not frozen")
    return PublicationProof(
        workspace_id=repository.workspace_id,
        route_id=snapshot.route.route_id,
        source_id=snapshot.binding.source_id,
        target_fingerprint=snapshot.target_fingerprint,
        binding_version=snapshot.binding.binding_version,
        candidate_id=candidate_id,
        candidate_generation=candidate.generation if candidate else None,
    )


def assert_publishable(repository: Any, proof: PublicationProof) -> None:
    if proof.workspace_id != repository.workspace_id:
        raise ActorOpsConflict("publication workspace changed")
    binding = repository.get_binding(proof.source_id)
    if (
        binding.route_id != proof.route_id
        or binding.binding_version != proof.binding_version
        or binding.target_fingerprint != proof.target_fingerprint
    ):
        raise ActorOpsConflict("source binding changed before publication")
    if proof.candidate_id is None:
        return
    candidate = repository.get_candidate(proof.candidate_id)
    if candidate.route_id != proof.route_id or not candidate_is_runnable(
        candidate.lifecycle,
        build_id=candidate.build_id,
        manifest_hash=candidate.manifest_hash,
    ):
        raise ActorOpsConflict("candidate is no longer publishable")


def publish_success(
    repository: Any,
    proof: PublicationProof,
    *,
    latest_published_at: str,
    latest_item_id_hash: str,
) -> None:
    repository._require_transaction()
    assert_publishable(repository, proof)
    stamp = _now()
    changed = repository.connection.execute(
        """UPDATE actor_source_bindings_v2
           SET last_known_good_candidate_id=COALESCE(?, last_known_good_candidate_id),
               last_success_at=?, watermark_latest_published_at=?,
               watermark_item_id_hash=?, watermark_last_advanced_at=?, updated_at=?
           WHERE workspace_id=? AND source_id=? AND binding_version=?
             AND target_fingerprint=?""",
        (
            proof.candidate_id, stamp, latest_published_at, latest_item_id_hash,
            stamp, stamp, repository.workspace_id, proof.source_id,
            proof.binding_version, proof.target_fingerprint,
        ),
    ).rowcount
    if changed != 1:
        raise ActorOpsConflict("binding changed during publication")


def record_candidate_outcome(
    repository: Any,
    candidate_id: str,
    *,
    expected_generation: int,
    succeeded: bool,
    error_class: str | None,
    error_code: str | None,
):
    repository._require_transaction()
    stamp = _now()
    changed = repository.connection.execute(
        """UPDATE actor_candidates_v2
           SET last_success_at=CASE WHEN ? THEN ? ELSE last_success_at END,
               last_failure_at=CASE WHEN ? THEN last_failure_at ELSE ? END,
               last_error_class=CASE WHEN ? THEN NULL ELSE ? END,
               last_error_code=CASE WHEN ? THEN NULL ELSE ? END,
               generation=generation+1, updated_at=?
           WHERE workspace_id=? AND candidate_id=? AND generation=?""",
        (
            int(succeeded), stamp, int(succeeded), stamp, int(succeeded),
            error_class, int(succeeded), error_code, stamp,
            repository.workspace_id, candidate_id, expected_generation,
        ),
    ).rowcount
    if changed != 1:
        raise ActorOpsConflict("candidate changed before outcome summary")
    return repository.get_candidate(candidate_id)
