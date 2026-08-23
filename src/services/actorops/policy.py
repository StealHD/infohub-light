"""Pure ActorOps v2 health and assignment policy helpers."""

from __future__ import annotations

import hashlib
from dataclasses import replace
from datetime import datetime, timezone
from typing import Any

from .domain import (
    AssignmentRole,
    CandidateLifecycle,
    CandidateRecord,
    RouteHealth,
    RUNNABLE_LIFECYCLES,
)
from .ports import TargetSpec


def derive_route_health(runnable_assignments: int) -> RouteHealth:
    if runnable_assignments < 0:
        raise ValueError("runnable assignment count cannot be negative")
    if runnable_assignments == 0:
        return RouteHealth.UNAVAILABLE
    if runnable_assignments == 1:
        return RouteHealth.DEGRADED
    return RouteHealth.HEALTHY


def candidate_is_runnable(
    lifecycle: CandidateLifecycle,
    *,
    build_id: str | None,
    manifest_hash: str | None,
) -> bool:
    return bool(
        lifecycle in RUNNABLE_LIFECYCLES
        and str(build_id or "").strip()
        and str(manifest_hash or "").strip()
    )


def target_fingerprint(target: TargetSpec) -> str:
    payload = "\x1f".join(
        (target.canonical_url, target.native_id or "", target.handle or "")
    )
    return hashlib.sha256(payload.encode("utf-8")).hexdigest()


def ordered_candidates(
    candidates: tuple[CandidateRecord, ...],
    *,
    last_known_good_candidate_id: str | None,
) -> tuple[CandidateRecord, ...]:
    runnable = {
        item.candidate_id: item
        for item in candidates
        if candidate_is_runnable(
            item.lifecycle,
            build_id=item.build_id,
            manifest_hash=item.manifest_hash,
        )
    }
    assigned = sorted(
        (
            item
            for item in runnable.values()
            if item.assignment_role in {AssignmentRole.ACTIVE, AssignmentRole.STANDBY}
        ),
        key=lambda item: (
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
