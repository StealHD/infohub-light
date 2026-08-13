"""Transaction boundary for user-requested job cancellation."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any, Callable

from ..storage.service_store import ServiceStore


def cancel_job(
    store: ServiceStore,
    get_job: Callable[[str], dict[str, Any] | None],
    job_id: str,
    *,
    user_id: str | None = None,
) -> dict[str, Any]:
    now = datetime.now(timezone.utc).isoformat()
    conn = store.connect()
    try:
        conn.execute("BEGIN IMMEDIATE")
        current = get_job(job_id)
        if current is None:
            raise LookupError("job not found")
        if user_id is not None and current["user_id"] != user_id:
            raise PermissionError("cannot cancel another user's job")
        if current["status"] == "cancelled" and current.get("cancelled_at"):
            conn.commit()
            return current
        if current["status"] == "queued":
            conn.execute(
                """
                UPDATE fetch_jobs
                SET status = 'cancelled',
                    worker_id = NULL,
                    claim_token = NULL,
                    locked_until = NULL,
                    cancelled_at = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'queued'
                """,
                (now, now, now, job_id),
            )
        elif current["status"] == "running" and current.get("job_type") == "user_feed_refresh":
            conn.execute(
                """
                UPDATE fetch_jobs
                SET cancelled_at = COALESCE(cancelled_at, ?),
                    updated_at = ?
                WHERE id = ? AND status = 'running'
                  AND job_type = 'user_feed_refresh'
                """,
                (now, now, job_id),
            )
        else:
            raise ValueError(
                "only queued jobs and running user Feed refreshes can be cancelled"
            )
        conn.commit()
    except Exception:
        if conn.in_transaction:
            conn.rollback()
        raise
    updated = get_job(job_id)
    if updated is None:
        raise LookupError("job not found after cancellation")
    return updated
