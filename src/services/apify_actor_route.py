"""Durable, sequential Actor failover for the Apify-only X profile route."""

from __future__ import annotations

import asyncio
import hashlib
import inspect
import logging
import math
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Awaitable, Callable, Generic, TypeVar

from ..storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore

logger = logging.getLogger(__name__)

X_PROFILE_ROUTE = "x/profile"
PER_RUN_RESERVATION_USD = 0.02
PER_ATTEMPT_GROUP_LIMIT_USD = 0.06
FAILED_SPEND_LIMIT_USD = 0.08
FAILED_SPEND_WINDOW = timedelta(hours=6)
QUOTA_SNAPSHOT_MAX_AGE = timedelta(seconds=60)
SYSTEMIC_FAILURE_WINDOW = timedelta(minutes=15)
TARGET_PAUSE = timedelta(hours=6)
HALF_OPEN_RECOVERY_SUCCESSES = 2
PROBATION_WINDOW = timedelta(hours=48)
PROBATION_SUCCESS_RATE = 0.95
_COOLDOWNS = (
    timedelta(hours=1),
    timedelta(hours=3),
    timedelta(hours=6),
    timedelta(hours=24),
)
_TERMINAL_ATTEMPT_STATUSES = frozenset(
    {
        "succeeded",
        "valid_empty",
        "actor_failed",
        "target_failed",
        "start_outcome_unknown",
        "cancelled",
    }
)

T = TypeVar("T")


class ApifyActorRoutedList(list[T]):
    """List carrying an internal proof of the final route generation."""

    __slots__ = ("_apify_actor_route_generation",)

    def __init__(self, values: list[T], *, route_generation: int) -> None:
        super().__init__(values)
        self._apify_actor_route_generation = int(route_generation)


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not isinstance(value, str) or not value.strip():
        return None
    try:
        return _utc(datetime.fromisoformat(value.replace("Z", "+00:00")))
    except ValueError:
        return None


