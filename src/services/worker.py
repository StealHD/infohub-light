"""Worker loop for queued InfoHub service jobs."""

from __future__ import annotations

import argparse
import logging
import os
import re
import threading
import time
from typing import Any

import httpx
from dotenv import load_dotenv

from ..logging_utils import configure_logging, error_fingerprint
from ..observability_context import (
    begin_observability_context,
    reset_observability_context,
    update_observability_context,
)
from ..rsshub import DEFAULT_RSSHUB_BASE_URL, is_managed_rsshub_config
from ..storage.manager import StorageManager
from ..ui.server import run_source_test
from .feed_schedule import FeedScheduleService, SCHEDULED_REFRESH_REASON
from .feed_end_messages import run_due_feed_end_messages_generation
from .job_queue import JobQueue
from .job_eligibility import JobEligibilityService
from .maintenance import MaintenanceService
from .preferred_source_notifications import PreferredSourceNotificationService
from .apify_actor_alerts import ApifyActorAlertService
from .operation_log import safe_emit_operation_event
from .source_type_registry import build_source_payload
from .secret_store import SecretStore
from .source_schedule import SourceScheduleService
from .source_acquisition import (
    SourceAcquisitionCoordinator,
    shared_acquisition_enabled,
)
from .usage_attempt_meter import UsageAttemptMeter
from .media_cache import MediaCacheService
from .source_avatar import SourceAvatarService
from .apify_pool_runtime import (
    apify_coordinator_for_workspace,
    reconcile_all_apify_pools_sync,
)
from .apify_key_pool import apify_key_pool_enabled
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
}


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


def _emit_job_invalidation(
    job: dict[str, Any],
    *,
    reason: str,
) -> None:
    safe_emit_operation_event(
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
        error_code=_safe_machine_code(reason, "job_invalidated"),
    )


def _cache_run_media(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    items: list[Any],
) -> None:
    """Best-effort media caching must never change the feed job outcome."""

    try:
        MediaCacheService(store, data_dir=data_dir).cache_items(
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
            items=items,
        )
    except Exception:
        if store.connect().in_transaction:
            store.connect().rollback()
        logger.warning(
            "media cache failed job_id=%s; content finalization will continue",
            job.get("id"),
        )


def _cache_run_source_avatars(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    result: Any,
) -> None:
    """Persist source-level avatar evidence without changing the Feed outcome."""

    try:
        refreshes = SourceAvatarService(
            store,
            data_dir=data_dir,
        ).refresh_run_result(
            workspace_id=str(job["workspace_id"]),
            result=result,
        )
    except Exception:
        if store.connect().in_transaction:
            store.connect().rollback()
        logger.warning(
            "source avatar cache failed job_id=%s; feed finalization will continue",
            job.get("id"),
        )
        return
    for refresh in refreshes:
        event_outcome = {
            "stored": "succeeded",
            "unchanged": "skipped",
            "candidate_missing": "skipped",
            "kept_previous": "partial",
            "failed": "failed",
            "identity_mismatch": "denied",
        }.get(refresh.status, "unavailable")
        safe_emit_operation_event(
            category="source",
            action="avatar_cache",
            outcome=event_outcome,
            level=(
                "warning"
                if refresh.status
                in {"kept_previous", "failed", "identity_mismatch"}
                else "info"
            ),
            workspace_id=str(job["workspace_id"]),
            subject_user_id=str(job["user_id"]),
            job_id=str(job["id"]),
            source_id=refresh.source_id,
            error_code=(
                refresh.status
                if refresh.status
                not in {"stored", "unchanged", "candidate_missing"}
                else None
            ),
        )


class MigrationRequiredError(RuntimeError):
    retryable = False


class PaidCanaryUnavailableError(RuntimeError):
    code = "apify_actor_routing_disabled"
    retryable = False


class PaidCanaryAuthorizationError(RuntimeError):
    code = "apify_actor_canary_unavailable"
    retryable = False


def _is_retryable_exception(exc: Exception) -> bool:
    explicit = getattr(exc, "retryable", None)
    if explicit is not None:
        return bool(explicit)
    if isinstance(exc, (ConnectionError, TimeoutError, httpx.TransportError)):
        return True
    if isinstance(exc, httpx.HTTPStatusError):
        return exc.response.status_code == 429 or exc.response.status_code >= 500
    return False


