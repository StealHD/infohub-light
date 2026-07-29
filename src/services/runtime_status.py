"""Runtime worker heartbeat freshness projection."""

from __future__ import annotations

import json
import re
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.service_store import ServiceStore


WORKER_STALE_AFTER_SECONDS = 35
SOURCE_HEALTH_FAILURE_WINDOW_HOURS = 24
_SAFE_SOURCE_FAILURE_CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}\Z")
_SECRET_SHAPED_CODE_RE = re.compile(
    r"(?:sk[-_]|gh[pousr]_|xox[a-z]-|AIza|xai-|gsk_|hf_|tp-)",
    re.IGNORECASE,
)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _public_source_failure_code(value: Any) -> str:
    code = str(value or "").strip()
    if (
        not _SAFE_SOURCE_FAILURE_CODE_RE.fullmatch(code)
        or _SECRET_SHAPED_CODE_RE.search(code)
    ):
        return "Other"
    return code


class RuntimeStatusService:
    """Add a fixed freshness interpretation to persisted worker heartbeats."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    def get_worker(
        self,
        worker_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any] | None:
        heartbeat = self.store.get_worker_heartbeat(worker_id)
        return self._with_freshness(heartbeat, now=now) if heartbeat else None

    def list_workers(self, *, now: datetime | None = None) -> list[dict[str, Any]]:
        return [
            self._with_freshness(heartbeat, now=now)
            for heartbeat in self.store.list_worker_heartbeats()
        ]

    @staticmethod
    def _availability_from_workers(
        workers: list[dict[str, Any]],
        *,
        checked_at: datetime,
    ) -> dict[str, Any]:
        available = [
            worker
            for worker in workers
            if not worker["is_stale"] and worker["state"] != "stopping"
        ]
        return {
            "worker_status": (
                "ready" if available else ("stale" if workers else "missing")
            ),
            "checked_at": checked_at.isoformat(),
        }

    def availability(
        self,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return worker availability without scanning jobs or schedule state."""
        checked_at = _utc(now or datetime.now(timezone.utc))
        workers = self.list_workers(now=checked_at)
        return self._availability_from_workers(workers, checked_at=checked_at)

    def summary(
        self,
        *,
        workspace_id: str | None = None,
        user_id: str | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        checked_at = _utc(now or datetime.now(timezone.utc))
        workers = self.list_workers(now=checked_at)
        availability = self._availability_from_workers(
            workers,
            checked_at=checked_at,
        )
        where: list[str] = []
        params: list[Any] = []
        if workspace_id:
            where.append("workspace_id = ?")
            params.append(workspace_id)
        if user_id:
            where.append("user_id = ?")
            params.append(user_id)
        clause = f"WHERE {' AND '.join(where)}" if where else ""
        rows = self.store.connect().execute(
            f"SELECT status, COUNT(*) AS count FROM fetch_jobs {clause} GROUP BY status",
            params,
        ).fetchall()
        job_counts = {
            status: 0
            for status in ("queued", "running", "succeeded", "failed", "partial", "cancelled")
        }
        job_counts.update({str(row["status"]): int(row["count"]) for row in rows})
        operational_counts = {
            "acquisition_cache_hits": 0,
            "acquisition_cache_misses": 0,
            "acquisition_upstream_attempts": 0,
            "acquisition_waits": 0,
            "invalidated_jobs": 0,
            "quota_rejects": 0,
        }
        operational_rows = self.store.connect().execute(
            f"SELECT error_code, result_json FROM fetch_jobs {clause}",
            params,
        ).fetchall()
        acquisition_fields = {
            "cache_hits": "acquisition_cache_hits",
            "cache_misses": "acquisition_cache_misses",
            "upstream_attempts": "acquisition_upstream_attempts",
            "waits": "acquisition_waits",
        }
        for row in operational_rows:
            if row["error_code"] == "job_invalidated":
                operational_counts["invalidated_jobs"] += 1
            try:
                result = json.loads(str(row["result_json"] or "{}"))
            except (TypeError, ValueError, json.JSONDecodeError):
                continue
            usage = result.get("acquisition_usage") if isinstance(result, dict) else None
            if not isinstance(usage, dict):
                continue
            for source_key, public_key in acquisition_fields.items():
                value = usage.get(source_key, 0)
                if isinstance(value, bool):
                    continue
                try:
                    operational_counts[public_key] += max(int(value), 0)
                except (TypeError, ValueError):
                    continue
        usage_rows = self.store.connect().execute(
            f"""
            SELECT COALESCE(SUM(quantity), 0) AS count
            FROM usage_events
            {clause + (' AND' if clause else ' WHERE')} event_type = 'quota_reject'
            """,
            params,
        ).fetchone()
        operational_counts["quota_rejects"] = int(
            usage_rows["count"] if usage_rows else 0
        )
        queued_row = self.store.connect().execute(
            f"SELECT MIN(created_at) AS oldest FROM fetch_jobs {clause + (' AND' if clause else ' WHERE')} status = 'queued'",
            params,
        ).fetchone()
        oldest_at = datetime.fromisoformat(queued_row["oldest"]) if queued_row and queued_row["oldest"] else None
        oldest_age = max((checked_at - _utc(oldest_at)).total_seconds(), 0.0) if oldest_at else None
        stale_running = self.store.connect().execute(
            f"SELECT COUNT(*) AS count FROM fetch_jobs {clause + (' AND' if clause else ' WHERE')} status = 'running' AND locked_until < ?",
            [*params, checked_at.isoformat()],
        ).fetchone()
        snapshot_where = []
        snapshot_params: list[Any] = []
        if workspace_id:
            snapshot_where.append("workspace_id = ?")
            snapshot_params.append(workspace_id)
        if user_id:
            snapshot_where.append("user_id = ?")
            snapshot_params.append(user_id)
        snapshot_clause = f"WHERE {' AND '.join(snapshot_where)}" if snapshot_where else ""
        snapshot_row = self.store.connect().execute(
            f"SELECT MAX(generated_at) AS latest FROM user_feed_snapshots {snapshot_clause}",
            snapshot_params,
        ).fetchone()
        latest_at = datetime.fromisoformat(snapshot_row["latest"]) if snapshot_row and snapshot_row["latest"] else None
        latest_age = max((checked_at - _utc(latest_at)).total_seconds(), 0.0) if latest_at else None
        schedule_row = self.store.connect().execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END), 0) AS enabled_count,
                COALESCE(SUM(
                    CASE
                        WHEN enabled = 1
                         AND next_run_at IS NOT NULL
                         AND next_run_at <= ?
                        THEN 1 ELSE 0
                    END
                ), 0) AS overdue_count,
                MIN(CASE WHEN enabled = 1 THEN next_run_at END) AS next_scheduled_at,
                MAX(last_evaluated_at) AS last_evaluated_at,
                MAX(last_enqueued_at) AS last_enqueued_at
            FROM user_feed_schedules
            {clause}
            """,
            [checked_at.isoformat(), *params],
        ).fetchone()
        skip_clause = clause + (" AND" if clause else " WHERE")
        skip_rows = self.store.connect().execute(
            f"""
            SELECT last_skip_reason, COUNT(*) AS count
            FROM user_feed_schedules
            {skip_clause} last_skip_reason IS NOT NULL
            GROUP BY last_skip_reason
            ORDER BY last_skip_reason
            """,
            params,
        ).fetchall()
        source_schedule_row = self.store.connect().execute(
            f"""
            SELECT
                COALESCE(SUM(CASE WHEN enabled = 1 THEN 1 ELSE 0 END), 0) AS enabled_count,
                COALESCE(SUM(
                    CASE
                        WHEN enabled = 1
                         AND next_run_at IS NOT NULL
                         AND next_run_at <= ?
                        THEN 1 ELSE 0
                    END
                ), 0) AS overdue_count,
                MIN(CASE WHEN enabled = 1 THEN next_run_at END) AS next_scheduled_at
            FROM user_source_schedules
            {clause}
            """,
            [checked_at.isoformat(), *params],
        ).fetchone()
        source_health_where: list[str] = []
        source_health_params: list[Any] = []
        if workspace_id:
            source_health_where.append("users.workspace_id = ?")
            source_health_params.append(workspace_id)
        if user_id:
            source_health_where.append("subscriptions.user_id = ?")
            source_health_params.append(user_id)
        source_health_clause = (
            f"WHERE {' AND '.join(source_health_where)}"
            if source_health_where
            else ""
        )
        source_health_rows = self.store.connect().execute(
            f"""
            SELECT COALESCE(health.status, 'unknown') AS status, COUNT(*) AS count
            FROM user_subscriptions AS subscriptions
            JOIN users
              ON users.id = subscriptions.user_id
            JOIN source_catalog AS sources
              ON sources.id = subscriptions.source_id
             AND sources.workspace_id = users.workspace_id
            LEFT JOIN user_source_health AS health
              ON health.subscription_id = subscriptions.id
             AND health.workspace_id = users.workspace_id
             AND health.user_id = subscriptions.user_id
             AND health.source_id = subscriptions.source_id
            {source_health_clause}
            GROUP BY COALESCE(health.status, 'unknown')
            """,
            source_health_params,
        ).fetchall()
        source_health_counts = {
            "total": 0,
            "unknown": 0,
            "healthy": 0,
            "degraded": 0,
            "failing": 0,
        }
        for row in source_health_rows:
            status = str(row["status"])
            count = int(row["count"])
            source_health_counts[status] = count
            source_health_counts["total"] += count

        failure_from = checked_at - timedelta(
            hours=SOURCE_HEALTH_FAILURE_WINDOW_HOURS
        )
        failure_where = [*source_health_where]
        failure_where.append("TRIM(COALESCE(health.last_issue_code, '')) <> ''")
        failure_rows = self.store.connect().execute(
            f"""
            SELECT
                TRIM(health.last_issue_code) AS code,
                health.last_failure_at
            FROM user_source_health AS health
            JOIN user_subscriptions AS subscriptions
              ON subscriptions.id = health.subscription_id
             AND subscriptions.user_id = health.user_id
             AND subscriptions.source_id = health.source_id
            JOIN users
              ON users.id = subscriptions.user_id
             AND users.workspace_id = health.workspace_id
            JOIN source_catalog AS sources
              ON sources.id = subscriptions.source_id
             AND sources.workspace_id = users.workspace_id
            WHERE {' AND '.join(failure_where)}
            ORDER BY TRIM(health.last_issue_code), health.last_failure_at
            """,
            source_health_params,
        ).fetchall()
        recent_source_failure_code_counts: dict[str, int] = {}
        for row in failure_rows:
            try:
                failed_at = _utc(datetime.fromisoformat(str(row["last_failure_at"])))
            except (TypeError, ValueError):
                continue
            if failure_from <= failed_at <= checked_at:
                code = _public_source_failure_code(row["code"])
                recent_source_failure_code_counts[code] = (
                    recent_source_failure_code_counts.get(code, 0) + 1
                )
        return {
            "worker_status": availability["worker_status"],
            "workers": workers,
            "job_counts": job_counts,
            "operational_counts": operational_counts,
            "oldest_queued_age_seconds": oldest_age,
            "stale_running_count": int(stale_running["count"] if stale_running else 0),
            "latest_snapshot_age_seconds": latest_age,
            "enabled_schedule_count": int(schedule_row["enabled_count"] if schedule_row else 0),
            "overdue_schedule_count": int(schedule_row["overdue_count"] if schedule_row else 0),
            "next_scheduled_at": schedule_row["next_scheduled_at"] if schedule_row else None,
            "schedule_stats": {
                "last_evaluated_at": schedule_row["last_evaluated_at"] if schedule_row else None,
                "last_enqueued_at": schedule_row["last_enqueued_at"] if schedule_row else None,
                "last_skip_reasons": {
                    str(row["last_skip_reason"]): int(row["count"])
                    for row in skip_rows
                },
            },
            "source_schedule_count": int(
                source_schedule_row["enabled_count"] if source_schedule_row else 0
            ),
            "overdue_source_schedule_count": int(
                source_schedule_row["overdue_count"] if source_schedule_row else 0
            ),
            "next_source_scheduled_at": (
                source_schedule_row["next_scheduled_at"]
                if source_schedule_row
                else None
            ),
            "source_health_counts": source_health_counts,
            "recent_source_failure_code_counts": recent_source_failure_code_counts,
            "source_health_failure_window_hours": SOURCE_HEALTH_FAILURE_WINDOW_HOURS,
            "checked_at": checked_at.isoformat(),
        }

    @staticmethod
    def _with_freshness(
        heartbeat: dict[str, Any],
        *,
        now: datetime | None,
    ) -> dict[str, Any]:
        heartbeat_at = _utc(datetime.fromisoformat(str(heartbeat["heartbeat_at"])))
        checked_at = _utc(now or datetime.now(timezone.utc))
        stale_at = heartbeat_at + timedelta(seconds=WORKER_STALE_AFTER_SECONDS)
        return {
            **heartbeat,
            "stale_after_seconds": WORKER_STALE_AFTER_SECONDS,
            "stale_at": stale_at.isoformat(),
            "is_stale": checked_at > stale_at,
        }
