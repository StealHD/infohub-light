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


@dataclass(frozen=True, slots=True)
class WorkerLifecyclePorts:
    exception_code: Callable[[Exception], str]
    safe_machine_code: Callable[[Any, str], str]
    emit_operation_event: Callable[..., None]


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


def cancel_claimed_job(
    queue: JobQueue,
    store: ServiceStore,
    job: dict[str, Any],
    *,
    reason: str,
    worker_id: str,
    ports: WorkerLifecyclePorts,
) -> dict[str, Any]:
    """Cancel a current claim without touching retired ActorOps facts."""

    connection = store.connect()
    owns_transaction = not connection.in_transaction
    try:
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        finalized = queue.cancel_claimed_job(
            str(job["id"]),
            reason=reason,
            worker_id=worker_id,
            claim_token=str(job["claim_token"]),
            error_code=(
                "job_cancelled" if reason == "user_cancelled" else "job_invalidated"
            ),
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
