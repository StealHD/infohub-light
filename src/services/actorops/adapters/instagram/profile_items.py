"""Instagram profile item Adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .....models import SourceType
from ...domain import RouteKey
from ...ports import ActorManifest, DiscoveryMapping, DiscoveryRevision, DiscoverySpec, FetchWindow, NativeFallbackResult, NormalizedBatch, TargetSpec
from .._discovery import deterministic_input_plan, deterministic_manifest
from .._manifest import build_input, validate_and_map
from .common import normalize_profile_target
from .profile_rows import prepare_profile_rows


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
            input_keys=(
                "username", "usernames", "instagramUsernames", "profiles",
                "profile", "handle", "profileUrls", "startUrls",
            ),
            identity_field="author_handle",
            identity_pointer_keys=(
                "author", "authorUsername", "author_username", "username",
                "ownerUsername", "owner_username", "user.username", "handle",
            ),
            identity_ref="target.handle",
            allowed_host="instagram.com",
            list_handle_input_keys=(
                "usernames", "instagramUsernames", "profiles",
            ),
            list_url_input_keys=("profileUrls", "startUrls"),
            max_items_input_keys=(
                "maxItems", "maxPosts", "postsPerProfile",
                "resultsPerProfile", "limit",
            ),
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
            input_keys=(
                "username", "usernames", "instagramUsernames", "profiles",
                "profile", "handle", "profileUrls", "startUrls",
            ),
            identity_ref="target.handle",
            list_handle_input_keys=(
                "usernames", "instagramUsernames", "profiles",
            ),
            list_url_input_keys=("profileUrls", "startUrls"),
            max_items_input_keys=(
                "maxItems", "maxPosts", "postsPerProfile",
                "resultsPerProfile", "limit",
            ),
        )

    def build_actor_input(self, target, manifest, window):
        return build_input(target, manifest, window)

    def validate_output(
        self, rows: Sequence[Mapping[str, object]], target: TargetSpec,
        manifest: ActorManifest, window: FetchWindow,
    ) -> NormalizedBatch:
        return validate_and_map(
            self.prepare_output_rows(rows, target, manifest),
            target, manifest, window,
            platform="instagram", source_type=SourceType.INSTAGRAM,
        )

    def prepare_output_rows(
        self, rows: Sequence[Mapping[str, object]], target: TargetSpec,
        manifest: ActorManifest,
    ) -> Sequence[Mapping[str, object]]:
        return prepare_profile_rows(rows, target, manifest)

    async def fetch_native_fallback(self, target, window):
        return NativeFallbackResult.unsupported()
