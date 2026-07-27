"""Per-user automatic Service Feed refresh scheduling."""

from __future__ import annotations

import os
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.service_store import ServiceStore
from .job_queue import JobQueue
from .quota import QuotaExceeded, QuotaService


ALLOWED_INTERVALS = (60, 180, 360, 720, 1440)
DEFAULT_INTERVAL_MINUTES = 360
SCHEDULED_REFRESH_REASON = "scheduled_service_refresh"


class NoEnabledSubscriptionsError(ValueError):
    """Raised when automatic refresh is enabled without a usable source."""

    code = "no_enabled_subscriptions"


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


class FeedScheduleService:
    """Read, update, and atomically enqueue per-user Feed schedules."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        quota: QuotaService | None = None,
        max_attempts: int | None = None,
        retention_days: int | None = None,
    ) -> None:
        self.store = store
        self.queue = JobQueue(store)
        self.quota = quota or QuotaService(
            store,
            max_fetch_jobs_per_day=int(
                os.getenv("INFOHUB_MAX_FETCH_JOBS_PER_DAY", "100")
            ),
        )
        self.max_attempts = int(
            max_attempts
            if max_attempts is not None
            else os.getenv("HORIZON_JOB_MAX_ATTEMPTS", "3")
        )
        self.retention_days = int(
            retention_days
            if retention_days is not None
            else os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")
        )

    @staticmethod
    def _schedule(row: Any) -> dict[str, Any]:
        data = dict(row)
        data["enabled"] = bool(int(data.get("enabled") or 0))
        data["interval_minutes"] = int(
            data.get("interval_minutes") or DEFAULT_INTERVAL_MINUTES
        )
        return data

    def _user_in_workspace(self, *, workspace_id: str | None, user_id: str) -> dict[str, Any]:
        user = self.store.get_user(user_id)
        if user is None:
            raise LookupError("user not found")
        if workspace_id is not None and user["workspace_id"] != workspace_id:
            raise LookupError("user not found in workspace")
        return user

    def get_user_schedule(
        self,
        *,
        user_id: str,
        workspace_id: str | None = None,
    ) -> dict[str, Any]:
        user = self._user_in_workspace(workspace_id=workspace_id, user_id=user_id)
        row = self.store.connect().execute(
            """
            SELECT * FROM user_feed_schedules
            WHERE user_id = ? AND workspace_id = ?
            """,
            (user_id, user["workspace_id"]),
        ).fetchone()
        if row is not None:
            return self._schedule(row)
        return {
            "user_id": user_id,
            "workspace_id": user["workspace_id"],
            "enabled": False,
            "interval_minutes": DEFAULT_INTERVAL_MINUTES,
            "next_run_at": None,
            "last_evaluated_at": None,
            "last_enqueued_at": None,
            "last_job_id": None,
            "last_skip_reason": None,
            "created_at": None,
            "updated_at": None,
        }

    def has_enabled_subscriptions(self, *, workspace_id: str, user_id: str) -> bool:
        return bool(
            self.store.connect().execute(
                """
                SELECT 1
                FROM user_subscriptions us
                JOIN source_catalog sc ON sc.id = us.source_id
                WHERE us.user_id = ?
                  AND sc.workspace_id = ?
                  AND us.enabled = 1
                  AND sc.enabled = 1
                LIMIT 1
                """,
                (user_id, workspace_id),
            ).fetchone()
        )

    def update_user_schedule(
        self,
        *,
        user_id: str,
        workspace_id: str | None = None,
        enabled: bool | None = None,
        interval_minutes: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if interval_minutes is not None and int(interval_minutes) not in ALLOWED_INTERVALS:
            raise ValueError(
                "interval_minutes must be one of "
                + ", ".join(str(value) for value in ALLOWED_INTERVALS)
            )
        user = self._user_in_workspace(workspace_id=workspace_id, user_id=user_id)
        workspace_id = str(user["workspace_id"])
        now_dt = _utc(now)
        now_iso = now_dt.isoformat()
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                "SELECT * FROM user_feed_schedules WHERE user_id = ?",
                (user_id,),
            ).fetchone()
            current = self._schedule(row) if row is not None else None
            current_enabled = bool(current and current["enabled"])
            target_enabled = current_enabled if enabled is None else bool(enabled)
            target_interval = int(
                interval_minutes
                if interval_minutes is not None
                else (current or {}).get("interval_minutes", DEFAULT_INTERVAL_MINUTES)
            )
            if target_enabled and not current_enabled and not self.has_enabled_subscriptions(
                workspace_id=workspace_id,
                user_id=user_id,
            ):
                raise NoEnabledSubscriptionsError(
                    "automatic feed refresh requires an enabled subscription"
                )

            if not target_enabled:
                next_run_at = None
            elif not current_enabled:
                next_run_at = now_iso
            elif target_interval != int(current["interval_minutes"]):
                next_run_at = (now_dt + timedelta(minutes=target_interval)).isoformat()
            else:
                next_run_at = current.get("next_run_at") or now_iso

            if current is None:
                conn.execute(
                    """
                    INSERT INTO user_feed_schedules (
                        user_id, workspace_id, enabled, interval_minutes,
                        next_run_at, created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?, ?)
                    """,
                    (
                        user_id,
                        workspace_id,
                        1 if target_enabled else 0,
                        target_interval,
                        next_run_at,
                        now_iso,
                        now_iso,
                    ),
                )
            else:
                conn.execute(
                    """
                    UPDATE user_feed_schedules
                    SET enabled = ?, interval_minutes = ?, next_run_at = ?, updated_at = ?
                    WHERE user_id = ? AND workspace_id = ?
                    """,
                    (
                        1 if target_enabled else 0,
                        target_interval,
                        next_run_at,
                        now_iso,
                        user_id,
                        workspace_id,
                    ),
                )

            if not target_enabled:
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
                    WHERE workspace_id = ?
                      AND user_id = ?
                      AND job_type = 'user_feed_refresh'
                      AND status = 'queued'
                      AND json_extract(payload_json, '$.reason') = ?
                    """,
                    (
                        now_iso,
                        now_iso,
                        now_iso,
                        workspace_id,
                        user_id,
                        SCHEDULED_REFRESH_REASON,
                    ),
                )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return self.get_user_schedule(workspace_id=workspace_id, user_id=user_id)

    def enqueue_due(
        self,
        now: datetime | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
        """Evaluate due plans and atomically enqueue at most one refresh per plan."""
        result: dict[str, Any] = {
            "evaluated": 0,
            "enqueued": 0,
            "deduplicated": 0,
            "skipped": 0,
            "outcomes": [],
        }
        limit = max(int(limit), 0)
        if limit == 0:
            return result
        now_dt = _utc(now)
        now_iso = now_dt.isoformat()
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT *
                FROM user_feed_schedules
                WHERE enabled = 1
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= ?
                ORDER BY next_run_at, user_id
                LIMIT ?
                """,
                (now_iso, limit),
            ).fetchall()
            migration_required = (
                self.store.feed_v2_migration_required()
                or self.store.content_index_v4_migration_required()
                or self.store.content_timeline_v11_migration_required()
            )
            for raw_row in rows:
                schedule = self._schedule(raw_row)
                result["evaluated"] += 1
                interval_next = now_dt + timedelta(minutes=schedule["interval_minutes"])
                if migration_required:
                    self._record_skip(
                        schedule,
                        now=now_dt,
                        next_run_at=now_dt + timedelta(minutes=5),
                        reason="migration_required",
                    )
                    self._append_skip(result, schedule, "migration_required")
                    continue

                user = self.store.get_user(str(schedule["user_id"]))
                if user is None or not user["enabled"]:
                    self._record_skip(
                        schedule,
                        now=now_dt,
                        next_run_at=interval_next,
                        reason="user_disabled",
                    )
                    self._append_skip(result, schedule, "user_disabled")
                    continue
                if user.get("role") == "viewer":
                    self._disable_read_only_schedule(schedule, now=now_dt)
                    self._append_skip(result, schedule, "user_read_only")
                    continue
                if not self.has_enabled_subscriptions(
                    workspace_id=str(schedule["workspace_id"]),
                    user_id=str(schedule["user_id"]),
                ):
                    self._record_skip(
                        schedule,
                        now=now_dt,
                        next_run_at=interval_next,
                        reason="no_enabled_subscriptions",
                    )
                    self._append_skip(result, schedule, "no_enabled_subscriptions")
                    continue

                active_refresh = conn.execute(
                    """
                    SELECT * FROM fetch_jobs
                    WHERE workspace_id = ?
                      AND user_id = ?
                      AND job_type = 'user_feed_refresh'
                      AND status IN ('queued', 'running')
                    ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
                    LIMIT 1
                    """,
                    (schedule["workspace_id"], schedule["user_id"]),
                ).fetchone()
                if active_refresh is not None:
                    active_job = self.store._job(active_refresh)
                    self._record_skip(
                        schedule,
                        now=now_dt,
                        next_run_at=interval_next,
                        reason="active_user_feed_refresh",
                        last_job_id=active_job["id"],
                    )
                    result["deduplicated"] += 1
                    result["outcomes"].append(
                        {
                            "user_id": schedule["user_id"],
                            "action": "deduplicated",
                            "reason": "active_user_feed_refresh",
                            "job_id": active_job["id"],
                        }
                    )
                    continue

                active_source_fetch = conn.execute(
                    """
                    SELECT 1 FROM fetch_jobs
                    WHERE workspace_id = ?
                      AND user_id = ?
                      AND job_type = 'source_fetch'
                      AND status IN ('queued', 'running')
                    LIMIT 1
                    """,
                    (schedule["workspace_id"], schedule["user_id"]),
                ).fetchone()
                if active_source_fetch is not None:
                    self._record_skip(
                        schedule,
                        now=now_dt,
                        next_run_at=now_dt + timedelta(minutes=5),
                        reason="active_source_fetch",
                    )
                    self._append_skip(result, schedule, "active_source_fetch")
                    continue

                try:
                    self.quota.ensure_job_allowed(
                        workspace_id=str(schedule["workspace_id"]),
                        user_id=str(schedule["user_id"]),
                        now=now_dt,
                    )
                except QuotaExceeded:
                    self.quota.record_quota_reject(
                        workspace_id=str(schedule["workspace_id"]),
                        user_id=str(schedule["user_id"]),
                        quota="fetch_job",
                        commit=False,
                    )
                    self._record_skip(
                        schedule,
                        now=now_dt,
                        next_run_at=interval_next,
                        reason="quota_exceeded",
                    )
                    self._append_skip(result, schedule, "quota_exceeded")
                    continue

                job, created = self.queue.create_user_feed_refresh_if_absent(
                    workspace_id=str(schedule["workspace_id"]),
                    user_id=str(schedule["user_id"]),
                    payload={"reason": SCHEDULED_REFRESH_REASON},
                    priority=-10,
                    max_attempts=self.max_attempts,
                    retention_days=self.retention_days,
                )
                if not created:
                    self._record_skip(
                        schedule,
                        now=now_dt,
                        next_run_at=interval_next,
                        reason="active_user_feed_refresh",
                        last_job_id=job["id"],
                    )
                    result["deduplicated"] += 1
                    result["outcomes"].append(
                        {
                            "user_id": schedule["user_id"],
                            "action": "deduplicated",
                            "reason": "active_user_feed_refresh",
                            "job_id": job["id"],
                        }
                    )
                    continue

                self.quota.record_job_usage(
                    workspace_id=str(schedule["workspace_id"]),
                    user_id=str(schedule["user_id"]),
                    event_type="user_feed_refresh",
                    commit=False,
                )
                conn.execute(
                    """
                    UPDATE user_feed_schedules
                    SET next_run_at = ?,
                        last_evaluated_at = ?,
                        last_enqueued_at = ?,
                        last_job_id = ?,
                        last_skip_reason = NULL,
                        updated_at = ?
                    WHERE user_id = ? AND enabled = 1
                    """,
                    (
                        interval_next.isoformat(),
                        now_iso,
                        now_iso,
                        job["id"],
                        now_iso,
                        schedule["user_id"],
                    ),
                )
                result["enqueued"] += 1
                result["outcomes"].append(
                    {
                        "user_id": schedule["user_id"],
                        "action": "enqueued",
                        "reason": SCHEDULED_REFRESH_REASON,
                        "job_id": job["id"],
                    }
                )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return result

    def _disable_read_only_schedule(
        self,
        schedule: dict[str, Any],
        *,
        now: datetime,
    ) -> None:
        now_iso = now.isoformat()
        conn = self.store.connect()
        conn.execute(
            """
            UPDATE user_feed_schedules
            SET enabled = 0,
                next_run_at = NULL,
                last_evaluated_at = ?,
                last_skip_reason = 'user_read_only',
                updated_at = ?
            WHERE user_id = ? AND enabled = 1
            """,
            (now_iso, now_iso, schedule["user_id"]),
        )
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
            WHERE workspace_id = ?
              AND user_id = ?
              AND job_type = 'user_feed_refresh'
              AND status = 'queued'
              AND json_extract(payload_json, '$.reason') = ?
            """,
            (
                now_iso,
                now_iso,
                now_iso,
                schedule["workspace_id"],
                schedule["user_id"],
                SCHEDULED_REFRESH_REASON,
            ),
        )

    def _record_skip(
        self,
        schedule: dict[str, Any],
        *,
        now: datetime,
        next_run_at: datetime,
        reason: str,
        last_job_id: str | None = None,
    ) -> None:
        self.store.connect().execute(
            """
            UPDATE user_feed_schedules
            SET next_run_at = ?,
                last_evaluated_at = ?,
                last_job_id = COALESCE(?, last_job_id),
                last_skip_reason = ?,
                updated_at = ?
            WHERE user_id = ? AND enabled = 1
            """,
            (
                next_run_at.isoformat(),
                now.isoformat(),
                last_job_id,
                reason,
                now.isoformat(),
                schedule["user_id"],
            ),
        )

    @staticmethod
    def _append_skip(result: dict[str, Any], schedule: dict[str, Any], reason: str) -> None:
        result["skipped"] += 1
        result["outcomes"].append(
            {
                "user_id": schedule["user_id"],
                "action": "skipped",
                "reason": reason,
                "job_id": None,
            }
        )
