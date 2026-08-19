"""Safe recovery for Worker failures before a job has started."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .job_queue import JobQueue


def requeue_unstarted_claim(
    queue: JobQueue,
    job: dict[str, Any],
    *,
    error_code: str,
) -> dict[str, Any] | None:
    """Return an unstarted claim to the queue without spending an attempt.

    This is deliberately limited to the exact active claim.  It is used only
    when Worker liveness cannot start, before a job handler (and therefore a
    paid Actor invocation) can have run.
    """

    connection = queue.store.connect()
    now = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute("BEGIN IMMEDIATE")
        cursor = connection.execute(
            """
            UPDATE fetch_jobs
            SET status = 'queued',
                attempts = CASE WHEN attempts > 0 THEN attempts - 1 ELSE 0 END,
                worker_id = NULL,
                claim_token = NULL,
                locked_until = NULL,
                next_run_at = ?,
                error_code = ?,
                error_message = 'Worker could not start the job; retrying',
                updated_at = ?
            WHERE id = ?
              AND status = 'running'
              AND worker_id = ?
              AND claim_token = ?
            """,
            (
                now,
                error_code,
                now,
                str(job["id"]),
                str(job["worker_id"]),
                str(job["claim_token"]),
            ),
        )
        if cursor.rowcount != 1:
            connection.rollback()
            return None
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return queue.get_job(str(job["id"]))
