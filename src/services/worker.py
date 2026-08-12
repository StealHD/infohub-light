"""Worker loop for queued InfoHub service jobs."""

from __future__ import annotations

import argparse
import logging
import os
import re
import time
from typing import Any

from dotenv import load_dotenv

from ..logging_utils import configure_logging, error_fingerprint
from ..observability_context import (
    begin_observability_context,
    reset_observability_context,
    update_observability_context,
)
from ..storage.manager import StorageManager
from .source_probe import run_source_test
from .feed_end_messages import run_due_feed_end_messages_generation
from .job_queue import JobQueue
from .operation_log import safe_emit_operation_event
from .media_cache import MediaCacheService, PostCommitMediaCleanup
from .source_avatar import SourceAvatarService
from .apify_pool_runtime import (
    apify_coordinator_for_workspace,
    reconcile_all_apify_pools_sync,
)
from .apify_key_pool import apify_key_pool_enabled
from .worker_actor_cycle import (
    enqueue_due_actor_freshness_checks as _enqueue_due_actor_freshness_checks_impl,
    promote_due_actor_revisions as _promote_due_actor_revisions_impl,
    reconcile_and_enqueue_actor_discoveries as _reconcile_actor_discoveries_impl,
)
from .worker_actor_canary_handler import (
    WorkerActorCanaryPorts,
    actor_canary_batch_id as _actor_canary_batch_id,
    run_actor_canary_batch,
)
from .worker_actor_discovery_handler import (
    WorkerActorDiscoveryPorts,
    actor_discovery_queries as _actor_discovery_queries,
    run_actor_discovery,
)
from .worker_actor_validation_handler import (
    WorkerActorValidationPorts,
    actor_freshness_check_id as _actor_freshness_check_id,
    actor_validation_id as _actor_validation_id,
    run_actor_freshness_check,
    run_actor_validation,
)
from .worker_cycle import (
    PreparedWorkerCycle,
    StoppedWorkerCycle,
    WorkerCyclePorts,
    prepare_worker_cycle,
)
from .worker_post_commit import WorkerPostCommitPorts, run_worker_post_commit
from .worker_feed_handler import (
    WorkerFeedPorts,
    active_catalog_source_ids,
    run_user_feed_refresh,
)
from .worker_handlers import (
    PaidCanaryAuthorizationError,
    PaidCanaryUnavailableError,
    WorkerHandlerPorts,
    run_job,
    source_payload_from_catalog,
)
from .worker_finalization import (
    MediaPublicationState,
    WorkerFinalizationPorts,
    execute_claimed_job,
)
from .worker_lifecycle import (
    LeaseHeartbeat,
    WorkerLifecyclePorts,
    cancel_claimed_job_with_validation,
    emit_job_invalidation,
    is_retryable_exception as _is_retryable_exception,
    terminalize_failed_actor_discovery as _terminalize_failed_actor_discovery,
    terminalize_unstarted_actor_validation,
)
from .worker_media_publication import (
    WorkerMediaPorts,
    cache_run_media,
    cache_run_source_avatars,
)
from .source_acquisition import shared_acquisition_enabled
from .apify_actor_monitoring import (
    build_apify_actor_route,
    sync_apify_actor_quota_alert,
)
from ..storage.service_store import ServiceStore


logger = logging.getLogger(__name__)
_SAFE_ERROR_CODE_RE = re.compile(r"^[A-Za-z0-9_]{1,96}$")
_SAFE_STAGE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
WORKER_JOB_TRACE_POLICY = {
    "source_test": "aggregate_acquisition",
    "source_fetch": "per_source_acquisition",
    "user_feed_refresh": "per_source_acquisition",
    "content_repair": "job_lifecycle_only",
    "apify_actor_validation": "job_lifecycle_only",
    "apify_actor_canary_batch": "job_lifecycle_only",
    "apify_actor_freshness_check": "job_lifecycle_only",
    "apify_actor_discovery": "job_lifecycle_only",
}


