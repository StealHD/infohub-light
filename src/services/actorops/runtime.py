"""Generic ActorOps v2 stable-fetch orchestration."""

from __future__ import annotations

import hashlib
import json
import uuid
from collections.abc import Callable, Mapping
from typing import Any

from .domain import AttemptStatus, FailureClass, RouteHealth, RuntimeMode
from .attempt_events import RepositoryAttemptEvents
from ...apify_actor_identity import source_target_fingerprint
from ..apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from .ports import (
    ActorManifest,
    ExecutionResult,
    FetchWindow,
    PublicationProof,
    RemoteActorClient,
    RemoteRunRequest,
)
from .policy import classify_batch_freshness
from .registry import AdapterNotRegistered, AdapterRegistry
from .repository import ActorOpsConflict, ActorOpsRepository


class ActorOpsRuntimeError(RuntimeError):
    def __init__(self, code: str, *, failure_class: FailureClass) -> None:
        self.code = code
        self.failure_class = failure_class
        self.retryable = failure_class not in {
            FailureClass.CONFIGURATION, FailureClass.TARGET
        }
        super().__init__(code.replace("_", " "))


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
        if route.runtime_mode is not RuntimeMode.ACTIVE:
            raise ActorOpsRuntimeError(
                "actorops_v2_route_not_active",
                failure_class=FailureClass.CONFIGURATION,
            )
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
                "actorops_v2_target_invalid", failure_class=FailureClass.TARGET
            ) from None
        raw_target = str(source_config.get("target") or "")
        fingerprint = source_target_fingerprint(
            self.repository.workspace_id,
            route_id,
            raw_target,
            platform=route.route_key.platform,
        )
        snapshot = self.repository.freeze_execution(route_id, source_id, fingerprint)
        health = self.repository.route_health(route_id)
        group_id = self.id_factory()
        fallback_allowed = True
        for index, candidate in enumerate(snapshot.candidates):
            try:
                result = await self._fetch_candidate(
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
                if error.code in {
                    "actorops_result_recovery_required",
                    "actorops_attempt_already_settled",
                }:
                    raise
                fallback_allowed = error.failure_class in {
                    FailureClass.CREDENTIAL,
                    FailureClass.REMOTE_UNKNOWN,
                }
                if not fallback_allowed:
                    raise
                break
            if result is not None:
                return result
        if fallback_allowed:
            fallback = await adapter.fetch_native_fallback(target, window)
            if fallback.supported:
                return ExecutionResult(
                    items=fallback.items,
                    execution_mode="native_fallback",
                    health=health.value,
                    degraded_reason=fallback.degraded_reason or "native_fallback",
                    candidate_id=None,
                    semantic_outcome="native_fallback",
                    publication_proof=self.repository.publication_proof(snapshot, None),
                )
        raise ActorOpsRuntimeError(
            "actorops_v2_route_unavailable",
            failure_class=FailureClass.CANDIDATE,
        )

    async def _fetch_candidate(
        self,
        *,
        adapter: Any,
        target: Any,
        snapshot: Any,
        candidate: Any,
        index: int,
        group_id: str,
        source_id: str,
        logical_job_id: str,
        window: FetchWindow,
        health: RouteHealth,
    ) -> ExecutionResult | None:
        try:
            manifest = self._manifest(candidate)
            actor_input = adapter.build_actor_input(target, manifest, window)
        except Exception:
            raise ActorOpsRuntimeError(
                "actorops_v2_candidate_contract_invalid",
                failure_class=FailureClass.CONFIGURATION,
            ) from None
        key = self._idempotency_key(
            logical_job_id, source_id, snapshot.binding.binding_version,
            candidate.candidate_id, window, index,
        )
        existing = self.repository.get_attempt_by_idempotency(key)
        if existing:
            settled = (
                AttemptStatus(str(existing["status"]))
                in {AttemptStatus.SUCCEEDED, AttemptStatus.FAILED, AttemptStatus.CANCELLED}
                and bool(existing["cost_final"])
            )
            raise ActorOpsRuntimeError(
                (
                    "actorops_attempt_already_settled"
                    if settled else "actorops_result_recovery_required"
                ),
                failure_class=FailureClass.REMOTE_UNKNOWN,
            )
        attempt_id = self.id_factory()
        with self.repository.transaction():
            self.repository.create_attempt(
                attempt_id=attempt_id,
                idempotency_key=key,
                route_id=snapshot.route.route_id,
                source_id=source_id,
                candidate_id=candidate.candidate_id,
                kind="fetch",
                attempt_group_id=group_id,
                attempt_index=index,
                route_generation=snapshot.route.generation,
                binding_version=snapshot.binding.binding_version,
                target_fingerprint=snapshot.target_fingerprint,
                reserved_usd=snapshot.route.per_run_cap_usd,
            )
        request = RemoteRunRequest(
            attempt_id=attempt_id,
            candidate_id=candidate.candidate_id,
            actor_id=candidate.actor_id,
            build_number=str(candidate.build_number),
            actor_input=actor_input,
            max_total_charge_usd=snapshot.route.per_run_cap_usd,
            max_items=window.max_items,
        )
        try:
            run = await self.remote.execute(
                request, RepositoryAttemptEvents(self.repository, attempt_id)
            )
        except ActorOpsRuntimeError as error:
            self._record_failure(attempt_id, error)
            if error.failure_class is FailureClass.CANDIDATE:
                self._candidate_outcome(
                    candidate.candidate_id, candidate.generation,
                    succeeded=False, error_code=error.code,
                )
                return None
            raise
        try:
            batch = adapter.validate_output(run.rows, target, manifest, window)
            try:
                batch = classify_batch_freshness(batch, snapshot.binding)
            except ValueError:
                raise ActorOpsRuntimeError(
                    "actorops_v2_watermark_invalid",
                    failure_class=FailureClass.CONFIGURATION,
                ) from None
        except ActorOpsRuntimeError as error:
            self._record_failure(attempt_id, error)
            raise
        except Exception:
            error = ActorOpsRuntimeError(
                "actorops_v2_candidate_contract_invalid",
                failure_class=FailureClass.CANDIDATE,
            )
            self._record_failure(attempt_id, error)
            self._candidate_outcome(
                candidate.candidate_id, candidate.generation,
                succeeded=False, error_code=error.code,
            )
            return None
        if batch.semantic_outcome in {"suspicious_empty", "stale_regression"}:
            self._fail_candidate_attempt(
                attempt_id, batch.semantic_outcome,
                run.actual_cost_usd, run.cost_final,
            )
            self._candidate_outcome(
                candidate.candidate_id, candidate.generation, succeeded=False,
                error_code=f"actorops_{batch.semantic_outcome}",
            )
            return None
        with self.repository.transaction():
            self.repository.complete_attempt(
                attempt_id,
                status=AttemptStatus.SUCCEEDED,
                semantic_outcome=batch.semantic_outcome,
                actual_cost_usd=run.actual_cost_usd,
                cost_final=run.cost_final,
            )
        self._candidate_outcome(
            candidate.candidate_id, candidate.generation, succeeded=True
        )
        return ExecutionResult(
            items=batch.items,
            execution_mode="actor",
            health=health.value,
            degraded_reason=(
                "single_candidate" if health is RouteHealth.DEGRADED else None
            ),
            candidate_id=candidate.candidate_id,
            semantic_outcome=batch.semantic_outcome,
            publication_proof=self.repository.publication_proof(
                snapshot, candidate.candidate_id
            ),
            latest_published_at=batch.latest_published_at,
            latest_item_id=batch.latest_item_id,
        )

    @staticmethod
    def _manifest(candidate) -> ActorManifest:
        if not all(
            (candidate.actor_id, candidate.build_id, candidate.build_number,
             candidate.manifest_json, candidate.manifest_hash)
        ):
            raise ActorOpsRuntimeError(
                "actorops_v2_candidate_revision_incomplete",
                failure_class=FailureClass.CONFIGURATION,
            )
        parsed = parse_actor_manifest(str(candidate.manifest_json))
        if (
            parsed.actor_id != candidate.actor_id
            or parsed.build_number != candidate.build_number
            or actor_manifest_hash(parsed) != candidate.manifest_hash
        ):
            raise ActorOpsRuntimeError(
                "actorops_v2_candidate_revision_mismatch",
                failure_class=FailureClass.CONFIGURATION,
            )
        return ActorManifest(
            actor_id=candidate.actor_id,
            build_id=str(candidate.build_id),
            build_number=str(candidate.build_number),
            manifest_json=str(candidate.manifest_json),
            manifest_hash=str(candidate.manifest_hash),
        )

    @staticmethod
    def _idempotency_key(
        job_id: str,
        source_id: str,
        binding_version: int,
        candidate_id: str,
        window: FetchWindow,
        index: int,
    ) -> str:
        payload = json.dumps(
            {
                "job": job_id,
                "source": source_id,
                "binding": binding_version,
                "candidate": candidate_id,
                "since": window.since.isoformat(),
                "until": window.until.isoformat() if window.until else None,
                "max_items": window.max_items,
                "index": index,
            },
            sort_keys=True,
            separators=(",", ":"),
        )
        return hashlib.sha256(payload.encode("utf-8")).hexdigest()

    def _record_failure(
        self, attempt_id: str, error: ActorOpsRuntimeError
    ) -> None:
        row = self.repository.get_attempt(attempt_id)
        current = AttemptStatus(str(row["status"]))
        if error.failure_class is FailureClass.REMOTE_UNKNOWN:
            if current is AttemptStatus.STARTING:
                with self.repository.transaction():
                    self.repository.transition_attempt(
                        attempt_id,
                        current,
                        AttemptStatus.START_UNKNOWN,
                        error_class=error.failure_class.value,
                        error_code=error.code,
                        expected_generation=int(row["generation"]),
                    )
            return
        if current not in {AttemptStatus.STARTING, AttemptStatus.REGISTERED, AttemptStatus.RUNNING}:
            return
        with self.repository.transaction():
            self.repository.complete_attempt(
                attempt_id,
                status=AttemptStatus.FAILED,
                semantic_outcome=error.code,
                actual_cost_usd=None,
                cost_final=False,
                failure_class=error.failure_class.value,
                error_code=error.code,
            )

    def _fail_candidate_attempt(
        self,
        attempt_id: str,
        outcome: str,
        cost: float | None,
        cost_final: bool,
    ) -> None:
        with self.repository.transaction():
            self.repository.complete_attempt(
                attempt_id,
                status=AttemptStatus.FAILED,
                semantic_outcome=outcome,
                actual_cost_usd=cost,
                cost_final=cost_final,
                failure_class=FailureClass.CANDIDATE.value,
                error_code=f"actorops_{outcome}",
            )

    def _candidate_outcome(
        self,
        candidate_id: str,
        generation: int,
        *,
        succeeded: bool,
        error_code: str | None = None,
    ) -> None:
        try:
            with self.repository.transaction():
                self.repository.record_candidate_outcome(
                    candidate_id,
                    expected_generation=generation,
                    succeeded=succeeded,
                    error_class=(
                        None if succeeded else FailureClass.CANDIDATE.value
                    ),
                    error_code=error_code,
                )
        except ActorOpsConflict:
            return
