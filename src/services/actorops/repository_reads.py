"""Typed Route, Candidate, and Binding reads for ActorOpsRepository."""

from __future__ import annotations

from typing import Any

from .domain import (
    AssignmentRole,
    BindingRecord,
    CandidateLifecycle,
    CandidateRecord,
    RouteKey,
    RouteRecord,
    RuntimeMode,
)
from .repository_errors import ActorOpsNotFound


def get_route(repository: Any, route_id: str) -> RouteRecord:
    row = repository.connection.execute(
        "SELECT * FROM actor_routes_v2 WHERE workspace_id=? AND route_id=?",
        (repository.workspace_id, route_id),
    ).fetchone()
    if row is None:
        raise ActorOpsNotFound(f"route not found: {route_id}")
    return RouteRecord(
        route_id=str(row["route_id"]), workspace_id=str(row["workspace_id"]),
        route_key=RouteKey(row["platform"], row["target_type"], row["capability"]),
        runtime_mode=RuntimeMode(str(row["runtime_mode"])),
        per_run_cap_usd=float(row["per_run_cap_usd"]),
        generation=int(row["generation"]),
        source_v1_generation=int(row["source_v1_generation"]),
    )


def get_candidate(repository: Any, candidate_id: str) -> CandidateRecord:
    row = repository.connection.execute(
        "SELECT * FROM actor_candidates_v2 WHERE workspace_id=? AND candidate_id=?",
        (repository.workspace_id, candidate_id),
    ).fetchone()
    if row is None:
        raise ActorOpsNotFound(f"candidate not found: {candidate_id}")
    return CandidateRecord(
        candidate_id=str(row["candidate_id"]), route_id=str(row["route_id"]),
        lifecycle=CandidateLifecycle(str(row["lifecycle"])),
        assignment_role=AssignmentRole(str(row["assignment_role"])),
        priority=int(row["priority"]) if row["priority"] is not None else None,
        generation=int(row["generation"]), build_id=row["build_id"],
        manifest_hash=row["manifest_hash"], actor_id=str(row["actor_id"]),
        publisher=str(row["publisher"]), build_number=row["build_number"],
        manifest_json=row["manifest_json"], input_schema_hash=row["input_schema_hash"],
        output_schema_hash=row["output_schema_hash"],
    )


def get_binding(repository: Any, source_id: str) -> BindingRecord:
    row = repository.connection.execute(
        "SELECT * FROM actor_source_bindings_v2 WHERE workspace_id=? AND source_id=?",
        (repository.workspace_id, source_id),
    ).fetchone()
    if row is None:
        raise ActorOpsNotFound(f"binding not found: {source_id}")
    return BindingRecord(
        binding_id=str(row["binding_id"]), source_id=str(row["source_id"]),
        route_id=str(row["route_id"]),
        target_fingerprint=str(row["target_fingerprint"]),
        binding_version=int(row["binding_version"]),
        preferred_candidate_id=row["preferred_candidate_id"],
        last_known_good_candidate_id=row["last_known_good_candidate_id"],
        status=str(row["status"]), last_success_at=row["last_success_at"],
        watermark_latest_published_at=row["watermark_latest_published_at"],
        watermark_item_id_hash=row["watermark_item_id_hash"],
    )
