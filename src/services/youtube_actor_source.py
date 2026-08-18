"""ActorOps runtime projection and free provisioning for YouTube channels."""

from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from typing import Any

from ..apify_actor_identity import source_target_fingerprint
from ..storage.service_store import ServiceStore
from .source_type_registry import is_youtube_channel_config


YOUTUBE_ROUTE_KEY = "youtube/channel/items"
_DISCOVERY_COOLDOWN = timedelta(hours=24)


def is_youtube_channel_record(record: dict[str, Any]) -> bool:
    """Return whether one catalog record is an official YouTube channel feed."""

    return bool(
        str(record.get("type") or "") == "rss"
        and is_youtube_channel_config(record.get("config"))
    )


def project_youtube_actor_runtime_record(
    record: dict[str, Any],
    *,
    route_id: str,
) -> dict[str, Any]:
    """Convert one catalog YouTube RSS identity into a routed Actor runtime row."""

    config = record.get("config") if isinstance(record.get("config"), dict) else {}
    target = str(config.get("url") or "").strip()
    if not target:
        raise ValueError("YouTube Actor runtime requires a canonical channel feed")
    runtime_config = {
        "profile_id": str(route_id),
        "platform": "youtube",
        "kind": "channel",
        "target": target,
        "fetch_limit": int(config.get("fetch_limit") or 20),
        "enabled": bool(config.get("enabled", True)),
        "analysis_mode": str(config.get("analysis_mode") or "full"),
    }
    projected = dict(record)
    projected["type"] = "apify_social"
    projected["config"] = runtime_config
    return projected


def provision_youtube_actor_sources(store: ServiceStore) -> dict[str, int]:
    """Bind subscribed YouTube channels and queue bounded free discovery.

    This runs in the Worker maintenance cycle.  It creates no paid validation:
    an existing pending candidate remains pending for the regular controlled
    Canary approval workflow.
    """

    from .apify_actor_ops import ActorOpsError, ApifyActorOpsService
    from .apify_key_pool import apify_key_pool_enabled

    if not apify_key_pool_enabled():
        return {"bound": 0, "discoveries": 0, "skipped": 0}

    connection = store.connect()
    rows = connection.execute(
        """
        SELECT DISTINCT source.id, source.workspace_id, source.config_json
        FROM source_catalog AS source
        JOIN user_subscriptions AS subscription
          ON subscription.source_id = source.id AND subscription.enabled = 1
        WHERE source.type = 'rss' AND source.enabled = 1
        ORDER BY source.workspace_id, source.id
        """
    ).fetchall()
    bound = 0
    discoveries = 0
    skipped = 0
    now = datetime.now(timezone.utc)
    for row in rows:
        try:
            config = json.loads(str(row["config_json"] or "{}"))
        except json.JSONDecodeError:
            skipped += 1
            continue
        record = {"type": "rss", "config": config}
        if not is_youtube_channel_record(record):
            continue
        workspace_id = str(row["workspace_id"])
        ops = ApifyActorOpsService(store, workspace_id=workspace_id)
        route = next(
            (
                item
                for item in ops.list_routes()
                if str(item.get("route_key")) == YOUTUBE_ROUTE_KEY
            ),
            None,
        )
        if route is None:
            skipped += 1
            continue
        route_id = str(route["route_id"])
        source_id = str(row["id"])
        try:
            ops.get_source_binding(source_id)
        except ActorOpsError as exc:
            if exc.status_code != 404:
                raise
            ops.bind_source(
                source_id=source_id,
                route_id=route_id,
                target_fingerprint=source_target_fingerprint(
                    workspace_id,
                    route_id,
                    str(config["url"]),
                    platform="youtube",
                ),
                mode="fallback",
            )
            bound += 1
        if ops.source_capability_ready(route_id):
            continue
        recent = connection.execute(
            """
            SELECT stage, updated_at
            FROM apify_actor_discovery_runs
            WHERE workspace_id = ? AND route_id = ?
            ORDER BY updated_at DESC, run_id DESC
            LIMIT 1
            """,
            (workspace_id, route_id),
        ).fetchone()
        if recent is not None:
            updated_at = datetime.fromisoformat(str(recent["updated_at"]))
            if updated_at.tzinfo is None:
                updated_at = updated_at.replace(tzinfo=timezone.utc)
            if updated_at.astimezone(timezone.utc) >= now - _DISCOVERY_COOLDOWN:
                continue
        result = ops.request_support_check(
            platform="youtube",
            target_type="channel",
            capability="items",
            trigger_reason="youtube_source_provisioning",
            expected_generation=ops.catalog_generation(),
        )
        if result.get("kind") == "discovery":
            discoveries += 1
    return {"bound": bound, "discoveries": discoveries, "skipped": skipped}


__all__ = [
    "YOUTUBE_ROUTE_KEY",
    "is_youtube_channel_record",
    "project_youtube_actor_runtime_record",
    "provision_youtube_actor_sources",
]
