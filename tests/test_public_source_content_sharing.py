from __future__ import annotations

from datetime import datetime, timezone

import pytest

from src.models import ContentItem, SourceType
from src.services.feed_payload import serialize_feed_item
from src.services.feed_read import FeedReadService
from src.services.public_source_content_sharing import fan_out_public_source_content
from src.services.user_feed_store import UserFeedStore
from src.storage.service_store import ServiceStore


@pytest.fixture
def sharing_context(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
        role="member",
    )
    viewer = store.create_user(
        workspace_id=workspace["id"],
        username="viewer",
        password="viewer-password",
        role="viewer",
    )
    try:
        yield store, workspace, owner, member, viewer
    finally:
        store.close()


def _source(store, workspace_id: str, owner_id: str, *, scope: str = "workspace"):
    source_id = store.create_source(
        workspace_id=workspace_id,
        scope=scope,
        owner_user_id=owner_id if scope == "private" else None,
        source_type="rss",
        display_name="Shared source",
        config={"url": "https://example.com/shared.xml"},
        source_key=f"rss:https://example.com/shared-{scope}.xml",
    )
    return store.get_source(source_id)


def _save_owner_item(store, workspace, owner, source, subscription):
    item = ContentItem(
        id="rss:shared:1",
        source_type=SourceType.RSS,
        title="Canonical source title",
        url="https://example.com/shared/1",
        content="Canonical source content",
        published_at=datetime.now(timezone.utc),
        metadata={
            "title_zh": "Owner-only translated title",
            "source_id": source["id"],
            "subscription_id": subscription["id"],
        },
    )
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="owner-source-fetch",
        payload={
            "schema_version": 2,
            "generated_at": datetime.now(timezone.utc).isoformat(),
            "items": [serialize_feed_item(item, featured_threshold=8.0)],
        },
    )
    return item


def test_public_source_fanout_reprojects_only_active_non_viewer_subscribers(
    sharing_context,
):
    store, workspace, owner, member, viewer = sharing_context
    source = _source(store, workspace["id"], owner["id"])
    owner_subscription = store.create_subscription(
        user_id=owner["id"],
        source_id=source["id"],
        override_channel="Owner channel",
        personal_tags=["Owner tag"],
    )
    member_subscription = store.create_subscription(
        user_id=member["id"],
        source_id=source["id"],
        override_channel="Member channel",
        personal_tags=["Member tag"],
        analysis_mode="personal_only",
    )
    store.create_subscription(user_id=viewer["id"], source_id=source["id"])
    item = _save_owner_item(
        store, workspace, owner, source, owner_subscription
    )

    result = fan_out_public_source_content(
        store,
        workspace_id=workspace["id"],
        source_id=source["id"],
    )

    assert result == {"projected_user_count": 2, "reused_item_count": 2}
    member_feed = FeedReadService(store).latest_feed(
        workspace_id=workspace["id"], user_id=member["id"]
    )
    member_item = member_feed["items"][0]
    assert member_item["id"] == item.id
    assert member_item["title"] == item.title
    assert member_item["title"] != "Owner-only translated title"
    assert member_item["channel"] == "Member channel"
    assert member_item["personal_tags"] == ["Member tag"]
    assert member_item["analysis_mode"] == "personal_only"
    assert UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"], user_id=viewer["id"]
    ) is None
    assert member_item["subscription_id"] == member_subscription["id"]


def test_private_source_is_never_fanned_out(sharing_context):
    store, workspace, owner, member, _viewer = sharing_context
    source = _source(store, workspace["id"], owner["id"], scope="private")
    owner_subscription = store.create_subscription(
        user_id=owner["id"], source_id=source["id"]
    )
    store.create_subscription(user_id=member["id"], source_id=source["id"])
    _save_owner_item(store, workspace, owner, source, owner_subscription)

    assert fan_out_public_source_content(
        store,
        workspace_id=workspace["id"],
        source_id=source["id"],
    ) == {"projected_user_count": 0, "reused_item_count": 0}
    assert UserFeedStore(store).latest_snapshot(
        workspace_id=workspace["id"], user_id=member["id"]
    ) is None
