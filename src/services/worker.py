"""Worker loop for queued InfoHub service jobs."""

from __future__ import annotations

import argparse
import logging
import os
import re
import threading
import time
from datetime import datetime, timezone
from typing import Any

import httpx
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
from .quota import QuotaService
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


def _terminalize_failed_actor_discovery(
    store: ServiceStore,
    job: dict[str, Any],
) -> bool:
    """Fail a broken discovery run in the caller's job-finalization transaction."""

    if str(job.get("job_type") or "") != "apify_actor_discovery":
        return False
    payload = (
        job.get("payload_json")
        if isinstance(job.get("payload_json"), dict)
        else {}
    )
    run_id = str(payload.get("run_id") or "").strip()
    if not run_id:
        return False
    cursor = store.connect().execute(
        """
        UPDATE apify_actor_discovery_runs
        SET stage = 'failed', error_code = 'apify_actor_discovery_failed',
            updated_at = ?
        WHERE workspace_id = ? AND run_id = ?
          AND stage IN (
              'queued', 'searching', 'metadata', 'ranking',
              'static_validation', 'input_validation'
          )
        """,
        (
            datetime.now(timezone.utc).isoformat(),
            str(job.get("workspace_id") or ""),
            run_id,
        ),
    )
    return cursor.rowcount == 1


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


def _cancel_claimed_job_with_validation(
    queue: JobQueue,
    store: ServiceStore,
    job: dict[str, Any],
    *,
    reason: str,
    worker_id: str,
) -> dict[str, Any]:
    """Atomically cancel a claim and any paid validation not yet attempted."""

    connection = store.connect()
    owns_transaction = not connection.in_transaction
    try:
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        _terminalize_unstarted_actor_validation(
            store,
            job,
            status="cancelled",
            semantic_outcome=reason,
        )
        finalized = queue.cancel_claimed_job(
            str(job["id"]),
            reason=reason,
            worker_id=worker_id,
            claim_token=str(job["claim_token"]),
            commit=False,
        )
        if owns_transaction:
            connection.commit()
        return finalized
    except Exception:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        raise


def _cache_run_media(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    items: list[Any],
    commit: bool = True,
    publication_cleanup: PostCommitMediaCleanup | None = None,
) -> None:
    """Best-effort media caching must never change the feed job outcome."""

    conn = store.connect()
    savepoint = not commit and conn.in_transaction
    if not commit and publication_cleanup is None:
        raise RuntimeError("publication_cleanup is required inside an outer transaction")
    stage_cleanup = PostCommitMediaCleanup()
    if savepoint:
        conn.execute("SAVEPOINT actor_ops_media_cache")
    try:
        MediaCacheService(store, data_dir=data_dir).cache_items(
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
            items=items,
            commit=commit,
            media_cleanup=(stage_cleanup if not commit else None),
        )
        if savepoint:
            conn.execute("RELEASE actor_ops_media_cache")
            publication_cleanup.absorb(stage_cleanup)
    except Exception:
        if savepoint:
            conn.execute("ROLLBACK TO actor_ops_media_cache")
            conn.execute("RELEASE actor_ops_media_cache")
        elif conn.in_transaction:
            conn.rollback()
        stage_cleanup.discard()
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
    commit: bool = True,
    publication_cleanup: PostCommitMediaCleanup | None = None,
) -> None:
    """Persist source-level avatar evidence without changing the Feed outcome."""

    conn = store.connect()
    savepoint = not commit and conn.in_transaction
    if not commit and publication_cleanup is None:
        raise RuntimeError("publication_cleanup is required inside an outer transaction")
    stage_cleanup = PostCommitMediaCleanup()
    if savepoint:
        conn.execute("SAVEPOINT actor_ops_avatar_cache")
    try:
        refreshes = SourceAvatarService(
            store,
            data_dir=data_dir,
        ).refresh_run_result(
            workspace_id=str(job["workspace_id"]),
            result=result,
            commit=commit,
            media_cleanup=(stage_cleanup if not commit else None),
        )
        if savepoint:
            conn.execute("RELEASE actor_ops_avatar_cache")
            publication_cleanup.absorb(stage_cleanup)
    except Exception:
        if savepoint:
            conn.execute("ROLLBACK TO actor_ops_avatar_cache")
            conn.execute("RELEASE actor_ops_avatar_cache")
        elif conn.in_transaction:
            conn.rollback()
        stage_cleanup.discard()
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


def _actor_validation_id(job: dict[str, Any]) -> str | None:
    if str(job.get("job_type") or "") != "apify_actor_validation":
        return None
    payload = job.get("payload_json")
    if not isinstance(payload, dict) or set(payload) != {"validation_id"}:
        return None
    validation_id = str(payload.get("validation_id") or "").strip()
    return validation_id or None


def _actor_canary_batch_id(job: dict[str, Any]) -> str | None:
    if str(job.get("job_type") or "") != "apify_actor_canary_batch":
        return None
    payload = job.get("payload_json")
    if not isinstance(payload, dict) or set(payload) != {"batch_id"}:
        return None
    batch_id = str(payload.get("batch_id") or "").strip()
    return batch_id or None


