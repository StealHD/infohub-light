"""Claimed Worker job execution and transaction finalization."""

from __future__ import annotations

import logging
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..observability_context import update_observability_context
from ..storage.service_store import ServiceStore
from .feed_production import FeedRunFailed
from .feed_run import safe_run_diagnostics
from .job_eligibility import JobEligibilityService
from .job_queue import JobQueue
from .media_cache import PostCommitMediaCleanup
from .preferred_source_notifications import PreferredSourceNotificationService
from .source_health import SourceHealthService, sanitize_issue_message


class MigrationRequiredError(RuntimeError):
    """A claimed job cannot cross a pending explicit migration gate."""

    retryable = False


@dataclass(slots=True)
class MediaPublicationState:
    cleanup: PostCommitMediaCleanup | None = None


@dataclass(frozen=True, slots=True)
class FinalizedJob:
    finalized: dict[str, Any]
    failure_fingerprint: str | None


@dataclass(frozen=True, slots=True)
class WorkerFinalizationPorts:
    run_job: Callable[..., dict[str, Any]]
    error_fingerprint: Callable[[], str]
    exception_code: Callable[[Exception], str]
    cancel_claimed_job: Callable[..., dict[str, Any]]
    emit_job_invalidation: Callable[..., None]
    terminalize_failed_discovery: Callable[[ServiceStore, dict[str, Any]], bool]
    terminalize_unstarted_validation: Callable[..., bool]
    is_retryable_exception: Callable[[Exception], bool]
    active_catalog_source_ids: Callable[..., set[str]]


def _require_job_migrations(store: ServiceStore, job_type: str) -> None:
    if job_type in {"source_fetch", "user_feed_refresh"}:
        if store.feed_v2_migration_required():
            raise MigrationRequiredError(
                "user feed v2 migration is required before feed jobs can run"
            )
    if job_type in {"source_fetch", "user_feed_refresh", "content_repair"}:
        if store.content_index_v4_migration_required():
            raise MigrationRequiredError(
                "user content v4 migration is required before feed jobs can run"
            )
        if store.content_timeline_v11_migration_required():
            raise MigrationRequiredError(
                "content timeline v11 migration is required before feed jobs can run"
            )
    checks = (
        (
            store.apify_actor_ops_v15_migration_required,
            "Apify ActorOps v15 migration is required before jobs can run",
        ),
        (
            store.apify_discovery_limits_v16_migration_required,
            "Apify Discovery limits v16 migration is required before jobs can run",
        ),
        (
            store.apify_actor_canary_batches_v17_migration_required,
            "Apify Actor Canary batch migration is required before jobs can run",
        ),
        (
            store.apify_actor_pool_staging_v18_migration_required,
            "Apify Actor pool staging migration is required before jobs can run",
        ),
        (
            store.apify_actor_manual_pool_selection_v19_migration_required,
            "Apify Actor manual pool selection migration is required before jobs can run",
        ),
        (
            store.apify_actor_validation_tuning_v20_migration_required,
            "Apify Actor validation tuning migration is required before jobs can run",
        ),
        (
            store.apify_actor_resilience_v21_migration_required,
            "Apify Actor resilience migration is required before jobs can run",
        ),
    )
    for required, message in checks:
        if required():
            raise MigrationRequiredError(message)


def _stage_preferred_notifications(
    store: ServiceStore,
    notifications: PreferredSourceNotificationService,
    job: dict[str, Any],
    result: dict[str, Any],
    *,
    logger: logging.Logger,
) -> None:
    if not result.get("snapshot_id"):
        return
    connection = store.connect()
    if not connection.in_transaction:
        logger.warning(
            "preferred-source notification staging skipped without feed transaction job_id=%s",
            job.get("id"),
        )
        return
    connection.execute("SAVEPOINT preferred_source_notification_stage")
    try:
        notifications.stage_for_job(
            job=job,
            snapshot_id=str(result["snapshot_id"]),
            snapshot_created=bool(result.get("snapshot_created")),
        )
    except Exception:
        connection.execute("ROLLBACK TO preferred_source_notification_stage")
        connection.execute("RELEASE preferred_source_notification_stage")
        logger.warning(
            "preferred-source notification staging failed job_id=%s",
            job.get("id"),
        )
    else:
        connection.execute("RELEASE preferred_source_notification_stage")


def _cancel_ineligible_job(
    queue: JobQueue,
    store: ServiceStore,
    job: dict[str, Any],
    *,
    reason: str,
    worker_id: str,
    ports: WorkerFinalizationPorts,
) -> dict[str, Any]:
    finalized = ports.cancel_claimed_job(
        queue,
        store,
        job,
        reason=reason,
        worker_id=worker_id,
    )
    ports.emit_job_invalidation(job, reason=reason)
    return finalized


def _apply_failed_feed_health(
    store: ServiceStore,
    job: dict[str, Any],
    finalized: dict[str, Any],
    exc: Exception,
    *,
    ports: WorkerFinalizationPorts,
) -> None:
    if finalized["status"] != "failed" or not isinstance(exc, FeedRunFailed):
        return
    outcomes = exc.result.source_outcomes
    if job["job_type"] == "source_fetch" and job.get("source_id"):
        outcomes = tuple(
            outcome for outcome in outcomes if outcome.source_id == job["source_id"]
        )
    elif job["job_type"] == "user_feed_refresh":
        active_source_ids = ports.active_catalog_source_ids(
            store,
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
        )
        outcomes = tuple(
            outcome for outcome in outcomes if outcome.source_id in active_source_ids
        )
    SourceHealthService(store).apply_outcomes(
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        job_id=job["id"],
        attempted_at=exc.result.finished_at,
        outcomes=outcomes,
        commit=False,
    )


