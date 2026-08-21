"""Best-effort Actor/provider housekeeping kept outside the Worker claim path."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..observability_context import update_observability_context
from ..storage.service_store import ServiceStore
from .apify_actor_pool_management_runtime import actor_pool_management_migration_required
from .job_queue import JobQueue
from .maintenance import MaintenanceService


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


def _rollback(store: ServiceStore) -> None:
    if store.connect().in_transaction:
        store.connect().rollback()


def _reconcile_actor_providers(
    store: ServiceStore,
    *,
    data_dir: str,
    ports: WorkerCyclePorts,
    logger: logging.Logger,
) -> None:
    try:
        outcomes = ports.reconcile_apify_pools(store, data_dir=data_dir)
    except Exception:
        _rollback(store)
        logger.warning("Apify pool reconcile failed", exc_info=True)
        outcomes = []
    workspace_ids = {str(outcome["workspace_id"]) for outcome in outcomes}
    for outcome in outcomes:
        workspace_id = str(outcome["workspace_id"])
        if not outcome.get("ok"):
            logger.warning(
                "Apify pool reconcile pending workspace_id=%s code=%s",
                workspace_id,
                outcome.get("code"),
            )
        try:
            actor_route = ports.build_actor_route(
                store,
                data_dir=data_dir,
                workspace_id=workspace_id,
            )
            if actor_route.reconcile_unfinished_attempts()["route_blocked"]:
                logger.warning(
                    "Apify Actor route reconcile blocked workspace_id=%s",
                    workspace_id,
                )
        except Exception:
            _rollback(store)
            logger.warning(
                "Apify Actor route reconcile failed workspace_id=%s",
                workspace_id,
                exc_info=True,
            )
            continue
        try:
            _reconcile_actor_ops(store, workspace_id=workspace_id, data_dir=data_dir, logger=logger)
        except Exception:
            _rollback(store)
            logger.warning(
                "Apify ActorOps reconcile failed workspace_id=%s",
                workspace_id,
                exc_info=True,
            )
        try:
            ports.sync_actor_quota_alert(
                store,
                data_dir=data_dir,
                workspace_id=workspace_id,
                route_state=actor_route.public_state(),
            )
        except Exception:
            _rollback(store)
            logger.warning(
                "Apify Actor quota alert sync failed workspace_id=%s", workspace_id
            )
    _reconcile_actorops_v2(
        store, data_dir=data_dir, workspace_ids=workspace_ids, logger=logger
    )


def _reconcile_actorops_v2(
    store: ServiceStore,
    *,
    data_dir: str,
    workspace_ids: set[str],
    logger: logging.Logger,
) -> None:
    from .actorops.readiness import actorops_v2_enabled

    if not actorops_v2_enabled():
        return
    if not workspace_ids:
        workspace_ids = {
            str(row["id"])
            for row in store.connect().execute("SELECT id FROM workspaces ORDER BY id").fetchall()
        }
    from .actorops.apify_ledger import ApifyRunLedger
    from .actorops.reconciliation import ActorOpsReconciler
    from .actorops.repository import ActorOpsRepository

    for workspace_id in sorted(workspace_ids):
        try:
            summary = asyncio.run(
                ActorOpsReconciler(
                    ActorOpsRepository(store.connect(), workspace_id),
                    ApifyRunLedger(store, workspace_id=workspace_id, data_dir=data_dir),
                ).reconcile()
            )
            if summary.scanned:
                logger.info(
                    "ActorOps v2 reconciliation workspace_id=%s scanned=%s settled=%s",
                    workspace_id,
                    summary.scanned,
                    summary.settled,
                )
        except Exception:
            _rollback(store)
            logger.warning(
                "ActorOps v2 reconciliation failed workspace_id=%s",
                workspace_id,
                exc_info=True,
            )


def _reconcile_actor_ops(
    store: ServiceStore,
    *,
    workspace_id: str,
    data_dir: str,
    logger: logging.Logger,
) -> None:
    from .apify_actor_ops import ApifyActorOpsService
    from .apify_actor_resilience import ApifyActorResilienceService
    from .apify_actor_canary_reconciliation import reconcile_interrupted_canary_runs

    actor_ops = ApifyActorOpsService(store, workspace_id=workspace_id)
    no_start = actor_ops.reconcile_proven_no_start_attempts()
    if no_start["attempts"]:
        logger.info("Apify Actor no-start proof reconciled workspace_id=%s count=%s", workspace_id, no_start["attempts"])
    unfinished = actor_ops.reconcile_unfinished_attempts()
    if unfinished["routes_blocked"]:
        logger.warning("Apify ActorOps reconcile blocked workspace_id=%s", workspace_id)
    reconciled = reconcile_interrupted_canary_runs(store, workspace_id=workspace_id, data_dir=data_dir)
    if reconciled["reconciled"]:
        logger.info("Apify Actor interrupted runs reconciled workspace_id=%s count=%s", workspace_id, reconciled["reconciled"])
    costs = actor_ops.reconcile_terminal_validation_costs()
    if costs["validations"]:
        logger.info("Apify Actor validation costs reconciled workspace_id=%s count=%s", workspace_id, costs["validations"])
    no_start_costs = actor_ops.reconcile_terminal_no_start_validation_costs()
    if no_start_costs["validations"]:
        logger.info("Apify Actor no-start validation costs settled workspace_id=%s count=%s", workspace_id, no_start_costs["validations"])
    freshness_costs = ApifyActorResilienceService(store, workspace_id=workspace_id).reconcile_terminal_freshness_costs()
    if freshness_costs["checks"]:
        logger.info("Apify Actor freshness costs reconciled workspace_id=%s count=%s", workspace_id, freshness_costs["checks"])


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
        lambda: actor_pool_management_migration_required(store),
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


def run_worker_housekeeping(
    store: ServiceStore,
    *,
    data_dir: str,
    queue: JobQueue,
    ports: WorkerCyclePorts,
    logger: logging.Logger,
    include_maintenance: bool,
) -> None:
    """Run bounded control work after a Job or while idle, never before claim."""

    update_observability_context(stage="provider_reconcile")
    _reconcile_actor_providers(store, data_dir=data_dir, ports=ports, logger=logger)
    if not include_maintenance:
        return
    try:
        _run_maintenance_if_due(
            store, promote_actor_revisions=ports.promote_actor_revisions, logger=logger
        )
    except Exception:
        _rollback(store)
        logger.warning("Worker maintenance housekeeping failed", exc_info=True)
    for stage, callback in (
        ("actor_discovery_reconcile", ports.reconcile_actor_discoveries),
        ("actor_freshness_enqueue", ports.enqueue_actor_freshness),
    ):
        try:
            update_observability_context(stage=stage)
            callback(store, queue)
        except Exception:
            _rollback(store)
            logger.warning("Worker housekeeping failed stage=%s", stage, exc_info=True)
    try:
        from .worker_actorops_v2_discovery import enqueue_due_actorops_v2_discoveries

        enqueue_due_actorops_v2_discoveries(store, queue)
    except Exception:
        _rollback(store)
        logger.warning("ActorOps v2 Discovery enqueue failed", exc_info=True)
    try:
        from .worker_actorops_v2_maintenance import enqueue_due_actorops_v2_maintenance

        enqueue_due_actorops_v2_maintenance(store, queue)
    except Exception:
        _rollback(store)
        logger.warning("ActorOps v2 maintenance enqueue failed", exc_info=True)
    try:
        from .worker_actorops_v2_replacement import enqueue_due_actorops_v2_replacements

        enqueue_due_actorops_v2_replacements(store, queue)
    except Exception:
        _rollback(store)
        logger.warning("ActorOps v2 replacement enqueue failed", exc_info=True)


__all__ = ["WorkerCyclePorts", "run_worker_housekeeping"]
