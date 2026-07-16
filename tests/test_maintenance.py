from __future__ import annotations

from datetime import datetime, timedelta, timezone

import pytest

from src.services.job_queue import JobQueue
from src.services.maintenance import MaintenanceService
from src.storage.service_store import ServiceStore


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    member = store.create_user(
        workspace_id=workspace["id"],
        username="maintenance-member",
        password="member-password",
    )
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Maintenance RSS",
        config={"url": "https://example.com/maintenance.xml"},
    )
    return store, workspace, owner, member, source_id


def test_hourly_maintenance_prunes_retention_and_preserves_latest_records(
    tmp_path, monkeypatch
):
    store, workspace, owner, member, source_id = _store(tmp_path, monkeypatch)
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    conn = store.connect()

    def insert_feed(snapshot_id, user_id, generated_at):
        conn.execute(
            """
            INSERT INTO user_feed_snapshots (
                id, workspace_id, user_id, schema_version, storage_version,
                generated_at, item_count, payload_json, created_at
            ) VALUES (?, ?, ?, 2, 1, ?, 0, '{}', ?)
            """,
            (
                snapshot_id,
                workspace["id"],
                user_id,
                generated_at.isoformat(),
                generated_at.isoformat(),
            ),
        )

    insert_feed("feed-owner-latest", owner["id"], now)
    insert_feed("feed-owner-middle", owner["id"], now - timedelta(days=1))
    insert_feed("feed-owner-old", owner["id"], now - timedelta(days=100))
    insert_feed("feed-member-only-old", member["id"], now - timedelta(days=200))
    conn.execute(
        """
        INSERT INTO user_feed_items (
            id, workspace_id, user_id, snapshot_id, article_id, created_at
        ) VALUES ('feed-item-old', ?, ?, 'feed-owner-old', 'article-old', ?)
        """,
        (workspace["id"], owner["id"], (now - timedelta(days=100)).isoformat()),
    )

    def insert_source(snapshot_id, acquisition_key, generated_at):
        conn.execute(
            """
            INSERT INTO source_content_snapshots (
                id, acquisition_key, workspace_id, source_id,
                config_fingerprint, isolation_scope, window_hours,
                generated_at, fresh_until, item_count, diagnostics_json,
                created_at
            ) VALUES (?, ?, ?, ?, 'fingerprint', 'workspace:default', 24,
                      ?, ?, 0, '{}', ?)
            """,
            (
                snapshot_id,
                acquisition_key,
                workspace["id"],
                source_id,
                generated_at.isoformat(),
                generated_at.isoformat(),
                generated_at.isoformat(),
            ),
        )

    insert_source("source-latest", "key-shared", now)
    insert_source("source-old", "key-shared", now - timedelta(days=10))
    insert_source("source-only-old", "key-only-old", now - timedelta(days=20))
    conn.execute(
        """
        INSERT INTO user_analysis_cache (
            workspace_id, user_id, article_id, input_hash, model,
            prompt_version, result_json, created_at, updated_at
        ) VALUES (?, ?, 'analysis-old', 'hash-old', 'model', 'prompt', '{}', ?, ?)
        """,
        (
            workspace["id"],
            owner["id"],
            (now - timedelta(days=31)).isoformat(),
            (now - timedelta(days=31)).isoformat(),
        ),
    )
    conn.execute(
        """
        INSERT INTO usage_events (
            id, workspace_id, user_id, event_type, quantity, created_at
        ) VALUES ('usage-old', ?, ?, 'source_fetch', 1, ?)
        """,
        (workspace["id"], owner["id"], (now - timedelta(days=91)).isoformat()),
    )
    expired_session = store.create_session(owner["id"], ttl_seconds=-1)
    conn.execute(
        "UPDATE sessions SET expires_at = ? WHERE token = ?",
        ((now - timedelta(seconds=1)).isoformat(), expired_session),
    )
    terminal = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
    )
    active = JobQueue(store).create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_test",
    )
    conn.execute(
        """
        UPDATE fetch_jobs
        SET status = 'succeeded', finished_at = ?, updated_at = ?, expires_at = NULL
        WHERE id = ?
        """,
        (
            (now - timedelta(days=15)).isoformat(),
            (now - timedelta(days=15)).isoformat(),
            terminal["id"],
        ),
    )
    conn.execute(
        "UPDATE fetch_jobs SET created_at = ?, updated_at = ? WHERE id = ?",
        (
            (now - timedelta(days=30)).isoformat(),
            (now - timedelta(days=30)).isoformat(),
            active["id"],
        ),
    )
    conn.commit()

    maintenance = MaintenanceService(
        store,
        max_feed_snapshots_per_user=2,
    )
    first = maintenance.run_if_due(now=now)
    second = maintenance.run_if_due(now=now + timedelta(minutes=30))

    assert first["ran"] is True
    assert first["deleted"] == {
        "feed_snapshots": 1,
        "source_snapshots": 1,
        "content_items": 0,
        "media_assets": 0,
        "analysis_cache": 1,
        "usage_events": 1,
        "jobs": 1,
        "sessions": 1,
    }
    assert second == {"ran": False, "deleted": {}}
    assert {
        row["id"]
        for row in conn.execute("SELECT id FROM user_feed_snapshots").fetchall()
    } == {
        "feed-owner-latest",
        "feed-owner-middle",
        "feed-member-only-old",
    }
    assert conn.execute(
        "SELECT 1 FROM user_feed_items WHERE id = 'feed-item-old'"
    ).fetchone() is None
    assert {
        row["id"]
        for row in conn.execute("SELECT id FROM source_content_snapshots").fetchall()
    } == {"source-latest", "source-only-old"}
    assert JobQueue(store).get_job(terminal["id"]) is None
    assert JobQueue(store).get_job(active["id"])["status"] == "queued"
    assert store.get_session_user(expired_session) is None
    assert conn.execute("PRAGMA foreign_key_check").fetchall() == []


