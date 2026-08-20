"""Runtime bridge from frozen ActorOps revisions to normalized content."""

from __future__ import annotations

import hashlib
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from typing import Any
from urllib.parse import parse_qsl, urlparse

from ..models import ContentItem, SourceType
from ..scrapers.apify_client import ApifyClient, ApifyClientError
from .apify_key_pool import ApifyKeyPoolError
from .apify_actor_manifest import (
    ActorManifestError,
    ActorRuntime,
    ActorTarget,
    MappedActorItem,
    map_actor_output,
    render_actor_input,
)
from .apify_actor_ops import (
    ActorOpsError,
    ApifyActorOpsService,
    RouteExecutionResult,
    RouteExecutionSnapshot,
    RouteInvocationResult,
    RouteSlotSnapshot,
    VALIDATION_MAX_CHARGE_USD_LIMIT,
)


@dataclass(frozen=True, slots=True)
class ActorContentContext:
    """Safe catalog projection attached to normalized Actor output."""

    platform: str
    source_id: str
    source_key: str
    source_name: str
    channel: str | None = None
    topics: tuple[str, ...] = ()
    tags: tuple[str, ...] = ()
    personal_tags: tuple[str, ...] = ()
    analysis_mode: str = "full"


class ApifyActorRuntimeService:
    """Execute one generic Route using an injected durable Apify client."""

    def __init__(
        self,
        ops: ApifyActorOpsService,
        client: ApifyClient,
    ) -> None:
        self.ops = ops
        self.client = client

    async def fetch(
        self,
        *,
        route_id: str,
        source_id: str,
        target: ActorTarget,
        runtime: ActorRuntime,
        content: ActorContentContext,
        key_pool_generation: int | None = None,
        job_id: str | None = None,
        frozen_snapshot: RouteExecutionSnapshot | None = None,
        source_target_value: str | None = None,
    ) -> RouteExecutionResult[list[ContentItem]]:
        if source_target_value is not None:
            self.ops.assert_source_target(
                route_id,
                source_id,
                source_target_value,
            )

        async def invoke(
            slot: RouteSlotSnapshot,
            snapshot: RouteExecutionSnapshot,
        ) -> RouteInvocationResult[list[ContentItem]]:
            actual_charge_usd: float | None = None
            try:
                if slot.manifest is None:
                    if (
                        content.platform.casefold() == "x"
                        and (
                            slot.lifecycle == "legacy_builtin"
                            or slot.execution_mode == "current"
                            or slot.observed_manifest
                        )
                    ):
                        return await self._fetch_controlled_x(
                            slot=slot,
                            snapshot=snapshot,
                            source_id=source_id,
                            target=target,
                            runtime=runtime,
                            content=content,
                            job_id=job_id,
                        )
                    return RouteInvocationResult(
                        semantic_outcome="revision_not_executable",
                        failure_scope="actor",
                        error_code="apify_actor_revision_not_executable",
                    )
                if not slot.build_number or not slot.manifest_hash:
                    return RouteInvocationResult(
                        semantic_outcome="revision_not_executable",
                        failure_scope="actor",
                        error_code="apify_actor_revision_not_executable",
                    )
                actor_input = render_actor_input(slot.manifest, target, runtime)
                run = await self.client.run_actor_detailed(
                    slot.actor_id,
                    actor_input,
                    max_total_charge_usd=snapshot.per_run_cap_usd,
                    logical_run_id=snapshot.attempt_id or job_id or source_id,
                    build_number=slot.build_number,
                    max_paid_dataset_items=max(1, int(runtime.max_items)),
                    dataset_item_limit=min(max(2, int(runtime.max_items) + 1), 100),
                    expected_pool_generation=snapshot.key_pool_generation,
                )
                actual_charge_usd = run.actual_charge_usd
                mapped = map_actor_output(
                    slot.manifest,
                    run.items,
                    target,
                    runtime,
                )
                items = sorted(
                    (_content_item_from_mapped(item, content=content) for item in mapped.items),
                    key=lambda item: (item.published_at, item.id), reverse=True,
                )[: int(runtime.max_items)]
                return RouteInvocationResult(
                    value=items,
                    semantic_outcome=mapped.semantic_outcome,
                    cost_usd=actual_charge_usd,
                    latest_published_at=mapped.latest_published_at,
                    latest_item_id=mapped.latest_native_id,
                )
            except ApifyClientError as exc:
                return RouteInvocationResult(
                    semantic_outcome=str(exc.code),
                    failure_scope=_client_failure_scope(exc),
                    error_code=str(exc.code),
                )
            except ApifyKeyPoolError as exc:
                return RouteInvocationResult(
                    semantic_outcome=str(exc.code),
                    failure_scope="key",
                    error_code=str(exc.code),
                )
            except ActorManifestError as exc:
                return RouteInvocationResult(
                    semantic_outcome=str(exc.code),
                    failure_scope=_client_failure_scope(exc),
                    cost_usd=actual_charge_usd,
                    error_code=str(exc.code),
                )

        execute_kwargs: dict[str, Any] = {
            "key_pool_generation": key_pool_generation,
            "job_id": job_id,
        }
        if frozen_snapshot is not None:
            execute_kwargs["frozen_snapshot"] = frozen_snapshot
        return await self.ops.execute_route(
            route_id,
            source_id,
            invoke,
            **execute_kwargs,
        )

    async def _fetch_controlled_x(
        self,
        *,
        slot: RouteSlotSnapshot,
        snapshot: RouteExecutionSnapshot,
        source_id: str,
        target: ActorTarget,
        runtime: ActorRuntime,
        content: ActorContentContext,
        job_id: str | None,
    ) -> RouteInvocationResult[list[ContentItem]]:
        """Execute the value-free observed compatibility contract for X."""

        from ..models import (
            ApifySocialConfig,
            ApifySocialPlatform,
            ApifySocialSubscriptionConfig,
        )
        from ..scrapers.apify_social import (
            ApifySocialScraper,
            ApifySocialSemanticError,
        )

        handle = str(target.handle or target.native_id or "").strip().lstrip("@")
        if not handle:
            return RouteInvocationResult(
                semantic_outcome="apify_actor_target_invalid",
                failure_scope="target",
                error_code="apify_actor_target_invalid",
            )
        since = (
            datetime.fromisoformat(runtime.since_iso.replace("Z", "+00:00"))
            if runtime.since_iso
            else datetime.min.replace(tzinfo=timezone.utc)
        )
        if since.tzinfo is None:
            since = since.replace(tzinfo=timezone.utc)
        sub = ApifySocialSubscriptionConfig(
            source_id=source_id,
            source_key=content.source_key,
            source_display_name=content.source_name,
            platform=ApifySocialPlatform.X,
            kind="profile",
            target=handle,
            fetch_limit=int(runtime.max_items),
            enabled=True,
            channel=content.channel,
            topics=list(content.topics),
            tags=list(content.tags),
            personal_tags=list(content.personal_tags),
            analysis_mode=content.analysis_mode,
        )
        scraper = ApifySocialScraper(
            ApifySocialConfig(
                enabled=True,
                timeout_seconds=self.client.timeout_seconds,
                subscriptions=[sub],
            ),
            self.client.http_client,
            apify_coordinator=self.client.coordinator,
        )
        actor_input = scraper._actor_input(
            sub,
            actor_id=slot.actor_id,
            input_dialect=slot.compatibility_input_dialect,
            input_count_field=slot.compatibility_input_count_field,
        )
        try:
            run = await self.client.run_actor_detailed(
                slot.actor_id,
                actor_input,
                max_total_charge_usd=min(snapshot.per_run_cap_usd, VALIDATION_MAX_CHARGE_USD_LIMIT),
                logical_run_id=snapshot.attempt_id or job_id or source_id,
                build_number=(
                    slot.build_number if slot.execution_mode != "current" else None
                ),
                max_paid_dataset_items=max(1, int(runtime.max_items)),
                dataset_item_limit=min(max(2, int(runtime.max_items) + 1), 100),
                expected_pool_generation=snapshot.key_pool_generation,
                max_remote_starts=1,
            )
            candidate_rows, raw_semantic = scraper._validated_x_rows(run.items)
            expected = handle.casefold()
            identity_rows = [
                row
                for row in candidate_rows
                if _x_output_handle(row) == expected
            ]
            if candidate_rows and not identity_rows:
                return RouteInvocationResult(
                    semantic_outcome="apify_actor_identity_mismatch",
                    cost_usd=run.actual_charge_usd,
                    failure_scope="actor",
                    error_code="apify_actor_identity_mismatch",
                )
            items = scraper._parse_candidate_rows(identity_rows, sub, since)
            all_items = scraper._parse_candidate_rows(
                identity_rows,
                sub,
                datetime.min.replace(tzinfo=timezone.utc),
            )
            latest = (
                max(items, key=lambda item: (item.published_at, item.id))
                if items
                else max(
                    all_items,
                    key=lambda item: (item.published_at, item.id),
                    default=None,
                )
            )
            semantic = (
                "valid_nonempty"
                if items
                else "valid_empty"
                if identity_rows
                else raw_semantic
            )
            return RouteInvocationResult(
                value=items,
                semantic_outcome=semantic,
                cost_usd=run.actual_charge_usd,
                latest_published_at=(
                    latest.published_at.astimezone(timezone.utc).isoformat()
                    if latest is not None
                    else None
                ),
                latest_item_id=(latest.id if latest is not None else None),
            )
        except ApifySocialSemanticError as exc:
            return RouteInvocationResult(
                semantic_outcome=str(exc.code),
                cost_usd=run.actual_charge_usd,
                failure_scope=(
                    "target" if exc.failure_scope == "target" else "actor"
                ),
                error_code=str(exc.code),
            )


