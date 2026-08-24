"""Best-effort v2 control work kept outside the Worker claim path."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..observability_context import update_observability_context
from ..storage.service_store import ServiceStore
from .job_queue import JobQueue
from .maintenance import MaintenanceService


@dataclass(frozen=True, slots=True)
class WorkerCyclePorts:
    run_feed_end_messages: Callable[..., dict[str, Any] | None]
    emit_operation_event: Callable[..., bool]


def _rollback(store: ServiceStore) -> None:
    if store.connect().in_transaction:
        store.connect().rollback()


def _reconcile_actorops_v2(
    store: ServiceStore,
    *,
    data_dir: str,
    logger: logging.Logger,
) -> None:
    from .actorops.readiness import actorops_v2_startup_migration_required

    # ActorOps is unavailable until its explicit single-track migration is
    # installed.  Housekeeping must not turn that local condition into a
    # failure for ordinary RSS/GitHub Worker work.
    if actorops_v2_startup_migration_required(store):
        return
    from .actorops.apify_ledger import ApifyRunLedger
    from .actorops.reconciliation import ActorOpsReconciler
    from .actorops.repository import ActorOpsRepository

    workspace_ids = [
        str(row["id"])
        for row in store.connect().execute(
            "SELECT id FROM workspaces ORDER BY id"
        ).fetchall()
    ]
    for workspace_id in workspace_ids:
        try:
            summary = asyncio.run(
                ActorOpsReconciler(
                    ActorOpsRepository(store.connect(), workspace_id),
                    ApifyRunLedger(
                        store,
                        workspace_id=workspace_id,
                        data_dir=data_dir,
                    ),
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


def _run_maintenance_if_due(store: ServiceStore) -> None:
    """Run generic retention without making it depend on retired ActorOps schema."""

    if (
        store.feed_storage_v3_migration_required()
        or store.content_index_v4_migration_required()
        or store.content_timeline_v11_migration_required()
    ):
        return
    update_observability_context(stage="maintenance")
    MaintenanceService(store).run_if_due()


def _run_v2_enqueuers(
    store: ServiceStore,
    queue: JobQueue,
    *,
    logger: logging.Logger,
) -> None:
    from .worker_actorops_v2_discovery import enqueue_due_actorops_v2_discoveries
    from .worker_actorops_v2_maintenance import enqueue_due_actorops_v2_maintenance
    from .worker_actorops_v2_replacement import enqueue_due_actorops_v2_replacements
    from .worker_actorops_v2_repair import enqueue_due_actorops_v2_repairs

    for stage, enqueue in (
        ("actorops_v2_discovery_enqueue", enqueue_due_actorops_v2_discoveries),
        ("actorops_v2_maintenance_enqueue", enqueue_due_actorops_v2_maintenance),
        ("actorops_v2_replacement_enqueue", enqueue_due_actorops_v2_replacements),
        ("actorops_v2_repair_enqueue", enqueue_due_actorops_v2_repairs),
    ):
        try:
            update_observability_context(stage=stage)
            enqueue(store, queue)
        except Exception:
            _rollback(store)
            logger.warning(
                "ActorOps v2 housekeeping failed stage=%s",
                stage,
                exc_info=True,
            )


def run_worker_housekeeping(
    store: ServiceStore,
    *,
    data_dir: str,
    queue: JobQueue,
    ports: WorkerCyclePorts,
    logger: logging.Logger,
    include_maintenance: bool,
) -> None:
    """Run bounded v2 control work after a Job or while idle, never before claim."""

    update_observability_context(stage="actorops_v2_reconcile")
    _reconcile_actorops_v2(store, data_dir=data_dir, logger=logger)
    if not include_maintenance:
        return
    try:
        _run_maintenance_if_due(store)
    except Exception:
        _rollback(store)
        logger.warning("Worker retention housekeeping failed", exc_info=True)
    _run_v2_enqueuers(store, queue, logger=logger)


__all__ = ["WorkerCyclePorts", "run_worker_housekeeping"]
