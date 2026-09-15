"""Explicit, previewed media-only repair of existing user-owned Instagram posts."""

from __future__ import annotations

import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from types import SimpleNamespace

from ..models import ContentItem, SourceType
from ..apify_actor_identity import source_target_fingerprint, source_config_target
from .apify_actor_manifest import actor_manifest_hash
from .actorops.adapter_rows import prepare_adapter_rows
from .actorops.adapters.instagram.profile_items import InstagramProfileItemsAdapter
from .actorops.attempt_recovery import frozen_window, request_fingerprint
from .actorops.known_dataset_reader import KnownDatasetError, read_known_dataset
from .actorops.ports import ActorManifest
from .media_cache import MediaCacheService, PostCommitMediaCleanup
from .operation_log import safe_emit_operation_event
from .instagram_media_saved import saved_media_urls


class MediaRepairError(ValueError):
    pass


@dataclass
class MediaRepairPlan:
    workspace_id: str
    user_id: str
    source_id: str
    article_id: str
    fingerprint: str
    state_fingerprint: str
    item: ContentItem | None
    reason: str

    def public(self):
        metadata = self.item.metadata if self.item else {}
        return {"article_id": self.article_id, "reason": self.reason,
                "preview": self.fingerprint,
                "available_images": len(metadata.get("media_urls", [])),
                "total_images": metadata.get("media_image_count", 0),
                "actor_posts": 0, "reservations": 0}


def _state(store, workspace_id, user_id, source_id, article_id):
    connection = store.connect()
    source = connection.execute(
        "SELECT * FROM source_catalog WHERE workspace_id=? AND id=?",
        (workspace_id, source_id),
    ).fetchone()
    record = connection.execute(
        """SELECT * FROM user_content_items WHERE workspace_id=? AND user_id=?
           AND source_id=? AND article_id=? AND archived_at IS NULL""",
        (workspace_id, user_id, source_id, article_id),
    ).fetchone()
    binding = connection.execute(
        "SELECT * FROM actor_source_bindings_v2 WHERE workspace_id=? AND source_id=?",
        (workspace_id, source_id),
    ).fetchone()
    if source is None or record is None or binding is None:
        raise MediaRepairError("instagram_media_item_unavailable")
    config = json.loads(source["config_json"])
    if source["type"] != "apify_social" or config.get("platform") != "instagram":
        raise MediaRepairError("instagram_media_source_invalid")
    if source_target_fingerprint(workspace_id, binding["route_id"],
            source_config_target(config, platform="instagram"), platform="instagram") != binding["target_fingerprint"]:
        raise MediaRepairError("instagram_media_binding_changed")
    attempts = connection.execute(
        """SELECT a.*, c.manifest_json, c.manifest_hash, c.build_id, c.build_number, c.actor_id
           FROM actor_attempts_v2 a JOIN actor_candidates_v2 c
             ON c.workspace_id=a.workspace_id AND c.candidate_id=a.candidate_id
           WHERE a.workspace_id=? AND a.source_id=? AND a.kind='fetch'
             AND a.status='succeeded' AND a.result_state='validated' AND a.cost_final=1
             AND a.binding_version=? AND a.target_fingerprint=? AND a.route_id=?
           ORDER BY a.created_at DESC, a.attempt_id LIMIT 5""",
        (workspace_id, source_id, binding["binding_version"],
         binding["target_fingerprint"], binding["route_id"]),
    ).fetchall()
    state = {"source": dict(source), "record": dict(record), "binding": dict(binding),
             "attempts": [dict(row) for row in attempts]}
    fingerprint = hashlib.sha256(json.dumps(state, sort_keys=True).encode()).hexdigest()
    return state, fingerprint


def _dataset_item(store, state, article_id, reader):
    adapter = InstagramProfileItemsAdapter()
    target = adapter.normalize_target(json.loads(state["source"]["config_json"]))
    stored = json.loads(state["record"]["item_json"])
    reason = "instagram_dataset_identity_unproven"
    for attempt in state["attempts"]:
        manifest = ActorManifest(attempt["actor_id"], attempt["build_id"],
                                 attempt["build_number"], attempt["manifest_json"],
                                 attempt["manifest_hash"])
        try:
            frozen = request_fingerprint(target_fingerprint=attempt["target_fingerprint"],
                candidate=SimpleNamespace(**attempt), route_cap_usd=attempt["reserved_usd"],
                window=frozen_window(attempt))
            if (frozen != attempt["request_fingerprint"]
                    or actor_manifest_hash(attempt["manifest_json"]) != attempt["manifest_hash"]):
                reason = "instagram_dataset_request_changed"
                continue
            rows = reader(store, attempt)
            batch = adapter.validate_output(prepare_adapter_rows(adapter, rows, target, manifest),
                                            target, manifest, frozen_window(attempt))
        except KnownDatasetError as error:
            reason = str(error)
            continue
        except Exception:
            reason = "instagram_dataset_validation_failed"
            continue
        matches = [item for item in batch.items if item.id == article_id or (
            str(item.url).rstrip("/") == str(stored.get("url", "")).rstrip("/")
            and item.url
        )]
        if len(matches) != 1:
            continue
        item = matches[0].model_copy(update={"id": article_id})
        if item.metadata.get("media_urls"):
            return item, "instagram_media_ready"
        reason = "instagram_media_missing"
    return None, reason


