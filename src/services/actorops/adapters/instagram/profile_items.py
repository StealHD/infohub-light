"""Instagram profile item Adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from ...domain import RouteKey
from ...ports import ActorManifest, DiscoveryMapping, DiscoveryRevision, DiscoverySpec, FetchWindow, NativeFallbackResult, NormalizedBatch, TargetSpec
from .._discovery import deterministic_input_plan, deterministic_manifest
from .._manifest import build_input
from ....apify_actor_manifest import parse_actor_manifest
from .common import normalize_profile_target
from .discovery_inputs import input_options, refine_mapping
from .profile_rows import prepare_profile_rows
from .media_enrichment import enrich_instagram_media
from .legacy_contributors import legacy_contributors_manifest
from .profile_batch import validate_profile_batch


class InstagramProfileItemsAdapter:
    route_key = RouteKey("instagram", "profile", "items")

    def normalize_target(self, source_config: Mapping[str, object]) -> TargetSpec:
        return normalize_profile_target(source_config.get("target"))

    def discovery_spec(self) -> DiscoverySpec:
        return DiscoverySpec(queries=(
            "instagram profile posts scraper",
            "instagram posts reels scraper",
            "instagram profile feed actor",
            "instagram user media scraper",
        ))

    def map_discovery_manifest(self, revision: DiscoveryRevision) -> DiscoveryMapping:
        return deterministic_manifest(
            revision,
            **input_options(revision),
            identity_field="author_handle",
            identity_pointer_keys=(
                "author", "authorUsername", "author_username", "username",
                "ownerUsername", "owner_username", "user.username", "handle",
            ),
            allowed_host="instagram.com",
            avatar_pointer_keys=(
                "profilePicUrlHD",
                "profilePicUrl",
                "profilePicture",
                "profile_pic_url",
                "authorProfilePicUrl",
                "ownerProfilePicUrl",
            ),
            thumbnail_pointer_keys=(
                "displayUrl", "imageUrl", "thumbnailUrl", "image_url",
            ),
            native_id_url_fallback=True,
        )

    def map_discovery_input_plan(
        self, revision: DiscoveryRevision
    ) -> tuple[str | None, str | None]:
        return deterministic_input_plan(
            revision,
            **input_options(revision),
        )

    def refine_discovery_mapping(self, revision, mapping):
        return refine_mapping(revision, mapping)

    def build_actor_input(self, target, manifest, window):
        return build_input(target, manifest, window)

    def validate_output(
        self, rows: Sequence[Mapping[str, object]], target: TargetSpec,
        manifest: ActorManifest, window: FetchWindow,
    ) -> NormalizedBatch:
        media = getattr(parse_actor_manifest(manifest.manifest_json).structures, "media", None)
        manifest = legacy_contributors_manifest(rows, manifest)
        prepared = self.prepare_output_rows(rows, target, manifest)
        prepared, batch = validate_profile_batch(prepared, target, manifest, window)
        if media:
            return batch
        return enrich_instagram_media(batch, prepared, target, manifest, window)

    def prepare_output_rows(
        self, rows: Sequence[Mapping[str, object]], target: TargetSpec,
        manifest: ActorManifest,
    ) -> Sequence[Mapping[str, object]]:
        effective = legacy_contributors_manifest(rows, manifest)
        if parse_actor_manifest(effective.manifest_json).structures is not None:
            return rows
        return prepare_profile_rows(rows, target, manifest)

    async def fetch_native_fallback(self, target, window):
        return NativeFallbackResult.unsupported()
