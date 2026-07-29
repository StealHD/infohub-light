"""User-scoped feed snapshots and visible archive item mappings."""

from __future__ import annotations

import json
import hashlib
import os
import uuid
from copy import deepcopy
from dataclasses import dataclass, field
from datetime import datetime, timezone
from typing import Any, Mapping

from ..storage.service_store import ServiceStore
from .canonical_content import INTERNAL_SOURCE_NATIVE_TITLE_KEY
from .content_presentation import complete_content_presentation
from .media_cache import MediaCacheService
from .source_acquisition import (
    TargetSubscriptionProjection,
    target_subscription_projection,
)
from .user_content_store import UserContentStore, service_public_item


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id(prefix: str) -> str:
    return f"{prefix}_{uuid.uuid4().hex}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: str | None, fallback: Any) -> Any:
    if not value:
        return fallback
    try:
        return json.loads(value)
    except json.JSONDecodeError:
        return fallback


def _list(value: Any) -> list[Any]:
    return value if isinstance(value, list) else []


def _float_or_none(value: Any) -> float | None:
    if value is None or value == "":
        return None
    try:
        return float(value)
    except (TypeError, ValueError):
        return None


_VOLATILE_CONTENT_KEYS = {
    INTERNAL_SOURCE_NATIVE_TITLE_KEY,
    "acquisition_usage",
    "analysis_usage",
    "created_at",
    "date",
    "dismissed_at",
    "fetched_at",
    "generated_at",
    "is_later",
    "is_read",
    "is_saved",
    "issues",
    "job_id",
    "later_at",
    "read_at",
    "run_id",
    "run_status",
    "saved_at",
    "snapshot_id",
    "source_outcomes",
    "total_fetched",
    "updated_at",
    "user_state",
}
_COMPACT_COLLECTIONS = {
    "featured_items": "featured_item_ids",
    "daily_push_items": "daily_push_item_ids",
    "personal_items": "personal_item_ids",
}
_SAFE_PRESENTATION_CONTENT_FIELDS = {
    "content_kind",
    "excerpt",
    "excerpt_truncated",
    "title",
    "title_origin",
}
_SAFE_PRESENTATION_ENGAGEMENT_FIELDS = {
    "comments",
    "likes",
    "native_score",
    "reposts",
    "shares",
    "upvote_ratio",
}


def _safe_text(value: Any) -> str:
    return str(value) if isinstance(value, (str, int, float)) else ""


def _safe_presentation_section(
    presentation: Mapping[str, Any],
    name: str,
) -> dict[str, Any]:
    value = presentation.get(name)
    return value if isinstance(value, dict) else {}


def _safe_engagement(value: Mapping[str, Any]) -> dict[str, Any]:
    return {
        key: (
            item
            if item is None
            or (isinstance(item, (int, float)) and not isinstance(item, bool))
            else None
        )
        for key, item in value.items()
        if key in _SAFE_PRESENTATION_ENGAGEMENT_FIELDS
    }


def _reuse_projection(
    *,
    source: Mapping[str, Any],
    subscription: Mapping[str, Any],
) -> TargetSubscriptionProjection:
    return target_subscription_projection(
        {
            "source_id": source.get("id"),
            "subscription_id": subscription.get("id"),
            "source_key": source.get("source_key"),
            "source_display_name": source.get("display_name"),
            "catalog_source_type": source.get("type"),
            "source_priority": subscription.get("priority"),
            "analysis_mode": subscription.get("analysis_mode"),
            "override_channel": subscription.get("override_channel"),
            "default_channel": source.get("default_channel"),
            "override_topics": subscription.get("override_topics"),
            "default_topics": source.get("default_topics"),
            "personal_tags": subscription.get("personal_tags"),
        }
    )


