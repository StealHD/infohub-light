"""Bridge the legacy YouTube RSS wrapper onto a frozen v2 execution handle."""

from __future__ import annotations

from datetime import datetime
from typing import Any

import httpx

from ...models import ApifySocialSubscriptionConfig
from ...scrapers.apify_client import ApifyClient
from ..apify_actor_source_execution import fetch_actorops_source_subscription


async def fetch_v2_youtube_rss(
    *,
    source: Any,
    actor_ops: Any,
    coordinator: Any,
    http_client: httpx.AsyncClient,
    binding: Any,
    snapshot: Any,
    since: datetime,
    job_id: str | None,
) -> list[Any]:
    """Use v2 directly; never hand its handle to the v1 Actor runtime."""

    subscription = ApifySocialSubscriptionConfig(
        profile_id=str(binding["route_id"]),
        platform="youtube",
        kind="channel",
        target=str(source.url),
        source_id=str(source.source_id),
        source_key=str(getattr(source, "source_key", "") or source.url),
        source_display_name=str(
            getattr(source, "source_display_name", "") or getattr(source, "name", "")
        ),
        catalog_source_type="rss",
        analysis_mode=getattr(source, "analysis_mode", "full"),
        source_priority=int(getattr(source, "source_priority", 0) or 0),
        fetch_limit=int(source.fetch_limit),
        channel=getattr(source, "channel", None),
        topics=list(getattr(source, "topics", ()) or ()),
        tags=list(getattr(source, "tags", ()) or ()),
        personal_tags=list(getattr(source, "personal_tags", ()) or ()),
    )
    return await fetch_actorops_source_subscription(
        subscription=subscription,
        since=since,
        ops=actor_ops,
        client_factory=lambda: ApifyClient(
            coordinator=coordinator, http_client=http_client
        ),
        job_id=job_id,
        frozen_snapshot=snapshot,
    )


__all__ = ["fetch_v2_youtube_rss"]
