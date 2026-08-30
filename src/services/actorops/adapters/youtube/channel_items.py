"""YouTube channel item Adapter with injectable free native fallback."""

from __future__ import annotations

import hashlib
import json
from collections.abc import Awaitable, Callable, Mapping, Sequence

from .....models import SourceType
from ...domain import RouteKey
from ...ports import ActorManifest, DiscoveryMapping, DiscoveryRevision, DiscoverySpec, FetchWindow, NativeFallbackResult, NormalizedBatch, TargetSpec
from ...discovery_virtual_fields import YOUTUBE_TARGET_URL_POINTER
from ...input_plan import create_input_plan
from ...youtube_capabilities import apply_youtube_input_capabilities
from .._discovery import deterministic_input_plan, deterministic_manifest
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
        return normalize_channel_target(
            source_config.get("target") or source_config.get("url")
        )

    def discovery_spec(self) -> DiscoverySpec:
        return DiscoverySpec(queries=(
            "youtube channel videos scraper",
            "youtube channel shorts scraper",
            "youtube channel uploads actor",
            "youtube videos playlists scraper",
        ))

    def map_discovery_manifest(self, revision: DiscoveryRevision) -> DiscoveryMapping:
        mapping = deterministic_manifest(
            revision,
            input_keys=(
                "channelId", "channelIds", "channelUrls", "channel_urls",
                "channelUrl", "channel_url", "channelInputs", "channels",
                "channelUsername", "channelHandle", "startUrls", "channel",
                "url",
            ),
            identity_field="source_native_id",
            identity_pointer_keys=(),
            identity_ref="target.native_id",
            allowed_host="youtube.com",
            list_url_input_keys=(
                "channelUrls", "channel_urls", "channelInputs", "channels",
                "startUrls",
            ),
            handle_input_keys=("channelUsername", "channelHandle"),
            url_input_keys=("channelUrl", "channel_url"),
            max_items_input_keys=(
                "maxResults", "maxItems", "maxItemsPerUrl", "limit",
                "maxVideosPerChannel", "maxPage", "max_shorts",
            ),
            thumbnail_pointer_keys=(
                "thumbnailUrl", "thumbnail", "Thumbnail URL",
            ),
            identity_virtual_pointer=YOUTUBE_TARGET_URL_POINTER,
            virtual_identity_field="source_url",
            virtual_identity_ref="target.canonical_url",
            native_id_url_fallback=True,
        )
        if not mapping.manifest_json:
            return mapping
        value = json.loads(mapping.manifest_json)
        value["input"] = apply_youtube_input_capabilities(
            value["input"], revision.input_schema
        )
        return DiscoveryMapping(json.dumps(value, ensure_ascii=False, sort_keys=True))

    def map_discovery_input_plan(
        self, revision: DiscoveryRevision
    ) -> tuple[str | None, str | None]:
        plan_json, error_code = deterministic_input_plan(
            revision,
            input_keys=(
                "channelId", "channelIds", "channelUrls", "channel_urls",
                "channelUrl", "channel_url", "channelInputs", "channels",
                "channelUsername", "channelHandle", "startUrls", "channel",
                "url",
            ),
            identity_ref="target.native_id",
            list_url_input_keys=(
                "channelUrls", "channel_urls", "channelInputs", "channels",
                "startUrls",
            ),
            handle_input_keys=("channelUsername", "channelHandle"),
            url_input_keys=("channelUrl", "channel_url"),
            max_items_input_keys=(
                "maxResults", "maxItems", "maxItemsPerUrl", "limit",
                "maxVideosPerChannel", "maxPage", "max_shorts",
            ),
        )
        if not plan_json:
            return plan_json, error_code
        value = json.loads(plan_json)
        value["input"] = apply_youtube_input_capabilities(
            value["input"], revision.input_schema
        )
        return create_input_plan(revision, value["input"])

    def build_actor_input(self, target, manifest, window):
        return build_input(target, manifest, window)

    def validate_output(
        self, rows: Sequence[Mapping[str, object]], target: TargetSpec,
        manifest: ActorManifest, window: FetchWindow,
    ) -> NormalizedBatch:
        batch = validate_and_map(
            self.prepare_output_rows(rows, target), target, manifest, window,
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

    def prepare_output_rows(
        self,
        rows: Sequence[Mapping[str, object]],
        target: TargetSpec,
        manifest: ActorManifest | None = None,
    ) -> tuple[Mapping[str, object], ...]:
        """Inject only the already-normalized channel identity for validation."""

        field = YOUTUBE_TARGET_URL_POINTER.removeprefix("/")
        return tuple({**dict(row), field: target.canonical_url} for row in rows)

    async def fetch_native_fallback(self, target, window):
        if self.native_fetcher is None:
            return NativeFallbackResult.unsupported()
        return await self.native_fetcher(target, window)
