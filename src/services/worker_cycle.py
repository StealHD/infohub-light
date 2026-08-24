"""Worker startup and pre-claim cycle coordination."""

from __future__ import annotations

import logging
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..observability_context import update_observability_context
from ..storage.service_store import ServiceStore
from .apify_actor_alerts import ApifyActorAlertService
from .feed_schedule import FeedScheduleService
from .job_queue import JobQueue
from .maintenance import MaintenanceService  # noqa: F401 - legacy test seam
from .preferred_source_notifications import PreferredSourceNotificationService
from .secret_store import SecretStore
from .source_schedule import SourceScheduleService
from .worker_migration_gate import first_required_worker_startup_migration
from .worker_housekeeping import WorkerCyclePorts, run_worker_housekeeping
from .worker_job_policy import WORKER_CLAIMABLE_JOB_TYPES
from .worker_retired_actorops_jobs import retire_queued_actorops_v1_jobs
from .system_settings import resolve_system_setting


@dataclass(frozen=True, slots=True)
class PreparedWorkerCycle:
    queue: JobQueue
    notifications: PreferredSourceNotificationService
    actor_alerts: ApifyActorAlertService
    job: dict[str, Any]
    lease_seconds: float
    retry_base_seconds: float
    ports: WorkerCyclePorts
    post_claim_housekeeping: Callable[[], None]


@dataclass(frozen=True, slots=True)
class StoppedWorkerCycle:
    result: dict[str, Any] | None


def _recover_stale_jobs(
    queue: JobQueue,
    *,
    emit_operation_event: Callable[..., bool],
) -> None:
    update_observability_context(stage="lease_recovery")
    for recovered in queue.recover_stale_running_jobs(
        allowed_job_types=WORKER_CLAIMABLE_JOB_TYPES,
    ):
        failed = recovered["status"] == "failed"
        emit_operation_event(
            category="job",
            action="lease_recovery",
            outcome="failed" if failed else "retried",
            level="error" if failed else "warning",
            workspace_id=str(recovered["workspace_id"]),
            subject_user_id=str(recovered["user_id"]),
            job_id=str(recovered["job_id"]),
            source_id=recovered.get("source_id"),
            subscription_id=recovered.get("subscription_id"),
            stage="lease_recovery",
            error_code="lease_expired",
            counts={"attempts": int(recovered["attempts"])},
        )


def _emit_schedule_outcomes(
    store: ServiceStore,
    outcomes: list[dict[str, Any]],
    *,
    source_schedule: bool,
    emit_operation_event: Callable[..., bool],
) -> None:
    for outcome in outcomes:
        if outcome.get("action") not in {"enqueued", "deduplicated"}:
            continue
        subscription = None
        if source_schedule:
            subscription = store.get_subscription(str(outcome["subscription_id"]))
            if subscription is None:
                continue
            user = store.get_user(str(subscription["user_id"]))
        else:
            user = store.get_user(str(outcome["user_id"]))
        if user is None:
            continue
        event: dict[str, Any] = {
            "category": "job",
            "action": "scheduled_queue",
            "outcome": (
                "queued" if outcome["action"] == "enqueued" else "skipped"
            ),
            "level": "info",
            "workspace_id": str(user["workspace_id"]),
            "subject_user_id": str(user["id"]),
            "job_id": outcome.get("job_id"),
            "counts": {
                "deduplicated": int(outcome["action"] == "deduplicated")
            },
        }
        if subscription is not None:
            event.update(
                source_id=str(subscription["source_id"]),
                subscription_id=str(subscription["id"]),
            )
        emit_operation_event(**event)


def _enqueue_schedules(
    store: ServiceStore,
    *,
    emit_operation_event: Callable[..., bool],
) -> None:
    update_observability_context(stage="schedule_enqueue")
    feed_result = FeedScheduleService(store).enqueue_due()
    source_result = SourceScheduleService(store).enqueue_due()
    _emit_schedule_outcomes(
        store,
        feed_result["outcomes"],
        source_schedule=False,
        emit_operation_event=emit_operation_event,
    )
    _emit_schedule_outcomes(
        store,
        source_result["outcomes"],
        source_schedule=True,
        emit_operation_event=emit_operation_event,
    )


