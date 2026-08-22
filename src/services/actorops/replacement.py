"""One-user-approved, serial Actor replacement probes without Feed publication."""

from __future__ import annotations

import hashlib
import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any, Mapping

from ...apify_actor_identity import source_target_fingerprint
from ..apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from .attempt_events import RepositoryAttemptEvents
from .attempt_recovery import request_fingerprint
from .domain import AttemptStatus, CandidateLifecycle, FailureClass, ReplacementStatus
from .ports import ActorManifest, FetchWindow, RemoteActorClient, RemoteRunRequest
from .registry import AdapterNotRegistered, AdapterRegistry
from .repository import ActorOpsConflict, ActorOpsRepository
from .runtime import ActorOpsRuntimeError


class ActorOpsReplacementRunner:
    """Run at most one paid remote execution at a time for one chosen Candidate."""

    def __init__(self, repository: ActorOpsRepository, registry: AdapterRegistry, remote: RemoteActorClient, preflight: Any) -> None:
        self.repository = repository
        self.registry = registry
        self.remote = remote
        self.preflight = preflight

    async def run(self, plan_id: str, sources: Mapping[str, Mapping[str, object]]) -> dict[str, object]:
        plan = self.repository.operator.get_plan(plan_id)
        if plan.status is ReplacementStatus.PREVIEWED:
            return {"status": "previewed", "plan_id": plan.plan_id}
        if plan.status in {ReplacementStatus.READY, ReplacementStatus.APPLIED, ReplacementStatus.FAILED, ReplacementStatus.CANCELLED}:
            return {"status": plan.status.value, "plan_id": plan.plan_id}
        try:
            with self.repository.transaction():
                bindings = self.repository.operator.assert_plan_current(plan)
                if plan.status is ReplacementStatus.AUTHORIZED:
                    plan = self.repository.operator.transition_plan(
                        plan.plan_id, current=plan.status, target=ReplacementStatus.RUNNING,
                        expected_generation=plan.generation,
                    )
        except ActorOpsConflict:
            return self._stale(plan)
        if self.repository.operator.proofs_complete(plan):
            # Evidence is scoped to this exact Candidate and every frozen
            # ready Binding, so a replacement can be prepared with no new run.
            return self._ready(plan)
        completed, waiting, prior_failure = self._proof_state(plan, bindings)
        if prior_failure:
            # A reconciled remote attempt cannot yield publishable data in this
            # workflow.  It is safe to close this plan, but never to charge or
            # silently try another Actor.
            return self._fail(plan, prior_failure)
        if waiting:
            return {"status": "recovery_required", "plan_id": plan.plan_id}
        if len(completed) == len(bindings):
            return self._ready(plan)
        source_id, binding_version, fingerprint = next(item for item in bindings if item[0] not in completed)
        source = sources.get(source_id)
        if not isinstance(source, Mapping):
            return self._fail(plan, "actorops_replacement_source_missing")
        return await self._probe_one(plan, source_id, binding_version, fingerprint, source)

    def _proof_state(
        self, plan: Any, bindings: tuple[tuple[str, int, str], ...]
    ) -> tuple[set[str], bool, str | None]:
        completed: set[str] = set()
        waiting = False
        for source_id, binding_version, fingerprint in bindings:
            row = self.repository.connection.execute(
                """SELECT status, semantic_outcome, cost_final FROM actor_attempts_v2
                   WHERE workspace_id=? AND attempt_group_id=? AND candidate_id=? AND source_id=?
                     AND binding_version=? AND target_fingerprint=? AND kind='probe'
                   ORDER BY created_at DESC, attempt_id DESC LIMIT 1""",
                (self.repository.workspace_id, plan.plan_id, plan.proposed_candidate_id, source_id, binding_version, fingerprint),
            ).fetchone()
            if row is None:
                continue
            if str(row["status"]) not in {"succeeded", "failed", "cancelled"} or not bool(row["cost_final"]):
                waiting = True
                continue
            if str(row["status"]) == "succeeded" and str(row["semantic_outcome"]) == "valid_nonempty":
                completed.add(source_id)
                continue
            return completed, waiting, "actorops_replacement_prior_probe_failed"
        return completed, waiting, None

    async def _probe_one(self, plan: Any, source_id: str, binding_version: int, fingerprint: str, source: Mapping[str, object]) -> dict[str, object]:
        route = self.repository.get_route(plan.route_id)
        candidate = self.repository.get_candidate(plan.proposed_candidate_id)
        try:
            adapter = self.registry.require(route.route_key)
            target = adapter.normalize_target(source)
            manifest = _manifest(candidate)
            raw_target = str(source.get("target") or "")
            actual_fingerprint = source_target_fingerprint(self.repository.workspace_id, route.route_id, raw_target, platform=route.route_key.platform)
            if actual_fingerprint != fingerprint:
                raise ValueError("fingerprint")
            preflight = await self.preflight.verify_candidate(
                candidate, max_charge_usd=plan.per_probe_cap_usd,
            )
            if not preflight.allowed:
                return self._fail(plan, _safe_code(preflight.error_code, "actorops_replacement_preflight_rejected"))
            now = datetime.now(timezone.utc)
            window = FetchWindow(max_items=1, since=now - timedelta(days=90), until=now)
            actor_input = adapter.build_actor_input(target, manifest, window)
        except (AdapterNotRegistered, TypeError, ValueError):
            return self._candidate_failure(plan, None, "actorops_replacement_contract_invalid")
        key = _idempotency_key(plan.plan_id, source_id, binding_version, candidate.candidate_id)
        existing = self.repository.get_attempt_by_idempotency(key)
        if existing is not None:
            return {"status": "recovery_required", "plan_id": plan.plan_id, "attempt_id": str(existing["attempt_id"])}
        attempt_id = f"{uuid.uuid4().hex}-{key[:12]}"
        try:
            with self.repository.transaction():
                self.repository.operator.assert_plan_current(plan)
                self.repository.create_attempt(
                    attempt_id=attempt_id, idempotency_key=key, route_id=route.route_id,
                    source_id=source_id, candidate_id=candidate.candidate_id, kind="probe",
                    attempt_group_id=plan.plan_id, attempt_index=binding_version,
                    route_generation=route.generation, binding_version=binding_version,
                    target_fingerprint=fingerprint, reserved_usd=plan.per_probe_cap_usd,
                    logical_job_id=plan.plan_id,
                    request_fingerprint=request_fingerprint(
                        target_fingerprint=fingerprint,
                        candidate=candidate,
                        route_cap_usd=plan.per_probe_cap_usd,
                        window=window,
                    ),
                    window_since=window.since.isoformat(),
                    window_until=window.until.isoformat() if window.until else None,
                    max_items=window.max_items,
                )
        except ActorOpsConflict:
            return self._stale(plan)
        request = RemoteRunRequest(
            attempt_id=attempt_id, candidate_id=candidate.candidate_id, actor_id=candidate.actor_id,
            build_number=str(candidate.build_number), actor_input=actor_input,
            max_total_charge_usd=plan.per_probe_cap_usd, max_items=1, max_remote_starts=1,
            dataset_item_limit=1,
        )
        try:
            run = await self.remote.execute(request, RepositoryAttemptEvents(self.repository, attempt_id))
        except ActorOpsRuntimeError as error:
            return self._remote_failure(plan, attempt_id, error)
        except Exception:
            return self._remote_failure(plan, attempt_id, ActorOpsRuntimeError("actorops_replacement_remote_failed", failure_class=FailureClass.INTERNAL))
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
            return self._candidate_failure(plan, (attempt_id, run.actual_cost_usd, run.cost_final), "actorops_replacement_contract_mismatch")
        if batch.semantic_outcome != "valid_nonempty":
            return self._no_evidence(plan, attempt_id, run.actual_cost_usd, run.cost_final)
        return self._success(plan, attempt_id, candidate, run.actual_cost_usd, run.cost_final)

    def _success(self, plan: Any, attempt_id: str, candidate: Any, cost: float | None, cost_final: bool) -> dict[str, object]:
        try:
            with self.repository.transaction():
                self.repository.complete_attempt(attempt_id, status=AttemptStatus.SUCCEEDED, semantic_outcome="valid_nonempty", actual_cost_usd=cost, cost_final=cost_final)
                current = self.repository.record_candidate_outcome(candidate.candidate_id, expected_generation=candidate.generation, succeeded=True)
                if current.lifecycle is CandidateLifecycle.STATIC_VALID:
                    current = self.repository.transition_candidate(current.candidate_id, CandidateLifecycle.STATIC_VALID, CandidateLifecycle.PROBATIONARY, expected_generation=current.generation)
                count = self.repository.maintenance.successful_probe_targets(current.candidate_id)
                if current.lifecycle is CandidateLifecycle.PROBATIONARY and count >= 2:
                    current = self.repository.transition_candidate(current.candidate_id, CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED, expected_generation=current.generation)
                plan = self.repository.operator.refresh_proposed_generation(plan.plan_id, status=ReplacementStatus.RUNNING, expected_generation=plan.generation, proposed_candidate_generation=current.generation)
            return {"status": "proved", "plan_id": plan.plan_id, "attempt_id": attempt_id}
        except ActorOpsConflict:
            return self._stale(plan)

    def _no_evidence(self, plan: Any, attempt_id: str, cost: float | None, cost_final: bool) -> dict[str, object]:
        with self.repository.transaction():
            self.repository.complete_attempt(attempt_id, status=AttemptStatus.SUCCEEDED, semantic_outcome="no_evidence", actual_cost_usd=cost, cost_final=cost_final)
            if cost_final:
                self.repository.operator.transition_plan(plan.plan_id, current=ReplacementStatus.RUNNING, target=ReplacementStatus.FAILED, expected_generation=plan.generation, error_code="actorops_replacement_no_evidence")
            else:
                self.repository.operator.note_plan(plan.plan_id, status=ReplacementStatus.RUNNING, expected_generation=plan.generation, error_code="actorops_replacement_cost_pending")
        return {"status": "no_evidence", "plan_id": plan.plan_id, "attempt_id": attempt_id}

    def _candidate_failure(self, plan: Any, execution: tuple[str, float | None, bool] | None, code: str) -> dict[str, object]:
        candidate = self.repository.get_candidate(plan.proposed_candidate_id)
        with self.repository.transaction():
            if execution is not None:
                self.repository.complete_attempt(execution[0], status=AttemptStatus.FAILED, semantic_outcome=code, actual_cost_usd=execution[1], cost_final=execution[2], failure_class="candidate", error_code=code)
            current = self.repository.record_candidate_outcome(candidate.candidate_id, expected_generation=candidate.generation, succeeded=False, error_class="candidate", error_code=code)
            if current.lifecycle is CandidateLifecycle.STATIC_VALID:
                current = self.repository.transition_candidate(current.candidate_id, CandidateLifecycle.STATIC_VALID, CandidateLifecycle.REJECTED, expected_generation=current.generation, error_class="candidate", error_code=code)
            elif current.lifecycle in {CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED}:
                current = self.repository.transition_candidate(current.candidate_id, current.lifecycle, CandidateLifecycle.QUARANTINED, expected_generation=current.generation, error_class="candidate", error_code=code)
            self.repository.operator.transition_plan(plan.plan_id, current=ReplacementStatus.RUNNING, target=ReplacementStatus.FAILED, expected_generation=plan.generation, error_code=code, proposed_candidate_generation=current.generation)
        return {"status": "failed", "plan_id": plan.plan_id, "error_code": code}

    def _remote_failure(self, plan: Any, attempt_id: str, error: ActorOpsRuntimeError) -> dict[str, object]:
        row = self.repository.get_attempt(attempt_id)
        current = AttemptStatus(str(row["status"]))
        with self.repository.transaction():
            if error.failure_class is FailureClass.REMOTE_UNKNOWN:
                if current is AttemptStatus.STARTING:
                    self.repository.transition_attempt(attempt_id, current, AttemptStatus.START_UNKNOWN, error_class=error.failure_class.value, error_code=error.code, expected_generation=int(row["generation"]))
                self.repository.operator.note_plan(plan.plan_id, status=ReplacementStatus.RUNNING, expected_generation=plan.generation, error_code=error.code)
                return {"status": "recovery_required", "plan_id": plan.plan_id, "attempt_id": attempt_id}
            if current in {AttemptStatus.STARTING, AttemptStatus.REGISTERED, AttemptStatus.RUNNING}:
                self.repository.complete_attempt(attempt_id, status=AttemptStatus.FAILED, semantic_outcome=error.code, actual_cost_usd=None, cost_final=False, failure_class=error.failure_class.value, error_code=error.code)
            self.repository.operator.transition_plan(plan.plan_id, current=ReplacementStatus.RUNNING, target=ReplacementStatus.FAILED, expected_generation=plan.generation, error_code=error.code)
        return {"status": "failed", "plan_id": plan.plan_id, "attempt_id": attempt_id, "error_code": error.code}

    def _ready(self, plan: Any) -> dict[str, object]:
        try:
            with self.repository.transaction():
                ready = self.repository.operator.transition_plan(plan.plan_id, current=plan.status, target=ReplacementStatus.READY, expected_generation=plan.generation)
            return {"status": ready.status.value, "plan_id": plan.plan_id}
        except ActorOpsConflict:
            return self._stale(plan)

    def _fail(self, plan: Any, code: str) -> dict[str, object]:
        with self.repository.transaction():
            self.repository.operator.transition_plan(plan.plan_id, current=plan.status, target=ReplacementStatus.FAILED, expected_generation=plan.generation, error_code=code)
        return {"status": "failed", "plan_id": plan.plan_id, "error_code": code}

    def _stale(self, plan: Any) -> dict[str, object]:
        return {"status": "failed", "plan_id": plan.plan_id, "error_code": "actorops_replacement_plan_stale"}


def _manifest(candidate: Any) -> ActorManifest:
    if not all((candidate.actor_id, candidate.build_id, candidate.build_number, candidate.manifest_json, candidate.manifest_hash)):
        raise ValueError("candidate revision incomplete")
    parsed = parse_actor_manifest(str(candidate.manifest_json))
    if parsed.actor_id != candidate.actor_id or parsed.build_number != candidate.build_number or actor_manifest_hash(parsed) != candidate.manifest_hash:
        raise ValueError("candidate revision changed")
    return ActorManifest(candidate.actor_id, str(candidate.build_id), str(candidate.build_number), str(candidate.manifest_json), str(candidate.manifest_hash))


def _idempotency_key(plan_id: str, source_id: str, binding_version: int, candidate_id: str) -> str:
    return hashlib.sha256(json.dumps((plan_id, source_id, binding_version, candidate_id), separators=(",", ":")).encode()).hexdigest()


def _safe_code(value: object, fallback: str) -> str:
    import re
    return str(value) if isinstance(value, str) and re.fullmatch(r"[a-z][a-z0-9_]{1,95}", value) else fallback


__all__ = ["ActorOpsReplacementRunner"]
