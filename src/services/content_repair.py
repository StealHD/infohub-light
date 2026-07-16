"""Maintenance-only repair of already indexed user content."""

from __future__ import annotations

import asyncio
from typing import Any, Callable

from ..models import Config, ContentItem
from ..orchestrator import HorizonOrchestrator
from ..storage.manager import StorageManager
from ..storage.service_store import ServiceStore
from .catalog_source_runner import build_catalog_source_config_data
from .feed_production import FeedRunFailed
from .media_cache import MediaCacheService
from .usage_attempt_meter import UsageAttemptMeter
from .user_content_store import UserContentStore


def source_requires_paid_acquisition(source: dict[str, Any]) -> bool:
    """The current paid catalog integration is Apify-backed social content."""

    return str(source.get("type") or "") == "apify_social"


def _fetch_source_items(
    job: dict[str, Any], data_dir: str, store: ServiceStore
) -> list[ContentItem]:
    source_id = str(job.get("source_id") or "")
    storage = StorageManager(data_dir=data_dir)
    base_config = storage.load_config()
    config = Config.model_validate(
        build_catalog_source_config_data(
            store=store,
            workspace_id=str(job["workspace_id"]),
            user_id=str(job["user_id"]),
            source_id=source_id,
            subscription_id=job.get("subscription_id"),
            base_config=base_config,
        )
    )
    # Repair is deliberately acquisition-only. It must never analyze old or
    # newly observed content, regardless of the workspace's global AI setting.
    config = config.model_copy(
        update={"ai": config.ai.model_copy(update={"enabled": False})}
    )
    orchestrator = HorizonOrchestrator(config, storage)
    orchestrator.set_service_attempt_meter(
        UsageAttemptMeter(
            store,
            workspace_id=str(job["workspace_id"]),
            user_id=str(job["user_id"]),
            job_id=str(job["id"]),
        )
    )
    payload = job.get("payload_json") or {}
    result = asyncio.run(
        orchestrator.execute(
            force_hours=int(payload.get("hours") or 24 * 3650),
            enrich=False,
        )
    )
    if result.status == "failed":
        raise FeedRunFailed(result)
    return list(result.items)


def repair_existing_content(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    fetch_items: Callable[[dict[str, Any], str, ServiceStore], list[ContentItem]] | None = None,
) -> dict[str, Any]:
    """Refetch one free source and update only rows that already exist."""

    source_id = str(job.get("source_id") or "")
    if not source_id:
        raise ValueError("content_repair requires source_id")
    source = store.get_source(source_id)
    if source is None:
        raise LookupError("content repair source not found")
    if source_requires_paid_acquisition(source):
        raise PermissionError("paid source repair requires per-item authorization")

    rows = store.connect().execute(
        """
        SELECT article_id, body_completeness
        FROM user_content_items
        WHERE workspace_id = ? AND user_id = ? AND source_id = ?
        """,
        (job["workspace_id"], job["user_id"], source_id),
    ).fetchall()
    existing = {str(row["article_id"]): dict(row) for row in rows}
    fetched = (fetch_items or _fetch_source_items)(job, data_dir, store)
    matched = [item for item in fetched if item.id in existing]
    ignored_new = len(fetched) - len(matched)
    body_before = sum(1 for item in matched if existing[item.id]["body_completeness"] != "captured")
    media_before = int(
        store.connect().execute(
            """
            SELECT COUNT(*) FROM media_assets
            WHERE workspace_id = ? AND user_id = ? AND source_id = ?
              AND asset_kind = 'content_image' AND status = 'ready'
            """,
            (job["workspace_id"], job["user_id"], source_id),
        ).fetchone()[0]
    )
    if matched:
        MediaCacheService(store, data_dir=data_dir).cache_items(
            workspace_id=str(job["workspace_id"]),
            user_id=str(job["user_id"]),
            items=matched,
        )
        UserContentStore(store).upsert_captured_items(
            workspace_id=str(job["workspace_id"]),
            user_id=str(job["user_id"]),
            items=matched,
        )
        matched_ids = [item.id for item in matched]
        placeholders = ",".join("?" for _ in matched_ids)
        store.connect().execute(
            f"""
            UPDATE user_content_items SET unresolved_reason = ''
            WHERE workspace_id = ? AND user_id = ? AND article_id IN ({placeholders})
              AND body_completeness = 'captured'
            """,
            (job["workspace_id"], job["user_id"], *matched_ids),
        )
    media_after = int(
        store.connect().execute(
            """
            SELECT COUNT(*) FROM media_assets
            WHERE workspace_id = ? AND user_id = ? AND source_id = ?
              AND asset_kind = 'content_image' AND status = 'ready'
            """,
            (job["workspace_id"], job["user_id"], source_id),
        ).fetchone()[0]
    )
    captured_after = {
        str(row["article_id"])
        for row in store.connect().execute(
            """
            SELECT article_id FROM user_content_items
            WHERE workspace_id = ? AND user_id = ? AND source_id = ?
              AND body_completeness = 'captured'
            """,
            (job["workspace_id"], job["user_id"], source_id),
        ).fetchall()
    }
    unresolved = sorted(set(existing) - {item.id for item in matched})
    store.connect().commit()
    return {
        "ok": True,
        "job_type": "content_repair",
        "source_id": source_id,
        "fetched_items": len(fetched),
        "matched_items": len(matched),
        "ignored_new_items": ignored_new,
        "repaired_body": sum(
            1 for item in matched if existing[item.id]["body_completeness"] != "captured" and item.id in captured_after
        ),
        "repaired_media": max(media_after - media_before, 0),
        "unresolved": unresolved,
        "analysis_calls": 0,
        "snapshot_created": False,
    }