def _neutral_reuse_item(
    *,
    donor: Mapping[str, Any],
    article_id: str,
    source_native_title: str,
    row: Mapping[str, Any],
    projection: TargetSubscriptionProjection,
    source_avatar_url: str,
    reused_at: str,
) -> dict[str, Any]:
    """Allowlist canonical donor content, then apply only target-owned fields."""

    donor_presentation = (
        donor.get("presentation")
        if isinstance(donor.get("presentation"), dict)
        else {}
    )
    donor_author = _safe_presentation_section(donor_presentation, "author")
    donor_timing = _safe_presentation_section(donor_presentation, "timing")
    donor_links = _safe_presentation_section(donor_presentation, "links")
    donor_content = _safe_presentation_section(donor_presentation, "content")
    donor_engagement = _safe_presentation_section(
        donor_presentation, "engagement"
    )

    title = source_native_title
    author = (
        _safe_text(donor.get("author"))
        or _safe_text(donor_author.get("name"))
    )
    url = (
        _safe_text(donor.get("url"))
        or _safe_text(donor_links.get("canonical_url"))
    )
    discussion_url = (
        _safe_text(donor.get("discussion_url"))
        or _safe_text(donor_links.get("source_url"))
        or url
    )
    published_at = (
        _safe_text(donor.get("published_at"))
        or _safe_text(donor_timing.get("published_at"))
    )
    fetched_at = (
        _safe_text(donor.get("fetched_at"))
        or _safe_text(donor_timing.get("fetched_at"))
    )
    source_type = (
        _safe_text(donor.get("source_type"))
        or str(projection.catalog_source_type or "")
    )
    source_name = str(
        projection.source_display_name
        or projection.catalog_source_type
        or source_type
    )
    channel = str(
        projection.channel
        or source_type
        or projection.catalog_source_type
        or "other"
    )
    topics = list(projection.topics)
    personal_tags = list(projection.personal_tags)
    analysis_status = (
        "personal_only"
        if projection.analysis_mode == "personal_only"
        else "fallback"
    )
    signal_type = (
        "personal_update"
        if projection.analysis_mode == "personal_only"
        else "other"
    )
    body_completeness = str(
        row["body_completeness"] or "excerpt_only"
    )
    body_is_captured = body_completeness == "captured"
    body_text = str(row["body_text"] or "") if body_is_captured else ""
    excerpt = (
        _safe_text(donor_content.get("excerpt"))
        or _safe_text(donor.get("excerpt"))
    )
    summary = (excerpt.strip() or body_text.strip() or title)[:200]
    retention_policy = str(donor.get("retention_policy") or "")
    if retention_policy not in {"latest_per_source", "time_window"}:
        retention_policy = "time_window"

    safe_content = {
        key: value
        for key, value in donor_content.items()
        if key in _SAFE_PRESENTATION_CONTENT_FIELDS
        and (
            isinstance(value, str)
            or (
                key == "excerpt_truncated"
                and isinstance(value, bool)
            )
        )
    }
    safe_content.update(
        {
            "title": title,
            "excerpt": excerpt,
            "body_text": body_text,
            "body_truncated": (
                bool(row["body_truncated"]) if body_is_captured else False
            ),
            "body_completeness": body_completeness,
            "unresolved_reason": (
                str(row["unresolved_reason"] or "")
                if body_is_captured
                else ""
            ),
        }
    )
    presentation_source = {
        "id": projection.source_id,
        "catalog_type": str(projection.catalog_source_type or source_type),
        "platform": source_type,
        "name": source_name,
    }
    if source_avatar_url:
        presentation_source["avatar_url"] = source_avatar_url

    item = {
        "id": article_id,
        "title": title,
        INTERNAL_SOURCE_NATIVE_TITLE_KEY: title,
        "source_type": source_type,
        "source": source_name,
        "author": author,
        "url": url,
        "discussion_url": discussion_url,
        "published_at": published_at,
        "fetched_at": fetched_at,
        "score": 0.0,
        "reason": "",
        "channel": channel,
        "topics": topics,
        "tags": list(topics),
        "category": channel,
        "signal_strength": "thin",
        "signal_type": signal_type,
        "entities": [],
        "is_featured": False,
        "show_on_featured_home": False,
        "summary_zh": summary,
        "action_suggestion": "",
        "image_url": "",
        "media_urls": [],
        "personal_tags": personal_tags,
        "interest_score": 8.0 if personal_tags else 0.0,
        "show_in_personal_feed": bool(
            personal_tags or projection.analysis_mode == "personal_only"
        ),
        "scoring_disabled": False,
        "source_id": projection.source_id,
        "source_ids": [projection.source_id],
        "subscription_id": str(projection.subscription_id or ""),
        "subscription_ids": (
            [str(projection.subscription_id)]
            if projection.subscription_id
            else []
        ),
        "source_key": str(projection.source_key or ""),
        "source_keys": (
            [str(projection.source_key)] if projection.source_key else []
        ),
        "source_priority": projection.source_priority,
        "analysis_mode": projection.analysis_mode,
        "retention_policy": retention_policy,
        "retention_policy_explicit": bool(
            donor.get("retention_policy_explicit")
        ),
        "ingested_at": reused_at,
        "presentation": {
            "version": 1,
            "source": presentation_source,
            "author": {
                "name": author,
                "kind": _safe_text(donor_author.get("kind")) or "unknown",
            },
            "timing": {
                "published_at": published_at,
                "fetched_at": fetched_at,
            },
            "links": {
                "canonical_url": url,
                "source_url": discussion_url,
            },
            "content": safe_content,
            "taxonomy": {
                "channel": channel,
                "configured_topics": topics,
                "inferred_topics": [],
                "topics": list(topics),
                "entities": [],
            },
            "engagement": _safe_engagement(donor_engagement),
            "analysis": {
                "status": analysis_status,
                "score": 0.0,
                "signal_strength": "thin",
                "signal_type": signal_type,
                "summary_zh": summary,
                "action_suggestion": "",
            },
            "media": {
                "images": [],
                "count": 0,
                "total_image_count": 0,
                "truncated": False,
            },
        },
    }
    item["presentation"] = complete_content_presentation(item)
    return item


