"""Bilibili schema adaptation, target isolation and main/standby execution."""

import asyncio
import hashlib
import json
from dataclasses import replace
from datetime import datetime, timezone

import pytest

from src.services.actorops.adapters import build_default_registry
from src.services.actorops.domain import CandidateLifecycle, FailureClass, RouteKey
from src.services.actorops.errors import ActorOpsRuntimeError
from src.services.actorops.ports import ActorManifest, DiscoveryRevision, FetchWindow
from src.services.actorops.discovery_manifest import validate_schema_proven_manifest
from src.services.actorops.binding_service import ActorOpsBindingService
from src.services.actorops.repository import ActorOpsRepository
from src.services.actorops.runtime import ActorOpsRuntime
from src.services.actorops.service import ActorOpsV2Service, _retain_latest
from src.services.apify_actor_manifest import ActorManifestError, actor_manifest_hash
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from tests.test_actorops_v2_runtime import _Remote


KEY = RouteKey("bilibili", "profile", "items")
UID = "39627524"
URL = "https://www.bilibili.com/video/BV1gsXHYDEU4"
WINDOW = FetchWindow(3, datetime(2026, 10, 1, tzinfo=timezone.utc), None)


def revision(style="nested", actor="publisher/bili-videos"):
    properties = {
        "bvid": {"type": "string"}, "url": {"type": "string"},
        "pubdate": {"type": "integer"}, "title": {"type": "string"},
        "desc": {"type": "string"}, "pic": {"type": "string"},
        "owner": {"type": "object", "properties": {
            "mid": {"type": "integer"}, "name": {"type": "string"}, "face": {"type": "string"},
        }},
        "stat": {"type": "object", "properties": {"view": {"type": "integer"}}},
    }
    inputs = {"uid": {"type": "string"}, "maxItems": {"type": "integer"}}
    if style == "flat":
        properties = {name: {"type": "string"} for name in (
            "videoId", "videoUrl", "publishedAt", "title", "description",
            "creatorId", "creatorName", "creatorAvatar", "cover",
        )}
        inputs = {"creatorUrls": {"type": "array", "items": {"type": "string"}}, "maxResults": {"type": "integer"}}
    return DiscoveryRevision(
        actor_id=actor, publisher=actor.split("/")[0], build_id="build",
        build_number="1.0.0", price_per_run_usd=0.001,
        input_schema={"type": "object", "properties": inputs},
        output_schema={"type": "object", "properties": properties},
    )


def manifest(style="nested", actor="publisher/bili-videos"):
    mapped = build_default_registry().require(KEY).map_discovery_manifest(revision(style, actor))
    assert mapped.manifest_json, mapped.rejection_code
    proven, error = validate_schema_proven_manifest(revision(style, actor), mapped)
    assert proven, error
    return ActorManifest(actor, "build", "1.0.0", mapped.manifest_json, actor_manifest_hash(mapped.manifest_json))


def row(uid=UID):
    return {
        "bvid": "BV1gsXHYDEU4", "url": URL, "pubdate": 1791504000,
        "title": "<b>Video</b>", "desc": "Description", "pic": "https://i0.hdslb.com/bfs/archive/cover.jpg",
        "owner": {"mid": int(uid), "name": "UP", "face": "https://i0.hdslb.com/bfs/face/avatar.jpg"},
        "stat": {"view": 42},
    }


@pytest.mark.parametrize("target", [UID, int(UID), f"https://space.bilibili.com/{UID}/"])
def test_target_is_canonical_and_idempotent(target):
    adapter = build_default_registry().require(KEY)
    first = adapter.normalize_target({"target": target})
    assert first == adapter.normalize_target({"target": first.canonical_url})
    assert first.native_id == UID


@pytest.mark.parametrize("target", [True, "0", "-1", "01", "https://evil.example/1", "https://user@space.bilibili.com/1", "https://space.bilibili.com/1?x=1", "https://space.bilibili.com/1/video"])
def test_target_rejects_unsafe_or_non_uid_values(target):
    with pytest.raises(ValueError):
        build_default_registry().require(KEY).normalize_target({"target": target})