def _dispatch_notification_backlog(
    store: ServiceStore,
    notifications: PreferredSourceNotificationService,
    actor_alerts: ApifyActorAlertService,
    *,
    logger: logging.Logger,
) -> None:
    update_observability_context(stage="notification_backlog")
    try:
        notifications.dispatch_pending(limit=20)
    except Exception:
        if store.connect().in_transaction:
            store.connect().rollback()
        logger.warning("preferred-source notification backlog dispatch failed")
    try:
        actor_alerts.dispatch_pending(limit=20)
    except Exception:
        if store.connect().in_transaction:
            store.connect().rollback()
        logger.warning("Apify Actor alert backlog dispatch failed")


def prepare_worker_cycle(
    store: ServiceStore,
    *,
    data_dir: str,
    worker_id: str,
    lease_seconds: float | None,
    retry_base_seconds: float | None,
    enqueue_schedules: bool,
    ports: WorkerCyclePorts,
    logger: logging.Logger,
) -> PreparedWorkerCycle | StoppedWorkerCycle:
    update_observability_context(stage="migration_check")
    required_migration = first_required_worker_startup_migration(store)
    if required_migration is not None:
        store.upsert_worker_heartbeat(
            worker_id, "idle", last_error_code="migration_required"
        )
        return StoppedWorkerCycle(
            {
                "ok": False,
                "error_code": "migration_required",
                "migration": required_migration,
            }
        )
    SecretStore(data_dir).load_into_environ()
    queue = JobQueue(store)
    lease = float(
        lease_seconds
        if lease_seconds is not None
        else os.getenv("HORIZON_WORKER_LEASE_SECONDS", "900")
    )
    retire_queued_actorops_v1_jobs(store)
    _recover_stale_jobs(queue, emit_operation_event=ports.emit_operation_event)
    if enqueue_schedules:
        _enqueue_schedules(store, emit_operation_event=ports.emit_operation_event)
    notifications = PreferredSourceNotificationService(store, data_dir=data_dir)
    actor_alerts = ApifyActorAlertService(
        store,
        data_dir=data_dir,
        email_transport=notifications.email_transport,
    )
    _dispatch_notification_backlog(store, notifications, actor_alerts, logger=logger)
    if store.get_worker_heartbeat(worker_id) is None:
        store.upsert_worker_heartbeat(worker_id, "starting")
    update_observability_context(stage="claim")
    job = queue.claim_next_job(
        worker_id=worker_id,
        lease_seconds=lease,
        allowed_job_types=WORKER_CLAIMABLE_JOB_TYPES,
    )
    if job is None:
        run_worker_housekeeping(
            store,
            data_dir=data_dir,
            queue=queue,
            ports=ports,
            logger=logger,
            include_maintenance=True,
        )
        update_observability_context(stage="claim")
        job = queue.claim_next_job(
            worker_id=worker_id,
            lease_seconds=lease,
            allowed_job_types=WORKER_CLAIMABLE_JOB_TYPES,
        )
    if job is None:
        result = ports.run_feed_end_messages(
            data_dir=data_dir,
            store=store,
            worker_id=worker_id,
        )
        store.upsert_worker_heartbeat(
            worker_id,
            "idle",
            last_error_code=(
                result.get("error_code") if result and not result.get("ok") else None
            ),
        )
        return StoppedWorkerCycle(result)
    update_observability_context(
        workspace_id=str(job["workspace_id"]),
        actor_user_id=str(job["user_id"]),
        job_id=str(job["id"]),
        source_id=job.get("source_id"),
        subscription_id=job.get("subscription_id"),
        stage="claim",
    )
    ports.emit_operation_event(
        category="job",
        action="claim",
        outcome="running",
        workspace_id=str(job["workspace_id"]),
        subject_user_id=str(job["user_id"]),
        job_id=str(job["id"]),
        source_id=job.get("source_id"),
        subscription_id=job.get("subscription_id"),
        stage="claim",
        counts={"attempts": int(job.get("attempts") or 0)},
    )
    retry_base = float(
        retry_base_seconds
        if retry_base_seconds is not None
        else resolve_system_setting(
            store, str(job["workspace_id"]), "jobs.retry_base_seconds"
        )
    )
    return PreparedWorkerCycle(
        queue=queue,
        notifications=notifications,
        actor_alerts=actor_alerts,
        job=job,
        lease_seconds=lease,
        retry_base_seconds=retry_base,
        ports=ports,
        post_claim_housekeeping=lambda: run_worker_housekeeping(
            store,
            data_dir=data_dir,
            queue=queue,
            ports=ports,
            logger=logger,
            include_maintenance=False,
        ),
    )
