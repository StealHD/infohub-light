import asyncio
from datetime import datetime, timezone
from types import SimpleNamespace

from src.models import SourceType
from src.services.apify_actor_manifest import (
    ActorRuntime,
    ActorTarget,
    parse_actor_manifest,
)
from src.services.apify_actor_ops import (
    RouteExecutionResult,
    RouteExecutionSnapshot,
    RouteSlotSnapshot,
)
from src.services.apify_actor_runtime import (
    ActorContentContext,
    ApifyActorRuntimeService,
    _client_failure_scope,
    actor_target_for_route,
)
from src.scrapers.apify_client import ApifyClientError


def _manifest():
    return parse_actor_manifest(
        {
            "version": 1,
            "actor_id": "vendor/youtube-actor",
            "build_number": "1.2.3",
            "input": {
                "startUrls": [{"url": {"$ref": "target.canonical_url"}}],
                "maxResults": {"$ref": "runtime.max_items"},
            },
            "output": {
                "native_id": {"pointers": ["/videoId"]},
                "url": {
                    "pointers": ["/url"],
                    "transforms": ["normalize_url"],
                },
                "published_at": {
                    "pointers": ["/published"],
                    "transforms": ["parse_datetime"],
                },
                "title": {"pointers": ["/title"]},
                "source_url": {
                    "pointers": ["/channelUrl"],
                    "transforms": ["normalize_url"],
                },
            },
            "semantics": {
                "identity": {
                    "output_field": "source_url",
                    "target_ref": "target.canonical_url",
                    "match": "url",
                },
                "url_host_allowlist": ["youtube.com"],
            },
        }
    )


class _FakeOps:
    def __init__(self, slot):
        self.slot = slot
        self.invocation_result = None

    async def execute_route(
        self,
        route_id,
        source_id,
        invoke,
        *,
        key_pool_generation=None,
        job_id=None,
    ):
        snapshot = RouteExecutionSnapshot(
            workspace_id="workspace",
            route_id=route_id,
            route_key="youtube/channel/items",
            route_generation=3,
            per_run_cap_usd=0.02,
            slots=(self.slot,),
            source_id=source_id,
            key_pool_generation=key_pool_generation,
        )
        result = await invoke(self.slot, snapshot)
        self.invocation_result = result
        return RouteExecutionResult(
            value=result.value,
            semantic_outcome=result.semantic_outcome,
            slot_name=self.slot.slot_name,
            attempt_ids=("attempt-1",),
        )


class _FakeClient:
    def __init__(self):
        self.kwargs = None

    async def run_actor_detailed(self, actor_id, actor_input, **kwargs):
        self.kwargs = {"actor_id": actor_id, "input": actor_input, **kwargs}
        return SimpleNamespace(
            items=[
                {
                    "videoId": "video-1",
                    "url": "https://www.youtube.com/watch?v=video-1",
                    "published": "2026-07-30T00:00:00Z",
                    "title": "Video",
                    "channelUrl": "https://www.youtube.com/@openai",
                }
            ],
            actual_charge_usd=0.01,
        )


def test_runtime_uses_frozen_build_cap_and_maps_content_without_actor_metadata():
    asyncio.run(_runtime_uses_frozen_build_cap_and_maps_content())


def test_runtime_separates_target_key_and_actor_failures():
    def scope(code):
        return _client_failure_scope(
            ApifyClientError(code, "safe", retryable=False)
        )

    assert scope("apify_actor_target_private") == "target"
    assert scope("apify_actor_no_such_account") == "target"
    assert scope("apify_key_quota_exhausted") == "key"
    assert scope("apify_actor_build_missing") == "actor"


def test_runtime_preserves_remote_charge_when_mapping_fails():
    manifest = _manifest()
    slot = RouteSlotSnapshot(
        slot_name="primary",
        candidate_id="candidate",
        revision_id="revision",
        actor_id="vendor/youtube-actor",
        publisher="vendor",
        build_id="build-id",
        build_number="1.2.3",
        manifest_hash="a" * 64,
        lifecycle="certified",
        candidate_state="closed",
        manifest=manifest,
    )

    class InvalidClient:
        async def run_actor_detailed(self, *_args, **_kwargs):
            return SimpleNamespace(
                items=[{"unexpected": "contract drift"}],
                actual_charge_usd=0.013,
            )

    ops = _FakeOps(slot)
    asyncio.run(
        ApifyActorRuntimeService(ops, InvalidClient()).fetch(
            route_id="route",
            source_id="source",
            target=ActorTarget(
                canonical_url="https://www.youtube.com/@openai",
                handle="openai",
            ),
            runtime=ActorRuntime(),
            content=ActorContentContext(
                platform="youtube",
                source_id="source",
                source_key="rss:youtube",
                source_name="OpenAI",
            ),
        )
    )

    assert ops.invocation_result.failure_scope == "actor"
    assert ops.invocation_result.cost_usd == 0.013


def test_actor_target_rejects_non_profile_routes_and_preserves_youtube_id_case():
    for platform, target in (
        ("x", "https://x.com/search?q=actor"),
        ("x", "https://x.com/openai/status/1"),
        ("instagram", "https://www.instagram.com/explore/"),
        ("instagram", "https://www.instagram.com/p/post-id/"),
    ):
        try:
            actor_target_for_route(platform, target)
        except Exception as exc:
            assert getattr(exc, "code", "") == "apify_actor_target_invalid"
        else:
            raise AssertionError(f"accepted non-profile target: {target}")

    channel_id = "UCAbcdefghijklmnopqrstuv"
    target = actor_target_for_route(
        "youtube",
        (
            "https://www.youtube.com/feeds/videos.xml?"
            f"channel_id={channel_id}"
        ),
    )
    assert target.native_id == channel_id


async def _runtime_uses_frozen_build_cap_and_maps_content():
    manifest = _manifest()
    slot = RouteSlotSnapshot(
        slot_name="primary",
        candidate_id="candidate",
        revision_id="revision",
        actor_id="vendor/youtube-actor",
        publisher="vendor",
        build_id="build-id",
        build_number="1.2.3",
        manifest_hash="a" * 64,
        lifecycle="certified",
        candidate_state="closed",
        manifest=manifest,
    )
    client = _FakeClient()
    runtime = ApifyActorRuntimeService(_FakeOps(slot), client)

    result = await runtime.fetch(
        route_id="route",
        source_id="source",
        target=ActorTarget(
            canonical_url="https://www.youtube.com/@openai",
            handle="openai",
        ),
        runtime=ActorRuntime(
            since_iso="2026-07-29T00:00:00Z",
            until_iso="2026-07-31T00:00:00Z",
        ),
        content=ActorContentContext(
            platform="youtube",
            source_id="source",
            source_key="rss:youtube",
            source_name="OpenAI",
        ),
        key_pool_generation=5,
        job_id="job",
    )

    assert client.kwargs["build_number"] == "1.2.3"
    assert client.kwargs["max_paid_dataset_items"] == 1
    assert client.kwargs["max_total_charge_usd"] == 0.02
    assert result.semantic_outcome == "valid_nonempty"
    item = result.value[0]
    assert item.source_type == SourceType.RSS
    assert item.metadata["source_id"] == "source"
    assert "actor_id" not in item.metadata
    assert "revision_id" not in item.metadata