class _LeaseHeartbeat:
    """Renew one job lease and publish worker liveness from a separate connection."""

    def __init__(self, *, data_dir: str, job: dict[str, Any], lease_seconds: float):
        self.store = ServiceStore(data_dir)
        self.queue = JobQueue(self.store)
        self.job = job
        self.lease_seconds = lease_seconds
        self.interval = min(10.0, max(1.0, lease_seconds / 3.0))
        self.stop_event = threading.Event()
        self.thread: threading.Thread | None = None
        self.last_error_code: str | None = None

    def __enter__(self) -> "_LeaseHeartbeat":
        self.store.upsert_worker_heartbeat(
            self.job["worker_id"],
            "running",
            current_job_id=self.job["id"],
        )
        self.thread = threading.Thread(target=self._run, name=f"lease-{self.job['id']}", daemon=True)
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
            except Exception as exc:  # the guarded finalizer will reject a lost claim
                self.last_error_code = _exception_code(exc)
                self.stop_event.set()

    def __exit__(self, exc_type, exc, _traceback) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=max(self.interval * 2, 2.0))
        error_code = _exception_code(exc) if exc is not None else self.last_error_code
        try:
            self.store.upsert_worker_heartbeat(
                self.job["worker_id"],
                "idle",
                last_job_id=self.job["id"],
                last_error_code=error_code,
            )
        finally:
            self.store.close()


def _source_payload_from_catalog(
    job: dict[str, Any],
    *,
    store: ServiceStore,
) -> dict[str, Any]:
    payload = dict(job.get("payload_json") or {})
    if not job.get("source_id"):
        return payload
    source = store.get_source(str(job["source_id"]))
    if not source:
        return payload

    managed_rsshub = bool(
        source.get("type") == "rss"
        and is_managed_rsshub_config(source.get("config"))
    )
    rsshub_base_url = DEFAULT_RSSHUB_BASE_URL
    if managed_rsshub:
        rsshub_base_url = StorageManager(
            data_dir=str(store.data_dir)
        ).load_config().rsshub.base_url
    canonical = build_source_payload(
        source,
        rsshub_base_url=rsshub_base_url,
    )
    # Job control metadata is never source configuration. Removing it before
    # the runtime overlay prevents unknown catalog fields from impersonating a
    # confirmed paid Canary.
    for reserved_key in (
        "reason",
        "apify_actor_candidate_id",
        "apify_actor_route_generation",
    ):
        canonical.pop(reserved_key, None)
    if source.get("type") == "rss":
        if managed_rsshub:
            canonical["enforce_public_network"] = False
        else:
            owner = store.get_user(str(source.get("owner_user_id") or ""))
            canonical["enforce_public_network"] = bool(
                source.get("enforce_public_network")
            ) or not (
                owner and owner.get("role") in {"owner", "admin"}
            )
    runtime_payload = {
        key: value
        for key, value in payload.items()
        if key
        in {
            "hours",
            "reason",
            "apify_actor_candidate_id",
            "apify_actor_route_generation",
        }
    }
    return {**canonical, **runtime_payload}


