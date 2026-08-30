"""Platform-registered ActorOps execution for one bound source."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..models import ApifySocialSubscriptionConfig, ContentItem
from ..scrapers.base import SourceFetchError
from .actorops.publication import source_avatar_hint_from_items


async def fetch_actorops_source_subscription(
    *,
    subscription: ApifySocialSubscriptionConfig,
    since: datetime,
    ops: Any,
    client_factory: Callable[[], Any],
    job_id: str | None,
    frozen_snapshot: Any | None,
    public_http_client: Any | None = None,
    avatar_observer: Callable[..., None] | None = None,
) -> list[ContentItem]:
    """Fetch latest configured items through one explicitly registered Route.

    Feed display windows are not acquisition windows: an inactive account's
    older, but still latest, items must remain observable and deduplicable.
    Unknown platform tuples fail before a client can start a paid Actor.
    """

    if getattr(frozen_snapshot, "actorops_version", None) != 2:
        raise SourceFetchError(
            "ActorOps v2 execution snapshot is required",
            retryable=False,
            code="actorops_v2_snapshot_required",
        )
    items = await ops.fetch_subscription(
        subscription=subscription,
        since=since,
        client_factory=client_factory,
        job_id=job_id,
        snapshot=frozen_snapshot,
        public_http_client=public_http_client,
    )
    _observe_source_avatar(items, subscription, avatar_observer)
    return items


def _observe_source_avatar(
    items: list[ContentItem],
    subscription: ApifySocialSubscriptionConfig,
    avatar_observer: Callable[..., None] | None,
) -> None:
    if avatar_observer is None:
        return
    hint = source_avatar_hint_from_items(items, subscription)
    if hint is None:
        return
    avatar_observer(
        source_id=hint.source_id,
        remote_url=hint.remote_url,
        origin=hint.origin,
        kind=hint.kind,
    )


__all__ = ["fetch_actorops_source_subscription"]
