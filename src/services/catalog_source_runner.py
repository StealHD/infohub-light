"""Run one catalog source in a user-scoped fetch job."""

from __future__ import annotations

import asyncio
import json
from copy import deepcopy
from pathlib import Path
from typing import Any

from ..models import Config
from ..orchestrator import HorizonOrchestrator
from ..storage.manager import StorageManager
from ..storage.service_store import ServiceStore
from .user_config_builder import _append_source, _ensure_sources
from .user_feed_store import UserFeedStore


def _reset_sources_for_single_source(data: dict[str, Any]) -> dict[str, Any]:
    sources = _ensure_sources(data)
    sources["rss"] = []
    sources["github"] = []
    sources["hackernews"] = {"enabled": False, **sources.get("hackernews", {})}
    sources["reddit"] = {**sources["reddit"], "enabled": False, "subreddits": [], "users": []}
    sources["telegram"] = {**sources["telegram"], "enabled": False, "channels": []}
    sources["apify_social"] = {
        **sources["apify_social"],
        "enabled": False,
        "subscriptions": [],
    }
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
    _append_source(sources, record)
    return data


def run_catalog_source_fetch(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
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
    asyncio.run(
        HorizonOrchestrator(config, storage).run(
            force_hours=int(payload.get("hours") or config.filtering.time_window_hours),
            send_notifications=False,
            write_summaries=False,
            incremental=True,
            enrich=False,
        )
    )
    payload_path = Path(data_dir) / "site" / "radar-data.json"
    if payload_path.exists():
        feed_payload = json.loads(payload_path.read_text(encoding="utf-8"))
    else:
        feed_payload = {"items": [], "generated_at": ""}
    snapshot = UserFeedStore(store).save_snapshot(
        workspace_id=job["workspace_id"],
        user_id=job["user_id"],
        job_id=job["id"],
        payload=feed_payload,
    )
    return {
        "ok": True,
        "job_type": "source_fetch",
        "source_id": source["id"],
        "source_type": source["type"],
        "source_key": source.get("source_key"),
        "snapshot_id": snapshot["id"],
        "item_count": snapshot["item_count"],
    }
