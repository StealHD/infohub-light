import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

import pytest

from src.models import ApifySocialSubscriptionConfig
from src.scrapers.base import SourceFetchError
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


def test_registered_actorops_source_forwards_only_v2_execution_snapshot():
    captured = {}

    class Ops:
        async def fetch_subscription(self, **kwargs):
            captured.update(kwargs)
            return ["v2-result"]

    snapshot = SimpleNamespace(actorops_version=2)
    since = datetime.now(timezone.utc)
    public_client = object()
    result = asyncio.run(
        fetch_actorops_source_subscription(
            subscription=_youtube_subscription(),
            since=since,
            ops=Ops(),
            client_factory=object,
            job_id="job",
            frozen_snapshot=snapshot,
            public_http_client=public_client,
        )
    )

    assert result == ["v2-result"]
    assert captured["snapshot"] is snapshot
    assert captured["since"] is since
    assert captured["public_http_client"] is public_client


def test_legacy_actorops_snapshot_is_rejected_before_client_creation():
    class Ops:
        async def fetch_subscription(self, **_kwargs):
            raise AssertionError("legacy snapshot must not reach ActorOps")

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
                frozen_snapshot=SimpleNamespace(actorops_version=1),
            )
        )

    assert raised.value.code == "actorops_v2_snapshot_required"
    assert created_client is False
