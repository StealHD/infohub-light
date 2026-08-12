"""Worker terminalization, retry, invalidation, and lease lifecycle primitives."""

from __future__ import annotations

import threading
from collections.abc import Callable
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any

import httpx

from ..storage.service_store import ServiceStore
from .job_queue import JobQueue
from .worker_actor_canary_handler import actor_canary_batch_id
from .worker_actor_validation_handler import (
    actor_freshness_check_id,
    actor_validation_id,
)


@dataclass(frozen=True, slots=True)
class WorkerLifecyclePorts:
    exception_code: Callable[[Exception], str]
    safe_machine_code: Callable[[Any, str], str]
    emit_operation_event: Callable[..., None]


def terminalize_failed_actor_discovery(
    store: ServiceStore,
    job: dict[str, Any],
) -> bool:
    """Fail a broken discovery run in the caller's job-finalization transaction."""

    if str(job.get("job_type") or "") != "apify_actor_discovery":
        return False
    payload = job.get("payload_json") if isinstance(job.get("payload_json"), dict) else {}
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        return False
    cursor = store.connect().execute(
        """
        UPDATE apify_actor_discovery_runs
        SET stage = 'failed', error_code = 'apify_actor_discovery_failed',
            updated_at = ?
        WHERE workspace_id = ? AND run_id = ?
          AND stage IN (
              'queued', 'searching', 'metadata', 'ranking',
              'static_validation', 'input_validation'
          )
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            str(job.get("workspace_id") or ""),
            run_id,
        ),
    )
    return cursor.rowcount == 1


def emit_job_invalidation(
    job: dict[str, Any],
    *,
    reason: str,
    ports: WorkerLifecyclePorts,
) -> None:
    ports.emit_operation_event(
        category="job",
        action="invalidate",
        outcome="cancelled",
        level="warning",
        workspace_id=str(job["workspace_id"]),
        subject_user_id=str(job["user_id"]),
        job_id=str(job["id"]),
        source_id=job.get("source_id"),
        subscription_id=job.get("subscription_id"),
        stage="eligibility",
        error_code=ports.safe_machine_code(reason, "job_invalidated"),
    )


def _terminalize_freshness(
    store: ServiceStore,
    job: dict[str, Any],
    *,
    semantic_outcome: str,
) -> bool:
    check_id = actor_freshness_check_id(job)
    if check_id is None:
        return False
    from .apify_actor_resilience import ApifyActorResilienceService

    ApifyActorResilienceService(
        store,
        workspace_id=str(job.get("workspace_id") or ""),
    ).fail_freshness_check(check_id, reason_code=semantic_outcome)
    return True


def _terminalize_canary_batch(
    store: ServiceStore,
    job: dict[str, Any],
    *,
    status: str,
    semantic_outcome: str,
    ports: WorkerLifecyclePorts,
) -> bool | None:
    batch_id = actor_canary_batch_id(job)
    if batch_id is None:
        return None
    if status not in {"failed", "cancelled"}:
        raise ValueError("unstarted Actor batch must become terminal")
    now = datetime.now(timezone.utc).isoformat()
    workspace_id = str(job.get("workspace_id") or "")
    reason = ports.safe_machine_code(
        semantic_outcome,
        "apify_actor_validation_not_started",
    )
    connection = store.connect()
    connection.execute(
        """
        UPDATE apify_actor_validations
        SET status = ?, semantic_outcome = ?, cost_usd = 0,
            cost_final = 1, counts_toward_canary = 0, completed_at = ?
        WHERE workspace_id = ? AND status = 'queued' AND attempt_id IS NULL
          AND validation_id IN (
              SELECT validation_id FROM apify_actor_canary_batch_items
              WHERE workspace_id = ? AND batch_id = ?
          )
        """,
        (status, reason, now, workspace_id, workspace_id, batch_id),
    )
    connection.execute(
        """
        UPDATE apify_actor_canary_batch_items
        SET status = 'not_needed_no_charge', semantic_outcome = ?,
            actual_cost_usd = 0, cost_final = 1,
            completed_at = ?, updated_at = ?
        WHERE workspace_id = ? AND batch_id = ?
          AND status IN ('planned', 'queued', 'preflight_passed')
        """,
        (reason, now, now, workspace_id, batch_id),
    )
    updated = connection.execute(
        """
        UPDATE apify_actor_canary_batches
        SET status = ?, stop_reason = ?, actual_cost_usd = 0,
            cost_final = 1, completed_at = ?, updated_at = ?
        WHERE workspace_id = ? AND batch_id = ?
          AND status IN ('queued', 'preflighting')
        """,
        (status, reason, now, now, workspace_id, batch_id),
    )
    connection.execute(
        """
        UPDATE apify_actor_pool_stages
        SET status = ?, last_error_code = ?, updated_at = ?
        WHERE workspace_id = ?
          AND stage_id = (
              SELECT pool_stage_id FROM apify_actor_canary_batches
              WHERE workspace_id = ? AND batch_id = ?
          )
          AND status IN ('queued', 'validating_route')
        """,
        (status, reason, now, workspace_id, workspace_id, batch_id),
    )
    return updated.rowcount == 1


def _terminalize_single_validation(
    store: ServiceStore,
    job: dict[str, Any],
    *,
    status: str,
    semantic_outcome: str,
    ports: WorkerLifecyclePorts,
) -> bool:
    validation_id = actor_validation_id(job)
    if validation_id is None:
        return False
    if status not in {"failed", "cancelled"}:
        raise ValueError("unstarted Actor validation must become terminal")
    updated = store.connect().execute(
        """
        UPDATE apify_actor_validations
        SET status = ?, semantic_outcome = ?, cost_usd = 0,
            cost_final = 1, counts_toward_canary = 0, completed_at = ?
        WHERE workspace_id = ? AND validation_id = ?
          AND status = 'queued' AND attempt_id IS NULL
        """,
        (
            status,
            ports.safe_machine_code(
                semantic_outcome,
                "apify_actor_validation_not_started",
            ),
            datetime.now(timezone.utc).isoformat(),
            str(job.get("workspace_id") or ""),
            validation_id,
        ),
    )
    return updated.rowcount == 1


def terminalize_unstarted_actor_validation(
    store: ServiceStore,
    job: dict[str, Any],
    *,
    status: str,
    semantic_outcome: str,
    ports: WorkerLifecyclePorts,
) -> bool:
    """Release a paid approval when its Worker job ends before an Attempt."""

    if _terminalize_freshness(
        store,
        job,
        semantic_outcome=semantic_outcome,
    ):
        return True
    batch_result = _terminalize_canary_batch(
        store,
        job,
        status=status,
        semantic_outcome=semantic_outcome,
        ports=ports,
    )
    if batch_result is not None:
        return batch_result
    return _terminalize_single_validation(
        store,
        job,
        status=status,
        semantic_outcome=semantic_outcome,
        ports=ports,
    )


def cancel_claimed_job_with_validation(
    queue: JobQueue,
    store: ServiceStore,
    job: dict[str, Any],
    *,
    reason: str,
    worker_id: str,
    ports: WorkerLifecyclePorts,
) -> dict[str, Any]:
    """Atomically cancel a claim and any paid validation not yet attempted."""

    connection = store.connect()
    owns_transaction = not connection.in_transaction
    try:
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        terminalize_unstarted_actor_validation(
            store,
            job,
            status="cancelled",
            semantic_outcome=reason,
            ports=ports,
        )
        finalized = queue.cancel_claimed_job(
            str(job["id"]),
            reason=reason,
            worker_id=worker_id,
            claim_token=str(job["claim_token"]),
            commit=False,
        )
        if owns_transaction:
            connection.commit()
        return finalized
    except Exception:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        raise


def is_retryable_exception(exc: Exception) -> bool:
    explicit = getattr(exc, "retryable", None)
    if explicit is not None:
        return bool(explicit)
    if isinstance(exc, (ConnectionError, TimeoutError, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


class LeaseHeartbeat:
    """Renew one job lease and publish worker liveness from a separate connection."""

    def __init__(
        self,
        *,
        data_dir: str,
        job: dict[str, Any],
        lease_seconds: float,
        exception_code: Callable[[Exception], str],
    ) -> None:
        self.store = ServiceStore(data_dir)
        self.queue = JobQueue(self.store)
        self.job = job
        self.lease_seconds = lease_seconds
        self.exception_code = exception_code
        self.interval = min(10.0, max(1.0, lease_seconds / 3.0))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_error_code: str | None = None

    def __enter__(self) -> "LeaseHeartbeat":
        self.store.upsert_worker_heartbeat(
            self.job["worker_id"],
            "running",
            current_job_id=self.job["id"],
        )
        self.thread = threading.Thread(
            target=self._run,
            name=f"lease-{self.job['id']}",
            daemon=True,
        )
        self.thread.start()
        return self

    def _run(self) -> None:
        while not self.stop_event.wait(self.interval):
            try:
                self.queue.extend_job_lease(
                    self.job["id"],
                    worker_id=self.job["worker_id"],
                    claim_token=self.job["claim_token"],
                    lease_seconds=self.lease_seconds,
                )
                self.store.upsert_worker_heartbeat(
                    self.job["worker_id"],
                    "running",
                    current_job_id=self.job["id"],
                )
            except Exception as exc:
                self.last_error_code = self.exception_code(exc)
                self.stop_event.set()

    def __exit__(self, exc_type, exc, _traceback) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=max(self.interval * 2, 2.0))
        error_code = (
            self.exception_code(exc) if exc is not None else self.last_error_code
        )
        try:
            self.store.upsert_worker_heartbeat(
                self.job["worker_id"],
                "idle",
                last_job_id=self.job["id"],
                last_error_code=error_code,
            )
        finally:
            self.store.close()
