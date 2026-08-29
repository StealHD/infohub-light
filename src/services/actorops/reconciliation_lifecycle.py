"""Local monotonic lifecycle repairs used by ActorOps reconciliation."""

from __future__ import annotations

from collections.abc import Mapping
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


__all__ = ["settle_unstarted_after_terminal_job"]
