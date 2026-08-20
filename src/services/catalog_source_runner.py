"""Run one catalog source in a user-scoped fetch job."""

from __future__ import annotations

import asyncio
import logging
from copy import deepcopy
from typing import Any

from ..models import Config
from ..orchestrator import HorizonOrchestrator
from ..storage.manager import StorageManager
from ..storage.service_store import ServiceStore
from .user_config_builder import (
    _append_source,
    _disable_non_catalog_sources,
    _ensure_sources,
    _record_with_runtime_fetch_window,
)
from .feed_production import FeedProductionService, FeedRunFailed
from .source_health import SourceHealthService
from .source_acquisition import (
    SourceAcquisitionCoordinator,
    shared_acquisition_enabled,
)
from .user_analysis_cache import UserAnalysisCache
from .usage_attempt_meter import UsageAttemptMeter
from .apify_pool_runtime import apify_coordinator_for_workspace
from .apify_key_pool import apify_key_pool_enabled
from .apify_actor_monitoring import build_apify_actor_route
from .apify_actor_source_runtime import with_actorops_runtime_profiles
from .operation_log import safe_emit_operation_event
from .media_cache import MediaCacheService, PostCommitMediaCleanup
from .source_avatar import SourceAvatarService


logger = logging.getLogger(__name__)


def _reset_sources_for_single_source(data: dict[str, Any]) -> dict[str, Any]:
    sources = _ensure_sources(data)
    sources["rss"] = []
    sources["github"] = []
    sources["hackernews"] = {**sources.get("hackernews", {}), "enabled": False}
    sources["reddit"] = {**sources["reddit"], "enabled": False, "subreddits": [], "users": []}
    sources["telegram"] = {**sources["telegram"], "enabled": False, "channels": []}
    sources["apify_social"] = {
        **sources["apify_social"],
        "enabled": False,
        "subscriptions": [],
    }
    _disable_non_catalog_sources(sources)
    return sources


def _record_from_source_and_subscription(
    *,
    source: dict[str, Any],
    user_id: str,
    subscription: dict[str, Any] | None = None,
) -> dict[str, Any]:
    return {
        "subscription_id": subscription["id"] if subscription else None,
        "user_id": user_id,
        "source_id": source["id"],
        "subscription_enabled": bool(subscription["enabled"]) if subscription else True,
        "override_channel": subscription["override_channel"] if subscription else None,
        "override_topics": subscription["override_topics"] if subscription else [],
        "personal_tags": subscription["personal_tags"] if subscription else [],
        "analysis_mode": subscription["analysis_mode"] if subscription else "full",
        "priority": subscription["priority"] if subscription else 0,
        "workspace_id": source["workspace_id"],
        "scope": source["scope"],
        "owner_user_id": source["owner_user_id"],
        "type": source["type"],
        "display_name": source["display_name"],
        "description": source["description"],
        "default_channel": source["default_channel"],
        "default_topics": source["default_topics"],
        "config": source["config"],
        "source_key": source.get("source_key"),
        "secret_env": source.get("secret_env"),
        "enforce_public_network": bool(source.get("enforce_public_network")),
        "source_enabled": bool(source["enabled"]),
    }


def _record_for_job(
    *,
    store: ServiceStore,
    workspace_id: str,
    user_id: str,
    source_id: str,
    subscription_id: str | None = None,
) -> dict[str, Any]:
    source = store.get_source(source_id)
    if not source or source["workspace_id"] != workspace_id or not source["enabled"]:
        raise LookupError("catalog source not found or disabled")

    subscriptions = store.list_user_subscriptions_with_sources(
        workspace_id=workspace_id,
        user_id=user_id,
        include_disabled_sources=True,
    )
    for record in subscriptions:
        if record["source_id"] != source_id:
            continue
        if subscription_id and record["subscription_id"] != subscription_id:
            continue
        return record

    subscription = store.get_subscription(subscription_id) if subscription_id else None
    if subscription and subscription["user_id"] != user_id:
        raise LookupError("subscription not found for user")
    return _record_from_source_and_subscription(
        source=source,
        user_id=user_id,
        subscription=subscription,
    )


def build_catalog_source_config_data(
    *,
    store: ServiceStore,
    workspace_id: str,
    user_id: str,
    source_id: str,
    base_config: dict[str, Any] | Config,
    subscription_id: str | None = None,
) -> dict[str, Any]:
    """Return a Config-compatible dict containing exactly one catalog source."""

    data = base_config.model_dump(mode="json") if isinstance(base_config, Config) else deepcopy(base_config)
    sources = _reset_sources_for_single_source(data)
    record = _record_for_job(
        store=store,
        workspace_id=workspace_id,
        user_id=user_id,
        source_id=source_id,
        subscription_id=subscription_id,
    )
    record = with_actorops_runtime_profiles(
        store,
        workspace_id=workspace_id,
        records=(record,),
    )[0]
    filtering = data.get("filtering") if isinstance(data.get("filtering"), dict) else {}
    _append_source(
        sources,
        _record_with_runtime_fetch_window(
            store,
            record,
            rss_initial_fetch_window_hours=int(
                filtering.get("rss_initial_fetch_window_hours", 168)
            ),
        ),
    )
    return data


