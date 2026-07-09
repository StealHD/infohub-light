"""SQLite-backed job queue for source tests and fetches."""

from __future__ import annotations

import json
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.service_store import JOB_STATUSES, ServiceStore


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"job_{uuid.uuid4().hex}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _parse_iso(value: str | None) -> datetime | None:
    if not value:
        return None
    return datetime.fromisoformat(value)


class JobQueue:
    """Small durable queue stored in ServiceStore's SQLite database."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    def create_job(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_type: str,
        payload: dict[str, Any] | None = None,
        source_id: str | None = None,
        subscription_id: str | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        delay_seconds: float = 0,
        retention_days: int | None = None,
    ) -> dict[str, Any]:
        job_id = _new_id()
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        next_run_at = (now_dt + timedelta(seconds=max(float(delay_seconds), 0))).isoformat()
        expires_at = (now_dt + timedelta(days=retention_days)).isoformat() if retention_days else None
        self.store.connect().execute(
            """
            INSERT INTO fetch_jobs (
                id, workspace_id, user_id, source_id, subscription_id,
                job_type, status, priority, attempts, payload_json,
                max_attempts, next_run_at, expires_at, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
            """,
            (
                job_id,
                workspace_id,
                user_id,
                source_id,
                subscription_id,
                job_type,
                "queued",
                int(priority),
                0,
                _json_dumps(payload or {}),
                max(1, int(max_attempts)),
                next_run_at,
                expires_at,
                now,
                now,
            ),
        )
        self.store.connect().commit()
        job = self.get_job(job_id)
        if job is None:
            raise LookupError("created job not found")
        return job

    def get_job(self, job_id: str) -> dict[str, Any] | None:
        return self.store._job(
            self.store.connect().execute(
                "SELECT * FROM fetch_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
        )

    def list_jobs(
        self,
        *,
        workspace_id: str,
        user_id: str | None = None,
        status: str | None = None,
        limit: int = 50,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [workspace_id]
        where = ["workspace_id = ?"]
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        if status:
            where.append("status = ?")
            params.append(status)
        params.append(int(limit))
        rows = self.store.connect().execute(
            f"""
            SELECT *
            FROM fetch_jobs
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            params,
        ).fetchall()
        return [job for row in rows if (job := self.store._job(row))]

    def claim_next_job(self, *, worker_id: str, lease_seconds: float = 900) -> dict[str, Any] | None:
        conn = self.store.connect()
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        locked_until = (now_dt + timedelta(seconds=max(float(lease_seconds), 1))).isoformat()
        row = conn.execute(
            """
            SELECT *
            FROM fetch_jobs
            WHERE status = 'queued'
              AND (next_run_at IS NULL OR next_run_at <= ?)
            ORDER BY priority DESC, created_at
            LIMIT 1
            """,
            (now,),
        ).fetchone()
        if row is None:
            return None
        job_id = row["id"]
        conn.execute(
            """
            UPDATE fetch_jobs
            SET status = 'running',
                attempts = attempts + 1,
                worker_id = ?,
                started_at = COALESCE(started_at, ?),
                locked_until = ?,
                updated_at = ?
            WHERE id = ? AND status = 'queued'
            """,
            (worker_id, now, locked_until, now, job_id),
        )
        conn.commit()
        return self.get_job(job_id)

    def complete_job(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
    ) -> dict[str, Any]:
        if status not in JOB_STATUSES - {"queued", "running"}:
            raise ValueError("completion status must be succeeded, failed, or partial")
        now = _now_iso()
        self.store.connect().execute(
            """
            UPDATE fetch_jobs
            SET status = ?,
                result_json = ?,
                error_code = ?,
                error_message = ?,
                worker_id = NULL,
                locked_until = NULL,
                finished_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                _json_dumps(result) if result is not None else None,
                error_code,
                error_message,
                now,
                now,
                job_id,
            ),
        )
        self.store.connect().commit()
        job = self.get_job(job_id)
        if job is None:
            raise LookupError("job not found")
        return job

    def fail_or_retry_job(
        self,
        job_id: str,
        *,
        error_code: str,
        error_message: str,
        retryable: bool = True,
        retry_base_seconds: float = 30,
    ) -> dict[str, Any]:
        current = self.get_job(job_id)
        if current is None:
            raise LookupError("job not found")
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        attempts = int(current.get("attempts") or 0)
        max_attempts = int(current.get("max_attempts") or 1)
        should_retry = retryable and attempts < max_attempts
        if should_retry:
            delay = max(float(retry_base_seconds), 0) * (2 ** max(attempts - 1, 0))
            self.store.connect().execute(
                """
                UPDATE fetch_jobs
                SET status = 'queued',
                    worker_id = NULL,
                    locked_until = NULL,
                    next_run_at = ?,
                    error_code = ?,
                    error_message = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    (now_dt + timedelta(seconds=delay)).isoformat(),
                    error_code,
                    error_message,
                    now,
                    job_id,
                ),
            )
        else:
            self.store.connect().execute(
                """
                UPDATE fetch_jobs
                SET status = 'failed',
                    worker_id = NULL,
                    locked_until = NULL,
                    error_code = ?,
                    error_message = ?,
                    finished_at = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (error_code, error_message, now, now, job_id),
            )
        self.store.connect().commit()
        updated = self.get_job(job_id)
        if updated is None:
            raise LookupError("job not found after update")
        return updated

    def requeue_stale_running_jobs(self, now: datetime | None = None) -> int:
        now_dt = now or datetime.now(timezone.utc)
        now_iso = now_dt.isoformat()
        cur = self.store.connect().execute(
            """
            UPDATE fetch_jobs
            SET status = 'queued',
                worker_id = NULL,
                locked_until = NULL,
                error_code = 'lease_expired',
                error_message = 'Worker lease expired before completion',
                updated_at = ?
            WHERE status = 'running'
              AND locked_until IS NOT NULL
              AND locked_until < ?
            """,
            (now_iso, now_iso),
        )
        self.store.connect().commit()
        return cur.rowcount

    def cancel_job(self, job_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        current = self.get_job(job_id)
        if current is None:
            raise LookupError("job not found")
        if user_id is not None and current["user_id"] != user_id:
            raise PermissionError("cannot cancel another user's job")
        if current["status"] != "queued":
            raise ValueError("only queued jobs can be cancelled")
        now = _now_iso()
        self.store.connect().execute(
            """
            UPDATE fetch_jobs
            SET status = 'cancelled',
                cancelled_at = ?,
                finished_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (now, now, now, job_id),
        )
        self.store.connect().commit()
        updated = self.get_job(job_id)
        if updated is None:
            raise LookupError("job not found after cancellation")
        return updated

    def retry_job(self, job_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        current = self.get_job(job_id)
        if current is None:
            raise LookupError("job not found")
        if user_id is not None and current["user_id"] != user_id:
            raise PermissionError("cannot retry another user's job")
        if current["status"] not in {"failed", "partial", "cancelled"}:
            raise ValueError("only failed, partial, or cancelled jobs can be retried")
        now = _now_iso()
        self.store.connect().execute(
            """
            UPDATE fetch_jobs
            SET status = 'queued',
                attempts = 0,
                worker_id = NULL,
                locked_until = NULL,
                next_run_at = ?,
                cancelled_at = NULL,
                finished_at = NULL,
                error_code = NULL,
                error_message = NULL,
                updated_at = ?
            WHERE id = ?
            """,
            (now, now, job_id),
        )
        self.store.connect().commit()
        updated = self.get_job(job_id)
        if updated is None:
            raise LookupError("job not found after retry")
        return updated

    def prune_terminal_jobs(self, now: datetime | None = None) -> int:
        now_dt = now or datetime.now(timezone.utc)
        cur = self.store.connect().execute(
            """
            DELETE FROM fetch_jobs
            WHERE status IN ('succeeded', 'failed', 'partial', 'cancelled')
              AND expires_at IS NOT NULL
              AND expires_at < ?
            """,
            (now_dt.isoformat(),),
        )
        self.store.connect().commit()
        return cur.rowcount
