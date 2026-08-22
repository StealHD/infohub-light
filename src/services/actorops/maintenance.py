"""Generic, default-off Candidate Probe and safe standby maintenance."""

from __future__ import annotations

import hashlib
import json
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable, Mapping

from ...apify_actor_identity import source_target_fingerprint
from ..apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from .attempt_events import RepositoryAttemptEvents
from .attempt_recovery import request_fingerprint
from .domain import AssignmentRole, AttemptStatus, CandidateLifecycle, FailureClass
from .ports import (
    ActorManifest,
    CandidateProbePreflight,
    FetchWindow,
    ProbePreflightResult,
    RemoteActorClient,
    RemoteRunRequest,
)
from .registry import AdapterNotRegistered, AdapterRegistry
from .repository import ActorOpsConflict, ActorOpsRepository
from .runtime import ActorOpsRuntimeError


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
    ) -> ProbeResult:
        now = _utc(self.now())
        route = self.repository.get_route(route_id)
        candidate = self.repository.get_candidate(candidate_id)
        binding = self.repository.get_binding(source_id)
        policy = self.repository.maintenance.effective_policy(route_id)
        if not policy.authorized:
            return ProbeResult(None, candidate_id, "skipped", "actorops_maintenance_not_authorized")
        try:
            adapter = self.registry.require(route.route_key)
            target = adapter.normalize_target(source_config)
            manifest = _manifest(candidate)
        except (AdapterNotRegistered, TypeError, ValueError):
            return ProbeResult(None, candidate_id, "skipped", "actorops_maintenance_contract_invalid")
        raw_target = str(source_config.get("target") or "")
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
        preflight = await self.preflight.verify(
            candidate, max_charge_usd=policy.max_charge_usd
        )
        if not preflight.allowed:
            return ProbeResult(None, candidate_id, "skipped", _safe_code(preflight.error_code, "actorops_maintenance_preflight_rejected"))
        window = FetchWindow(max_items=1, since=now - timedelta(days=90), until=now)
        actor_input = adapter.build_actor_input(target, manifest, window)
        key = _idempotency_key(route_id, candidate_id, source_id, binding.binding_version, maintenance_slot)
        existing = self.repository.get_attempt_by_idempotency(key)
        if existing is not None:
            settled = (
                str(existing["status"]) in {"succeeded", "failed", "cancelled"}
                and bool(existing["cost_final"])
            )
            return ProbeResult(str(existing["attempt_id"]), candidate_id,
                               "already_settled" if settled else "recovery_required")
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
                )
        except ActorOpsConflict as error:
            return ProbeResult(None, candidate_id, "skipped", _safe_code(str(error), "actorops_maintenance_conflict"))
        request = RemoteRunRequest(
            attempt_id=attempt_id, candidate_id=candidate_id, actor_id=candidate.actor_id,
            build_number=str(candidate.build_number), actor_input=actor_input,
            max_total_charge_usd=policy.max_charge_usd,
            max_items=1, max_remote_starts=1, dataset_item_limit=1,
        )
        try:
            run = await self.remote.execute(
                request, RepositoryAttemptEvents(self.repository, attempt_id)
            )
        except ActorOpsRuntimeError as error:
            self._record_remote_failure(attempt_id, error)
            return ProbeResult(
                attempt_id, candidate_id,
                "recovery_required" if error.failure_class is FailureClass.REMOTE_UNKNOWN else "failed",
                error.code,
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
            batch = adapter.validate_output(run.rows, target, manifest, window)
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
        return self._promote_success(attempt_id, route, candidate, policy, run)

    def _promote_success(self, attempt_id: str, route: Any, candidate: Any, policy: Any, run: Any) -> ProbeResult:
        try:
            with self.repository.transaction():
                self.repository.complete_attempt(
                    attempt_id, status=AttemptStatus.SUCCEEDED, semantic_outcome="valid_nonempty",
                    actual_cost_usd=run.actual_cost_usd, cost_final=run.cost_final,
                )
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
                if current.assignment_role is AssignmentRole.INACTIVE:
                    replaced = False
                    if policy.route.auto_replace_non_last:
                        replaced = self.repository.maintenance.replace_unhealthy_non_last(
                            route.route_id, current.candidate_id,
                            expected_route_generation=route.generation,
                            expected_candidate_generation=current.generation,
                        )
                    if not replaced and policy.route.auto_add_standby:
                        self.repository.maintenance.add_standby(
                            route.route_id, current.candidate_id,
                            expected_route_generation=route.generation,
                            expected_candidate_generation=current.generation,
                        )
        except ActorOpsConflict:
            return ProbeResult(attempt_id, candidate.candidate_id, "completed")
        final = self.repository.get_candidate(candidate.candidate_id)
        return ProbeResult(attempt_id, candidate.candidate_id,
                           "promoted" if final.lifecycle is not CandidateLifecycle.STATIC_VALID else "completed")

    def _candidate_failure(self, attempt_id: str, candidate: Any, code: str, cost: float | None, cost_final: bool) -> None:
        try:
            with self.repository.transaction():
                self.repository.complete_attempt(
                    attempt_id, status=AttemptStatus.FAILED, semantic_outcome=code,
                    actual_cost_usd=cost, cost_final=cost_final,
                    failure_class=FailureClass.CANDIDATE.value, error_code=code,
                )
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