@pytest.mark.parametrize("style", ["nested", "flat"])
def test_distinct_actor_shapes_keep_the_legacy_rss_video_id(style):
    adapter = build_default_registry().require(KEY)
    target = adapter.normalize_target({"target": UID})
    value = row() if style == "nested" else {
        "videoId": "BV1gsXHYDEU4", "videoUrl": URL + "?from=search", "publishedAt": "2026-10-09T00:00:00Z",
        "title": "Video", "description": "Description", "creatorId": UID, "creatorName": "UP",
        "creatorAvatar": "https://i0.hdslb.com/bfs/face/avatar.jpg", "cover": "https://i0.hdslb.com/bfs/archive/cover.jpg",
    }
    batch = adapter.validate_output((value,), target, manifest(style), WINDOW)
    item = batch.items[0]
    feed_hash = hashlib.sha256(f"rss:rsshub:bilibili:user_video:{UID}".encode()).hexdigest()[:16]
    entry_hash = hashlib.sha256(URL.encode()).hexdigest()[:16]
    assert item.id == f"rss:{feed_hash}:{entry_hash}"
    assert item.title == "Video"
    assert item.content == "Description"
    assert item.url == URL
    assert item.author == "UP"
    assert item.metadata["image_url"].endswith("cover.jpg")
    assert batch.source_avatar_url.endswith("avatar.jpg")
    if style == "nested":
        assert item.metadata["engagement"]["views"] == 42
    rendered = adapter.build_actor_input(target, manifest(style), WINDOW)
    assert rendered == ({"uid": UID, "maxItems": 3} if style == "nested" else {
        "creatorUrls": [f"https://space.bilibili.com/{UID}"], "maxResults": 3,
    })


def test_cross_owner_and_non_video_content_fail_closed():
    adapter = build_default_registry().require(KEY)
    target = adapter.normalize_target({"target": UID})
    with pytest.raises(ActorManifestError):
        adapter.validate_output((row("123"),), target, manifest(), WINDOW)
    with pytest.raises(ValueError):
        adapter.validate_output(({**row(), "url": "https://www.bilibili.com/read/cv123"},), target, manifest(), WINDOW)


@pytest.mark.parametrize("video_url", ["https://www.bilibili.com/video/BV17x411w7KC", "https://www.bilibili.com/video/av170001"])
def test_early_video_keeps_rsshub_av_identity(video_url):
    adapter = build_default_registry().require(KEY)
    old = {**row(), "url": video_url, "bvid": "BV17x411w7KC", "pubdate": 1589990400}
    window = replace(WINDOW, since=datetime(2000, 1, 1, tzinfo=timezone.utc))
    item = adapter.validate_output((old,), adapter.normalize_target({"target": UID}), manifest(), window).items[0]
    assert item.url == "https://www.bilibili.com/video/av170001"
    expected = hashlib.sha256(item.url.encode()).hexdigest()[:16]
    assert item.id.endswith(":" + expected)


def test_modern_av_actor_link_keeps_rsshub_bv_identity():
    adapter = build_default_registry().require(KEY)
    value = {**row(), "url": "https://www.bilibili.com/video/av170001"}
    item = adapter.validate_output((value,), adapter.normalize_target({"target": UID}), manifest(), WINDOW).items[0]
    assert item.url == "https://www.bilibili.com/video/BV17x411w7KC"


def test_limits_window_empty_and_no_native_fallback():
    adapter = build_default_registry().require(KEY)
    target = adapter.normalize_target({"target": UID})
    old = {**row(), "pubdate": 1767225600}
    batch = adapter.validate_output((old,), target, manifest(), WINDOW)
    assert batch.items == ()
    assert batch.latest_item_id == "BV1gsXHYDEU4"
    rows = tuple({**row(), "bvid": f"BV1gsXHYDEU{i}", "url": URL[:-1] + str(i)} for i in range(3))
    assert len(adapter.validate_output(rows, target, manifest(), replace(WINDOW, max_items=1)).items) == 1
    assert asyncio.run(adapter.fetch_native_fallback(target, WINDOW)).supported is False
    assert adapter.validate_output((), target, manifest(), WINDOW).items == ()


def test_source_projection_preserves_raw_feed_identity_and_latest_retention():
    adapter = build_default_registry().require(KEY)
    item = adapter.validate_output((row(),), adapter.normalize_target({"target": UID}), manifest(), WINDOW).items[0]
    from src.models import ApifySocialSubscriptionConfig
    sub = ApifySocialSubscriptionConfig(
        profile_id="route-bili", platform="bilibili", kind="profile", target=UID,
        source_id="source", source_key="legacy-key", rss_identity_url="http://rsshub:1200/bilibili/user/video/39627524/1",
    )
    projected = ActorOpsV2Service._project_items((item,), sub, "actor")
    assert projected[0].id.startswith("rss:rsshub:1200_bilibili_user_video_39627524_1:")
    retained = _retain_latest(projected, datetime(2026, 10, 10, tzinfo=timezone.utc))
    assert retained[0].metadata["retention_policy"] == "latest_per_source"


