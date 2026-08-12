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
from .maintenance import MaintenanceService
from .preferred_source_notifications import PreferredSourceNotificationService
from .secret_store import SecretStore
from .source_schedule import SourceScheduleService
from .worker_migration_gate import first_required_worker_startup_migration


@dataclass(frozen=True, slots=True)
class WorkerCyclePorts:
    reconcile_apify_pools: Callable[..., list[dict[str, Any]]]
    build_actor_route: Callable[..., Any]
    sync_actor_quota_alert: Callable[..., Any]
    promote_actor_revisions: Callable[[ServiceStore], dict[str, int]]
    reconcile_actor_discoveries: Callable[[ServiceStore, JobQueue], dict[str, int]]
    enqueue_actor_freshness: Callable[[ServiceStore, JobQueue], dict[str, int]]
    run_feed_end_messages: Callable[..., dict[str, Any] | None]
    emit_operation_event: Callable[..., bool]


@dataclass(frozen=True, slots=True)
class PreparedWorkerCycle:
    queue: JobQueue
    notifications: PreferredSourceNotificationService
    actor_alerts: ApifyActorAlertService
    job: dict[str, Any]
    lease_seconds: float
    retry_base_seconds: float


@dataclass(frozen=True, slots=True)
class StoppedWorkerCycle:
    result: dict[str, Any] | None


def _reconcile_actor_providers(
    store: ServiceStore,
    *,
    data_dir: str,
    ports: WorkerCyclePorts,
    logger: logging.Logger,
) -> None:
    outcomes = ports.reconcile_apify_pools(store, data_dir=data_dir)
    for outcome in outcomes:
        if not outcome["ok"]:
            logger.warning(
                "Apify pool reconcile pending workspace_id=%s code=%s",
                outcome["workspace_id"],
                outcome["code"],
            )
        workspace_id = str(outcome["workspace_id"])
        actor_route = ports.build_actor_route(
            store,
            data_dir=data_dir,
            workspace_id=workspace_id,
        )
        route_reconcile = actor_route.reconcile_unfinished_attempts()
        if route_reconcile["route_blocked"]:
            logger.warning(
                "Apify Actor route reconcile blocked workspace_id=%s",
                outcome["workspace_id"],
            )
        _reconcile_actor_ops(store, workspace_id=workspace_id, logger=logger)
        try:
            ports.sync_actor_quota_alert(
                store,
                data_dir=data_dir,
                workspace_id=workspace_id,
                route_state=actor_route.public_state(),
            )
        except Exception:
            if store.connect().in_transaction:
                store.connect().rollback()
            logger.warning(
                "Apify Actor quota alert sync failed workspace_id=%s",
                outcome["workspace_id"],
            )


def _reconcile_actor_ops(
    store: ServiceStore,
    *,
    workspace_id: str,
    logger: logging.Logger,
) -> None:
    from .apify_actor_ops import ApifyActorOpsService
    from .apify_actor_resilience import ApifyActorResilienceService

    actor_ops = ApifyActorOpsService(store, workspace_id=workspace_id)
    no_start = actor_ops.reconcile_proven_no_start_attempts()
    if no_start["attempts"]:
        logger.info(
            "Apify Actor no-start proof reconciled workspace_id=%s count=%s",
            workspace_id,
            no_start["attempts"],
        )
    unfinished = actor_ops.reconcile_unfinished_attempts()
    if unfinished["routes_blocked"]:
        logger.warning(
            "Apify ActorOps reconcile blocked workspace_id=%s",
            workspace_id,
        )
    costs = actor_ops.reconcile_terminal_validation_costs()
    if costs["validations"]:
        logger.info(
            "Apify Actor validation costs reconciled workspace_id=%s count=%s",
            workspace_id,
            costs["validations"],
        )
    freshness_costs = ApifyActorResilienceService(
        store,
        workspace_id=workspace_id,
    ).reconcile_terminal_freshness_costs()
    if freshness_costs["checks"]:
        logger.info(
            "Apify Actor freshness costs reconciled workspace_id=%s count=%s",
            workspace_id,
            freshness_costs["checks"],
        )


def _maintenance_is_safe(store: ServiceStore) -> bool:
    checks = (
        store.feed_storage_v3_migration_required,
        store.content_index_v4_migration_required,
        store.content_timeline_v11_migration_required,
        store.apify_actor_routing_v13_migration_required,
        store.webhook_providers_v14_migration_required,
        store.multichannel_notifications_v15_migration_required,
        store.notification_targets_v16_migration_required,
        store.apify_actor_ops_v15_migration_required,
        store.apify_discovery_limits_v16_migration_required,
        store.apify_actor_canary_batches_v17_migration_required,
        store.apify_actor_pool_staging_v18_migration_required,
        store.apify_actor_manual_pool_selection_v19_migration_required,
        store.apify_actor_validation_tuning_v20_migration_required,
        store.apify_actor_resilience_v21_migration_required,
    )
    return not any(check() for check in checks)


def _run_maintenance_if_due(
    store: ServiceStore,
    *,
    promote_actor_revisions: Callable[[ServiceStore], dict[str, int]],
    logger: logging.Logger,
) -> None:
    if not _maintenance_is_safe(store):
        return
    update_observability_context(stage="maintenance")
    if not bool(MaintenanceService(store).run_if_due().get("ran")):
        return
    try:
        promote_actor_revisions(store)
    except Exception:
        logger.warning("Actor revision certification maintenance failed", exc_info=True)
    try:
        from .apify_actor_maintenance import run_due_actor_metadata_checks

        run_due_actor_metadata_checks(store)
    except Exception:
        logger.warning("Actor metadata maintenance failed", exc_info=True)


def _recover_stale_jobs(
    queue: JobQueue,
    *,
    emit_operation_event: Callable[..., bool],
) -> None:
    update_observability_context(stage="lease_recovery")
    for recovered in queue.recover_stale_running_jobs():
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
    update_observability_context(stage="provider_reconcile")
    _reconcile_actor_providers(store, data_dir=data_dir, ports=ports, logger=logger)
    _run_maintenance_if_due(
        store,
        promote_actor_revisions=ports.promote_actor_revisions,
        logger=logger,
    )
    queue = JobQueue(store)
    lease = float(
        lease_seconds
        if lease_seconds is not None
        else os.getenv("HORIZON_WORKER_LEASE_SECONDS", "900")
    )
    retry_base = float(
        retry_base_seconds
        if retry_base_seconds is not None
        else os.getenv("HORIZON_WORKER_RETRY_BASE_SECONDS", "30")
    )
    _recover_stale_jobs(queue, emit_operation_event=ports.emit_operation_event)
    ports.reconcile_actor_discoveries(store, queue)
    ports.enqueue_actor_freshness(store, queue)
    queue.prune_terminal_jobs()
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
    job = queue.claim_next_job(worker_id=worker_id, lease_seconds=lease)
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
    return PreparedWorkerCycle(
        queue=queue,
        notifications=notifications,
        actor_alerts=actor_alerts,
        job=job,
        lease_seconds=lease,
        retry_base_seconds=retry_base,
    )