def test_maintenance_keeps_saved_and_later_content_but_prunes_unpinned_media(
    tmp_path, monkeypatch
):
    from src.services.user_content_store import UserContentStore
    from src.services.user_item_state import UserItemStateStore

    store, workspace, owner, _member, _source_id = _store(tmp_path, monkeypatch)
    now = datetime(2026, 7, 14, 12, 0, tzinfo=timezone.utc)
    old = (now - timedelta(days=100)).isoformat()
    content = UserContentStore(store)
    content.upsert_items(
        workspace_id=workspace["id"], user_id=owner["id"], seen_at=old,
        items=[
            {"id": "saved-old", "title": "Saved", "url": "https://example.com/saved"},
            {"id": "later-old", "title": "Later", "url": "https://example.com/later"},
            {"id": "ordinary-old", "title": "Old", "url": "https://example.com/old"},
        ],
    )
    states = UserItemStateStore(store)
    states.update_state(
        workspace_id=workspace["id"], user_id=owner["id"], article_id="saved-old",
        is_saved=True,
    )
    states.update_state(
        workspace_id=workspace["id"], user_id=owner["id"], article_id="later-old",
        is_later=True,
    )
    media_path = tmp_path / "media" / "old.png"
    media_path.parent.mkdir(parents=True, exist_ok=True)
    media_path.write_bytes(b"old")
    store.connect().execute(
        """
        INSERT INTO media_assets (
          id, workspace_id, user_id, article_id, asset_kind, remote_url,
          local_path, mime_type, byte_size, checksum, alt, visibility_scope,
          status, created_at, updated_at
        ) VALUES ('med-old', ?, ?, 'ordinary-old', 'content_image', '',
          'media/old.png', 'image/png', 3, 'sum', 'old', 'private', 'ready', ?, ?)
        """,
        (workspace["id"], owner["id"], old, old),
    )
    store.connect().commit()

    result = MaintenanceService(store, feed_retention_days=30).run_if_due(now=now, force=True)

    assert result["deleted"]["content_items"] == 1
    assert result["deleted"]["media_assets"] == 1
    assert {
        row["article_id"] for row in store.connect().execute(
            "SELECT article_id FROM user_content_items"
        ).fetchall()
    } == {"saved-old", "later-old"}
    assert not media_path.exists()


def test_maintenance_does_not_commit_a_callers_transaction(tmp_path, monkeypatch):
    store, workspace, owner, _member, _source_id = _store(tmp_path, monkeypatch)
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO usage_events (
            id, workspace_id, user_id, event_type, quantity, created_at
        ) VALUES ('usage-uncommitted', ?, ?, 'source_fetch', 1, ?)
        """,
        (workspace["id"], owner["id"], datetime.now(timezone.utc).isoformat()),
    )

    try:
        with pytest.raises(RuntimeError, match="requires no active transaction"):
            MaintenanceService(store).run_if_due(force=True)
        assert conn.in_transaction is True
    finally:
        conn.rollback()

    assert conn.execute(
        "SELECT 1 FROM usage_events WHERE id = 'usage-uncommitted'"
    ).fetchone() is None