def _finalize_failed_job(
    queue: JobQueue,
    store: ServiceStore,
    job: dict[str, Any],
    exc: Exception,
    *,
    worker_id: str,
    retry_base_seconds: float,
    publication: MediaPublicationState,
    ports: WorkerFinalizationPorts,
    logger: logging.Logger,
) -> FinalizedJob:
    fingerprint = ports.error_fingerprint()
    error_code = ports.exception_code(exc)
    update_observability_context(stage="execute", error_code=error_code)
    logger.exception(
        "job execution failed job_id=%s job_type=%s",
        job["id"],
        job["job_type"],
        extra={"stage": "execute", "error_code": error_code},
    )
    connection = store.connect()
    connection.rollback()
    if publication.cleanup is not None:
        publication.cleanup.discard()
        publication.cleanup = None
    eligibility = JobEligibilityService(store).evaluate_current_attempt(str(job["id"]))
    if not eligibility.allowed:
        reason = str(eligibility.reason or "job_invalidated")
        finalized = _cancel_ineligible_job(
            queue,
            store,
            job,
            reason=reason,
            worker_id=worker_id,
            ports=ports,
        )
        return FinalizedJob(finalized, fingerprint)
    try:
        connection.execute("BEGIN IMMEDIATE")
        ports.terminalize_failed_discovery(store, job)
        ports.terminalize_unstarted_validation(
            store,
            job,
            status="failed",
            semantic_outcome=error_code,
        )
        structured_result = (
            safe_run_diagnostics(exc.result, item_count=0)
            if isinstance(exc, FeedRunFailed)
            else None
        )
        finalized = queue.fail_or_retry_job(
            job["id"],
            error_code=error_code,
            error_message=sanitize_issue_message(str(exc)),
            retryable=ports.is_retryable_exception(exc),
            retry_base_seconds=retry_base_seconds,
            result=structured_result,
            worker_id=worker_id,
            claim_token=job["claim_token"],
            commit=False,
        )
        _apply_failed_feed_health(store, job, finalized, exc, ports=ports)
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return FinalizedJob(finalized, fingerprint)


def _finalize_successful_job(
    queue: JobQueue,
    store: ServiceStore,
    job: dict[str, Any],
    result: dict[str, Any],
    *,
    worker_id: str,
    publication: MediaPublicationState,
    ports: WorkerFinalizationPorts,
) -> FinalizedJob:
    update_observability_context(stage="finalize")
    eligibility = JobEligibilityService(store).evaluate_current_attempt(str(job["id"]))
    if not eligibility.allowed:
        store.connect().rollback()
        if publication.cleanup is not None:
            publication.cleanup.discard()
            publication.cleanup = None
        reason = str(eligibility.reason or "job_invalidated")
        finalized = _cancel_ineligible_job(
            queue,
            store,
            job,
            reason=reason,
            worker_id=worker_id,
            ports=ports,
        )
        return FinalizedJob(finalized, None)
    status = str(result.pop("_job_status", "succeeded"))
    finalized = queue.complete_job(
        job["id"],
        status=status,
        result=result,
        worker_id=worker_id,
        claim_token=job["claim_token"],
        commit=False,
    )
    store.connect().commit()
    cleanup = publication.cleanup
    publication.cleanup = None
    if cleanup is not None:
        cleanup.run()
    return FinalizedJob(finalized, None)


def execute_claimed_job(
    queue: JobQueue,
    store: ServiceStore,
    job: dict[str, Any],
    *,
    data_dir: str,
    worker_id: str,
    retry_base_seconds: float,
    notifications: PreferredSourceNotificationService,
    publication: MediaPublicationState,
    ports: WorkerFinalizationPorts,
    logger: logging.Logger,
) -> FinalizedJob:
    update_observability_context(stage="eligibility")
    eligibility = JobEligibilityService(store).evaluate_current_attempt(str(job["id"]))
    if not eligibility.allowed:
        reason = str(eligibility.reason or "job_invalidated")
        finalized = _cancel_ineligible_job(
            queue,
            store,
            job,
            reason=reason,
            worker_id=worker_id,
            ports=ports,
        )
        return FinalizedJob(finalized, None)
    try:
        update_observability_context(stage="execute")
        _require_job_migrations(store, str(job["job_type"]))
        result = ports.run_job(job, data_dir=data_dir, store=store)
        raw_cleanup = result.pop("_media_cleanup", None)
        if raw_cleanup is not None and not isinstance(
            raw_cleanup, PostCommitMediaCleanup
        ):
            raise RuntimeError("invalid media publication cleanup")
        publication.cleanup = raw_cleanup
        _stage_preferred_notifications(
            store,
            notifications,
            job,
            result,
            logger=logger,
        )
    except Exception as exc:
        return _finalize_failed_job(
            queue,
            store,
            job,
            exc,
            worker_id=worker_id,
            retry_base_seconds=retry_base_seconds,
            publication=publication,
            ports=ports,
            logger=logger,
        )
    return _finalize_successful_job(
        queue,
        store,
        job,
        result,
        worker_id=worker_id,
        publication=publication,
        ports=ports,
    )
