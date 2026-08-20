"""YouTube channel item Adapter with injectable free native fallback."""

from __future__ import annotations

import hashlib
from collections.abc import Awaitable, Callable, Mapping, Sequence

from .....models import SourceType
from ...domain import RouteKey
from ...ports import ActorManifest, DiscoveryMapping, DiscoveryRevision, DiscoverySpec, FetchWindow, NativeFallbackResult, NormalizedBatch, TargetSpec
from .._discovery import deterministic_manifest
from .._manifest import build_input, validate_and_map
from .common import normalize_channel_target


class YouTubeChannelItemsAdapter:
    route_key = RouteKey("youtube", "channel", "items")

    def __init__(
        self,
        *,
        native_fetcher: Callable[
            [TargetSpec, FetchWindow], Awaitable[NativeFallbackResult]
        ] | None = None,
    ) -> None:
        self.native_fetcher = native_fetcher

    def normalize_target(self, source_config: Mapping[str, object]) -> TargetSpec:
        return normalize_channel_target(source_config.get("target"))

    def discovery_spec(self) -> DiscoverySpec:
        return DiscoverySpec(queries=("YouTube channel videos actor",))

    def map_discovery_manifest(self, revision: DiscoveryRevision) -> DiscoveryMapping:
        return deterministic_manifest(
            revision,
            input_keys=("channelUrl", "channel", "url"),
            identity_field="source_native_id",
            identity_pointer_keys=("channelId", "sourceId", "channel_id"),
            identity_ref="target.native_id",
            allowed_host="youtube.com",
        )

    def build_actor_input(self, target, manifest, window):
        return build_input(target, manifest, window)

    def validate_output(
        self, rows: Sequence[Mapping[str, object]], target: TargetSpec,
        manifest: ActorManifest, window: FetchWindow,
    ) -> NormalizedBatch:
        batch = validate_and_map(
            rows, target, manifest, window,
            platform="youtube", source_type=SourceType.RSS,
        )
        feed_url = target.native_url or target.canonical_url
        feed_id = feed_url.split("//", 1)[-1].replace("/", "_")
        for item in batch.items:
            native_id = str(item.metadata.get("native_id") or "")
            entry_hash = hashlib.sha256(
                f"yt:video:{native_id}".encode("utf-8")
            ).hexdigest()[:16]
            item.id = f"rss:{feed_id}:{entry_hash}"
            item.metadata.update(
                {"catalog_type": "rss", "acquisition_origin": "apify_actor"}
            )
        return batch

    async def fetch_native_fallback(self, target, window):
        if self.native_fetcher is None:
            return NativeFallbackResult.unsupported()
        return await self.native_fetcher(target, window)
