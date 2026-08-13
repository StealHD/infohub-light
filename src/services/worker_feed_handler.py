"""User Feed refresh execution and rollback-safe publication."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import TYPE_CHECKING, Any

from ..storage.service_store import ServiceStore
from .job_eligibility import JobEligibilityService, effective_manual_refresh_scope
from .media_cache import PostCommitMediaCleanup

if TYPE_CHECKING:
    from ..orchestrator import HorizonOrchestrator
    from .user_analysis_cache import UserAnalysisCache


@dataclass(frozen=True, slots=True)
class WorkerFeedPorts:
    cache_source_avatars: Callable[..., None]
    cache_media: Callable[..., None]
    apify_coordinator: Callable[..., Any]
    build_actor_route: Callable[..., Any]
    apify_key_pool_enabled: Callable[[], bool]
    shared_acquisition_enabled: Callable[[], bool]


def active_catalog_source_ids(
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


def _configure_orchestrator(
    orchestrator: HorizonOrchestrator,
    store: ServiceStore,
    job: dict[str, Any],
    *,
    data_dir: str,
    analysis_cache: UserAnalysisCache,
    ports: WorkerFeedPorts,
) -> None:
    from .usage_attempt_meter import UsageAttemptMeter

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
            ports.apify_coordinator(
                store,
                workspace_id=str(job["workspace_id"]),
                data_dir=data_dir,
            )
        )
    if ports.apify_key_pool_enabled() and hasattr(
        orchestrator, "set_service_apify_actor_route"
    ):
        orchestrator.set_service_apify_actor_route(
            ports.build_actor_route(
                store,
                data_dir=data_dir,
                workspace_id=str(job["workspace_id"]),
            ),
            job_id=str(job["id"]),
        )
    if ports.apify_key_pool_enabled() and hasattr(
        orchestrator, "set_service_apify_actor_ops"
    ):
        from .apify_actor_ops import ApifyActorOpsService

        orchestrator.set_service_apify_actor_ops(
            ApifyActorOpsService(
                store,
                workspace_id=str(job["workspace_id"]),
            ),
            job_id=str(job["id"]),
        )
    if ports.shared_acquisition_enabled() and hasattr(
        orchestrator, "set_service_acquisition_coordinator"
    ):
        from .source_acquisition import SourceAcquisitionCoordinator

        orchestrator.set_service_acquisition_coordinator(
            SourceAcquisitionCoordinator(
                store,
                workspace_id=job["workspace_id"],
                user_id=job["user_id"],
                job_id=job["id"],
            )
        )


def _stage_user_feed_publication(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    config: Any,
    orchestrator: HorizonOrchestrator,
    run_result: Any,
    ports: WorkerFeedPorts,
) -> dict[str, Any]:
    from .feed_production import (
        FeedProductionService,
        FeedRunFailed,
        active_service_source_ids,
    )
    from .feed_run import safe_run_diagnostics
    from .source_health import SourceHealthService
    from .source_schedule import SourceScheduleService

    publication = store.connect()
    if not publication.in_transaction:
        publication.execute("BEGIN IMMEDIATE")
    cleanup = PostCommitMediaCleanup()
    try:
        JobEligibilityService(store).require_current_attempt(str(job["id"]))
        if hasattr(orchestrator, "assert_service_apify_actor_ops_publishable"):
            orchestrator.assert_service_apify_actor_ops_publishable()
        ports.cache_source_avatars(
            job,
            data_dir=data_dir,
            store=store,
            result=run_result,
            commit=False,
            publication_cleanup=cleanup,
        )
        if run_result.status == "failed":
            raise FeedRunFailed(run_result)
        publish_watermarks = getattr(
            orchestrator, "publish_service_apify_watermarks", None
        )
        if callable(publish_watermarks):
            publish_watermarks(connection=publication)
        ports.cache_media(
            job,
            data_dir=data_dir,
            store=store,
            items=list(run_result.items),
            commit=False,
            publication_cleanup=cleanup,
        )
        all_source_ids = active_catalog_source_ids(
            store,
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
        )
        configured_ids = active_service_source_ids(config)
        current_outcomes = tuple(
            outcome
            for outcome in run_result.source_outcomes
            if outcome.source_id in configured_ids & all_source_ids
        )
        subscriptions = store.list_user_subscriptions(job["user_id"])
        snapshot = FeedProductionService(store, config).save_run_result(
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
            job_id=job["id"],
            job_type="user_feed_refresh",
            result=run_result,
            active_source_ids=all_source_ids if subscriptions else None,
            publication_fence=(
                orchestrator.assert_service_apify_actor_ops_publishable
                if hasattr(orchestrator, "assert_service_apify_actor_ops_publishable")
                else None
            ),
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
            "_media_cleanup": cleanup,
        }
    except Exception:
        if publication.in_transaction:
            publication.rollback()
        cleanup.discard()
        raise


def run_user_feed_refresh(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ports: WorkerFeedPorts,
) -> dict[str, Any]:
    from ..orchestrator import HorizonOrchestrator
    from ..storage.manager import StorageManager
    from .feed_schedule import SCHEDULED_REFRESH_REASON
    from .user_analysis_cache import UserAnalysisCache
    from .user_config_builder import build_user_config

    storage = StorageManager(data_dir=data_dir)
    scheduled = (
        (job.get("payload_json") or {}).get("reason") == SCHEDULED_REFRESH_REASON
    )
    current_user = store.get_user(str(job["user_id"]))
    if current_user is None:
        raise RuntimeError("refresh user no longer exists")
    source_scope = (
        "all" if scheduled else effective_manual_refresh_scope(job, current_user)
    )
    config = build_user_config(
        store=store,
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        base_config=storage.load_config(),
        schedule_scope="global" if scheduled else "all",
        source_scope=source_scope,
    )
    cache = UserAnalysisCache(
        store,
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        job_id=job["id"],
    )
    try:
        cache.prune()
        orchestrator = HorizonOrchestrator(config, storage)
        _configure_orchestrator(
            orchestrator,
            store,
            job,
            data_dir=data_dir,
            analysis_cache=cache,
            ports=ports,
        )
        raw_hours = (job.get("payload_json") or {}).get("hours")
        run_result = asyncio.run(
            orchestrator.execute(
                force_hours=int(raw_hours) if raw_hours is not None else None,
                enrich=False,
            )
        )
        if hasattr(orchestrator, "assert_service_apify_actor_ops_publishable"):
            orchestrator.assert_service_apify_actor_ops_publishable()
        JobEligibilityService(store).require_current_attempt(str(job["id"]))
    finally:
        cache.close()
    return _stage_user_feed_publication(
        job,
        data_dir=data_dir,
        store=store,
        config=config,
        orchestrator=orchestrator,
        run_result=run_result,
        ports=ports,
    )
