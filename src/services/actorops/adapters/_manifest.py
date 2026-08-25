"""Restricted Manifest bridge shared by stateless platform adapters."""

from __future__ import annotations

import hashlib
from collections.abc import Mapping, Sequence

from ....models import ContentItem, SourceType
from ...apify_actor_manifest import (
    ActorRuntime,
    ActorTarget,
    MappedActorItem,
    map_actor_output,
    render_actor_input,
)
from ..ports import ActorManifest, FetchWindow, NormalizedBatch, TargetSpec


def build_input(
    target: TargetSpec, manifest: ActorManifest, window: FetchWindow
) -> Mapping[str, object]:
    return render_actor_input(
        manifest.manifest_json,
        ActorTarget(
            canonical_url=target.canonical_url,
            native_id=target.native_id,
            handle=target.handle,
        ),
        _runtime(window),
    )


def validate_and_map(
    rows: Sequence[Mapping[str, object]],
    target: TargetSpec,
    manifest: ActorManifest,
    window: FetchWindow,
    *,
    platform: str,
    source_type: SourceType,
) -> NormalizedBatch:
    mapped = map_actor_output(
        manifest.manifest_json,
        rows,
        ActorTarget(
            canonical_url=target.canonical_url,
            native_id=target.native_id,
            handle=target.handle,
        ),
        _runtime(window),
    )
    items = tuple(
        _content_item(
            item,
            platform=platform,
            source_type=source_type,
            target=target,
        )
        for item in mapped.items
    )
    return NormalizedBatch(
        items=items,
        semantic_outcome=mapped.semantic_outcome,
        latest_published_at=mapped.latest_published_at,
        latest_item_id=mapped.latest_native_id,
        source_avatar_url=mapped.source_avatar_url,
    )


def _runtime(window: FetchWindow) -> ActorRuntime:
    return ActorRuntime(
        max_items=window.max_items,
        since_iso=window.since.isoformat(),
        until_iso=window.until.isoformat() if window.until else None,
    )


def _content_item(
    item: MappedActorItem,
    *,
    platform: str,
    source_type: SourceType,
    target: TargetSpec,
) -> ContentItem:
    identity = target.native_id or target.handle or target.canonical_url
    stable_id = hashlib.sha256(
        f"{platform}\x1f{identity}\x1f{item.native_id}".encode("utf-8")
    ).hexdigest()[:24]
    engagement = {
        key: value
        for key, value in {
            "likes": item.like_count,
            "comments": item.comment_count,
            "reposts": item.repost_count,
            "shares": item.share_count,
            "views": item.view_count,
        }.items()
        if value is not None
    }
    return ContentItem(
        id=f"actor:{platform}:{stable_id}",
        source_type=source_type,
        title=str(item.title or item.text or item.author or platform),
        url=item.url,
        content=str(item.text or item.title or ""),
        author=item.author or item.author_handle,
        published_at=item.published_at,
        metadata={
            "platform": platform,
            "native_id": item.native_id,
            **({"engagement": engagement} if engagement else {}),
            **({"author_avatar_url": item.author_avatar_url} if item.author_avatar_url else {}),
            **({"image_url": item.thumbnail_url} if item.thumbnail_url else {}),
        },
    )
