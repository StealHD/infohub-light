"""X profile item Adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .....models import SourceType
from ...domain import RouteKey
from ...ports import (
    ActorManifest,
    DiscoveryMapping,
    DiscoveryRevision,
    DiscoverySpec,
    FetchWindow,
    NativeFallbackResult,
    NormalizedBatch,
    TargetSpec,
)
from .._discovery import deterministic_manifest
from .._manifest import build_input, validate_and_map
from .common import normalize_profile_target


class XProfileItemsAdapter:
    route_key = RouteKey("x", "profile", "items")

    def normalize_target(self, source_config: Mapping[str, object]) -> TargetSpec:
        return normalize_profile_target(source_config.get("target"))

    def discovery_spec(self) -> DiscoverySpec:
        return DiscoverySpec(queries=("X profile posts actor",))

    def map_discovery_manifest(self, revision: DiscoveryRevision) -> DiscoveryMapping:
        return deterministic_manifest(
            revision,
            input_keys=("profile", "username", "handle"),
            identity_field="author_handle",
            identity_pointer_keys=("author", "authorHandle", "username", "handle"),
            identity_ref="target.handle",
            allowed_host="x.com",
        )

    def build_actor_input(self, target, manifest, window):
        return build_input(target, manifest, window)

    def validate_output(
        self,
        rows: Sequence[Mapping[str, object]],
        target: TargetSpec,
        manifest: ActorManifest,
        window: FetchWindow,
    ) -> NormalizedBatch:
        return validate_and_map(
            rows, target, manifest, window,
            platform="x", source_type=SourceType.TWITTER,
        )

    async def fetch_native_fallback(self, target, window):
        return NativeFallbackResult.unsupported()
