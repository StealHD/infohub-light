import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.models import ApifySocialSubscriptionConfig
from src.scrapers.base import SourceFetchError
from src.services.apify_actor_ops import RouteExecutionResult
from src.services.apify_actor_runtime import ApifyActorRuntimeService
from src.services.apify_actor_source_execution import fetch_actorops_source_subscription


def _youtube_subscription(*, profile_id: str = "route-youtube"):
    return ApifySocialSubscriptionConfig(
        platform="youtube",
        kind="channel",
        target="https://www.youtube.com/feeds/videos.xml?channel_id=UCAbcdefghijklmnopqrstuv",
        profile_id=profile_id,
        source_id="source-youtube",
        fetch_limit=3,
    )


def test_registered_actorops_source_fetches_latest_items_without_feed_window(monkeypatch):
    class Ops:
        @staticmethod
        def get_route(_profile_id):
            return {"platform": "youtube", "target_type": "channel", "capability": "items"}

    captured = {}

    async def fetch(_self, **kwargs):
        captured["runtime"] = kwargs["runtime"]
        return RouteExecutionResult([], "valid_empty", "primary", ())

    monkeypatch.setattr(ApifyActorRuntimeService, "fetch", fetch)
    asyncio.run(
        fetch_actorops_source_subscription(
            subscription=_youtube_subscription(),
            since=datetime.now(timezone.utc) - timedelta(days=30),
            ops=Ops(),
            client_factory=object,
            job_id="job",
            frozen_snapshot=None,
        )
    )

    assert captured["runtime"].since_iso is None
    assert captured["runtime"].max_items == 3


def test_unregistered_actorops_source_is_rejected_before_client_creation():
    class Ops:
        @staticmethod
        def get_route(_profile_id):
            return {"platform": "youtube", "target_type": "profile", "capability": "items"}

    created_client = False

    def client_factory():
        nonlocal created_client
        created_client = True
        return object()

    with pytest.raises(SourceFetchError) as raised:
        asyncio.run(
            fetch_actorops_source_subscription(
                subscription=_youtube_subscription(profile_id="unregistered"),
                since=datetime.now(timezone.utc),
                ops=Ops(),
                client_factory=client_factory,
                job_id="job",
                frozen_snapshot=None,
            )
        )

    assert raised.value.code == "apify_actor_route_unregistered"
    assert created_client is False
