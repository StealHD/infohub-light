"""ActorOps fetch resilience side effects, kept outside the runtime control flow."""

from __future__ import annotations

from typing import Any


def trace_candidate_plan(
    repository: Any, *, logical_job_id: str, route_id: str, source_id: str,
    candidates: tuple[Any, ...], cross_check: bool,
) -> None:
    repository.resilience.emit(
        root_job_id=logical_job_id, route_id=route_id, source_id=source_id,
        phase="candidate_selection", outcome="selected",
        counts={"candidate_count": len(candidates), "cross_check": int(cross_check)},
    )
    for index, candidate in enumerate(candidates):
        repository.resilience.emit(
            root_job_id=logical_job_id, route_id=route_id, source_id=source_id,
            candidate_id=candidate.candidate_id, phase="candidate_selection",
            outcome="selected", counts={"candidate_index": index},
        )


def record_fetch_result(
    repository: Any, *, binding: Any, plan: Any, result: Any,
    candidate: Any, index: int, logical_job_id: str, route_id: str, source_id: str,
    natural_schedule: bool,
) -> None:
    if plan.cross_check and index == 0 and plan.primary_candidate_id:
        freshness = repository.resilience.record_cross_check(
            binding=binding, primary_candidate_id=plan.primary_candidate_id,
            candidate_id=candidate.candidate_id, outcome=result.semantic_outcome,
            logical_job_id=logical_job_id,
        )
        repository.resilience.emit(
            root_job_id=logical_job_id, route_id=route_id, source_id=source_id,
            candidate_id=candidate.candidate_id, phase="freshness_crosscheck",
            outcome=freshness, counts={"candidate_index": index},
        )
    else:
        repository.resilience.record_regular_result(
            binding=binding, candidate_id=candidate.candidate_id,
            outcome=result.semantic_outcome, logical_job_id=logical_job_id,
            natural_schedule=natural_schedule,
        )
    repository.resilience.emit(
        root_job_id=logical_job_id, route_id=route_id, source_id=source_id,
        candidate_id=candidate.candidate_id, phase="result_classification",
        outcome=result.semantic_outcome,
    )


def queue_repair_and_trace(
    repository: Any, *, logical_job_id: str, route_id: str, source_id: str,
    error_code: str | None = None, blocked_code: str | None = None,
) -> Any:
    repair = repository.resilience.ensure_repair(
        route_id=route_id, source_id=source_id, origin_job_id=logical_job_id,
        trigger_code="actorops_route_exhausted", blocked_code=blocked_code,
    )
    repository.resilience.emit(
        root_job_id=logical_job_id, route_id=route_id, source_id=source_id,
        repair_id=str(repair["repair_id"]), phase="route_repair",
        outcome=str(repair["status"]), reason_code=repair.get("error_code") or error_code,
    )
    return repair


def trace_native_fallback(
    repository: Any, *, logical_job_id: str, route_id: str, source_id: str,
) -> None:
    repository.resilience.emit(
        root_job_id=logical_job_id, route_id=route_id, source_id=source_id,
        phase="native_fallback", outcome="fallback",
    )


__all__ = [
    "queue_repair_and_trace", "record_fetch_result", "trace_candidate_plan",
    "trace_native_fallback",
]
