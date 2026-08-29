from __future__ import annotations

import asyncio
import hashlib
import json
from types import SimpleNamespace

from src.services.actorops.publication import (
    ActorOpsV2RoutedList,
    merge_private_source_avatar_hints,
    source_avatar_url_from_items,
)
from src.services.feed_payload import build_feed_payload
from src.services.feed_run import FeedRunResult, SourceOutcome, safe_run_diagnostics
from src.services.media_cache import MediaCacheService
from src.services.source_avatar import SourceAvatarService
from src.services.source_acquisition import SourceAcquisitionCoordinator
from tests.test_source_acquisition import (
    _content_item,
    _ready_v2_binding,
    _store,
)


def test_v2_route_generation_accepts_exact_publication_proof(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Shared X",
        config={
            "platform": "x",
            "kind": "profile",
            "target": "OpenAI",
            "fetch_limit": 1,
        },
        source_key="apify:x:profile:openai-proven-generation",
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    route_id, binding = _ready_v2_binding(
        store, workspace["id"], source_id
    )
    projection = SimpleNamespace(
        source_id=source_id,
        subscription_id=subscription["id"],
        source_key="apify:x:profile:openai-proven-generation",
        source_display_name="Shared X",
        catalog_source_type="apify_social",
        source_priority=0,
        analysis_mode="full",
        channel="AI",
        category="AI",
        topics=[],
        tags=[],
        personal_tags=[],
    )
    coordinator = SourceAcquisitionCoordinator(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-apify-proven-route",
    )
    old_context = coordinator._context(projection, window_hours=24)

    async def fetch_from_backup():
        store.connect().execute(
            """UPDATE actor_routes_v2
               SET generation=generation+1,
                   updated_at='2026-07-29T00:00:00+00:00'
               WHERE workspace_id=? AND route_id=?""",
            (workspace["id"], route_id),
        )
        store.connect().commit()
        return ActorOpsV2RoutedList(
            [_content_item(suffix="apify-proven-route")],
            {
                "version": 2,
                "workspace_id": str(workspace["id"]),
                "route_id": route_id,
                "source_id": source_id,
                "target_fingerprint": binding.target_fingerprint,
                "binding_version": binding.binding_version,
                "candidate_id": None,
                "candidate_generation": None,
                "latest_published_at": "2026-07-29T00:00:00+00:00",
                "latest_item_id_hash": hashlib.sha256(
                    b"publication-item"
                ).hexdigest(),
            },
        )

    items = asyncio.run(
        coordinator.acquire(
            source=projection,
            provider="apify_social",
            window_hours=24,
            fetch=fetch_from_backup,
        )
    )

    new_context = coordinator._context(projection, window_hours=24)
    snapshot = store.connect().execute(
        """SELECT acquisition_key, config_fingerprint
           FROM source_content_snapshots WHERE source_id=?""",
        (source_id,),
    ).fetchone()
    assert [item.id for item in items] == [
        _content_item(suffix="apify-proven-route").id
    ]
    assert new_context.actor_route_generation != old_context.actor_route_generation
    assert snapshot["acquisition_key"] == new_context.acquisition_key
    assert snapshot["config_fingerprint"] == new_context.config_fingerprint
    assert items._actorops_v2_publication_proof["route_id"] == route_id

    cached = asyncio.run(
        coordinator.acquire(
            source=projection,
            provider="apify_social",
            window_hours=24,
            fetch=fetch_from_backup,
        )
    )
    assert cached._actorops_v2_publication_proof == (
        items._actorops_v2_publication_proof
    )


def test_cache_hit_replays_private_instagram_avatar_after_first_cache_failure(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Shared Instagram",
        config={
            "platform": "instagram",
            "kind": "profile",
            "target": "openai",
            "fetch_limit": 1,
        },
        source_key="apify:instagram:profile:openai-avatar-retry",
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    route_id, binding = _ready_v2_binding(
        store, workspace["id"], source_id
    )
    projection = SimpleNamespace(
        source_id=source_id,
        subscription_id=subscription["id"],
        source_key="apify:instagram:profile:openai-avatar-retry",
        source_display_name="Shared Instagram",
        catalog_source_type="apify_social",
        source_priority=0,
        analysis_mode="full",
        channel="AI",
        category="AI",
        topics=[],
        tags=[],
        personal_tags=[],
        platform="instagram",
        kind="profile",
    )
    proof = {
        "version": 2,
        "workspace_id": str(workspace["id"]),
        "route_id": route_id,
        "source_id": source_id,
        "target_fingerprint": binding.target_fingerprint,
        "binding_version": binding.binding_version,
        "candidate_id": None,
        "candidate_generation": None,
        "latest_published_at": "2026-08-27T00:00:00+00:00",
        "latest_item_id_hash": hashlib.sha256(b"avatar-item").hexdigest(),
    }
    avatar_url = "https://cdninstagram.com/openai-avatar.jpg?private=sidecar"
    upstream_calls = 0

    async def fetch():
        nonlocal upstream_calls
        upstream_calls += 1
        return ActorOpsV2RoutedList(
            [_content_item(suffix="instagram-avatar")],
            proof,
            source_avatar_url=avatar_url,
        )

    def acquire(job_id: str):
        return asyncio.run(
            SourceAcquisitionCoordinator(
                store,
                workspace_id=workspace["id"],
                user_id=owner["id"],
                job_id=job_id,
            ).acquire(
                source=projection,
                provider="apify_social",
                window_hours=24,
                fetch=fetch,
            )
        )

    def run_result(items, run_id: str) -> FeedRunResult:
        hints = merge_private_source_avatar_hints((), items, projection)
        return FeedRunResult(
            run_id=run_id,
            status="succeeded",
            started_at="2026-08-27T00:00:00+00:00",
            finished_at="2026-08-27T00:00:01+00:00",
            items=tuple(items),
            source_outcomes=(SourceOutcome(
                source_id=source_id,
                subscription_id=subscription["id"],
                source_key=projection.source_key,
                analysis_mode="full",
                status="succeeded",
                fetched_count=len(items),
                avatar_hints=hints,
            ),),
        )

    image_fetches = 0

    def fetch_image(_url: str):
        nonlocal image_fetches
        image_fetches += 1
        if image_fetches == 1:
            return b"", "image/png"
        return b"\x89PNG\r\n\x1a\nactorops-avatar", "image/png"

    media = MediaCacheService(
        store, data_dir=tmp_path, fetch_image=fetch_image
    )
    avatars = SourceAvatarService(
        store, data_dir=str(tmp_path), media_cache=media
    )
    first = acquire("job-avatar-upstream")
    first_result = run_result(first, "run-avatar-upstream")
    first_refresh = avatars.refresh_run_result(
        workspace_id=workspace["id"], result=first_result
    )
    assert first_refresh[0].status == "failed"
    assert media.avatar_for_source(
        workspace_id=workspace["id"], source_id=source_id
    ) is None

    second = acquire("job-avatar-cache-hit")
    second_result = run_result(second, "run-avatar-cache-hit")
    second_refresh = avatars.refresh_run_result(
        workspace_id=workspace["id"], result=second_result
    )
    avatar = media.avatar_for_source(
        workspace_id=workspace["id"], source_id=source_id
    )

    assert upstream_calls == 1
    assert source_avatar_url_from_items(second) == avatar_url
    assert all(
        avatar_url not in json.dumps(item.metadata, sort_keys=True)
        for item in (*first, *second)
    )
    assert second_refresh[0].status == "stored"
    assert image_fetches == 2
    assert avatar is not None and avatar["remote_url"] == avatar_url
    snapshot = store.connect().execute(
        "SELECT diagnostics_json FROM source_content_snapshots WHERE source_id=?",
        (source_id,),
    ).fetchone()
    assert json.loads(snapshot["diagnostics_json"])["actor_private"] == {
        "source_avatar_url": avatar_url
    }
    item_json = store.connect().execute(
        "SELECT item_json FROM source_content_items LIMIT 1"
    ).fetchone()["item_json"]
    assert avatar_url not in item_json
    assert avatar_url not in json.dumps(
        safe_run_diagnostics(second_result, item_count=len(second)),
        sort_keys=True,
    )

    media.cache_items(
        workspace_id=workspace["id"], user_id=owner["id"], items=list(second)
    )
    payload = build_feed_payload(
        all_items=list(second), date="2026-08-27", total_fetched=len(second)
    )
    serialized = json.dumps(payload, sort_keys=True)
    assert payload["items"][0]["presentation"]["source"]["avatar_url"] == (
        f"/api/media/{avatar['id']}"
    )
    assert avatar_url not in serialized
