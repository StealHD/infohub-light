"""X profile item Adapter."""

from __future__ import annotations

from collections.abc import Mapping, Sequence

from .....models import SourceType
from ....apify_actor_manifest import ActorManifestError
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
from .._discovery import deterministic_input_plan, deterministic_manifest
from .._manifest import validate_and_map
from .common import normalize_profile_target
from .post_relationship import exclude_x_reply_rows
from .profile_mapping import build_profile_input, derive_profile_rows


class XProfileItemsAdapter:
    route_key = RouteKey("x", "profile", "items")

    def normalize_target(self, source_config: Mapping[str, object]) -> TargetSpec:
        return normalize_profile_target(source_config.get("target"))

    def discovery_spec(self) -> DiscoverySpec:
        return DiscoverySpec(queries=(
            "twitter scraper",
            "x tweet scraper",
            "twitter profile posts",
            "x advanced search",
        ))

    def map_discovery_manifest(self, revision: DiscoveryRevision) -> DiscoveryMapping:
        return deterministic_manifest(
            revision,
            input_keys=(
                "handles", "profileUrls", "startUrls", "profileUrl",
                "profile", "username", "handle", "from",
            ),
            identity_field="author_handle",
            identity_pointer_keys=(
                "author", "authorHandle", "username", "userName",
                "profileHandle", "handle",
            ),
            identity_ref="target.handle",
            allowed_host="x.com",
            list_handle_input_keys=("handles",),
            list_url_input_keys=("profileUrls", "startUrls"),
            url_input_keys=("profileUrl",),
            max_items_input_keys=(
                "maxItems", "maxPosts", "numberOfTweets", "resultsLimit",
                "maxResults", "maxPostsPerProfile", "maxNbItemsToScrape",
            ),
            identity_container_keys=("author",),
            avatar_pointer_keys=(
                "user_profile_image_url_https", "user_profile_image_url",
                "profilePictureFull", "profilePicture", "avatarUrl",
            ),
            thumbnail_pointer_keys=(
                "thumbnailUrl", "imageUrl", "mediaUrl", "photoUrl",
            ),
            identity_url_fallback=True,
        )

    def map_discovery_input_plan(
        self, revision: DiscoveryRevision
    ) -> tuple[str | None, str | None]:
        return deterministic_input_plan(
            revision,
            input_keys=(
                "handles", "profileUrls", "startUrls", "profileUrl",
                "profile", "username", "handle", "from",
            ),
            identity_ref="target.handle",
            list_handle_input_keys=("handles",),
            list_url_input_keys=("profileUrls", "startUrls"),
            url_input_keys=("profileUrl",),
            max_items_input_keys=(
                "maxItems", "maxPosts", "numberOfTweets", "resultsLimit",
                "maxResults", "maxPostsPerProfile", "maxNbItemsToScrape",
            ),
        )

    def build_actor_input(self, target, manifest, window):
        return build_profile_input(target, manifest, window)

    def validate_output(
        self,
        rows: Sequence[Mapping[str, object]],
        target: TargetSpec,
        manifest: ActorManifest,
        window: FetchWindow,
    ) -> NormalizedBatch:
        derived_rows = derive_profile_rows(rows, manifest)
        validated = validate_and_map(
            derived_rows, target, manifest, window,
            platform="x", source_type=SourceType.TWITTER,
        )
        visible_rows, excluded_replies = exclude_x_reply_rows(derived_rows)
        if not excluded_replies:
            return validated
        if not visible_rows:
            return _valid_empty_batch()
        try:
            return validate_and_map(
                visible_rows, target, manifest, window,
                platform="x", source_type=SourceType.TWITTER,
            )
        except ActorManifestError as error:
            if error.code == "apify_actor_metadata_only":
                return _valid_empty_batch()
            raise

    async def fetch_native_fallback(self, target, window):
        return NativeFallbackResult.unsupported()


def _valid_empty_batch() -> NormalizedBatch:
    return NormalizedBatch(items=(), semantic_outcome="valid_empty")
