"""Ephemeral ActorOps projection of the existing Bilibili catalog identity."""

from __future__ import annotations

from copy import deepcopy

from .bilibili_source_identity import bilibili_public_target, is_bilibili_source


BILIBILI_ROUTE_KEY = "bilibili/profile/items"


def is_bilibili_record(record):
    return is_bilibili_source(str(record.get("type") or ""), record.get("config"))


def project_bilibili_runtime_record(record, *, route_id=None):
    original = record.get("config") or {}
    runtime_config = {
        key: deepcopy(original[key])
        for key in ("fetch_limit", "keep_latest_item", "analysis_mode", "channel",
                    "topics", "tags", "personal_tags", "service_fetch_window_hours")
        if key in original
    }
    runtime_config.update({
        "platform": "bilibili", "kind": "profile",
        "target": bilibili_public_target(original), "enabled": bool(route_id),
        "fetch_limit": int(original.get("fetch_limit") or 20),
        "rss_identity_url": str(original.get("url") or "") if original.get("provider") != "rsshub" else None,
        "rss_identity_key": str(record.get("source_key") or "") if original.get("provider") == "rsshub" else None,
        **({"profile_id": str(route_id)} if route_id else {}),
    })
    return {**record, "type": "apify_social", "catalog_source_type": "rss", "config": runtime_config}
