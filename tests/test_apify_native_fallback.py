import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import httpx

from src.models import ContentItem, SourceType
from src.services.apify_native_fallback import (
    NativeFallbackDecision,
    NativeFetchEvidence,
    decide_youtube_actor_fallback,
    is_canonical_youtube_url,
    reattribute_youtube_fallback_items,
    YouTubeNativeActorFallbackScraper,
)
from src.services.apify_actor_ops import RouteInvocationResult


YOUTUBE_FEED = (
    "https://www.youtube.com/feeds/videos.xml?"
    "channel_id=UCabcdefghijklmnopqrstuv&feature=shared"
)


def test_youtube_fallback_admission_preserves_native_first_cost_boundary():
    assert decide_youtube_actor_fallback(
        NativeFetchEvidence(canonical_url=YOUTUBE_FEED)
    ) == NativeFallbackDecision.ACCEPT_NATIVE
    assert decide_youtube_actor_fallback(
        NativeFetchEvidence(canonical_url=YOUTUBE_FEED, returned_empty=True)
    ) == NativeFallbackDecision.ACCEPT_NATIVE
    assert decide_youtube_actor_fallback(
        NativeFetchEvidence(
            canonical_url=YOUTUBE_FEED,
            returned_empty=True,
            had_historical_content=True,
        )
    ) == NativeFallbackDecision.ACTOR_FALLBACK
    assert decide_youtube_actor_fallback(
        NativeFetchEvidence(
            canonical_url=YOUTUBE_FEED,
            exception=httpx.ReadTimeout("bounded timeout"),
        )
    ) == NativeFallbackDecision.ACTOR_FALLBACK
    assert decide_youtube_actor_fallback(
        NativeFetchEvidence(canonical_url=YOUTUBE_FEED, status_code=429)
    ) == NativeFallbackDecision.ACTOR_FALLBACK
    assert decide_youtube_actor_fallback(
        NativeFetchEvidence(
            canonical_url=YOUTUBE_FEED,
            status_code=404,
            target_previously_validated=True,
        )
    ) == NativeFallbackDecision.ACTOR_FALLBACK


def test_youtube_fallback_rejects_security_or_identity_changes():
    assert is_canonical_youtube_url(YOUTUBE_FEED)
    assert not is_canonical_youtube_url(
        "https://youtube.com.evil.example/feeds/videos.xml"
    )
    assert not is_canonical_youtube_url(
        "https://203.0.113.8/feeds/videos.xml?channel_id=UC1"
    )
    assert decide_youtube_actor_fallback(
        NativeFetchEvidence(
            canonical_url=YOUTUBE_FEED,
            security_rejected=True,
            status_code=503,
        )
    ) == NativeFallbackDecision.FAIL_CLOSED
    assert decide_youtube_actor_fallback(
        NativeFetchEvidence(
            canonical_url=YOUTUBE_FEED,
            confirmed_target_unavailable=True,
        )
    ) == NativeFallbackDecision.FAIL_CLOSED


def test_actor_fallback_keeps_rss_source_and_stable_youtube_item_id():
    item = ContentItem(
        id="apify:temporary:1",
        source_type=SourceType.INSTAGRAM,
        title="Video title",
        url="https://www.youtube.com/watch?v=video-123",
        content="Description",
        author="Channel",
        published_at=datetime(2026, 7, 30, tzinfo=timezone.utc),
        metadata={"native_id": "video-123"},
    )

    first = reattribute_youtube_fallback_items(
        [item],
        source_id="source-youtube",
        source_key="rss:youtube-channel",
        canonical_feed_url=YOUTUBE_FEED,
    )[0]
    second = reattribute_youtube_fallback_items(
        [item],
        source_id="source-youtube",
        source_key="rss:youtube-channel",
        canonical_feed_url=YOUTUBE_FEED,
    )[0]

    assert first.id == second.id
    assert first.id.startswith("rss:")
    assert first.source_type == SourceType.RSS
    assert first.metadata["source_id"] == "source-youtube"
    assert first.metadata["acquisition_origin"] == "apify_fallback"


def test_youtube_fallback_freezes_route_before_native_fetch(monkeypatch):
    snapshots = []

    class ActorOps:
        workspace_id = "workspace-test"
        generation = 7

        def get_source_binding(self, source_id):
            assert source_id == "source-youtube"
            return {
                "route_id": "route-youtube",
                "validation_status": "ready_3of3",
            }

        def get_route(self, route_id):
            assert route_id == "route-youtube"
            return {"platform": "youtube"}

        def freeze_execution(self, route_id, *, source_id=None):
            assert route_id == "route-youtube"
            assert source_id == "source-youtube"
            snapshot = SimpleNamespace(generation=self.generation)
            snapshots.append(snapshot)
            return snapshot

    actor_ops = ActorOps()
    exact_feed = (
        "https://www.youtube.com/feeds/videos.xml?"
        "channel_id=UCabcdefghijklmnopqrstuv"
    )
    source = SimpleNamespace(
        url=exact_feed,
        source_id="source-youtube",
        source_key="rss:youtube-channel",
        source_display_name="Channel",
        name="Channel",
        channel="AI",
        topics=(),
        tags=(),
        personal_tags=(),
        analysis_mode="full",
    )
    client = httpx.AsyncClient(transport=httpx.MockTransport(lambda _request: None))
    scraper = YouTubeNativeActorFallbackScraper(
        source,
        client,
        actor_ops=actor_ops,
        apify_coordinator=object(),
        job_id="job-youtube",
    )

    class Native:
        upstream_response_schema = None
        source_avatar_hints = ()
        strict_errors = True

        async def fetch(self, _since):
            actor_ops.generation = 8
            raise httpx.ReadTimeout("native timed out")

    scraper.native = Native()
    scraper._had_historical_content = lambda: False

    class DummyClient:
        def __init__(self, **_kwargs):
            pass

    class Runtime:
        def __init__(self, _actor_ops, _client):
            pass

        async def fetch(self, **kwargs):
            assert kwargs["frozen_snapshot"].generation == 7
            return RouteInvocationResult(value=[])

    monkeypatch.setattr("src.scrapers.apify_client.ApifyClient", DummyClient)
    monkeypatch.setattr(
        "src.services.apify_actor_runtime.ApifyActorRuntimeService",
        Runtime,
    )

    result = asyncio.run(
        scraper.fetch(datetime(2026, 7, 30, tzinfo=timezone.utc))
    )
    asyncio.run(client.aclose())

    assert result == []
    assert len(snapshots) == 1
    assert scraper.publication_snapshots == snapshots