def _actor_freshness_check_id(job: dict[str, Any]) -> str | None:
    if str(job.get("job_type") or "") != "apify_actor_freshness_check":
        return None
    payload = job.get("payload_json")
    if not isinstance(payload, dict) or set(payload) != {"check_id"}:
        return None
    check_id = str(payload.get("check_id") or "").strip()
    return check_id or None


def _terminalize_unstarted_actor_validation(
    store: ServiceStore,
    job: dict[str, Any],
    *,
    status: str,
    semantic_outcome: str,
) -> bool:
    """Release a paid approval when its Worker job ends before an Attempt."""

    freshness_check_id = _actor_freshness_check_id(job)
    if freshness_check_id is not None:
        from .apify_actor_resilience import ApifyActorResilienceService

        ApifyActorResilienceService(
            store,
            workspace_id=str(job.get("workspace_id") or ""),
        ).fail_freshness_check(
            freshness_check_id,
            reason_code=semantic_outcome,
        )
        return True

    batch_id = _actor_canary_batch_id(job)
    if batch_id is not None:
        if status not in {"failed", "cancelled"}:
            raise ValueError("unstarted Actor batch must become terminal")
        now = datetime.now(timezone.utc).isoformat()
        connection = store.connect()
        connection.execute(
            """
            UPDATE apify_actor_validations
            SET status = ?, semantic_outcome = ?, cost_usd = 0,
                cost_final = 1, counts_toward_canary = 0,
                completed_at = ?
            WHERE workspace_id = ? AND status = 'queued'
              AND attempt_id IS NULL
              AND validation_id IN (
                  SELECT validation_id
                  FROM apify_actor_canary_batch_items
                  WHERE workspace_id = ? AND batch_id = ?
              )
            """,
            (
                status,
                _safe_machine_code(
                    semantic_outcome,
                    "apify_actor_validation_not_started",
                ),
                now,
                str(job.get("workspace_id") or ""),
                str(job.get("workspace_id") or ""),
                batch_id,
            ),
        )
        connection.execute(
            """
            UPDATE apify_actor_canary_batch_items
            SET status = 'not_needed_no_charge',
                semantic_outcome = ?, actual_cost_usd = 0,
                cost_final = 1, completed_at = ?, updated_at = ?
            WHERE workspace_id = ? AND batch_id = ?
              AND status IN ('planned', 'queued', 'preflight_passed')
            """,
            (
                _safe_machine_code(
                    semantic_outcome,
                    "apify_actor_validation_not_started",
                ),
                now,
                now,
                str(job.get("workspace_id") or ""),
                batch_id,
            ),
        )
        updated = connection.execute(
            """
            UPDATE apify_actor_canary_batches
            SET status = ?, stop_reason = ?, actual_cost_usd = 0,
                cost_final = 1, completed_at = ?, updated_at = ?
            WHERE workspace_id = ? AND batch_id = ?
              AND status IN ('queued', 'preflighting')
            """,
            (
                status,
                _safe_machine_code(
                    semantic_outcome,
                    "apify_actor_validation_not_started",
                ),
                now,
                now,
                str(job.get("workspace_id") or ""),
                batch_id,
            ),
        )
        connection.execute(
            """
            UPDATE apify_actor_pool_stages
            SET status = ?, last_error_code = ?, updated_at = ?
            WHERE workspace_id = ?
              AND stage_id = (
                  SELECT pool_stage_id
                  FROM apify_actor_canary_batches
                  WHERE workspace_id = ? AND batch_id = ?
              )
              AND status IN ('queued', 'validating_route')
            """,
            (
                status,
                _safe_machine_code(
                    semantic_outcome,
                    "apify_actor_validation_not_started",
                ),
                now,
                str(job.get("workspace_id") or ""),
                str(job.get("workspace_id") or ""),
                batch_id,
            ),
        )
        return updated.rowcount == 1
    validation_id = _actor_validation_id(job)
    if validation_id is None:
        return False
    if status not in {"failed", "cancelled"}:
        raise ValueError("unstarted Actor validation must become terminal")
    now = datetime.now(timezone.utc).isoformat()
    updated = store.connect().execute(
        """
        UPDATE apify_actor_validations
        SET status = ?, semantic_outcome = ?, cost_usd = 0,
            cost_final = 1, counts_toward_canary = 0,
            completed_at = ?
        WHERE workspace_id = ? AND validation_id = ?
          AND status = 'queued' AND attempt_id IS NULL
        """,
        (
            status,
            _safe_machine_code(
                semantic_outcome,
                "apify_actor_validation_not_started",
            ),
            now,
            str(job.get("workspace_id") or ""),
            validation_id,
        ),
    )
    return updated.rowcount == 1


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


