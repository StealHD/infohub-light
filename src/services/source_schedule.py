"""Per-subscription automatic source fetch scheduling."""

from __future__ import annotations

import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.service_store import ServiceStore
from .apify_actor_monitoring import build_apify_actor_route
from .apify_actor_ops import ApifyActorOpsService
from .apify_key_pool import ApifyKeyPoolService, apify_key_pool_enabled
from .job_queue import JobQueue
from .quota import QuotaExceeded, QuotaService


SOURCE_ALLOWED_INTERVALS = (30, 60, 180, 360, 720, 1440)
DEFAULT_SOURCE_INTERVAL_MINUTES = 60
SCHEDULED_SOURCE_FETCH_REASON = "scheduled_source_fetch"


class SourceScheduleUnavailableError(ValueError):
    code = "source_schedule_unavailable"


def _utc(value: datetime | None = None) -> datetime:
    value = value or datetime.now(timezone.utc)
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        return _utc(datetime.fromisoformat(str(value).replace("Z", "+00:00")))
    except (TypeError, ValueError):
        return None


class SourceScheduleService:
    """Read, update, and atomically enqueue subscription fetch schedules."""

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
            data.get("interval_minutes") or DEFAULT_SOURCE_INTERVAL_MINUTES
        )
        return data

    def _subscription_row(
        self,
        *,
        workspace_id: str,
        user_id: str,
        subscription_id: str,
    ) -> Any:
        row = self.store.connect().execute(
            """
            SELECT
                us.id AS subscription_id,
                us.user_id,
                us.source_id,
                us.enabled AS subscription_enabled,
                sc.workspace_id,
                sc.type AS source_type,
                sc.config_json AS source_config_json,
                sc.enabled AS source_enabled,
                u.enabled AS user_enabled,
                u.role AS user_role
            FROM user_subscriptions us
            JOIN source_catalog sc ON sc.id = us.source_id
            JOIN users u ON u.id = us.user_id
            WHERE us.id = ? AND us.user_id = ? AND sc.workspace_id = ?
            """,
            (subscription_id, user_id, workspace_id),
        ).fetchone()
        if row is None:
            raise LookupError("subscription not found")
        return row

    def get_subscription_schedule(
        self,
        *,
        workspace_id: str,
        user_id: str,
        subscription_id: str,
    ) -> dict[str, Any]:
        subscription = self._subscription_row(
            workspace_id=workspace_id,
            user_id=user_id,
            subscription_id=subscription_id,
        )
        row = self.store.get_source_schedule(subscription_id)
        if row is not None:
            return self._schedule(row)
        return {
            "subscription_id": subscription_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "source_id": subscription["source_id"],
            "enabled": False,
            "interval_minutes": DEFAULT_SOURCE_INTERVAL_MINUTES,
            "next_run_at": None,
            "last_evaluated_at": None,
            "last_enqueued_at": None,
            "last_job_id": None,
            "last_skip_reason": None,
            "created_at": None,
            "updated_at": None,
        }

    def list_user_subscription_schedules(
        self,
        *,
        workspace_id: str,
        user_id: str,
        subscriptions: list[dict[str, Any]],
    ) -> dict[str, dict[str, Any]]:
        """Load all persisted schedules once and fill defaults in memory."""
        rows = self.store.connect().execute(
            """
            SELECT *
            FROM user_source_schedules
            WHERE workspace_id = ? AND user_id = ?
            """,
            (workspace_id, user_id),
        ).fetchall()
        rows_by_subscription_id = {
            str(row["subscription_id"]): row for row in rows
        }
        schedules: dict[str, dict[str, Any]] = {}
        for subscription in subscriptions:
            subscription_id = str(subscription["id"])
            source_id = str(subscription["source_id"])
            row = rows_by_subscription_id.get(subscription_id)
            if row is not None and str(row["source_id"]) == source_id:
                schedules[subscription_id] = self._schedule(row)
                continue
            schedules[subscription_id] = {
                "subscription_id": subscription_id,
                "workspace_id": workspace_id,
                "user_id": user_id,
                "source_id": source_id,
                "enabled": False,
                "interval_minutes": DEFAULT_SOURCE_INTERVAL_MINUTES,
                "next_run_at": None,
                "last_evaluated_at": None,
                "last_enqueued_at": None,
                "last_job_id": None,
                "last_skip_reason": None,
                "created_at": None,
                "updated_at": None,
            }
        return schedules

    def update_subscription_schedule(
        self,
        *,
        workspace_id: str,
        user_id: str,
        subscription_id: str,
        enabled: bool | None = None,
        interval_minutes: int | None = None,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        if (
            interval_minutes is not None
            and int(interval_minutes) not in SOURCE_ALLOWED_INTERVALS
        ):
            raise ValueError(
                "interval_minutes must be one of "
                + ", ".join(str(value) for value in SOURCE_ALLOWED_INTERVALS)
            )
        now_dt = _utc(now)
        now_iso = now_dt.isoformat()
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            subscription = self._subscription_row(
                workspace_id=workspace_id,
                user_id=user_id,
                subscription_id=subscription_id,
            )
            raw_current = conn.execute(
                "SELECT * FROM user_source_schedules WHERE subscription_id = ?",
                (subscription_id,),
            ).fetchone()
            current = self._schedule(raw_current) if raw_current is not None else None
            current_enabled = bool(current and current["enabled"])
            target_enabled = current_enabled if enabled is None else bool(enabled)
            target_interval = int(
                interval_minutes
                if interval_minutes is not None
                else (current or {}).get(
                    "interval_minutes", DEFAULT_SOURCE_INTERVAL_MINUTES
                )
            )
            if target_enabled and not (
                bool(subscription["subscription_enabled"])
                and bool(subscription["source_enabled"])
                and bool(subscription["user_enabled"])
            ):
                raise SourceScheduleUnavailableError(
                    "automatic source fetch requires an enabled subscription"
                )

            if not target_enabled:
                next_run_at = None
            elif not current_enabled:
                next_run_at = now_iso
            elif target_interval != int(current["interval_minutes"]):
                next_run_at = (
                    now_dt + timedelta(minutes=target_interval)
                ).isoformat()
            else:
                next_run_at = current.get("next_run_at") or now_iso

            conn.execute(
                """
                INSERT INTO user_source_schedules (
                    subscription_id, workspace_id, user_id, source_id,
                    enabled, interval_minutes, next_run_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(subscription_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    interval_minutes = excluded.interval_minutes,
                    next_run_at = excluded.next_run_at,
                    updated_at = excluded.updated_at
                """,
                (
                    subscription_id,
                    workspace_id,
                    user_id,
                    subscription["source_id"],
                    1 if target_enabled else 0,
                    target_interval,
                    next_run_at,
                    now_iso,
                    now_iso,
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
                      AND subscription_id = ?
                      AND job_type = 'source_fetch'
                      AND status = 'queued'
                      AND json_extract(payload_json, '$.reason') = ?
                    """,
                    (
                        now_iso,
                        now_iso,
                        now_iso,
                        workspace_id,
                        user_id,
                        subscription_id,
                        SCHEDULED_SOURCE_FETCH_REASON,
                    ),
                )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return self.get_subscription_schedule(
            workspace_id=workspace_id,
            user_id=user_id,
            subscription_id=subscription_id,
        )

    def enqueue_due(
        self,
        now: datetime | None = None,
        limit: int = 100,
    ) -> dict[str, Any]:
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
        actor_routes: list[Any] = []
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT * FROM user_source_schedules
                WHERE enabled = 1
                  AND next_run_at IS NOT NULL
                  AND next_run_at <= ?
                ORDER BY next_run_at, subscription_id
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
                interval_next = now_dt + timedelta(
                    minutes=schedule["interval_minutes"]
                )
                reason = None
                try:
                    subscription = self._subscription_row(
                        workspace_id=str(schedule["workspace_id"]),
                        user_id=str(schedule["user_id"]),
                        subscription_id=str(schedule["subscription_id"]),
                    )
                except LookupError:
                    subscription = None
                    reason = "subscription_missing"
                if migration_required:
                    reason = "migration_required"
                elif subscription is not None and not bool(
                    subscription["user_enabled"]
                ):
                    reason = "user_disabled"
                elif subscription is not None and subscription["user_role"] == "viewer":
                    reason = "user_read_only"
                elif subscription is not None and not (
                    bool(subscription["subscription_enabled"])
                    and bool(subscription["source_enabled"])
                ):
                    reason = "subscription_disabled"
                elif (
                    subscription is not None
                    and subscription["source_type"] == "apify_social"
                ):
                    if apify_key_pool_enabled():
                        pool_gate = ApifyKeyPoolService(self.store).schedule_gate(
                            str(schedule["workspace_id"]),
                            now=now_dt,
                        )
                        if pool_gate["blocked"]:
                            reason = str(pool_gate["code"])
                            retry_at = _parse_time(pool_gate.get("retry_at"))
                            if retry_at is not None and retry_at > now_dt:
                                interval_next = retry_at
                    profile_id = self._actor_ops_profile_id(subscription)
                    if reason is None and profile_id is not None:
                        route_gate = ApifyActorOpsService(
                            self.store,
                            workspace_id=str(schedule["workspace_id"]),
                        ).schedule_gate(
                            profile_id,
                            source_id=str(subscription["source_id"]),
                        )
                        if not route_gate.allowed:
                            reason = str(
                                route_gate.error_code
                                or "apify_actor_route_candidate_shortfall"
                            )
                    elif (
                        reason is None
                        and apify_key_pool_enabled()
                        and self._is_x_profile_subscription(subscription)
                    ):
                        actor_route = build_apify_actor_route(
                            self.store,
                            data_dir=str(self.store.data_dir),
                            workspace_id=str(schedule["workspace_id"]),
                        )
                        actor_routes.append(actor_route)
                        actor_gate = actor_route.schedule_gate(
                            str(subscription["source_id"])
                        )
                        if not actor_gate.allowed:
                            reason = str(
                                actor_gate.error_code
                                or "apify_actor_route_exhausted"
                            )
                            if (
                                actor_gate.retry_at is not None
                                and actor_gate.retry_at > now_dt
                            ):
                                interval_next = actor_gate.retry_at

                if reason is not None:
                    self._record_skip(
                        schedule,
                        now=now_dt,
                        next_run_at=interval_next,
                        reason=reason,
                    )
                    result["skipped"] += 1
                    result["outcomes"].append(
                        {
                            "subscription_id": schedule["subscription_id"],
                            "action": "skipped",
                            "reason": reason,
                        }
                    )
                    continue

                active_refresh = conn.execute(
                    """
                    SELECT id, status FROM fetch_jobs
                    WHERE workspace_id = ? AND user_id = ?
                      AND job_type = 'user_feed_refresh'
                      AND status IN ('queued', 'running')
                    ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
                    LIMIT 1
                    """,
                    (schedule["workspace_id"], schedule["user_id"]),
                ).fetchone()
                if active_refresh is not None:
                    self._record_skip(
                        schedule,
                        now=now_dt,
                        next_run_at=now_dt + timedelta(minutes=5),
                        reason="active_user_feed_refresh",
                        last_job_id=active_refresh["id"],
                    )
                    result["deduplicated"] += 1
                    result["outcomes"].append(
                        {
                            "subscription_id": schedule["subscription_id"],
                            "action": "deduplicated",
                            "reason": "active_user_feed_refresh",
                            "job_id": active_refresh["id"],
                        }
                    )
                    continue

                active_source = conn.execute(
                    """
                    SELECT * FROM fetch_jobs
                    WHERE workspace_id = ?
                      AND user_id = ?
                      AND source_id = ?
                      AND subscription_id = ?
                      AND job_type = 'source_fetch'
                      AND status IN ('queued', 'running')
                    ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
                    LIMIT 1
                    """,
                    (
                        schedule["workspace_id"],
                        schedule["user_id"],
                        schedule["source_id"],
                        schedule["subscription_id"],
                    ),
                ).fetchone()
                if active_source is not None:
                    active_job = self.store._job(active_source)
                    if active_job is None:
                        raise LookupError("active source fetch could not be loaded")
                    conn.execute(
                        """
                        UPDATE user_source_schedules
                        SET next_run_at = ?, last_evaluated_at = ?,
                            last_job_id = ?, last_skip_reason = NULL, updated_at = ?
                        WHERE subscription_id = ?
                        """,
                        (
                            interval_next.isoformat(),
                            now_iso,
                            active_job["id"],
                            now_iso,
                            schedule["subscription_id"],
                        ),
                    )
                    result["deduplicated"] += 1
                    result["outcomes"].append(
                        {
                            "subscription_id": schedule["subscription_id"],
                            "action": "deduplicated",
                            "job_id": active_job["id"],
                        }
                    )
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
                    result["skipped"] += 1
                    continue

                job, created = self.queue.create_source_fetch_if_absent(
                    workspace_id=str(schedule["workspace_id"]),
                    user_id=str(schedule["user_id"]),
                    source_id=str(schedule["source_id"]),
                    subscription_id=str(schedule["subscription_id"]),
                    payload={
                        "reason": SCHEDULED_SOURCE_FETCH_REASON,
                        "source_id": schedule["source_id"],
                        "subscription_id": schedule["subscription_id"],
                    },
                    priority=-10,
                    max_attempts=self.max_attempts,
                    retention_days=self.retention_days,
                )
                if created:
                    self.quota.record_job_usage(
                        workspace_id=str(schedule["workspace_id"]),
                        user_id=str(schedule["user_id"]),
                        event_type="source_fetch",
                        commit=False,
                    )
                    result["enqueued"] += 1
                    action = "enqueued"
                else:
                    result["deduplicated"] += 1
                    action = "deduplicated"
                conn.execute(
                    """
                    UPDATE user_source_schedules
                    SET next_run_at = ?, last_evaluated_at = ?,
                        last_enqueued_at = CASE WHEN ? THEN ? ELSE last_enqueued_at END,
                        last_job_id = ?, last_skip_reason = NULL, updated_at = ?
                    WHERE subscription_id = ?
                    """,
                    (
                        interval_next.isoformat(),
                        now_iso,
                        1 if created else 0,
                        now_iso,
                        job["id"],
                        now_iso,
                        schedule["subscription_id"],
                    ),
                )
                result["outcomes"].append(
                    {
                        "subscription_id": schedule["subscription_id"],
                        "action": action,
                        "job_id": job["id"],
                    }
                )
            for actor_route in actor_routes:
                actor_route.stage_pending_transitions()
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        return result

    @staticmethod
    def _actor_ops_profile_id(subscription: Any) -> str | None:
        try:
            config = json.loads(str(subscription["source_config_json"] or "{}"))
        except (KeyError, TypeError, json.JSONDecodeError):
            return None
        if not isinstance(config, dict):
            return None
        profile_id = str(config.get("profile_id") or "").strip()
        return profile_id or None

    @staticmethod
    def _is_x_profile_subscription(subscription: Any) -> bool:
        try:
            config = json.loads(str(subscription["source_config_json"] or "{}"))
        except (KeyError, TypeError, json.JSONDecodeError):
            return False
        if not isinstance(config, dict):
            return False
        return (
            str(config.get("platform") or "").strip().casefold() == "x"
            and str(config.get("kind") or "profile").strip().casefold()
            == "profile"
        )

    def advance_after_full_refresh(
        self,
        *,
        workspace_id: str,
        user_id: str,
        source_outcomes: Any,
        finished_at: str,
        job_id: str,
    ) -> int:
        """Treat a participating full-refresh outcome as this source's latest run."""
        finished = datetime.fromisoformat(str(finished_at).replace("Z", "+00:00"))
        finished = _utc(finished)
        subscription_ids = {
            str(outcome.subscription_id)
            for outcome in source_outcomes
            if getattr(outcome, "subscription_id", None)
        }
        if not subscription_ids:
            return 0
        conn = self.store.connect()
        updated = 0
        for subscription_id in sorted(subscription_ids):
            row = conn.execute(
                """
                SELECT * FROM user_source_schedules
                WHERE subscription_id = ?
                  AND workspace_id = ?
                  AND user_id = ?
                  AND enabled = 1
                """,
                (subscription_id, workspace_id, user_id),
            ).fetchone()
            if row is None:
                continue
            schedule = self._schedule(row)
            next_run_at = finished + timedelta(
                minutes=schedule["interval_minutes"]
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
                  AND subscription_id = ?
                  AND job_type = 'source_fetch'
                  AND status = 'queued'
                  AND json_extract(payload_json, '$.reason') = ?
                """,
                (
                    finished.isoformat(),
                    finished.isoformat(),
                    finished.isoformat(),
                    workspace_id,
                    user_id,
                    subscription_id,
                    SCHEDULED_SOURCE_FETCH_REASON,
                ),
            )
            changed = conn.execute(
                """
                UPDATE user_source_schedules
                SET next_run_at = ?, last_evaluated_at = ?,
                    last_enqueued_at = ?, last_job_id = ?,
                    last_skip_reason = NULL, updated_at = ?
                WHERE subscription_id = ?
                  AND workspace_id = ?
                  AND user_id = ?
                  AND enabled = 1
                """,
                (
                    next_run_at.isoformat(),
                    finished.isoformat(),
                    finished.isoformat(),
                    job_id,
                    finished.isoformat(),
                    subscription_id,
                    workspace_id,
                    user_id,
                ),
            )
            updated += changed.rowcount
        return updated

    def _record_skip(
        self,
        schedule: dict[str, Any],
        *,
        now: datetime,
        next_run_at: datetime,
        reason: str,
        last_job_id: str | None = None,
    ) -> None:
        now_iso = _utc(now).isoformat()
        self.store.connect().execute(
            """
            UPDATE user_source_schedules
            SET next_run_at = ?, last_evaluated_at = ?, last_skip_reason = ?,
                last_job_id = COALESCE(?, last_job_id), updated_at = ?
            WHERE subscription_id = ?
            """,
            (
                _utc(next_run_at).isoformat(),
                now_iso,
                reason,
                last_job_id,
                now_iso,
                schedule["subscription_id"],
            ),
        )