def _source_payload_from_catalog(
    job: dict[str, Any],
    *,
    store: ServiceStore,
) -> dict[str, Any]:
    """Compatibility façade for catalog payload projection callers."""

    return source_payload_from_catalog(job, store=store)


def _promote_due_actor_revisions(store: ServiceStore) -> dict[str, int]:
    """Compatibility seam for tests and operational overrides."""

    return _promote_due_actor_revisions_impl(store)


def _reconcile_and_enqueue_actor_discoveries(
    store: ServiceStore,
    queue: JobQueue,
) -> dict[str, int]:
    """Compatibility seam for tests and operational overrides."""

    return _reconcile_actor_discoveries_impl(store, queue)


def _enqueue_due_actor_freshness_checks(
    store: ServiceStore,
    queue: JobQueue,
) -> dict[str, int]:
    """Compatibility seam for tests and operational overrides."""

    return _enqueue_due_actor_freshness_checks_impl(store, queue)


def _exception_code(exc: Exception) -> str:
    """Prefer a bounded stable domain code without trusting arbitrary text."""

    candidate = str(getattr(exc, "code", "") or "").strip()
    return candidate if _SAFE_ERROR_CODE_RE.fullmatch(candidate) else type(exc).__name__


def _safe_machine_code(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip()
    return (
        candidate
        if _SAFE_ERROR_CODE_RE.fullmatch(candidate)
        else fallback
    )


def _emit_source_outcome_events(
    job: dict[str, Any],
    result_payload: dict[str, Any],
    *,
    failure_fingerprint: str | None = None,
) -> None:
    outcomes = result_payload.get("source_outcomes")
    if not isinstance(outcomes, list):
        return
    for outcome in outcomes:
        if not isinstance(outcome, dict):
            continue
        status = str(outcome.get("status") or "")
        source_id = outcome.get("source_id")
        if status not in {"succeeded", "failed"} or not source_id:
            continue
        issue = (
            outcome.get("issue")
            if isinstance(outcome.get("issue"), dict)
            else {}
        )
        raw_stage = str(issue.get("stage") or "")
        stage = (
            raw_stage
            if _SAFE_STAGE_RE.fullmatch(raw_stage)
            else "acquisition"
        )
        error_code = (
            _safe_machine_code(issue.get("code"), "source_failed")
            if status == "failed"
            else None
        )
        fetched_count = outcome.get("fetched_count")
        safe_emit_operation_event(
            category="acquisition",
            action="source_result",
            outcome=status,
            level="error" if status == "failed" else "info",
            workspace_id=str(job["workspace_id"]),
            subject_user_id=str(job["user_id"]),
            job_id=str(job["id"]),
            source_id=str(source_id),
            subscription_id=outcome.get("subscription_id"),
            stage=stage,
            error_code=error_code,
            error_fingerprint=(
                failure_fingerprint if status == "failed" else None
            ),
            counts={
                "items": (
                    max(int(fetched_count), 0)
                    if isinstance(fetched_count, int)
                    and not isinstance(fetched_count, bool)
                    else 0
                )
            },
        )


def _lifecycle_ports() -> WorkerLifecyclePorts:
    return WorkerLifecyclePorts(
        exception_code=_exception_code,
        safe_machine_code=_safe_machine_code,
        emit_operation_event=safe_emit_operation_event,
    )


def _emit_job_invalidation(job: dict[str, Any], *, reason: str) -> None:
    emit_job_invalidation(job, reason=reason, ports=_lifecycle_ports())


def _terminalize_unstarted_actor_validation(
    store: ServiceStore,
    job: dict[str, Any],
    *,
    status: str,
    semantic_outcome: str,
) -> bool:
    return terminalize_unstarted_actor_validation(
        store,
        job,
        status=status,
        semantic_outcome=semantic_outcome,
        ports=_lifecycle_ports(),
    )


def _cancel_claimed_job_with_validation(
    queue: JobQueue,
    store: ServiceStore,
    job: dict[str, Any],
    *,
    reason: str,
    worker_id: str,
) -> dict[str, Any]:
    return cancel_claimed_job_with_validation(
        queue,
        store,
        job,
        reason=reason,
        worker_id=worker_id,
        ports=_lifecycle_ports(),
    )


def _media_ports() -> WorkerMediaPorts:
    return WorkerMediaPorts(
        media_cache_service=MediaCacheService,
        source_avatar_service=SourceAvatarService,
        emit_operation_event=safe_emit_operation_event,
        log_warning=logger.warning,
    )


def _cache_run_media(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    items: list[Any],
    commit: bool = True,
    publication_cleanup: PostCommitMediaCleanup | None = None,
) -> None:
    cache_run_media(
        job,
        data_dir=data_dir,
        store=store,
        items=items,
        commit=commit,
        publication_cleanup=publication_cleanup,
        ports=_media_ports(),
    )


def _cache_run_source_avatars(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    result: Any,
    commit: bool = True,
    publication_cleanup: PostCommitMediaCleanup | None = None,
) -> None:
    cache_run_source_avatars(
        job,
        data_dir=data_dir,
        store=store,
        result=result,
        commit=commit,
        publication_cleanup=publication_cleanup,
        ports=_media_ports(),
    )


def _actor_validation_ports() -> WorkerActorValidationPorts:
    return WorkerActorValidationPorts(
        apify_coordinator=apify_coordinator_for_workspace,
        exception_code=_exception_code,
        safe_machine_code=_safe_machine_code,
    )


def _run_apify_actor_validation(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    """Compatibility façade for Worker tests and operational overrides."""

    return run_actor_validation(
        job,
        data_dir=data_dir,
        store=store,
        ports=_actor_validation_ports(),
    )


def _run_apify_actor_canary_batch(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    """Compatibility façade for Worker tests and operational overrides."""

    return run_actor_canary_batch(
        job,
        data_dir=data_dir,
        store=store,
        ports=WorkerActorCanaryPorts(
            apify_coordinator=apify_coordinator_for_workspace,
        ),
    )


def _run_apify_actor_freshness_check(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    """Compatibility façade for Worker tests and operational overrides."""

    return run_actor_freshness_check(
        job,
        data_dir=data_dir,
        store=store,
        ports=_actor_validation_ports(),
    )


def _log_actor_discovery_ai_close_failure() -> None:
    logger.warning(
        "Actor discovery AI client close failed error_code=ai_client_close_failed"
    )


def _run_apify_actor_discovery(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    """Compatibility façade for Worker tests and operational overrides."""

    return run_actor_discovery(
        job,
        data_dir=data_dir,
        store=store,
        ports=WorkerActorDiscoveryPorts(
            safe_machine_code=_safe_machine_code,
            log_close_failure=_log_actor_discovery_ai_close_failure,
        ),
    )


def _run_job(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    """Compatibility façade over the explicit Worker handler registry."""

    feed_ports = WorkerFeedPorts(
        cache_source_avatars=_cache_run_source_avatars,
        cache_media=_cache_run_media,
        apify_coordinator=apify_coordinator_for_workspace,
        build_actor_route=build_apify_actor_route,
        apify_key_pool_enabled=apify_key_pool_enabled,
        shared_acquisition_enabled=shared_acquisition_enabled,
    )

    def feed_refresh(
        feed_job: dict[str, Any],
        *,
        data_dir: str,
        store: ServiceStore,
    ) -> dict[str, Any]:
        return run_user_feed_refresh(
            feed_job,
            data_dir=data_dir,
            store=store,
            ports=feed_ports,
        )

    return run_job(
        job,
        data_dir=data_dir,
        store=store,
        ports=WorkerHandlerPorts(
            actor_handlers={
                "apify_actor_discovery": _run_apify_actor_discovery,
                "apify_actor_validation": _run_apify_actor_validation,
                "apify_actor_canary_batch": _run_apify_actor_canary_batch,
                "apify_actor_freshness_check": _run_apify_actor_freshness_check,
            },
            run_user_feed_refresh=feed_refresh,
            run_source_test=run_source_test,
            apify_coordinator=apify_coordinator_for_workspace,
            build_actor_route=build_apify_actor_route,
            apify_key_pool_enabled=apify_key_pool_enabled,
            shared_acquisition_enabled=shared_acquisition_enabled,
        ),
    )


def run_worker_once(
    *,
    data_dir: str = "data",
    worker_id: str = "horizon-worker",
    lease_seconds: float | None = None,
    retry_base_seconds: float | None = None,
    enqueue_schedules: bool = True,
) -> dict[str, Any] | None:
    started_at = time.monotonic()
    store = ServiceStore(data_dir)
    job: dict[str, Any] | None = None
    failure_fingerprint: str | None = None
    publication = MediaPublicationState()
    context_token = begin_observability_context(stage="startup")
    try:
        store.initialize()
        prepared_cycle = prepare_worker_cycle(
            store,
            data_dir=data_dir,
            worker_id=worker_id,
            lease_seconds=lease_seconds,
            retry_base_seconds=retry_base_seconds,
            enqueue_schedules=enqueue_schedules,
            ports=WorkerCyclePorts(
                reconcile_apify_pools=reconcile_all_apify_pools_sync,
                build_actor_route=build_apify_actor_route,
                sync_actor_quota_alert=sync_apify_actor_quota_alert,
                promote_actor_revisions=_promote_due_actor_revisions,
                reconcile_actor_discoveries=_reconcile_and_enqueue_actor_discoveries,
                enqueue_actor_freshness=_enqueue_due_actor_freshness_checks,
                run_feed_end_messages=run_due_feed_end_messages_generation,
                emit_operation_event=safe_emit_operation_event,
            ),
            logger=logger,
        )
        if isinstance(prepared_cycle, StoppedWorkerCycle):
            return prepared_cycle.result
        if not isinstance(prepared_cycle, PreparedWorkerCycle):
            raise RuntimeError("invalid prepared Worker cycle")
        queue = prepared_cycle.queue
        notifications = prepared_cycle.notifications
        actor_alerts = prepared_cycle.actor_alerts
        job = prepared_cycle.job
        lease = prepared_cycle.lease_seconds
        retry_base = prepared_cycle.retry_base_seconds
        with LeaseHeartbeat(
            data_dir=data_dir,
            job=job,
            lease_seconds=lease,
            exception_code=_exception_code,
        ):
            finalization = execute_claimed_job(
                queue,
                store,
                job,
                data_dir=data_dir,
                worker_id=worker_id,
                retry_base_seconds=retry_base,
                notifications=notifications,
                publication=publication,
                ports=WorkerFinalizationPorts(
                    run_job=_run_job,
                    error_fingerprint=error_fingerprint,
                    exception_code=_exception_code,
                    cancel_claimed_job=_cancel_claimed_job_with_validation,
                    emit_job_invalidation=_emit_job_invalidation,
                    terminalize_failed_discovery=_terminalize_failed_actor_discovery,
                    terminalize_unstarted_validation=(
                        _terminalize_unstarted_actor_validation
                    ),
                    is_retryable_exception=_is_retryable_exception,
                    active_catalog_source_ids=active_catalog_source_ids,
                ),
                logger=logger,
            )
        finalized = finalization.finalized
        failure_fingerprint = finalization.failure_fingerprint
        return run_worker_post_commit(
            store,
            notifications=notifications,
            actor_alerts=actor_alerts,
            job=job,
            finalized=finalized,
            started_at=started_at,
            failure_fingerprint=failure_fingerprint,
            ports=WorkerPostCommitPorts(
                exception_code=_exception_code,
                emit_operation_event=safe_emit_operation_event,
                emit_source_outcomes=_emit_source_outcome_events,
            ),
            logger=logger,
        )
    except Exception as exc:
        boundary_fingerprint = error_fingerprint()
        boundary_error_code = _exception_code(exc)
        update_observability_context(
            stage="worker_boundary",
            error_code=boundary_error_code,
        )
        if job is not None:
            logger.exception(
                "job_id=%s job_type=%s duration_ms=%d status=error",
                job["id"],
                job["job_type"],
                int((time.monotonic() - started_at) * 1000),
                extra={
                    "stage": "worker_boundary",
                    "error_code": boundary_error_code,
                },
            )
            safe_emit_operation_event(
                category="job",
                action="worker_boundary",
                outcome="failed",
                level="error",
                workspace_id=str(job["workspace_id"]),
                subject_user_id=str(job["user_id"]),
                job_id=str(job["id"]),
                source_id=job.get("source_id"),
                subscription_id=job.get("subscription_id"),
                stage="worker_boundary",
                error_code=boundary_error_code,
                error_fingerprint=boundary_fingerprint,
                duration_ms=int((time.monotonic() - started_at) * 1000),
            )
        else:
            logger.exception(
                "worker pre-claim boundary failed duration_ms=%d",
                int((time.monotonic() - started_at) * 1000),
                extra={
                    "stage": "worker_boundary",
                    "error_code": boundary_error_code,
                },
            )
            safe_emit_operation_event(
                category="job",
                action="worker_boundary",
                outcome="failed",
                level="error",
                stage="worker_boundary",
                error_code=boundary_error_code,
                error_fingerprint=boundary_fingerprint,
                duration_ms=int(
                    (time.monotonic() - started_at) * 1000
                ),
            )
        raise
    finally:
        if publication.cleanup is not None:
            if store.connect().in_transaction:
                store.connect().rollback()
            publication.cleanup.discard()
        store.close()
        reset_observability_context(context_token)


def main() -> None:
    parser = argparse.ArgumentParser(description="Run InfoHub queued jobs")
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--worker-id", default=os.getenv("HORIZON_WORKER_ID", "horizon-worker"))
    parser.add_argument("--once", action="store_true")
    parser.add_argument("--healthcheck", action="store_true")
    parser.add_argument("--max-heartbeat-age", type=float, default=35.0)
    parser.add_argument("--poll-seconds", type=float, default=float(os.getenv("HORIZON_WORKER_POLL_SECONDS", "5")))
    parser.add_argument(
        "--schedule-poll-seconds",
        type=float,
        default=float(os.getenv("HORIZON_SCHEDULE_POLL_SECONDS", "30")),
    )
    parser.add_argument("--lease-seconds", type=float, default=float(os.getenv("HORIZON_WORKER_LEASE_SECONDS", "900")))
    parser.add_argument(
        "--retry-base-seconds",
        type=float,
        default=float(os.getenv("HORIZON_WORKER_RETRY_BASE_SECONDS", "30")),
    )
    args = parser.parse_args()

    load_dotenv()
    if args.healthcheck:
        from .runtime_status import RuntimeStatusService

        store = ServiceStore(args.data_dir)
        store.initialize()
        heartbeat = RuntimeStatusService(store).get_worker(args.worker_id)
        raise SystemExit(0 if heartbeat and not heartbeat["is_stale"] else 1)
    configure_logging(service="worker")
    if args.once:
        run_worker_once(
            data_dir=args.data_dir,
            worker_id=args.worker_id,
            lease_seconds=args.lease_seconds,
            retry_base_seconds=args.retry_base_seconds,
        )
        return

    last_schedule_check: float | None = None
    try:
        while True:
            loop_started_at = time.monotonic()
            check_schedules = (
                last_schedule_check is None
                or loop_started_at - last_schedule_check >= max(args.schedule_poll_seconds, 0.5)
            )
            run_worker_once(
                data_dir=args.data_dir,
                worker_id=args.worker_id,
                lease_seconds=args.lease_seconds,
                retry_base_seconds=args.retry_base_seconds,
                enqueue_schedules=check_schedules,
            )
            if check_schedules:
                last_schedule_check = loop_started_at
            time.sleep(max(args.poll_seconds, 0.5))
    finally:
        try:
            store = ServiceStore(args.data_dir)
            store.initialize()
            store.upsert_worker_heartbeat(args.worker_id, "stopping")
        except Exception:
            pass


if __name__ == "__main__":
    main()
