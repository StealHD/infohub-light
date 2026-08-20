"""Read-only remote reconciliation for durable ActorOps v2 Attempts."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass

from .domain import AttemptStatus, FailureClass, TERMINAL_ATTEMPT_STATUSES
from .ports import (
    ReconciliationRunLink,
    ReconciliationRunObservation,
    RemoteRunLedger,
)
from .repository import ActorOpsConflict, ActorOpsRepository


_REMOTE_RUNNING = frozenset({"ready", "running", "aborting"})
_REMOTE_SUCCEEDED = frozenset({"succeeded"})
_REMOTE_TERMINAL_FAILURE = frozenset(
    {"failed", "aborted", "timed_out", "cancelled"}
)


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
    ) -> None:
        self.repository = repository
        self.ledger = ledger
        self.scan_limit = min(max(int(scan_limit), 1), 100)
        self.remote_read_limit = min(max(int(remote_read_limit), 1), self.scan_limit)

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
        return summary

    async def _reconcile_row(
        self, row: Mapping[str, object], reads_remaining: int
    ) -> ReconciliationSummary:
        resolution = await self.ledger.resolve(row)
        if resolution.ambiguous:
            self._mark_error(row, "actorops_reconcile_ambiguous_run")
            return ReconciliationSummary(ambiguous=1)
        link = resolution.link
        if link is None:
            self._mark_error(row, "actorops_reconcile_run_missing")
            return ReconciliationSummary(pending=1)
        if link.remote_run_id:
            if reads_remaining <= 0:
                self._mark_error(row, "actorops_reconcile_deferred")
                return ReconciliationSummary(pending=1)
            try:
                observation = await self.ledger.read_known(link)
            except Exception:
                self._mark_error(row, "actorops_reconcile_read_failed")
                return ReconciliationSummary(remote_reads=1, errors=1)
            return self._settle_known(row, link, observation)
        if AttemptStatus(str(row["status"])) is not AttemptStatus.START_UNKNOWN:
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
        self._mutate(
            row,
            target=AttemptStatus.FAILED,
            semantic_outcome="actorops_proven_no_start",
            actual_cost_usd=0.0,
            cost_final=True,
            failure_class=FailureClass.REMOTE_UNKNOWN.value,
            error_code="actorops_proven_no_start",
        )
        return ReconciliationSummary(remote_reads=1, settled=1)

    def _settle_known(
        self,
        row: Mapping[str, object],
        link: ReconciliationRunLink,
        observation: ReconciliationRunObservation,
    ) -> ReconciliationSummary:
        current = AttemptStatus(str(row["status"]))
        if current is AttemptStatus.START_UNKNOWN:
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
                )
            else:
                self._mutate(
                    row,
                    target=AttemptStatus.FAILED,
                    remote_run_id=link.remote_run_id,
                    dataset_id=observation.dataset_id or link.dataset_id,
                    semantic_outcome="actorops_reconciled_unpublished_success",
                    actual_cost_usd=observation.actual_cost_usd,
                    cost_final=observation.cost_final,
                    failure_class=FailureClass.REMOTE_UNKNOWN.value,
                    error_code="actorops_reconciled_unpublished_success",
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
    ) -> None:
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

    def _mark_error(self, row: Mapping[str, object], code: str) -> None:
        try:
            with self.repository.transaction():
                self.repository.mark_reconciliation_error(
                    str(row["attempt_id"]),
                    expected_status=AttemptStatus(str(row["status"])),
                    expected_generation=int(row["generation"]),
                    error_code=code,
                )
        except ActorOpsConflict:
            return

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
