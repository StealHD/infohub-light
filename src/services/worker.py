"""Worker loop for queued InfoHub service jobs."""

from __future__ import annotations

import argparse
import logging
import os
import threading
import time
from typing import Any

import httpx
from dotenv import load_dotenv

from ..ui.server import run_source_test
from .feed_schedule import FeedScheduleService
from .job_queue import JobQueue
from .job_eligibility import JobEligibilityService
from .maintenance import MaintenanceService
from .source_type_registry import build_source_payload
from .secret_store import SecretStore
from .source_schedule import SourceScheduleService
from .source_acquisition import (
    SourceAcquisitionCoordinator,
    shared_acquisition_enabled,
)
from .usage_attempt_meter import UsageAttemptMeter
from .media_cache import MediaCacheService
from ..storage.service_store import ServiceStore


logger = logging.getLogger(__name__)


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


class MigrationRequiredError(RuntimeError):
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
                self.last_error_code = type(exc).__name__
                self.stop_event.set()

    def __exit__(self, exc_type, exc, _traceback) -> None:
        self.stop_event.set()
        if self.thread:
            self.thread.join(timeout=max(self.interval * 2, 2.0))
        error_code = type(exc).__name__ if exc is not None else self.last_error_code
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

    canonical = build_source_payload(source)
    if source.get("type") == "rss":
        owner = store.get_user(str(source.get("owner_user_id") or ""))
        canonical["enforce_public_network"] = not (
            owner and owner.get("role") in {"owner", "admin"}
        )
    runtime_payload = {
        key: value
        for key, value in payload.items()
        if key in {"hours", "reason"}
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
    config = build_user_config(
        store=store,
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        base_config=base_config,
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
        run_result = asyncio.run(
            orchestrator.execute(
                force_hours=int((job.get("payload_json") or {}).get("hours") or config.filtering.time_window_hours),
                enrich=False,
            )
        )
    finally:
        analysis_cache.close()
    if run_result.status == "failed":
        raise FeedRunFailed(run_result)
    _cache_run_media(
        job,
        data_dir=data_dir,
        store=store,
        items=list(run_result.items),
    )
    configured_source_ids = active_service_source_ids(config)
    active_source_ids: set[str] | None = None
    current_outcomes = run_result.source_outcomes
    if configured_source_ids:
        active_source_ids = configured_source_ids & _active_catalog_source_ids(
            store,
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
        )
        current_outcomes = tuple(
            outcome
            for outcome in run_result.source_outcomes
            if outcome.source_id in active_source_ids
        )
    snapshot = FeedProductionService(store, config).save_run_result(
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        job_id=job["id"],
        job_type="user_feed_refresh",
        result=run_result,
        active_source_ids=active_source_ids,
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
        **safe_run_diagnostics(run_result, item_count=snapshot["item_count"]),
        "_job_status": run_result.status,
    }


def _run_job(job: dict[str, Any], *, data_dir: str, store: ServiceStore) -> dict[str, Any]:
    payload = _source_payload_from_catalog(job, store=store)
    job_type = job["job_type"]

    if job_type == "source_test":
        meter = UsageAttemptMeter(
            store,
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
            job_id=job["id"],
        )

        def run_metered_test() -> dict[str, Any]:
            meter.before_fetch_attempt(
                provider=str(payload.get("source_type") or "unknown"),
                source_id=str(job.get("source_id") or ""),
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
    try:
        store.initialize()
        SecretStore(data_dir).load_into_environ()
        if (
            not store.feed_storage_v3_migration_required()
            and not store.content_index_v4_migration_required()
        ):
            MaintenanceService(store).run_if_due()
        queue = JobQueue(store)
        lease = float(lease_seconds if lease_seconds is not None else os.getenv("HORIZON_WORKER_LEASE_SECONDS", "900"))
        retry_base = float(
            retry_base_seconds
            if retry_base_seconds is not None
            else os.getenv("HORIZON_WORKER_RETRY_BASE_SECONDS", "30")
        )
        queue.requeue_stale_running_jobs()
        queue.prune_terminal_jobs()
        if enqueue_schedules:
            FeedScheduleService(store).enqueue_due()
            SourceScheduleService(store).enqueue_due()
        if store.get_worker_heartbeat(worker_id) is None:
            store.upsert_worker_heartbeat(worker_id, "starting")
        job = queue.claim_next_job(worker_id=worker_id, lease_seconds=lease)
        if not job:
            store.upsert_worker_heartbeat(worker_id, "idle")
            return None
        with _LeaseHeartbeat(data_dir=data_dir, job=job, lease_seconds=lease):
            eligibility = JobEligibilityService(store).evaluate(job)
            if not eligibility.allowed:
                finalized = queue.cancel_claimed_job(
                    job["id"],
                    reason=str(eligibility.reason or "job_invalidated"),
                    worker_id=worker_id,
                    claim_token=job["claim_token"],
                )
            else:
                try:
                    if job["job_type"] in {"source_fetch", "user_feed_refresh"} and store.feed_v2_migration_required():
                        raise MigrationRequiredError("user feed v2 migration is required before feed jobs can run")
                    if job["job_type"] in {"source_fetch", "user_feed_refresh", "content_repair"} and store.content_index_v4_migration_required():
                        raise MigrationRequiredError("user content v4 migration is required before feed jobs can run")
                    result = _run_job(job, data_dir=data_dir, store=store)
                except Exception as exc:
                    from .feed_production import FeedRunFailed
                    from .feed_run import safe_run_diagnostics
                    from .source_health import SourceHealthService
                    from .source_health import sanitize_issue_message

                    conn = store.connect()
                    conn.rollback()
                    eligibility = JobEligibilityService(store).evaluate(job)
                    if not eligibility.allowed:
                        finalized = queue.cancel_claimed_job(
                            job["id"],
                            reason=str(
                                eligibility.reason or "job_invalidated"
                            ),
                            worker_id=worker_id,
                            claim_token=job["claim_token"],
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
                                error_code=type(exc).__name__,
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
                    eligibility = JobEligibilityService(store).evaluate(job)
                    if not eligibility.allowed:
                        store.connect().rollback()
                        finalized = queue.cancel_claimed_job(
                            job["id"],
                            reason=str(eligibility.reason or "job_invalidated"),
                            worker_id=worker_id,
                            claim_token=job["claim_token"],
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
        result_payload = finalized.get("result_json") or {}
        logger.info(
            "worker_id=%s job_id=%s job_type=%s run_id=%s duration_ms=%d status=%s",
            worker_id,
            job["id"],
            job["job_type"],
            result_payload.get("run_id") or "-",
            int((time.monotonic() - started_at) * 1000),
            finalized["status"],
        )
        return finalized
    except Exception:
        if job is not None:
            logger.exception(
                "worker_id=%s job_id=%s job_type=%s run_id=- duration_ms=%d status=error",
                worker_id,
                job["id"],
                job["job_type"],
                int((time.monotonic() - started_at) * 1000),
            )
        raise
    finally:
        store.close()


def main() -> None:
    logging.basicConfig(
        level=getattr(logging, os.getenv("HORIZON_LOG_LEVEL", "INFO").upper(), logging.INFO),
        format="%(asctime)s %(levelname)s %(name)s %(message)s",
    )
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
