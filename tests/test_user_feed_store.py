from src.services.user_feed_store import UserFeedStore
from src.storage.service_store import ServiceStore


def _store_with_users(tmp_path, monkeypatch):
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
    return store, workspace, owner, alice


def test_user_feed_store_saves_latest_snapshot_and_items(tmp_path, monkeypatch):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)
    payload = {
        "generated_at": "2026-07-09T10:00:00+08:00",
        "items": [
            {
                "id": "rss:item:1",
                "source": "Example RSS",
                "source_type": "rss",
                "channel": "AI",
                "topics": ["Agent", "Codex"],
                "score": 8.5,
                "published_at": "2026-07-08T00:00:00+00:00",
            },
            {
                "id": "github:item:2",
                "source_type": "github",
                "category": "产品机会",
                "tags": ["Launch"],
                "score": None,
                "published_at": "2026-07-07T00:00:00+00:00",
            },
        ],
    }

    snapshot = feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_refresh",
        payload=payload,
    )
    latest = feeds.latest_snapshot(workspace_id=workspace["id"], user_id=owner["id"])
    history = feeds.snapshot_history(workspace_id=workspace["id"], user_id=owner["id"])
    visible_ids = feeds.visible_article_ids(user_id=owner["id"])

    assert snapshot["item_count"] == 2
    assert latest["id"] == snapshot["id"]
    assert latest["payload"]["scope"] == "user"
    assert latest["payload"]["items"][0]["id"] == "rss:item:1"
    assert history == [
        {
            "snapshot_id": snapshot["id"],
            "generated_at": "2026-07-09T10:00:00+08:00",
            "item_count": 2,
            "job_id": "job_refresh",
        }
    ]
    assert visible_ids == ["github:item:2", "rss:item:1"]


def test_user_feed_store_accepts_legacy_today_items_payload(tmp_path, monkeypatch):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)

    snapshot = feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_today_items",
        payload={
            "generated_at": "2026-07-09T10:30:00+08:00",
            "items": [],
            "today_items": [
                {
                    "id": "hackernews:story:1",
                    "source": "Hacker News",
                    "channel": "AI",
                    "topics": ["Agent"],
                }
            ],
        },
    )
    latest = feeds.latest_snapshot(workspace_id=workspace["id"], user_id=owner["id"])

    assert snapshot["item_count"] == 1
    assert latest["payload"]["item_count"] == 1
    assert latest["payload"]["items"][0]["id"] == "hackernews:story:1"
    assert feeds.visible_article_ids(user_id=owner["id"]) == ["hackernews:story:1"]


def test_user_feed_store_isolates_snapshots_between_users(tmp_path, monkeypatch):
    store, workspace, owner, alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_owner",
        payload={"generated_at": "2026-07-09T10:00:00+08:00", "items": [{"id": "rss:item:owner"}]},
    )

    assert feeds.latest_snapshot(workspace_id=workspace["id"], user_id=alice["id"]) is None
    assert feeds.snapshot_history(workspace_id=workspace["id"], user_id=alice["id"]) == []
    assert feeds.visible_article_ids(user_id=alice["id"]) == []
