from __future__ import annotations

import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx

from src.models import ContentItem, SourceType
from src.services.actorops.publication import ActorOpsV2RoutedList, proof_from_items
from src.services.apify_native_fallback import (
    NativeFallbackDecision,
    NativeFetchEvidence,
    YouTubeNativeActorFallbackScraper,
    decide_youtube_actor_fallback,
    is_canonical_youtube_url,
    reattribute_youtube_fallback_items,
)


YOUTUBE_FEED = "https://www.youtube.com/feeds/videos.xml?channel_id=UCabcdefghijklmnopqrstuv"


def test_youtube_fallback_admission_is_free_and_fail_closed() -> None:
    assert decide_youtube_actor_fallback(
        NativeFetchEvidence(canonical_url=YOUTUBE_FEED)
    ) is NativeFallbackDecision.ACCEPT_NATIVE
    assert decide_youtube_actor_fallback(
        NativeFetchEvidence(canonical_url=YOUTUBE_FEED, status_code=429)
    ) is NativeFallbackDecision.ACTOR_FALLBACK
    assert decide_youtube_actor_fallback(
        NativeFetchEvidence(canonical_url=YOUTUBE_FEED, security_rejected=True)
    ) is NativeFallbackDecision.FAIL_CLOSED
    assert is_canonical_youtube_url(YOUTUBE_FEED)
    assert not is_canonical_youtube_url("https://youtube.com.evil.example/feed")


def test_youtube_reattribution_preserves_only_v2_publication_proof() -> None:
    item = ContentItem(
        id="temporary", source_type=SourceType.INSTAGRAM, title="Video",
        url="https://www.youtube.com/watch?v=video-123", content="Description",
        published_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        metadata={"native_id": "video-123"},
    )
    proof = {
        "version": 2, "workspace_id": "workspace", "route_id": "route",
        "source_id": "source", "target_fingerprint": "a" * 64,
        "binding_version": 1, "candidate_id": "candidate",
        "candidate_generation": 1, "latest_published_at": None,
        "latest_item_id_hash": None,
    }

    projected = reattribute_youtube_fallback_items(
        ActorOpsV2RoutedList([item], proof), source_id="source",
        source_key="rss:youtube", canonical_feed_url=YOUTUBE_FEED,
    )

    assert projected[0].id.startswith("rss:")
    assert projected[0].source_type is SourceType.RSS
    assert proof_from_items(projected) == proof


def test_pending_v2_youtube_binding_uses_native_rss() -> None:
    source = SimpleNamespace(url=YOUTUBE_FEED, source_id="source", fetch_limit=2)

    class Repository:
        def get_binding(self, _source_id):
            return SimpleNamespace(status=SimpleNamespace(value="pending"))

    class ActorOps:
        repository = Repository()

    async def check() -> None:
        async with httpx.AsyncClient() as client:
            scraper = YouTubeNativeActorFallbackScraper(
                source, client, actor_ops=ActorOps(), apify_coordinator=object(),
            )
            marker = object()
            scraper.native = SimpleNamespace(
                upstream_response_schema=None, source_avatar_hints=(), strict_errors=True,
                fetch=lambda _since: _return([marker]),
            )
            assert await scraper.fetch(datetime.now(timezone.utc)) == [marker]

    asyncio.run(check())


async def _return(value):
    return value