def preview_media_repair(store, *, workspace_id, user_id, source_id, article_id,
                         reader=read_known_dataset):
    state, fingerprint = _state(store, workspace_id, user_id, source_id, article_id)
    stored = json.loads(state["record"]["item_json"])
    # Remote addresses, when present in old private rows, avoid a Dataset GET.
    urls = saved_media_urls(store, state)
    if urls:
        item = ContentItem(id=article_id, source_type=SourceType.INSTAGRAM,
                           published_at=stored.get("published_at") or state["record"]["published_at"],
                           title=stored.get("title", "Instagram"), url=stored.get("url", ""),
                           metadata={"media_urls": list(dict.fromkeys(urls))[:6],
                                     "media_image_count": max(len(urls), int(stored.get("total_image_count") or 0))})
        reason = "instagram_media_ready"
        if len(urls) < min(item.metadata["media_image_count"], 6):
            refreshed, refresh_reason = _dataset_item(store, state, article_id, reader)
            if refreshed is not None:
                item = refreshed
            else:
                reason = refresh_reason
    else:
        item, reason = _dataset_item(store, state, article_id, reader)
    if item:
        item.metadata.update(source_id=source_id, subscription_id=state["record"]["subscription_id"])
    preview = hashlib.sha256(json.dumps({"state": fingerprint,
        "media": item.metadata if item else None}, sort_keys=True).encode()).hexdigest()
    return MediaRepairPlan(workspace_id, user_id, source_id, article_id,
                           preview, fingerprint, item, reason)


def apply_media_repair(store, plan, *, expected_preview, fetch_image=None):
    if expected_preview != plan.fingerprint:
        raise MediaRepairError("instagram_media_preview_changed")
    if plan.item is None:
        return {**plan.public(), "status": "skipped"}
    connection = store.connect()
    if connection.in_transaction:
        raise MediaRepairError("instagram_media_transaction_busy")
    cleanup = PostCommitMediaCleanup()
    try:
        connection.execute("BEGIN IMMEDIATE")
        state, current = _state(store, plan.workspace_id, plan.user_id, plan.source_id, plan.article_id)
        if current != plan.state_fingerprint:
            raise MediaRepairError("instagram_media_preview_changed")
        item = plan.item.model_copy(deep=True)
        MediaCacheService(store, data_dir=store.data_dir, fetch_image=fetch_image).cache_items(
            workspace_id=plan.workspace_id, user_id=plan.user_id, items=[item],
            commit=False, media_cleanup=cleanup,
        )
        from .instagram_media_repair_projection import repaired_projection
        original = json.loads(state["record"]["item_json"])
        updated = repaired_projection(original, item.metadata)
        changed = updated != original
        if changed:
            connection.execute(
                "UPDATE user_content_items SET item_json=?, updated_at=? WHERE id=?",
                (json.dumps(updated, ensure_ascii=False), datetime.now(timezone.utc).isoformat(),
                 state["record"]["id"]),
            )
        connection.commit()
        cleanup.run()
    except Exception:
        connection.rollback()
        cleanup.discard()
        raise
    count = len(item.metadata.get("media_urls", []))
    expected_count = min(int(plan.item.metadata.get("media_image_count") or 0), 6)
    status = "partial" if count < max(expected_count, len(plan.item.metadata.get("media_urls", []))) else "succeeded"
    safe_emit_operation_event(category="storage", action="instagram_media_repair", outcome=status,
                              workspace_id=plan.workspace_id, source_id=plan.source_id,
                              subject_user_id=plan.user_id,
                              error_code="instagram_media_download_partial" if status == "partial" else None,
                              counts={"cached_images": count, "updated_items": int(changed)})
    return {**plan.public(), "status": status, "cached_images": count, "updated": changed}
