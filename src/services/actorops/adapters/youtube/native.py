"""Public YouTube Atom fallback isolated behind the Adapter port."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any

from .....models import RSSSourceConfig
from .....scrapers.rss import RSSScraper
from ...ports import FetchWindow, NativeFallbackResult, TargetSpec


def build_youtube_native_fetcher(
    subscription: Any,
    http_client: Any,
) -> Callable[[TargetSpec, FetchWindow], Awaitable[NativeFallbackResult]]:
    async def fetch(target: TargetSpec, window: FetchWindow) -> NativeFallbackResult:
        native_url = str(target.native_url or "")
        if "/feeds/videos.xml" not in native_url:
            return NativeFallbackResult.unsupported()
        source = RSSSourceConfig(
            name=str(subscription.source_display_name or subscription.target),
            url=native_url,
            source_id=subscription.source_id,
            source_key=subscription.source_key,
            source_display_name=subscription.source_display_name,
            catalog_source_type="rss",
            analysis_mode=subscription.analysis_mode,
            source_priority=subscription.source_priority,
            enabled=True,
            channel=subscription.channel,
            topics=list(subscription.topics),
            tags=list(subscription.tags),
            personal_tags=list(subscription.personal_tags),
            fetch_limit=window.max_items,
            enforce_public_network=True,
        )
        scraper = RSSScraper([source], http_client)
        scraper.strict_errors = True
        items = await scraper.fetch(window.since)
        return NativeFallbackResult(
            supported=True,
            items=tuple(items),
            degraded_reason="youtube_public_atom",
        )

    return fetch
