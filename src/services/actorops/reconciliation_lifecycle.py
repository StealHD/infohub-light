"""Local monotonic lifecycle repairs used by ActorOps reconciliation."""

from __future__ import annotations

from collections.abc import Mapping
from datetime import datetime, timezone
from typing import Any

from .domain import AttemptStatus, FailureClass


_TERMINAL_JOB_STATUSES = ("succeeded", "failed", "partial", "cancelled")


def settle_unstarted_after_terminal_job(
    repository: Any, row: Mapping[str, object]
) -> bool:
    """Cancel one created Attempt only after its exact Job is terminal."""

    with repository.transaction():
        job = repository.connection.execute(
            """SELECT 1 FROM fetch_jobs
                WHERE id=? AND workspace_id=?
                  AND status IN (?,?,?,?)""",
            (
                str(row["logical_job_id"] or ""),
                repository.workspace_id,
                *_TERMINAL_JOB_STATUSES,
            ),
        ).fetchone()
        if job is None:
            return False
        reservation = repository.connection.execute(
            """SELECT 1 FROM apify_actor_runs
                WHERE workspace_id=? AND purpose='acquisition'
                  AND logical_run_id=? LIMIT 1""",
            (
                repository.workspace_id,
                str(row["attempt_id"]),
            ),
        ).fetchone()
        if reservation is not None:
            return False
        repository.reconcile_attempt(
            str(row["attempt_id"]),
            expected_status=AttemptStatus.CREATED,
            expected_generation=int(row["generation"]),
            target_status=AttemptStatus.CANCELLED,
            remote_run_id=None,
            dataset_id=None,
            semantic_outcome="actorops_reconciled_no_reservation",
            actual_cost_usd=0.0,
            cost_final=True,
            failure_class=FailureClass.REMOTE_UNKNOWN.value,
            error_code="actorops_reconciled_no_reservation",
        )
    return True


def recover_observed_result_after_terminal_job(
    repository: Any, row: Mapping[str, object]
) -> str | None:
    """Queue the exact failed Job, or preserve an explicit cancellation."""

    attempt_id = str(row["attempt_id"])
    job_id = str(row["logical_job_id"] or "")
    source_id = str(row["source_id"] or "")
    if not job_id or not source_id:
        return None
    stamp = datetime.now(timezone.utc).isoformat()
    with repository.transaction():
        current = repository.get_attempt(attempt_id)
        if (
            int(current["generation"]) != int(row["generation"])
            or str(current["status"]) not in {"registered", "running"}
            or str(current["result_state"]) != "observed"
            or not bool(current["cost_final"])
            or not current["remote_run_id"]
            or not current["dataset_id"]
        ):
            return None
        job = repository.connection.execute(
            """SELECT status FROM fetch_jobs
                WHERE id=? AND workspace_id=? AND job_type='source_fetch'
                  AND source_id=?""",
            (job_id, repository.workspace_id, source_id),
        ).fetchone()
        if job is None:
            return None
        if str(job["status"]) == "cancelled":
            repository.reconcile_attempt(
                attempt_id,
                expected_status=AttemptStatus(str(current["status"])),
                expected_generation=int(current["generation"]),
                target_status=AttemptStatus.CANCELLED,
                remote_run_id=None,
                dataset_id=None,
                semantic_outcome="actorops_result_recovery_cancelled",
                actual_cost_usd=None,
                cost_final=True,
                failure_class=FailureClass.REMOTE_UNKNOWN.value,
                error_code="actorops_result_recovery_cancelled",
            )
            return "cancelled"
        if str(job["status"]) not in {"failed", "partial"}:
            return None
        active = repository.connection.execute(
            """SELECT 1 FROM fetch_jobs
                WHERE workspace_id=? AND source_id=? AND job_type='source_fetch'
                  AND status IN ('queued','running') AND id<>? LIMIT 1""",
            (repository.workspace_id, source_id, job_id),
        ).fetchone()
        if active is not None:
            return None
        changed = repository.connection.execute(
            """UPDATE fetch_jobs
                  SET status='queued', worker_id=NULL, claim_token=NULL,
                      locked_until=NULL, next_run_at=?, cancelled_at=NULL,
                      finished_at=NULL, error_code=NULL, error_message=NULL,
                      result_json=NULL, started_at=NULL, updated_at=?
                WHERE id=? AND workspace_id=? AND status IN ('failed','partial')""",
            (stamp, stamp, job_id, repository.workspace_id),
        ).rowcount
        if changed != 1:
            return None
        repository.reconcile_attempt(
            attempt_id,
            expected_status=AttemptStatus(str(current["status"])),
            expected_generation=int(current["generation"]),
            target_status=None,
            remote_run_id=None,
            dataset_id=None,
            semantic_outcome=None,
            actual_cost_usd=None,
            cost_final=True,
            failure_class=FailureClass.REMOTE_UNKNOWN.value,
            error_code="actorops_result_recovery_queued",
        )
    return "queued"


__all__ = [
    "recover_observed_result_after_terminal_job",
    "settle_unstarted_after_terminal_job",
]