def _active_catalog_source_ids(
    store: ServiceStore,
    *,
    workspace_id: str,
    user_id: str,
) -> set[str]:
    return {
        str(record["source_id"])
        for record in store.list_enabled_user_subscriptions_with_sources(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if record.get("source_id")
    }


def _run_user_feed_refresh(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    import asyncio

    from ..orchestrator import HorizonOrchestrator
    from ..storage.manager import StorageManager
    from .feed_production import FeedProductionService, FeedRunFailed, active_service_source_ids
    from .feed_run import safe_run_diagnostics
    from .source_health import SourceHealthService
    from .user_analysis_cache import UserAnalysisCache
    from .user_config_builder import build_user_config

    storage = StorageManager(data_dir=data_dir)
    base_config = storage.load_config()
    scheduled_global_refresh = (
        (job.get("payload_json") or {}).get("reason")
        == SCHEDULED_REFRESH_REASON
    )
    config = build_user_config(
        store=store,
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        base_config=base_config,
        schedule_scope="global" if scheduled_global_refresh else "all",
    )
    analysis_cache = UserAnalysisCache(
        store,
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        job_id=job["id"],
    )
    try:
        analysis_cache.prune()
        orchestrator = HorizonOrchestrator(config, storage)
        if hasattr(orchestrator, "set_service_analysis_cache"):
            orchestrator.set_service_analysis_cache(analysis_cache)
        if hasattr(orchestrator, "set_service_attempt_meter"):
            orchestrator.set_service_attempt_meter(
                UsageAttemptMeter(
                    store,
                    workspace_id=job["workspace_id"],
                    user_id=job["user_id"],
                    job_id=job["id"],
                )
            )
        if hasattr(orchestrator, "set_service_apify_coordinator"):
            orchestrator.set_service_apify_coordinator(
                apify_coordinator_for_workspace(
                    store,
                    workspace_id=str(job["workspace_id"]),
                    data_dir=data_dir,
                )
            )
        if (
            apify_key_pool_enabled()
            and hasattr(orchestrator, "set_service_apify_actor_route")
        ):
            orchestrator.set_service_apify_actor_route(
                build_apify_actor_route(
                    store,
                    data_dir=data_dir,
                    workspace_id=str(job["workspace_id"]),
                ),
                job_id=str(job["id"]),
            )
        if (
            shared_acquisition_enabled()
            and hasattr(orchestrator, "set_service_acquisition_coordinator")
        ):
            orchestrator.set_service_acquisition_coordinator(
                SourceAcquisitionCoordinator(
                    store,
                    workspace_id=job["workspace_id"],
                    user_id=job["user_id"],
                    job_id=job["id"],
                )
            )
        raw_force_hours = (job.get("payload_json") or {}).get("hours")
        run_result = asyncio.run(
            orchestrator.execute(
                force_hours=(
                    int(raw_force_hours)
                    if raw_force_hours is not None
                    else None
                ),
                enrich=False,
            )
        )
    finally:
        analysis_cache.close()
    _cache_run_source_avatars(
        job,
        data_dir=data_dir,
        store=store,
        result=run_result,
    )
    if run_result.status == "failed":
        raise FeedRunFailed(run_result)
    _cache_run_media(
        job,
        data_dir=data_dir,
        store=store,
        items=list(run_result.items),
    )
    configured_source_ids = active_service_source_ids(config)
    all_active_source_ids = _active_catalog_source_ids(
        store,
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
    )
    catalog_subscriptions = store.list_user_subscriptions(job["user_id"])
    retained_source_ids = (
        all_active_source_ids if catalog_subscriptions else None
    )
    attempted_source_ids = configured_source_ids & all_active_source_ids
    current_outcomes = tuple(
        outcome
        for outcome in run_result.source_outcomes
        if outcome.source_id in attempted_source_ids
    )
    snapshot = FeedProductionService(store, config).save_run_result(
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        job_id=job["id"],
        job_type="user_feed_refresh",
        result=run_result,
        active_source_ids=retained_source_ids,
        commit=False,
    )
    SourceHealthService(store).apply_outcomes(
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        job_id=job["id"],
        attempted_at=run_result.finished_at,
        outcomes=current_outcomes,
        commit=False,
    )
    SourceScheduleService(store).advance_after_full_refresh(
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        source_outcomes=current_outcomes,
        finished_at=run_result.finished_at,
        job_id=job["id"],
    )
    return {
        "ok": True,
        "job_type": "user_feed_refresh",
        "snapshot_id": snapshot["id"],
        "snapshot_created": bool(snapshot.get("snapshot_created", True)),
        "new_item_count": snapshot["new_item_count"],
        **safe_run_diagnostics(run_result, item_count=snapshot["item_count"]),
        "_job_status": run_result.status,
    }


def _run_job(job: dict[str, Any], *, data_dir: str, store: ServiceStore) -> dict[str, Any]:
    payload = _source_payload_from_catalog(job, store=store)
    raw_job_payload = (
        job.get("payload_json")
        if isinstance(job.get("payload_json"), dict)
        else {}
    )
    job_type = job["job_type"]

    if job_type == "source_test":
        meter = UsageAttemptMeter(
            store,
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
            job_id=job["id"],
        )

        def run_metered_test() -> dict[str, Any]:
            is_paid_canary = (
                raw_job_payload.get("reason") == "apify_actor_canary"
            )
            is_x_profile = (
                str(payload.get("source_type") or "") == "apify_social"
                and str(payload.get("platform") or "").casefold() == "x"
                and str(payload.get("kind") or "profile").casefold()
                == "profile"
            )
            if is_paid_canary and (
                not apify_key_pool_enabled() or not is_x_profile
            ):
                raise PaidCanaryUnavailableError(
                    "Paid Actor canary requires enabled X profile routing"
                )
            if is_paid_canary and (
                int(job.get("max_attempts") or 0) != 1
                or int(job.get("priority") or 0) != 100
            ):
                raise PaidCanaryAuthorizationError(
                    "Paid Actor canary was not created by the confirmed canary action"
                )
            meter.before_fetch_attempt(
                provider=str(payload.get("source_type") or "unknown"),
                source_id=str(job.get("source_id") or ""),
            )
            apify_coordinator = apify_coordinator_for_workspace(
                store,
                workspace_id=str(job["workspace_id"]),
                data_dir=data_dir,
            )
            actor_route = None
            forced_candidate_id = None
            forced_route_generation = None
            paid_canary = False
            if (
                apify_key_pool_enabled()
                and is_x_profile
            ):
                actor_route = build_apify_actor_route(
                    store,
                    data_dir=data_dir,
                    workspace_id=str(job["workspace_id"]),
                )
                if is_paid_canary:
                    actor = store.get_user(str(job["user_id"]))
                    if (
                        actor is None
                        or not bool(actor.get("enabled"))
                        or actor.get("role") not in {"owner", "admin"}
                    ):
                        raise PermissionError(
                            "paid Actor canary requires an active administrator"
                        )
                    forced_candidate_id = str(
                        raw_job_payload.get("apify_actor_candidate_id") or ""
                    )
                    raw_generation = raw_job_payload.get(
                        "apify_actor_route_generation"
                    )
                    if not forced_candidate_id or not isinstance(
                        raw_generation,
                        int,
                    ):
                        raise ValueError(
                            "paid Actor canary routing metadata is invalid"
                        )
                    forced_route_generation = int(raw_generation)
                    paid_canary = True
            if actor_route is not None:
                return run_source_test(
                    payload,
                    apify_coordinator=apify_coordinator,
                    apify_actor_route=actor_route,
                    route_job_id=str(job["id"]),
                    forced_candidate_id=forced_candidate_id,
                    forced_route_generation=forced_route_generation,
                    paid_canary=paid_canary,
                )
            if apify_coordinator is not None:
                return run_source_test(
                    payload,
                    apify_coordinator=apify_coordinator,
                )
            return run_source_test(payload)

        if shared_acquisition_enabled() and job.get("source_id"):
            return SourceAcquisitionCoordinator(
                store,
                workspace_id=job["workspace_id"],
                user_id=job["user_id"],
                job_id=job["id"],
            ).run_probe(source=payload, call=run_metered_test)
        return run_metered_test()

    if job_type == "source_fetch":
        if job.get("source_id"):
            from .catalog_source_runner import run_catalog_source_fetch

            return run_catalog_source_fetch(job, data_dir=data_dir, store=store, commit=False)
        if not payload.get("source_type"):
            return _run_user_feed_refresh(job, data_dir=data_dir, store=store)
        raise ValueError("service source_fetch requires a catalog source_id")

    if job_type == "user_feed_refresh":
        return _run_user_feed_refresh(job, data_dir=data_dir, store=store)

    if job_type == "content_repair":
        from .content_repair import repair_existing_content

        return repair_existing_content(job, data_dir=data_dir, store=store)

    raise ValueError(f"unsupported job_type: {job_type}")


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
    context_token = begin_observability_context(stage="startup")
    try:
        store.initialize()
        update_observability_context(stage="migration_check")
        if store.apify_actor_routing_v13_migration_required():
            store.upsert_worker_heartbeat(
                worker_id,
                "idle",
                last_error_code="migration_required",
            )
            return {
                "ok": False,
                "error_code": "migration_required",
                "migration": "apify_actor_routing_v13",
            }
        if store.webhook_providers_v14_migration_required():
            store.upsert_worker_heartbeat(
                worker_id,
                "idle",
                last_error_code="migration_required",
            )
            return {
                "ok": False,
                "error_code": "migration_required",
                "migration": "webhook_providers_v14",
            }
        if store.multichannel_notifications_v15_migration_required():
            store.upsert_worker_heartbeat(
                worker_id,
                "idle",
                last_error_code="migration_required",
            )
            return {
                "ok": False,
                "error_code": "migration_required",
                "migration": "multichannel_notifications_v15",
            }
        SecretStore(data_dir).load_into_environ()
        update_observability_context(stage="provider_reconcile")
        apify_reconcile_outcomes = reconcile_all_apify_pools_sync(
            store,
            data_dir=data_dir,
        )
        for outcome in apify_reconcile_outcomes:
            if not outcome["ok"]:
                logger.warning(
                    "Apify pool reconcile pending workspace_id=%s code=%s",
                    outcome["workspace_id"],
                    outcome["code"],
                )
            actor_route = build_apify_actor_route(
                store,
                data_dir=data_dir,
                workspace_id=str(outcome["workspace_id"]),
            )
            route_reconcile = actor_route.reconcile_unfinished_attempts()
            if route_reconcile["route_blocked"]:
                logger.warning(
                    "Apify Actor route reconcile blocked workspace_id=%s",
                    outcome["workspace_id"],
                )
            try:
                sync_apify_actor_quota_alert(
                    store,
                    data_dir=data_dir,
                    workspace_id=str(outcome["workspace_id"]),
                    route_state=actor_route.public_state(),
                )
            except Exception:
                if store.connect().in_transaction:
                    store.connect().rollback()
                logger.warning(
                    "Apify Actor quota alert sync failed workspace_id=%s",
                    outcome["workspace_id"],
                )
        if (
            not store.feed_storage_v3_migration_required()
            and not store.content_index_v4_migration_required()
            and not store.content_timeline_v11_migration_required()
            and not store.apify_actor_routing_v13_migration_required()
            and not store.webhook_providers_v14_migration_required()
            and not store.multichannel_notifications_v15_migration_required()
        ):
            update_observability_context(stage="maintenance")
            MaintenanceService(store).run_if_due()
        queue = JobQueue(store)
        lease = float(lease_seconds if lease_seconds is not None else os.getenv("HORIZON_WORKER_LEASE_SECONDS", "900"))
        retry_base = float(
            retry_base_seconds
            if retry_base_seconds is not None
            else os.getenv("HORIZON_WORKER_RETRY_BASE_SECONDS", "30")
        )
        update_observability_context(stage="lease_recovery")
        recovered_jobs = queue.recover_stale_running_jobs()
        for recovered in recovered_jobs:
            recovery_failed = recovered["status"] == "failed"
            safe_emit_operation_event(
                category="job",
                action="lease_recovery",
                outcome="failed" if recovery_failed else "retried",
                level="error" if recovery_failed else "warning",
                workspace_id=str(recovered["workspace_id"]),
                subject_user_id=str(recovered["user_id"]),
                job_id=str(recovered["job_id"]),
                source_id=recovered.get("source_id"),
                subscription_id=recovered.get("subscription_id"),
                stage="lease_recovery",
                error_code="lease_expired",
                counts={"attempts": int(recovered["attempts"])},
            )
        queue.prune_terminal_jobs()
        if enqueue_schedules:
            update_observability_context(stage="schedule_enqueue")
            feed_enqueue_result = FeedScheduleService(store).enqueue_due()
            source_enqueue_result = SourceScheduleService(store).enqueue_due()
            for outcome in feed_enqueue_result["outcomes"]:
                if outcome.get("action") not in {"enqueued", "deduplicated"}:
                    continue
                scheduled_user = store.get_user(str(outcome["user_id"]))
                if scheduled_user is None:
                    continue
                safe_emit_operation_event(
                    category="job",
                    action="scheduled_queue",
                    outcome=(
                        "queued"
                        if outcome["action"] == "enqueued"
                        else "skipped"
                    ),
                    level="info",
                    workspace_id=str(scheduled_user["workspace_id"]),
                    subject_user_id=str(scheduled_user["id"]),
                    job_id=outcome.get("job_id"),
                    counts={
                        "deduplicated": int(
                            outcome["action"] == "deduplicated"
                        )
                    },
                )
            for outcome in source_enqueue_result["outcomes"]:
                if outcome.get("action") not in {"enqueued", "deduplicated"}:
                    continue
                scheduled_subscription = store.get_subscription(
                    str(outcome["subscription_id"])
                )
                if scheduled_subscription is None:
                    continue
                scheduled_user = store.get_user(
                    str(scheduled_subscription["user_id"])
                )
                if scheduled_user is None:
                    continue
                safe_emit_operation_event(
                    category="job",
                    action="scheduled_queue",
                    outcome=(
                        "queued"
                        if outcome["action"] == "enqueued"
                        else "skipped"
                    ),
                    level="info",
                    workspace_id=str(scheduled_user["workspace_id"]),
                    subject_user_id=str(scheduled_subscription["user_id"]),
                    job_id=outcome.get("job_id"),
                    source_id=str(scheduled_subscription["source_id"]),
                    subscription_id=str(scheduled_subscription["id"]),
                    counts={
                        "deduplicated": int(
                            outcome["action"] == "deduplicated"
                        )
                    },
                )
        notifications = PreferredSourceNotificationService(
            store,
            data_dir=data_dir,
        )
        actor_alerts = ApifyActorAlertService(
            store,
            data_dir=data_dir,
            email_transport=notifications.email_transport,
        )
        try:
            update_observability_context(stage="notification_backlog")
            notifications.dispatch_pending(limit=20)
        except Exception:
            if store.connect().in_transaction:
                store.connect().rollback()
            logger.warning(
                "preferred-source notification backlog dispatch failed"
            )
        try:
            actor_alerts.dispatch_pending(limit=20)
        except Exception:
            if store.connect().in_transaction:
                store.connect().rollback()
            logger.warning("Apify Actor alert backlog dispatch failed")
        if store.get_worker_heartbeat(worker_id) is None:
            store.upsert_worker_heartbeat(worker_id, "starting")
        update_observability_context(stage="claim")
        job = queue.claim_next_job(worker_id=worker_id, lease_seconds=lease)
        if not job:
            generation_result = run_due_feed_end_messages_generation(
                data_dir=data_dir,
                store=store,
                worker_id=worker_id,
            )
            store.upsert_worker_heartbeat(
                worker_id,
                "idle",
                last_error_code=(
                    generation_result.get("error_code")
                    if generation_result and not generation_result.get("ok")
                    else None
                ),
            )
            return generation_result
        update_observability_context(
            workspace_id=str(job["workspace_id"]),
            actor_user_id=str(job["user_id"]),
            job_id=str(job["id"]),
            source_id=job.get("source_id"),
            subscription_id=job.get("subscription_id"),
            stage="claim",
        )
        safe_emit_operation_event(
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
        with _LeaseHeartbeat(data_dir=data_dir, job=job, lease_seconds=lease):
            update_observability_context(stage="eligibility")
            eligibility = JobEligibilityService(store).evaluate(job)
            if not eligibility.allowed:
                invalidation_reason = str(
                    eligibility.reason or "job_invalidated"
                )
                finalized = queue.cancel_claimed_job(
                    job["id"],
                    reason=invalidation_reason,
                    worker_id=worker_id,
                    claim_token=job["claim_token"],
                )
                _emit_job_invalidation(job, reason=invalidation_reason)
            else:
                try:
                    update_observability_context(stage="execute")
                    if job["job_type"] in {"source_fetch", "user_feed_refresh"} and store.feed_v2_migration_required():
                        raise MigrationRequiredError("user feed v2 migration is required before feed jobs can run")
                    if job["job_type"] in {"source_fetch", "user_feed_refresh", "content_repair"} and store.content_index_v4_migration_required():
                        raise MigrationRequiredError("user content v4 migration is required before feed jobs can run")
                    if job["job_type"] in {"source_fetch", "user_feed_refresh", "content_repair"} and store.content_timeline_v11_migration_required():
                        raise MigrationRequiredError("content timeline v11 migration is required before feed jobs can run")
                    result = _run_job(job, data_dir=data_dir, store=store)
                    if result.get("snapshot_id"):
                        conn = store.connect()
                        if conn.in_transaction:
                            conn.execute(
                                "SAVEPOINT preferred_source_notification_stage"
                            )
                            try:
                                notifications.stage_for_job(
                                    job=job,
                                    snapshot_id=str(result["snapshot_id"]),
                                    snapshot_created=bool(
                                        result.get("snapshot_created")
                                    ),
                                )
                            except Exception:
                                conn.execute(
                                    "ROLLBACK TO preferred_source_notification_stage"
                                )
                                conn.execute(
                                    "RELEASE preferred_source_notification_stage"
                                )
                                logger.warning(
                                    "preferred-source notification staging failed job_id=%s",
                                    job.get("id"),
                                )
                            else:
                                conn.execute(
                                    "RELEASE preferred_source_notification_stage"
                                )
                        else:
                            logger.warning(
                                "preferred-source notification staging skipped without feed transaction job_id=%s",
                                job.get("id"),
                            )
                except Exception as exc:
                    from .feed_production import FeedRunFailed
                    from .feed_run import safe_run_diagnostics
                    from .source_health import SourceHealthService
                    from .source_health import sanitize_issue_message

                    failure_fingerprint = error_fingerprint()
                    error_code = _exception_code(exc)
                    update_observability_context(
                        stage="execute",
                        error_code=error_code,
                    )
                    logger.exception(
                        "job execution failed job_id=%s job_type=%s",
                        job["id"],
                        job["job_type"],
                        extra={
                            "stage": "execute",
                            "error_code": error_code,
                        },
                    )
                    conn = store.connect()
                    conn.rollback()
                    eligibility = JobEligibilityService(store).evaluate(job)
                    if not eligibility.allowed:
                        invalidation_reason = str(
                            eligibility.reason or "job_invalidated"
                        )
                        finalized = queue.cancel_claimed_job(
                            job["id"],
                            reason=invalidation_reason,
                            worker_id=worker_id,
                            claim_token=job["claim_token"],
                        )
                        _emit_job_invalidation(
                            job,
                            reason=invalidation_reason,
                        )
                    else:
                        try:
                            conn.execute("BEGIN IMMEDIATE")
                            structured_result = (
                                safe_run_diagnostics(exc.result, item_count=0)
                                if isinstance(exc, FeedRunFailed)
                                else None
                            )
                            finalized = queue.fail_or_retry_job(
                                job["id"],
                                error_code=error_code,
                                error_message=sanitize_issue_message(str(exc)),
                                retryable=_is_retryable_exception(exc),
                                retry_base_seconds=retry_base,
                                result=structured_result,
                                worker_id=worker_id,
                                claim_token=job["claim_token"],
                                commit=False,
                            )
                            if finalized["status"] == "failed" and isinstance(
                                exc, FeedRunFailed
                            ):
                                outcomes = exc.result.source_outcomes
                                if (
                                    job["job_type"] == "source_fetch"
                                    and job.get("source_id")
                                ):
                                    outcomes = tuple(
                                        outcome
                                        for outcome in outcomes
                                        if outcome.source_id == job["source_id"]
                                    )
                                elif job["job_type"] == "user_feed_refresh":
                                    active_source_ids = _active_catalog_source_ids(
                                        store,
                                        workspace_id=job["workspace_id"],
                                        user_id=job["user_id"],
                                    )
                                    outcomes = tuple(
                                        outcome
                                        for outcome in outcomes
                                        if outcome.source_id in active_source_ids
                                    )
                                SourceHealthService(store).apply_outcomes(
                                    workspace_id=job["workspace_id"],
                                    user_id=job["user_id"],
                                    job_id=job["id"],
                                    attempted_at=exc.result.finished_at,
                                    outcomes=outcomes,
                                    commit=False,
                                )
                            conn.commit()
                        except Exception:
                            if conn.in_transaction:
                                conn.rollback()
                            raise
                else:
                    update_observability_context(stage="finalize")
                    eligibility = JobEligibilityService(store).evaluate(job)
                    if not eligibility.allowed:
                        store.connect().rollback()
                        invalidation_reason = str(
                            eligibility.reason or "job_invalidated"
                        )
                        finalized = queue.cancel_claimed_job(
                            job["id"],
                            reason=invalidation_reason,
                            worker_id=worker_id,
                            claim_token=job["claim_token"],
                        )
                        _emit_job_invalidation(
                            job,
                            reason=invalidation_reason,
                        )
                    else:
                        job_status = str(result.pop("_job_status", "succeeded"))
                        finalized = queue.complete_job(
                            job["id"],
                            status=job_status,
                            result=result,
                            worker_id=worker_id,
                            claim_token=job["claim_token"],
                        )
        update_observability_context(stage="notification_dispatch")
        try:
            delivery_summary = notifications.dispatch_pending(job_id=str(job["id"]))
        except Exception as exc:
            if store.connect().in_transaction:
                store.connect().rollback()
            logger.warning(
                "preferred-source notification dispatch failed job_id=%s",
                job.get("id"),
            )
            safe_emit_operation_event(
                category="notification",
                action="dispatch",
                outcome="failed",
                level="error",
                workspace_id=str(job["workspace_id"]),
                subject_user_id=str(job["user_id"]),
                job_id=str(job["id"]),
                source_id=job.get("source_id"),
                subscription_id=job.get("subscription_id"),
                error_code=_exception_code(exc),
            )
        else:
            if int(delivery_summary.get("claimed") or 0) > 0:
                failed_deliveries = int(delivery_summary.get("failed") or 0)
                succeeded_deliveries = int(
                    delivery_summary.get("succeeded") or 0
                )
                if failed_deliveries and succeeded_deliveries:
                    delivery_outcome = "partial"
                    delivery_level = "warning"
                elif failed_deliveries:
                    delivery_outcome = "failed"
                    delivery_level = "error"
                else:
                    delivery_outcome = "succeeded"
                    delivery_level = "info"
                safe_emit_operation_event(
                    category="notification",
                    action="dispatch",
                    outcome=delivery_outcome,
                    level=delivery_level,
                    workspace_id=str(job["workspace_id"]),
                    subject_user_id=str(job["user_id"]),
                    job_id=str(job["id"]),
                    source_id=job.get("source_id"),
                    subscription_id=job.get("subscription_id"),
                    counts={
                        "claimed": int(delivery_summary["claimed"]),
                        "failed": failed_deliveries,
                        "succeeded": succeeded_deliveries,
                    },
                )
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
        result_payload = finalized.get("result_json") or {}
        final_status = str(finalized["status"])
        outcome_by_status = {
            "queued": "retried",
            "succeeded": "succeeded",
            "partial": "partial",
            "failed": "failed",
            "cancelled": "cancelled",
        }
        final_outcome = outcome_by_status.get(final_status, "failed")
        if final_outcome == "failed":
            final_level = "error"
        elif final_outcome in {"partial", "retried"}:
            final_level = "warning"
        else:
            final_level = "info"
        duration_ms = int((time.monotonic() - started_at) * 1000)
        final_counts = {"attempts": int(finalized.get("attempts") or 0)}
        if isinstance(result_payload.get("item_count"), int):
            final_counts["items"] = max(int(result_payload["item_count"]), 0)
        update_observability_context(
            stage="finish",
            error_code=str(finalized.get("error_code") or ""),
        )
        safe_emit_operation_event(
            category="job",
            action="finish",
            outcome=final_outcome,
            level=final_level,
            workspace_id=str(job["workspace_id"]),
            subject_user_id=str(job["user_id"]),
            job_id=str(job["id"]),
            source_id=job.get("source_id"),
            subscription_id=job.get("subscription_id"),
            stage="finish",
            error_code=finalized.get("error_code"),
            error_fingerprint=(
                failure_fingerprint
                if final_outcome in {"failed", "retried"}
                else None
            ),
            duration_ms=duration_ms,
            counts=final_counts,
        )
        _emit_source_outcome_events(
            job,
            result_payload,
            failure_fingerprint=failure_fingerprint,
        )
        if job["job_type"] in {
            "source_test",
            "source_fetch",
            "user_feed_refresh",
        }:
            safe_emit_operation_event(
                category="acquisition",
                action=(
                    "test" if job["job_type"] == "source_test" else "fetch"
                ),
                outcome=final_outcome,
                level=final_level,
                workspace_id=str(job["workspace_id"]),
                subject_user_id=str(job["user_id"]),
                job_id=str(job["id"]),
                source_id=job.get("source_id"),
                subscription_id=job.get("subscription_id"),
                stage="acquisition",
                error_code=finalized.get("error_code"),
                error_fingerprint=(
                    failure_fingerprint
                    if final_outcome in {"failed", "retried"}
                    else None
                ),
                duration_ms=duration_ms,
                counts=final_counts,
            )
        logger.info(
            "job_id=%s job_type=%s duration_ms=%d status=%s",
            job["id"],
            job["job_type"],
            duration_ms,
            finalized["status"],
        )
        return finalized
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
