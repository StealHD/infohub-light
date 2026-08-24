"""Generic ActorOps v2 stable-fetch orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping

from ...apify_actor_identity import source_target_fingerprint
from .attempt_recovery import attempt_group_identity, attempt_identity
from .candidate_execution import CandidateExecution
from .domain import FailureClass, RuntimeMode
from .errors import ActorOpsRuntimeError
from .ports import ExecutionResult, FetchWindow, RemoteActorClient
from .registry import AdapterNotRegistered, AdapterRegistry
from .repository import ActorOpsRepository
from .runtime_resilience import (
    queue_repair_and_trace, record_fetch_result, trace_candidate_plan,
    trace_native_fallback,
)


class ActorOpsRuntime:
    def __init__(
        self,
        repository: ActorOpsRepository,
        registry: AdapterRegistry,
        remote: RemoteActorClient,
        *,
        id_factory: Callable[[], str] | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.remote = remote
        self.id_factory = id_factory or (lambda: uuid.uuid4().hex)

    async def fetch(
        self,
        *,
        route_id: str,
        source_id: str,
        source_config: Mapping[str, object],
        window: FetchWindow,
        logical_job_id: str,
    ) -> ExecutionResult:
        route = self.repository.get_route(route_id)
        try:
            adapter = self.registry.require(route.route_key)
        except AdapterNotRegistered:
            raise ActorOpsRuntimeError(
                "actorops_v2_adapter_not_registered",
                failure_class=FailureClass.CONFIGURATION,
            ) from None
        try:
            target = adapter.normalize_target(source_config)
        except (TypeError, ValueError):
            raise ActorOpsRuntimeError(
                "actorops_v2_target_invalid",
                failure_class=FailureClass.TARGET,
            ) from None
        fingerprint = source_target_fingerprint(
            self.repository.workspace_id,
            route_id,
            str(source_config.get("target") or ""),
            platform=route.route_key.platform,
        )
        snapshot = self.repository.freeze_execution(
            route_id, source_id, fingerprint
        )
        health = self.repository.route_health(route_id)
        if route.runtime_mode is not RuntimeMode.ACTIVE:
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
                    publication_proof=self.repository.publication_proof(
                        snapshot, None
                    ),
                )
            raise ActorOpsRuntimeError(
                "actorops_v2_route_disabled",
                failure_class=FailureClass.CONFIGURATION,
            )
        group_id = attempt_group_identity(
            self.repository.workspace_id,
            logical_job_id,
            source_id,
            snapshot.binding.binding_version,
            kind="fetch",
        )
        executor = CandidateExecution(
            self.repository, self.remote, self.id_factory
        )
        candidates = _recovery_first(
            self.repository,
            snapshot,
            source_id=source_id,
            logical_job_id=logical_job_id,
        )
        natural_schedule = self.repository.resilience.is_natural_schedule(
            logical_job_id
        )
        plan = self.repository.resilience.plan_candidates(
            binding=snapshot.binding,
            candidates=candidates,
            natural_schedule=natural_schedule,
        )
        candidates = plan.candidates
        trace_candidate_plan(
            self.repository, logical_job_id=logical_job_id, route_id=route_id,
            source_id=source_id, candidates=candidates, cross_check=plan.cross_check,
        )
        for index, candidate in enumerate(candidates):
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
                    self.repository.resilience.emit(
                        root_job_id=logical_job_id, route_id=route_id, source_id=source_id,
                        candidate_id=candidate.candidate_id, phase="candidate_execution",
                        outcome="failed", reason_code=error.code,
                    )
                    continue
                queue_repair_and_trace(
                    self.repository, logical_job_id=logical_job_id, route_id=route_id,
                    source_id=source_id, error_code=error.code,
                    blocked_code=(error.code if error.failure_class is FailureClass.REMOTE_UNKNOWN else None),
                )
                raise
            if result is not None:
                record_fetch_result(
                    self.repository, binding=snapshot.binding, plan=plan, result=result,
                    candidate=candidate, index=index, logical_job_id=logical_job_id,
                    route_id=route_id, source_id=source_id,
                    natural_schedule=natural_schedule,
                )
                return result
        fallback = await adapter.fetch_native_fallback(target, window)
        if fallback.supported:
            trace_native_fallback(
                self.repository, logical_job_id=logical_job_id, route_id=route_id,
                source_id=source_id,
            )
            return ExecutionResult(
                items=fallback.items,
                execution_mode="native_fallback",
                health=health.value,
                degraded_reason=fallback.degraded_reason or "native_fallback",
                candidate_id=None,
                semantic_outcome="native_fallback",
                publication_proof=self.repository.publication_proof(
                    snapshot, None
                ),
            )
        queue_repair_and_trace(
            self.repository, logical_job_id=logical_job_id, route_id=route_id,
            source_id=source_id,
        )
        raise ActorOpsRuntimeError(
            "actorops_v2_route_unavailable",
            failure_class=FailureClass.CANDIDATE,
        )


def _recovery_first(
    repository: ActorOpsRepository,
    snapshot: object,
    *,
    source_id: str,
    logical_job_id: str,
) -> tuple[object, ...]:
    def has_attempt(candidate: object) -> bool:
        key = attempt_identity(
            repository.workspace_id,
            logical_job_id,
            source_id,
            snapshot.binding.binding_version,
            candidate.candidate_id,
            kind="fetch",
        )
        return repository.get_attempt_by_idempotency(key) is not None

    return tuple(sorted(snapshot.candidates, key=lambda item: not has_attempt(item)))


__all__ = ["ActorOpsRuntime", "ActorOpsRuntimeError"]