def _run_apify_actor_validation(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    import asyncio

    from ..scrapers.apify_client import ApifyClient
    from .apify_actor_canary import (
        ApifyActorCanaryRunner,
        actor_canary_timeout_seconds,
    )
    from .apify_actor_ops import ApifyActorOpsService

    validation_id = _actor_validation_id(job)
    if (
        not validation_id
        or int(job.get("max_attempts") or 0) != 1
        or int(job.get("priority") or 0) != 100
    ):
        raise PaidCanaryAuthorizationError(
            "Actor validation job authorization metadata is invalid"
        )
    actor = store.get_user(str(job["user_id"]))
    if (
        actor is None
        or not bool(actor.get("enabled"))
        or actor.get("role") not in {"owner", "admin"}
    ):
        raise PaidCanaryAuthorizationError(
            "Actor validation requires an active administrator"
        )
    coordinator = apify_coordinator_for_workspace(
        store,
        workspace_id=str(job["workspace_id"]),
        data_dir=data_dir,
        purpose="validation",
    )
    if coordinator is None:
        raise PaidCanaryUnavailableError(
            "Actor validation requires the enabled Apify Key pool"
        )
    pool_state = coordinator.public_state(str(job["workspace_id"]))
    validation_secret_id = str(
        pool_state.get("validation_secret_id")
        or pool_state.get("active_secret_id")
        or ""
    )
    if not validation_secret_id:
        raise PaidCanaryUnavailableError(
            "Actor validation requires an active Apify credential"
        )
    metadata_credential = coordinator.quota_candidate(validation_secret_id)

    async def execute() -> dict[str, Any]:
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(
            timeout=timeout,
            trust_env=False,
        ) as http_client:
            client = ApifyClient(
                tokens=[
                    (
                        metadata_credential.env_name,
                        metadata_credential.token,
                    )
                ],
                coordinator=coordinator,
                http_client=http_client,
                timeout_seconds=actor_canary_timeout_seconds(),
            )
            result = await ApifyActorCanaryRunner(
                store,
                ApifyActorOpsService(
                    store,
                    workspace_id=str(job["workspace_id"]),
                ),
                client,
            ).run(
                validation_id,
                job_id=str(job["id"]),
            )
            return {
                "ok": True,
                "job_type": "apify_actor_validation",
                **result.public_dict(),
            }

    return asyncio.run(execute())


def _run_apify_actor_canary_batch(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    """Execute one administrator-approved, strictly serial Canary batch."""

    import asyncio

    from ..scrapers.apify_client import ApifyClient, ApifyClientError
    from .apify_actor_canary import (
        ApifyActorCanaryRunner,
        actor_canary_timeout_seconds,
    )
    from .apify_actor_ops import ApifyActorOpsService, ActorOpsError

    batch_id = _actor_canary_batch_id(job)
    if (
        not batch_id
        or int(job.get("max_attempts") or 0) != 1
        or int(job.get("priority") or 0) != 100
    ):
        raise PaidCanaryAuthorizationError(
            "Actor Canary batch authorization metadata is invalid"
        )
    actor = store.get_user(str(job["user_id"]))
    if (
        actor is None
        or not bool(actor.get("enabled"))
        or actor.get("role") not in {"owner", "admin"}
    ):
        raise PaidCanaryAuthorizationError(
            "Actor Canary batch requires an active administrator"
        )
    coordinator = apify_coordinator_for_workspace(
        store,
        workspace_id=str(job["workspace_id"]),
        data_dir=data_dir,
        purpose="validation",
    )
    if coordinator is None:
        raise PaidCanaryUnavailableError(
            "Actor Canary batch requires the enabled Apify Key pool"
        )
    pool_state = coordinator.public_state(str(job["workspace_id"]))
    validation_secret_id = str(
        pool_state.get("validation_secret_id")
        or pool_state.get("active_secret_id")
        or ""
    )
    if not validation_secret_id:
        raise PaidCanaryUnavailableError(
            "Actor Canary batch requires an active Apify credential"
        )
    metadata_credential = coordinator.quota_candidate(validation_secret_id)
    ops = ApifyActorOpsService(
        store,
        workspace_id=str(job["workspace_id"]),
    )

    def cancel_remaining(
        items: list[dict[str, Any]],
        *,
        reason: str,
    ) -> None:
        for item in items:
            validation = ops.get_validation(str(item["validation_id"]))
            if str(validation["status"]) in {"queued", "running"}:
                if str(validation["status"]) == "queued":
                    ops.record_validation(
                        str(item["validation_id"]),
                        status="cancelled",
                        semantic_outcome=reason,
                        cost_usd=0.0,
                        cost_final=True,
                        counts_toward_canary=False,
                    )
                else:
                    continue
            ops.update_canary_batch_item(
                batch_id,
                int(item["ordinal"]),
                status="not_needed_no_charge",
                semantic_outcome=reason,
                actual_cost_usd=0.0,
                cost_final=True,
            )

    async def execute() -> dict[str, Any]:
        current = ops.get_canary_batch(batch_id)
        if str(current["status"]) != "queued":
            raise PaidCanaryAuthorizationError(
                "Actor Canary batch is not queued"
            )
        ops.set_canary_batch_status(
            batch_id,
            expected_statuses=("queued",),
            status="preflighting",
        )
        goal = str(current.get("goal") or "initial_pool")
        stage_id = (
            str(current["pool_stage_id"])
            if current.get("pool_stage_id")
            else None
        )
        if goal != "initial_pool" and stage_id is None:
            raise PaidCanaryAuthorizationError(
                "Staged Actor Canary batch is missing its pool stage"
            )
        if stage_id is not None:
            ops.set_pool_stage_status(
                stage_id,
                expected_statuses=("queued",),
                status="validating_route",
            )
        timeout = httpx.Timeout(30.0, connect=10.0)
        stop_reason: str | None = None
        async with httpx.AsyncClient(
            timeout=timeout,
            trust_env=False,
        ) as http_client:
            client = ApifyClient(
                tokens=[
                    (
                        metadata_credential.env_name,
                        metadata_credential.token,
                    )
                ],
                coordinator=coordinator,
                http_client=http_client,
                timeout_seconds=actor_canary_timeout_seconds(),
            )
            runner = ApifyActorCanaryRunner(store, ops, client)
            items = list(ops.get_canary_batch(batch_id)["items"])
            for index, item in enumerate(items):
                route_ready = (
                    ops.pool_stage_route_ready(stage_id)
                    if stage_id is not None
                    else bool(
                        ops.recommend_active_pool(
                            str(current["route_id"])
                        ).get("ready")
                    )
                )
                if route_ready:
                    stop_reason = (
                        "staged_route_ready"
                        if stage_id is not None
                        else "two_providers_ready"
                    )
                    cancel_remaining(
                        [
                            remaining
                            for remaining in items[index:]
                            if str(remaining.get("status"))
                            not in {"succeeded", "not_needed_no_charge"}
                        ],
                        reason=stop_reason,
                    )
                    break
                if str(item.get("status")) in {
                    "succeeded",
                    "not_needed_no_charge",
                }:
                    continue
                validation_id = str(item["validation_id"])
                revision_id = str(item["revision_id"])
                try:
                    if goal != "compatibility_single":
                        await client.preflight_actor_revision(
                            str(item["actor_id"]),
                            build_id=str(item["build_id"]),
                            build_number=str(item["build_number"]),
                        )
                except ApifyClientError as exc:
                    ops.record_validation(
                        validation_id,
                        status="failed",
                        semantic_outcome=str(exc.code),
                        cost_usd=0.0,
                        cost_final=True,
                        counts_toward_canary=False,
                    )
                    if str(exc.code) == "apify_actor_revision_unavailable":
                        ops.stop_unavailable_revision(
                            revision_id,
                            reason=str(exc.code),
                        )
                    ops.update_canary_batch_item(
                        batch_id,
                        int(item["ordinal"]),
                        status="preflight_failed",
                        semantic_outcome=str(exc.code),
                        actual_cost_usd=0.0,
                        cost_final=True,
                    )
                    if str(exc.code) in {
                        "apify_key_rejected",
                        "apify_actor_revision_preflight_unavailable",
                    }:
                        stop_reason = str(exc.code)
                        cancel_remaining(items[index + 1 :], reason=stop_reason)
                        break
                    continue
                ops.update_canary_batch_item(
                    batch_id,
                    int(item["ordinal"]),
                    status="preflight_passed",
                    semantic_outcome=(
                        "compatibility_preflight_deferred"
                        if goal == "compatibility_single"
                        else "preflight_available"
                    ),
                )
                batch_state = ops.get_canary_batch(batch_id)
                if str(batch_state["status"]) == "preflighting":
                    ops.set_canary_batch_status(
                        batch_id,
                        expected_statuses=("preflighting",),
                        status="running",
                    )
                ops.update_canary_batch_item(
                    batch_id,
                    int(item["ordinal"]),
                    status="running",
                )
                try:
                    result = await runner.run(
                        validation_id,
                        job_id=str(job["id"]),
                        skip_preflight=True,
                    )
                except ActorOpsError as exc:
                    validation = ops.get_validation(validation_id)
                    cost = validation.get("cost_usd")
                    final = bool(validation.get("cost_final"))
                    unknown = str(exc.code) in {
                        "apify_start_outcome_unknown",
                        "apify_run_reconcile_required",
                    }
                    ops.update_canary_batch_item(
                        batch_id,
                        int(item["ordinal"]),
                        status=(
                            "blocked_unknown_start" if unknown else "failed"
                        ),
                        semantic_outcome=str(
                            validation.get("semantic_outcome") or exc.code
                        ),
                        actual_cost_usd=(
                            float(cost) if cost is not None else None
                        ),
                        cost_final=final,
                    )
                    if unknown:
                        stop_reason = "apify_start_outcome_unknown"
                        cancel_remaining(items[index + 1 :], reason=stop_reason)
                        if stage_id is not None:
                            ops.block_pool_stage_unknown_start(stage_id)
                        ops.set_canary_batch_status(
                            batch_id,
                            expected_statuses=("running",),
                            status="blocked_unknown_start",
                            stop_reason=stop_reason,
                        )
                        return {
                            "ok": False,
                            "job_type": "apify_actor_canary_batch",
                            "batch_id": batch_id,
                            "status": "blocked_unknown_start",
                            "error_code": stop_reason,
                            "_job_status": "failed",
                        }
                    continue
                else:
                    validation = ops.get_validation(validation_id)
                    ops.update_canary_batch_item(
                        batch_id,
                        int(item["ordinal"]),
                        status="succeeded",
                        semantic_outcome=result.semantic_outcome,
                        actual_cost_usd=result.cost_usd,
                        cost_final=bool(validation.get("cost_final")),
                    )

            if stage_id is not None and goal == "compatibility_single":
                ops.prepare_compatibility_stage_activation(stage_id)
            elif stage_id is not None:
                source_validation_ids = (
                    ops.prepare_pool_stage_source_validations(stage_id)
                )
                if source_validation_ids:
                    batch_state = ops.get_canary_batch(batch_id)
                    if str(batch_state["status"]) == "preflighting":
                        ops.set_canary_batch_status(
                            batch_id,
                            expected_statuses=("preflighting",),
                            status="running",
                        )
                for validation_id in source_validation_ids:
                    try:
                        await runner.run(
                            validation_id,
                            job_id=str(job["id"]),
                            # A staged source may target an already-proven
                            # Route revision that was not preflighted by this
                            # batch iteration. Every paid POST therefore owns
                            # its own fresh free Actor/Build preflight.
                            skip_preflight=False,
                        )
                    except ActorOpsError as exc:
                        unknown = str(exc.code) in {
                            "apify_start_outcome_unknown",
                            "apify_run_reconcile_required",
                        }
                        ops.refresh_pool_stage_sources(stage_id)
                        if unknown:
                            stop_reason = "apify_start_outcome_unknown"
                            ops.block_pool_stage_unknown_start(stage_id)
                            batch_state = ops.get_canary_batch(batch_id)
                            ops.set_canary_batch_status(
                                batch_id,
                                expected_statuses=(str(batch_state["status"]),),
                                status="blocked_unknown_start",
                                stop_reason=stop_reason,
                            )
                            return {
                                "ok": False,
                                "job_type": "apify_actor_canary_batch",
                                "batch_id": batch_id,
                                "pool_stage_id": stage_id,
                                "status": "blocked_unknown_start",
                                "error_code": stop_reason,
                                "_job_status": "failed",
                            }
                        continue
                    else:
                        ops.refresh_pool_stage_sources(stage_id)
                ops.refresh_pool_stage_sources(stage_id)

        finalized = ops.finalize_canary_batch(
            batch_id,
            stop_reason=stop_reason,
        )
        replenishment_job_id: str | None = None
        if (
            goal == "initial_pool"
            and stage_id is None
            and str(finalized["status"]) == "partial"
        ):
            continuation = ops.get_canary_plan(
                str(finalized["discovery_run_id"])
            )
            if not bool(continuation["ready"]):
                route = ops.get_route(str(finalized["route_id"]))
                discovery = ops.create_discovery_run(
                    str(finalized["route_id"]),
                    trigger_reason="canary_batch_replenishment",
                    expected_generation=int(route["generation"]),
                )
                replenishment = JobQueue(store).create_job(
                    workspace_id=str(job["workspace_id"]),
                    user_id=str(job["user_id"]),
                    job_type="apify_actor_discovery",
                    payload={"run_id": str(discovery["run_id"])},
                    priority=50,
                    max_attempts=1,
                    retention_days=int(
                        os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")
                    ),
                )
                replenishment_job_id = str(replenishment["id"])
        result = {
            "ok": True,
            "job_type": "apify_actor_canary_batch",
            "batch_id": batch_id,
            "status": str(finalized["status"]),
            "success_count": int(finalized["success_count"]),
            "publisher_count": int(finalized["publisher_count"]),
            "actual_cost_usd": finalized.get("actual_cost_usd"),
            "cost_final": bool(finalized.get("cost_final")),
            "replenishment_job_id": replenishment_job_id,
        }
        if stage_id is not None:
            result["pool_stage"] = ops.get_pool_stage(stage_id)
        return result

    return asyncio.run(execute())


def _actor_discovery_queries(route: dict[str, Any]) -> tuple[str, str, str]:
    """Return route-specific Store queries that target content-item Actors."""

    profile = (
        str(route.get("platform") or ""),
        str(route.get("target_type") or ""),
        str(route.get("capability") or ""),
    )
    presets = {
        ("x", "profile", "items"): (
            "x profile posts scraper",
            "twitter user tweets scraper",
            "x profile feed actor",
        ),
        ("youtube", "channel", "items"): (
            "youtube channel videos scraper",
            "youtube public channel videos",
            "youtube channel feed actor",
        ),
        ("instagram", "profile", "items"): (
            "instagram profile posts scraper",
            "instagram user posts scraper",
            "instagram profile feed actor",
        ),
    }
    selected = presets.get(profile)
    if selected is None:
        raise ValueError("Actor discovery route profile is unsupported")
    return selected


def _run_apify_actor_freshness_check(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    """Execute one manual or standing-authorized freshness round."""

    import asyncio

    from ..scrapers.apify_client import ApifyClient
    from .apify_actor_canary import actor_canary_timeout_seconds
    from .apify_actor_freshness import ApifyActorFreshnessRunner
    from .apify_actor_ops import ApifyActorOpsService
    from .apify_actor_resilience import ApifyActorResilienceService

    check_id = _actor_freshness_check_id(job)
    resilience = ApifyActorResilienceService(
        store,
        workspace_id=str(job["workspace_id"]),
    )
    if (
        not check_id
        or int(job.get("max_attempts") or 0) != 1
        or int(job.get("priority") or 0) != 100
    ):
        if check_id:
            resilience.fail_freshness_check(
                check_id,
                reason_code="freshness_job_authorization_invalid",
            )
        raise PaidCanaryAuthorizationError(
            "Actor freshness Job authorization metadata is invalid"
        )
    actor = store.get_user(str(job["user_id"]))
    if (
        actor is None
        or not bool(actor.get("enabled"))
        or actor.get("role") not in {"owner", "admin"}
    ):
        resilience.fail_freshness_check(
            check_id,
            reason_code="freshness_actor_unauthorized",
        )
        raise PaidCanaryAuthorizationError(
            "Actor freshness check requires an active administrator"
        )
    coordinator = apify_coordinator_for_workspace(
        store,
        workspace_id=str(job["workspace_id"]),
        data_dir=data_dir,
        purpose="validation",
        require_validation_key=True,
    )
    if coordinator is None:
        resilience.fail_freshness_check(
            check_id,
            reason_code="validation_key_unavailable",
        )
        raise PaidCanaryUnavailableError(
            "Actor freshness check requires the dedicated validation Key"
        )
    pool_state = coordinator.public_state(str(job["workspace_id"]))
    validation_secret_id = str(pool_state.get("validation_secret_id") or "")
    if not validation_secret_id:
        resilience.fail_freshness_check(
            check_id,
            reason_code="validation_key_unavailable",
        )
        raise PaidCanaryUnavailableError(
            "Actor freshness check requires the dedicated validation Key"
        )
    try:
        credential = coordinator.quota_candidate(validation_secret_id)
    except Exception:
        resilience.fail_freshness_check(
            check_id,
            reason_code="validation_key_unavailable",
        )
        raise

    async def execute() -> dict[str, Any]:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            trust_env=False,
        ) as http_client:
            client = ApifyClient(
                tokens=[(credential.env_name, credential.token)],
                coordinator=coordinator,
                http_client=http_client,
                timeout_seconds=actor_canary_timeout_seconds(),
            )
            runner = ApifyActorFreshnessRunner(
                store,
                ApifyActorOpsService(
                    store,
                    workspace_id=str(job["workspace_id"]),
                ),
                client,
            )
            try:
                result = await runner.run(check_id, job_id=str(job["id"]))
            except Exception as exc:
                runner.resilience.fail_freshness_check(
                    check_id,
                    reason_code=_safe_machine_code(
                        _exception_code(exc),
                        "freshness_job_failed",
                    ).casefold(),
                )
                raise
            return {
                "ok": str(result["status"]) in {"succeeded", "partial"},
                "job_type": "apify_actor_freshness_check",
                "check_id": check_id,
                "status": str(result["status"]),
                "actual_cost_usd": result.get("actual_cost_usd"),
                "cost_final": bool(result.get("cost_final")),
            }

    return asyncio.run(execute())


def _run_apify_actor_discovery(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
) -> dict[str, Any]:
    import asyncio
    import inspect
    import json

    from ..ai.client import create_ai_client
    from .apify_actor_discovery import (
        ActorDiscoveryError,
        ApifyActorDiscoveryService,
        ApifyStoreRestClient,
        LEGACY_UPGRADE_DISCOVERY_CANDIDATE_LIMIT,
    )
    from .apify_actor_ops import ApifyActorOpsService
    from .apify_discovery_ai import resolve_global_discovery_ai

    payload = (
        job.get("payload_json")
        if isinstance(job.get("payload_json"), dict)
        else {}
    )
    run_id = str(payload.get("run_id") or "").strip()
    prefer_existing = payload.get("prefer_existing_legacy_actors", False)
    if (
        not run_id
        or set(payload) not in (
            {"run_id"},
            {"run_id", "prefer_existing_legacy_actors"},
        )
        or not isinstance(prefer_existing, bool)
        or int(job.get("max_attempts") or 0) != 1
    ):
        raise ValueError("Actor discovery job metadata is invalid")
    actor = store.get_user(str(job["user_id"]))
    if actor is None or not bool(actor.get("enabled")) or actor.get("role") == "viewer":
        raise PermissionError("Actor discovery requires an active member")
    ops = ApifyActorOpsService(
        store,
        workspace_id=str(job["workspace_id"]),
    )
    run = ops.get_discovery_run(run_id)
    expanded_compatibility = (
        str(run.get("trigger_reason") or "")
        == "manual_compatibility_candidate_refresh"
    )
    if str(run["stage"]) != "queued":
        # Concurrent support checks can observe the same queued Run before one
        # Worker advances it.  A second one-shot Job must be an idempotent
        # no-op, not a false system failure after the first Job succeeds.
        return {
            "ok": True,
            "job_type": "apify_actor_discovery",
            "run_id": run_id,
            "stage": str(run["stage"]),
            "revision_count": 0,
            "idempotent_replay": True,
        }
    if prefer_existing:
        earlier_active = store.connect().execute(
            """
            SELECT 1
            FROM apify_actor_discovery_runs AS earlier
            WHERE earlier.workspace_id = ?
              AND earlier.route_id = ?
              AND earlier.trigger_reason = 'manual_legacy_upgrade_refresh'
              AND earlier.stage IN (
                  'queued', 'searching', 'metadata', 'ranking',
                  'static_validation', 'input_validation'
              )
              AND earlier.rowid < (
                  SELECT current.rowid
                  FROM apify_actor_discovery_runs AS current
                  WHERE current.workspace_id = ? AND current.run_id = ?
              )
            LIMIT 1
            """,
            (
                str(job["workspace_id"]),
                str(run["route_id"]),
                str(job["workspace_id"]),
                run_id,
            ),
        ).fetchone()
        if earlier_active is not None:
            superseded = ops.update_discovery_run(
                run_id,
                expected_stage="queued",
                stage="failed",
                error_code="superseded_duplicate_refresh",
            )
            return {
                "ok": True,
                "job_type": "apify_actor_discovery",
                "run_id": run_id,
                "stage": superseded["stage"],
                "revision_count": 0,
                "superseded_duplicate": True,
            }
    settings = ops.get_discovery_settings()
    if not bool(settings["enabled"]):
        blocked = ops.update_discovery_run(
            run_id,
            expected_stage="queued",
            stage="blocked_ai_unavailable",
            error_code="discovery_ai_disabled",
        )
        return {
            "ok": True,
            "job_type": "apify_actor_discovery",
            "run_id": run_id,
            "stage": blocked["stage"],
            "revision_count": 0,
        }
    global_ai = resolve_global_discovery_ai(
        store,
        data_dir=data_dir,
        workspace_id=str(job["workspace_id"]),
        secret_ref_id=(
            str(settings["secret_ref_id"])
            if settings.get("secret_ref_id")
            else None
        ),
    )
    if not global_ai.ready or global_ai.config is None:
        blocked = ops.update_discovery_run(
            run_id,
            expected_stage="queued",
            stage="blocked_ai_unavailable",
            error_code="discovery_global_ai_unavailable",
        )
        return {
            "ok": True,
            "job_type": "apify_actor_discovery",
            "run_id": run_id,
            "stage": blocked["stage"],
            "revision_count": 0,
        }
    pool_secret = store.connect().execute(
        """
        SELECT secret.env_name
        FROM apify_key_pool_state AS state
        JOIN secret_refs AS secret ON secret.id = state.active_secret_id
        WHERE state.workspace_id = ?
        """,
        (str(job["workspace_id"]),),
    ).fetchone()
    apify_env = str(pool_secret["env_name"]) if pool_secret else ""
    if not apify_env or not os.getenv(apify_env):
        failed = ops.update_discovery_run(
            run_id,
            expected_stage="queued",
            stage="failed",
            error_code="metadata_token_unavailable",
        )
        return {
            "ok": False,
            "job_type": "apify_actor_discovery",
            "run_id": run_id,
            "stage": failed["stage"],
            "revision_count": 0,
        }
    QuotaService(store).admit_ai_attempt(
        workspace_id=str(job["workspace_id"]),
        user_id=str(job["user_id"]),
        provider=global_ai.provider,
    )
    route = ops.get_route(str(run["route_id"]))
    output_limit = int(run.get("ai_max_output_tokens") or settings["max_output_tokens"])
    ai_config = global_ai.config.model_copy(
        update={
            "enabled": True,
            "temperature": 0.0,
            "max_tokens": output_limit,
        }
    )
    ai_client = create_ai_client(
        ai_config,
        single_attempt=True,
        timeout_seconds=180,
    )

    async def generate(prompt: dict[str, Any]) -> dict[str, Any]:
        started = time.monotonic()
        try:
            raw = await ai_client.complete(
                (
                    "Return one strict JSON object only. Follow the supplied "
                    "Manifest v1 contract exactly. Never invent Actor IDs, "
                    "Build IDs, schema fields, code, templates, credentials, "
                    "headers, tokens, or URLs."
                ),
                json.dumps(prompt, ensure_ascii=False, sort_keys=True),
                temperature=0.0,
                max_tokens=output_limit,
            )
        except Exception as error:
            latency_ms = int((time.monotonic() - started) * 1000)
            ops.record_discovery_ai_metrics(
                run_id,
                latency_ms=latency_ms,
                json_status="unknown",
                manifest_status="not_run",
            )
            status = getattr(error, "status_code", None)
            name = type(error).__name__.casefold()
            if "timeout" in name or isinstance(error, (TimeoutError, httpx.TimeoutException)):
                code = "discovery_ai_timeout"
            elif status in {401, 403}:
                code = "discovery_ai_authentication_failed"
            elif status == 402:
                code = "discovery_ai_balance_unavailable"
            elif status == 404:
                code = "discovery_ai_model_unavailable"
            elif status == 429:
                code = "discovery_ai_rate_limited"
            else:
                code = "discovery_ai_transport_unavailable"
            raise ActorDiscoveryError(code, "Actor discovery AI request failed") from error
        latency_ms = int((time.monotonic() - started) * 1000)
        metrics = getattr(ai_client, "last_completion_metrics", None)
        ops.record_discovery_ai_metrics(
            run_id,
            input_tokens=(metrics.input_tokens if metrics else None),
            completion_tokens=(metrics.completion_tokens if metrics else None),
            reasoning_tokens=(metrics.reasoning_tokens if metrics else None),
            content_tokens=(metrics.content_tokens if metrics else None),
            finish_reason=(metrics.finish_reason if metrics else None),
            latency_ms=latency_ms,
            response_bytes=(metrics.response_bytes if metrics else len(raw.encode("utf-8"))),
            json_status="unknown",
            manifest_status="not_run",
        )
        if not raw.strip():
            ops.record_discovery_ai_metrics(run_id, json_status="empty")
            raise ActorDiscoveryError("discovery_ai_empty_content", "Actor discovery AI returned no content")
        try:
            parsed = json.loads(raw)
        except json.JSONDecodeError as error:
            status = "truncated" if metrics and metrics.finish_reason == "length" else "invalid"
            ops.record_discovery_ai_metrics(run_id, json_status=status)
            code = "discovery_ai_output_truncated" if status == "truncated" else "discovery_ai_invalid_json"
            raise ActorDiscoveryError(code, "Actor discovery AI returned invalid JSON") from error
        if not isinstance(parsed, dict):
            ops.record_discovery_ai_metrics(run_id, json_status="invalid")
            raise ActorDiscoveryError("discovery_ai_contract_invalid", "Actor discovery AI output must be an object")
        ops.record_discovery_ai_metrics(run_id, json_status="valid")
        return parsed

    queries = _actor_discovery_queries(route)

    async def execute() -> dict[str, Any]:
        try:
            async with httpx.AsyncClient(
                timeout=httpx.Timeout(30.0, connect=10.0),
                trust_env=False,
            ) as http_client:
                service = ApifyActorDiscoveryService(
                    ops,
                    ApifyStoreRestClient(
                        os.environ[apify_env],
                        client=http_client,
                    ),
                    generate,
                    ai_provider=global_ai.provider,
                    ai_model=global_ai.model,
                )
                outcome = await service.run_discovery(
                    run_id,
                    queries=queries,
                    preferred_actor_ids=(
                        ops.legacy_actor_ids(str(run["route_id"]))
                        if prefer_existing
                        else ()
                    ),
                    candidate_limit=(
                        LEGACY_UPGRADE_DISCOVERY_CANDIDATE_LIMIT
                        if prefer_existing or expanded_compatibility
                        else None
                    ),
                )
                return {
                    "ok": True,
                    "job_type": "apify_actor_discovery",
                    "run_id": outcome.run_id,
                    "route_id": outcome.route_id,
                    "stage": outcome.stage,
                    "revision_count": len(outcome.revision_ids),
                    "rejected_count": len(outcome.rejected),
                }
        finally:
            close = getattr(ai_client, "aclose", None)
            if callable(close):
                try:
                    close_result = close()
                    if inspect.isawaitable(close_result):
                        await close_result
                except Exception:
                    logger.warning(
                        "Actor discovery AI client close failed error_code=ai_client_close_failed"
                    )

    try:
        return asyncio.run(execute())
    except Exception as exc:
        current = ops.get_discovery_run(run_id)
        if str(current["stage"]) not in {
            "awaiting_canary_approval",
            "candidate_shortfall",
            "blocked_ai_unavailable",
            "failed",
        }:
            ops.update_discovery_run(
                run_id,
                expected_stage=str(current["stage"]),
                stage="failed",
                error_code=_safe_machine_code(
                    getattr(exc, "code", None),
                    "apify_actor_discovery_failed",
                ),
                failure_phase={
                    "searching": "store",
                    "metadata": "metadata",
                    "ranking": "ai_generation",
                    "static_validation": "static_validation",
                    "input_validation": "input_validation",
                }.get(str(current["stage"])),
            )
        raise


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
        with _LeaseHeartbeat(data_dir=data_dir, job=job, lease_seconds=lease):
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
