"""ActorOps adapter for public Bilibili uploads belonging to one UP UID."""

from __future__ import annotations

from dataclasses import replace

from .....models import SourceType
from ...domain import RouteKey
from ...ports import DiscoverySpec, NativeFallbackResult
from .._discovery import deterministic_input_plan
from .._manifest import build_input, validate_and_map
from .common import normalize_profile_target, rss_article_id
from .video_identity import rss_video_url
from .discovery import input_options, map_manifest, refine_mapping
from .owned_rows import owned_video_rows
from ....bilibili_source_identity import bilibili_public_target


class BilibiliProfileItemsAdapter:
    route_key = RouteKey("bilibili", "profile", "items")

    def normalize_target(self, source_config):
        raw = source_config.get("target")
        return normalize_profile_target(raw if raw is not None else bilibili_public_target(source_config))

    def discovery_spec(self):
        return DiscoverySpec(queries=(
            "bilibili creator videos scraper", "bilibili user uploads scraper",
            "bilibili UP videos API", "bilibili profile videos actor",
        ))

    def map_discovery_manifest(self, revision):
        return map_manifest(revision)

    def map_discovery_input_plan(self, revision):
        return deterministic_input_plan(revision, **input_options(revision))

    def refine_discovery_mapping(self, revision, mapping):
        return refine_mapping(revision, mapping)

    def build_actor_input(self, target, manifest, window):
        return build_input(target, manifest, window)

    def validate_output(self, rows, target, manifest, window):
        batch = validate_and_map(
            owned_video_rows(rows, target, manifest), target, manifest, window,
            platform="bilibili", source_type=SourceType.RSS,
        )
        for item in batch.items:
            item.url = rss_video_url(item.url, item.published_at)
            item.id = rss_article_id(str(target.native_id), item.url)
            item.metadata.update({"catalog_type": "rss", "content_type": "video"})
        items = tuple(sorted(batch.items, key=lambda item: (item.published_at, item.id), reverse=True))
        return replace(batch, items=items)

    async def fetch_native_fallback(self, target, window):
        return NativeFallbackResult.unsupported()
