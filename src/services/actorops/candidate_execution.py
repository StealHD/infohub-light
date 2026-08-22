"""One exact-candidate ActorOps v2 execution and recovery path."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Callable

from ..apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from .attempt_events import RepositoryAttemptEvents
from .attempt_recovery import attempt_identity, frozen_window, request_fingerprint
from .domain import AttemptStatus, FailureClass, RouteHealth
from .errors import ActorOpsRuntimeError
from .policy import classify_batch_freshness
from .ports import (
    ActorManifest,
    ExecutionResult,
    FetchWindow,
    RemoteActorClient,
    RemoteRunRequest,
    RemoteRunResult,
)
from .repository import ActorOpsConflict, ActorOpsRepository


_TERMINAL = {
    AttemptStatus.SUCCEEDED,
    AttemptStatus.FAILED,
    AttemptStatus.CANCELLED,
}


@dataclass(frozen=True, slots=True)
class _PreparedAttempt:
    attempt_id: str
    window: FetchWindow
    cap_usd: float
    run: RemoteRunResult | None = None
    skip: bool = False


class CandidateExecution:
    def __init__(
        self,
        repository: ActorOpsRepository,
        remote: RemoteActorClient,
        id_factory: Callable[[], str],
    ) -> None:
        self.repository = repository
        self.remote = remote
        self.id_factory = id_factory

    async def fetch(
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
            manifest = _manifest(candidate)
        except Exception:
            self._candidate_outcome(
                candidate, succeeded=False,
                error_code="actorops_v2_candidate_contract_invalid",
            )
            return None
        prepared = await self._prepare(
            snapshot=snapshot,
            candidate=candidate,
            source_id=source_id,
            logical_job_id=logical_job_id,
            group_id=group_id,
            index=index,
            window=window,
        )
        if prepared.skip:
            return None
        try:
            actor_input = adapter.build_actor_input(
                target, manifest, prepared.window
            )
        except Exception:
            self._cancel_unstarted(
                prepared.attempt_id, "actorops_v2_candidate_contract_invalid"
            )
            self._candidate_outcome(
                candidate, succeeded=False,
                error_code="actorops_v2_candidate_contract_invalid",
            )
            return None
        run = prepared.run or await self._start_remote(
            prepared,
            candidate=candidate,
            actor_input=actor_input,
        )
        return self._validate(
            adapter=adapter,
            target=target,
            snapshot=snapshot,
            candidate=candidate,
            manifest=manifest,
            prepared=prepared,
            run=run,
            health=health,
        )

    async def _prepare(
        self,
        *,
        snapshot: Any,
        candidate: Any,
        source_id: str,
        logical_job_id: str,
        group_id: str,
        index: int,
        window: FetchWindow,
    ) -> _PreparedAttempt:
        key = attempt_identity(
            self.repository.workspace_id,
            logical_job_id,
            source_id,
            snapshot.binding.binding_version,
            candidate.candidate_id,
            kind="fetch",
        )
        existing = self.repository.get_attempt_by_idempotency(key)
        if existing is not None:
            return await self._resume(existing, candidate)
        attempt_id = self.id_factory()
        fingerprint = request_fingerprint(
            target_fingerprint=snapshot.target_fingerprint,
            candidate=candidate,
            route_cap_usd=snapshot.route.per_run_cap_usd,
            window=window,
        )
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
                logical_job_id=logical_job_id,
                request_fingerprint=fingerprint,
                window_since=window.since.isoformat(),
                window_until=window.until.isoformat() if window.until else None,
                max_items=window.max_items,
            )
        return _PreparedAttempt(
            attempt_id=attempt_id,
            window=window,
            cap_usd=snapshot.route.per_run_cap_usd,
        )

    async def _resume(self, row: Any, candidate: Any) -> _PreparedAttempt:
        if int(row["request_schema_version"]) != 2:
            raise ActorOpsRuntimeError(
                "actorops_legacy_attempt_recovery_only",
                failure_class=FailureClass.REMOTE_UNKNOWN,
            )
        window = frozen_window(row)
        fingerprint = request_fingerprint(
            target_fingerprint=str(row["target_fingerprint"]),
            candidate=candidate,
            route_cap_usd=float(row["reserved_usd"]),
            window=window,
        )
        if fingerprint != str(row["request_fingerprint"]):
            raise ActorOpsRuntimeError(
                "actorops_frozen_request_mismatch",
                failure_class=FailureClass.CANDIDATE,
            )
        status = AttemptStatus(str(row["status"]))
        if status in _TERMINAL and not bool(row["cost_final"]):
            raise _cost_settlement_required()
        if str(row["result_state"]) in {"observed", "validated"}:
            dataset_id = str(row["dataset_id"] or "")
            if not dataset_id:
                raise _unrecoverable_dataset()
            rows = await self.remote.read_dataset(
                dataset_id, max_items=int(row["max_items"])
            )
            run = RemoteRunResult(
                rows=rows,
                remote_run_id=str(row["remote_run_id"] or ""),
                dataset_id=dataset_id,
                actual_cost_usd=row["actual_cost_usd"],
                cost_final=bool(row["cost_final"]),
            )
            return _PreparedAttempt(
                str(row["attempt_id"]), window, float(row["reserved_usd"]), run
            )
        if status is AttemptStatus.CREATED:
            return _PreparedAttempt(
                str(row["attempt_id"]), window, float(row["reserved_usd"])
            )
        if status in _TERMINAL and bool(row["cost_final"]):
            return _PreparedAttempt(
                str(row["attempt_id"]), window, float(row["reserved_usd"]),
                skip=True,
            )
        raise ActorOpsRuntimeError(
            "actorops_result_recovery_required",
            failure_class=FailureClass.REMOTE_UNKNOWN,
        )

    async def _start_remote(
        self,
        prepared: _PreparedAttempt,
        *,
        candidate: Any,
        actor_input: Any,
    ) -> RemoteRunResult:
        request = RemoteRunRequest(
            attempt_id=prepared.attempt_id,
            candidate_id=candidate.candidate_id,
            actor_id=candidate.actor_id,
            build_number=str(candidate.build_number),
            actor_input=actor_input,
            max_total_charge_usd=prepared.cap_usd,
            max_items=prepared.window.max_items,
        )
        try:
            run = await self.remote.execute(
                request,
                RepositoryAttemptEvents(self.repository, prepared.attempt_id),
            )
        except ActorOpsRuntimeError as error:
            self._record_failure(prepared.attempt_id, error)
            if error.failure_class is FailureClass.CANDIDATE:
                row = self.repository.get_attempt(prepared.attempt_id)
                if bool(row["cost_final"]):
                    self._candidate_outcome(
                        candidate, succeeded=False, error_code=error.code
                    )
                    raise _SettledCandidateFailure() from None
                raise _cost_settlement_required() from None
            raise
        with self.repository.transaction():
            self.repository.observe_attempt_result(
                prepared.attempt_id,
                remote_run_id=run.remote_run_id,
                dataset_id=run.dataset_id,
                actual_cost_usd=run.actual_cost_usd,
                cost_final=run.cost_final,
            )
        return run

    def _validate(
        self,
        *,
        adapter: Any,
        target: Any,
        snapshot: Any,
        candidate: Any,
        manifest: ActorManifest,
        prepared: _PreparedAttempt,
        run: RemoteRunResult,
        health: RouteHealth,
    ) -> ExecutionResult | None:
        try:
            batch = adapter.validate_output(
                run.rows, target, manifest, prepared.window
            )
            try:
                batch = classify_batch_freshness(batch, snapshot.binding)
            except ValueError:
                raise ActorOpsRuntimeError(
                    "actorops_v2_watermark_invalid",
                    failure_class=FailureClass.CONFIGURATION,
                ) from None
        except ActorOpsRuntimeError as error:
            self._record_failure(prepared.attempt_id, error)
            raise
        except Exception:
            return self._invalid_output(prepared.attempt_id, candidate)
        if batch.semantic_outcome in {"suspicious_empty", "stale_regression"}:
            return self._suspicious_output(
                prepared.attempt_id, candidate, batch.semantic_outcome, run
            )
        current = AttemptStatus(
            str(self.repository.get_attempt(prepared.attempt_id)["status"])
        )
        if current in {AttemptStatus.FAILED, AttemptStatus.CANCELLED}:
            raise ActorOpsRuntimeError(
                "actorops_replay_outcome_conflict",
                failure_class=FailureClass.REMOTE_UNKNOWN,
            )
        if current is not AttemptStatus.SUCCEEDED:
            with self.repository.transaction():
                self.repository.complete_attempt(
                    prepared.attempt_id,
                    status=AttemptStatus.SUCCEEDED,
                    semantic_outcome=batch.semantic_outcome,
                    actual_cost_usd=run.actual_cost_usd,
                    cost_final=run.cost_final,
                )
        self._candidate_outcome(candidate, succeeded=True)
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

    def _invalid_output(self, attempt_id: str, candidate: Any) -> None:
        current = AttemptStatus(
            str(self.repository.get_attempt(attempt_id)["status"])
        )
        if current is AttemptStatus.SUCCEEDED:
            raise _replay_outcome_conflict()
        error = ActorOpsRuntimeError(
            "actorops_v2_candidate_contract_invalid",
            failure_class=FailureClass.CANDIDATE,
        )
        self._record_failure(attempt_id, error)
        self._candidate_outcome(
            candidate, succeeded=False, error_code=error.code
        )
        if not bool(self.repository.get_attempt(attempt_id)["cost_final"]):
            raise _cost_settlement_required()
        return None

    def _suspicious_output(
        self,
        attempt_id: str,
        candidate: Any,
        outcome: str,
        run: RemoteRunResult,
    ) -> None:
        current = AttemptStatus(str(self.repository.get_attempt(attempt_id)["status"]))
        if current is AttemptStatus.SUCCEEDED:
            raise _replay_outcome_conflict()
        if current not in _TERMINAL:
            with self.repository.transaction():
                self.repository.complete_attempt(
                    attempt_id,
                    status=AttemptStatus.FAILED,
                    semantic_outcome=outcome,
                    actual_cost_usd=run.actual_cost_usd,
                    cost_final=run.cost_final,
                    failure_class=FailureClass.CANDIDATE.value,
                    error_code=f"actorops_{outcome}",
                )
        self._candidate_outcome(
            candidate, succeeded=False, error_code=f"actorops_{outcome}"
        )
        if not bool(self.repository.get_attempt(attempt_id)["cost_final"]):
            raise _cost_settlement_required()
        return None

    def _cancel_unstarted(self, attempt_id: str, code: str) -> None:
        row = self.repository.get_attempt(attempt_id)
        if AttemptStatus(str(row["status"])) is not AttemptStatus.CREATED:
            return
        with self.repository.transaction():
            self.repository.reconcile_attempt(
                attempt_id,
                expected_status=AttemptStatus.CREATED,
                expected_generation=int(row["generation"]),
                target_status=AttemptStatus.CANCELLED,
                remote_run_id=None,
                dataset_id=None,
                semantic_outcome=code,
                actual_cost_usd=0.0,
                cost_final=True,
                failure_class=FailureClass.CANDIDATE.value,
                error_code=code,
            )

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
        if current not in {
            AttemptStatus.STARTING,
            AttemptStatus.REGISTERED,
            AttemptStatus.RUNNING,
        }:
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

    def _candidate_outcome(
        self,
        candidate: Any,
        *,
        succeeded: bool,
        error_code: str | None = None,
    ) -> None:
        try:
            with self.repository.transaction():
                self.repository.record_candidate_outcome(
                    candidate.candidate_id,
                    expected_generation=candidate.generation,
                    succeeded=succeeded,
                    error_class=(
                        None if succeeded else FailureClass.CANDIDATE.value
                    ),
                    error_code=error_code,
                )
        except ActorOpsConflict:
            return


class _SettledCandidateFailure(ActorOpsRuntimeError):
    def __init__(self) -> None:
        super().__init__(
            "actorops_candidate_failed", failure_class=FailureClass.CANDIDATE
        )


def _cost_settlement_required() -> ActorOpsRuntimeError:
    return ActorOpsRuntimeError(
        "actorops_cost_settlement_required",
        failure_class=FailureClass.REMOTE_UNKNOWN,
    )


def _unrecoverable_dataset() -> ActorOpsRuntimeError:
    return ActorOpsRuntimeError(
        "actorops_dataset_unrecoverable",
        failure_class=FailureClass.REMOTE_UNKNOWN,
    )


def _replay_outcome_conflict() -> ActorOpsRuntimeError:
    return ActorOpsRuntimeError(
        "actorops_replay_outcome_conflict",
        failure_class=FailureClass.REMOTE_UNKNOWN,
    )


def _manifest(candidate: Any) -> ActorManifest:
    if not all((
        candidate.actor_id,
        candidate.build_id,
        candidate.build_number,
        candidate.manifest_json,
        candidate.manifest_hash,
    )):
        raise ValueError("candidate revision is incomplete")
    parsed = parse_actor_manifest(str(candidate.manifest_json))
    if (
        parsed.actor_id != candidate.actor_id
        or parsed.build_number != candidate.build_number
        or actor_manifest_hash(parsed) != candidate.manifest_hash
    ):
        raise ValueError("candidate revision mismatch")
    return ActorManifest(
        actor_id=candidate.actor_id,
        build_id=str(candidate.build_id),
        build_number=str(candidate.build_number),
        manifest_json=str(candidate.manifest_json),
        manifest_hash=str(candidate.manifest_hash),
    )


__all__ = ["CandidateExecution"]
