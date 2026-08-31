from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.services.content_timeline import (
    feed_window,
    normalize_feed_window_days,
    resolve_effective_at,
    timeline_bucket,
)
from src.services.user_content_store import UserContentStore
from src.storage.service_store import ServiceStore
from scripts.migrate_content_timeline_v11 import migrate_content_timeline_v11


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    assert owner is not None
    return store, workspace, owner


def test_feed_window_uses_shanghai_natural_days_and_allowed_ranges():
    now = datetime(2026, 7, 27, 4, 30, tzinfo=timezone.utc)

    expected_starts = {
        7: datetime(2026, 7, 20, 16, 0, tzinfo=timezone.utc),
        14: datetime(2026, 7, 13, 16, 0, tzinfo=timezone.utc),
        30: datetime(2026, 6, 27, 16, 0, tzinfo=timezone.utc),
    }
    for days, expected_start in expected_starts.items():
        window = feed_window(days, now=now)
        assert window.today_start == datetime(
            2026, 7, 26, 16, 0, tzinfo=timezone.utc
        )
        assert window.feed_start == expected_start
        assert timeline_bucket(window.today_start, window) == "today"
        assert timeline_bucket(window.feed_start, window) == "feed"
        assert (
            timeline_bucket(window.feed_start - timedelta(microseconds=1), window)
            == "history"
        )

    for invalid in (0, 8, 31, True, "7"):
        with pytest.raises(ValueError):
            normalize_feed_window_days(invalid)


def test_effective_at_prefers_trusted_publish_time_and_rejects_future_time():
    now = datetime(2026, 7, 27, 4, 30, tzinfo=timezone.utc)
    first_seen = now - timedelta(hours=2)
    published = now - timedelta(days=40)

    assert resolve_effective_at(
        {"published_at": published.isoformat()},
        first_seen_at=first_seen.isoformat(),
        now=now,
    ) == published.isoformat()
    assert resolve_effective_at(
        {},
        first_seen_at=first_seen.isoformat(),
        now=now,
    ) == first_seen.isoformat()
    assert resolve_effective_at(
        {"published_at": "not-a-time"},
        first_seen_at=first_seen.isoformat(),
        now=now,
    ) == first_seen.isoformat()
    assert resolve_effective_at(
        {"published_at": (now + timedelta(hours=1)).isoformat()},
        first_seen_at=first_seen.isoformat(),
        now=now,
    ) == first_seen.isoformat()


def test_feed_reads_current_catalog_name_for_legacy_youtube_rss_item(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="workspace",
        owner_user_id=None,
        source_type="rss",
        display_name="Example Channel",
        config={
            "url": "https://www.youtube.com/feeds/videos.xml?channel_id=UCexample"
        },
    )
    now = datetime(2026, 8, 31, 4, 30, tzinfo=timezone.utc)
    content = UserContentStore(store)
    content.upsert_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        seen_at=now.isoformat(),
        items=[{
            "id": "rss:youtube:legacy-name",
            "source_id": source_id,
            "source_type": "rss",
            "source": "rss",
            "title": "Legacy YouTube video",
            "url": "https://www.youtube.com/watch?v=legacy",
            "published_at": now.isoformat(),
            "presentation": {
                "source": {"id": source_id, "platform": "youtube", "name": "rss"},
                "links": {"canonical_url": "https://www.youtube.com/watch?v=legacy"},
            },
        }],
    )

    [feed_item] = content.feed_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        window=feed_window(7, now=now),
    )
    detail_item = content.detail_item(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:youtube:legacy-name",
    )

    assert feed_item["source"] == "Example Channel"
    assert feed_item["presentation"]["source"]["name"] == "Example Channel"
    assert detail_item is not None
    assert detail_item["presentation"]["source"]["name"] == "Example Channel"
    store.close()


