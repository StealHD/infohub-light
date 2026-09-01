from __future__ import annotations

from datetime import datetime, timedelta, timezone
import json

import pytest

from src.models import ContentItem, SourceType
from src.services.feed_payload import serialize_feed_item
from src.services.feed_read import FeedReadService
from src.services.subscription_mutation import (
    SubscriptionActor,
    SubscriptionMutationService,
)
from src.services.user_feed_store import UserFeedStore
from src.storage.service_store import ServiceStore


@pytest.fixture
def reuse_context(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    member = store.create_user(
        workspace_id=workspace["id"],
        username="new-member",
        password="member-password",
        role="member",
    )
    try:
        yield store, workspace, member
    finally:
        store.close()


def _shared_source(store, workspace_id: str, *, enabled: bool = True):
    source_id = store.create_source(
        workspace_id=workspace_id,
        scope="workspace",
        owner_user_id=None,
        source_type="rss",
        display_name="Existing YouTube source",
        config={
            "url": (
                "https://www.youtube.com/feeds/videos.xml"
                "?channel_id=UC1234567890123456789012"
            )
        },
        source_key="rss:youtube:UC1234567890123456789012",
        enabled=enabled,
    )
    return store.get_source(source_id)


def _insert_shared_source_cache(
    store: ServiceStore,
    *,
    workspace_id: str,
    source_id: str,
    item: ContentItem,
) -> None:
    now = datetime.now(timezone.utc)
    snapshot_id = "acq_existing_source"
    connection = store.connect()
    connection.execute(
        """
        INSERT INTO source_content_snapshots (
            id, acquisition_key, workspace_id, source_id, config_fingerprint,
            isolation_scope, window_hours, generated_at, fresh_until,
            item_count, producer_job_id, diagnostics_json, created_at
        ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, NULL, '{}', ?)
        """,
        (
            snapshot_id,
            "existing-source-acquisition",
            workspace_id,
            source_id,
            "existing-source-fingerprint",
            f"workspace:{workspace_id}",
            168,
            now.isoformat(),
            (now + timedelta(minutes=5)).isoformat(),
            1,
            now.isoformat(),
        ),
    )
    connection.execute(
        """
        INSERT INTO source_content_items (
            id, snapshot_id, canonical_key, source_item_id, position,
            item_json, created_at
        ) VALUES (?, ?, ?, ?, 0, ?, ?)
        """,
        (
            "aci_existing_source",
            snapshot_id,
            str(item.url),
            item.id,
            json.dumps(item.model_dump(mode="json"), ensure_ascii=False),
            now.isoformat(),
        ),
    )
    connection.commit()


@pytest.mark.parametrize("source_enabled", [True, False])
def test_new_subscriber_reuses_shared_acquisition_cache_without_user_donor(
    reuse_context,
    source_enabled,
):
    store, workspace, member = reuse_context
    source = _shared_source(store, workspace["id"], enabled=source_enabled)
    published_at = datetime.now(timezone.utc) - timedelta(days=2)
    item = ContentItem(
        id="youtube:existing-source:video-1",
        source_type=SourceType.RSS,
        title="Canonical video title",
        url="https://www.youtube.com/watch?v=video-1",
        content="Existing source excerpt",
        author="Existing channel",
        published_at=published_at,
    )
    _insert_shared_source_cache(
        store,
        workspace_id=workspace["id"],
        source_id=source["id"],
        item=item,
    )

    result = SubscriptionMutationService(store).rest_create_subscription(
        SubscriptionActor.from_user(member),
        source_id=source["id"],
        values={},
        allow_disabled_source=not source_enabled,
    )

    assert result["reused_item_count"] == 1
    latest = FeedReadService(store).latest_feed(
        workspace_id=workspace["id"],
        user_id=member["id"],
    )
    assert [entry["id"] for entry in latest["items"]] == [item.id]
    assert latest["items"][0]["title"] == item.title
    assert latest["items"][0]["subscription_id"] == result["id"]


def test_new_subscriber_reuses_legacy_row_with_proven_native_title(reuse_context):
    store, workspace, member = reuse_context
    source = _shared_source(store, workspace["id"])
    owner = store.get_user_by_username("owner")
    owner_subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source["id"],
    )
    item = ContentItem(
        id="youtube:legacy-native:video-1",
        source_type=SourceType.RSS,
        title="Legacy canonical title",
        url="https://www.youtube.com/watch?v=legacy-video-1",
        content="Legacy source excerpt",
        published_at=datetime.now(timezone.utc) - timedelta(days=1),
        metadata={
            "source_id": source["id"],
            "subscription_id": owner_subscription["id"],
        },
    )
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [serialize_feed_item(item, featured_threshold=8.0)],
        },
    )
    store.connect().execute(
        """UPDATE user_content_items SET source_native_title = NULL
           WHERE workspace_id = ? AND user_id = ? AND article_id = ?""",
        (workspace["id"], owner["id"], item.id),
    )
    store.connect().commit()

    result = SubscriptionMutationService(store).rest_create_subscription(
        SubscriptionActor.from_user(member),
        source_id=source["id"],
        values={},
    )

    assert result["reused_item_count"] == 1
    latest = FeedReadService(store).latest_feed(
        workspace_id=workspace["id"],
        user_id=member["id"],
    )
    assert latest["items"][0]["title"] == item.title


def test_new_subscriber_prioritizes_shared_cache_before_stable_donor(
    reuse_context,
):
    store, workspace, member = reuse_context
    source = _shared_source(store, workspace["id"])
    owner = store.get_user_by_username("owner")
    owner_subscription = store.create_subscription(
        user_id=owner["id"], source_id=source["id"]
    )
    donor = ContentItem(
        id="youtube:donor:video-1",
        source_type=SourceType.RSS,
        title="Earlier stable donor",
        url="https://www.youtube.com/watch?v=donor-video-1",
        published_at=datetime.now(timezone.utc) - timedelta(days=1),
        metadata={
            "source_id": source["id"],
            "subscription_id": owner_subscription["id"],
        },
    )
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [serialize_feed_item(donor, featured_threshold=8.0)],
        },
    )
    cached = ContentItem(
        id="youtube:cache:video-2",
        source_type=SourceType.RSS,
        title="Latest neutral cache item",
        url="https://www.youtube.com/watch?v=cache-video-2",
        published_at=datetime.now(timezone.utc),
    )
    _insert_shared_source_cache(
        store,
        workspace_id=workspace["id"],
        source_id=source["id"],
        item=cached,
    )

    result = SubscriptionMutationService(store).rest_create_subscription(
        SubscriptionActor.from_user(member), source_id=source["id"], values={}
    )

    assert result["reused_item_count"] == 2
    snapshot = UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"], user_id=member["id"]
    )
    assert [entry["id"] for entry in snapshot["payload"]["items"]] == [
        cached.id,
        donor.id,
    ]
