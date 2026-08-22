from __future__ import annotations

import asyncio
import hashlib
from types import SimpleNamespace

from src.services.actorops.publication import ActorOpsV2RoutedList
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