def test_stable_store_repartitions_without_overlap_and_refetch_does_not_revive(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    content = UserContentStore(store)
    now = datetime(2026, 7, 27, 4, 30, tzinfo=timezone.utc)
    window = feed_window(7, now=now)
    old_at = window.feed_start - timedelta(days=1)
    current_at = window.feed_start + timedelta(hours=1)
    today_at = window.today_start + timedelta(hours=1)
    content.upsert_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        seen_at=now.isoformat(),
        items=[
            {
                "id": "timeline-history",
                "title": "Needle historical record",
                "published_at": old_at.isoformat(),
            },
            {
                "id": "timeline-feed",
                "title": "Needle current record",
                "published_at": current_at.isoformat(),
            },
            {
                "id": "timeline-today",
                "title": "Needle today record",
                "published_at": today_at.isoformat(),
            },
        ],
    )
    content.upsert_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        seen_at=now.isoformat(),
        items=[
            {
                "id": "timeline-history",
                "title": "Needle historical record refreshed",
                "published_at": today_at.isoformat(),
            }
        ],
    )

    feed_items = content.feed_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        window=window,
    )
    history = content.history_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        window=window,
    )
    feed_ids = {item["id"] for item in feed_items}
    history_ids = {item["id"] for item in history["items"]}

    assert feed_ids == {"timeline-feed", "timeline-today"}
    assert history_ids == {"timeline-history"}
    assert feed_ids.isdisjoint(history_ids)
    assert feed_ids | history_ids == {
        "timeline-history",
        "timeline-feed",
        "timeline-today",
    }
    assert next(
        item for item in history["items"] if item["id"] == "timeline-history"
    )["title"].endswith("refreshed")
    for projected in [*feed_items, *history["items"]]:
        assert projected["presentation"]["source"]["id"] == ""
        assert projected["presentation"]["author"]["kind"] == "unknown"
        assert projected["presentation"]["content"]["title"]
        assert "channel" in projected["presentation"]["taxonomy"]
        assert projected["presentation"]["analysis"]["status"] == "fallback"
        assert projected["presentation"]["timing"]["effective_at"]

    search = content.search_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        q="Needle",
        window=window,
    )
    assert search["total_count"] == 3
    assert {
        item["id"]: item["timeline_bucket"] for item in search["items"]
    } == {
        "timeline-today": "today",
        "timeline-feed": "feed",
        "timeline-history": "history",
    }

    wider = content.feed_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        window=feed_window(14, now=now),
    )
    assert {item["id"] for item in wider} == {
        "timeline-history",
        "timeline-feed",
        "timeline-today",
    }


def test_content_timeline_v11_migration_backs_up_and_rebuilds_index(
    tmp_path,
    monkeypatch,
):
    data_dir = tmp_path / "data"
    store, workspace, owner = _store(data_dir, monkeypatch)
    UserContentStore(store).upsert_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        seen_at="2026-07-01T00:00:00+00:00",
        items=[
            {
                "id": "migration-timeline-item",
                "title": "Migration searchable needle",
                "published_at": "2026-06-01T00:00:00+00:00",
            }
        ],
    )
    store.connect().execute(
        """
        UPDATE user_content_items
        SET effective_at = '', search_text = ''
        WHERE article_id = 'migration-timeline-item'
        """
    )
    store.connect().execute(
        "DELETE FROM schema_migrations WHERE version = 11"
    )
    store.connect().commit()
    assert store.content_timeline_v11_migration_required() is True
    store.close()

    dry_run = migrate_content_timeline_v11(
        data_dir=data_dir,
        backup_dir=data_dir / "backups",
        apply=False,
    )
    assert dry_run["pending_count"] == 1
    applied = migrate_content_timeline_v11(
        data_dir=data_dir,
        backup_dir=data_dir / "backups",
        apply=True,
    )
    assert applied["applied"] is True
    assert applied["backfilled_count"] == 1
    assert applied["indexed_count"] == 1
    assert applied["integrity_check"] == "ok"
    assert applied["foreign_key_errors"] == 0
    assert (data_dir / "backups").is_dir()
    assert applied["backup_path"]

    reopened = ServiceStore(data_dir)
    reopened.initialize()
    assert reopened.content_timeline_v11_migration_required() is False
    row = reopened.connect().execute(
        """
        SELECT effective_at, search_text
        FROM user_content_items
        WHERE article_id = 'migration-timeline-item'
        """
    ).fetchone()
    assert row["effective_at"] == "2026-06-01T00:00:00+00:00"
    assert "migration searchable needle" in row["search_text"]
    reopened.close()
