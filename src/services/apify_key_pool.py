"""Workspace-scoped Apify credential pool and run-generation barrier."""

from __future__ import annotations

import asyncio
import math
import os
import re
import sqlite3
import uuid
from collections.abc import Iterable
from dataclasses import dataclass, field
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..scrapers.apify_client import ApifyCredentialLease
from ..storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from .secret_store import SecretStore


POOL_QUOTA_MAX_AGE_SECONDS = 60
APIFY_RUN_TERMINAL_STATUSES = frozenset(
    {
        "succeeded",
        "failed",
        "aborted",
        "timed_out",
        "start_rejected",
        "cancelled",
    }
)
_NONTERMINAL_RUN_SQL = (
    "'reserved', 'starting', 'running', 'aborting', 'start_outcome_unknown'"
)
_SAFE_ERROR_CODE_RE = re.compile(r"^[a-z0-9_]{1,96}$")


def apify_key_pool_enabled() -> bool:
    """Return the single rollout decision used by Service integrations."""

    return os.getenv("HORIZON_APIFY_KEY_POOL_ENABLED", "false").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def apify_pool_generation(store: ServiceStore, workspace_id: str) -> int | None:
    """Read the cache/finalize barrier without constructing a coordinator."""

    try:
        row = store.connect().execute(
            "SELECT generation FROM apify_key_pool_state WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
    except sqlite3.OperationalError:
        return None
    return int(row["generation"]) if row is not None else None


class ApifyKeyPoolError(RuntimeError):
    """Base class for public-safe pool transition failures."""

    code = "apify_key_pool_error"
    retryable = False

    def __init__(self, message: str | None = None) -> None:
        super().__init__(message or self.code)


class ApifyKeyBusyError(ApifyKeyPoolError):
    code = "apify_key_busy"


class ApifyKeyPoolConflictError(ApifyKeyPoolError):
    code = "apify_key_pool_conflict"
    retryable = True


class ApifyKeyDrainPendingError(ApifyKeyPoolError):
    code = "apify_key_drain_pending"
    retryable = True

    def __init__(self, message: str | None = None, *, active_run_count: int = 0) -> None:
        self.active_run_count = max(int(active_run_count), 0)
        super().__init__(message)


class ApifyKeyPoolExhaustedError(ApifyKeyPoolError):
    code = "apify_key_pool_exhausted"
    retryable = True


class ApifyKeyPoolBlockedError(ApifyKeyPoolError):
    code = "apify_key_pool_blocked"


class ApifyCredentialRejectedError(ApifyKeyPoolError):
    """The acquired credential became unusable before its Actor POST."""

    code = "apify_key_rejected"
    retryable = True


class ApifyRunLeaseError(ApifyKeyPoolConflictError):
    """A caller attempted to mutate a run through the wrong pinned lease."""


@dataclass(frozen=True, slots=True)
class ApifyQuotaCandidate:
    """Private credential material for rechecking one due depleted member."""

    secret_id: str
    secret_version: int
    env_name: str
    token: str = field(repr=False)


def _utc(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    return _utc(parsed)


def _optional_timestamp(value: Any, *, field_name: str) -> str | None:
    if value is None:
        return None
    parsed = _parse_time(value)
    if parsed is None:
        raise ValueError(f"{field_name} must be an ISO 8601 timestamp")
    return parsed.isoformat()


def _safe_error_code(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if _SAFE_ERROR_CODE_RE.fullmatch(candidate) else fallback


def _safe_nonnegative_number(value: Any, *, required: bool = False) -> float | None:
    if value is None and not required:
        return None
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("quota values must be numeric")
    number = float(value)
    if not math.isfinite(number) or number < 0:
        raise ValueError("quota values must be finite and non-negative")
    return number


def _normalize_run_status(value: Any) -> str:
    status = str(value or "").strip().lower().replace("-", "_")
    if status == "timedout":
        status = "timed_out"
    return status


class ApifyKeyPoolService:
    """Coordinate one sticky active Apify key and its ordered standbys."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        secret_store: SecretStore | None = None,
        now: Callable[[], datetime] | None = None,
        quota_max_age_seconds: int = POOL_QUOTA_MAX_AGE_SECONDS,
        workspace_id: str = DEFAULT_WORKSPACE_ID,
    ) -> None:
        self.store = store
        self.secret_store = secret_store or SecretStore(store.data_dir)
        self._now = now or (lambda: datetime.now(timezone.utc))
        self.quota_max_age_seconds = max(int(quota_max_age_seconds), 1)
        self.workspace_id = str(workspace_id)

    def _current_time(self) -> datetime:
        return _utc(self._now())

    def _state_row(self, connection: sqlite3.Connection, workspace_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM apify_key_pool_state WHERE workspace_id = ?",
            (workspace_id,),
        ).fetchone()
        if row is None:
            raise LookupError("Apify key pool workspace not initialized")
        return row

    @staticmethod
    def _member_rows(
        connection: sqlite3.Connection, workspace_id: str
    ) -> list[sqlite3.Row]:
        return connection.execute(
            """
            SELECT *
            FROM apify_key_pool_members
            WHERE workspace_id = ?
            ORDER BY position, secret_id
            """,
            (workspace_id,),
        ).fetchall()

    @staticmethod
    def _compact_positions(
        connection: sqlite3.Connection,
        *,
        workspace_id: str,
        ordered_secret_ids: Iterable[str],
        now_iso: str,
    ) -> None:
        ordered = list(ordered_secret_ids)
        maximum = connection.execute(
            """
            SELECT COALESCE(MAX(position), -1) AS maximum
            FROM apify_key_pool_members
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        temporary_offset = int(maximum["maximum"]) + len(ordered) + 1
        for index, secret_id in enumerate(ordered):
            connection.execute(
                """
                UPDATE apify_key_pool_members
                SET position = ?, updated_at = ?
                WHERE workspace_id = ? AND secret_id = ?
                """,
                (temporary_offset + index, now_iso, workspace_id, secret_id),
            )
        for index, secret_id in enumerate(ordered):
            connection.execute(
                """
                UPDATE apify_key_pool_members
                SET position = ?, updated_at = ?
                WHERE workspace_id = ? AND secret_id = ?
                """,
                (index, now_iso, workspace_id, secret_id),
            )

    @staticmethod
    def _nonterminal_count(
        connection: sqlite3.Connection,
        *,
        workspace_id: str,
        secret_id: str | None = None,
        up_to_generation: int | None = None,
    ) -> int:
        clauses = ["workspace_id = ?", f"status IN ({_NONTERMINAL_RUN_SQL})"]
        parameters: list[Any] = [workspace_id]
        if secret_id is not None:
            clauses.append("secret_id = ?")
            parameters.append(secret_id)
        if up_to_generation is not None:
            clauses.append("pool_generation <= ?")
            parameters.append(int(up_to_generation))
        row = connection.execute(
            f"""
            SELECT COUNT(*) AS count
            FROM apify_actor_runs
            WHERE {' AND '.join(clauses)}
            """,
            parameters,
        ).fetchone()
        return int(row["count"] if row is not None else 0)

    def current_generation(self, workspace_id: str) -> int:
        state = self._state_row(self.store.connect(), workspace_id)
        return int(state["generation"])

    def generation_matches(self, workspace_id: str, generation: int) -> bool:
        return self.current_generation(workspace_id) == int(generation)

    def public_state(self, workspace_id: str) -> dict[str, Any]:
        """Project pool state without credentials or remote run identifiers."""

        connection = self.store.connect()
        state = self._state_row(connection, workspace_id)
        rows = connection.execute(
            f"""
            SELECT
                member.secret_id,
                member.position,
                member.status,
                member.blocked_until,
                member.cycle_end_at,
                member.last_checked_at,
                member.last_error_code,
                COUNT(run.id) AS active_run_count
            FROM apify_key_pool_members AS member
            LEFT JOIN apify_actor_runs AS run
              ON run.workspace_id = member.workspace_id
             AND run.secret_id = member.secret_id
             AND run.status IN ({_NONTERMINAL_RUN_SQL})
            WHERE member.workspace_id = ?
            GROUP BY
                member.workspace_id,
                member.secret_id,
                member.position,
                member.status,
                member.blocked_until,
                member.cycle_end_at,
                member.last_checked_at,
                member.last_error_code
            ORDER BY member.position, member.secret_id
            """,
            (workspace_id,),
        ).fetchall()
        retry_candidates = [
            value
            for row in rows
            if row["status"] == "depleted"
            for value in (row["blocked_until"], row["cycle_end_at"])
            if value
        ]
        return {
            "schema_version": 1,
            "enabled": apify_key_pool_enabled(),
            "generation": int(state["generation"]),
            "status": str(state["status"]),
            "active_secret_id": state["active_secret_id"],
            "draining_secret_id": state["draining_secret_id"],
            "blocked_reason": state["blocked_reason"],
            "retry_at": min(retry_candidates) if retry_candidates else None,
            "members": [
                {
                    "secret_id": str(row["secret_id"]),
                    "position": int(row["position"]),
                    "status": str(row["status"]),
                    "blocked_until": row["blocked_until"],
                    "cycle_end_at": row["cycle_end_at"],
                    "last_checked_at": row["last_checked_at"],
                    "last_error_code": row["last_error_code"],
                    "active_run_count": int(row["active_run_count"] or 0),
                }
                for row in rows
            ],
        }

    def schedule_gate(
        self,
        workspace_id: str,
        *,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        """Return a safe scheduler decision without starting a transaction."""

        state = self.public_state(workspace_id)
        status = state["status"]
        if status == "ready":
            return {"blocked": False, "code": None, "retry_at": None}
        if status == "draining":
            return {
                "blocked": True,
                "code": ApifyKeyDrainPendingError.code,
                "retry_at": (_utc(now) + timedelta(seconds=30)).isoformat(),
            }
        if status in {"empty", "exhausted"}:
            return {
                "blocked": True,
                "code": ApifyKeyPoolExhaustedError.code,
                "retry_at": state["retry_at"],
            }
        return {
            "blocked": True,
            "code": state["blocked_reason"] or ApifyKeyPoolBlockedError.code,
            "retry_at": None,
        }

    def append_secret(self, secret_id: str) -> dict[str, Any]:
        """Append a configured Apify ref without ever reading its raw value."""

        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            secret = connection.execute(
                "SELECT * FROM secret_refs WHERE id = ?",
                (secret_id,),
            ).fetchone()
            if secret is None:
                raise LookupError("secret ref not found")
            if str(secret["provider"]).lower() != "apify" and str(
                secret["kind"]
            ).lower() != "apify":
                raise ValueError("secret ref is not an Apify credential")
            workspace_id = str(secret["workspace_id"])
            state = self._state_row(connection, workspace_id)
            existing = connection.execute(
                """
                SELECT 1 FROM apify_key_pool_members
                WHERE workspace_id = ? AND secret_id = ?
                """,
                (workspace_id, secret_id),
            ).fetchone()
            if existing is None:
                position_row = connection.execute(
                    """
                    SELECT COALESCE(MAX(position), -1) + 1 AS position
                    FROM apify_key_pool_members
                    WHERE workspace_id = ?
                    """,
                    (workspace_id,),
                ).fetchone()
                activate = (
                    state["status"] in {"empty", "exhausted"}
                    and not state["active_secret_id"]
                )
                connection.execute(
                    """
                    INSERT INTO apify_key_pool_members (
                        workspace_id, secret_id, position, status,
                        created_at, updated_at
                    ) VALUES (?, ?, ?, ?, ?, ?)
                    """,
                    (
                        workspace_id,
                        secret_id,
                        int(position_row["position"]),
                        "active" if activate else "standby",
                        now_iso,
                        now_iso,
                    ),
                )
                if activate:
                    current_rows = self._member_rows(connection, workspace_id)
                    self._compact_positions(
                        connection,
                        workspace_id=workspace_id,
                        ordered_secret_ids=[
                            secret_id,
                            *[
                                str(row["secret_id"])
                                for row in current_rows
                                if row["secret_id"] != secret_id
                            ],
                        ],
                        now_iso=now_iso,
                    )
                    connection.execute(
                        """
                        UPDATE apify_key_pool_state
                        SET generation = generation + 1,
                            status = 'ready',
                            active_secret_id = ?,
                            blocked_reason = NULL,
                            updated_at = ?
                        WHERE workspace_id = ?
                        """,
                        (secret_id, now_iso, workspace_id),
                    )
                else:
                    connection.execute(
                        """
                        UPDATE apify_key_pool_state
                        SET generation = generation + 1, updated_at = ?
                        WHERE workspace_id = ?
                        """,
                        (now_iso, workspace_id),
                    )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        return self.public_state(workspace_id)

    def reorder(
        self,
        workspace_id: str,
        *,
        expected_generation: int,
        secret_ids: Iterable[str],
    ) -> dict[str, Any]:
        """CAS-update the complete order while preserving the active key."""

        requested = [str(secret_id) for secret_id in secret_ids]
        if len(requested) != len(set(requested)):
            raise ValueError("secret_ids must not contain duplicates")
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            state = self._state_row(connection, workspace_id)
            if int(state["generation"]) != int(expected_generation):
                raise ApifyKeyPoolConflictError()
            if state["status"] in {"draining", "blocked"}:
                raise ApifyKeyBusyError()
            current_rows = self._member_rows(connection, workspace_id)
            current_ids = [str(row["secret_id"]) for row in current_rows]
            if len(requested) != len(current_ids) or set(requested) != set(current_ids):
                raise ValueError("secret_ids must contain every pool member exactly once")
            active_secret_id = state["active_secret_id"]
            if active_secret_id and requested and requested[0] != active_secret_id:
                active_run_count = self._nonterminal_count(
                    connection,
                    workspace_id=workspace_id,
                    secret_id=str(active_secret_id),
                )
                if apify_key_pool_enabled() or active_run_count:
                    raise ApifyKeyBusyError(
                        "active Apify key must be drained before it can be replaced"
                    )
                connection.execute(
                    """
                    UPDATE apify_key_pool_members
                    SET status = 'standby', updated_at = ?
                    WHERE workspace_id = ? AND secret_id = ?
                    """,
                    (now_iso, workspace_id, active_secret_id),
                )
                connection.execute(
                    """
                    UPDATE apify_key_pool_members
                    SET status = 'active', updated_at = ?
                    WHERE workspace_id = ? AND secret_id = ?
                    """,
                    (now_iso, workspace_id, requested[0]),
                )
                connection.execute(
                    """
                    UPDATE apify_key_pool_state
                    SET active_secret_id = ?, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (requested[0], now_iso, workspace_id),
                )
            self._compact_positions(
                connection,
                workspace_id=workspace_id,
                ordered_secret_ids=requested,
                now_iso=now_iso,
            )
            connection.execute(
                """
                UPDATE apify_key_pool_state
                SET generation = generation + 1, updated_at = ?
                WHERE workspace_id = ?
                """,
                (now_iso, workspace_id),
            )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        return self.public_state(workspace_id)

    def _token_for_env(self, env_name: str) -> str | None:
        value = self.secret_store.read().get(env_name)
        candidate = str(value or "").strip()
        return candidate or None

    def _quota_snapshot_stale(self, member: sqlite3.Row, now: datetime) -> bool:
        checked_at = _parse_time(member["last_checked_at"])
        if checked_at is None:
            return True
        return (now - checked_at).total_seconds() > self.quota_max_age_seconds

    def acquire_credential(
        self,
        attempted_secret_ids: Iterable[str] = (),
        *,
        workspace_id: str | None = None,
        logical_run_id: str | None = None,
    ) -> ApifyCredentialLease:
        """Atomically pin one active secret and create a pre-POST reservation."""

        workspace_id = str(workspace_id or self.workspace_id)
        attempted = {str(secret_id) for secret_id in attempted_secret_ids}
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now = self._current_time()
        now_iso = now.isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            state = self._state_row(connection, workspace_id)
            if state["status"] == "draining":
                raise ApifyKeyDrainPendingError()
            if state["status"] == "blocked":
                raise ApifyKeyPoolBlockedError()
            if state["status"] != "ready" or not state["active_secret_id"]:
                raise ApifyKeyPoolExhaustedError()
            secret_id = str(state["active_secret_id"])
            if secret_id in attempted:
                raise ApifyKeyPoolExhaustedError(
                    "every currently available Apify key was already attempted"
                )
            member = connection.execute(
                """
                SELECT * FROM apify_key_pool_members
                WHERE workspace_id = ? AND secret_id = ? AND status = 'active'
                """,
                (workspace_id, secret_id),
            ).fetchone()
            secret = connection.execute(
                """
                SELECT * FROM secret_refs
                WHERE id = ? AND workspace_id = ?
                """,
                (secret_id, workspace_id),
            ).fetchone()
            if member is None or secret is None:
                raise ApifyKeyPoolBlockedError("active Apify key metadata is inconsistent")
            quota_snapshot_stale = self._quota_snapshot_stale(member, now)
            if (
                not quota_snapshot_stale
                and member["remaining_included_credits_usd"] is not None
                and float(member["remaining_included_credits_usd"]) <= 0
            ):
                self._begin_drain_in_transaction(
                    connection,
                    workspace_id=workspace_id,
                    secret_id=secret_id,
                    target_status="depleted",
                    reason="apify_credits_depleted",
                    now_iso=now_iso,
                )
                if owns_transaction:
                    connection.commit()
                state_after = self.complete_drain_and_failover(workspace_id)
                if state_after["status"] == "exhausted":
                    raise ApifyKeyPoolExhaustedError() from None
                return self.acquire_credential(
                    (*attempted, secret_id),
                    workspace_id=workspace_id,
                    logical_run_id=logical_run_id,
                )
            env_name = str(secret["env_name"])
            token = self._token_for_env(env_name)
            if token is None:
                self._begin_drain_in_transaction(
                    connection,
                    workspace_id=workspace_id,
                    secret_id=secret_id,
                    target_status="invalid",
                    reason="apify_secret_not_configured",
                    now_iso=now_iso,
                )
                if owns_transaction:
                    connection.commit()
                try:
                    state_after = self.complete_drain_and_failover(workspace_id)
                except ApifyKeyDrainPendingError:
                    raise
                if state_after["status"] == "exhausted":
                    raise ApifyKeyPoolExhaustedError() from None
                return self.acquire_credential(
                    (*attempted, secret_id),
                    workspace_id=workspace_id,
                    logical_run_id=logical_run_id,
                )

            reservation_id = f"apifyrun_{uuid.uuid4().hex}"
            connection.execute(
                """
                INSERT INTO apify_actor_runs (
                    id, workspace_id, logical_run_id, secret_id, secret_version,
                    pool_generation, status, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'reserved', ?, ?)
                """,
                (
                    reservation_id,
                    workspace_id,
                    str(logical_run_id) if logical_run_id else None,
                    secret_id,
                    int(secret["version"]),
                    int(state["generation"]),
                    now_iso,
                    now_iso,
                ),
            )
            quota_check_required = quota_snapshot_stale
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        return ApifyCredentialLease(
            reservation_id=reservation_id,
            secret_id=secret_id,
            secret_version=int(secret["version"]),
            pool_generation=int(state["generation"]),
            env_name=env_name,
            token=token,
            quota_check_required=quota_check_required,
        )

    @staticmethod
    def _lease_values(lease: ApifyCredentialLease) -> tuple[str, str, int]:
        return (
            str(lease.reservation_id),
            str(lease.secret_id),
            int(lease.pool_generation),
        )

    def _run_for_lease(
        self,
        connection: sqlite3.Connection,
        lease: ApifyCredentialLease,
    ) -> sqlite3.Row:
        reservation_id, secret_id, generation = self._lease_values(lease)
        row = connection.execute(
            """
            SELECT * FROM apify_actor_runs
            WHERE id = ? AND secret_id = ? AND pool_generation = ?
              AND secret_version = ?
            """,
            (
                reservation_id,
                secret_id,
                generation,
                int(lease.secret_version),
            ),
        ).fetchone()
        if row is None:
            raise ApifyRunLeaseError()
        return row

    def assert_lease_startable(self, lease: ApifyCredentialLease) -> None:
        """Fail immediately if a drain barrier appeared before the Actor POST."""

        connection = self.store.connect()
        run = self._run_for_lease(connection, lease)
        state = self._state_row(connection, str(run["workspace_id"]))
        if (
            run["status"] != "reserved"
            or state["status"] != "ready"
            or state["active_secret_id"] != run["secret_id"]
        ):
            raise ApifyKeyDrainPendingError()

    def register_run(
        self,
        lease: ApifyCredentialLease,
        run_id: str,
        dataset_id: str | None,
        logical_run_id: str | None = None,
    ) -> dict[str, Any]:
        """Attach remote identifiers to the pre-POST reservation idempotently."""

        remote_run_id = str(run_id or "").strip()
        remote_dataset_id = str(dataset_id or "").strip() or None
        if not remote_run_id:
            raise ValueError("run_id is required")
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            run = self._run_for_lease(connection, lease)
            if run["remote_run_id"]:
                if (
                    run["remote_run_id"] != remote_run_id
                    or run["dataset_id"] != remote_dataset_id
                ):
                    raise ApifyRunLeaseError()
            elif run["status"] not in {"reserved", "starting"}:
                raise ApifyRunLeaseError()
            else:
                connection.execute(
                    """
                    UPDATE apify_actor_runs
                    SET remote_run_id = ?, dataset_id = ?,
                        logical_run_id = COALESCE(logical_run_id, ?),
                        status = 'running',
                        started_at = COALESCE(started_at, ?), updated_at = ?
                    WHERE id = ?
                    """,
                    (
                        remote_run_id,
                        remote_dataset_id,
                        str(logical_run_id) if logical_run_id else None,
                        now_iso,
                        now_iso,
                        run["id"],
                    ),
                )
            state = self._state_row(connection, str(run["workspace_id"]))
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        result = self.get_run(str(run["id"]))
        if result is None:
            raise LookupError("registered Apify run not found")
        if (
            state["status"] != "ready"
            or state["active_secret_id"] != run["secret_id"]
        ):
            raise ApifyKeyDrainPendingError(active_run_count=1)
        return result

    def release_reservation(
        self,
        lease: ApifyCredentialLease,
        error_code: str = "apify_start_rejected",
    ) -> dict[str, Any]:
        """Close an explicit no-run outcome without changing key health."""

        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        safe_code = _safe_error_code(error_code, "apify_start_rejected")
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            run = self._run_for_lease(connection, lease)
            if run["status"] == "reserved" and not run["remote_run_id"]:
                connection.execute(
                    """
                    UPDATE apify_actor_runs
                    SET status = 'start_rejected', last_error_code = ?,
                        terminal_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (safe_code, now_iso, now_iso, run["id"]),
                )
            elif run["status"] not in APIFY_RUN_TERMINAL_STATUSES:
                raise ApifyRunLeaseError()
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        result = self.get_run(str(run["id"]))
        if result is None:
            raise LookupError("released Apify reservation not found")
        return result

    def report_start_outcome_unknown(
        self,
        lease: ApifyCredentialLease,
        error_code: str = "apify_start_outcome_unknown",
    ) -> None:
        """Persist an unknowable POST outcome and fail the whole pool closed."""

        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        safe_code = _safe_error_code(error_code, "apify_start_outcome_unknown")
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            run = self._run_for_lease(connection, lease)
            if run["status"] in APIFY_RUN_TERMINAL_STATUSES:
                raise ApifyRunLeaseError()
            connection.execute(
                """
                UPDATE apify_actor_runs
                SET status = 'start_outcome_unknown', last_error_code = ?,
                    updated_at = ?
                WHERE id = ?
                """,
                (safe_code, now_iso, run["id"]),
            )
            connection.execute(
                """
                UPDATE apify_key_pool_state
                SET status = 'blocked', blocked_reason = ?, updated_at = ?
                WHERE workspace_id = ?
                """,
                (safe_code, now_iso, run["workspace_id"]),
            )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise

    def block_unregistered_reservations(
        self,
        workspace_id: str,
        *,
        error_code: str = "apify_start_outcome_unknown",
    ) -> int:
        """Fail closed on restart when a pre-POST reservation has no outcome.

        This transition needs no SecretStore access. A restarted process cannot
        prove whether the old process sent the Actor POST, so every surviving
        reservation without a remote ID becomes manual-reconciliation evidence.
        """

        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        safe_code = _safe_error_code(error_code, "apify_start_outcome_unknown")
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            cursor = connection.execute(
                """
                UPDATE apify_actor_runs
                SET status = 'start_outcome_unknown',
                    last_error_code = ?,
                    updated_at = ?
                WHERE workspace_id = ?
                  AND status IN ('reserved', 'starting')
                  AND remote_run_id IS NULL
                """,
                (safe_code, now_iso, workspace_id),
            )
            changed = max(int(cursor.rowcount), 0)
            if changed:
                connection.execute(
                    """
                    UPDATE apify_key_pool_state
                    SET status = 'blocked', blocked_reason = ?, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (safe_code, now_iso, workspace_id),
                )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        return changed

    def mark_run_aborting(
        self,
        lease: ApifyCredentialLease,
        run_id: str | None = None,
    ) -> dict[str, Any]:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            run = self._run_for_lease(connection, lease)
            if run_id and run["remote_run_id"] != str(run_id):
                raise ApifyRunLeaseError()
            if run["status"] not in APIFY_RUN_TERMINAL_STATUSES:
                connection.execute(
                    """
                    UPDATE apify_actor_runs
                    SET status = 'aborting', updated_at = ?
                    WHERE id = ?
                    """,
                    (now_iso, run["id"]),
                )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        result = self.get_run(str(run["id"]))
        if result is None:
            raise LookupError("Apify run not found after abort transition")
        return result

    def mark_run_terminal(
        self,
        lease: ApifyCredentialLease,
        run_id: str,
        status: str,
    ) -> None:
        terminal_status = _normalize_run_status(status)
        if terminal_status not in APIFY_RUN_TERMINAL_STATUSES:
            raise ValueError("status is not terminal")
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            run = self._run_for_lease(connection, lease)
            if run["remote_run_id"] and run["remote_run_id"] != str(run_id):
                raise ApifyRunLeaseError()
            if run["status"] not in APIFY_RUN_TERMINAL_STATUSES:
                connection.execute(
                    """
                    UPDATE apify_actor_runs
                    SET status = ?, terminal_at = ?, updated_at = ?
                    WHERE id = ?
                    """,
                    (terminal_status, now_iso, now_iso, run["id"]),
                )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        if self.get_run(str(run["id"])) is None:
            raise LookupError("terminal Apify run not found")

    def get_run(self, reservation_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            "SELECT * FROM apify_actor_runs WHERE id = ?",
            (reservation_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def list_nonterminal_runs(
        self,
        workspace_id: str,
        *,
        up_to_generation: int | None = None,
    ) -> list[dict[str, Any]]:
        clauses = [
            "run.workspace_id = ?",
            f"run.status IN ({_NONTERMINAL_RUN_SQL})",
        ]
        parameters: list[Any] = [workspace_id]
        if up_to_generation is not None:
            clauses.append("run.pool_generation <= ?")
            parameters.append(int(up_to_generation))
        rows = self.store.connect().execute(
            f"""
            SELECT run.*, secret.env_name
            FROM apify_actor_runs AS run
            LEFT JOIN secret_refs AS secret ON secret.id = run.secret_id
            WHERE {' AND '.join(clauses)}
            ORDER BY run.pool_generation, run.created_at, run.id
            """,
            parameters,
        ).fetchall()
        return [dict(row) for row in rows]

    def lease_for_run(self, reservation_id: str) -> ApifyCredentialLease:
        connection = self.store.connect()
        run = connection.execute(
            """
            SELECT run.*, secret.env_name, secret.version AS current_secret_version
            FROM apify_actor_runs AS run
            LEFT JOIN secret_refs AS secret ON secret.id = run.secret_id
            WHERE run.id = ?
            """,
            (reservation_id,),
        ).fetchone()
        if run is None or not run["env_name"]:
            raise ApifyRunLeaseError()
        if int(run["current_secret_version"]) != int(run["secret_version"]):
            raise ApifyKeyBusyError("Apify secret changed while a run was active")
        token = self._token_for_env(str(run["env_name"]))
        if token is None:
            raise ApifyKeyBusyError("Apify secret value is unavailable for run cleanup")
        return ApifyCredentialLease(
            reservation_id=str(run["id"]),
            secret_id=str(run["secret_id"]),
            secret_version=int(run["secret_version"]),
            pool_generation=int(run["pool_generation"]),
            env_name=str(run["env_name"]),
            token=token,
            quota_check_required=False,
        )

    def _begin_drain_in_transaction(
        self,
        connection: sqlite3.Connection,
        *,
        workspace_id: str,
        secret_id: str,
        target_status: str,
        reason: str,
        now_iso: str,
    ) -> bool:
        if target_status not in {"standby", "depleted", "invalid"}:
            raise ValueError("invalid drain target status")
        state = self._state_row(connection, workspace_id)
        member = connection.execute(
            """
            SELECT * FROM apify_key_pool_members
            WHERE workspace_id = ? AND secret_id = ?
            """,
            (workspace_id, secret_id),
        ).fetchone()
        if member is None:
            raise LookupError("Apify key pool member not found")
        safe_reason = _safe_error_code(reason, "apify_key_drain")
        if state["status"] == "draining":
            if state["draining_secret_id"] != secret_id:
                raise ApifyKeyBusyError()
            return True
        if state["status"] == "blocked":
            raise ApifyKeyPoolBlockedError()
        if state["active_secret_id"] != secret_id:
            if member["status"] not in {"draining", "active"}:
                connection.execute(
                    """
                    UPDATE apify_key_pool_members
                    SET status = ?, last_error_code = ?, updated_at = ?
                    WHERE workspace_id = ? AND secret_id = ?
                    """,
                    (target_status, safe_reason, now_iso, workspace_id, secret_id),
                )
            return False
        connection.execute(
            """
            UPDATE apify_key_pool_members
            SET status = 'draining', last_error_code = ?, updated_at = ?
            WHERE workspace_id = ? AND secret_id = ?
            """,
            (safe_reason, now_iso, workspace_id, secret_id),
        )
        connection.execute(
            """
            UPDATE apify_key_pool_state
            SET status = 'draining',
                draining_secret_id = ?,
                drain_generation = generation,
                drain_target_status = ?,
                drain_reason = ?,
                drain_started_at = ?,
                blocked_reason = NULL,
                updated_at = ?
            WHERE workspace_id = ?
            """,
            (
                secret_id,
                target_status,
                safe_reason,
                now_iso,
                now_iso,
                workspace_id,
            ),
        )
        return True

    def begin_drain(
        self,
        secret_id: str,
        *,
        target_status: str = "standby",
        reason: str = "apify_key_manual_drain",
    ) -> dict[str, Any]:
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            member = connection.execute(
                """
                SELECT workspace_id FROM apify_key_pool_members
                WHERE secret_id = ?
                """,
                (secret_id,),
            ).fetchone()
            if member is None:
                raise LookupError("Apify key pool member not found")
            workspace_id = str(member["workspace_id"])
            self._begin_drain_in_transaction(
                connection,
                workspace_id=workspace_id,
                secret_id=secret_id,
                target_status=target_status,
                reason=reason,
                now_iso=now_iso,
            )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        return self.public_state(workspace_id)

    def complete_drain_and_failover(self, workspace_id: str) -> dict[str, Any]:
        """Promote a standby only after every old-generation run is terminal."""

        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            state = self._state_row(connection, workspace_id)
            if state["status"] == "blocked":
                raise ApifyKeyPoolBlockedError()
            if state["status"] != "draining":
                if owns_transaction:
                    connection.commit()
                return self.public_state(workspace_id)
            drain_generation = int(state["drain_generation"] or state["generation"])
            active_run_count = self._nonterminal_count(
                connection,
                workspace_id=workspace_id,
                up_to_generation=drain_generation,
            )
            if active_run_count:
                raise ApifyKeyDrainPendingError(active_run_count=active_run_count)
            draining_secret_id = str(state["draining_secret_id"])
            target_status = str(state["drain_target_status"] or "standby")
            connection.execute(
                """
                UPDATE apify_key_pool_members
                SET status = ?,
                    blocked_until = CASE
                        WHEN ? = 'depleted' THEN COALESCE(cycle_end_at, blocked_until)
                        ELSE blocked_until
                    END,
                    updated_at = ?
                WHERE workspace_id = ? AND secret_id = ?
                """,
                (
                    target_status,
                    target_status,
                    now_iso,
                    workspace_id,
                    draining_secret_id,
                ),
            )
            candidate = connection.execute(
                """
                SELECT secret_id
                FROM apify_key_pool_members
                WHERE workspace_id = ?
                  AND status = 'standby'
                  AND secret_id != ?
                ORDER BY position, secret_id
                LIMIT 1
                """,
                (workspace_id, draining_secret_id),
            ).fetchone()
            candidate_id = str(candidate["secret_id"]) if candidate is not None else None
            rows = self._member_rows(connection, workspace_id)
            ordered_ids = [
                *([candidate_id] if candidate_id else []),
                *[
                    str(row["secret_id"])
                    for row in rows
                    if row["secret_id"] not in {candidate_id, draining_secret_id}
                    and row["status"] == "standby"
                ],
                *[
                    str(row["secret_id"])
                    for row in rows
                    if row["secret_id"] not in {candidate_id, draining_secret_id}
                    and row["status"] != "standby"
                ],
                draining_secret_id,
            ]
            self._compact_positions(
                connection,
                workspace_id=workspace_id,
                ordered_secret_ids=ordered_ids,
                now_iso=now_iso,
            )
            if candidate_id:
                connection.execute(
                    """
                    UPDATE apify_key_pool_members
                    SET status = 'active', blocked_until = NULL, updated_at = ?
                    WHERE workspace_id = ? AND secret_id = ?
                    """,
                    (now_iso, workspace_id, candidate_id),
                )
            connection.execute(
                """
                UPDATE apify_key_pool_state
                SET generation = generation + 1,
                    status = ?,
                    active_secret_id = ?,
                    draining_secret_id = NULL,
                    drain_generation = NULL,
                    drain_target_status = NULL,
                    drain_reason = NULL,
                    drain_started_at = NULL,
                    blocked_reason = NULL,
                    updated_at = ?
                WHERE workspace_id = ?
                """,
                (
                    "ready" if candidate_id else "exhausted",
                    candidate_id,
                    now_iso,
                    workspace_id,
                ),
            )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        return self.public_state(workspace_id)

    def _record_credential_failure(
        self,
        lease_or_secret_id: ApifyCredentialLease | str,
        failure_kind: Any,
        status_code: int | None = None,
        error_type: str | None = None,
    ) -> tuple[str, bool]:
        """Persist classification and enter draining without doing network I/O."""

        del status_code, error_type
        kind = str(getattr(failure_kind, "value", failure_kind)).strip().lower()
        if kind not in {"depleted", "invalid"}:
            raise ValueError("failure_kind must be depleted or invalid")
        lease = (
            lease_or_secret_id
            if isinstance(lease_or_secret_id, ApifyCredentialLease)
            else None
        )
        secret_id = (
            str(lease.secret_id) if lease is not None else str(lease_or_secret_id)
        )
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        reason = "apify_credits_depleted" if kind == "depleted" else "apify_token_invalid"
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            member = connection.execute(
                """
                SELECT workspace_id FROM apify_key_pool_members
                WHERE secret_id = ?
                """,
                (secret_id,),
            ).fetchone()
            if member is None:
                raise LookupError("Apify key pool member not found")
            workspace_id = str(member["workspace_id"])
            if lease is not None:
                run = self._run_for_lease(connection, lease)
                if run["status"] == "reserved" and not run["remote_run_id"]:
                    connection.execute(
                        """
                        UPDATE apify_actor_runs
                        SET status = 'start_rejected', last_error_code = ?,
                            terminal_at = ?, updated_at = ?
                        WHERE id = ?
                        """,
                        (reason, now_iso, now_iso, run["id"]),
                    )
            draining = self._begin_drain_in_transaction(
                connection,
                workspace_id=workspace_id,
                secret_id=secret_id,
                target_status=kind,
                reason=reason,
                now_iso=now_iso,
            )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        return workspace_id, draining

    async def report_credential_failure(
        self,
        lease: ApifyCredentialLease,
        *,
        failure_kind: Any,
        status_code: int,
        error_type: str | None,
        abort_run: Any,
    ) -> None:
        """Abort and confirm every old-generation run before returning."""

        workspace_id, draining = self._record_credential_failure(
            lease,
            failure_kind,
            status_code=status_code,
            error_type=error_type,
        )
        if not draining:
            return
        state = self._state_row(self.store.connect(), workspace_id)
        drain_generation = int(state["drain_generation"] or state["generation"])
        try:
            async with asyncio.timeout(30):
                for run in self.list_nonterminal_runs(
                    workspace_id,
                    up_to_generation=drain_generation,
                ):
                    remote_run_id = str(run["remote_run_id"] or "")
                    if not remote_run_id:
                        raise ApifyKeyDrainPendingError(active_run_count=1)
                    run_lease = self.lease_for_run(str(run["id"]))
                    self.mark_run_aborting(run_lease, remote_run_id)
                    terminal_status = await abort_run(run_lease, remote_run_id)
                    normalized = _normalize_run_status(terminal_status)
                    if normalized not in APIFY_RUN_TERMINAL_STATUSES:
                        raise ApifyKeyDrainPendingError(active_run_count=1)
                    self.mark_run_terminal(
                        run_lease,
                        remote_run_id,
                        normalized,
                    )
        except TimeoutError:
            remaining = self._nonterminal_count(
                self.store.connect(),
                workspace_id=workspace_id,
                up_to_generation=drain_generation,
            )
            raise ApifyKeyDrainPendingError(active_run_count=remaining) from None
        self.complete_drain_and_failover(workspace_id)

    def should_retry_after_terminal(
        self,
        lease: ApifyCredentialLease,
        remote_run_id: str,
        status: str,
    ) -> bool | None:
        del remote_run_id, status
        run = self.get_run(str(lease.reservation_id))
        if run is None:
            return False
        state = self._state_row(
            self.store.connect(),
            str(run["workspace_id"]),
        )
        if state["status"] == "draining" and int(
            state["drain_generation"] or state["generation"]
        ) >= int(lease.pool_generation):
            return None
        return (
            state["status"] == "ready"
            and int(state["generation"]) != int(lease.pool_generation)
            and state["active_secret_id"] != lease.secret_id
        )

    def _write_quota_snapshot(
        self,
        connection: sqlite3.Connection,
        *,
        workspace_id: str,
        secret_id: str,
        checked_at: str,
        cycle_start_at: str | None,
        cycle_end_at: str | None,
        monthly_included_credits_usd: float | None,
        monthly_usage_usd: float | None,
        remaining_included_credits_usd: float,
        max_monthly_usage_usd: float | None,
        remaining_hard_limit_usd: float | None,
        now_iso: str,
    ) -> sqlite3.Row:
        cursor = connection.execute(
            """
            UPDATE apify_key_pool_members
            SET cycle_start_at = ?,
                cycle_end_at = ?,
                last_checked_at = ?,
                monthly_included_credits_usd = ?,
                monthly_usage_usd = ?,
                remaining_included_credits_usd = ?,
                max_monthly_usage_usd = ?,
                remaining_hard_limit_usd = ?,
                updated_at = ?
            WHERE workspace_id = ? AND secret_id = ?
            """,
            (
                cycle_start_at,
                cycle_end_at,
                checked_at,
                monthly_included_credits_usd,
                monthly_usage_usd,
                remaining_included_credits_usd,
                max_monthly_usage_usd,
                remaining_hard_limit_usd,
                now_iso,
                workspace_id,
                secret_id,
            ),
        )
        if cursor.rowcount != 1:
            raise LookupError("Apify key pool member not found")
        row = connection.execute(
            """
            SELECT * FROM apify_key_pool_members
            WHERE workspace_id = ? AND secret_id = ?
            """,
            (workspace_id, secret_id),
        ).fetchone()
        if row is None:
            raise LookupError("Apify key pool member not found")
        return row

    def record_quota_snapshot(
        self,
        lease: ApifyCredentialLease,
        *,
        remaining_included_credits_usd: float,
        checked_at: str | None = None,
        cycle_start_at: str | None = None,
        cycle_end_at: str | None = None,
        monthly_included_credits_usd: float | None = None,
        monthly_usage_usd: float | None = None,
        max_monthly_usage_usd: float | None = None,
        remaining_hard_limit_usd: float | None = None,
    ) -> None:
        remaining = _safe_nonnegative_number(
            remaining_included_credits_usd, required=True
        )
        optional_numbers = [
            _safe_nonnegative_number(monthly_included_credits_usd),
            _safe_nonnegative_number(monthly_usage_usd),
            _safe_nonnegative_number(max_monthly_usage_usd),
            _safe_nonnegative_number(remaining_hard_limit_usd),
        ]
        now = self._current_time()
        checked = _parse_time(checked_at) if checked_at else now
        if checked is None:
            raise ValueError("checked_at must be an ISO 8601 timestamp")
        normalized_cycle_start = _optional_timestamp(
            cycle_start_at,
            field_name="cycle_start_at",
        )
        normalized_cycle_end = _optional_timestamp(
            cycle_end_at,
            field_name="cycle_end_at",
        )
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            run = self._run_for_lease(connection, lease)
            self._write_quota_snapshot(
                connection,
                workspace_id=str(run["workspace_id"]),
                secret_id=str(run["secret_id"]),
                checked_at=checked.isoformat(),
                cycle_start_at=normalized_cycle_start,
                cycle_end_at=normalized_cycle_end,
                monthly_included_credits_usd=optional_numbers[0],
                monthly_usage_usd=optional_numbers[1],
                remaining_included_credits_usd=float(remaining),
                max_monthly_usage_usd=optional_numbers[2],
                remaining_hard_limit_usd=optional_numbers[3],
                now_iso=now.isoformat(),
            )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        return

    def record_member_quota(
        self,
        *,
        workspace_id: str,
        secret_id: str,
        remaining_included_credits_usd: float,
        checked_at: str | None = None,
        cycle_start_at: str | None = None,
        cycle_end_at: str | None = None,
        monthly_included_credits_usd: float | None = None,
        monthly_usage_usd: float | None = None,
        max_monthly_usage_usd: float | None = None,
        remaining_hard_limit_usd: float | None = None,
    ) -> dict[str, Any]:
        """Record a recheck and recover a depleted key at the queue tail."""

        remaining = _safe_nonnegative_number(
            remaining_included_credits_usd, required=True
        )
        now = self._current_time()
        checked = _parse_time(checked_at) if checked_at else now
        if checked is None:
            raise ValueError("checked_at must be an ISO 8601 timestamp")
        optional_numbers = [
            _safe_nonnegative_number(monthly_included_credits_usd),
            _safe_nonnegative_number(monthly_usage_usd),
            _safe_nonnegative_number(max_monthly_usage_usd),
            _safe_nonnegative_number(remaining_hard_limit_usd),
        ]
        normalized_cycle_start = _optional_timestamp(
            cycle_start_at,
            field_name="cycle_start_at",
        )
        normalized_cycle_end = _optional_timestamp(
            cycle_end_at,
            field_name="cycle_end_at",
        )
        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            member = self._write_quota_snapshot(
                connection,
                workspace_id=workspace_id,
                secret_id=secret_id,
                checked_at=checked.isoformat(),
                cycle_start_at=normalized_cycle_start,
                cycle_end_at=normalized_cycle_end,
                monthly_included_credits_usd=optional_numbers[0],
                monthly_usage_usd=optional_numbers[1],
                remaining_included_credits_usd=float(remaining),
                max_monthly_usage_usd=optional_numbers[2],
                remaining_hard_limit_usd=optional_numbers[3],
                now_iso=now.isoformat(),
            )
            state = self._state_row(connection, workspace_id)
            if remaining <= 0 and member["status"] not in {"active", "draining"}:
                connection.execute(
                    """
                    UPDATE apify_key_pool_members
                    SET status = 'depleted', blocked_until = ?,
                        last_error_code = 'apify_credits_depleted', updated_at = ?
                    WHERE workspace_id = ? AND secret_id = ?
                    """,
                    (
                        normalized_cycle_end,
                        now.isoformat(),
                        workspace_id,
                        secret_id,
                    ),
                )
            elif remaining > 0 and member["status"] in {"depleted", "invalid"}:
                activate = (
                    state["status"] in {"empty", "exhausted"}
                    and not state["active_secret_id"]
                )
                rows = self._member_rows(connection, workspace_id)
                other_ids = [
                    str(row["secret_id"])
                    for row in rows
                    if row["secret_id"] != secret_id
                ]
                ordered = (
                    [secret_id, *other_ids]
                    if activate
                    else [*other_ids, secret_id]
                )
                self._compact_positions(
                    connection,
                    workspace_id=workspace_id,
                    ordered_secret_ids=ordered,
                    now_iso=now.isoformat(),
                )
                connection.execute(
                    """
                    UPDATE apify_key_pool_members
                    SET status = ?, blocked_until = NULL, last_error_code = NULL,
                        updated_at = ?
                    WHERE workspace_id = ? AND secret_id = ?
                    """,
                    (
                        "active" if activate else "standby",
                        now.isoformat(),
                        workspace_id,
                        secret_id,
                    ),
                )
                if activate:
                    connection.execute(
                        """
                        UPDATE apify_key_pool_state
                        SET generation = generation + 1, status = 'ready',
                            active_secret_id = ?, blocked_reason = NULL, updated_at = ?
                        WHERE workspace_id = ?
                        """,
                        (secret_id, now.isoformat(), workspace_id),
                    )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        return self.public_state(workspace_id)

    def recover_due_members(
        self,
        workspace_id: str,
        *,
        now: datetime | None = None,
    ) -> list[str]:
        """List depleted members whose recorded billing-cycle boundary passed.

        This method is intentionally read-only. Callers must recheck each
        returned credential with Apify and pass the safe result to
        :meth:`record_member_quota`; elapsed time alone never restores a key.
        """

        now_iso = _utc(now or self._current_time()).isoformat()
        rows = self.store.connect().execute(
            """
            SELECT secret_id
            FROM apify_key_pool_members
            WHERE workspace_id = ?
              AND status = 'depleted'
              AND COALESCE(blocked_until, cycle_end_at) IS NOT NULL
              AND COALESCE(blocked_until, cycle_end_at) <= ?
            ORDER BY position, secret_id
            """,
            (workspace_id, now_iso),
        ).fetchall()
        return [str(row["secret_id"]) for row in rows]

    def quota_candidate(self, secret_id: str) -> ApifyQuotaCandidate:
        """Resolve one due member's token without placing it in SQLite or repr."""

        row = self.store.connect().execute(
            """
            SELECT member.secret_id, secret.version, secret.env_name
            FROM apify_key_pool_members AS member
            JOIN secret_refs AS secret ON secret.id = member.secret_id
            WHERE member.secret_id = ?
            """,
            (secret_id,),
        ).fetchone()
        if row is None:
            raise LookupError("Apify key pool member not found")
        token = self._token_for_env(str(row["env_name"]))
        if token is None:
            raise ApifyKeyBusyError("Apify secret value is unavailable")
        return ApifyQuotaCandidate(
            secret_id=str(row["secret_id"]),
            secret_version=int(row["version"]),
            env_name=str(row["env_name"]),
            token=token,
        )

    def mark_secret_rotated(self, secret_id: str) -> dict[str, Any] | None:
        """Invalidate old quota state and safely requeue a rotated credential."""

        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            member = connection.execute(
                """
                SELECT * FROM apify_key_pool_members
                WHERE secret_id = ?
                """,
                (secret_id,),
            ).fetchone()
            if member is None:
                if owns_transaction:
                    connection.commit()
                return None
            workspace_id = str(member["workspace_id"])
            state = self._state_row(connection, workspace_id)
            active_run_count = self._nonterminal_count(
                connection,
                workspace_id=workspace_id,
                secret_id=secret_id,
            )
            if (
                active_run_count
                or member["status"] == "draining"
                or state["status"] in {"draining", "blocked"}
            ):
                raise ApifyKeyBusyError()

            remains_active = state["active_secret_id"] == secret_id
            activate = (
                not remains_active
                and not state["active_secret_id"]
                and state["status"] in {"empty", "ready", "exhausted"}
            )
            next_status = "active" if remains_active or activate else "standby"
            connection.execute(
                """
                UPDATE apify_key_pool_members
                SET status = ?,
                    blocked_until = NULL,
                    cycle_start_at = NULL,
                    cycle_end_at = NULL,
                    last_checked_at = NULL,
                    last_error_code = NULL,
                    monthly_included_credits_usd = NULL,
                    monthly_usage_usd = NULL,
                    remaining_included_credits_usd = NULL,
                    max_monthly_usage_usd = NULL,
                    remaining_hard_limit_usd = NULL,
                    updated_at = ?
                WHERE workspace_id = ? AND secret_id = ?
                """,
                (next_status, now_iso, workspace_id, secret_id),
            )
            if not remains_active:
                rows = self._member_rows(connection, workspace_id)
                other_ids = [
                    str(row["secret_id"])
                    for row in rows
                    if row["secret_id"] != secret_id
                ]
                self._compact_positions(
                    connection,
                    workspace_id=workspace_id,
                    ordered_secret_ids=(
                        [secret_id, *other_ids]
                        if activate
                        else [*other_ids, secret_id]
                    ),
                    now_iso=now_iso,
                )
            connection.execute(
                """
                UPDATE apify_key_pool_state
                SET generation = generation + 1,
                    status = CASE WHEN ? THEN 'ready' ELSE status END,
                    active_secret_id = CASE
                        WHEN ? THEN ?
                        ELSE active_secret_id
                    END,
                    blocked_reason = CASE
                        WHEN ? THEN NULL
                        ELSE blocked_reason
                    END,
                    updated_at = ?
                WHERE workspace_id = ?
                """,
                (
                    1 if activate else 0,
                    1 if activate else 0,
                    secret_id,
                    1 if activate else 0,
                    now_iso,
                    workspace_id,
                ),
            )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        return self.public_state(workspace_id)

    def secret_lifecycle(self, secret_id: str) -> dict[str, Any]:
        connection = self.store.connect()
        row = connection.execute(
            f"""
            SELECT
                member.workspace_id,
                member.secret_id,
                member.status,
                COUNT(run.id) AS active_run_count
            FROM apify_key_pool_members AS member
            LEFT JOIN apify_actor_runs AS run
              ON run.workspace_id = member.workspace_id
             AND run.secret_id = member.secret_id
             AND run.status IN ({_NONTERMINAL_RUN_SQL})
            WHERE member.secret_id = ?
            GROUP BY member.workspace_id, member.secret_id, member.status
            """,
            (secret_id,),
        ).fetchone()
        if row is None:
            return {
                "managed": False,
                "busy": False,
                "status": None,
                "active_run_count": 0,
            }
        active_run_count = int(row["active_run_count"] or 0)
        status = str(row["status"])
        return {
            "managed": True,
            "busy": status in {"active", "draining"} or active_run_count > 0,
            "status": status,
            "active_run_count": active_run_count,
            "workspace_id": str(row["workspace_id"]),
        }

    def ensure_secret_mutable(self, secret_id: str) -> dict[str, Any]:
        lifecycle = self.secret_lifecycle(secret_id)
        pool_busy = False
        if lifecycle["managed"]:
            state = self._state_row(
                self.store.connect(),
                str(lifecycle["workspace_id"]),
            )
            pool_busy = state["status"] in {"draining", "blocked"}
        if lifecycle["busy"] or pool_busy:
            raise ApifyKeyBusyError()
        return lifecycle

    def remove_secret(self, secret_id: str) -> dict[str, Any] | None:
        """Remove a non-busy pool member and preserve a complete order."""

        connection = self.store.connect()
        owns_transaction = not connection.in_transaction
        now_iso = self._current_time().isoformat()
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            member = connection.execute(
                """
                SELECT * FROM apify_key_pool_members
                WHERE secret_id = ?
                """,
                (secret_id,),
            ).fetchone()
            if member is None:
                if owns_transaction:
                    connection.commit()
                return None
            workspace_id = str(member["workspace_id"])
            active_run_count = self._nonterminal_count(
                connection,
                workspace_id=workspace_id,
                secret_id=secret_id,
            )
            if member["status"] in {"active", "draining"} or active_run_count:
                raise ApifyKeyBusyError()
            connection.execute(
                """
                DELETE FROM apify_key_pool_members
                WHERE workspace_id = ? AND secret_id = ?
                """,
                (workspace_id, secret_id),
            )
            rows = self._member_rows(connection, workspace_id)
            self._compact_positions(
                connection,
                workspace_id=workspace_id,
                ordered_secret_ids=[str(row["secret_id"]) for row in rows],
                now_iso=now_iso,
            )
            state = self._state_row(connection, workspace_id)
            candidate = None
            if not state["active_secret_id"] and state["status"] not in {
                "draining",
                "blocked",
            }:
                candidate = connection.execute(
                    """
                    SELECT secret_id
                    FROM apify_key_pool_members
                    WHERE workspace_id = ? AND status = 'standby'
                    ORDER BY position
                    LIMIT 1
                    """,
                    (workspace_id,),
                ).fetchone()
                if candidate is not None:
                    connection.execute(
                        """
                        UPDATE apify_key_pool_members
                        SET status = 'active', updated_at = ?
                        WHERE workspace_id = ? AND secret_id = ?
                        """,
                        (now_iso, workspace_id, candidate["secret_id"]),
                    )
            member_exists = bool(rows)
            connection.execute(
                """
                UPDATE apify_key_pool_state
                SET generation = generation + 1,
                    status = CASE
                        WHEN active_secret_id IS NOT NULL THEN 'ready'
                        WHEN ? IS NOT NULL THEN 'ready'
                        WHEN ? THEN 'exhausted'
                        ELSE 'empty'
                    END,
                    active_secret_id = COALESCE(active_secret_id, ?),
                    updated_at = ?
                WHERE workspace_id = ?
                """,
                (
                    candidate["secret_id"] if candidate is not None else None,
                    1 if member_exists else 0,
                    candidate["secret_id"] if candidate is not None else None,
                    now_iso,
                    workspace_id,
                ),
            )
            if owns_transaction:
                connection.commit()
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
        return self.public_state(workspace_id)


__all__ = [
    "APIFY_RUN_TERMINAL_STATUSES",
    "ApifyCredentialLease",
    "ApifyCredentialRejectedError",
    "ApifyKeyBusyError",
    "ApifyKeyDrainPendingError",
    "ApifyKeyPoolBlockedError",
    "ApifyKeyPoolConflictError",
    "ApifyKeyPoolError",
    "ApifyKeyPoolExhaustedError",
    "ApifyKeyPoolService",
    "ApifyQuotaCandidate",
    "ApifyRunLeaseError",
    "apify_key_pool_enabled",
    "apify_pool_generation",
]
