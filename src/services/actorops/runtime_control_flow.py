"""Bounded ActorOps runtime control-flow helpers."""

from __future__ import annotations

from typing import Any

from .domain import FailureClass
from .errors import ActorOpsRuntimeError
from .ports import ExecutionResult
from .runtime_resilience import (
    queue_repair_and_trace,
    record_fetch_result,
    trace_native_fallback,
)


async def fetch_disabled_route(
    repository: Any, *, adapter: Any, target: Any, window: Any,
    snapshot: Any, health: Any,
) -> ExecutionResult:
    fallback = await adapter.fetch_native_fallback(target, window)
    if fallback.supported:
        return ExecutionResult(
            items=fallback.items,
            execution_mode="native_fallback",
            health=health.value,
            degraded_reason=(
                fallback.degraded_reason
                or "actorops_v2_route_disabled_native_fallback"
            ),
            candidate_id=None,
            semantic_outcome="native_fallback",
            publication_proof=repository.publication_proof(snapshot, None),
        )
    raise ActorOpsRuntimeError(
        "actorops_v2_route_disabled",
        failure_class=FailureClass.CONFIGURATION,
    )


async def execute_candidate_plan(
    repository: Any,
    executor: Any,
    *,
    adapter: Any,
    target: Any,
    snapshot: Any,
    plan: Any,
    group_id: str,
    source_id: str,
    logical_job_id: str,
    route_id: str,
    window: Any,
    health: Any,
    natural_schedule: bool,
) -> ExecutionResult | None:
    for index, candidate in enumerate(plan.candidates):
        try:
            result = await executor.fetch(
                adapter=adapter,
                target=target,
                snapshot=snapshot,
                candidate=candidate,
                index=index,
                group_id=group_id,
                source_id=source_id,
                logical_job_id=logical_job_id,
                window=window,
                health=health,
            )
        except ActorOpsRuntimeError as error:
            if error.failure_class is FailureClass.CANDIDATE:
                repository.resilience.emit(
                    root_job_id=logical_job_id,
                    route_id=route_id,
                    source_id=source_id,
                    candidate_id=candidate.candidate_id,
                    phase="candidate_execution",
                    outcome="failed",
                    reason_code=error.code,
                )
                continue
            queue_repair_and_trace(
                repository,
                logical_job_id=logical_job_id,
                route_id=route_id,
                source_id=source_id,
                error_code=error.code,
                blocked_code=(
                    error.code
                    if error.failure_class is FailureClass.REMOTE_UNKNOWN
                    else None
                ),
            )
            raise
        if result is None:
            continue
        record_fetch_result(
            repository,
            binding=snapshot.binding,
            plan=plan,
            result=result,
            candidate=candidate,
            index=index,
            logical_job_id=logical_job_id,
            route_id=route_id,
            source_id=source_id,
            natural_schedule=natural_schedule,
        )
        return result
    return None


async def fallback_or_fail(
    repository: Any,
    *,
    adapter: Any,
    target: Any,
    window: Any,
    snapshot: Any,
    plan: Any,
    health: Any,
    route_id: str,
    source_id: str,
    logical_job_id: str,
) -> ExecutionResult:
    fallback = await adapter.fetch_native_fallback(target, window)
    if fallback.supported:
        trace_native_fallback(
            repository,
            logical_job_id=logical_job_id,
            route_id=route_id,
            source_id=source_id,
        )
        queue_repair_and_trace(
            repository,
            logical_job_id=logical_job_id,
            route_id=route_id,
            source_id=source_id,
            blocked_code=plan.blocked_code,
        )
        return ExecutionResult(
            items=fallback.items,
            execution_mode="native_fallback",
            health=health.value,
            degraded_reason=fallback.degraded_reason or "native_fallback",
            candidate_id=None,
            semantic_outcome="native_fallback",
            publication_proof=repository.publication_proof(snapshot, None),
        )
    queue_repair_and_trace(
        repository,
        logical_job_id=logical_job_id,
        route_id=route_id,
        source_id=source_id,
        blocked_code=plan.blocked_code,
    )
    if plan.blocked_code:
        raise ActorOpsRuntimeError(
            plan.blocked_code,
            failure_class=FailureClass.REMOTE_UNKNOWN,
            retryable=False,
        )
    raise ActorOpsRuntimeError(
        "actorops_v2_route_unavailable",
        failure_class=FailureClass.CANDIDATE,
        retryable=False,
    )


__all__ = ["execute_candidate_plan", "fallback_or_fail", "fetch_disabled_route"]
