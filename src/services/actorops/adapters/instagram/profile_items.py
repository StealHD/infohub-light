"""Instagram profile item Adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .....models import SourceType
from ...domain import RouteKey
from ...ports import ActorManifest, DiscoveryMapping, DiscoveryRevision, DiscoverySpec, FetchWindow, NativeFallbackResult, NormalizedBatch, TargetSpec
from .._discovery import deterministic_manifest
from .._manifest import build_input, validate_and_map
from .common import normalize_profile_target


class InstagramProfileItemsAdapter:
    route_key = RouteKey("instagram", "profile", "items")

    def normalize_target(self, source_config: Mapping[str, object]) -> TargetSpec:
        return normalize_profile_target(source_config.get("target"))

    def discovery_spec(self) -> DiscoverySpec:
        return DiscoverySpec(queries=("Instagram profile posts actor",))

    def map_discovery_manifest(self, revision: DiscoveryRevision) -> DiscoveryMapping:
        return deterministic_manifest(
            revision,
            input_keys=("username", "usernames", "profile", "handle", "startUrls"),
            identity_field="author_handle",
            identity_pointer_keys=("author", "authorUsername", "username", "ownerUsername", "handle"),
            identity_ref="target.handle",
            allowed_host="instagram.com",
            list_handle_input_keys=("usernames",),
            list_url_input_keys=("startUrls",),
        )

    def build_actor_input(self, target, manifest, window):
        return build_input(target, manifest, window)

    def validate_output(
        self, rows: Sequence[Mapping[str, object]], target: TargetSpec,
        manifest: ActorManifest, window: FetchWindow,
    ) -> NormalizedBatch:
        return validate_and_map(
            rows, target, manifest, window,
            platform="instagram", source_type=SourceType.INSTAGRAM,
        )

    async def fetch_native_fallback(self, target, window):
        return NativeFallbackResult.unsupported()
