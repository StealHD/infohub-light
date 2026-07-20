import pytest

from src.services.user_feed_store import UserFeedStore
from src.services.user_item_state import UserItemStateStore
from src.storage.service_store import ServiceStore


def _store_with_visible_items(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    alice = store.create_user(
        workspace_id=workspace["id"],
        username="alice",
        password="alice-password",
        role="member",
    )
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_owner",
        payload={
            "generated_at": "2026-07-09T12:00:00+08:00",
            "items": [
                {"id": "rss:item:1", "title": "Visible item"},
                {"id": "rss:item:2", "title": "Second item"},
            ],
        },
    )
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=alice["id"],
        job_id="job_alice",
        payload={
            "generated_at": "2026-07-09T12:00:00+08:00",
            "items": [{"id": "rss:item:1", "title": "Alice visible item"}],
        },
    )
    return store, workspace, owner, alice


def test_user_item_state_upserts_toggles_and_isolates_users(tmp_path, monkeypatch):
    store, workspace, owner, alice = _store_with_visible_items(tmp_path, monkeypatch)
    states = UserItemStateStore(store)

    updated = states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:item:1",
        is_read=True,
        is_saved=True,
        is_later=True,
    )
    assert updated["is_read"] is True
    assert updated["is_saved"] is True
    assert updated["is_later"] is True
    assert updated["read_at"]
    assert updated["saved_at"]
    assert updated["later_at"]

    cleared = states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:item:1",
        is_saved=False,
        dismissed=True,
    )
    assert cleared["is_saved"] is False
    assert cleared["saved_at"] is None
    assert cleared["dismissed"] is True
    assert cleared["dismissed_at"]

    owner_states = states.get_states(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_ids=["rss:item:1", "rss:item:2"],
    )
    alice_state = states.get_state(
        workspace_id=workspace["id"],
        user_id=alice["id"],
        article_id="rss:item:1",
    )

    assert owner_states["rss:item:1"]["is_read"] is True
    assert owner_states["rss:item:2"]["is_read"] is False
    assert alice_state["is_read"] is False
    assert alice_state["is_saved"] is False


def test_user_item_state_counts_current_user_flags(tmp_path, monkeypatch):
    store, workspace, owner, alice = _store_with_visible_items(tmp_path, monkeypatch)
    states = UserItemStateStore(store)

    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:item:1",
        is_read=True,
        is_saved=True,
    )
    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:item:2",
        is_later=True,
        dismissed=True,
    )
    states.update_state(
        workspace_id=workspace["id"],
        user_id=alice["id"],
        article_id="rss:item:1",
        is_read=True,
        is_saved=True,
        is_later=True,
        dismissed=True,
    )

    assert states.count_flags(workspace_id=workspace["id"], user_id=owner["id"]) == {
        "read_count": 1,
        "saved_count": 1,
        "later_count": 1,
        "dismissed_count": 1,
    }


def test_user_item_feedback_validates_types_and_records_events(tmp_path, monkeypatch):
    store, workspace, owner, _alice = _store_with_visible_items(tmp_path, monkeypatch)
    states = UserItemStateStore(store)

    event = states.record_feedback(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:item:1",
        feedback_type="more_like_this",
        reason="useful source",
        metadata={"surface": "reader"},
    )

    assert event["feedback_type"] == "more_like_this"
    assert event["reason"] == "useful source"
    assert event["metadata"] == {"surface": "reader"}

    with pytest.raises(ValueError, match="feedback_type"):
        states.record_feedback(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            article_id="rss:item:1",
            feedback_type="bad_signal",
        )


def test_user_item_state_visibility_uses_user_feed_items(tmp_path, monkeypatch):
    store, workspace, owner, alice = _store_with_visible_items(tmp_path, monkeypatch)
    states = UserItemStateStore(store)

    assert states.is_visible(workspace_id=workspace["id"], user_id=owner["id"], article_id="rss:item:2")
    assert not states.is_visible(workspace_id=workspace["id"], user_id=alice["id"], article_id="rss:item:2")