_X_PROFILE_RE = re.compile(r"^[A-Za-z0-9_]{1,15}$")
_INSTAGRAM_PROFILE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
_YOUTUBE_CHANNEL_ID_RE = re.compile(r"^UC[A-Za-z0-9_-]{22}$")
_X_RESERVED_PROFILES = frozenset(
    {
        "compose",
        "explore",
        "home",
        "i",
        "messages",
        "notifications",
        "search",
        "settings",
    }
)
_INSTAGRAM_RESERVED_PROFILES = frozenset(
    {
        "about",
        "accounts",
        "developer",
        "direct",
        "directory",
        "explore",
        "p",
        "reel",
        "reels",
        "stories",
        "web",
    }
)


def _x_output_handle(row: dict[str, Any]) -> str:
    user_value = row.get("user") or row.get("author") or {}
    user = user_value if isinstance(user_value, dict) else {}
    value = str(
        user.get("screen_name")
        or user.get("username")
        or user.get("userName")
        or user.get("handle")
        or row.get("user_screen_name")
        or row.get("user_username")
        or row.get("screen_name")
        or row.get("handle")
        or row.get("username")
        or ""
    ).strip().lstrip("@").casefold()
    if value:
        return value
    parsed = urlparse(str(row.get("url") or row.get("permalink") or ""))
    parts = [part for part in parsed.path.split("/") if part]
    return parts[0].lstrip("@").casefold() if parts else ""