class BilibiliRemote(_Remote):
    async def execute(self, request, events):
        result = await super().execute(request, events)
        outcome = result.rows[0]["semantic"]
        rows = (row("123" if outcome == "wrong_owner" else UID),)
        self.datasets[result.dataset_id] = rows
        return replace(result, rows=rows)


def _runtime(tmp_path, outcomes):
    store = ServiceStore(tmp_path)
    store.initialize()
    repo = ActorOpsRepository(store.connect(), DEFAULT_WORKSPACE_ID)
    route_id = store.connect().execute("SELECT route_id FROM actor_routes_v2 WHERE platform='bilibili'").fetchone()[0]
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace", owner_user_id=None,
        source_type="rss", display_name="UP", config={"provider": "rsshub", "site": "bilibili", "route_key": "user_video", "params": {"uid": UID}},
    )
    with repo.transaction():
        for index in range(2):
            spec = manifest(actor=f"publisher{index}/bili")
            repo.create_candidate(
                candidate_id=f"candidate-{index}", route_id=route_id, actor_id=spec.actor_id,
                publisher=f"publisher{index}", build_id=spec.build_id, build_number=spec.build_number,
                manifest_json=spec.manifest_json, manifest_hash=spec.manifest_hash,
                input_schema_hash="a" * 64, output_schema_hash="b" * 64, lifecycle=CandidateLifecycle.CERTIFIED,
            )
            store.connect().execute("UPDATE actor_candidates_v2 SET assignment_role=?, priority=? WHERE candidate_id=?",
                                    ("active" if index == 0 else "standby", index, f"candidate-{index}"))
        store.connect().execute("UPDATE actor_routes_v2 SET runtime_mode='active' WHERE route_id=?", (route_id,))
    service = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    binding = service.ensure(source_id)
    service.verify(source_id, expected_binding_version=binding.binding_version, expected_target_fingerprint=binding.target_fingerprint)
    remote = BilibiliRemote(outcomes)
    runtime = ActorOpsRuntime(repo, build_default_registry(), remote)
    return store, runtime, remote, {
        "route_id": route_id, "source_id": source_id,
        "source_config": {"target": f"https://space.bilibili.com/{UID}"},
        "window": WINDOW, "logical_job_id": "test-bilibili",
    }


def test_actual_bilibili_adapter_switches_from_wrong_owner_to_standby(tmp_path):
    store, runtime, remote, args = _runtime(tmp_path, ["wrong_owner", "valid"])
    result = asyncio.run(runtime.fetch(**args))
    assert result.items[0].url == URL
    assert [request.candidate_id for request in remote.requests] == ["candidate-0", "candidate-1"]
    store.close()


def test_unknown_start_does_not_launch_bilibili_standby(tmp_path):
    error = ActorOpsRuntimeError("actorops_remote_unknown", failure_class=FailureClass.REMOTE_UNKNOWN)
    store, runtime, remote, args = _runtime(tmp_path, [error, "valid"])
    with pytest.raises(ActorOpsRuntimeError) as caught:
        asyncio.run(runtime.fetch(**args))
    assert caught.value.failure_class is FailureClass.REMOTE_UNKNOWN
    assert len(remote.requests) == 1
    store.close()


@pytest.mark.parametrize("input_field,mode", [("userIds", "user_videos"), ("userUrls", "user-videos")])
def test_multi_mode_actor_uses_only_up_uploads_with_schema_proven_limits(input_field, mode):
    adapter = build_default_registry().require(KEY)
    base = revision()
    schema = {"type": "object", "properties": {
        input_field: {"type": "array", "items": {"type": "string"}},
        "mode": {"type": "string", "enum": ["search", "comments", mode], "default": "search"},
        "maxItems": {"type": "integer", "maximum": 100},
    }, "required": ["mode", input_field]}
    revised = replace(base, input_schema=schema)
    mapping = adapter.map_discovery_manifest(revised)
    proven, error = validate_schema_proven_manifest(revised, mapping)
    assert proven, error
    exact = ActorManifest(base.actor_id, "build", "1.0.0", proven, actor_manifest_hash(proven))
    rendered = adapter.build_actor_input(adapter.normalize_target({"target": UID}), exact, WINDOW)
    assert rendered == {input_field: [UID if input_field == "userIds" else f"https://space.bilibili.com/{UID}"],
                        "mode": mode, "maxItems": 3}
