"""Platform-registered ActorOps execution for one bound source."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from typing import Any

from ..models import ApifySocialSubscriptionConfig, ContentItem
from ..scrapers.base import SourceFetchError


async def fetch_actorops_source_subscription(
    *,
    subscription: ApifySocialSubscriptionConfig,
    since: datetime,
    ops: Any,
    client_factory: Callable[[], Any],
    job_id: str | None,
    frozen_snapshot: Any | None,
    public_http_client: Any | None = None,
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
    return await ops.fetch_subscription(
        subscription=subscription,
        since=since,
        client_factory=client_factory,
        job_id=job_id,
        snapshot=frozen_snapshot,
        public_http_client=public_http_client,
    )


__all__ = ["fetch_actorops_source_subscription"]