def actor_target_for_route(platform: str, raw_target: str) -> ActorTarget:
    """Normalize one stored target while preserving the platform hostname."""

    normalized_platform = str(platform).strip().casefold()
    raw = str(raw_target or "").strip()
    if normalized_platform not in {"x", "instagram", "youtube"} or not raw:
        raise ActorOpsError(
            "apify_actor_target_invalid",
            "Actor target is invalid for the selected Route",
            status_code=422,
        )
    parsed = urlparse(raw)
    is_url = parsed.scheme.casefold() == "https" and bool(parsed.hostname)
    host = str(parsed.hostname or "").casefold()
    if normalized_platform == "x":
        if (
            is_url
            and (
                host
                not in {
                    "x.com",
                    "www.x.com",
                    "twitter.com",
                    "www.twitter.com",
                }
                or parsed.port not in {None, 443}
                or parsed.query
                or parsed.fragment
                or len([part for part in parsed.path.split("/") if part]) != 1
            )
        ) or (not is_url and "://" in raw):
            raise ActorOpsError(
                "apify_actor_target_invalid",
                "X target must preserve the x.com identity",
                status_code=422,
            )
        handle = (
            parsed.path.strip("/")
            if is_url
            else raw.lstrip("@").strip("/")
        )
        if (
            not _X_PROFILE_RE.fullmatch(handle)
            or handle.casefold() in _X_RESERVED_PROFILES
        ):
            raise ActorOpsError(
                "apify_actor_target_invalid",
                "X target must be one public profile handle",
                status_code=422,
            )
        canonical_url = f"https://x.com/{handle}"
        native_id = handle
    elif normalized_platform == "instagram":
        if (
            is_url
            and (
                host not in {"instagram.com", "www.instagram.com"}
                or parsed.port not in {None, 443}
                or parsed.query
                or parsed.fragment
                or len([part for part in parsed.path.split("/") if part]) != 1
            )
        ) or (not is_url and "://" in raw):
            raise ActorOpsError(
                "apify_actor_target_invalid",
                "Instagram target must preserve the instagram.com identity",
                status_code=422,
            )
        handle = (
            parsed.path.strip("/")
            if is_url
            else raw.lstrip("@").strip("/")
        )
        if (
            not _INSTAGRAM_PROFILE_RE.fullmatch(handle)
            or ".." in handle
            or handle.startswith(".")
            or handle.endswith(".")
            or handle.casefold() in _INSTAGRAM_RESERVED_PROFILES
        ):
            raise ActorOpsError(
                "apify_actor_target_invalid",
                "Instagram target must be one public profile username",
                status_code=422,
            )
        canonical_url = f"https://www.instagram.com/{handle}/"
        native_id = handle
    else:
        if (
            not is_url
            or host not in {"youtube.com", "www.youtube.com"}
            or parsed.port not in {None, 443}
            or parsed.fragment
        ):
            raise ActorOpsError(
                "apify_actor_target_invalid",
                "YouTube target must preserve the youtube.com identity",
                status_code=422,
            )
        pairs = parse_qsl(parsed.query, keep_blank_values=True)
        path_parts = [part for part in parsed.path.split("/") if part]
        native_id: str | None = None
        handle: str | None = None
        if parsed.path == "/feeds/videos.xml":
            if (
                len(pairs) != 1
                or pairs[0][0] != "channel_id"
                or _YOUTUBE_CHANNEL_ID_RE.fullmatch(pairs[0][1]) is None
            ):
                raise ActorOpsError(
                    "apify_actor_target_invalid",
                    "YouTube feed target must contain one exact channel_id",
                    status_code=422,
                )
            native_id = pairs[0][1]
            # Actors expect a public channel page, not YouTube's Atom endpoint.
            canonical_url = f"https://www.youtube.com/channel/{native_id}"
        elif (
            len(path_parts) == 2
            and path_parts[0] == "channel"
            and not pairs
            and _YOUTUBE_CHANNEL_ID_RE.fullmatch(path_parts[1])
        ):
            native_id = path_parts[1]
            canonical_url = f"https://www.youtube.com/channel/{native_id}"
        elif (
            len(path_parts) == 1
            and path_parts[0].startswith("@")
            and len(path_parts[0]) > 1
            and not pairs
        ):
            handle = path_parts[0][1:]
            canonical_url = f"https://www.youtube.com/@{handle}"
        else:
            raise ActorOpsError(
                "apify_actor_target_invalid",
                "YouTube target must be one channel URL or channel feed",
                status_code=422,
            )
    if not str(native_id or handle or "").strip():
        raise ActorOpsError(
            "apify_actor_target_invalid",
            "Actor target does not contain a stable identity",
            status_code=422,
        )
    return ActorTarget(
        canonical_url=canonical_url,
        native_id=native_id,
        handle=handle,
    )