def compact_feed_snapshots_enabled() -> bool:
    return os.getenv("HORIZON_COMPACT_FEED_SNAPSHOTS_ENABLED", "true").strip().lower() in {
        "1",
        "true",
        "yes",
        "on",
    }


def _stable_public_value(value: Any) -> Any:
    if isinstance(value, dict):
        return {
            str(key): _stable_public_value(item)
            for key, item in sorted(value.items(), key=lambda pair: str(pair[0]))
            if str(key) not in _VOLATILE_CONTENT_KEYS
        }
    if isinstance(value, list):
        return [_stable_public_value(item) for item in value]
    return value


def _item_ids(value: Any) -> list[str]:
    return [
        str(item["id"])
        for item in _list(value)
        if isinstance(item, dict) and item.get("id")
    ]


def feed_content_hash(payload: Mapping[str, Any], items: list[dict[str, Any]]) -> str:
    """Hash ordered visible content, excluding run timestamps and live state."""

    public_payload = {
        "items": _stable_public_value(items),
        **{
            id_key: _item_ids(payload.get(collection_key))
            for collection_key, id_key in _COMPACT_COLLECTIONS.items()
        },
    }
    raw = json.dumps(
        public_payload,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )
    return hashlib.sha256(raw.encode("utf-8")).hexdigest()


def _compact_payload(payload: dict[str, Any], items: list[dict[str, Any]]) -> dict[str, Any]:
    compact = deepcopy(payload)
    compact["item_ids"] = [str(item["id"]) for item in items]
    for collection_key, id_key in _COMPACT_COLLECTIONS.items():
        compact[id_key] = _item_ids(compact.get(collection_key))
        compact.pop(collection_key, None)
    compact.pop("items", None)
    compact.pop("today_items", None)
    return compact


@dataclass(frozen=True, slots=True)
class UserFeedSnapshotInput:
    """Validated service-owned input for a schema-v2 user snapshot."""

    run_id: str
    run_status: str
    generated_at: str
    items: tuple[dict[str, Any], ...]
    extra: Mapping[str, Any] = field(default_factory=dict)


