"""SQLite-backed job queue for source tests and fetches."""

from __future__ import annotations

import json
import uuid
from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.service_store import JOB_STATUSES, ServiceStore
from .job_cancellation import cancel_job as cancel_job_transaction
from .job_queue_claims import (
    claim_next_job as claim_next_job_transaction,
    recover_stale_running_jobs as recover_stale_running_jobs_transaction,
)


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

    @staticmethod
    def _claim_guard(
        worker_id: str,
        claim_token: str,
    ) -> tuple[str, tuple[str, ...]]:
        if not worker_id or not claim_token:
            raise ValueError("worker_id and claim_token are required")
        return "worker_id = ? AND claim_token = ?", (worker_id, claim_token)

    def _raise_claim_conflict(self, job_id: str) -> None:
        if self.get_job(job_id) is None:
            raise LookupError("job not found")
        raise PermissionError("job claim is no longer active")

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
        commit: bool = True,
    ) -> dict[str, Any]:
        if job_type == "user_feed_refresh":
            if not commit:
                raise ValueError(
                    "user_feed_refresh creation uses its own transaction boundary"
                )
            job, _created = self.create_user_feed_refresh_if_absent(
                workspace_id=workspace_id,
                user_id=user_id,
                payload=payload,
                priority=priority,
                max_attempts=max_attempts,
                delay_seconds=delay_seconds,
                retention_days=retention_days,
            )
            return job
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
        if commit:
            self.store.connect().commit()
        job = self.get_job(job_id)
        if job is None:
            raise LookupError("created job not found")
        return job

    def create_user_feed_refresh_if_absent(
        self,
        *,
        workspace_id: str,
        user_id: str,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        delay_seconds: float = 0,
        retention_days: int | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically return the user's active full refresh or create one."""
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            active_row = conn.execute(
                """
                SELECT *
                FROM fetch_jobs
                WHERE workspace_id = ?
                  AND user_id = ?
                  AND job_type = 'user_feed_refresh'
                  AND status IN ('queued', 'running')
                ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
                LIMIT 1
                """,
                (workspace_id, user_id),
            ).fetchone()
            if active_row is not None:
                job = self.store._job(active_row)
                if owns_transaction:
                    conn.commit()
                if job is None:
                    raise LookupError("active user feed refresh could not be loaded")
                return job, False

            job_id = _new_id()
            now_dt = datetime.now(timezone.utc)
            now = now_dt.isoformat()
            next_run_at = (
                now_dt + timedelta(seconds=max(float(delay_seconds), 0))
            ).isoformat()
            expires_at = (
                (now_dt + timedelta(days=retention_days)).isoformat()
                if retention_days
                else None
            )
            conn.execute(
                """
                INSERT INTO fetch_jobs (
                    id, workspace_id, user_id, source_id, subscription_id,
                    job_type, status, priority, attempts, payload_json,
                    max_attempts, next_run_at, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, NULL, NULL, 'user_feed_refresh', 'queued', ?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    workspace_id,
                    user_id,
                    int(priority),
                    _json_dumps(payload or {}),
                    max(1, int(max_attempts)),
                    next_run_at,
                    expires_at,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM fetch_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        job = self.store._job(row)
        if job is None:
            raise LookupError("created user feed refresh not found")
        return job, True

    def create_source_fetch_if_absent(
        self,
        *,
        workspace_id: str,
        user_id: str,
        source_id: str,
        subscription_id: str,
        payload: dict[str, Any] | None = None,
        priority: int = 0,
        max_attempts: int = 3,
        delay_seconds: float = 0,
        retention_days: int | None = None,
    ) -> tuple[dict[str, Any], bool]:
        """Atomically return the subscription's active fetch or create one."""
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            active_row = conn.execute(
                """
                SELECT *
                FROM fetch_jobs
                WHERE workspace_id = ?
                  AND user_id = ?
                  AND source_id = ?
                  AND subscription_id = ?
                  AND job_type = 'source_fetch'
                  AND status IN ('queued', 'running')
                ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
                LIMIT 1
                """,
                (workspace_id, user_id, source_id, subscription_id),
            ).fetchone()
            if active_row is not None:
                job = self.store._job(active_row)
                if owns_transaction:
                    conn.commit()
                if job is None:
                    raise LookupError("active source fetch could not be loaded")
                return job, False

            job_id = _new_id()
            now_dt = datetime.now(timezone.utc)
            now = now_dt.isoformat()
            next_run_at = (
                now_dt + timedelta(seconds=max(float(delay_seconds), 0))
            ).isoformat()
            expires_at = (
                (now_dt + timedelta(days=retention_days)).isoformat()
                if retention_days
                else None
            )
            conn.execute(
                """
                INSERT INTO fetch_jobs (
                    id, workspace_id, user_id, source_id, subscription_id,
                    job_type, status, priority, attempts, payload_json,
                    max_attempts, next_run_at, expires_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, 'source_fetch', 'queued', ?, 0, ?, ?, ?, ?, ?, ?)
                """,
                (
                    job_id,
                    workspace_id,
                    user_id,
                    source_id,
                    subscription_id,
                    int(priority),
                    _json_dumps(payload or {}),
                    max(1, int(max_attempts)),
                    next_run_at,
                    expires_at,
                    now,
                    now,
                ),
            )
            row = conn.execute(
                "SELECT * FROM fetch_jobs WHERE id = ?",
                (job_id,),
            ).fetchone()
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        job = self.store._job(row)
        if job is None:
            raise LookupError("created source fetch not found")
        return job, True

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
        job_types: list[str] | tuple[str, ...] | None = None,
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
        normalized_job_types = tuple(
            dict.fromkeys(str(job_type) for job_type in (job_types or ()))
        )
        if normalized_job_types:
            where.append(
                "job_type IN ("
                + ", ".join("?" for _job_type in normalized_job_types)
                + ")"
            )
            params.extend(normalized_job_types)
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

    @staticmethod
    def _job_summary_row(row: Any) -> dict[str, Any]:
        job = dict(row)
        summary = {
            key: job[key]
            for key in (
                "id",
                "user_id",
                "source_id",
                "subscription_id",
                "job_type",
                "status",
                "error_code",
                "error_message",
                "created_at",
                "started_at",
                "cancelled_at",
                "finished_at",
            )
            if key in job
        }
        if isinstance(summary.get("error_code"), str):
            summary["error_code"] = summary["error_code"][:64]
        if isinstance(summary.get("error_message"), str):
            summary["error_message"] = summary["error_message"][:240]
        compact_result: dict[str, Any] = {}
        message = job.get("summary_message")
        if isinstance(message, str):
            compact_result["message"] = message
        snapshot_created_type = job.get("summary_snapshot_created_type")
        if snapshot_created_type in {"true", "false"}:
            compact_result["snapshot_created"] = bool(
                job.get("summary_snapshot_created")
            )
        new_item_count = job.get("summary_new_item_count")
        if isinstance(new_item_count, int) and new_item_count >= 0:
            compact_result["new_item_count"] = new_item_count
        failed_source_count = job.get("summary_failed_source_count")
        if isinstance(failed_source_count, int) and failed_source_count >= 0:
            compact_result["failed_source_count"] = failed_source_count
        if compact_result:
            summary["result"] = compact_result
        return summary

    def list_job_summaries(
        self,
        *,
        workspace_id: str,
        user_id: str | None = None,
        status: str | None = None,
        job_types: list[str] | tuple[str, ...] | None = None,
        limit: int = 50,
        include_active: bool = False,
    ) -> list[dict[str, Any]]:
        params: list[Any] = [workspace_id]
        where = ["workspace_id = ?"]
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        if status:
            where.append("status = ?")
            params.append(status)
        normalized_job_types = tuple(
            dict.fromkeys(str(job_type) for job_type in (job_types or ()))
        )
        if normalized_job_types:
            where.append(
                "job_type IN ("
                + ", ".join("?" for _job_type in normalized_job_types)
                + ")"
            )
            params.extend(normalized_job_types)
        safe_result_json = (
            "CASE WHEN json_valid(result_json) THEN result_json END"
        )
        columns = f"""
            id, user_id, source_id, subscription_id, job_type, status,
            substr(error_code, 1, 64) AS error_code,
            substr(error_message, 1, 240) AS error_message,
            created_at, started_at, cancelled_at, finished_at,
            CASE
                WHEN json_type({safe_result_json}, '$.message') = 'text'
                THEN substr(json_extract({safe_result_json}, '$.message'), 1, 240)
            END AS summary_message,
            json_type({safe_result_json}, '$.snapshot_created')
                AS summary_snapshot_created_type,
            json_extract({safe_result_json}, '$.snapshot_created')
                AS summary_snapshot_created,
            CASE
                WHEN json_type({safe_result_json}, '$.new_item_count') = 'integer'
                  AND json_extract({safe_result_json}, '$.new_item_count') >= 0
                THEN json_extract({safe_result_json}, '$.new_item_count')
            END AS summary_new_item_count,
            CASE
                WHEN json_type({safe_result_json}, '$.failed_source_count') = 'integer'
                  AND json_extract({safe_result_json}, '$.failed_source_count') >= 0
                THEN json_extract({safe_result_json}, '$.failed_source_count')
                WHEN json_type({safe_result_json}, '$.source_outcomes') = 'array'
                THEN (
                    SELECT COUNT(*)
                    FROM json_each({safe_result_json}, '$.source_outcomes')
                    WHERE json_extract(value, '$.status') = 'failed'
                )
            END AS summary_failed_source_count
        """
        recent_rows = self.store.connect().execute(
            f"""
            SELECT {columns}
            FROM fetch_jobs
            WHERE {' AND '.join(where)}
            ORDER BY created_at DESC
            LIMIT ?
            """,
            [*params, int(limit)],
        ).fetchall()
        rows_by_id = {str(row["id"]): row for row in recent_rows}
        if include_active and status is None:
            active_rows = self.store.connect().execute(
                f"""
                SELECT {columns}
                FROM fetch_jobs
                WHERE {' AND '.join(where)}
                  AND status IN ('queued', 'running')
                ORDER BY created_at DESC
                LIMIT 200
                """,
                params,
            ).fetchall()
            rows_by_id.update({str(row["id"]): row for row in active_rows})
        jobs = [self._job_summary_row(row) for row in rows_by_id.values()]
        jobs.sort(key=lambda job: str(job.get("created_at") or ""), reverse=True)
        return jobs

    def claim_next_job(
        self,
        *,
        worker_id: str,
        lease_seconds: float = 900,
        allowed_job_types: Collection[str] | None = None,
    ) -> dict[str, Any] | None:
        return claim_next_job_transaction(
            self.store,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            allowed_job_types=allowed_job_types,
        )

    def complete_job(
        self,
        job_id: str,
        *,
        status: str,
        result: dict[str, Any] | None = None,
        error_code: str | None = None,
        error_message: str | None = None,
        worker_id: str,
        claim_token: str,
        commit: bool = True,
    ) -> dict[str, Any]:
        if status not in JOB_STATUSES - {"queued", "running"}:
            raise ValueError("completion status must be succeeded, failed, or partial")
        now = _now_iso()
        guard_sql, guard_params = self._claim_guard(worker_id, claim_token)
        conn = self.store.connect()
        current = conn.execute(
            f"""
            UPDATE fetch_jobs
            SET status = ?,
                result_json = ?,
                error_code = ?,
                error_message = ?,
                worker_id = NULL,
                claim_token = NULL,
                locked_until = NULL,
                finished_at = ?,
                updated_at = ?
            WHERE id = ?
              AND status = 'running'
              AND {guard_sql}
              AND locked_until IS NOT NULL
              AND locked_until >= ?
            """,
            (
                status,
                _json_dumps(result) if result is not None else None,
                error_code,
                error_message,
                now,
                now,
                job_id,
                *guard_params,
                now,
            ),
        )
        if current.rowcount != 1:
            conn.rollback()
            self._raise_claim_conflict(job_id)
        row = conn.execute(
            "SELECT * FROM fetch_jobs WHERE id = ?",
            (job_id,),
        ).fetchone()
        job = self.store._job(row)
        if job is None:
            if conn.in_transaction:
                conn.rollback()
            raise LookupError("job not found")
        if commit:
            conn.commit()
        return job

    def fail_or_retry_job(
        self,
        job_id: str,
        *,
        error_code: str,
        error_message: str,
        retryable: bool = True,
        retry_base_seconds: float = 30,
        result: dict[str, Any] | None = None,
        worker_id: str,
        claim_token: str,
        commit: bool = True,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        guard_sql, guard_params = self._claim_guard(worker_id, claim_token)
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        try:
            if not conn.in_transaction:
                conn.execute("BEGIN IMMEDIATE")
            current_row = conn.execute(
                f"""
                SELECT * FROM fetch_jobs
                WHERE id = ?
                  AND status = 'running'
                  AND {guard_sql}
                  AND locked_until IS NOT NULL
                  AND locked_until >= ?
                """,
                (job_id, *guard_params, now),
            ).fetchone()
            if current_row is None:
                conn.rollback()
                self._raise_claim_conflict(job_id)
            current = self.store._job(current_row)
            attempts = int(current.get("attempts") or 0)
            max_attempts = int(current.get("max_attempts") or 1)
            should_retry = retryable and attempts < max_attempts
            if should_retry:
                delay = max(float(retry_base_seconds), 0) * (2 ** max(attempts - 1, 0))
                updated = conn.execute(
                    f"""
                    UPDATE fetch_jobs
                    SET status = 'queued',
                        worker_id = NULL,
                        claim_token = NULL,
                        locked_until = NULL,
                        next_run_at = ?,
                        error_code = ?,
                        error_message = ?,
                        result_json = COALESCE(?, result_json),
                        updated_at = ?
                    WHERE id = ?
                      AND status = 'running'
                      AND {guard_sql}
                      AND locked_until IS NOT NULL
                      AND locked_until >= ?
                    """,
                    (
                        (now_dt + timedelta(seconds=delay)).isoformat(),
                        error_code,
                        error_message,
                        _json_dumps(result) if result is not None else None,
                        now,
                        job_id,
                        *guard_params,
                        now,
                    ),
                )
            else:
                updated = conn.execute(
                    f"""
                    UPDATE fetch_jobs
                    SET status = 'failed',
                        worker_id = NULL,
                        claim_token = NULL,
                        locked_until = NULL,
                        error_code = ?,
                        error_message = ?,
                        result_json = COALESCE(?, result_json),
                        finished_at = ?,
                        updated_at = ?
                    WHERE id = ?
                      AND status = 'running'
                      AND {guard_sql}
                      AND locked_until IS NOT NULL
                      AND locked_until >= ?
                    """,
                    (
                        error_code,
                        error_message,
                        _json_dumps(result) if result is not None else None,
                        now,
                        now,
                        job_id,
                        *guard_params,
                        now,
                    ),
                )
            if updated.rowcount != 1:
                conn.rollback()
                self._raise_claim_conflict(job_id)
            if commit:
                conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        updated = self.get_job(job_id)
        if updated is None:
            raise LookupError("job not found after update")
        return updated

    def cancel_claimed_job(
        self,
        job_id: str,
        *,
        reason: str,
        worker_id: str,
        claim_token: str,
        error_code: str = "job_invalidated",
        commit: bool = True,
    ) -> dict[str, Any]:
        """Cancel the current running claim after a lifecycle invalidation."""
        guard_sql, guard_values = self._claim_guard(worker_id, claim_token)
        now = _now_iso()
        cur = self.store.connect().execute(
            f"""
            UPDATE fetch_jobs
            SET status = 'cancelled',
                result_json = ?,
                error_code = ?,
                error_message = NULL,
                worker_id = NULL,
                claim_token = NULL,
                locked_until = NULL,
                cancelled_at = COALESCE(cancelled_at, ?),
                finished_at = ?,
                updated_at = ?
            WHERE id = ? AND status = 'running' AND {guard_sql}
            """,
            (
                _json_dumps({"invalidation_reason": reason}),
                error_code,
                now,
                now,
                now,
                job_id,
                *guard_values,
            ),
        )
        if cur.rowcount != 1:
            if commit and self.store.connect().in_transaction:
                self.store.connect().rollback()
            self._raise_claim_conflict(job_id)
        if commit:
            self.store.connect().commit()
        updated = self.get_job(job_id)
        if updated is None:
            raise LookupError("job not found after invalidation")
        return updated

    def extend_job_lease(
        self,
        job_id: str,
        *,
        worker_id: str,
        claim_token: str,
        lease_seconds: float = 900,
    ) -> dict[str, Any]:
        if not worker_id or not claim_token:
            raise ValueError("worker_id and claim_token are required")
        now_dt = datetime.now(timezone.utc)
        now = now_dt.isoformat()
        locked_until = (now_dt + timedelta(seconds=max(float(lease_seconds), 1))).isoformat()
        current = self.store.connect().execute(
            """
            UPDATE fetch_jobs
            SET locked_until = CASE
                    WHEN locked_until IS NULL OR locked_until < ? THEN ?
                    ELSE locked_until
                END,
                updated_at = ?
            WHERE id = ?
              AND status = 'running'
              AND worker_id = ?
              AND claim_token = ?
              AND (locked_until IS NULL OR locked_until >= ?)
            """,
            (locked_until, locked_until, now, job_id, worker_id, claim_token, now),
        )
        self.store.connect().commit()
        if current.rowcount != 1:
            self._raise_claim_conflict(job_id)
        updated = self.get_job(job_id)
        if updated is None:
            raise LookupError("job not found after lease extension")
        return updated

    def recover_stale_running_jobs(
        self,
        now: datetime | None = None,
        *,
        allowed_job_types: Collection[str] | None = None,
    ) -> list[dict[str, Any]]:
        return recover_stale_running_jobs_transaction(
            self.store,
            now=now,
            allowed_job_types=allowed_job_types,
        )

    def requeue_stale_running_jobs(
        self,
        now: datetime | None = None,
        *,
        allowed_job_types: Collection[str] | None = None,
    ) -> int:
        """Compatibility count wrapper for the structured recovery API."""

        return len(
            self.recover_stale_running_jobs(
                now=now,
                allowed_job_types=allowed_job_types,
            )
        )

    def cancel_job(self, job_id: str, *, user_id: str | None = None) -> dict[str, Any]:
        return cancel_job_transaction(
            self.store,
            self.get_job,
            job_id,
            user_id=user_id,
        )

    def retry_job(
        self,
        job_id: str,
        *,
        user_id: str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        now = _now_iso()
        conn = self.store.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            current = self.store._job(
                conn.execute(
                    "SELECT * FROM fetch_jobs WHERE id = ?",
                    (job_id,),
                ).fetchone()
            )
            if current is None:
                raise LookupError("job not found")
            if user_id is not None and current["user_id"] != user_id:
                raise PermissionError("cannot retry another user's job")
            if current["status"] not in {"failed", "partial", "cancelled"}:
                raise ValueError("only failed, partial, or cancelled jobs can be retried")

            if current["job_type"] == "user_feed_refresh":
                active_row = conn.execute(
                    """
                    SELECT * FROM fetch_jobs
                    WHERE workspace_id = ?
                      AND user_id = ?
                      AND job_type = 'user_feed_refresh'
                      AND status IN ('queued', 'running')
                      AND id != ?
                    ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
                    LIMIT 1
                    """,
                    (current["workspace_id"], current["user_id"], job_id),
                ).fetchone()
                if active_row is not None:
                    active = self.store._job(active_row)
                    if owns_transaction:
                        conn.commit()
                    if active is None:
                        raise LookupError("active user feed refresh could not be loaded")
                    return active

            if current["job_type"] == "source_fetch" and current.get(
                "subscription_id"
            ):
                active_row = conn.execute(
                    """
                    SELECT * FROM fetch_jobs
                    WHERE workspace_id = ?
                      AND user_id = ?
                      AND source_id = ?
                      AND subscription_id = ?
                      AND job_type = 'source_fetch'
                      AND status IN ('queued', 'running')
                      AND id != ?
                    ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
                    LIMIT 1
                    """,
                    (
                        current["workspace_id"],
                        current["user_id"],
                        current["source_id"],
                        current["subscription_id"],
                        job_id,
                    ),
                ).fetchone()
                if active_row is not None:
                    active = self.store._job(active_row)
                    if owns_transaction:
                        conn.commit()
                    if active is None:
                        raise LookupError("active source fetch could not be loaded")
                    return active

            updated_row = conn.execute(
                """
                UPDATE fetch_jobs
                SET status = 'queued',
                    attempts = 0,
                    worker_id = NULL,
                    claim_token = NULL,
                    locked_until = NULL,
                    next_run_at = ?,
                    cancelled_at = NULL,
                    finished_at = NULL,
                    error_code = NULL,
                    error_message = NULL,
                    result_json = NULL,
                    started_at = NULL,
                    updated_at = ?
                WHERE id = ?
                  AND status IN ('failed', 'partial', 'cancelled')
                """,
                (now, now, job_id),
            )
            if updated_row.rowcount != 1:
                raise ValueError("only failed, partial, or cancelled jobs can be retried")
            conn.execute(
                "DELETE FROM user_source_health_applications WHERE job_id = ?",
                (job_id,),
            )
            conn.execute(
                """
                UPDATE user_source_health
                SET last_job_id = NULL
                WHERE last_job_id = ?
                """,
                (job_id,),
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
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
