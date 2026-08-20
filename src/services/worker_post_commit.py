"""Worker dispatch and telemetry that must run only after job commit."""

from __future__ import annotations

import logging
import time
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..observability_context import update_observability_context
from ..storage.service_store import ServiceStore
from .apify_actor_alerts import ApifyActorAlertService
from .preferred_source_notifications import PreferredSourceNotificationService


@dataclass(frozen=True, slots=True)
class WorkerPostCommitPorts:
    exception_code: Callable[[Exception], str]
    emit_operation_event: Callable[..., bool]
    emit_source_outcomes: Callable[..., None]


def _dispatch_preferred_notifications(
    store: ServiceStore,
    notifications: PreferredSourceNotificationService,
    job: dict[str, Any],
    *,
    ports: WorkerPostCommitPorts,
    logger: logging.Logger,
) -> None:
    update_observability_context(stage="notification_dispatch")
    try:
        summary = notifications.dispatch_pending(job_id=str(job["id"]))
    except Exception as exc:
        if store.connect().in_transaction:
            store.connect().rollback()
        logger.warning(
            "preferred-source notification dispatch failed job_id=%s",
            job.get("id"),
        )
        ports.emit_operation_event(
            category="notification",
            action="dispatch",
            outcome="failed",
            level="error",
            workspace_id=str(job["workspace_id"]),
            subject_user_id=str(job["user_id"]),
            job_id=str(job["id"]),
            source_id=job.get("source_id"),
            subscription_id=job.get("subscription_id"),
            error_code=ports.exception_code(exc),
        )
        return
    if int(summary.get("claimed") or 0) <= 0:
        return
    failed = int(summary.get("failed") or 0)
    succeeded = int(summary.get("succeeded") or 0)
    if failed and succeeded:
        outcome, level = "partial", "warning"
    elif failed:
        outcome, level = "failed", "error"
    else:
        outcome, level = "succeeded", "info"
    ports.emit_operation_event(
        category="notification",
        action="dispatch",
        outcome=outcome,
        level=level,
        workspace_id=str(job["workspace_id"]),
        subject_user_id=str(job["user_id"]),
        job_id=str(job["id"]),
        source_id=job.get("source_id"),
        subscription_id=job.get("subscription_id"),
        counts={
            "claimed": int(summary["claimed"]),
            "failed": failed,
            "succeeded": succeeded,
        },
    )


def _dispatch_actor_alerts(
    store: ServiceStore,
    actor_alerts: ApifyActorAlertService,
    job: dict[str, Any],
    *,
    logger: logging.Logger,
) -> None:
    try:
        actor_alerts.dispatch_pending(
            workspace_id=str(job["workspace_id"]),
            limit=20,
        )
    except Exception:
        if store.connect().in_transaction:
            store.connect().rollback()
        logger.warning(
            "Apify Actor alert dispatch failed job_id=%s",
            job.get("id"),
        )


def _emit_finish_events(
    job: dict[str, Any],
    finalized: dict[str, Any],
    *,
    started_at: float,
    failure_fingerprint: str | None,
    ports: WorkerPostCommitPorts,
    logger: logging.Logger,
) -> None:
    result = finalized.get("result_json") or {}
    status = str(finalized["status"])
    outcome = {
        "queued": "retried",
        "succeeded": "succeeded",
        "partial": "partial",
        "failed": "failed",
        "cancelled": "cancelled",
    }.get(status, "failed")
    if outcome == "failed":
        level = "error"
    elif outcome in {"partial", "retried"}:
        level = "warning"
    else:
        level = "info"
    duration_ms = int((time.monotonic() - started_at) * 1000)
    counts = {"attempts": int(finalized.get("attempts") or 0)}
    if isinstance(result.get("item_count"), int):
        counts["items"] = max(int(result["item_count"]), 0)
    update_observability_context(
        stage="finish",
        error_code=str(finalized.get("error_code") or ""),
    )
    fingerprint = failure_fingerprint if outcome in {"failed", "retried"} else None
    ports.emit_operation_event(
        category="job",
        action="finish",
        outcome=outcome,
        level=level,
        workspace_id=str(job["workspace_id"]),
        subject_user_id=str(job["user_id"]),
        job_id=str(job["id"]),
        source_id=job.get("source_id"),
        subscription_id=job.get("subscription_id"),
        stage="finish",
        error_code=finalized.get("error_code"),
        error_fingerprint=fingerprint,
        duration_ms=duration_ms,
        counts=counts,
    )
    ports.emit_source_outcomes(
        job,
        result,
        failure_fingerprint=failure_fingerprint,
    )
    if job["job_type"] in {"source_test", "source_fetch", "user_feed_refresh"}:
        ports.emit_operation_event(
            category="acquisition",
            action="test" if job["job_type"] == "source_test" else "fetch",
            outcome=outcome,
            level=level,
            workspace_id=str(job["workspace_id"]),
            subject_user_id=str(job["user_id"]),
            job_id=str(job["id"]),
            source_id=job.get("source_id"),
            subscription_id=job.get("subscription_id"),
            stage="acquisition",
            error_code=finalized.get("error_code"),
            error_fingerprint=fingerprint,
            duration_ms=duration_ms,
            counts=counts,
        )
    logger.info(
        "job_id=%s job_type=%s duration_ms=%d status=%s",
        job["id"],
        job["job_type"],
        duration_ms,
        finalized["status"],
    )


def run_worker_post_commit(
    store: ServiceStore,
    *,
    notifications: PreferredSourceNotificationService,
    actor_alerts: ApifyActorAlertService,
    job: dict[str, Any],
    finalized: dict[str, Any],
    started_at: float,
    failure_fingerprint: str | None,
    ports: WorkerPostCommitPorts,
    logger: logging.Logger,
    post_claim_housekeeping: Callable[[], None] | None = None,
) -> dict[str, Any]:
    _dispatch_preferred_notifications(
        store,
        notifications,
        job,
        ports=ports,
        logger=logger,
    )
    _dispatch_actor_alerts(store, actor_alerts, job, logger=logger)
    _emit_finish_events(
        job,
        finalized,
        started_at=started_at,
        failure_fingerprint=failure_fingerprint,
        ports=ports,
        logger=logger,
    )
    if post_claim_housekeeping is not None:
        try:
            post_claim_housekeeping()
        except Exception:
            logger.warning("post-claim Worker housekeeping failed", exc_info=True)
    return finalized
