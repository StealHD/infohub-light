"""Generic ActorOps v2 stable-fetch orchestration."""

from __future__ import annotations

import uuid
from collections.abc import Callable, Mapping

from ...apify_actor_identity import source_config_target, source_target_fingerprint
from .attempt_recovery import attempt_group_identity, attempt_identity
from .candidate_execution import CandidateExecution
from .domain import FailureClass, RuntimeMode
from .errors import ActorOpsRuntimeError
from .ports import ExecutionResult, FetchWindow, RemoteActorClient
from .registry import AdapterNotRegistered, AdapterRegistry
from .repository import ActorOpsRepository
from .runtime_candidate_health import operational_route_summary
from .runtime_control_flow import (
    execute_candidate_plan,
    fallback_or_fail,
    fetch_disabled_route,
)
from .runtime_resilience import trace_candidate_plan


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
            source_config_target(
                source_config, platform=route.route_key.platform
            ),
            platform=route.route_key.platform,
        )
        snapshot = self.repository.freeze_execution(
            route_id, source_id, fingerprint
        )
        health = operational_route_summary(
            self.repository,
            snapshot.candidates,
            route_id=route_id,
            source_id=source_id,
        ).health
        if route.runtime_mode is not RuntimeMode.ACTIVE:
            return await fetch_disabled_route(
                self.repository, adapter=adapter, target=target, window=window,
                snapshot=snapshot, health=health,
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
            logical_job_id=logical_job_id,
        )
        candidates = plan.candidates
        trace_candidate_plan(
            self.repository, logical_job_id=logical_job_id, route_id=route_id,
            source_id=source_id, candidates=candidates, cross_check=plan.cross_check,
        )
        result = await execute_candidate_plan(
            self.repository, executor, adapter=adapter, target=target,
            snapshot=snapshot, plan=plan, group_id=group_id,
            source_id=source_id, logical_job_id=logical_job_id,
            route_id=route_id, window=window, health=health,
            natural_schedule=natural_schedule,
        )
        if result is not None:
            return result
        return await fallback_or_fail(
            self.repository, adapter=adapter, target=target, window=window,
            snapshot=snapshot, plan=plan, health=health, route_id=route_id,
            source_id=source_id, logical_job_id=logical_job_id,
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