class UserFeedStore:
    """Repository for per-user feed snapshots and visible archive boundaries."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    def save_snapshot(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str | None,
        payload: dict[str, Any],
        commit: bool = True,
    ) -> dict[str, Any]:
        normalized_payload = deepcopy(payload)
        items = _list(normalized_payload.get("items")) or _list(normalized_payload.get("today_items"))
        return self._insert_snapshot(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=job_id,
            schema_version=int(normalized_payload.get("schema_version") or 1),
            generated_at=str(normalized_payload.get("generated_at") or _now_iso()),
            items=items,
            payload=normalized_payload,
            commit=commit,
        )

    def reconcile_active_subscriptions(
        self,
        *,
        workspace_id: str,
        user_id: str,
        commit: bool = True,
    ) -> dict[str, Any] | None:
        """Remove inactive source provenance from the latest Feed without fetching."""
        latest = self.latest_snapshot(workspace_id=workspace_id, user_id=user_id)
        if latest is None:
            return None
        active_records = self.store.list_enabled_user_subscriptions_with_sources(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        active_subscription_ids = {
            str(record["subscription_id"])
            for record in active_records
            if record.get("subscription_id")
        }
        active_source_ids = {
            str(record["source_id"])
            for record in active_records
            if record.get("source_id")
        }
        active_source_keys_by_id = {
            str(record["source_id"]): str(record["source_key"])
            for record in active_records
            if record.get("source_id") and record.get("source_key")
        }
        active_source_keys = set(active_source_keys_by_id.values())
        reconciled: list[dict[str, Any]] = []
        for original in _list(latest["payload"].get("items")):
            if not isinstance(original, dict) or not original.get("id"):
                continue
            if not active_subscription_ids and not active_source_ids:
                continue
            item = deepcopy(original)
            subscription_ids = [
                str(value)
                for value in [
                    *(_list(item.get("subscription_ids"))),
                    item.get("subscription_id"),
                ]
                if value
            ]
            source_ids = [
                str(value)
                for value in [
                    *(_list(item.get("source_ids"))),
                    item.get("source_id"),
                ]
                if value
            ]
            source_keys = [
                str(value)
                for value in [
                    *(_list(item.get("source_keys"))),
                    item.get("source_key"),
                ]
                if value
            ]
            kept_subscriptions = list(
                dict.fromkeys(
                    value
                    for value in subscription_ids
                    if value in active_subscription_ids
                )
            )
            kept_sources = list(
                dict.fromkeys(
                    value for value in source_ids if value in active_source_ids
                )
            )
            kept_source_keys = list(
                dict.fromkeys(
                    [
                        active_source_keys_by_id[source_id]
                        for source_id in kept_sources
                        if source_id in active_source_keys_by_id
                    ]
                    + [
                        source_key
                        for source_key in source_keys
                        if source_key in active_source_keys
                    ]
                )
            )
            if subscription_ids and not kept_subscriptions:
                continue
            if not subscription_ids and source_ids and not kept_sources:
                continue
            if subscription_ids:
                item["subscription_ids"] = kept_subscriptions
                item["subscription_id"] = kept_subscriptions[0]
            if source_ids:
                item["source_ids"] = kept_sources
                item["source_id"] = kept_sources[0]
            if source_keys or kept_source_keys:
                item["source_keys"] = kept_source_keys
                if kept_source_keys:
                    item["source_key"] = kept_source_keys[0]
                else:
                    item.pop("source_key", None)
            reconciled.append(item)

        previous_items = _list(latest["payload"].get("items"))
        if reconciled == previous_items:
            return latest
        generated_at = _now_iso()
        payload = deepcopy(latest["payload"])
        payload.update(
            {
                "generated_at": generated_at,
                "run_id": f"lifecycle-reconcile:{generated_at}",
                "run_status": "succeeded",
                "items": reconciled,
                "today_items": list(reconciled),
                "today_total_items": len(reconciled),
                "item_count": len(reconciled),
            }
        )
        return self.save_snapshot(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=None,
            payload=payload,
            commit=commit,
        )

    def reuse_source_content(
        self,
        *,
        workspace_id: str,
        user_id: str,
        source_id: str,
        subscription_id: str,
        limit: int = 200,
        commit: bool = True,
    ) -> dict[str, Any]:
        """Seed a subscriber Feed from already indexed shared-source content."""

        source = self.store.get_source(source_id)
        subscription = self.store.get_subscription(subscription_id)
        user = self.store.get_user(user_id)
        if (
            source is None
            or subscription is None
            or user is None
            or source.get("workspace_id") != workspace_id
            or user.get("workspace_id") != workspace_id
            or subscription.get("user_id") != user_id
            or subscription.get("source_id") != source_id
            or not bool(subscription.get("enabled"))
            or not bool(source.get("enabled"))
            or (
                source.get("scope") == "private"
                and source.get("owner_user_id") != user_id
            )
        ):
            return {"reused_count": 0, "snapshot": None}
        projection = _reuse_projection(
            source=source,
            subscription=subscription,
        )
        avatar = MediaCacheService(
            self.store,
            data_dir=self.store.data_dir,
        ).avatar_for_source(
            workspace_id=workspace_id,
            source_id=source_id,
        )
        source_avatar_url = (
            f"/api/media/{avatar['id']}" if avatar is not None else ""
        )
        reused_at = _now_iso()
        rows = self.store.connect().execute(
            """
            SELECT item_json, source_native_title, body_text, body_truncated,
                   body_completeness, unresolved_reason, first_seen_at,
                   last_seen_at, article_id
            FROM user_content_items
            WHERE workspace_id = ? AND source_id = ?
            ORDER BY last_seen_at DESC, first_seen_at DESC, id DESC
            LIMIT ?
            """,
            (workspace_id, source_id, max(1, min(int(limit), 1000))),
        ).fetchall()
        reused: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for row in rows:
            article_id = str(row["article_id"])
            if article_id in seen_ids:
                continue
            source_native_title = str(
                row["source_native_title"] or ""
            ).strip()
            if not source_native_title:
                continue
            item = _json_loads(row["item_json"], {})
            if not isinstance(item, dict):
                continue
            seen_ids.add(article_id)
            reused.append(
                _neutral_reuse_item(
                    donor=item,
                    article_id=article_id,
                    source_native_title=source_native_title,
                    row=row,
                    projection=projection,
                    source_avatar_url=source_avatar_url,
                    reused_at=reused_at,
                )
            )
        if not reused:
            return {"reused_count": 0, "snapshot": None}

        latest = self.latest_snapshot(workspace_id=workspace_id, user_id=user_id)
        existing_items = _list((latest or {}).get("payload", {}).get("items"))
        merged_by_id: dict[str, dict[str, Any]] = {}
        order: list[str] = []
        for original in [*existing_items, *reused]:
            if not isinstance(original, dict) or not original.get("id"):
                continue
            article_id = str(original["id"])
            if article_id not in merged_by_id:
                merged_by_id[article_id] = deepcopy(original)
                order.append(article_id)
                continue
            current = merged_by_id[article_id]
            for plural, singular, incoming in (
                ("source_ids", "source_id", source_id),
                ("subscription_ids", "subscription_id", subscription_id),
            ):
                values = [
                    str(value)
                    for value in [*(_list(current.get(plural))), current.get(singular), incoming]
                    if value
                ]
                current[plural] = list(dict.fromkeys(values))
                current[singular] = current[plural][0]
        generated_at = _now_iso()
        payload = deepcopy((latest or {}).get("payload") or {})
        payload.update(
            {
                "schema_version": max(2, int(payload.get("schema_version") or 2)),
                "generated_at": generated_at,
                "run_id": f"source-reuse:{source_id}:{user_id}:{generated_at}",
                "run_status": "succeeded",
                "items": [merged_by_id[article_id] for article_id in order],
            }
        )
        snapshot = self.save_snapshot(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=None,
            payload=payload,
            commit=commit,
        )
        return {"reused_count": len(reused), "snapshot": snapshot}

    def save_run_snapshot(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str,
        snapshot: UserFeedSnapshotInput,
        commit: bool = True,
    ) -> dict[str, Any]:
        payload = deepcopy(dict(snapshot.extra))
        payload.update(
            {
                "schema_version": 2,
                "run_id": snapshot.run_id,
                "run_status": snapshot.run_status,
                "generated_at": snapshot.generated_at,
                "items": [deepcopy(item) for item in snapshot.items],
                "today_items": [deepcopy(item) for item in snapshot.items],
            }
        )
        return self._insert_snapshot(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=job_id,
            schema_version=2,
            generated_at=snapshot.generated_at,
            items=list(snapshot.items),
            payload=payload,
            commit=commit,
        )

    def _insert_snapshot(
        self,
        *,
        workspace_id: str,
        user_id: str,
        job_id: str | None,
        schema_version: int,
        generated_at: str,
        items: list[dict[str, Any]],
        payload: dict[str, Any],
        commit: bool = True,
    ) -> dict[str, Any]:
        existing = self._snapshot_by_job_id(job_id) if job_id else None
        deduped_items: list[dict[str, Any]] = []
        content_items: list[dict[str, Any]] = []
        seen_ids: set[str] = set()
        for item in items:
            if not isinstance(item, dict) or not item.get("id"):
                continue
            article_id = str(item["id"])
            if article_id in seen_ids:
                continue
            seen_ids.add(article_id)
            content_items.append(deepcopy(item))
            deduped_items.append(service_public_item(item))
        items = deduped_items
        now = _now_iso()
        snapshot_id = existing["id"] if existing is not None else _new_id("ufs")
        normalized_payload = deepcopy(payload)
        normalized_payload["scope"] = "user"
        normalized_payload["snapshot_id"] = snapshot_id
        normalized_payload["generated_at"] = generated_at
        normalized_payload["items"] = items
        normalized_payload["today_items"] = list(items)
        for collection_key in _COMPACT_COLLECTIONS:
            collection = normalized_payload.get(collection_key)
            if isinstance(collection, list):
                normalized_payload[collection_key] = [
                    service_public_item(item)
                    if isinstance(item, dict)
                    else item
                    for item in collection
                ]
        normalized_payload["today_total_items"] = len(items)
        normalized_payload["item_count"] = len(items)
        content_hash = feed_content_hash(normalized_payload, items)
        conn = self.store.connect()
        if existing is not None and existing["payload"].get("run_id") == normalized_payload.get("run_id"):
            native_title_updates = UserContentStore(
                self.store
            ).update_source_native_titles(
                workspace_id=workspace_id,
                user_id=user_id,
                items=content_items,
            )
            if commit and native_title_updates:
                conn.commit()
            return {**existing, "snapshot_created": False}
        latest = self.latest_snapshot(workspace_id=workspace_id, user_id=user_id)
        if latest is not None:
            latest_hash = latest.get("content_hash") or feed_content_hash(
                latest.get("payload") or {},
                _list((latest.get("payload") or {}).get("items")),
            )
            if latest_hash == content_hash and (existing is None or latest["id"] == existing["id"]):
                native_title_updates = UserContentStore(
                    self.store
                ).update_source_native_titles(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    items=content_items,
                )
                if commit and native_title_updates:
                    conn.commit()
                return {
                    **latest,
                    "content_hash": latest_hash,
                    "snapshot_created": False,
                }
        storage_version = (
            2
            if (
                int(schema_version) >= 2
                and compact_feed_snapshots_enabled()
                and not self.store.feed_storage_v3_migration_required()
            )
            else 1
        )
        stored_payload = (
            _compact_payload(normalized_payload, items)
            if storage_version == 2
            else normalized_payload
        )
        if existing is not None:
            if existing["workspace_id"] != workspace_id or existing["user_id"] != user_id:
                raise ValueError("job snapshot scope does not match the requested user")
            conn.execute(
                """
                UPDATE user_feed_snapshots
                SET schema_version = ?,
                    storage_version = ?,
                    content_hash = ?,
                    generated_at = ?,
                    item_count = ?,
                    payload_json = ?
                WHERE id = ?
                """,
                (
                    int(schema_version),
                    storage_version,
                    content_hash,
                    generated_at,
                    len(items),
                    _json_dumps(stored_payload),
                    snapshot_id,
                ),
            )
            conn.execute(
                "DELETE FROM user_feed_items WHERE snapshot_id = ?",
                (snapshot_id,),
            )
        else:
            conn.execute(
                """
                INSERT INTO user_feed_snapshots (
                    id, workspace_id, user_id, job_id, schema_version,
                    storage_version, content_hash, generated_at, item_count,
                    payload_json, created_at
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    snapshot_id,
                    workspace_id,
                    user_id,
                    job_id,
                    int(schema_version),
                    storage_version,
                    content_hash,
                    generated_at,
                    len(items),
                    _json_dumps(stored_payload),
                    now,
                ),
            )
        for position, item in enumerate(items):
            if not isinstance(item, dict) or not item.get("id"):
                continue
            topics = _list(item.get("topics")) or _list(item.get("tags"))
            conn.execute(
                """
                INSERT INTO user_feed_items (
                    id, workspace_id, user_id, snapshot_id, article_id,
                    source_id, subscription_id, position, source, channel,
                    topics_json, score, published_at, created_at
                    , item_json
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                """,
                (
                    _new_id("ufi"),
                    workspace_id,
                    user_id,
                    snapshot_id,
                    str(item["id"]),
                    str(item.get("source_id") or "") or None,
                    str(item.get("subscription_id") or "") or None,
                    position,
                    str(item.get("source") or item.get("source_type") or ""),
                    str(item.get("channel") or item.get("category") or ""),
                    _json_dumps(topics),
                    _float_or_none(item.get("score")),
                    item.get("published_at"),
                    now,
                    _json_dumps(item),
                ),
            )
        UserContentStore(self.store).upsert_items(
            workspace_id=workspace_id,
            user_id=user_id,
            items=content_items,
            seen_at=generated_at,
        )
        if commit:
            conn.commit()
        saved = self._snapshot_by_id(snapshot_id)
        if saved is not None:
            return {**saved, "snapshot_created": existing is None}
        return {
            "id": snapshot_id,
            "workspace_id": workspace_id,
            "user_id": user_id,
            "job_id": job_id,
            "generated_at": generated_at,
            "item_count": len(items),
            "payload": normalized_payload,
            "content_hash": content_hash,
            "storage_version": storage_version,
            "snapshot_created": existing is None,
        }

    def latest_snapshot(self, *, workspace_id: str, user_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            """
            SELECT * FROM user_feed_snapshots
            WHERE workspace_id = ? AND user_id = ?
            ORDER BY generated_at DESC, created_at DESC
            LIMIT 1
            """,
            (workspace_id, user_id),
        ).fetchone()
        return self._snapshot(row)

    def snapshot_history(
        self,
        *,
        workspace_id: str,
        user_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self.store.connect().execute(
            """
            SELECT id, generated_at, item_count, job_id
            FROM user_feed_snapshots
            WHERE workspace_id = ? AND user_id = ?
            ORDER BY generated_at DESC, created_at DESC
            LIMIT ?
            """,
            (workspace_id, user_id, max(1, int(limit))),
        ).fetchall()
        return [
            {
                "snapshot_id": row["id"],
                "generated_at": row["generated_at"],
                "item_count": row["item_count"],
                "job_id": row["job_id"],
            }
            for row in rows
        ]

    def recent_snapshots(
        self,
        *,
        workspace_id: str,
        user_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        rows = self.store.connect().execute(
            """
            SELECT *
            FROM user_feed_snapshots
            WHERE workspace_id = ? AND user_id = ?
            ORDER BY generated_at DESC, created_at DESC
            LIMIT ?
            """,
            (workspace_id, user_id, max(1, int(limit))),
        ).fetchall()
        return [snapshot for row in rows if (snapshot := self._snapshot(row)) is not None]

    def visible_article_ids(self, *, user_id: str) -> list[str]:
        rows = self.store.connect().execute(
            """
            SELECT DISTINCT article_id
            FROM user_feed_items
            WHERE user_id = ?
            ORDER BY article_id
            """,
            (user_id,),
        ).fetchall()
        return [str(row["article_id"]) for row in rows]

    def _snapshot_by_id(self, snapshot_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            "SELECT * FROM user_feed_snapshots WHERE id = ?",
            (snapshot_id,),
        ).fetchone()
        return self._snapshot(row)

    def _snapshot_by_job_id(self, job_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            "SELECT * FROM user_feed_snapshots WHERE job_id = ? ORDER BY created_at DESC LIMIT 1",
            (job_id,),
        ).fetchone()
        return self._snapshot(row)

    def _snapshot(self, row: Any) -> dict[str, Any] | None:
        if row is None:
            return None
        data = dict(row)
        payload = _json_loads(data.pop("payload_json", None), {})
        if int(data.get("storage_version") or 1) >= 2:
            item_rows = self.store.connect().execute(
                """
                SELECT item_json FROM user_feed_items
                WHERE snapshot_id = ?
                ORDER BY position, id
                """,
                (data["id"],),
            ).fetchall()
            items = [
                item
                for item_row in item_rows
                if isinstance(
                    (item := _json_loads(item_row["item_json"], None)),
                    dict,
                )
            ]
            payload["items"] = items
            payload["today_items"] = list(items)
            payload["today_total_items"] = len(items)
            by_id = {str(item.get("id") or ""): item for item in items}
            for collection_key, id_key in _COMPACT_COLLECTIONS.items():
                payload[collection_key] = [
                    by_id[item_id]
                    for item_id in _list(payload.get(id_key))
                    if item_id in by_id
                ]
        data["payload"] = payload
        return data