def _safe_cost(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    if not math.isfinite(number) or number < 0:
        return None
    return number


def _attempt_consumes_job_budget(row: sqlite3.Row) -> bool:
    """Keep only cancellations that are proven not to have started an Actor."""

    if str(row["status"]) != "cancelled":
        return True
    if str(row["semantic_outcome"] or "") == (
        "apify_actor_route_generation_conflict"
    ):
        return True
    if float(row["actual_cost_usd"] or 0.0) > 0:
        return True
    return bool(row["may_have_started"])


class ApifyActorRouteError(RuntimeError):
    """Safe route failure suitable for API and Worker handling."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        retryable: bool,
        retry_at: datetime | None = None,
        status_code: int = 503,
    ) -> None:
        self.code = code
        self.retryable = retryable
        self.retry_at = _utc(retry_at) if retry_at else None
        self.status_code = status_code
        super().__init__(message)


class ApifyActorRouteConflictError(ApifyActorRouteError):
    def __init__(self) -> None:
        super().__init__(
            "apify_actor_route_generation_conflict",
            "The Actor route changed; reload before retrying",
            retryable=True,
            status_code=409,
        )


class ApifyActorRouteBlockedError(ApifyActorRouteError):
    pass


@dataclass(frozen=True, slots=True)
class ApifyActorCandidateLease:
    attempt_id: str
    attempt_group_id: str
    route_generation: int
    candidate_id: str
    actor_id: str
    adapter_key: str
    source_id: str | None
    job_id: str | None
    attempt_index: int
    canary: bool = False
    resume_run_id: str | None = None


@dataclass(frozen=True, slots=True)
class ApifyActorInvocationResult(Generic[T]):
    value: T
    semantic_outcome: str
    actual_cost_usd: float | None = None
    cost_final: bool = False


@dataclass(frozen=True, slots=True)
class ApifyActorScheduleGate:
    allowed: bool
    status: str
    retry_at: datetime | None = None
    error_code: str | None = None


class ApifyActorRouteService:
    """Own Actor choice and accounting; the Key Pool still owns credentials."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
        route_key: str = X_PROFILE_ROUTE,
        now: Callable[[], datetime] | None = None,
        transition_hook: Callable[[str, dict[str, Any]], Any] | None = None,
        enforce_quota_admission: bool = False,
    ) -> None:
        if route_key != X_PROFILE_ROUTE:
            raise ValueError("Only x/profile routing is implemented")
        self.store = store
        self.workspace_id = str(workspace_id)
        self.route_key = route_key
        self._now = now or (lambda: datetime.now(timezone.utc))
        self._transition_hook = transition_hook
        self._enforce_quota_admission = bool(enforce_quota_admission)
        self._pending_transitions: list[tuple[str, dict[str, Any]]] = []

    def _current_time(self) -> datetime:
        return _utc(self._now())

    def _commit(
        self,
        connection: sqlite3.Connection,
        owns_transaction: bool,
    ) -> None:
        if owns_transaction:
            connection.commit()
            self._flush_transition_hooks()

    def _rollback(
        self,
        connection: sqlite3.Connection,
        owns_transaction: bool,
    ) -> None:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        self._pending_transitions.clear()

    def _flush_transition_hooks(self) -> None:
        pending, self._pending_transitions = self._pending_transitions, []
        if self._transition_hook is None:
            return
        for event_type, payload in pending:
            try:
                result = self._transition_hook(event_type, payload)
                if inspect.isawaitable(result):
                    task = asyncio.ensure_future(result)
                    task.add_done_callback(self._consume_hook_result)
            except Exception:
                connection = self.store.connect()
                if connection.in_transaction:
                    connection.rollback()
                logger.warning(
                    "Apify Actor transition hook failed event_type=%s",
                    event_type,
                )

    def _consume_hook_result(self, task: asyncio.Task[Any]) -> None:
        try:
            task.result()
        except Exception:
            connection = self.store.connect()
            if connection.in_transaction:
                connection.rollback()
            logger.warning("Async Apify Actor transition hook failed")

    def stage_pending_transitions(self) -> None:
        """Stage synchronous transition effects inside the caller transaction.

        The schedule evaluator owns a wider transaction than one route call.
        Savepoints keep alert staging non-blocking without publishing an event
        for a route mutation that may still roll back.
        """

        pending, self._pending_transitions = self._pending_transitions, []
        if self._transition_hook is None or not pending:
            return
        connection = self.store.connect()
        if not connection.in_transaction:
            self._pending_transitions = pending + self._pending_transitions
            raise RuntimeError(
                "staging Actor transitions requires an active transaction"
            )
        for index, (event_type, payload) in enumerate(pending):
            savepoint = f"apify_actor_transition_{index}"
            connection.execute(f"SAVEPOINT {savepoint}")
            try:
                result = self._transition_hook(event_type, payload)
                if inspect.isawaitable(result):
                    close = getattr(result, "close", None)
                    if callable(close):
                        close()
                    raise TypeError(
                        "transactional Actor transition hooks must be synchronous"
                    )
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
            except Exception:
                connection.execute(f"ROLLBACK TO SAVEPOINT {savepoint}")
                connection.execute(f"RELEASE SAVEPOINT {savepoint}")
                logger.warning(
                    "Apify Actor transition hook failed event_type=%s",
                    event_type,
                )

    def _route_row(self, connection: sqlite3.Connection) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM apify_actor_routes
            WHERE workspace_id = ? AND route_key = ?
            """,
            (self.workspace_id, self.route_key),
        ).fetchone()
        if row is None:
            raise LookupError("Apify Actor route is not configured")
        return row

    def route_generation(self) -> int:
        return int(self._route_row(self.store.connect())["generation"])

    def reconcile_unfinished_attempts(self) -> dict[str, int | bool]:
        """Close stale route reservations after the Key Pool startup barrier.

        Any linked remote Run is reconciliation evidence and blocks new paid
        starts. Only an attempt that never acquired a Key, or explicit
        pre-start rejection rows without a remote id, is safe to cancel.
        """

        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        cancelled = 0
        blocked_attempts = 0
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            attempts = connection.execute(
                """
                SELECT attempt.*, candidate.adapter_key
                FROM apify_actor_attempts AS attempt
                JOIN apify_actor_candidates AS candidate
                  ON candidate.id = attempt.candidate_id
                WHERE attempt.workspace_id = ? AND attempt.route_key = ?
                  AND attempt.status IN ('reserved', 'running')
                ORDER BY attempt.created_at, attempt.id
                """,
                (self.workspace_id, self.route_key),
            ).fetchall()
            route_must_block = False
            for attempt in attempts:
                key_runs = connection.execute(
                    """
                    SELECT status, remote_run_id, dataset_id,
                           charge_actual_usd, charge_final
                    FROM apify_actor_runs
                    WHERE workspace_id = ? AND logical_run_id = ?
                    ORDER BY created_at, id
                    """,
                    (self.workspace_id, attempt["id"]),
                ).fetchall()
                unknown = any(
                    str(run["status"]) not in {
                        "succeeded",
                        "failed",
                        "aborted",
                        "timed_out",
                        "start_rejected",
                        "cancelled",
                    }
                    for run in key_runs
                )
                remote_evidence = any(run["remote_run_id"] for run in key_runs)
                dataset_pending = any(
                    str(run["status"]) == "succeeded"
                    and run["remote_run_id"]
                    and run["dataset_id"]
                    for run in key_runs
                )
                known_cost = 0.0
                all_costs_final = True
                for run in key_runs:
                    status = str(run["status"])
                    no_remote_start_rejected = (
                        status in {"start_rejected", "cancelled"}
                        and not run["remote_run_id"]
                    )
                    if bool(run["charge_final"]):
                        known_cost += float(run["charge_actual_usd"] or 0.0)
                    elif not no_remote_start_rejected:
                        all_costs_final = False
                if unknown or remote_evidence:
                    terminal_status = (
                        "running" if remote_evidence else "start_outcome_unknown"
                    )
                    semantic_outcome = (
                        "apify_restart_dataset_pending"
                        if dataset_pending
                        else "apify_restart_run_reconcile_required"
                    )
                    route_must_block = True
                    blocked_attempts += 1
                else:
                    terminal_status = "cancelled"
                    semantic_outcome = (
                        "apify_restart_before_key_reservation"
                        if not key_runs
                        else "apify_restart_key_run_reconciled"
                    )
                    cancelled += 1
                terminal_at = (
                    None if terminal_status == "running" else now.isoformat()
                )
                connection.execute(
                    """
                    UPDATE apify_actor_attempts
                    SET status = ?, semantic_outcome = ?,
                        actual_cost_usd = ?, cost_final = ?,
                        last_error_code = ?, terminal_at = ?, updated_at = ?
                    WHERE id = ? AND status IN ('reserved', 'running')
                    """,
                    (
                        terminal_status,
                        semantic_outcome,
                        known_cost if key_runs else 0.0,
                        int(all_costs_final),
                        semantic_outcome,
                        terminal_at,
                        now.isoformat(),
                        attempt["id"],
                    ),
                )
                if remote_evidence:
                    connection.execute(
                        """
                        UPDATE apify_actor_runs
                        SET last_error_code = 'apify_run_reconcile_required',
                            updated_at = ?
                        WHERE workspace_id = ? AND logical_run_id = ?
                          AND remote_run_id IS NOT NULL
                        """,
                        (
                            now.isoformat(),
                            self.workspace_id,
                            attempt["id"],
                        ),
                    )
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET probe_claimed_at = NULL, updated_at = ?
                    WHERE id = ?
                    """,
                    (now.isoformat(), attempt["candidate_id"]),
                )
            self._evaluate_due_probations(connection, now)
            if route_must_block:
                blocked_reason = "apify_run_reconcile_required"
                route = self._route_row(connection)
                adopt_generation = int(route["generation"])
                if route["status"] != "blocked":
                    self._write_route_change(
                        connection,
                        route,
                        now,
                        active_candidate_id=route["active_candidate_id"],
                        status="blocked",
                        reason=blocked_reason,
                        blocked_reason=blocked_reason,
                    )
                current_generation = int(
                    self._route_row(connection)["generation"]
                )
                connection.execute(
                    """
                    UPDATE apify_actor_attempts
                    SET route_generation = ?, updated_at = ?
                    WHERE workspace_id = ? AND route_key = ?
                      AND status = 'running'
                      AND route_generation = ?
                      AND semantic_outcome IN (
                          'apify_restart_dataset_pending',
                          'apify_restart_run_reconcile_required',
                          'apify_run_reconcile_required'
                      )
                    """,
                    (
                        current_generation,
                        now.isoformat(),
                        self.workspace_id,
                        self.route_key,
                        adopt_generation,
                    ),
                )
                connection.execute(
                    """
                    UPDATE apify_key_pool_state
                    SET status = 'blocked', blocked_reason = ?, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (blocked_reason, now.isoformat(), self.workspace_id),
                )
            self._commit(connection, owns_transaction)
        except Exception:
            self._rollback(connection, owns_transaction)
            raise
        return {
            "cancelled": cancelled,
            "blocked_attempts": blocked_attempts,
            "route_blocked": blocked_attempts > 0,
        }

    def public_state(self) -> dict[str, Any]:
        connection = self.store.connect()
        route = self._route_row(connection)
        now = self._current_time()
        cutoff = (now - timedelta(hours=24)).isoformat()
        listed_prices = {
            "scrape_badger": 0.15,
            "dami": 0.30,
            "xquik": 15.0,
        }
        paid_plan_listed_prices = {
            "xquik": 0.15,
        }
        candidates: list[dict[str, Any]] = []
        for row in connection.execute(
            """
            SELECT * FROM apify_actor_candidates
            WHERE workspace_id = ? AND route_key = ?
            ORDER BY position, id
            """,
            (self.workspace_id, self.route_key),
        ).fetchall():
            metrics = connection.execute(
                """
                SELECT
                    SUM(CASE WHEN status IN ('succeeded', 'valid_empty')
                        THEN 1 ELSE 0 END) AS successes,
                    SUM(CASE WHEN status = 'actor_failed'
                        THEN 1 ELSE 0 END) AS failures,
                    AVG(CASE WHEN cost_final = 1
                        THEN actual_cost_usd END) AS avg_cost
                FROM apify_actor_attempts
                WHERE candidate_id = ? AND created_at >= ?
                  AND status IN ('succeeded', 'valid_empty', 'actor_failed')
                """,
                (row["id"], cutoff),
            ).fetchone()
            last_cost = connection.execute(
                """
                SELECT actual_cost_usd
                FROM apify_actor_attempts
                WHERE candidate_id = ? AND cost_final = 1
                ORDER BY terminal_at DESC, created_at DESC LIMIT 1
                """,
                (row["id"],),
            ).fetchone()
            successes = int(metrics["successes"] or 0)
            failures = int(metrics["failures"] or 0)
            measured = successes + failures
            candidates.append(
                {
                    "id": str(row["id"]),
                    "position": int(row["position"]),
                    "display_name": str(row["display_name"]),
                    "actor_public_name": str(row["actor_id"]),
                    "state": str(row["state"]),
                    "listed_price_usd_per_1000": listed_prices.get(
                        str(row["adapter_key"])
                    ),
                    "paid_plan_listed_price_usd_per_1000":
                        paid_plan_listed_prices.get(
                            str(row["adapter_key"])
                        ),
                    "success_rate_24h": (
                        round(successes / measured, 4) if measured else None
                    ),
                    "avg_charge_24h_usd": (
                        float(metrics["avg_cost"])
                        if metrics["avg_cost"] is not None
                        else None
                    ),
                    "last_charge_usd": (
                        float(last_cost["actual_cost_usd"])
                        if last_cost is not None
                        and last_cost["actual_cost_usd"] is not None
                        else None
                    ),
                    "last_success_at": row["last_success_at"],
                    "last_failure_at": row["last_failure_at"],
                    "retry_at": row["retry_at"],
                    "last_error_code": row["last_error_code"],
                    "can_enable": (
                        row["state"] == "disabled"
                        and row["last_error_code"] != "canary_required"
                    ),
                    "can_disable": row["state"] != "disabled",
                    "can_canary": True,
                }
            )
        retry_at = self._next_retry_at(connection)
        quota = self._quota_state(connection, now)
        return {
            "schema_version": 1,
            "route": self.route_key,
            "generation": int(route["generation"]),
            "status": str(route["status"]),
            "active_candidate_id": route["active_candidate_id"],
            "last_switch_reason": route["last_switch_reason"],
            "last_switch_at": route["last_switch_at"],
            "retry_at": retry_at.isoformat() if retry_at else None,
            "blocked_reason": route["blocked_reason"],
            "quota": quota,
            "limits": {
                "per_run_usd": PER_RUN_RESERVATION_USD,
                "per_job_usd": PER_ATTEMPT_GROUP_LIMIT_USD,
                "failed_spend_6h_usd": FAILED_SPEND_LIMIT_USD,
            },
            "candidates": candidates,
        }

    def _quota_state(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> dict[str, Any]:
        rows = connection.execute(
            """
            SELECT
                remaining_included_credits_usd,
                last_checked_at
            FROM apify_key_pool_members
            WHERE workspace_id = ?
              AND status IN ('active', 'standby', 'draining')
            ORDER BY position, secret_id
            """,
            (self.workspace_id,),
        ).fetchall()
        checked_times = [_parse_time(row["last_checked_at"]) for row in rows]
        all_available_measured = bool(rows) and all(
            row["remaining_included_credits_usd"] is not None
            and checked_at is not None
            and now - QUOTA_SNAPSHOT_MAX_AGE <= checked_at
            and checked_at <= now + QUOTA_SNAPSHOT_MAX_AGE
            for row, checked_at in zip(rows, checked_times, strict=True)
        )
        total_remaining = (
            sum(float(row["remaining_included_credits_usd"]) for row in rows)
            if all_available_measured
            else None
        )
        x_allocatable = (
            max(total_remaining - max(1.0, total_remaining * 0.20), 0.0)
            if total_remaining is not None
            else None
        )
        spend_row = connection.execute(
            """
            SELECT COALESCE(SUM(actual_cost_usd), 0) AS spend
            FROM apify_actor_attempts
            WHERE workspace_id = ? AND route_key = ?
              AND cost_final = 1 AND terminal_at >= ?
            """,
            (
                self.workspace_id,
                self.route_key,
                (now - timedelta(hours=24)).isoformat(),
            ),
        ).fetchone()
        spend_24h = float(spend_row["spend"] or 0.0)
        estimated_days = (
            round(x_allocatable / spend_24h, 2)
            if x_allocatable is not None and spend_24h > 0
            else None
        )
        return {
            "currency": "USD",
            "total_remaining_usd": total_remaining,
            "x_allocatable_usd": x_allocatable,
            "spend_24h_usd": spend_24h,
            "estimated_days_remaining": estimated_days,
            "as_of": (
                min(
                    checked_at
                    for checked_at in checked_times
                    if checked_at is not None
                ).isoformat()
                if all_available_measured
                else None
            ),
        }

    def schedule_gate(self, source_id: str | None = None) -> ApifyActorScheduleGate:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            self._release_expired_budget_block(connection, now)
            self._make_due_candidates_probeable(connection, now)
            route = self._route_row(connection)
            target_retry = self._target_pause_until(
                connection,
                source_id,
                now,
            )
            if target_retry is not None:
                result = ApifyActorScheduleGate(
                    False,
                    str(route["status"]),
                    target_retry,
                    "apify_actor_target_paused",
                )
            elif route["status"] == "blocked":
                result = ApifyActorScheduleGate(
                    False,
                    "blocked",
                    None,
                    str(route["blocked_reason"] or "apify_actor_route_blocked"),
                )
            elif route["status"] == "budget_blocked":
                result = ApifyActorScheduleGate(
                    False,
                    "budget_blocked",
                    _parse_time(route["budget_blocked_until"]),
                    "apify_actor_budget_blocked",
                )
            elif (
                self._enforce_quota_admission
                and self._quota_state(connection, now)["x_allocatable_usd"]
                is None
            ):
                result = ApifyActorScheduleGate(
                    False,
                    str(route["status"]),
                    None,
                    "apify_actor_quota_unknown",
                )
            elif self._has_selectable_candidate(
                connection,
                now,
                exclude_canary_busy=True,
            ):
                result = ApifyActorScheduleGate(
                    True,
                    str(route["status"]),
                )
            elif self._has_selectable_candidate(connection, now):
                result = ApifyActorScheduleGate(
                    False,
                    str(route["status"]),
                    None,
                    "apify_actor_canary_active",
                )
            else:
                retry_at = self._next_retry_at(connection)
                self._set_route_unavailable(
                    connection,
                    now,
                    retry_at=retry_at,
                    reason="all_candidates_unavailable",
                )
                result = ApifyActorScheduleGate(
                    False,
                    "exhausted",
                    retry_at,
                    "apify_actor_route_exhausted",
                )
            self._commit(connection, owns_transaction)
            return result
        except Exception:
            self._rollback(connection, owns_transaction)
            raise

    def reorder(
        self,
        candidate_ids: list[str],
        *,
        expected_generation: int,
    ) -> dict[str, Any]:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            self._release_expired_budget_block(connection, now)
            route = self._assert_generation(connection, expected_generation)
            current_rows = connection.execute(
                """
                SELECT id FROM apify_actor_candidates
                WHERE workspace_id = ? AND route_key = ?
                ORDER BY position, id
                """,
                (self.workspace_id, self.route_key),
            ).fetchall()
            current_ids = [str(row["id"]) for row in current_rows]
            if (
                len(candidate_ids) != len(current_ids)
                or len(set(candidate_ids)) != len(candidate_ids)
                or set(candidate_ids) != set(current_ids)
            ):
                raise ValueError("candidate_ids must contain every route candidate once")
            for index, candidate_id in enumerate(candidate_ids):
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET position = ?, updated_at = ?
                    WHERE id = ? AND workspace_id = ? AND route_key = ?
                    """,
                    (1000 + index, now.isoformat(), candidate_id,
                     self.workspace_id, self.route_key),
                )
            for index, candidate_id in enumerate(candidate_ids):
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET position = ?, updated_at = ?
                    WHERE id = ? AND workspace_id = ? AND route_key = ?
                    """,
                    (index, now.isoformat(), candidate_id,
                     self.workspace_id, self.route_key),
                )
            # An explicit order update is the one operation that is allowed to
            # replace a still-healthy sticky primary. Runtime recovery remains
            # sticky and therefore does not reclaim the primary automatically.
            active = self._first_candidate_by_position(connection, now)
            self._write_route_change(
                connection,
                route,
                now,
                active_candidate_id=active["id"] if active else None,
                status=self._route_availability_status(
                    connection,
                    active_candidate=active,
                ),
                reason="admin_reorder",
            )
            self._commit(connection, owns_transaction)
        except Exception:
            self._rollback(connection, owns_transaction)
            raise
        return self.public_state()

    def enable(
        self,
        candidate_id: str,
        *,
        expected_generation: int,
    ) -> dict[str, Any]:
        return self._set_enabled(
            candidate_id,
            enabled=True,
            expected_generation=expected_generation,
        )

    def disable(
        self,
        candidate_id: str,
        *,
        expected_generation: int,
    ) -> dict[str, Any]:
        return self._set_enabled(
            candidate_id,
            enabled=False,
            expected_generation=expected_generation,
        )

    def _set_enabled(
        self,
        candidate_id: str,
        *,
        enabled: bool,
        expected_generation: int,
    ) -> dict[str, Any]:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            self._release_expired_budget_block(connection, now)
            route = self._assert_generation(connection, expected_generation)
            candidate = self._candidate_row(connection, candidate_id)
            if (
                enabled
                and candidate["state"] == "disabled"
                and candidate["last_error_code"] == "canary_required"
            ):
                raise ApifyActorRouteError(
                    "apify_actor_canary_required",
                    "This Actor must pass a paid canary before it can be enabled",
                    retryable=False,
                    status_code=409,
                )
            desired_state = "half_open" if enabled else "disabled"
            if candidate["state"] == desired_state or (
                enabled and candidate["state"] != "disabled"
            ):
                self._commit(connection, owns_transaction)
                return self.public_state()
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET state = ?, recovery_successes = 0, probe_claimed_at = NULL,
                    retry_at = ?, last_error_code = NULL, updated_at = ?
                WHERE id = ?
                """,
                (
                    desired_state,
                    now.isoformat() if enabled else None,
                    now.isoformat(),
                    candidate_id,
                ),
            )
            active = self._first_routable_candidate(connection, now)
            self._write_route_change(
                connection,
                route,
                now,
                active_candidate_id=active["id"] if active else None,
                status=self._route_availability_status(
                    connection,
                    active_candidate=active,
                ),
                reason="admin_enable" if enabled else "admin_disable",
            )
            self._commit(connection, owns_transaction)
        except Exception:
            self._rollback(connection, owns_transaction)
            raise
        return self.public_state()

    def unblock(
        self,
        *,
        expected_generation: int,
        reason: str = "run_reconciled",
    ) -> dict[str, Any]:
        """Release a start-unknown block only after the caller reconciles the Run."""

        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            route = self._assert_generation(connection, expected_generation)
            if route["status"] != "blocked":
                self._commit(connection, owns_transaction)
                return self.public_state()
            active = self._first_routable_candidate(connection, now)
            self._write_route_change(
                connection,
                route,
                now,
                active_candidate_id=active["id"] if active else None,
                status="degraded" if active else "exhausted",
                reason=reason,
                blocked_reason=None,
            )
            self._commit(connection, owns_transaction)
        except Exception:
            self._rollback(connection, owns_transaction)
            raise
        return self.public_state()

    def reserve_canary(
        self,
        candidate_id: str,
        source_id: str,
        *,
        expected_generation: int,
        job_id: str | None = None,
    ) -> ApifyActorCandidateLease:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            self._release_expired_budget_block(connection, now)
            route = self._assert_generation(connection, expected_generation)
            candidate = self._candidate_row(connection, candidate_id)
            self._assert_canary_candidate_idle(
                connection,
                candidate_id,
                job_id=job_id,
            )
            self._assert_route_charge_allowed(connection, route, now)
            if candidate["state"] == "open":
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET state = 'half_open', recovery_successes = 0,
                        probe_claimed_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now.isoformat(), now.isoformat(), candidate_id),
                )
            lease = self._insert_attempt(
                connection,
                route,
                candidate,
                source_id=source_id,
                job_id=job_id,
                attempt_group_id=f"canary-{uuid.uuid4().hex}",
                attempt_index=1,
                canary=True,
                now=now,
            )
            self._commit(connection, owns_transaction)
            return lease
        except ApifyActorRouteError:
            self._commit(connection, owns_transaction)
            raise
        except Exception:
            self._rollback(connection, owns_transaction)
            raise

    async def execute_x_profile(
        self,
        source_id: str,
        invoke: Callable[
            [ApifyActorCandidateLease],
            ApifyActorInvocationResult[T] | Awaitable[ApifyActorInvocationResult[T]] | Any,
        ],
        *,
        job_id: str | None = None,
        candidate_id: str | None = None,
        expected_generation: int | None = None,
        canary: bool = False,
    ) -> T:
        """Try at most three different Actors serially for one logical claim."""

        resume_lease = self._resume_pending_attempt(
            source_id=source_id,
            job_id=job_id,
            candidate_id=candidate_id,
        )
        last_actor_error: Exception | None = None
        if resume_lease is not None:
            self.mark_running(resume_lease)
            succeeded, value, actor_error = await self._invoke_once(
                resume_lease,
                invoke,
                fallback_allowed=True,
            )
            if succeeded:
                return value
            if candidate_id:
                assert actor_error is not None
                raise actor_error
            group_id = resume_lease.attempt_group_id
            last_actor_error = actor_error
        else:
            group_id = self._attempt_group_id(
                source_id=source_id,
                job_id=job_id,
            )
            if self._has_unrecoverable_terminal_success(
                source_id=source_id,
                job_id=job_id,
                candidate_id=candidate_id,
            ):
                raise ApifyActorRouteError(
                    "apify_run_reconcile_required",
                    "The completed Actor Dataset cannot be safely replayed",
                    retryable=True,
                )

        if canary and not candidate_id:
            raise ValueError("canary execution requires candidate_id")
        if candidate_id and resume_lease is None:
            if expected_generation is None:
                raise ValueError("forced Actor execution requires expected_generation")
            lease = (
                self.reserve_canary(
                    candidate_id,
                    source_id,
                    expected_generation=expected_generation,
                    job_id=job_id,
                )
                if canary
                else self._reserve_forced(
                    candidate_id,
                    source_id=source_id,
                    job_id=job_id,
                    expected_generation=expected_generation,
                )
            )
            self.mark_running(lease)
            succeeded, value, actor_error = await self._invoke_once(
                lease,
                invoke,
                fallback_allowed=False,
            )
            if succeeded:
                return value
            assert actor_error is not None
            raise actor_error

        progress = self._attempt_group_progress(
            group_id,
            source_id=source_id,
            job_id=job_id,
        )
        if (
            int(progress["charged_attempts"]) >= 3
            or float(progress["reserved_spend_usd"])
            + PER_RUN_RESERVATION_USD
            > PER_ATTEMPT_GROUP_LIMIT_USD + 1e-9
        ):
            raise ApifyActorRouteError(
                "apify_actor_job_budget_exhausted",
                "This task reached its Actor charge reservation limit",
                retryable=False,
            )
        attempted = set(progress["excluded_candidate_ids"])
        for _remaining in range(3 - int(progress["charged_attempts"])):
            lease = self._reserve_next(
                source_id=source_id,
                job_id=job_id,
                attempt_group_id=group_id,
                excluded_candidate_ids=attempted,
            )
            attempted.add(lease.candidate_id)
            self.mark_running(lease)
            succeeded, value, actor_error = await self._invoke_once(
                lease,
                invoke,
                fallback_allowed=True,
            )
            if succeeded:
                return value
            last_actor_error = actor_error

        retry_at = self._next_retry_at(self.store.connect())
        raise ApifyActorRouteError(
            "apify_actor_attempts_exhausted",
            "All available X profile Actors failed for this task",
            retryable=True,
            retry_at=retry_at,
        ) from last_actor_error

    def _resume_pending_attempt(
        self,
        *,
        source_id: str,
        job_id: str | None,
        candidate_id: str | None,
    ) -> ApifyActorCandidateLease | None:
        """Return a durable Run/Dataset for the same retried Worker job.

        A route attempt may already be terminal when the Worker crashes after
        recording semantic success but before completing its Job. Replaying
        that Dataset remains GET-only and must win over a new paid Actor POST.
        """

        if not job_id:
            return None
        row = self.store.connect().execute(
            """
            SELECT attempt.*, candidate.actor_id, candidate.adapter_key,
                   run.id AS resume_run_id
            FROM apify_actor_attempts AS attempt
            JOIN apify_actor_candidates AS candidate
              ON candidate.id = attempt.candidate_id
            JOIN apify_actor_runs AS run
              ON run.workspace_id = attempt.workspace_id
             AND run.logical_run_id = attempt.id
             AND run.remote_run_id IS NOT NULL
            WHERE attempt.workspace_id = ? AND attempt.route_key = ?
              AND attempt.source_id = ? AND attempt.job_id = ?
              AND (? IS NULL OR attempt.candidate_id = ?)
              AND (
                  (
                      attempt.status = 'running'
                      AND attempt.semantic_outcome IN (
                          'apify_restart_dataset_pending',
                          'apify_restart_run_reconcile_required',
                          'apify_run_reconcile_required'
                      )
                  )
                  OR (
                      attempt.status IN ('succeeded', 'valid_empty')
                      AND run.status = 'succeeded'
                      AND run.dataset_id IS NOT NULL
                  )
              )
            ORDER BY
              CASE WHEN attempt.status IN ('succeeded', 'valid_empty')
                  THEN 0 ELSE 1 END,
              attempt.created_at, run.created_at
            LIMIT 1
            """,
            (
                self.workspace_id,
                self.route_key,
                source_id,
                job_id,
                candidate_id,
                candidate_id,
            ),
        ).fetchone()
        if row is None:
            return None
        return ApifyActorCandidateLease(
            attempt_id=str(row["id"]),
            attempt_group_id=str(row["attempt_group_id"]),
            route_generation=int(row["route_generation"]),
            candidate_id=str(row["candidate_id"]),
            actor_id=str(row["actor_id"]),
            adapter_key=str(row["adapter_key"]),
            source_id=str(row["source_id"]) if row["source_id"] else None,
            job_id=str(row["job_id"]) if row["job_id"] else None,
            attempt_index=int(row["attempt_index"]),
            canary=str(row["attempt_group_id"]).startswith("canary-"),
            resume_run_id=str(row["resume_run_id"]),
        )

    def _has_unrecoverable_terminal_success(
        self,
        *,
        source_id: str,
        job_id: str | None,
        candidate_id: str | None,
    ) -> bool:
        if not job_id:
            return False
        row = self.store.connect().execute(
            """
            SELECT 1
            FROM apify_actor_attempts AS attempt
            WHERE attempt.workspace_id = ? AND attempt.route_key = ?
              AND attempt.source_id = ? AND attempt.job_id = ?
              AND (? IS NULL OR attempt.candidate_id = ?)
              AND attempt.status IN ('succeeded', 'valid_empty')
              AND NOT EXISTS (
                  SELECT 1
                  FROM apify_actor_runs AS run
                  WHERE run.workspace_id = attempt.workspace_id
                    AND run.logical_run_id = attempt.id
                    AND run.status = 'succeeded'
                    AND run.remote_run_id IS NOT NULL
                    AND run.dataset_id IS NOT NULL
              )
            LIMIT 1
            """,
            (
                self.workspace_id,
                self.route_key,
                source_id,
                job_id,
                candidate_id,
                candidate_id,
            ),
        ).fetchone()
        return row is not None

    async def _invoke_once(
        self,
        lease: ApifyActorCandidateLease,
        invoke: Callable[[ApifyActorCandidateLease], Any],
        *,
        fallback_allowed: bool,
    ) -> tuple[bool, Any, Exception | None]:
        try:
            raw_result = invoke(lease)
            if inspect.isawaitable(raw_result):
                raw_result = await raw_result
        except Exception as exc:
            code = str(getattr(exc, "code", "") or type(exc).__name__)
            if code in {
                "apify_start_outcome_unknown",
                "apify_start_http_outcome_unknown",
            }:
                self.record_start_outcome_unknown(
                    lease,
                    error_code=code,
                )
                raise
            if code == "apify_run_reconcile_required":
                self.record_run_reconcile_required(lease)
                raise
            if self._is_key_pool_failure(code, exc):
                self.cancel_attempt(lease, error_code=code)
                raise
            scope = str(getattr(exc, "failure_scope", "") or "")
            if scope == "target":
                self.record_failure(
                    lease,
                    failure_scope="target",
                    semantic_outcome=code,
                    error_code=code,
                    actual_cost_usd=getattr(exc, "actual_charge_usd", None),
                    cost_final=bool(getattr(exc, "cost_final", False)),
                )
                raise
            if scope == "actor" or self._is_actor_transport_failure(code, exc):
                self.record_failure(
                    lease,
                    failure_scope="actor",
                    semantic_outcome=code,
                    error_code=code,
                    actual_cost_usd=getattr(exc, "actual_charge_usd", None),
                    cost_final=bool(getattr(exc, "cost_final", False)),
                )
                if fallback_allowed:
                    return False, None, exc
                raise
            self.cancel_attempt(lease, error_code=code)
            raise

        try:
            normalized = self._normalize_invocation_result(raw_result)
        except (TypeError, ValueError) as exc:
            self.record_failure(
                lease,
                failure_scope="actor",
                semantic_outcome="apify_actor_contract_mismatch",
                error_code="apify_actor_contract_mismatch",
                actual_cost_usd=getattr(raw_result, "actual_charge_usd", None),
                cost_final=bool(getattr(raw_result, "cost_final", False)),
            )
            if fallback_allowed:
                return False, None, exc
            raise ApifyActorRouteError(
                "apify_actor_contract_mismatch",
                "The selected Actor returned an invalid semantic result",
                retryable=True,
            ) from None
        if normalized.semantic_outcome == "suspicious_empty":
            should_fallback, final_generation = self.record_suspicious_empty(
                lease,
                actual_cost_usd=normalized.actual_cost_usd,
                cost_final=normalized.cost_final,
            )
            if should_fallback:
                actor_error = ApifyActorRouteError(
                    "apify_actor_unexpected_empty",
                    "The selected Actor returned abnormal empty datasets",
                    retryable=True,
                )
                if fallback_allowed:
                    return False, None, actor_error
                raise actor_error
            value = normalized.value
            if isinstance(value, list):
                value = ApifyActorRoutedList(
                    value,
                    route_generation=final_generation,
                )
            return True, value, None
        final_generation = self.record_success(
            lease,
            semantic_outcome=normalized.semantic_outcome,
            actual_cost_usd=normalized.actual_cost_usd,
            cost_final=normalized.cost_final,
        )
        value = normalized.value
        if isinstance(value, list):
            value = ApifyActorRoutedList(
                value,
                route_generation=final_generation,
            )
        return True, value, None

    def _reserve_forced(
        self,
        candidate_id: str,
        *,
        source_id: str,
        job_id: str | None,
        expected_generation: int,
    ) -> ApifyActorCandidateLease:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            self._release_expired_budget_block(connection, now)
            route = self._assert_generation(connection, expected_generation)
            candidate = self._candidate_row(connection, candidate_id)
            if candidate["state"] == "disabled":
                raise ApifyActorRouteError(
                    "apify_actor_candidate_disabled",
                    "The selected Actor candidate is disabled",
                    retryable=False,
                    status_code=409,
                )
            self._assert_route_charge_allowed(connection, route, now)
            lease = self._insert_attempt(
                connection,
                route,
                candidate,
                source_id=source_id,
                job_id=job_id,
                attempt_group_id=f"forced-{uuid.uuid4().hex}",
                attempt_index=1,
                canary=False,
                now=now,
            )
            self._commit(connection, owns_transaction)
            return lease
        except ApifyActorRouteError:
            self._commit(connection, owns_transaction)
            raise
        except Exception:
            self._rollback(connection, owns_transaction)
            raise

    def _reserve_next(
        self,
        *,
        source_id: str,
        job_id: str | None,
        attempt_group_id: str,
        excluded_candidate_ids: set[str],
    ) -> ApifyActorCandidateLease:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            self._release_expired_budget_block(connection, now)
            self._make_due_candidates_probeable(connection, now)
            route = self._route_row(connection)
            paused_until = self._target_pause_until(connection, source_id, now)
            if paused_until is not None:
                raise ApifyActorRouteError(
                    "apify_actor_target_paused",
                    "The X profile subscription is temporarily paused",
                    retryable=True,
                    retry_at=paused_until,
                )
            active_group_attempt = connection.execute(
                """
                SELECT 1
                FROM apify_actor_attempts
                WHERE workspace_id = ? AND route_key = ?
                  AND (
                      attempt_group_id = ?
                      OR (
                          ? IS NOT NULL AND job_id = ? AND source_id = ?
                      )
                  )
                  AND status IN ('reserved', 'running')
                LIMIT 1
                """,
                (
                    self.workspace_id,
                    self.route_key,
                    attempt_group_id,
                    job_id,
                    job_id,
                    source_id,
                ),
            ).fetchone()
            if active_group_attempt is not None:
                raise ApifyActorRouteError(
                    "apify_actor_job_active",
                    "This task already has an active Actor Run",
                    retryable=True,
                )
            attempt_rows = connection.execute(
                """
                SELECT attempt.candidate_id, attempt.status,
                       attempt.semantic_outcome, attempt.reserved_usd,
                       attempt.actual_cost_usd,
                       EXISTS (
                           SELECT 1
                           FROM apify_actor_runs AS run
                           WHERE run.workspace_id = attempt.workspace_id
                             AND run.logical_run_id = attempt.id
                             AND (
                                 run.remote_run_id IS NOT NULL
                                 OR run.status NOT IN (
                                     'start_rejected', 'cancelled'
                                 )
                                 OR (
                                     run.charge_final = 1
                                     AND COALESCE(run.charge_actual_usd, 0) > 0
                                 )
                             )
                       ) AS may_have_started
                FROM apify_actor_attempts AS attempt
                WHERE attempt.workspace_id = ? AND attempt.route_key = ?
                  AND (
                      attempt.attempt_group_id = ?
                      OR (
                          ? IS NOT NULL
                          AND attempt.job_id = ?
                          AND attempt.source_id = ?
                      )
                  )
                ORDER BY attempt.created_at, attempt.id
                """,
                (
                    self.workspace_id,
                    self.route_key,
                    attempt_group_id,
                    job_id,
                    job_id,
                    source_id,
                ),
            ).fetchall()
            charged_rows = [
                row
                for row in attempt_rows
                if _attempt_consumes_job_budget(row)
            ]
            spent = sum(
                float(row["reserved_usd"] or 0.0)
                for row in charged_rows
            )
            if (
                len(charged_rows) >= 3
                or spent + PER_RUN_RESERVATION_USD
                > PER_ATTEMPT_GROUP_LIMIT_USD + 1e-9
            ):
                raise ApifyActorRouteError(
                    "apify_actor_job_budget_exhausted",
                    "This task reached its Actor charge reservation limit",
                    retryable=False,
                )
            self._assert_route_charge_allowed(connection, route, now)
            excluded_candidate_ids.update(
                str(row["candidate_id"])
                for row in charged_rows
                if str(row["status"])
                in {
                    "actor_failed",
                    "succeeded",
                    "valid_empty",
                    "cancelled",
                }
            )
            candidate = self._choose_candidate(
                connection,
                route,
                now,
                excluded_candidate_ids,
                exclude_canary_busy=True,
            )
            if candidate is None:
                if self._has_canary_busy_candidate(connection, now):
                    raise ApifyActorRouteError(
                        "apify_actor_canary_active",
                        "An eligible Actor is temporarily reserved for a canary",
                        retryable=True,
                    )
                if not self._has_selectable_candidate(connection, now):
                    retry_at = self._next_retry_at(connection)
                    self._set_route_unavailable(
                        connection,
                        now,
                        retry_at=retry_at,
                        reason="all_candidates_unavailable",
                    )
                    raise ApifyActorRouteError(
                        "apify_actor_route_exhausted",
                        "No X profile Actor is currently available",
                        retryable=True,
                        retry_at=retry_at,
                    )
                raise ApifyActorRouteError(
                    "apify_actor_attempts_exhausted",
                    "No untried Actor remains for this task",
                    retryable=True,
                    retry_at=self._next_retry_at(connection),
                )
            lease = self._insert_attempt(
                connection,
                route,
                candidate,
                source_id=source_id,
                job_id=job_id,
                attempt_group_id=attempt_group_id,
                attempt_index=len(charged_rows) + 1,
                canary=False,
                now=now,
            )
            if candidate["state"] == "half_open":
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET probe_claimed_at = ?, last_attempt_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (now.isoformat(), now.isoformat(), now.isoformat(), candidate["id"]),
                )
            self._commit(connection, owns_transaction)
            return lease
        except ApifyActorRouteError:
            self._commit(connection, owns_transaction)
            raise
        except Exception:
            self._rollback(connection, owns_transaction)
            raise

    def _attempt_group_id(
        self,
        *,
        source_id: str,
        job_id: str | None,
    ) -> str:
        if not job_id:
            return f"route-{uuid.uuid4().hex}"
        existing = self.store.connect().execute(
            """
            SELECT attempt_group_id
            FROM apify_actor_attempts
            WHERE workspace_id = ? AND route_key = ?
              AND source_id = ? AND job_id = ?
            ORDER BY created_at, id
            LIMIT 1
            """,
            (self.workspace_id, self.route_key, source_id, job_id),
        ).fetchone()
        if existing is not None:
            return str(existing["attempt_group_id"])
        digest = hashlib.sha256(
            "\x1f".join(
                (
                    self.workspace_id,
                    self.route_key,
                    str(source_id),
                    str(job_id),
                )
            ).encode("utf-8")
        ).hexdigest()
        return f"job-{digest[:40]}"

    def _attempt_group_progress(
        self,
        attempt_group_id: str,
        *,
        source_id: str,
        job_id: str | None,
    ) -> dict[str, Any]:
        attempt_rows = self.store.connect().execute(
            """
            SELECT attempt.candidate_id, attempt.status,
                   attempt.semantic_outcome, attempt.reserved_usd,
                   attempt.actual_cost_usd,
                   EXISTS (
                       SELECT 1
                       FROM apify_actor_runs AS run
                       WHERE run.workspace_id = attempt.workspace_id
                         AND run.logical_run_id = attempt.id
                         AND (
                             run.remote_run_id IS NOT NULL
                             OR run.status NOT IN (
                                 'start_rejected', 'cancelled'
                             )
                             OR (
                                 run.charge_final = 1
                                 AND COALESCE(run.charge_actual_usd, 0) > 0
                             )
                         )
                   ) AS may_have_started
            FROM apify_actor_attempts AS attempt
            WHERE attempt.workspace_id = ? AND attempt.route_key = ?
              AND (
                  attempt.attempt_group_id = ?
                  OR (
                      ? IS NOT NULL
                      AND attempt.job_id = ?
                      AND attempt.source_id = ?
                  )
              )
            ORDER BY attempt.created_at, attempt.id
            """,
            (
                self.workspace_id,
                self.route_key,
                attempt_group_id,
                job_id,
                job_id,
                source_id,
            ),
        ).fetchall()
        rows = [
            row
            for row in attempt_rows
            if _attempt_consumes_job_budget(row)
        ]
        return {
            "charged_attempts": len(rows),
            "reserved_spend_usd": sum(
                float(row["reserved_usd"] or 0.0)
                for row in rows
            ),
            "excluded_candidate_ids": {
                str(row["candidate_id"])
                for row in rows
                if str(row["status"])
                in {
                    "actor_failed",
                    "succeeded",
                    "valid_empty",
                    "cancelled",
                }
            },
        }

    def mark_running(self, lease: ApifyActorCandidateLease) -> None:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE apify_actor_attempts
                SET status = 'running', started_at = COALESCE(started_at, ?),
                    updated_at = ?
                WHERE id = ? AND status = 'reserved'
                """,
                (now_iso, now_iso, lease.attempt_id),
            )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise

    def cancel_attempt(
        self,
        lease: ApifyActorCandidateLease,
        *,
        error_code: str,
    ) -> None:
        self._finish_attempt(
            lease,
            status="cancelled",
            semantic_outcome=None,
            error_code=error_code,
            actual_cost_usd=None,
            cost_final=False,
        )

    def record_start_outcome_unknown(
        self,
        lease: ApifyActorCandidateLease,
        *,
        error_code: str = "apify_start_outcome_unknown",
    ) -> None:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            if not self._finish_attempt_in_transaction(
                connection,
                lease,
                status="start_outcome_unknown",
                semantic_outcome=error_code,
                error_code=error_code,
                actual_cost_usd=None,
                cost_final=False,
                now=now,
            ):
                self._commit(connection, owns_transaction)
                return
            route = self._route_row(connection)
            self._write_route_change(
                connection,
                route,
                now,
                active_candidate_id=route["active_candidate_id"],
                status="blocked",
                reason=error_code,
                blocked_reason=error_code,
            )
            self._commit(connection, owns_transaction)
        except Exception:
            self._rollback(connection, owns_transaction)
            raise

    def record_run_reconcile_required(
        self,
        lease: ApifyActorCandidateLease,
    ) -> None:
        """Keep a durable remote Run resumable while blocking fresh charges."""

        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            connection.execute(
                """
                UPDATE apify_actor_attempts
                SET status = 'running',
                    semantic_outcome = 'apify_run_reconcile_required',
                    last_error_code = 'apify_run_reconcile_required',
                    terminal_at = NULL, updated_at = ?
                WHERE id = ? AND status IN ('reserved', 'running')
                """,
                (now.isoformat(), lease.attempt_id),
            )
            route = self._route_row(connection)
            adopt_generation = int(route["generation"])
            if (
                route["status"] != "blocked"
                or route["blocked_reason"] != "apify_run_reconcile_required"
            ):
                self._write_route_change(
                    connection,
                    route,
                    now,
                    active_candidate_id=route["active_candidate_id"],
                    status="blocked",
                    reason="apify_run_reconcile_required",
                    blocked_reason="apify_run_reconcile_required",
                )
            if adopt_generation == int(lease.route_generation):
                connection.execute(
                    """
                    UPDATE apify_actor_attempts
                    SET route_generation = ?, updated_at = ?
                    WHERE id = ? AND route_generation = ?
                      AND status = 'running'
                    """,
                    (
                        int(self._route_row(connection)["generation"]),
                        now.isoformat(),
                        lease.attempt_id,
                        adopt_generation,
                    ),
                )
            self._commit(connection, owns_transaction)
        except Exception:
            self._rollback(connection, owns_transaction)
            raise

    def record_success(
        self,
        lease: ApifyActorCandidateLease,
        *,
        semantic_outcome: str,
        actual_cost_usd: float | None,
        cost_final: bool,
    ) -> int:
        if semantic_outcome not in {"valid_nonempty", "valid_empty"}:
            raise ValueError("semantic_outcome must be valid_nonempty or valid_empty")
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            if self._settle_route_generation_conflict(
                connection,
                lease,
                actual_cost_usd=actual_cost_usd,
                cost_final=cost_final,
                now=now,
            ):
                self._commit(connection, owns_transaction)
                raise ApifyActorRouteConflictError()
            status = "succeeded" if semantic_outcome == "valid_nonempty" else "valid_empty"
            if not self._finish_attempt_in_transaction(
                connection,
                lease,
                status=status,
                semantic_outcome=semantic_outcome,
                error_code=None,
                actual_cost_usd=actual_cost_usd,
                cost_final=cost_final,
                now=now,
            ):
                final_generation = int(self._route_row(connection)["generation"])
                self._commit(connection, owns_transaction)
                return final_generation
            candidate = self._candidate_row(connection, lease.candidate_id)
            recovery_successes = int(candidate["recovery_successes"] or 0)
            next_state = str(candidate["state"])
            probation_started_at: str | None = None
            if (
                lease.canary
                and next_state == "disabled"
                and semantic_outcome == "valid_nonempty"
            ):
                enabled_sources = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM source_catalog
                    WHERE workspace_id = ? AND enabled = 1
                      AND type = 'apify_social'
                      AND lower(
                          COALESCE(
                              json_extract(config_json, '$.platform'),
                              ''
                          )
                      ) = 'x'
                      AND lower(
                          COALESCE(
                              json_extract(config_json, '$.kind'),
                              'profile'
                          )
                      ) = 'profile'
                    """,
                    (self.workspace_id,),
                ).fetchone()
                required_sources = max(
                    1,
                    min(2, int(enabled_sources["count"] or 0)),
                )
                successful_sources = connection.execute(
                    """
                    SELECT COUNT(DISTINCT source_id) AS count
                    FROM apify_actor_attempts
                    WHERE workspace_id = ? AND route_key = ?
                      AND candidate_id = ?
                      AND attempt_group_id LIKE 'canary-%'
                      AND status = 'succeeded'
                      AND semantic_outcome = 'valid_nonempty'
                      AND source_id IS NOT NULL
                    """,
                    (
                        self.workspace_id,
                        self.route_key,
                        lease.candidate_id,
                    ),
                ).fetchone()
                if int(successful_sources["count"] or 0) >= required_sources:
                    next_state = "probationary"
                    probation_started_at = now.isoformat()
            if next_state == "half_open":
                if semantic_outcome == "valid_nonempty":
                    recovery_successes += 1
                    if recovery_successes >= HALF_OPEN_RECOVERY_SUCCESSES:
                        next_state = "closed"
                        recovery_successes = 0
                else:
                    # Recovery requires two consecutive real-post results.
                    # A legitimate empty result is healthy for normal routing,
                    # but cannot prove that a previously broken Actor recovered.
                    recovery_successes = 0
            probe_claimed_at = (
                now.isoformat() if next_state == "half_open" else None
            )
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET state = ?, recovery_successes = ?, probe_claimed_at = ?,
                    retry_at = CASE WHEN ? = 'closed' THEN NULL ELSE retry_at END,
                    failure_level = CASE WHEN ? = 'closed' THEN 0
                        ELSE failure_level END,
                    probation_started_at = COALESCE(?, probation_started_at),
                    success_count = success_count + 1,
                    last_attempt_at = ?, last_success_at = ?,
                    last_error_code = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    next_state,
                    recovery_successes,
                    probe_claimed_at,
                    next_state,
                    next_state,
                    probation_started_at,
                    now.isoformat(),
                    now.isoformat(),
                    (
                        "canary_required"
                        if next_state == "disabled"
                        else None
                    ),
                    now.isoformat(),
                    lease.candidate_id,
                ),
            )
            self._record_target_success(
                connection,
                lease,
                semantic_outcome,
                now,
            )
            self._evaluate_probation(connection, lease.candidate_id, now)
            self._release_reconcile_block_if_clear(connection, now)
            route = self._route_row(connection)
            if route["status"] == "exhausted":
                active = self._first_routable_candidate(connection, now)
                if active is not None:
                    self._write_route_change(
                        connection,
                        route,
                        now,
                        active_candidate_id=active["id"],
                        status="degraded",
                        reason="actor_recovered",
                    )
            elif (
                candidate["state"] == "disabled"
                and next_state == "probationary"
            ):
                self._bump_generation(
                    connection,
                    now,
                    reason="actor_canary_passed",
                )
            elif (
                candidate["state"] == "half_open"
                and next_state == "closed"
            ):
                unavailable = connection.execute(
                    """
                    SELECT COUNT(*) AS count
                    FROM apify_actor_candidates
                    WHERE workspace_id = ? AND route_key = ?
                      AND state NOT IN ('closed', 'probationary')
                    """,
                    (self.workspace_id, self.route_key),
                ).fetchone()
                if (
                    route["status"] == "degraded"
                    and int(unavailable["count"] or 0) == 0
                ):
                    self._write_route_change(
                        connection,
                        route,
                        now,
                        active_candidate_id=route["active_candidate_id"],
                        status="ready",
                        reason="actor_recovered",
                    )
                else:
                    self._bump_generation(
                        connection,
                        now,
                        reason="actor_recovered",
                    )
            if (
                lease.canary
                and semantic_outcome == "valid_nonempty"
                and int(self._route_row(connection)["generation"])
                == int(route["generation"])
            ):
                self._bump_generation(
                    connection,
                    now,
                    reason="actor_canary_passed",
                )
            final_generation = int(self._route_row(connection)["generation"])
            connection.execute(
                """
                UPDATE apify_actor_attempts
                SET route_generation = ?, updated_at = ?
                WHERE id = ?
                """,
                (final_generation, now.isoformat(), lease.attempt_id),
            )
            self._commit(connection, owns_transaction)
            return final_generation
        except Exception:
            self._rollback(connection, owns_transaction)
            raise

    def record_suspicious_empty(
        self,
        lease: ApifyActorCandidateLease,
        *,
        actual_cost_usd: float | None,
        cost_final: bool,
    ) -> tuple[bool, int]:
        """Correlate raw-empty datasets across previously healthy targets."""

        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            if self._settle_route_generation_conflict(
                connection,
                lease,
                actual_cost_usd=actual_cost_usd,
                cost_final=cost_final,
                now=now,
            ):
                self._commit(connection, owns_transaction)
                raise ApifyActorRouteConflictError()
            candidate = self._candidate_row(connection, lease.candidate_id)
            health = (
                connection.execute(
                    """
                    SELECT had_valid_nonempty
                    FROM apify_actor_target_health
                    WHERE workspace_id = ? AND route_key = ?
                      AND candidate_id = ? AND source_id = ?
                    """,
                    (
                        self.workspace_id,
                        self.route_key,
                        lease.candidate_id,
                        lease.source_id,
                    ),
                ).fetchone()
                if lease.source_id
                else None
            )
            previously_healthy = bool(
                health is not None and health["had_valid_nonempty"]
            )
            if not previously_healthy:
                if not self._finish_attempt_in_transaction(
                    connection,
                    lease,
                    status="valid_empty",
                    semantic_outcome="suspicious_empty",
                    error_code=None,
                    actual_cost_usd=actual_cost_usd,
                    cost_final=cost_final,
                    now=now,
                ):
                    generation = int(self._route_row(connection)["generation"])
                    self._commit(connection, owns_transaction)
                    return False, generation
                probe_claimed_at = (
                    now.isoformat()
                    if candidate["state"] == "half_open"
                    else None
                )
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET success_count = success_count + 1,
                        recovery_successes = CASE
                            WHEN state = 'half_open' THEN 0
                            ELSE recovery_successes END,
                        probe_claimed_at = ?, last_attempt_at = ?,
                        last_success_at = ?, last_error_code = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        probe_claimed_at,
                        now.isoformat(),
                        now.isoformat(),
                        now.isoformat(),
                        lease.candidate_id,
                    ),
                )
                self._record_target_success(
                    connection,
                    lease,
                    "valid_empty",
                    now,
                )
                generation = int(self._route_row(connection)["generation"])
                connection.execute(
                    """
                    UPDATE apify_actor_attempts
                    SET route_generation = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (generation, now.isoformat(), lease.attempt_id),
                )
                self._commit(connection, owns_transaction)
                return False, generation

            self._record_actor_failure_evidence(
                connection,
                lease,
                "apify_actor_unexpected_empty",
                now,
            )
            should_open = (
                candidate["state"] == "half_open"
                or self._systemic_failure_count(
                    connection,
                    lease.candidate_id,
                    now,
                )
                >= 2
            )
            status = "actor_failed" if should_open else "valid_empty"
            if not self._finish_attempt_in_transaction(
                connection,
                lease,
                status=status,
                semantic_outcome="apify_actor_unexpected_empty",
                error_code=(
                    "apify_actor_unexpected_empty" if should_open else None
                ),
                actual_cost_usd=actual_cost_usd,
                cost_final=cost_final,
                now=now,
            ):
                generation = int(self._route_row(connection)["generation"])
                self._commit(connection, owns_transaction)
                return should_open, generation
            connection.execute(
                """
                UPDATE apify_actor_candidates
                SET failure_count = failure_count + ?,
                    last_attempt_at = ?, last_failure_at = ?,
                    last_error_code = ?, probe_claimed_at = NULL,
                    updated_at = ?
                WHERE id = ?
                """,
                (
                    int(should_open),
                    now.isoformat(),
                    now.isoformat(),
                    (
                        "apify_actor_unexpected_empty"
                        if should_open
                        else candidate["last_error_code"]
                    ),
                    now.isoformat(),
                    lease.candidate_id,
                ),
            )
            if should_open:
                self._open_candidate(
                    connection,
                    candidate,
                    now,
                    reason="apify_actor_unexpected_empty",
                )
                self._ensure_active_candidate(
                    connection,
                    now,
                    reason="apify_actor_unexpected_empty",
                )
                if self._failed_spend(connection, now) >= FAILED_SPEND_LIMIT_USD:
                    self._engage_budget_fuse(connection, now)
            generation = int(self._route_row(connection)["generation"])
            connection.execute(
                """
                UPDATE apify_actor_attempts
                SET route_generation = ?, updated_at = ?
                WHERE id = ?
                """,
                (generation, now.isoformat(), lease.attempt_id),
            )
            self._commit(connection, owns_transaction)
            return should_open, generation
        except Exception:
            self._rollback(connection, owns_transaction)
            raise

    def record_failure(
        self,
        lease: ApifyActorCandidateLease,
        *,
        failure_scope: str,
        semantic_outcome: str,
        error_code: str,
        actual_cost_usd: float | None,
        cost_final: bool,
    ) -> None:
        if failure_scope not in {"actor", "target"}:
            raise ValueError("failure_scope must be actor or target")
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            if self._settle_route_generation_conflict(
                connection,
                lease,
                actual_cost_usd=actual_cost_usd,
                cost_final=cost_final,
                now=now,
            ):
                self._commit(connection, owns_transaction)
                raise ApifyActorRouteConflictError()
            status = "actor_failed" if failure_scope == "actor" else "target_failed"
            if not self._finish_attempt_in_transaction(
                connection,
                lease,
                status=status,
                semantic_outcome=semantic_outcome,
                error_code=error_code,
                actual_cost_usd=actual_cost_usd,
                cost_final=cost_final,
                now=now,
            ):
                self._commit(connection, owns_transaction)
                return
            candidate = self._candidate_row(connection, lease.candidate_id)
            should_open = False
            if failure_scope == "target":
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET last_attempt_at = ?, probe_claimed_at = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (now.isoformat(), now.isoformat(), lease.candidate_id),
                )
                self._record_target_failure(
                    connection,
                    lease,
                    semantic_outcome,
                    now,
                )
            else:
                connection.execute(
                    """
                    UPDATE apify_actor_candidates
                    SET failure_count = failure_count + 1,
                        last_attempt_at = ?, last_failure_at = ?,
                        last_error_code = ?, probe_claimed_at = NULL,
                        updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        now.isoformat(),
                        now.isoformat(),
                        error_code,
                        now.isoformat(),
                        lease.candidate_id,
                    ),
                )
                self._record_actor_failure_evidence(
                    connection,
                    lease,
                    semantic_outcome,
                    now,
                )
                severe_contract_failure = error_code in {
                    "apify_actor_contract_mismatch",
                    "apify_actor_deleted",
                    "apify_actor_build_unavailable",
                }
                should_open = (
                    candidate["state"] != "disabled"
                    and (
                        candidate["state"] == "half_open"
                        or severe_contract_failure
                        or self._systemic_failure_count(
                            connection,
                            lease.candidate_id,
                            now,
                        )
                        >= 2
                    )
                )
                if should_open:
                    self._open_candidate(
                        connection,
                        candidate,
                        now,
                        reason=error_code,
                    )
            self._evaluate_probation(connection, lease.candidate_id, now)
            self._release_reconcile_block_if_clear(connection, now)
            if self._failed_spend(connection, now) >= FAILED_SPEND_LIMIT_USD:
                self._engage_budget_fuse(connection, now)
            elif should_open:
                self._ensure_active_candidate(connection, now, reason=error_code)
            connection.execute(
                """
                UPDATE apify_actor_attempts
                SET route_generation = ?, updated_at = ?
                WHERE id = ?
                """,
                (
                    int(self._route_row(connection)["generation"]),
                    now.isoformat(),
                    lease.attempt_id,
                ),
            )
            self._commit(connection, owns_transaction)
        except Exception:
            self._rollback(connection, owns_transaction)
            raise

    def _finish_attempt(
        self,
        lease: ApifyActorCandidateLease,
        *,
        status: str,
        semantic_outcome: str | None,
        error_code: str | None,
        actual_cost_usd: float | None,
        cost_final: bool,
    ) -> None:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            self._finish_attempt_in_transaction(
                connection,
                lease,
                status=status,
                semantic_outcome=semantic_outcome,
                error_code=error_code,
                actual_cost_usd=actual_cost_usd,
                cost_final=cost_final,
                now=self._current_time(),
            )
            self._commit(connection, owns_transaction)
        except Exception:
            self._rollback(connection, owns_transaction)
            raise

    def _finish_attempt_in_transaction(
        self,
        connection: sqlite3.Connection,
        lease: ApifyActorCandidateLease,
        *,
        status: str,
        semantic_outcome: str | None,
        error_code: str | None,
        actual_cost_usd: float | None,
        cost_final: bool,
        now: datetime,
    ) -> bool:
        if status not in _TERMINAL_ATTEMPT_STATUSES:
            raise ValueError("invalid terminal attempt status")
        row = connection.execute(
            """
            SELECT status, candidate_id, route_generation,
                   actual_cost_usd, cost_final
            FROM apify_actor_attempts WHERE id = ?
            """,
            (lease.attempt_id,),
        ).fetchone()
        if row is None:
            raise LookupError("Actor attempt not found")
        if (
            str(row["candidate_id"]) != lease.candidate_id
            or int(row["route_generation"]) != lease.route_generation
        ):
            raise ApifyActorRouteConflictError()
        if row["status"] in _TERMINAL_ATTEMPT_STATUSES:
            actual = _safe_cost(actual_cost_usd)
            actual, aggregated_final = self._aggregate_key_run_cost(
                connection,
                lease.attempt_id,
                fallback_actual=actual,
                fallback_final=bool(cost_final and actual is not None),
            )
            effective_actual = (
                actual
                if actual is not None
                else _safe_cost(row["actual_cost_usd"])
            )
            effective_final = bool(
                row["cost_final"]
                or (aggregated_final and effective_actual is not None)
            )
            if effective_actual is not None:
                connection.execute(
                    """
                    UPDATE apify_actor_attempts
                    SET actual_cost_usd = ?, cost_final = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        effective_actual,
                        int(effective_final),
                        now.isoformat(),
                        lease.attempt_id,
                    ),
                )
            return False
        actual = _safe_cost(actual_cost_usd)
        actual, cost_final = self._aggregate_key_run_cost(
            connection,
            lease.attempt_id,
            fallback_actual=actual,
            fallback_final=bool(cost_final and actual is not None),
        )
        connection.execute(
            """
            UPDATE apify_actor_attempts
            SET status = ?, semantic_outcome = ?, actual_cost_usd = ?,
                cost_final = ?, last_error_code = ?, terminal_at = ?,
                updated_at = ?
            WHERE id = ?
            """,
            (
                status,
                semantic_outcome,
                actual,
                int(bool(cost_final and actual is not None)),
                error_code,
                now.isoformat(),
                now.isoformat(),
                lease.attempt_id,
            ),
        )
        return True

    def _settle_route_generation_conflict(
        self,
        connection: sqlite3.Connection,
        lease: ApifyActorCandidateLease,
        *,
        actual_cost_usd: float | None,
        cost_final: bool,
        now: datetime,
    ) -> bool:
        if int(self._route_row(connection)["generation"]) == int(
            lease.route_generation
        ):
            return False
        self._finish_attempt_in_transaction(
            connection,
            lease,
            status="cancelled",
            semantic_outcome="apify_actor_route_generation_conflict",
            error_code="apify_actor_route_generation_conflict",
            actual_cost_usd=actual_cost_usd,
            cost_final=cost_final,
            now=now,
        )
        connection.execute(
            """
            UPDATE apify_actor_candidates
            SET probe_claimed_at = NULL, updated_at = ?
            WHERE id = ?
            """,
            (now.isoformat(), lease.candidate_id),
        )
        self._release_reconcile_block_if_clear(connection, now)
        return True

    @staticmethod
    def _aggregate_key_run_cost(
        connection: sqlite3.Connection,
        logical_run_id: str,
        *,
        fallback_actual: float | None,
        fallback_final: bool,
    ) -> tuple[float | None, bool]:
        """Aggregate every credential attempt belonging to one Actor attempt."""

        rows = connection.execute(
            """
            SELECT status, remote_run_id, charge_actual_usd, charge_final
            FROM apify_actor_runs
            WHERE logical_run_id = ?
            ORDER BY created_at, id
            """,
            (logical_run_id,),
        ).fetchall()
        if not rows:
            return fallback_actual, fallback_final

        total = 0.0
        observed_amount = False
        all_final = True
        for row in rows:
            if bool(row["charge_final"]):
                total += float(row["charge_actual_usd"] or 0.0)
                observed_amount = True
                continue
            explicit_no_start = (
                str(row["status"]) in {"start_rejected", "cancelled"}
                and not row["remote_run_id"]
            )
            if not explicit_no_start:
                all_final = False
        if all_final:
            return total, True
        if observed_amount:
            return total, False
        return fallback_actual, False

    def _normalize_invocation_result(
        self,
        value: Any,
    ) -> ApifyActorInvocationResult[Any]:
        if isinstance(value, ApifyActorInvocationResult):
            result = value
        elif hasattr(value, "semantic_outcome"):
            result = ApifyActorInvocationResult(
                value=getattr(value, "value", getattr(value, "items", value)),
                semantic_outcome=str(getattr(value, "semantic_outcome")),
                actual_cost_usd=getattr(
                    value,
                    "actual_cost_usd",
                    getattr(value, "actual_charge_usd", None),
                ),
                cost_final=bool(getattr(value, "cost_final", False)),
            )
        else:
            raise TypeError("Actor invocation must return a semantic outcome")
        if result.semantic_outcome not in {
            "valid_nonempty",
            "valid_empty",
            "suspicious_empty",
        }:
            raise ValueError("Actor invocation returned an invalid semantic outcome")
        return ApifyActorInvocationResult(
            value=result.value,
            semantic_outcome=result.semantic_outcome,
            actual_cost_usd=_safe_cost(result.actual_cost_usd),
            cost_final=bool(
                result.cost_final and _safe_cost(result.actual_cost_usd) is not None
            ),
        )

    @staticmethod
    def _is_key_pool_failure(code: str, exc: Exception) -> bool:
        status_code = getattr(exc, "status_code", None)
        return (
            code.startswith("apify_key_")
            or code.startswith("apify_quota_")
            or code in {
                "apify_pool_empty",
                "apify_pool_exhausted",
                "apify_pool_blocked",
            }
            or status_code in {401, 402}
        )

    @staticmethod
    def _is_actor_transport_failure(code: str, exc: Exception) -> bool:
        if code in {
            "apify_actor_deleted",
            "apify_actor_build_unavailable",
            "apify_actor_start_rejected",
            "apify_dataset_unavailable",
            "apify_run_status_unavailable",
        }:
            return True
        return isinstance(exc, (TimeoutError, ValueError))

    def _insert_attempt(
        self,
        connection: sqlite3.Connection,
        route: sqlite3.Row,
        candidate: sqlite3.Row,
        *,
        source_id: str | None,
        job_id: str | None,
        attempt_group_id: str,
        attempt_index: int,
        canary: bool,
        now: datetime,
    ) -> ApifyActorCandidateLease:
        attempt_id = f"apify-attempt-{uuid.uuid4().hex}"
        connection.execute(
            """
            INSERT INTO apify_actor_attempts (
                id, workspace_id, route_key, route_generation,
                candidate_id, source_id, job_id, attempt_group_id,
                attempt_index, status, semantic_outcome, reserved_usd,
                cost_final, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'reserved', ?, ?, 0, ?, ?)
            """,
            (
                attempt_id,
                self.workspace_id,
                self.route_key,
                int(route["generation"]),
                candidate["id"],
                source_id,
                job_id,
                attempt_group_id,
                attempt_index,
                "canary_reserved" if canary else None,
                PER_RUN_RESERVATION_USD,
                now.isoformat(),
                now.isoformat(),
            ),
        )
        return ApifyActorCandidateLease(
            attempt_id=attempt_id,
            attempt_group_id=attempt_group_id,
            route_generation=int(route["generation"]),
            candidate_id=str(candidate["id"]),
            actor_id=str(candidate["actor_id"]),
            adapter_key=str(candidate["adapter_key"]),
            source_id=source_id,
            job_id=job_id,
            attempt_index=attempt_index,
            canary=canary,
        )

    def _candidate_row(
        self,
        connection: sqlite3.Connection,
        candidate_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            """
            SELECT * FROM apify_actor_candidates
            WHERE id = ? AND workspace_id = ? AND route_key = ?
            """,
            (candidate_id, self.workspace_id, self.route_key),
        ).fetchone()
        if row is None:
            raise LookupError("Actor candidate not found")
        return row

    def _assert_generation(
        self,
        connection: sqlite3.Connection,
        expected_generation: int,
    ) -> sqlite3.Row:
        route = self._route_row(connection)
        if int(route["generation"]) != int(expected_generation):
            raise ApifyActorRouteConflictError()
        return route

    def _choose_candidate(
        self,
        connection: sqlite3.Connection,
        route: sqlite3.Row,
        now: datetime,
        excluded_candidate_ids: set[str],
        *,
        exclude_canary_busy: bool = False,
    ) -> sqlite3.Row | None:
        rows = connection.execute(
            """
            SELECT * FROM apify_actor_candidates
            WHERE workspace_id = ? AND route_key = ?
              AND state IN ('closed', 'probationary', 'half_open')
            ORDER BY
              CASE WHEN state = 'half_open' THEN 0 ELSE 1 END,
              CASE WHEN id = ? THEN 0 ELSE 1 END,
              position, id
            """,
            (
                self.workspace_id,
                self.route_key,
                route["active_candidate_id"] or "",
            ),
        ).fetchall()
        for row in rows:
            candidate_id = str(row["id"])
            if candidate_id in excluded_candidate_ids:
                continue
            if (
                exclude_canary_busy
                and self._candidate_has_active_canary(
                    connection,
                    candidate_id,
                )
            ):
                continue
            if row["state"] == "half_open":
                claimed_at = _parse_time(row["probe_claimed_at"])
                if claimed_at is not None and claimed_at > now - timedelta(hours=1):
                    continue
            return row
        return None

    def _has_selectable_candidate(
        self,
        connection: sqlite3.Connection,
        now: datetime,
        *,
        exclude_canary_busy: bool = False,
    ) -> bool:
        route = self._route_row(connection)
        return (
            self._choose_candidate(
                connection,
                route,
                now,
                set(),
                exclude_canary_busy=exclude_canary_busy,
            )
            is not None
        )

    def _candidate_has_active_canary(
        self,
        connection: sqlite3.Connection,
        candidate_id: str,
    ) -> bool:
        active_attempt = connection.execute(
            """
            SELECT 1
            FROM apify_actor_attempts
            WHERE workspace_id = ? AND route_key = ?
              AND candidate_id = ?
              AND attempt_group_id LIKE 'canary-%'
              AND status IN ('reserved', 'running')
            LIMIT 1
            """,
            (self.workspace_id, self.route_key, candidate_id),
        ).fetchone()
        if active_attempt is not None:
            return True
        queued_job = connection.execute(
            """
            SELECT 1
            FROM fetch_jobs
            WHERE workspace_id = ? AND job_type = 'source_test'
              AND status IN ('queued', 'running')
              AND json_extract(payload_json, '$.reason')
                  = 'apify_actor_canary'
              AND json_extract(
                  payload_json,
                  '$.apify_actor_candidate_id'
              ) = ?
            LIMIT 1
            """,
            (self.workspace_id, candidate_id),
        ).fetchone()
        return queued_job is not None

    def _has_canary_busy_candidate(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> bool:
        route = self._route_row(connection)
        rows = connection.execute(
            """
            SELECT id
            FROM apify_actor_candidates
            WHERE workspace_id = ? AND route_key = ?
              AND state IN ('closed', 'probationary', 'half_open')
            """,
            (self.workspace_id, self.route_key),
        ).fetchall()
        return any(
            self._candidate_has_active_canary(connection, str(row["id"]))
            for row in rows
        ) and self._choose_candidate(
            connection,
            route,
            now,
            set(),
        ) is not None

    def _assert_canary_candidate_idle(
        self,
        connection: sqlite3.Connection,
        candidate_id: str,
        *,
        job_id: str | None,
    ) -> None:
        active_attempt = connection.execute(
            """
            SELECT 1
            FROM apify_actor_attempts
            WHERE workspace_id = ? AND route_key = ?
              AND candidate_id = ?
              AND status IN ('reserved', 'running')
            LIMIT 1
            """,
            (self.workspace_id, self.route_key, candidate_id),
        ).fetchone()
        other_canary_job = connection.execute(
            """
            SELECT 1
            FROM fetch_jobs
            WHERE workspace_id = ? AND job_type = 'source_test'
              AND status IN ('queued', 'running')
              AND json_extract(payload_json, '$.reason')
                  = 'apify_actor_canary'
              AND json_extract(
                  payload_json,
                  '$.apify_actor_candidate_id'
              ) = ?
              AND (? IS NULL OR id != ?)
            LIMIT 1
            """,
            (self.workspace_id, candidate_id, job_id, job_id),
        ).fetchone()
        if active_attempt is not None or other_canary_job is not None:
            raise ApifyActorRouteError(
                "apify_actor_canary_active",
                "The selected Actor already has an active paid invocation",
                retryable=True,
                status_code=409,
            )

    def _first_routable_candidate(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> sqlite3.Row | None:
        route = self._route_row(connection)
        return self._choose_candidate(connection, route, now, set())

    def _first_candidate_by_position(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> sqlite3.Row | None:
        """Return the first healthy candidate in administrator-defined order."""

        rows = connection.execute(
            """
            SELECT * FROM apify_actor_candidates
            WHERE workspace_id = ? AND route_key = ?
              AND state IN ('closed', 'probationary')
            ORDER BY position, id
            """,
            (self.workspace_id, self.route_key),
        ).fetchall()
        if rows:
            return rows[0]
        # A route with no established candidate may still expose one natural
        # half-open probe. Do not select an already-claimed probe as active.
        for row in connection.execute(
            """
            SELECT * FROM apify_actor_candidates
            WHERE workspace_id = ? AND route_key = ? AND state = 'half_open'
            ORDER BY position, id
            """,
            (self.workspace_id, self.route_key),
        ).fetchall():
            claimed_at = _parse_time(row["probe_claimed_at"])
            if claimed_at is None or claimed_at <= now - timedelta(hours=1):
                return row
        return None

    def _make_due_candidates_probeable(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> None:
        self._evaluate_due_probations(connection, now)
        connection.execute(
            """
            UPDATE apify_actor_candidates
            SET state = 'half_open', probe_claimed_at = NULL,
                recovery_successes = 0, updated_at = ?
            WHERE workspace_id = ? AND route_key = ? AND state = 'open'
              AND retry_at IS NOT NULL AND retry_at <= ?
            """,
            (
                now.isoformat(),
                self.workspace_id,
                self.route_key,
                now.isoformat(),
            ),
        )

    def _target_pause_until(
        self,
        connection: sqlite3.Connection,
        source_id: str | None,
        now: datetime,
    ) -> datetime | None:
        if not source_id:
            return None
        row = connection.execute(
            """
            SELECT MAX(paused_until) AS paused_until
            FROM apify_actor_target_health
            WHERE workspace_id = ? AND route_key = ? AND source_id = ?
              AND paused_until > ?
            """,
            (
                self.workspace_id,
                self.route_key,
                source_id,
                now.isoformat(),
            ),
        ).fetchone()
        return _parse_time(row["paused_until"] if row else None)

    def _record_target_success(
        self,
        connection: sqlite3.Connection,
        lease: ApifyActorCandidateLease,
        semantic_outcome: str,
        now: datetime,
    ) -> None:
        if not lease.source_id:
            return
        connection.execute(
            """
            INSERT INTO apify_actor_target_health (
                workspace_id, route_key, candidate_id, source_id,
                had_valid_nonempty, consecutive_failures,
                last_semantic_outcome, last_valid_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, 0, ?, ?, ?)
            ON CONFLICT(workspace_id, route_key, candidate_id, source_id)
            DO UPDATE SET
                had_valid_nonempty = MAX(
                    apify_actor_target_health.had_valid_nonempty,
                    excluded.had_valid_nonempty
                ),
                consecutive_failures = 0,
                last_semantic_outcome = excluded.last_semantic_outcome,
                last_valid_at = excluded.last_valid_at,
                paused_until = NULL,
                updated_at = excluded.updated_at
            """,
            (
                self.workspace_id,
                self.route_key,
                lease.candidate_id,
                lease.source_id,
                int(semantic_outcome == "valid_nonempty"),
                semantic_outcome,
                now.isoformat(),
                now.isoformat(),
            ),
        )

    def _record_target_failure(
        self,
        connection: sqlite3.Connection,
        lease: ApifyActorCandidateLease,
        semantic_outcome: str,
        now: datetime,
    ) -> None:
        if not lease.source_id:
            return
        existing = connection.execute(
            """
            SELECT consecutive_failures
            FROM apify_actor_target_health
            WHERE workspace_id = ? AND route_key = ?
              AND candidate_id = ? AND source_id = ?
            """,
            (
                self.workspace_id,
                self.route_key,
                lease.candidate_id,
                lease.source_id,
            ),
        ).fetchone()
        failures = int(existing["consecutive_failures"] or 0) + 1 if existing else 1
        paused_until = (
            (now + TARGET_PAUSE).isoformat() if failures >= 2 else None
        )
        connection.execute(
            """
            INSERT INTO apify_actor_target_health (
                workspace_id, route_key, candidate_id, source_id,
                consecutive_failures, last_semantic_outcome,
                last_failure_at, paused_until, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(workspace_id, route_key, candidate_id, source_id)
            DO UPDATE SET
                consecutive_failures = excluded.consecutive_failures,
                last_semantic_outcome = excluded.last_semantic_outcome,
                last_failure_at = excluded.last_failure_at,
                paused_until = excluded.paused_until,
                updated_at = excluded.updated_at
            """,
            (
                self.workspace_id,
                self.route_key,
                lease.candidate_id,
                lease.source_id,
                failures,
                semantic_outcome,
                now.isoformat(),
                paused_until,
                now.isoformat(),
            ),
        )

    def _record_actor_failure_evidence(
        self,
        connection: sqlite3.Connection,
        lease: ApifyActorCandidateLease,
        semantic_outcome: str,
        now: datetime,
    ) -> None:
        if not lease.source_id:
            return
        connection.execute(
            """
            INSERT INTO apify_actor_target_health (
                workspace_id, route_key, candidate_id, source_id,
                consecutive_failures, last_semantic_outcome,
                last_failure_at, updated_at
            ) VALUES (?, ?, ?, ?, 0, ?, ?, ?)
            ON CONFLICT(workspace_id, route_key, candidate_id, source_id)
            DO UPDATE SET
                last_semantic_outcome = excluded.last_semantic_outcome,
                last_failure_at = excluded.last_failure_at,
                updated_at = excluded.updated_at
            """,
            (
                self.workspace_id,
                self.route_key,
                lease.candidate_id,
                lease.source_id,
                semantic_outcome,
                now.isoformat(),
                now.isoformat(),
            ),
        )

    def _systemic_failure_count(
        self,
        connection: sqlite3.Connection,
        candidate_id: str,
        now: datetime,
    ) -> int:
        row = connection.execute(
            """
            SELECT COUNT(DISTINCT source_id) AS count
            FROM apify_actor_target_health
            WHERE workspace_id = ? AND route_key = ? AND candidate_id = ?
              AND had_valid_nonempty = 1
              AND last_failure_at >= ?
              AND last_semantic_outcome LIKE 'apify_actor_%'
            """,
            (
                self.workspace_id,
                self.route_key,
                candidate_id,
                (now - SYSTEMIC_FAILURE_WINDOW).isoformat(),
            ),
        ).fetchone()
        return int(row["count"] or 0)

    def _open_candidate(
        self,
        connection: sqlite3.Connection,
        candidate: sqlite3.Row,
        now: datetime,
        *,
        reason: str,
    ) -> None:
        failure_level = min(int(candidate["failure_level"] or 0) + 1, len(_COOLDOWNS))
        retry_at = now + _COOLDOWNS[failure_level - 1]
        connection.execute(
            """
            UPDATE apify_actor_candidates
            SET state = 'open', failure_level = ?, recovery_successes = 0,
                probe_claimed_at = NULL, opened_at = ?, retry_at = ?,
                last_failure_at = ?, last_error_code = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                failure_level,
                now.isoformat(),
                retry_at.isoformat(),
                now.isoformat(),
                reason,
                now.isoformat(),
                candidate["id"],
            ),
        )

    def _ensure_active_candidate(
        self,
        connection: sqlite3.Connection,
        now: datetime,
        *,
        reason: str,
    ) -> None:
        route = self._route_row(connection)
        active_id = route["active_candidate_id"]
        active = (
            self._candidate_row(connection, str(active_id))
            if active_id
            else None
        )
        if active is not None and active["state"] in {"closed", "probationary"}:
            if route["status"] == "ready":
                self._write_route_change(
                    connection,
                    route,
                    now,
                    active_candidate_id=active["id"],
                    status="degraded",
                    reason=reason,
                )
            return
        replacement = self._first_routable_candidate(connection, now)
        self._write_route_change(
            connection,
            route,
            now,
            active_candidate_id=replacement["id"] if replacement else None,
            status="degraded" if replacement else "exhausted",
            reason=reason,
        )

    def _evaluate_probation(
        self,
        connection: sqlite3.Connection,
        candidate_id: str,
        now: datetime,
    ) -> None:
        candidate = self._candidate_row(connection, candidate_id)
        if candidate["state"] != "probationary":
            return
        started_at = _parse_time(candidate["probation_started_at"])
        if started_at is None or now < started_at + PROBATION_WINDOW:
            return
        metrics = connection.execute(
            """
            SELECT
                SUM(CASE WHEN status = 'succeeded' THEN 1 ELSE 0 END) AS real_posts,
                COUNT(*) AS measured
            FROM apify_actor_attempts
            WHERE candidate_id = ? AND created_at >= ?
              AND status IN ('succeeded', 'valid_empty', 'actor_failed')
            """,
            (candidate_id, started_at.isoformat()),
        ).fetchone()
        measured = int(metrics["measured"] or 0)
        rate = (
            int(metrics["real_posts"] or 0) / measured
            if measured
            else 0.0
        )
        next_state = "closed" if rate >= PROBATION_SUCCESS_RATE else "disabled"
        generation_before = int(self._route_row(connection)["generation"])
        connection.execute(
            """
            UPDATE apify_actor_candidates
            SET state = ?, retry_at = NULL, probe_claimed_at = NULL,
                last_error_code = CASE WHEN ? = 'disabled'
                    THEN 'probation_failed' ELSE NULL END,
                updated_at = ?
            WHERE id = ?
            """,
            (next_state, next_state, now.isoformat(), candidate_id),
        )
        if next_state == "disabled":
            self._ensure_active_candidate(
                connection,
                now,
                reason="probation_failed",
            )
        if int(self._route_row(connection)["generation"]) == generation_before:
            self._bump_generation(
                connection,
                now,
                reason=(
                    "probation_passed"
                    if next_state == "closed"
                    else "probation_failed"
                ),
            )

    def _evaluate_due_probations(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> None:
        rows = connection.execute(
            """
            SELECT id
            FROM apify_actor_candidates
            WHERE workspace_id = ? AND route_key = ?
              AND state = 'probationary'
              AND probation_started_at IS NOT NULL
              AND probation_started_at <= ?
            ORDER BY position, id
            """,
            (
                self.workspace_id,
                self.route_key,
                (now - PROBATION_WINDOW).isoformat(),
            ),
        ).fetchall()
        for row in rows:
            self._evaluate_probation(connection, str(row["id"]), now)

    def _failed_spend(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> float:
        row = connection.execute(
            """
            SELECT COALESCE(SUM(
                CASE WHEN cost_final = 1
                    THEN COALESCE(actual_cost_usd, 0)
                    ELSE reserved_usd END
            ), 0) AS spend
            FROM apify_actor_attempts
            WHERE workspace_id = ? AND route_key = ?
              AND terminal_at >= ?
              AND (
                  status IN (
                      'actor_failed', 'target_failed', 'start_outcome_unknown'
                  )
                  OR (
                      status = 'cancelled'
                      AND (
                          semantic_outcome IN (
                              'apify_actor_route_generation_conflict',
                              'apify_restart_key_run_reconciled'
                          )
                          OR actual_cost_usd > 0
                          OR EXISTS (
                              SELECT 1
                              FROM apify_actor_runs AS run
                              WHERE run.workspace_id =
                                  apify_actor_attempts.workspace_id
                                AND run.logical_run_id =
                                    apify_actor_attempts.id
                                AND (
                                    run.remote_run_id IS NOT NULL
                                    OR run.status NOT IN (
                                        'start_rejected', 'cancelled'
                                    )
                                    OR (
                                        run.charge_final = 1
                                        AND COALESCE(
                                            run.charge_actual_usd, 0
                                        ) > 0
                                    )
                                )
                          )
                      )
                  )
              )
            """,
            (
                self.workspace_id,
                self.route_key,
                (now - FAILED_SPEND_WINDOW).isoformat(),
            ),
        ).fetchone()
        return float(row["spend"] or 0.0)

    def _engage_budget_fuse(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> None:
        oldest = connection.execute(
            """
            SELECT MIN(terminal_at) AS terminal_at
            FROM apify_actor_attempts
            WHERE workspace_id = ? AND route_key = ?
              AND terminal_at >= ?
              AND (
                  status IN (
                      'actor_failed', 'target_failed', 'start_outcome_unknown'
                  )
                  OR (
                      status = 'cancelled'
                      AND (
                          semantic_outcome IN (
                              'apify_actor_route_generation_conflict',
                              'apify_restart_key_run_reconciled'
                          )
                          OR actual_cost_usd > 0
                          OR EXISTS (
                              SELECT 1
                              FROM apify_actor_runs AS run
                              WHERE run.workspace_id =
                                  apify_actor_attempts.workspace_id
                                AND run.logical_run_id =
                                    apify_actor_attempts.id
                                AND (
                                    run.remote_run_id IS NOT NULL
                                    OR run.status NOT IN (
                                        'start_rejected', 'cancelled'
                                    )
                                    OR (
                                        run.charge_final = 1
                                        AND COALESCE(
                                            run.charge_actual_usd, 0
                                        ) > 0
                                    )
                                )
                          )
                      )
                  )
              )
            """,
            (
                self.workspace_id,
                self.route_key,
                (now - FAILED_SPEND_WINDOW).isoformat(),
            ),
        ).fetchone()
        oldest_at = _parse_time(oldest["terminal_at"] if oldest else None) or now
        blocked_until = oldest_at + FAILED_SPEND_WINDOW
        route = self._route_row(connection)
        self._write_route_change(
            connection,
            route,
            now,
            active_candidate_id=route["active_candidate_id"],
            status="budget_blocked",
            reason="failed_spend_limit",
            budget_blocked_until=blocked_until,
            blocked_reason=None,
        )

    def _release_expired_budget_block(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> None:
        route = self._route_row(connection)
        if route["status"] != "budget_blocked":
            return
        blocked_until = _parse_time(route["budget_blocked_until"])
        if route["last_switch_reason"] == "quota_exhausted":
            quota = self._quota_state(connection, now)
            allocatable = quota["x_allocatable_usd"]
            if allocatable is None or allocatable < PER_RUN_RESERVATION_USD:
                return
        elif blocked_until is None or blocked_until > now:
            return
        active = None
        if route["active_candidate_id"]:
            current = self._candidate_row(
                connection,
                str(route["active_candidate_id"]),
            )
            if current["state"] in {"closed", "probationary"}:
                active = current
        if active is None:
            active = self._first_routable_candidate(connection, now)
        self._write_route_change(
            connection,
            route,
            now,
            active_candidate_id=active["id"] if active else None,
            status="degraded" if active else "exhausted",
            reason="budget_fuse_released",
            budget_blocked_until=None,
        )

    def _release_reconcile_block_if_clear(
        self,
        connection: sqlite3.Connection,
        now: datetime,
    ) -> None:
        route = self._route_row(connection)
        if (
            route["status"] != "blocked"
            or route["blocked_reason"] != "apify_run_reconcile_required"
        ):
            return
        pending = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM apify_actor_attempts
            WHERE workspace_id = ? AND route_key = ?
              AND status IN ('reserved', 'running')
              AND semantic_outcome IN (
                  'apify_restart_dataset_pending',
                  'apify_restart_run_reconcile_required',
                  'apify_run_reconcile_required'
              )
            """,
            (self.workspace_id, self.route_key),
        ).fetchone()
        if int(pending["count"] or 0):
            return
        active = None
        if route["active_candidate_id"]:
            current = self._candidate_row(
                connection,
                str(route["active_candidate_id"]),
            )
            if current["state"] in {"closed", "probationary"}:
                active = current
        if active is None:
            active = self._first_routable_candidate(connection, now)
        unavailable = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM apify_actor_candidates
            WHERE workspace_id = ? AND route_key = ?
              AND state IN ('open', 'half_open')
            """,
            (self.workspace_id, self.route_key),
        ).fetchone()
        status = (
            "exhausted"
            if active is None
            else "degraded"
            if int(unavailable["count"] or 0)
            else "ready"
        )
        self._write_route_change(
            connection,
            route,
            now,
            active_candidate_id=active["id"] if active else None,
            status=status,
            reason="run_reconciled",
            blocked_reason=None,
        )

    def _route_availability_status(
        self,
        connection: sqlite3.Connection,
        *,
        active_candidate: sqlite3.Row | None,
    ) -> str:
        if active_candidate is None:
            return "exhausted"
        unavailable = connection.execute(
            """
            SELECT COUNT(*) AS count
            FROM apify_actor_candidates
            WHERE workspace_id = ? AND route_key = ?
              AND state NOT IN ('closed', 'probationary')
            """,
            (self.workspace_id, self.route_key),
        ).fetchone()
        return "degraded" if int(unavailable["count"] or 0) else "ready"

    def _assert_route_charge_allowed(
        self,
        connection: sqlite3.Connection,
        route: sqlite3.Row,
        now: datetime,
    ) -> None:
        if route["status"] == "blocked":
            raise ApifyActorRouteBlockedError(
                str(route["blocked_reason"] or "apify_actor_route_blocked"),
                "X profile Actor routing is blocked pending Run reconciliation",
                retryable=False,
            )
        if route["status"] == "budget_blocked":
            raise ApifyActorRouteBlockedError(
                "apify_actor_budget_blocked",
                "X profile Actor routing is paused by the charge fuse",
                retryable=True,
                retry_at=_parse_time(route["budget_blocked_until"]),
            )
        outstanding_row = connection.execute(
            """
            SELECT COALESCE(SUM(reserved_usd), 0) AS reserved
            FROM apify_actor_attempts
            WHERE workspace_id = ? AND route_key = ?
              AND status IN ('reserved', 'running')
            """,
            (self.workspace_id, self.route_key),
        ).fetchone()
        outstanding = float(outstanding_row["reserved"] or 0.0)
        failed_spend = self._failed_spend(connection, now)
        if failed_spend >= FAILED_SPEND_LIMIT_USD:
            self._engage_budget_fuse(connection, now)
            refreshed = self._route_row(connection)
            raise ApifyActorRouteBlockedError(
                "apify_actor_budget_blocked",
                "X profile Actor routing is paused by the charge fuse",
                retryable=True,
                retry_at=_parse_time(refreshed["budget_blocked_until"]),
            )
        if (
            failed_spend + outstanding + PER_RUN_RESERVATION_USD
            > FAILED_SPEND_LIMIT_USD + 1e-9
        ):
            raise ApifyActorRouteBlockedError(
                "apify_actor_budget_blocked",
                "X profile Actor charge reservations are temporarily full",
                retryable=True,
            )
        quota = self._quota_state(connection, now)
        allocatable = quota["x_allocatable_usd"]
        if self._enforce_quota_admission and allocatable is None:
            raise ApifyActorRouteBlockedError(
                "apify_actor_quota_unknown",
                "Fresh quota snapshots are required before a paid Actor Run",
                retryable=True,
            )
        if (
            allocatable is not None
            and allocatable - outstanding + 1e-9 < PER_RUN_RESERVATION_USD
        ):
            retry_row = connection.execute(
                """
                SELECT MIN(cycle_end_at) AS retry_at
                FROM apify_key_pool_members
                WHERE workspace_id = ? AND cycle_end_at > ?
                """,
                (self.workspace_id, now.isoformat()),
            ).fetchone()
            retry_at = _parse_time(retry_row["retry_at"] if retry_row else None)
            self._write_route_change(
                connection,
                route,
                now,
                active_candidate_id=route["active_candidate_id"],
                status="budget_blocked",
                reason="quota_exhausted",
                budget_blocked_until=retry_at,
                blocked_reason=None,
            )
            raise ApifyActorRouteBlockedError(
                "apify_actor_budget_blocked",
                "X profile Actor routing has no allocatable Apify balance",
                retryable=True,
                retry_at=retry_at,
            )

    def _next_retry_at(
        self,
        connection: sqlite3.Connection,
    ) -> datetime | None:
        route = self._route_row(connection)
        route_retry = _parse_time(route["budget_blocked_until"])
        row = connection.execute(
            """
            SELECT MIN(retry_at) AS retry_at
            FROM apify_actor_candidates
            WHERE workspace_id = ? AND route_key = ?
              AND state = 'open' AND retry_at IS NOT NULL
            """,
            (self.workspace_id, self.route_key),
        ).fetchone()
        candidate_retry = _parse_time(row["retry_at"] if row else None)
        values = [value for value in (route_retry, candidate_retry) if value]
        return min(values) if values else None

    def _set_route_unavailable(
        self,
        connection: sqlite3.Connection,
        now: datetime,
        *,
        retry_at: datetime | None,
        reason: str,
    ) -> None:
        route = self._route_row(connection)
        if route["status"] in {"blocked", "budget_blocked"}:
            return
        if route["status"] == "exhausted" and route["active_candidate_id"] is None:
            return
        self._write_route_change(
            connection,
            route,
            now,
            active_candidate_id=None,
            status="exhausted",
            reason=reason,
        )

    def _write_route_change(
        self,
        connection: sqlite3.Connection,
        route: sqlite3.Row,
        now: datetime,
        *,
        active_candidate_id: Any,
        status: str,
        reason: str,
        budget_blocked_until: datetime | None | object = ...,
        blocked_reason: str | None | object = ...,
    ) -> None:
        budget_value = (
            route["budget_blocked_until"]
            if budget_blocked_until is ...
            else (
                budget_blocked_until.isoformat()
                if isinstance(budget_blocked_until, datetime)
                else None
            )
        )
        blocked_value = (
            route["blocked_reason"]
            if blocked_reason is ...
            else blocked_reason
        )
        previous_active = route["active_candidate_id"]
        previous_status = str(route["status"])
        next_generation = int(route["generation"]) + 1
        connection.execute(
            """
            UPDATE apify_actor_routes
            SET generation = generation + 1, status = ?,
                active_candidate_id = ?, last_switch_reason = ?,
                last_switch_at = ?, budget_blocked_until = ?,
                blocked_reason = ?, updated_at = ?
            WHERE workspace_id = ? AND route_key = ?
            """,
            (
                status,
                active_candidate_id,
                reason,
                now.isoformat(),
                budget_value,
                blocked_value,
                now.isoformat(),
                self.workspace_id,
                self.route_key,
            ),
        )
        payload = {
            "route": self.route_key,
            "generation": next_generation,
            "status": status,
            "candidate_id": active_candidate_id,
            "reason": reason,
        }
        if status == "blocked":
            self._pending_transitions.append(("start_outcome_unknown", payload))
        elif status == "budget_blocked":
            self._pending_transitions.append(("budget_blocked", payload))
        elif status == "exhausted":
            self._pending_transitions.append(("all_actors_unavailable", payload))
        if (
            previous_status in {"degraded", "exhausted", "budget_blocked", "blocked"}
            and status in {"ready", "degraded"}
        ):
            self._pending_transitions.append(("route_recovered", payload))
        if previous_active != active_candidate_id and active_candidate_id is not None:
            self._pending_transitions.append(("actor_switched", payload))

    def _bump_generation(
        self,
        connection: sqlite3.Connection,
        now: datetime,
        *,
        reason: str,
    ) -> None:
        connection.execute(
            """
            UPDATE apify_actor_routes
            SET generation = generation + 1, last_switch_reason = ?,
                last_switch_at = ?, updated_at = ?
            WHERE workspace_id = ? AND route_key = ?
            """,
            (
                reason,
                now.isoformat(),
                now.isoformat(),
                self.workspace_id,
                self.route_key,
            ),
        )
        if reason == "actor_recovered":
            route = self._route_row(connection)
            self._pending_transitions.append(
                (
                    "actor_recovered",
                    {
                        "route": self.route_key,
                        "generation": int(route["generation"]),
                        "status": str(route["status"]),
                        "candidate_id": route["active_candidate_id"],
                        "reason": reason,
                    },
                )
            )
