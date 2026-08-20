"""Composition root for the three Phase 2 source adapters."""

from __future__ import annotations

from collections.abc import Awaitable, Callable

from ..ports import FetchWindow, NativeFallbackResult, TargetSpec
from ..registry import AdapterRegistry
from .instagram.profile_items import InstagramProfileItemsAdapter
from .x.profile_items import XProfileItemsAdapter
from .youtube.channel_items import YouTubeChannelItemsAdapter
from .youtube.native import build_youtube_native_fetcher


NativeFetcher = Callable[
    [TargetSpec, FetchWindow], Awaitable[NativeFallbackResult]
]


def build_default_registry(
    *, youtube_native_fetcher: NativeFetcher | None = None
) -> AdapterRegistry:
    registry = AdapterRegistry()
    for adapter in (
        XProfileItemsAdapter(),
        InstagramProfileItemsAdapter(),
        YouTubeChannelItemsAdapter(native_fetcher=youtube_native_fetcher),
    ):
        registry.register(adapter)
    return registry


def build_source_registry(subscription: object, http_client: object) -> AdapterRegistry:
    return build_default_registry(
        youtube_native_fetcher=build_youtube_native_fetcher(
            subscription, http_client
        )
    )


__all__ = ["build_default_registry", "build_source_registry"]