def _client_failure_scope(
    error: ApifyClientError,
) -> str:
    code = str(error.code)
    if code in {
        "apify_start_outcome_unknown",
        "apify_run_reconcile_required",
    }:
        return "start_outcome_unknown"
    if code.startswith(
        (
            "apify_key_",
            "apify_quota_",
            "apify_pool_",
        )
    ):
        return "key"
    if code in {
        "apify_actor_target_private",
        "apify_actor_target_deleted",
        "apify_actor_target_not_found",
        "apify_actor_no_such_account",
        "apify_target_private",
        "apify_target_deleted",
        "apify_target_not_found",
    } or any(
        marker in code
        for marker in (
            "target_private",
            "target_deleted",
            "target_not_found",
            "no_such_account",
        )
    ):
        return "target"
    return "actor"


def _source_type(platform: str) -> SourceType:
    normalized = str(platform).strip().casefold()
    if normalized == "x":
        return SourceType.TWITTER
    if normalized == "instagram":
        return SourceType.INSTAGRAM
    if normalized == "youtube":
        return SourceType.RSS
    if normalized == "facebook":
        return SourceType.FACEBOOK
    if normalized == "telegram":
        return SourceType.TELEGRAM
    return SourceType.RSS


def _content_item_from_mapped(
    item: MappedActorItem,
    *,
    content: ActorContentContext,
) -> ContentItem:
    stable_id = hashlib.sha256(
        "\x1f".join(
            (
                str(content.platform).casefold(),
                str(content.source_key),
                str(item.native_id),
            )
        ).encode("utf-8")
    ).hexdigest()[:24]
    metrics = {
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
    title = str(item.title or item.text or content.source_name).strip()
    body = str(item.text or item.title or "").strip()
    metadata: dict[str, Any] = {
        "source_id": content.source_id,
        "source_key": content.source_key,
        "source_name": content.source_name,
        "platform": str(content.platform).casefold(),
        "native_id": item.native_id,
        "tags": list(dict.fromkeys(content.tags)),
        "topics": list(dict.fromkeys(content.topics)),
        "personal_tags": list(dict.fromkeys(content.personal_tags)),
        "analysis_mode": content.analysis_mode,
        **({"channel": content.channel} if content.channel else {}),
        **({"engagement": metrics} if metrics else {}),
        **(
            {"author_avatar_url": item.author_avatar_url}
            if item.author_avatar_url
            else {}
        ),
        **({"image_url": item.thumbnail_url} if item.thumbnail_url else {}),
    }
    return ContentItem(
        id=f"actor:{str(content.platform).casefold()}:{stable_id}",
        source_type=_source_type(content.platform),
        title=title,
        url=item.url,
        content=body,
        author=item.author or item.author_handle or content.source_name,
        published_at=_utc(item.published_at),
        metadata=metadata,
    )


def _utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


__all__ = [
    "ActorContentContext",
    "ApifyActorRuntimeService",
    "actor_target_for_route",
]
