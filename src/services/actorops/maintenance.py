"""Generic Candidate Probe and bounded standby maintenance."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from ...apify_actor_identity import source_config_target, source_target_fingerprint
from ..apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from .adapter_rows import validate_and_enrich_adapter_rows
from .attempt_events import RepositoryAttemptEvents
from .attempt_recovery import request_fingerprint
from .domain import AssignmentRole, AttemptStatus, CandidateLifecycle, FailureClass
from .maintenance_preflight import settle_preflight_rejection
from .ports import (
    ActorManifest,
    CandidateProbePreflight,
    FetchWindow,
    ProbePreflightResult,
    RemoteActorClient,
    RemoteRunRequest,
)
from .probe_limits import PROBE_DATASET_VALIDATION_LIMIT
from .recovery_probe import (
    RECOVERY_INTENT,
    apply_recovery_success,
    apply_settled_recovery_success,
    recovery_target_is_current,
)
from .registry import AdapterNotRegistered, AdapterRegistry
from .repository import ActorOpsConflict, ActorOpsRepository
from .runtime import ActorOpsRuntimeError
from .runtime_candidate_health import candidate_operational_states


@dataclass(frozen=True, slots=True)
class ProbeResult:
    attempt_id: str | None
    candidate_id: str
    status: str
    error_code: str | None = None


class ActorOpsProber:
    """Run one exact Candidate Probe without Feed or fallback ownership."""

    def __init__(
        self,
        repository: ActorOpsRepository,
        registry: AdapterRegistry,
        remote: RemoteActorClient,
        preflight: CandidateProbePreflight,
        *,
        id_factory: Callable[[], str] | None = None,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.registry = registry
        self.remote = remote
        self.preflight = preflight
        self.id_factory = id_factory or (lambda: uuid.uuid4().hex)
        self.now = now or (lambda: datetime.now(timezone.utc))

    async def probe(
        self,
        *,
        route_id: str,
        candidate_id: str,
        source_id: str,
        source_config: Mapping[str, object],
        maintenance_slot: str,
        expected_binding_version: int | None = None,
        intent: str = "standing",
        expected_route_generation: int | None = None,
        expected_candidate_generation: int | None = None,
        expected_last_failure_at: str | None = None,
    ) -> ProbeResult:
        now = _utc(self.now())
        route = self.repository.get_route(route_id)
        candidate = self.repository.get_candidate(candidate_id)
        binding = self.repository.get_binding(source_id)
        policy = self.repository.maintenance.effective_policy(route_id)
        if not policy.authorized:
            return ProbeResult(None, candidate_id, "skipped", "actorops_maintenance_not_authorized")
        operator_recovery = intent == RECOVERY_INTENT
        if operator_recovery and self._recovery_target_changed(
            route=route,
            candidate=candidate,
            expected_route_generation=expected_route_generation,
            expected_candidate_generation=expected_candidate_generation,
            expected_last_failure_at=expected_last_failure_at,
            now=now,
        ):
            return ProbeResult(
                None, candidate_id, "skipped", "actorops_maintenance_recovery_target_changed",
            )
        try:
            adapter = self.registry.require(route.route_key)
            target = adapter.normalize_target(source_config)
            manifest = _manifest(candidate)
        except (AdapterNotRegistered, TypeError, ValueError):
            return ProbeResult(None, candidate_id, "skipped", "actorops_maintenance_contract_invalid")
        raw_target = source_config_target(source_config, platform=route.route_key.platform)
        fingerprint = source_target_fingerprint(
            self.repository.workspace_id, route_id, raw_target,
            platform=route.route_key.platform,
        )
        if (
            binding.route_id != route_id or binding.status != "ready"
            or (expected_binding_version is not None and binding.binding_version != expected_binding_version)
            or binding.target_fingerprint != fingerprint
        ):
            return ProbeResult(None, candidate_id, "skipped", "actorops_maintenance_target_changed")
        rejected = await self._preflight_result(
            route_id=route_id,
            source_id=source_id,
            candidate=candidate,
            maintenance_slot=maintenance_slot,
            max_charge_usd=policy.max_charge_usd,
            operator_recovery=operator_recovery,
        )
        if rejected is not None:
            return rejected
        window = FetchWindow(max_items=1, since=now - timedelta(days=90), until=now)
        actor_input = adapter.build_actor_input(target, manifest, window)
        key = _idempotency_key(route_id, candidate_id, source_id, binding.binding_version, maintenance_slot)
        existing = self.repository.get_attempt_by_idempotency(key)
        if existing is not None:
            return self._existing_probe_result(
                existing, candidate_id, operator_recovery=operator_recovery
            )
        attempt_id = f"{self.id_factory()}-{key[:12]}"
        try:
            with self.repository.transaction():
                self.repository.maintenance.reserve_probe(
                    route_id=route_id, candidate_id=candidate_id, source_id=source_id,
                    binding_version=binding.binding_version, target_fingerprint=fingerprint,
                    idempotency_key=key, attempt_id=attempt_id,
                    attempt_group_id=f"maintenance:{maintenance_slot}",
                    expected_route_generation=route.generation,
                    expected_candidate_generation=candidate.generation,
                    expected_workspace_policy_generation=policy.workspace.generation,
                    expected_route_policy_generation=policy.route.generation,
                    reserved_usd=policy.max_charge_usd, now=now,
                    logical_job_id=f"maintenance:{maintenance_slot}",
                    request_fingerprint=request_fingerprint(
                        target_fingerprint=fingerprint,
                        candidate=candidate,
                        route_cap_usd=policy.max_charge_usd,
                        window=window,
                    ),
                    window_since=window.since.isoformat(),
                    window_until=window.until.isoformat() if window.until else None,
                    max_items=window.max_items,
                    operator_recovery=operator_recovery,
                    expected_last_failure_at=expected_last_failure_at,
                )
        except ActorOpsConflict as error:
            return ProbeResult(None, candidate_id, "skipped", _safe_code(str(error), "actorops_maintenance_conflict"))
        request = RemoteRunRequest(
            attempt_id=attempt_id, candidate_id=candidate_id, actor_id=candidate.actor_id,
            build_number=str(candidate.build_number), actor_input=actor_input,
            max_total_charge_usd=policy.max_charge_usd,
            max_items=1,
            max_remote_starts=1,
            dataset_item_limit=PROBE_DATASET_VALIDATION_LIMIT,
        )
        try:
            run = await self.remote.execute(
                request, RepositoryAttemptEvents(self.repository, attempt_id)
            )
        except ActorOpsRuntimeError as error:
            self._record_remote_failure(attempt_id, error)
            return ProbeResult(
                attempt_id, candidate_id,
                "recovery_required" if error.failure_class is FailureClass.REMOTE_UNKNOWN else "failed", error.code,
            )
        except Exception:
            error = ActorOpsRuntimeError(
                "actorops_maintenance_remote_failed", failure_class=FailureClass.INTERNAL
            )
            self._record_remote_failure(attempt_id, error)
            return ProbeResult(attempt_id, candidate_id, "failed", error.code)
        with self.repository.transaction():
            self.repository.observe_attempt_result(
                attempt_id,
                remote_run_id=run.remote_run_id,
                dataset_id=run.dataset_id,
                actual_cost_usd=run.actual_cost_usd,
                cost_final=run.cost_final,
            )
        try:
            batch = validate_and_enrich_adapter_rows(self.repository, adapter, run.rows, target, manifest, window, candidate, route.route_key.platform)
        except Exception:
            self._candidate_failure(
                attempt_id, candidate, "actorops_maintenance_candidate_contract_invalid",
                run.actual_cost_usd, run.cost_final,
            )
            return ProbeResult(attempt_id, candidate_id, "failed", "actorops_maintenance_candidate_contract_invalid")
        if batch.semantic_outcome != "valid_nonempty":
            with self.repository.transaction():
                self.repository.complete_attempt(
                    attempt_id, status=AttemptStatus.SUCCEEDED, semantic_outcome="no_evidence",
                    actual_cost_usd=run.actual_cost_usd, cost_final=run.cost_final,
                )
            return ProbeResult(attempt_id, candidate_id, "no_evidence")
        return self._promote_success(
            attempt_id, route, candidate, run, binding=binding,
            operator_recovery=operator_recovery,
            expected_route_generation=expected_route_generation,
            expected_candidate_generation=expected_candidate_generation,
            expected_last_failure_at=expected_last_failure_at,
        )

    def _recovery_target_changed(
        self,
        *,
        route: Any,
        candidate: Any,
        expected_route_generation: int | None,
        expected_candidate_generation: int | None,
        expected_last_failure_at: str | None,
        now: datetime,
    ) -> bool:
        return (
            route.generation != expected_route_generation
            or candidate.generation != expected_candidate_generation
            or not recovery_target_is_current(
                self.repository,
                candidate,
                expected_last_failure_at=str(expected_last_failure_at or ""),
                now=now,
            )
        )

    async def _preflight_result(
        self,
        *,
        route_id: str,
        source_id: str,
        candidate: Any,
        maintenance_slot: str,
        max_charge_usd: float,
        operator_recovery: bool,
    ) -> ProbeResult | None:
        if (
            not operator_recovery
            and candidate_operational_states(self.repository, (candidate,))[
                candidate.candidate_id
            ].confirmed_failure
        ):
            return ProbeResult(
                None,
                candidate.candidate_id,
                "skipped",
                "actorops_maintenance_candidate_confirmed_failure",
            )
        preflight = await self.preflight.verify(
            candidate, max_charge_usd=max_charge_usd
        )
        if preflight.allowed:
            return None
        code = _safe_code(
            preflight.error_code,
            "actorops_maintenance_preflight_rejected",
        )
        disposition = settle_preflight_rejection(
            self.repository,
            route_id=route_id,
            source_id=source_id,
            candidate_id=candidate.candidate_id,
            expected_candidate_generation=candidate.generation,
            maintenance_slot=maintenance_slot,
            error_code=code,
        )
        if disposition == "hard_failed":
            return ProbeResult(None, candidate.candidate_id, "failed", code)
        if disposition == "candidate_changed":
            code = "actorops_maintenance_candidate_changed"
        return ProbeResult(None, candidate.candidate_id, "skipped", code)

    def _promote_success(
        self,
        attempt_id: str,
        route: Any,
        candidate: Any,
        run: Any,
        *,
        binding: Any,
        operator_recovery: bool,
        expected_route_generation: int | None,
        expected_candidate_generation: int | None,
        expected_last_failure_at: str | None,
    ) -> ProbeResult:
        with self.repository.transaction():
            self.repository.complete_attempt(
                attempt_id, status=AttemptStatus.SUCCEEDED,
                semantic_outcome="valid_nonempty",
                actual_cost_usd=run.actual_cost_usd,
                cost_final=run.cost_final,
            )
        if not run.cost_final:
            return ProbeResult(
                attempt_id, candidate.candidate_id, "recovery_required",
                "actorops_maintenance_cost_pending",
            )
        if operator_recovery:
            try:
                recovered = apply_recovery_success(
                    self.repository,
                    attempt_id=attempt_id,
                    candidate_id=candidate.candidate_id,
                    binding=binding,
                    expected_route_generation=int(expected_route_generation or 0),
                    expected_candidate_generation=int(
                        expected_candidate_generation or 0
                    ),
                    expected_last_failure_at=str(expected_last_failure_at or ""),
                )
            except Exception:
                recovered = False
            if not recovered:
                return ProbeResult(
                    attempt_id, candidate.candidate_id, "recovery_required",
                    "actorops_maintenance_candidate_reconciliation_required",
                )
            return ProbeResult(attempt_id, candidate.candidate_id, "recovered")
        current = self._promote_settled_candidate(candidate.candidate_id)
        if current is None:
            return ProbeResult(
                attempt_id,
                candidate.candidate_id,
                "completed",
            )
        self._add_safe_standby(route.route_id, current.candidate_id)
        final = self.repository.get_candidate(candidate.candidate_id)
        return ProbeResult(
            attempt_id, candidate.candidate_id,
            "promoted" if final.lifecycle is not CandidateLifecycle.STATIC_VALID else "completed",
        )

    def _existing_probe_result(
        self, existing: Mapping[str, object], candidate_id: str, *,
        operator_recovery: bool,
    ) -> ProbeResult:
        settled = (
            str(existing["status"]) in {"succeeded", "failed", "cancelled"}
            and bool(existing["cost_final"])
        )
        if not operator_recovery or not settled:
            return ProbeResult(
                str(existing["attempt_id"]), candidate_id,
                "already_settled" if settled else "recovery_required",
            )
        try:
            recovered = apply_settled_recovery_success(
                self.repository, candidate_id
            )
        except Exception:
            recovered = None
        return ProbeResult(
            str(existing["attempt_id"]), candidate_id,
            "recovered" if recovered is not None else "recovery_required",
            None if recovered is not None
            else "actorops_maintenance_candidate_reconciliation_required",
        )

    def _promote_settled_candidate(self, candidate_id: str) -> Any | None:
        try:
            with self.repository.transaction():
                candidate = self.repository.get_candidate(candidate_id)
                current = self.repository.record_candidate_outcome(
                    candidate.candidate_id, expected_generation=candidate.generation, succeeded=True,
                )
                if current.lifecycle is CandidateLifecycle.STATIC_VALID:
                    current = self.repository.transition_candidate(
                        current.candidate_id, CandidateLifecycle.STATIC_VALID,
                        CandidateLifecycle.PROBATIONARY, expected_generation=current.generation,
                    )
                if (
                    current.lifecycle is CandidateLifecycle.PROBATIONARY
                    and self.repository.maintenance.successful_probe_targets(current.candidate_id) >= 2
                ):
                    current = self.repository.transition_candidate(
                        current.candidate_id, CandidateLifecycle.PROBATIONARY,
                        CandidateLifecycle.CERTIFIED, expected_generation=current.generation,
                    )
        except ActorOpsConflict:
            return None
        return current

    def _add_safe_standby(self, route_id: str, candidate_id: str) -> None:
        try:
            policy = self.repository.maintenance.effective_policy(route_id)
            if not policy.authorized or not policy.route.auto_add_standby:
                return
            with self.repository.transaction():
                route = self.repository.get_route(route_id)
                candidate = self.repository.get_candidate(candidate_id)
                if candidate.assignment_role is not AssignmentRole.INACTIVE:
                    return
                self.repository.maintenance.add_standby(
                    route_id,
                    candidate_id,
                    expected_route_generation=route.generation,
                    expected_candidate_generation=candidate.generation,
                )
        except ActorOpsConflict:
            return

    def _candidate_failure(self, attempt_id: str, candidate: Any, code: str, cost: float | None, cost_final: bool) -> None:
        with self.repository.transaction():
            self.repository.complete_attempt(
                attempt_id, status=AttemptStatus.FAILED,
                semantic_outcome=code, actual_cost_usd=cost,
                cost_final=cost_final,
                failure_class=FailureClass.CANDIDATE.value, error_code=code,
            )
        try:
            with self.repository.transaction():
                candidate = self.repository.get_candidate(candidate.candidate_id)
                current = self.repository.record_candidate_outcome(
                    candidate.candidate_id, expected_generation=candidate.generation,
                    succeeded=False, error_class=FailureClass.CANDIDATE.value, error_code=code,
                )
                if current.lifecycle is CandidateLifecycle.STATIC_VALID:
                    self.repository.transition_candidate(
                        current.candidate_id, CandidateLifecycle.STATIC_VALID,
                        CandidateLifecycle.REJECTED, expected_generation=current.generation,
                        error_class=FailureClass.CANDIDATE.value, error_code=code,
                    )
                elif current.lifecycle in {
                    CandidateLifecycle.PROBATIONARY,
                    CandidateLifecycle.CERTIFIED,
                }:
                    self.repository.transition_candidate(
                        current.candidate_id, current.lifecycle,
                        CandidateLifecycle.QUARANTINED,
                        expected_generation=current.generation,
                        error_class=FailureClass.CANDIDATE.value,
                        error_code=code,
                    )
        except ActorOpsConflict:
            return

    def _record_remote_failure(self, attempt_id: str, error: ActorOpsRuntimeError) -> None:
        row = self.repository.get_attempt(attempt_id)
        current = AttemptStatus(str(row["status"]))
        if error.failure_class is FailureClass.REMOTE_UNKNOWN:
            if current is AttemptStatus.STARTING:
                with self.repository.transaction():
                    self.repository.transition_attempt(
                        attempt_id, current, AttemptStatus.START_UNKNOWN,
                        error_class=error.failure_class.value, error_code=error.code,
                        expected_generation=int(row["generation"]),
                    )
            return
        if current in {AttemptStatus.STARTING, AttemptStatus.REGISTERED, AttemptStatus.RUNNING}:
            with self.repository.transaction():
                self.repository.complete_attempt(
                    attempt_id, status=AttemptStatus.FAILED, semantic_outcome=error.code,
                    actual_cost_usd=None, cost_final=False,
                    failure_class=error.failure_class.value, error_code=error.code,
                )


def _manifest(candidate: Any) -> ActorManifest:
    if not all((candidate.actor_id, candidate.build_id, candidate.build_number, candidate.manifest_json, candidate.manifest_hash)):
        raise ValueError("candidate revision is incomplete")
    parsed = parse_actor_manifest(str(candidate.manifest_json))
    if (
        parsed.actor_id != candidate.actor_id or parsed.build_number != candidate.build_number
        or actor_manifest_hash(parsed) != candidate.manifest_hash
    ):
        raise ValueError("candidate revision does not match its manifest")
    return ActorManifest(candidate.actor_id, str(candidate.build_id), str(candidate.build_number), str(candidate.manifest_json), str(candidate.manifest_hash))


def _idempotency_key(route_id: str, candidate_id: str, source_id: str, binding_version: int, slot: str) -> str:
    value = json.dumps({"route": route_id, "candidate": candidate_id, "source": source_id, "binding": binding_version, "slot": slot}, sort_keys=True, separators=(",", ":"))
    return hashlib.sha256(value.encode()).hexdigest()


def _safe_code(value: str | None, fallback: str) -> str:
    import re

    return str(value) if value and re.fullmatch(r"[a-z][a-z0-9_]{1,95}", str(value)) else fallback


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


__all__ = ["ActorOpsProber", "ProbePreflightResult", "ProbeResult"]
