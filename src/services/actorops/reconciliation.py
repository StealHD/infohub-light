"""Read-only remote reconciliation for durable ActorOps v2 Attempts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Callable

from .candidate_failure_settlement import record_settled_candidate_failure
from .domain import AttemptStatus, FailureClass, TERMINAL_ATTEMPT_STATUSES
from .ports import (
    ReconciliationRunLink,
    ReconciliationRunObservation,
    RemoteRunLedger,
)
from .reconciliation_lifecycle import settle_unstarted_after_terminal_job
from .recovery_probe import (
    RECOVERY_ATTEMPT_GROUP_PREFIX,
    apply_settled_recovery_success,
    settled_recovery_candidate_ids,
)
from .repository import ActorOpsConflict, ActorOpsRepository


_REMOTE_RUNNING = frozenset({"ready", "running", "aborting"})
_REMOTE_SUCCEEDED = frozenset({"succeeded"})
_REMOTE_TERMINAL_FAILURE = frozenset(
    {"failed", "aborted", "timed_out", "cancelled"}
)
_UNPUBLISHED_SUCCESS_GRACE_SECONDS = 60.0


@dataclass(frozen=True, slots=True)
class ReconciliationSummary:
    scanned: int = 0
    remote_reads: int = 0
    settled: int = 0
    pending: int = 0
    ambiguous: int = 0
    errors: int = 0


class ActorOpsReconciler:
    """Settle facts already created by Runtime without publishing any content."""

    def __init__(
        self,
        repository: ActorOpsRepository,
        ledger: RemoteRunLedger,
        *,
        scan_limit: int = 20,
        remote_read_limit: int = 5,
        unpublished_success_grace_seconds: float = _UNPUBLISHED_SUCCESS_GRACE_SECONDS,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.repository = repository
        self.ledger = ledger
        self.scan_limit = min(max(int(scan_limit), 1), 100)
        self.remote_read_limit = min(max(int(remote_read_limit), 1), self.scan_limit)
        self.unpublished_success_grace_seconds = max(
            float(unpublished_success_grace_seconds), 0.0
        )
        self.now = now or (lambda: datetime.now(timezone.utc))

    async def reconcile(self) -> ReconciliationSummary:
        summary = ReconciliationSummary()
        reads_remaining = self.remote_read_limit
        for row in self.repository.list_reconcilable_attempts(limit=self.scan_limit):
            summary = self._replace(summary, scanned=summary.scanned + 1)
            try:
                result = await self._reconcile_row(row, reads_remaining)
            except ActorOpsConflict:
                summary = self._replace(summary, errors=summary.errors + 1)
                continue
            except Exception:
                self._mark_error(row, "actorops_reconcile_read_failed")
                summary = self._replace(summary, errors=summary.errors + 1)
                continue
            summary = self._replace(
                summary,
                remote_reads=summary.remote_reads + result.remote_reads,
                settled=summary.settled + result.settled,
                pending=summary.pending + result.pending,
                ambiguous=summary.ambiguous + result.ambiguous,
                errors=summary.errors + result.errors,
            )
            reads_remaining = max(reads_remaining - result.remote_reads, 0)
        recovery_errors = self._project_settled_recoveries()
        return self._replace(summary, errors=summary.errors + recovery_errors)

    async def _reconcile_row(
        self, row: Mapping[str, object], reads_remaining: int
    ) -> ReconciliationSummary:
        current = AttemptStatus(str(row["status"]))
        resolution = await self.ledger.resolve(row)
        if resolution.ambiguous:
            self._mark_error(row, "actorops_reconcile_ambiguous_run")
            return ReconciliationSummary(ambiguous=1)
        link = resolution.link
        if link is None:
            if current is AttemptStatus.CREATED and resolution.reservation_absent:
                if settle_unstarted_after_terminal_job(self.repository, row):
                    self._wake_repairs_after_cost_settlement(row)
                    return ReconciliationSummary(settled=1)
                self._mark_error(row, "actorops_reconcile_run_missing")
                return ReconciliationSummary(pending=1)
            self._mark_error(row, "actorops_reconcile_run_missing")
            return ReconciliationSummary(pending=1)
        if (
            not link.remote_run_id
            and str(link.status).casefold() == "start_rejected"
        ):
            if current not in {
                AttemptStatus.CREATED,
                AttemptStatus.STARTING,
                AttemptStatus.START_UNKNOWN,
                *TERMINAL_ATTEMPT_STATUSES,
            }:
                self._mark_error(row, "actorops_reconcile_run_missing")
                return ReconciliationSummary(pending=1)
            try:
                await self.ledger.settle_proven_no_start(link)
            except Exception:
                self._mark_error(row, "actorops_reconcile_settlement_failed")
                return ReconciliationSummary(errors=1)
            terminal = current in TERMINAL_ATTEMPT_STATUSES
            self._mutate(
                row,
                target=(
                    None
                    if terminal
                    else AttemptStatus.CANCELLED
                    if current is AttemptStatus.CREATED
                    else AttemptStatus.FAILED
                ),
                semantic_outcome=(None if terminal else "actorops_proven_no_start"),
                actual_cost_usd=0.0,
                cost_final=True,
                failure_class=(
                    None if terminal else FailureClass.REMOTE_UNKNOWN.value
                ),
                error_code=(None if terminal else "actorops_proven_no_start"),
            )
            return ReconciliationSummary(settled=1)
        if link.remote_run_id:
            if reads_remaining <= 0:
                self._mark_error(row, "actorops_reconcile_deferred")
                return ReconciliationSummary(pending=1)
            try:
                observation = await self.ledger.read_known(link)
            except Exception:
                self._mark_error(row, "actorops_reconcile_read_failed")
                return ReconciliationSummary(remote_reads=1, errors=1)
            try:
                return self._settle_known(row, link, observation)
            except ActorOpsConflict:
                return ReconciliationSummary(remote_reads=1, errors=1)
            except Exception:
                self._mark_error(row, "actorops_reconcile_settlement_failed")
                return ReconciliationSummary(remote_reads=1, errors=1)
        if current not in {
            AttemptStatus.CREATED,
            AttemptStatus.STARTING,
            AttemptStatus.START_UNKNOWN,
        }:
            self._mark_error(row, "actorops_reconcile_run_missing")
            return ReconciliationSummary(pending=1)
        if reads_remaining <= 0:
            self._mark_error(row, "actorops_reconcile_deferred")
            return ReconciliationSummary(pending=1)
        try:
            proven_no_start = await self.ledger.prove_no_start(link)
        except Exception:
            self._mark_error(row, "actorops_reconcile_read_failed")
            return ReconciliationSummary(remote_reads=1, errors=1)
        if not proven_no_start:
            self._mark_error(row, "actorops_reconcile_pending")
            return ReconciliationSummary(remote_reads=1, pending=1)
        try:
            await self.ledger.settle_proven_no_start(link)
        except Exception:
            self._mark_error(row, "actorops_reconcile_settlement_failed")
            return ReconciliationSummary(remote_reads=1, errors=1)
        try:
            self._mutate(
                row,
                target=(
                    AttemptStatus.CANCELLED
                    if current is AttemptStatus.CREATED
                    else AttemptStatus.FAILED
                ),
                semantic_outcome="actorops_proven_no_start",
                actual_cost_usd=0.0,
                cost_final=True,
                failure_class=FailureClass.REMOTE_UNKNOWN.value,
                error_code="actorops_proven_no_start",
            )
        except ActorOpsConflict:
            return ReconciliationSummary(remote_reads=1, errors=1)
        return ReconciliationSummary(remote_reads=1, settled=1)

    def _settle_known(
        self,
        row: Mapping[str, object],
        link: ReconciliationRunLink,
        observation: ReconciliationRunObservation,
    ) -> ReconciliationSummary:
        current = AttemptStatus(str(row["status"]))
        if current in {AttemptStatus.STARTING, AttemptStatus.START_UNKNOWN}:
            self._mutate(
                row,
                target=AttemptStatus.REGISTERED,
                remote_run_id=link.remote_run_id,
                dataset_id=observation.dataset_id or link.dataset_id,
            )
            row = self.repository.get_attempt(str(row["attempt_id"]))
            current = AttemptStatus(str(row["status"]))
        normalized = str(observation.status).strip().casefold().replace("-", "_")
        if normalized in _REMOTE_RUNNING:
            self._mutate(
                row,
                target=(AttemptStatus.RUNNING if current is AttemptStatus.REGISTERED else None),
                remote_run_id=link.remote_run_id,
                dataset_id=observation.dataset_id or link.dataset_id,
                error_code="actorops_remote_pending",
            )
            return ReconciliationSummary(remote_reads=1, pending=1)
        if normalized in _REMOTE_SUCCEEDED:
            if current in TERMINAL_ATTEMPT_STATUSES:
                self._mutate(
                    row,
                    target=None,
                    remote_run_id=link.remote_run_id,
                    dataset_id=observation.dataset_id or link.dataset_id,
                    actual_cost_usd=observation.actual_cost_usd,
                    cost_final=observation.cost_final,
                    candidate_failure_outcome="paid_candidate_failure",
                )
            elif not self._unpublished_success_is_stale(row):
                # The Runtime can still be validating rows or entering its
                # publication fence after Apify reports a completed Run.
                # Do not race that in-process handoff into a terminal fact.
                return ReconciliationSummary(remote_reads=1, pending=1)
            else:
                self._mutate(
                    row,
                    target=None,
                    remote_run_id=link.remote_run_id,
                    dataset_id=observation.dataset_id or link.dataset_id,
                    actual_cost_usd=observation.actual_cost_usd,
                    cost_final=observation.cost_final,
                )
            return ReconciliationSummary(remote_reads=1, settled=1)
        if normalized in _REMOTE_TERMINAL_FAILURE:
            if current in TERMINAL_ATTEMPT_STATUSES:
                self._mutate(
                    row,
                    target=None,
                    remote_run_id=link.remote_run_id,
                    dataset_id=observation.dataset_id or link.dataset_id,
                    actual_cost_usd=observation.actual_cost_usd,
                    cost_final=observation.cost_final,
                    candidate_failure_outcome="paid_candidate_failure",
                )
            else:
                code = f"actorops_reconciled_remote_{normalized}"
                self._mutate(
                    row,
                    target=AttemptStatus.FAILED,
                    remote_run_id=link.remote_run_id,
                    dataset_id=observation.dataset_id or link.dataset_id,
                    semantic_outcome=code,
                    actual_cost_usd=observation.actual_cost_usd,
                    cost_final=observation.cost_final,
                    failure_class=FailureClass.REMOTE_UNKNOWN.value,
                    error_code=code,
                    candidate_failure_outcome="paid_candidate_failure",
                )
            return ReconciliationSummary(remote_reads=1, settled=1)
        self._mark_error(row, "actorops_reconcile_status_unknown")
        return ReconciliationSummary(remote_reads=1, pending=1)

    def _mutate(
        self,
        row: Mapping[str, object],
        *,
        target: AttemptStatus | None,
        remote_run_id: str | None = None,
        dataset_id: str | None = None,
        semantic_outcome: str | None = None,
        actual_cost_usd: float | None = None,
        cost_final: bool = False,
        failure_class: str | None = None,
        error_code: str | None = None,
        candidate_failure_outcome: str | None = None,
    ) -> None:
        became_cost_final = bool(cost_final) and not bool(row["cost_final"])
        with self.repository.transaction():
            self.repository.reconcile_attempt(
                str(row["attempt_id"]),
                expected_status=AttemptStatus(str(row["status"])),
                expected_generation=int(row["generation"]),
                target_status=target,
                remote_run_id=remote_run_id,
                dataset_id=dataset_id,
                semantic_outcome=semantic_outcome,
                actual_cost_usd=actual_cost_usd,
                cost_final=cost_final,
                failure_class=failure_class,
                error_code=error_code,
            )
            if candidate_failure_outcome:
                record_settled_candidate_failure(
                    self.repository,
                    attempt_id=str(row["attempt_id"]),
                    outcome=candidate_failure_outcome,
                )
            if (
                became_cost_final
                and str(row["kind"]) == "probe"
                and str(row["attempt_group_id"]).startswith(
                    RECOVERY_ATTEMPT_GROUP_PREFIX
                )
            ):
                apply_settled_recovery_success(
                    self.repository, str(row["candidate_id"])
                )
        if became_cost_final:
            self._wake_repairs_after_cost_settlement(row)

    def _project_settled_recoveries(self) -> int:
        errors = 0
        for candidate_id in settled_recovery_candidate_ids(
            self.repository, limit=self.scan_limit
        ):
            try:
                apply_settled_recovery_success(self.repository, candidate_id)
            except Exception:
                errors += 1
        return errors

    def _wake_repairs_after_cost_settlement(
        self, row: Mapping[str, object]
    ) -> None:
        route_id = str(row["route_id"] or "")
        source_id = str(row["source_id"] or "")
        if not route_id or not source_id:
            return
        wake = getattr(
            self.repository.resilience,
            "wake_repairs_after_cost_settlement",
            None,
        )
        if not callable(wake):
            return
        try:
            wake(route_id=route_id, source_id=source_id)
        except Exception:
            # Cost settlement is the primary monotonic fact.  A best-effort
            # scheduler wake must never turn it back into reconciliation work.
            return

    def _mark_error(self, row: Mapping[str, object], code: str) -> None:
        try:
            with self.repository.transaction():
                self.repository.mark_reconciliation_error(
                    str(row["attempt_id"]),
                    expected_status=AttemptStatus(str(row["status"])),
                    expected_generation=int(row["generation"]),
                    failure_class=str(row["failure_class"] or "remote_unknown"),
                    error_code=code,
                )
        except ActorOpsConflict:
            return

    def _unpublished_success_is_stale(self, row: Mapping[str, object]) -> bool:
        raw_updated_at = str(row["updated_at"] or "")
        try:
            updated_at = datetime.fromisoformat(raw_updated_at)
        except ValueError:
            return True
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        else:
            updated_at = updated_at.astimezone(timezone.utc)
        now = self.now()
        if now.tzinfo is None:
            now = now.replace(tzinfo=timezone.utc)
        else:
            now = now.astimezone(timezone.utc)
        return (now - updated_at).total_seconds() >= self.unpublished_success_grace_seconds

    @staticmethod
    def _replace(summary: ReconciliationSummary, **changes: int) -> ReconciliationSummary:
        values = {
            "scanned": summary.scanned,
            "remote_reads": summary.remote_reads,
            "settled": summary.settled,
            "pending": summary.pending,
            "ambiguous": summary.ambiguous,
            "errors": summary.errors,
        }
        values.update(changes)
        return ReconciliationSummary(**values)


__all__ = ["ActorOpsReconciler", "ReconciliationSummary"]