def run_catalog_source_fetch(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    commit: bool = True,
) -> dict[str, Any]:
    """Execute a source_fetch job for a single catalog source and save a user snapshot."""

    source_id = str(job.get("source_id") or "")
    if not source_id:
        raise ValueError("catalog source_fetch requires source_id")

    source = store.get_source(source_id)
    if not source:
        raise LookupError("catalog source not found")

    storage = StorageManager(data_dir=data_dir)
    base_config = storage.load_config()
    config = Config.model_validate(
        build_catalog_source_config_data(
            store=store,
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
            source_id=source_id,
            subscription_id=job.get("subscription_id"),
            base_config=base_config,
        )
    )
    payload = job.get("payload_json") or {}
    raw_force_hours = payload.get("hours")
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
            apify_key_pool_enabled()
            and hasattr(orchestrator, "set_service_apify_actor_ops")
        ):
            from .actorops.service import build_source_actorops_service

            orchestrator.set_service_apify_actor_ops(
                build_source_actorops_service(
                    store,
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
        if hasattr(
            orchestrator,
            "assert_service_apify_actor_ops_publishable",
        ):
            orchestrator.assert_service_apify_actor_ops_publishable()
    finally:
        analysis_cache.close()
    return _stage_catalog_publication(
        job,
        data_dir=data_dir,
        store=store,
        config=config,
        orchestrator=orchestrator,
        run_result=run_result,
        source=source,
        source_id=source_id,
        commit=commit,
    )


def _stage_catalog_publication(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    config: Config,
    orchestrator: Any,
    run_result: Any,
    source: dict[str, Any],
    source_id: str,
    commit: bool,
) -> dict[str, Any]:
    """Stage a source Feed and media references with rollback-safe files."""

    publication = store.connect()
    if not publication.in_transaction:
        publication.execute("BEGIN IMMEDIATE")
    cleanup = PostCommitMediaCleanup()
    try:
        if hasattr(
            orchestrator,
            "assert_service_apify_actor_ops_publishable",
        ):
            orchestrator.assert_service_apify_actor_ops_publishable()

        avatar_cleanup = PostCommitMediaCleanup()
        publication.execute("SAVEPOINT actor_ops_avatar_cache")
        try:
            avatar_refreshes = SourceAvatarService(
                store,
                data_dir=data_dir,
            ).refresh_run_result(
                workspace_id=str(job["workspace_id"]),
                result=run_result,
                commit=False,
                media_cleanup=avatar_cleanup,
            )
            publication.execute("RELEASE actor_ops_avatar_cache")
            cleanup.absorb(avatar_cleanup)
        except Exception:
            publication.execute("ROLLBACK TO actor_ops_avatar_cache")
            publication.execute("RELEASE actor_ops_avatar_cache")
            avatar_cleanup.discard()
            avatar_refreshes = []
            logger.warning(
                "source avatar cache failed job_id=%s; feed finalization will continue",
                job.get("id"),
            )
        for refresh in avatar_refreshes:
            safe_emit_operation_event(
                category="source",
                action="avatar_cache",
                outcome=(
                    "succeeded"
                    if refresh.status == "stored"
                    else "skipped"
                    if refresh.status in {"unchanged", "candidate_missing"}
                    else "partial"
                    if refresh.status == "kept_previous"
                    else "denied"
                    if refresh.status == "identity_mismatch"
                    else "failed"
                ),
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
        if run_result.status == "failed":
            raise FeedRunFailed(run_result)
        publish_watermarks = getattr(
            orchestrator,
            "publish_service_apify_watermarks",
            None,
        )
        if callable(publish_watermarks):
            publish_watermarks(connection=publication)

        media_cleanup = PostCommitMediaCleanup()
        publication.execute("SAVEPOINT actor_ops_media_cache")
        try:
            MediaCacheService(store, data_dir=data_dir).cache_items(
                workspace_id=job["workspace_id"],
                user_id=job["user_id"],
                items=list(run_result.items),
                commit=False,
                media_cleanup=media_cleanup,
            )
            publication.execute("RELEASE actor_ops_media_cache")
            cleanup.absorb(media_cleanup)
        except Exception:
            publication.execute("ROLLBACK TO actor_ops_media_cache")
            publication.execute("RELEASE actor_ops_media_cache")
            media_cleanup.discard()

        snapshot = FeedProductionService(store, config).save_run_result(
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
            job_id=job["id"],
            job_type="source_fetch",
            source_id=source_id,
            result=run_result,
            publication_fence=(
                orchestrator.assert_service_apify_actor_ops_publishable
                if hasattr(
                    orchestrator,
                    "assert_service_apify_actor_ops_publishable",
                )
                else None
            ),
            commit=False,
        )
        source_outcomes = tuple(
            outcome
            for outcome in run_result.source_outcomes
            if outcome.source_id == source_id
        )
        fetched_count = sum(
            max(int(outcome.fetched_count), 0) for outcome in source_outcomes
        )
        SourceHealthService(store).apply_outcomes(
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
            job_id=job["id"],
            attempted_at=run_result.finished_at,
            outcomes=source_outcomes,
            commit=False,
        )
        if commit:
            publication.commit()
            cleanup.run()
        return {
            "ok": True,
            "job_type": "source_fetch",
            "source_id": source["id"],
            "source_type": source["type"],
            "source_key": source.get("source_key"),
            "run_id": run_result.run_id,
            "run_status": run_result.status,
            "snapshot_id": snapshot["id"],
            "snapshot_created": bool(snapshot.get("snapshot_created", True)),
            "fetched_count": fetched_count,
            "item_count": snapshot["item_count"],
            "new_item_count": snapshot["new_item_count"],
            "analysis_usage": run_result.analysis_usage.as_dict(),
            "acquisition_usage": run_result.acquisition_usage.as_dict(),
            "_job_status": run_result.status,
            **({} if commit else {"_media_cleanup": cleanup}),
        }
    except Exception:
        if publication.in_transaction:
            publication.rollback()
        cleanup.discard()
        raise
