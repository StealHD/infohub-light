"""Platform-registered ActorOps execution for one bound source."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime, timezone
from typing import Any

from ..models import ApifySocialSubscriptionConfig, ContentItem
from ..scrapers.base import SourceFetchError
from .apify_actor_capability_matrix import source_fetch_window_policy
from .apify_actor_manifest import ActorRuntime
from .apify_actor_runtime import (
    ActorContentContext,
    ApifyActorRuntimeService,
    actor_target_for_route,
)


async def fetch_actorops_source_subscription(
    *,
    subscription: ApifySocialSubscriptionConfig,
    since: datetime,
    ops: Any,
    client_factory: Callable[[], Any],
    job_id: str | None,
    frozen_snapshot: Any | None,
) -> list[ContentItem]:
    """Fetch latest configured items through one explicitly registered Route.

    Feed display windows are not acquisition windows: an inactive account's
    older, but still latest, items must remain observable and deduplicable.
    Unknown platform tuples fail before a client can start a paid Actor.
    """

    if getattr(frozen_snapshot, "actorops_version", 1) == 2:
        return await ops.fetch_subscription(
            subscription=subscription,
            since=since,
            client_factory=client_factory,
            job_id=job_id,
            snapshot=frozen_snapshot,
        )

    route = ops.get_route(str(subscription.profile_id))
    platform = str(route["platform"])
    window_policy = source_fetch_window_policy(
        platform,
        str(route.get("target_type") or ""),
        str(route.get("capability") or ""),
    )
    if window_policy not in {"latest_items", "time_window"}:
        raise SourceFetchError(
            "ActorOps Route is not registered for source execution",
            retryable=False,
            code="apify_actor_route_unregistered",
        )
    analysis_mode = (
        subscription.analysis_mode.value
        if hasattr(subscription.analysis_mode, "value")
        else str(subscription.analysis_mode)
    )
    now = datetime.now(timezone.utc)
    result = await ApifyActorRuntimeService(ops, client_factory()).fetch(
        route_id=str(subscription.profile_id),
        source_id=str(subscription.source_id),
        target=actor_target_for_route(platform, subscription.target),
        runtime=ActorRuntime(
            max_items=subscription.fetch_limit,
            since_iso=(
                None
                if window_policy == "latest_items"
                else since.astimezone(timezone.utc).isoformat()
            ),
            until_iso=now.isoformat(),
        ),
        content=ActorContentContext(
            platform=platform,
            source_id=str(subscription.source_id),
            source_key=str(
                subscription.source_key
                or f"apify_social:{subscription.profile_id}:{subscription.source_id}"
            ),
            source_name=str(subscription.source_display_name or subscription.target),
            channel=subscription.channel,
            topics=tuple(subscription.topics),
            tags=tuple(subscription.tags),
            personal_tags=tuple(subscription.personal_tags),
            analysis_mode=analysis_mode,
        ),
        job_id=job_id,
        frozen_snapshot=frozen_snapshot,
        source_target_value=subscription.target,
    )
    return result.value or []


__all__ = ["fetch_actorops_source_subscription"]
