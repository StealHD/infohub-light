"""Pure ActorOps v2 health and assignment policy helpers."""

from __future__ import annotations

import hashlib
import re
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from ..apify_actor_manifest import (
    ActorManifestError,
    actor_manifest_hash,
    parse_actor_manifest,
)
from .domain import (
    AssignmentRole,
    CandidateLifecycle,
    CandidateRecord,
    RouteHealth,
    RUNNABLE_LIFECYCLES,
)
from .ports import TargetSpec


_SHA256 = re.compile(r"^[0-9a-f]{64}$")


def derive_route_health(runnable_assignments: int) -> RouteHealth:
    if runnable_assignments < 0:
        raise ValueError("runnable assignment count cannot be negative")
    if runnable_assignments == 0:
        return RouteHealth.UNAVAILABLE
    if runnable_assignments == 1:
        return RouteHealth.DEGRADED
    return RouteHealth.HEALTHY


def candidate_has_exact_execution_contract(candidate: CandidateRecord) -> bool:
    """Validate the immutable fields required by every paid execution path."""

    actor_id = str(candidate.actor_id or "").strip()
    build_id = str(candidate.build_id or "").strip()
    build_number = str(candidate.build_number or "").strip()
    manifest_json = str(candidate.manifest_json or "").strip()
    manifest_hash = str(candidate.manifest_hash or "").strip()
    input_hash = str(candidate.input_schema_hash or "").strip()
    output_hash = str(candidate.output_schema_hash or "").strip()
    if not (
        actor_id
        and build_id
        and build_number
        and manifest_json
        and _SHA256.fullmatch(manifest_hash)
        and _SHA256.fullmatch(input_hash)
        and _SHA256.fullmatch(output_hash)
    ):
        return False
    try:
        manifest = parse_actor_manifest(manifest_json)
    except ActorManifestError:
        return False
    return bool(
        manifest.actor_id == actor_id
        and manifest.build_number == build_number
        and actor_manifest_hash(manifest) == manifest_hash
    )


def candidate_is_runnable(candidate: CandidateRecord) -> bool:
    """Fail closed unless an assigned Candidate can execute exactly."""

    return bool(
        candidate.lifecycle in RUNNABLE_LIFECYCLES
        and candidate_has_exact_execution_contract(candidate)
    )


def target_fingerprint(target: TargetSpec) -> str:
    payload = "\x1f".join(
        (target.canonical_url, target.native_id or "", target.handle or "")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ordered_candidates(
    candidates: tuple[CandidateRecord, ...],
    *,
    preferred_candidate_id: str | None = None,
    last_known_good_candidate_id: str | None,
) -> tuple[CandidateRecord, ...]:
    runnable = {
        item.candidate_id: item
        for item in candidates
        if candidate_is_runnable(item)
    }
    assigned = sorted(
        (
            item
            for item in runnable.values()
            if item.assignment_role in {AssignmentRole.ACTIVE, AssignmentRole.STANDBY}
        ),
        key=lambda item: (
            0 if item.candidate_id == preferred_candidate_id else 1,
            0 if item.assignment_role is AssignmentRole.ACTIVE else 1,
            item.priority if item.priority is not None else 1_000_000,
            item.candidate_id,
        ),
    )
    result = list(assigned)
    lkg = runnable.get(str(last_known_good_candidate_id or ""))
    if lkg is not None and all(item.candidate_id != lkg.candidate_id for item in result):
        result.append(lkg)
    return tuple(result)


def classify_batch_freshness(batch: Any, binding: Any) -> Any:
    if batch.semantic_outcome not in {"valid_nonempty", "valid_empty"}:
        return batch
    if not batch.latest_published_at or not batch.latest_item_id:
        return (
            replace(batch, semantic_outcome="suspicious_empty")
            if batch.semantic_outcome == "valid_nonempty"
            else batch
        )
    watermark = binding.watermark_latest_published_at
    if not watermark:
        return (
            replace(batch, semantic_outcome="advanced")
            if batch.semantic_outcome == "valid_nonempty"
            else batch
        )
    try:
        latest = datetime.fromisoformat(
            str(batch.latest_published_at).replace("Z", "+00:00")
        )
        previous = datetime.fromisoformat(str(watermark).replace("Z", "+00:00"))
    except ValueError as error:
        raise ValueError("ActorOps binding watermark is invalid") from error
    if latest.tzinfo is None:
        latest = latest.replace(tzinfo=timezone.utc)
    if previous.tzinfo is None:
        previous = previous.replace(tzinfo=timezone.utc)
    if latest < previous:
        return replace(batch, semantic_outcome="stale_regression")
    item_hash = hashlib.sha256(batch.latest_item_id.encode("utf-8")).hexdigest()
    if latest == previous and item_hash == binding.watermark_item_id_hash:
        return replace(batch, semantic_outcome="no_advance")
    if batch.semantic_outcome == "valid_empty":
        return replace(batch, semantic_outcome="suspicious_empty")
    return replace(batch, semantic_outcome="advanced")
