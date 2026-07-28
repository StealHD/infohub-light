import json
from datetime import datetime, timedelta, timezone
from unittest.mock import AsyncMock

import httpx

from src.models import ContentItem, SourceType
from src.services.feed_archive import FeedArchiveService
from src.services.user_content_store import UserContentStore
from src.services.user_analysis_cache import UserAnalysisCache
from src.services.user_feed_store import UserFeedStore
from src.services.user_item_state import UserItemStateStore
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


def _days_ago(days: int) -> str:
    return (
        datetime.now(timezone.utc) - timedelta(days=days)
    ).replace(microsecond=0).isoformat()


def _assert_window(payload: dict, *, days: int = 7) -> None:
    window = payload["window"]
    assert window["timezone"] == "Asia/Shanghai"
    assert window["feed_days"] == days
    assert datetime.fromisoformat(window["feed_start"]) < datetime.fromisoformat(
        window["today_start"]
    ) <= datetime.fromisoformat(window["now"])


def _save_snapshots(feeds, *, workspace_id, user_id, payloads):
    return [
        feeds.save_snapshot(
            workspace_id=workspace_id,
            user_id=user_id,
            job_id=f"job_history_{user_id}_{index}",
            payload=payload,
        )
        for index, payload in enumerate(payloads)
    ]


def _replace_snapshot_payload(store, snapshot_id, payload):
    store.connect().execute(
        "UPDATE user_feed_snapshots SET payload_json = ? WHERE id = ?",
        (json.dumps(payload), snapshot_id),
    )
    store.connect().commit()


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
    stored_scores = [
        row["score"]
        for row in store.connect().execute(
            """
            SELECT score FROM user_feed_items
            WHERE snapshot_id = ?
            ORDER BY position
            """,
            (snapshot["id"],),
        ).fetchall()
    ]

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
    assert stored_scores == [8.5, None]


def test_source_native_title_is_internal_and_legacy_upsert_cannot_erase_it(
    tmp_path,
    monkeypatch,
):
    from src.services.canonical_content import INTERNAL_SOURCE_NATIVE_TITLE_KEY
    from src.ui.site import build_site_payload, serialize_item

    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    try:
        columns = {
            row["name"]
            for row in store.connect().execute(
                "PRAGMA table_info(user_content_items)"
            ).fetchall()
        }
        assert "source_native_title" in columns
        item = ContentItem(
            id="rss:native-title:upsert",
            source_type=SourceType.RSS,
            title="Canonical source title",
            url="https://example.com/native-title-upsert",
            published_at=datetime(2026, 7, 24, tzinfo=timezone.utc),
            metadata={"title_zh": "Donor AI display title"},
        )
        serialized = serialize_item(item, featured_threshold=8.0)
        assert (
            serialized[INTERNAL_SOURCE_NATIVE_TITLE_KEY]
            == "Canonical source title"
        )
        UserContentStore(store).upsert_items(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            items=[serialized],
            seen_at="2026-07-24T00:00:00+00:00",
        )
        legacy_update = dict(serialized)
        legacy_update.pop(INTERNAL_SOURCE_NATIVE_TITLE_KEY)
        legacy_update["title"] = "Later display-only title"
        UserContentStore(store).upsert_items(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            items=[legacy_update],
            seen_at="2026-07-24T01:00:00+00:00",
        )

        stored = store.connect().execute(
            """
            SELECT source_native_title, item_json
            FROM user_content_items
            WHERE workspace_id = ? AND user_id = ? AND article_id = ?
            """,
            (workspace["id"], owner["id"], item.id),
        ).fetchone()
        assert stored["source_native_title"] == "Canonical source title"
        assert INTERNAL_SOURCE_NATIVE_TITLE_KEY not in stored["item_json"]
        static_payload = build_site_payload(
            all_items=[item],
            date="2026-07-24",
            total_fetched=1,
        )
        assert INTERNAL_SOURCE_NATIVE_TITLE_KEY not in json.dumps(
            static_payload,
            sort_keys=True,
        )
    finally:
        store.close()


def test_initialize_adds_nullable_native_title_column_without_backfill(
    tmp_path,
    monkeypatch,
):
    import sqlite3

    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job-legacy-native-title-schema",
        payload={
            "generated_at": "2026-07-24T00:00:00+00:00",
            "items": [
                {
                    "id": "rss:legacy:native-title-schema",
                    "title": "Unproven legacy display title",
                }
            ],
        },
    )
    store.close()
    legacy_connection = sqlite3.connect(tmp_path / "service.db")
    try:
        legacy_connection.execute(
            "ALTER TABLE user_content_items DROP COLUMN source_native_title"
        )
        legacy_connection.commit()
    finally:
        legacy_connection.close()

    reopened = ServiceStore(tmp_path)
    try:
        reopened.initialize()
        columns = {
            row["name"]
            for row in reopened.connect().execute(
                "PRAGMA table_info(user_content_items)"
            ).fetchall()
        }
        legacy_row = reopened.connect().execute(
            """
            SELECT source_native_title FROM user_content_items
            WHERE workspace_id = ? AND user_id = ? AND article_id = ?
            """,
            (
                workspace["id"],
                owner["id"],
                "rss:legacy:native-title-schema",
            ),
        ).fetchone()
        assert "source_native_title" in columns
        assert legacy_row["source_native_title"] is None
    finally:
        reopened.close()


def test_snapshot_upserts_stable_user_content_without_dropping_old_items(
    tmp_path, monkeypatch
):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_stable_first",
        payload={
            "generated_at": "2026-07-14T01:00:00+00:00",
            "items": [
                {
                    "id": "rss:stable:1",
                    "title": "First title",
                    "summary_zh": "First summary",
                    "presentation": {
                        "version": 1,
                        "content": {
                            "excerpt": "Captured excerpt",
                            "excerpt_truncated": False,
                        },
                    },
                }
            ],
        },
    )
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_stable_empty",
        payload={
            "generated_at": "2026-07-14T02:00:00+00:00",
            "items": [],
        },
    )

    stored = UserContentStore(store).get_item(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:stable:1",
    )

    assert stored is not None
    assert stored["item"]["title"] == "First title"
    assert stored["body_text"] == "Captured excerpt"
    assert stored["body_completeness"] == "excerpt_only"
    assert stored["first_seen_at"] == "2026-07-14T01:00:00+00:00"
    assert stored["last_seen_at"] == "2026-07-14T01:00:00+00:00"


def test_stable_content_replaces_payload_but_keeps_first_seen_time(
    tmp_path, monkeypatch
):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)
    for index, (generated_at, title) in enumerate(
        [
            ("2026-07-14T01:00:00+00:00", "Old title"),
            ("2026-07-14T03:00:00+00:00", "New title"),
        ]
    ):
        feeds.save_snapshot(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id=f"job_stable_{index}",
            payload={
                "generated_at": generated_at,
                "items": [{"id": "rss:stable:2", "title": title}],
            },
        )

    stored = UserContentStore(store).get_item(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="rss:stable:2",
    )

    assert stored["item"]["title"] == "New title"
    assert stored["first_seen_at"] == "2026-07-14T01:00:00+00:00"
    assert stored["last_seen_at"] == "2026-07-14T03:00:00+00:00"


def test_captured_body_cleans_html_preserves_paragraphs_and_caps_20000_chars(
    tmp_path, monkeypatch
):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_captured_body",
        payload={
            "generated_at": "2026-07-14T04:00:00+00:00",
            "items": [{"id": "rss:captured:1", "title": "Captured"}],
        },
    )
    item = ContentItem(
        id="rss:captured:1",
        source_type=SourceType.RSS,
        title="Captured",
        url="https://example.com/captured",
        content=(
            "<p>第一段 &amp; 文本</p><script>steal()</script>"
            "<div>第二段</div><p>" + ("长" * 21000) + "</p>"
        ),
        published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
    )

    UserContentStore(store).upsert_captured_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[item],
    )
    store.connect().commit()
    stored = UserContentStore(store).get_item(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id=item.id,
    )

    assert stored["body_text"].startswith("第一段 & 文本\n\n第二段\n\n")
    assert "steal" not in stored["body_text"]
    assert len(stored["body_text"]) == 20000
    assert stored["body_text"].endswith("…")
    assert stored["body_truncated"] is True
    assert stored["body_completeness"] == "captured"
    assert stored["analysis_input_hash"] == UserAnalysisCache.content_hash(item)


def test_captured_body_upsert_removes_only_stale_source_body_reason(
    tmp_path, monkeypatch
):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    content_store = UserContentStore(store)
    content_store.upsert_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[
            {"id": "rss:captured:reasons", "title": "Captured reasons"},
            {"id": "rss:captured:only-stale", "title": "Only stale"},
            {"id": "rss:captured:stale-tail", "title": "Stale tail"},
            {"id": "rss:captured:stale-surrounded", "title": "Stale surrounded"},
            {"id": "rss:captured:blank", "title": "Blank body"},
        ],
        seen_at="2026-07-14T04:00:00+00:00",
    )
    store.connect().executemany(
        "UPDATE user_content_items SET unresolved_reason = ? WHERE article_id = ?",
        [
            (
                "source_body_not_available;media_cache_failed:2;"
                "source_body_not_available_extra",
                "rss:captured:reasons",
            ),
            ("source_body_not_available", "rss:captured:only-stale"),
            ("source_body_not_available;   ", "rss:captured:stale-tail"),
            (" ; source_body_not_available ; ", "rss:captured:stale-surrounded"),
            ("source_body_not_available", "rss:captured:blank"),
        ],
    )

    captured = [
        ContentItem(
            id="rss:captured:reasons",
            source_type=SourceType.RSS,
            title="Captured reasons",
            url="https://example.com/captured-reasons",
            content="Captured source body",
            published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        ),
        ContentItem(
            id="rss:captured:only-stale",
            source_type=SourceType.RSS,
            title="Only stale",
            url="https://example.com/only-stale",
            content="Another captured source body",
            published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        ),
        ContentItem(
            id="rss:captured:stale-tail",
            source_type=SourceType.RSS,
            title="Stale tail",
            url="https://example.com/stale-tail",
            content="Captured body with a whitespace tail reason",
            published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        ),
        ContentItem(
            id="rss:captured:stale-surrounded",
            source_type=SourceType.RSS,
            title="Stale surrounded",
            url="https://example.com/stale-surrounded",
            content="Captured body with surrounding whitespace reasons",
            published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        ),
        ContentItem(
            id="rss:captured:blank",
            source_type=SourceType.RSS,
            title="Blank body",
            url="https://example.com/blank",
            content=" \n\t ",
            published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        ),
    ]

    content_store.upsert_captured_items(
        workspace_id=workspace["id"], user_id=owner["id"], items=captured
    )
    content_store.upsert_captured_items(
        workspace_id=workspace["id"], user_id=owner["id"], items=captured
    )
    rows = {
        row["article_id"]: dict(row)
        for row in store.connect().execute(
            """
            SELECT article_id, body_completeness, unresolved_reason
            FROM user_content_items
            WHERE article_id LIKE 'rss:captured:%'
            """
        ).fetchall()
    }

    assert rows["rss:captured:reasons"]["unresolved_reason"] == (
        "media_cache_failed:2;source_body_not_available_extra"
    )
    assert rows["rss:captured:only-stale"]["unresolved_reason"] is None
    assert rows["rss:captured:stale-tail"]["unresolved_reason"] is None
    assert rows["rss:captured:stale-surrounded"]["unresolved_reason"] is None
    assert rows["rss:captured:blank"]["body_completeness"] == "excerpt_only"
    assert rows["rss:captured:blank"]["unresolved_reason"] == (
        "source_body_not_available"
    )


def test_media_cache_downloads_at_most_six_images_and_rewrites_item_urls(
    tmp_path, monkeypatch
):
    from src.services.media_cache import MediaCacheService

    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Instagram",
        config={"platform": "instagram", "kind": "profile", "target": "tsucha_ri"},
    )
    urls = [f"https://cdn.example.com/image-{index}.png" for index in range(7)]
    item = ContentItem(
        id="instagram:post:gallery",
        source_type=SourceType.INSTAGRAM,
        title="Gallery",
        url="https://instagram.com/p/gallery",
        content="Gallery body",
        published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        metadata={
            "source_id": source_id,
            "media_urls": urls,
            "author_avatar_url": "https://cdn.example.com/avatar.png",
        },
    )

    def fetch_image(url):
        return b"\x89PNG\r\n\x1a\n" + url.encode("utf-8"), "image/png"

    MediaCacheService(store, data_dir=tmp_path, fetch_image=fetch_image).cache_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[item],
    )

    rows = store.connect().execute(
        "SELECT * FROM media_assets ORDER BY asset_kind, created_at, id"
    ).fetchall()
    content_rows = [row for row in rows if row["asset_kind"] == "content_image"]
    avatar_rows = [row for row in rows if row["asset_kind"] == "source_avatar"]
    assert len(content_rows) == 6
    assert len(avatar_rows) == 1
    assert item.metadata["remote_media_urls"] == urls[:6]
    assert item.metadata["media_image_count"] == 7
    assert len(item.metadata["media_urls"]) == 6
    assert all(url.startswith("/api/media/med_") for url in item.metadata["media_urls"])
    assert item.metadata["avatar_url"].startswith("/api/media/med_")
    assert all((tmp_path / row["local_path"]).is_file() for row in rows)

    from src.ui.site import serialize_item

    serialized = serialize_item(item, featured_threshold=8.0)
    assert serialized["presentation"]["media"] == {
        "images": [
            {"url": url, "alt": "Gallery"}
            for url in item.metadata["media_urls"]
        ],
        "count": 6,
        "total_image_count": 7,
        "truncated": True,
    }
    UserContentStore(store).upsert_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[serialized],
        seen_at="2026-07-14T00:00:00+00:00",
    )
    indexed_item = UserContentStore(store).get_item(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id=item.id,
    )["item"]
    assert "remote_image_url" not in indexed_item
    assert "remote_media_urls" not in indexed_item

    snapshot = UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_media_public_contract",
        payload={
            "schema_version": 2,
            "generated_at": "2026-07-14T00:00:00+00:00",
            "items": [serialized],
        },
    )
    public_item = snapshot["payload"]["items"][0]
    assert "remote_image_url" not in public_item
    assert "remote_media_urls" not in public_item
    assert public_item["image_url"].startswith("/api/media/med_")
    assert all(url.startswith("/api/media/med_") for url in public_item["media_urls"])


def test_media_cache_reuses_checksum_across_rotating_instagram_urls(
    tmp_path, monkeypatch
):
    from src.services.media_cache import MediaCacheService
    from src.ui.site import serialize_item

    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    shared_bytes = b"\x89PNG\r\n\x1a\n" + b"same-instagram-image"
    cache = MediaCacheService(
        store,
        data_dir=tmp_path,
        fetch_image=lambda _url: (shared_bytes, "image/png"),
    )
    first = ContentItem(
        id="instagram:post:rotating-cdn",
        source_type=SourceType.INSTAGRAM,
        title="Rotating CDN",
        url="https://instagram.com/p/rotating-cdn",
        published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        metadata={"media_urls": ["https://scontent-a.cdninstagram.com/image.jpg?sig=old"]},
    )
    second = ContentItem(
        id=first.id,
        source_type=first.source_type,
        title=first.title,
        url=first.url,
        published_at=first.published_at,
        metadata={
            "media_urls": [
                "https://scontent-b.cdninstagram.com/image.jpg?sig=new",
                "https://scontent-c.cdninstagram.com/image.jpg?sig=newer",
            ]
        },
    )

    cache.cache_items(workspace_id=workspace["id"], user_id=owner["id"], items=[first])
    first_local_url = first.metadata["media_urls"][0]
    cache.cache_items(workspace_id=workspace["id"], user_id=owner["id"], items=[second])

    rows = store.connect().execute(
        """
        SELECT id, remote_url, checksum FROM media_assets
        WHERE article_id = ? AND asset_kind = 'content_image'
        """,
        (first.id,),
    ).fetchall()
    assert len(rows) == 1
    assert rows[0]["remote_url"].endswith("sig=newer")
    assert second.metadata["media_urls"] == [first_local_url]

    serialized = serialize_item(second, featured_threshold=8.0)
    UserContentStore(store).upsert_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[serialized],
        seen_at="2026-07-14T00:00:00+00:00",
    )
    original = dict(rows[0])
    store.connect().execute(
        """
        INSERT INTO media_assets (
            id, workspace_id, user_id, article_id, asset_kind, remote_url,
            local_path, mime_type, byte_size, checksum, alt, visibility_scope,
            status, created_at, updated_at
        )
        SELECT 'med_legacy_duplicate', workspace_id, user_id, article_id,
               asset_kind, 'https://legacy.example/image.jpg', local_path,
               mime_type, byte_size, checksum, alt, visibility_scope, status,
               '2026-07-13T00:00:00+00:00', '2026-07-13T00:00:00+00:00'
        FROM media_assets WHERE id = ?
        """,
        (original["id"],),
    )
    store.connect().commit()

    detail = UserContentStore(store).detail_item(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id=first.id,
    )
    assert detail["presentation"]["media"]["count"] == 1
    assert len(detail["presentation"]["media"]["images"]) == 1


def test_media_cache_download_allows_synthetic_dns_only_for_instagram_cdn(
    tmp_path, monkeypatch
):
    from src.services import media_cache

    response = httpx.Response(
        200,
        content=b"\x89PNG\r\n\x1a\nimage-bytes",
        headers={"content-type": "image/png"},
        request=httpx.Request(
            "GET", "https://instagram.flas1-1.fna.fbcdn.net/image.png"
        ),
    )
    fetch_public = AsyncMock(return_value=response)
    monkeypatch.setattr(media_cache, "fetch_public_http", fetch_public)

    data, mime_type = media_cache.MediaCacheService(
        ServiceStore(tmp_path), data_dir=tmp_path
    )._download("https://instagram.flas1-1.fna.fbcdn.net/image.png")

    assert data.startswith(b"\x89PNG")
    assert mime_type == "image/png"
    fetch_public.assert_awaited_once_with(
        "https://instagram.flas1-1.fna.fbcdn.net/image.png",
        headers={"Accept": "image/*"},
        timeout=15.0,
        max_response_bytes=media_cache.MAX_IMAGE_BYTES,
        synthetic_dns_host_suffixes=media_cache.TRUSTED_MEDIA_HOST_SUFFIXES,
    )


def test_media_cache_failure_is_nonfatal_and_keeps_remote_url_for_retry(
    tmp_path, monkeypatch
):
    from src.services.media_cache import MediaCacheService

    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    item = ContentItem(
        id="instagram:post:retry",
        source_type=SourceType.INSTAGRAM,
        title="Retry",
        url="https://instagram.com/p/retry",
        published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
        metadata={"media_urls": ["https://cdn.example.com/expired.jpg"]},
    )

    def fail_image(_url):
        raise TimeoutError("remote image expired")

    MediaCacheService(store, data_dir=tmp_path, fetch_image=fail_image).cache_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[item],
    )

    assert item.metadata["media_urls"] == []
    assert item.metadata["remote_media_urls"] == [
        "https://cdn.example.com/expired.jpg"
    ]
    assert store.connect().execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 0


def test_source_avatar_is_cached_once_and_can_be_invalidated_after_identity_change(
    tmp_path, monkeypatch
):
    from src.services.media_cache import MediaCacheService

    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Social profile",
        config={"platform": "x", "kind": "profile", "target": "first"},
    )
    fetches = []

    def fetch_image(url):
        fetches.append(url)
        return b"\x89PNG\r\n\x1a\n" + b"avatar", "image/png"

    cache = MediaCacheService(store, data_dir=tmp_path, fetch_image=fetch_image)
    for article_id in ("x:first:1", "x:first:2"):
        cache.cache_items(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            items=[ContentItem(
                id=article_id,
                source_type=SourceType.TWITTER,
                title="Post",
                url="https://x.com/first/status/1",
                published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
                metadata={
                    "source_id": source_id,
                    "author_avatar_url": "https://cdn.example.com/avatar.png",
                },
            )],
        )

    avatar = cache.avatar_for_source(workspace_id=workspace["id"], source_id=source_id)
    avatar_path = tmp_path / avatar["local_path"]
    assert fetches == ["https://cdn.example.com/avatar.png"]
    assert avatar_path.is_file()

    assert cache.invalidate_source_avatar(
        workspace_id=workspace["id"], source_id=source_id
    ) == 1
    store.connect().commit()
    assert cache.avatar_for_source(workspace_id=workspace["id"], source_id=source_id) is None
    assert not avatar_path.exists()


def test_source_avatar_remote_identity_change_replaces_verified_version(
    tmp_path, monkeypatch
):
    from src.services.media_cache import MediaCacheService

    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="X profile",
        config={"platform": "x", "kind": "profile", "target": "profile"},
    )
    fetched = []

    def fetch_image(url):
        fetched.append(url)
        suffix = b"old" if "old-avatar" in url else b"new"
        return b"\x89PNG\r\n\x1a\n" + suffix, "image/png"

    cache = MediaCacheService(store, data_dir=tmp_path, fetch_image=fetch_image)

    def item(article_id, avatar_url):
        return ContentItem(
            id=article_id,
            source_type=SourceType.TWITTER,
            title="Post",
            url=f"https://x.com/profile/status/{article_id[-1]}",
            published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            metadata={"source_id": source_id, "author_avatar_url": avatar_url},
        )

    cache.cache_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[item("twitter:tweet:1", "https://pbs.twimg.com/old-avatar.png?x=1")],
    )
    old = cache.avatar_for_source(workspace_id=workspace["id"], source_id=source_id)
    old_path = tmp_path / old["local_path"]
    cache.cache_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[item("twitter:tweet:2", "https://pbs.twimg.com/new-avatar.png?x=2")],
    )
    current = cache.avatar_for_source(workspace_id=workspace["id"], source_id=source_id)

    assert fetched == [
        "https://pbs.twimg.com/old-avatar.png?x=1",
        "https://pbs.twimg.com/new-avatar.png?x=2",
    ]
    assert current["id"] != old["id"]
    assert current["remote_url"].endswith("new-avatar.png?x=2")
    assert not old_path.exists()
    assert store.connect().execute(
        "SELECT COUNT(*) FROM media_assets WHERE source_id = ? AND asset_kind = 'source_avatar'",
        (source_id,),
    ).fetchone()[0] == 1


def test_source_avatar_refresh_failure_keeps_existing_ready_version(
    tmp_path, monkeypatch
):
    from src.services.media_cache import MediaCacheService

    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="X profile",
        config={"platform": "x", "kind": "profile", "target": "profile"},
    )
    calls = []

    def fetch_image(url):
        calls.append(url)
        if "new-avatar" in url:
            raise TimeoutError("candidate failed")
        return b"\x89PNG\r\n\x1a\nold", "image/png"

    cache = MediaCacheService(store, data_dir=tmp_path, fetch_image=fetch_image)

    def cache_avatar(article_id, avatar_url):
        item = ContentItem(
            id=article_id,
            source_type=SourceType.TWITTER,
            title="Post",
            url="https://x.com/profile/status/1",
            published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            metadata={"source_id": source_id, "author_avatar_url": avatar_url},
        )
        cache.cache_items(
            workspace_id=workspace["id"], user_id=owner["id"], items=[item]
        )
        return item

    first = cache_avatar("twitter:tweet:1", "https://pbs.twimg.com/old-avatar.png")
    old = cache.avatar_for_source(workspace_id=workspace["id"], source_id=source_id)
    old_path = tmp_path / old["local_path"]
    second = cache_avatar("twitter:tweet:2", "https://pbs.twimg.com/new-avatar.png")
    current = cache.avatar_for_source(workspace_id=workspace["id"], source_id=source_id)

    assert calls == [
        "https://pbs.twimg.com/old-avatar.png",
        "https://pbs.twimg.com/new-avatar.png",
    ]
    assert current["id"] == old["id"]
    assert old_path.exists()
    assert first.metadata["avatar_url"] == second.metadata["avatar_url"]


def test_source_avatar_same_identity_rechecks_checksum_after_24_hours(
    tmp_path, monkeypatch
):
    from src.services.media_cache import MediaCacheService

    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="X profile",
        config={"platform": "x", "kind": "profile", "target": "profile"},
    )
    calls = []

    def fetch_image(url):
        calls.append(url)
        version = b"old" if "version=1" in url else b"new"
        return b"\x89PNG\r\n\x1a\n" + version, "image/png"

    cache = MediaCacheService(store, data_dir=tmp_path, fetch_image=fetch_image)

    def item(article_id, avatar_url):
        return ContentItem(
            id=article_id,
            source_type=SourceType.TWITTER,
            title="Post",
            url="https://x.com/profile/status/1",
            published_at=datetime(2026, 7, 14, tzinfo=timezone.utc),
            metadata={"source_id": source_id, "author_avatar_url": avatar_url},
        )

    cache.cache_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[item("twitter:tweet:1", "https://pbs.twimg.com/avatar.png?version=1")],
    )
    old = cache.avatar_for_source(workspace_id=workspace["id"], source_id=source_id)
    store.connect().execute(
        "UPDATE media_assets SET updated_at = ? WHERE id = ?",
        ("2026-07-14T00:00:00+00:00", old["id"]),
    )
    store.connect().commit()

    cache.cache_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[item("twitter:tweet:2", "https://pbs.twimg.com/avatar.png?version=2")],
    )
    current = cache.avatar_for_source(workspace_id=workspace["id"], source_id=source_id)

    assert calls == [
        "https://pbs.twimg.com/avatar.png?version=1",
        "https://pbs.twimg.com/avatar.png?version=2",
    ]
    assert current["id"] != old["id"]
    assert current["remote_url"].endswith("avatar.png?version=2")


def test_deleting_last_subscription_reconciles_latest_feed_to_empty(
    tmp_path, monkeypatch
):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Lifecycle Feed",
        config={"url": "https://example.com/lifecycle.xml"},
        source_key="rss:https://example.com/lifecycle.xml",
    )
    subscription = store.create_subscription(
        user_id=owner["id"], source_id=source_id
    )
    feeds = UserFeedStore(store)
    old_snapshot = feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_lifecycle_old",
        payload={
            "schema_version": 2,
            "generated_at": "2026-07-14T08:00:00+00:00",
            "items": [
                {
                    "id": "rss:lifecycle:1",
                    "source_id": source_id,
                    "subscription_id": subscription["id"],
                    "source_ids": [source_id],
                    "subscription_ids": [subscription["id"]],
                    "title": "Old item",
                }
            ],
        },
    )

    assert store.delete_subscription(
        subscription["id"], user_id=owner["id"]
    ) is True

    latest = feeds.latest_snapshot(
        workspace_id=workspace["id"], user_id=owner["id"]
    )
    assert latest["id"] != old_snapshot["id"]
    assert latest["payload"]["items"] == []
    assert latest["payload"]["today_items"] == []
    assert latest["item_count"] == 0


def test_deleting_one_subscription_prunes_all_inactive_shared_provenance(
    tmp_path, monkeypatch
):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    source_ids = [
        store.create_source(
            workspace_id=workspace["id"],
            scope="public",
            owner_user_id=owner["id"],
            source_type="rss",
            display_name=f"Shared Feed {index}",
            config={"url": f"https://example.com/shared-{index}.xml"},
            source_key=f"rss:https://example.com/shared-{index}.xml",
        )
        for index in range(2)
    ]
    subscriptions = [
        store.create_subscription(user_id=owner["id"], source_id=source_id)
        for source_id in source_ids
    ]
    source_keys = [f"rss:https://example.com/shared-{index}.xml" for index in range(2)]
    feeds = UserFeedStore(store)
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_shared_provenance",
        payload={
            "schema_version": 2,
            "items": [
                {
                    "id": "rss:shared:item",
                    "title": "Shared item",
                    "source_id": source_ids[0],
                    "source_ids": source_ids,
                    "subscription_id": subscriptions[0]["id"],
                    "subscription_ids": [item["id"] for item in subscriptions],
                    "source_key": source_keys[0],
                    "source_keys": source_keys,
                }
            ],
        },
    )

    store.delete_subscription(subscriptions[0]["id"], user_id=owner["id"])

    item = feeds.latest_snapshot(
        workspace_id=workspace["id"], user_id=owner["id"]
    )["payload"]["items"][0]
    assert item["id"] == "rss:shared:item"
    assert item["source_id"] == source_ids[1]
    assert item["source_ids"] == [source_ids[1]]
    assert item["subscription_id"] == subscriptions[1]["id"]
    assert item["subscription_ids"] == [subscriptions[1]["id"]]
    assert item["source_key"] == source_keys[1]
    assert item["source_keys"] == [source_keys[1]]


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


def test_history_feed_returns_empty_schema_then_single_snapshot_metadata(tmp_path, monkeypatch):
    store, workspace, owner, alice = _store_with_users(tmp_path, monkeypatch)
    service = FeedArchiveService(tmp_path, store=store)

    def fail_global_read(*_args, **_kwargs):
        raise AssertionError("user history must not read global site JSON")

    class FailArticleStore:
        def __init__(self, *_args, **_kwargs):
            raise AssertionError("user history must not read ArticleStore")

    monkeypatch.setattr(FeedArchiveService, "_read_site_json", fail_global_read)
    monkeypatch.setattr("src.services.feed_archive.ArticleStore", FailArticleStore)

    empty_history = service.history_feed(
        workspace_id=workspace["id"],
        user_id=alice["id"],
    )
    _assert_window(empty_history)
    empty_history.pop("window")
    assert empty_history == {
        "schema_version": 2,
        "scope": "user",
        "snapshots": [],
        "items": [],
        "featured_items": [],
        "item_count": 0,
        "total_count": 0,
        "limit": 200,
        "offset": 0,
        "has_more": False,
    }

    current_at = _days_ago(1)
    snapshot = UserFeedStore(store).save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_history_single",
        payload={
            "generated_at": current_at,
            "date": "current",
            "ai_enabled": False,
            "thresholds": {"featured": 8.0},
            "channels": ["AI"],
            "topics": ["Agent"],
            "items": [{"id": "current-only", "title": "Current"}],
            "featured_items": [{"id": "current-only", "title": "Current"}],
        },
    )

    owner_history = service.history_feed(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )
    _assert_window(owner_history)
    owner_history.pop("window")
    assert owner_history == {
        "generated_at": current_at,
        "date": "current",
        "ai_enabled": False,
        "thresholds": {"featured": 8.0},
        "sources": [],
        "channels": [],
        "categories": [],
        "tags": [],
        "topics": [],
        "personal_tags": [],
        "schema_version": 2,
        "scope": "user",
        "snapshots": [
            {
                "snapshot_id": snapshot["id"],
                "generated_at": current_at,
                "item_count": 1,
                "job_id": "job_history_single",
            }
        ],
        "items": [],
        "featured_items": [],
        "item_count": 0,
        "total_count": 0,
        "limit": 200,
        "offset": 0,
        "has_more": False,
    }


def test_history_feed_rebuilds_filter_collections_from_final_history_items(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    history_at = _days_ago(10)
    current_at = _days_ago(1)
    _save_snapshots(
        UserFeedStore(store),
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payloads=[
            {
                "generated_at": history_at,
                "items": [
                    {
                        "id": "history-b",
                        "source": "History Source B",
                        "channel": "History Channel B",
                        "category": "History Category B",
                        "tags": ["History Tag B", "Shared Tag"],
                        "topics": ["History Topic B", "Shared Topic"],
                        "personal_tags": ["History Personal B"],
                    },
                    {
                        "id": "history-c",
                        "source": "History Source C",
                        "channel": "History Channel C",
                        "category": "History Category C",
                        "tags": ["Shared Tag", "History Tag C"],
                        "topics": ["History Topic B", "History Topic C"],
                        "personal_tags": ["History Personal B", "History Personal C"],
                    },
                ],
            },
            {
                "generated_at": current_at,
                "date": "current",
                "ai_enabled": True,
                "thresholds": {"featured": 8.0},
                "tag_library": ["Latest Tag A", "History Tag B", "History Tag C"],
                "personal_tag_library": ["Latest Personal A", "History Personal B"],
                "sources": ["Latest Source A"],
                "channels": ["Latest Channel A"],
                "categories": ["Latest Category A"],
                "tags": ["Latest Tag A"],
                "topics": ["Latest Topic A"],
                "personal_tags": ["Latest Personal A"],
                "items": [
                    {
                        "id": "latest-a",
                        "source": "Latest Source A",
                        "channel": "Latest Channel A",
                        "category": "Latest Category A",
                        "tags": ["Latest Tag A"],
                        "topics": ["Latest Topic A"],
                        "personal_tags": ["Latest Personal A"],
                    }
                ],
            },
        ],
    )

    history = FeedArchiveService(tmp_path, store=store).history_feed(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert {
        key: history[key]
        for key in (
            "sources",
            "channels",
            "categories",
            "tags",
            "topics",
            "personal_tags",
        )
    } == {
        "sources": ["History Source B", "History Source C"],
        "channels": ["History Channel B", "History Channel C"],
        "categories": ["History Category B", "History Category C"],
        "tags": ["History Tag B", "Shared Tag", "History Tag C"],
        "topics": ["History Topic B", "Shared Topic", "History Topic C"],
        "personal_tags": ["History Personal B", "History Personal C"],
    }
    assert history["generated_at"] == current_at
    assert history["date"] == "current"
    assert history["ai_enabled"] is True
    assert history["thresholds"] == {"featured": 8.0}
    assert history["tag_library"] == [
        "Latest Tag A",
        "History Tag B",
        "History Tag C",
    ]
    assert history["personal_tag_library"] == [
        "Latest Personal A",
        "History Personal B",
    ]


def test_history_feed_uses_durable_index_when_v2_snapshot_payload_is_rewritten(tmp_path, monkeypatch):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)
    old_snapshot = feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_v2_empty_old",
        payload={
            "schema_version": 2,
            "generated_at": "2026-07-10T10:00:00+08:00",
            "items": [{"id": "placeholder"}],
        },
    )
    _replace_snapshot_payload(
        store,
        old_snapshot["id"],
        {
            "schema_version": 2,
            "generated_at": "2026-07-10T10:00:00+08:00",
            "items": [],
            "today_items": [{"id": "stale-today-item"}],
        },
    )
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_v2_empty_latest",
        payload={
            "schema_version": 2,
            "generated_at": "2026-07-11T10:00:00+08:00",
            "items": [],
        },
    )

    history = FeedArchiveService(tmp_path, store=store).history_feed(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert [item["id"] for item in history["items"]] == ["placeholder"]


def test_history_feed_does_not_replace_durable_index_from_rewritten_legacy_snapshot(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)
    old_snapshot = feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_legacy_today_old",
        payload={
            "generated_at": "2026-07-10T10:00:00+08:00",
            "items": [{"id": "placeholder"}],
        },
    )
    _replace_snapshot_payload(
        store,
        old_snapshot["id"],
        {
            "generated_at": "2026-07-10T10:00:00+08:00",
            "today_items": [{"id": "legacy-today-item"}],
        },
    )
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_legacy_today_latest",
        payload={
            "generated_at": "2026-07-11T10:00:00+08:00",
            "items": [],
        },
    )

    history = FeedArchiveService(tmp_path, store=store).history_feed(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert [item["id"] for item in history["items"]] == ["placeholder"]


def test_history_feed_strips_remote_media_from_legacy_snapshots_without_rewriting_them(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)
    old_snapshot = feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_legacy_remote_media",
        payload={
            "generated_at": "2026-07-10T10:00:00+08:00",
            "items": [{"id": "placeholder"}],
        },
    )
    remote_url = "https://cdn.example.com/expired.jpg?signature=secret"
    legacy_payload = {
        "generated_at": "2026-07-10T10:00:00+08:00",
        "items": [
            {
                "id": "legacy-remote-media",
                "image_url": remote_url,
                "remote_image_url": remote_url,
                "media_urls": [remote_url, "/api/media/med_local"],
                "remote_media_urls": [remote_url],
                "presentation": {
                    "media": {
                        "images": [
                            {"url": remote_url, "alt": "remote"},
                            {"url": "/api/media/med_local", "alt": "cached"},
                        ],
                        "count": 2,
                    }
                },
            }
        ],
    }
    _replace_snapshot_payload(store, old_snapshot["id"], legacy_payload)
    store.connect().execute(
        """
        UPDATE user_content_items
        SET article_id = ?, item_json = ?
        WHERE workspace_id = ? AND user_id = ? AND article_id = ?
        """,
        (
            "legacy-remote-media",
            json.dumps(legacy_payload["items"][0]),
            workspace["id"],
            owner["id"],
            "placeholder",
        ),
    )
    store.connect().commit()
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_after_legacy_remote_media",
        payload={
            "generated_at": "2026-07-11T10:00:00+08:00",
            "items": [],
        },
    )

    history = FeedArchiveService(tmp_path, store=store).history_feed(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    item = history["items"][0]
    assert item["image_url"] == ""
    assert item["media_urls"] == ["/api/media/med_local"]
    assert "remote_image_url" not in item
    assert "remote_media_urls" not in item
    assert item["presentation"]["media"] == {
        "images": [{"url": "/api/media/med_local", "alt": "cached"}],
        "count": 1,
        "total_image_count": 2,
        "truncated": True,
    }
    stored_payload = store.connect().execute(
        "SELECT payload_json FROM user_feed_snapshots WHERE id = ?",
        (old_snapshot["id"],),
    ).fetchone()["payload_json"]
    assert remote_url in stored_payload


def test_history_feed_uses_effective_time_and_does_not_revive_repeated_items(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)
    oldest_at = _days_ago(12)
    history_at = _days_ago(10)
    current_at = _days_ago(1)
    snapshots = _save_snapshots(
        feeds,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payloads=[
            {
                "generated_at": oldest_at,
                "items": [
                    {"id": "duplicate", "title": "Old duplicate"},
                    {"id": "old-only", "title": "Old only"},
                ],
            },
            {
                "generated_at": history_at,
                "items": [
                    {"id": "newer-only", "title": "Newer only"},
                    {"id": "duplicate", "title": "Newer duplicate"},
                    {"id": "still-current", "title": "Historical current"},
                ],
            },
            {
                "generated_at": current_at,
                "date": "current",
                "items": [
                    {"id": "still-current", "title": "Current version"},
                    {"id": "current-only", "title": "Current only"},
                ],
            },
        ],
    )

    history = FeedArchiveService(tmp_path, store=store).history_feed(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert [item["id"] for item in history["items"]] == [
        "newer-only",
        "still-current",
        "duplicate",
        "old-only",
    ]
    assert next(
        item for item in history["items"] if item["id"] == "duplicate"
    )["title"] == "Newer duplicate"
    assert next(
        item for item in history["items"] if item["id"] == "still-current"
    )["title"] == "Current version"
    assert "current-only" not in {item["id"] for item in history["items"]}
    assert [entry["snapshot_id"] for entry in history["snapshots"]] == [
        snapshots[2]["id"],
        snapshots[1]["id"],
        snapshots[0]["id"],
    ]
    assert history["date"] == "current"
    assert history["item_count"] == 4


def test_history_feed_uses_saved_featured_membership_order_and_current_user_state(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)
    _save_snapshots(
        feeds,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payloads=[
            {
                "generated_at": "2026-07-10T10:00:00+08:00",
                "items": [
                    {"id": "featured-via-id", "score": 0},
                    {"id": "high-score-not-featured", "score": 99},
                    {"id": "featured-via-item", "score": 0},
                ],
                "featured_items": [{"id": "featured-via-item", "score": 0}],
                "featured_item_ids": ["featured-via-id"],
            },
            {
                "generated_at": "2026-07-11T10:00:00+08:00",
                "items": [],
            },
        ],
    )
    expected_state = UserItemStateStore(store).update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="featured-via-id",
        is_read=True,
        is_saved=True,
        is_later=True,
        dismissed=True,
    )

    history = FeedArchiveService(tmp_path, store=store).history_feed(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert [item["id"] for item in history["featured_items"]] == [
        "featured-via-id",
        "featured-via-item",
    ]
    assert "high-score-not-featured" not in {
        item["id"] for item in history["featured_items"]
    }
    assert history["items"][0]["user_state"] == expected_state
    assert history["featured_items"][0]["user_state"] == expected_state


def test_history_feed_caps_items_at_200(tmp_path, monkeypatch):
    store, workspace, owner, _alice = _store_with_users(tmp_path, monkeypatch)
    feeds = UserFeedStore(store)
    history_at = _days_ago(10)
    current_at = _days_ago(1)
    _save_snapshots(
        feeds,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        payloads=[
            {
                "generated_at": history_at,
                "items": [{"id": f"old-{index:03d}"} for index in range(205)],
            },
            {
                "generated_at": current_at,
                "items": [{"id": "current"}],
            },
        ],
    )

    history = FeedArchiveService(tmp_path, store=store).history_feed(
        workspace_id=workspace["id"],
        user_id=owner["id"],
    )

    assert history["item_count"] == 200
    assert len(history["items"]) == 200
    assert history["items"][0]["id"] == "old-000"
    assert history["items"][-1]["id"] == "old-199"
    assert history["total_count"] == 205
    assert history["has_more"] is True


def test_history_feed_queries_durable_items_before_pagination_with_full_provenance(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner, alice = _store_with_users(tmp_path, monkeypatch)
    target_source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Target source",
        config={"url": "https://example.com/target.xml"},
        source_key="rss:https://example.com/target.xml",
    )
    donor_source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="public",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Donor source",
        config={"url": "https://example.com/donor.xml"},
        source_key="rss:https://example.com/donor.xml",
    )
    feeds = UserFeedStore(store)
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_durable_history_old",
        payload={
            "generated_at": "2026-07-01T00:00:00+00:00",
            "items": [
                {
                    "id": "history-a",
                    "title": "First durable result",
                    "source": "Target source",
                    "source_id": target_source_id,
                    "source_ids": [target_source_id],
                    "topics": ["Archive"],
                },
                {
                    "id": "history-b",
                    "title": "Second durable result",
                    "source": "Donor source",
                    "source_id": donor_source_id,
                    "source_ids": [donor_source_id, target_source_id],
                    "presentation": {
                        "content": {"body_text": "Needle in durable body"},
                        "author": {"name": "tsucha_ri"},
                        "taxonomy": {"topics": ["Long tail"]},
                    },
                },
            ],
        },
    )
    for index in range(21):
        feeds.save_snapshot(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            job_id=f"job_durable_history_marker_{index}",
            payload={
                "generated_at": f"2026-07-02T{index:02d}:00:00+00:00",
                "items": [{"id": f"marker-{index:02d}", "title": f"Marker {index}"}],
            },
        )
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_id="job_durable_history_latest",
        payload={
            "generated_at": _days_ago(1),
            "items": [
                {
                    "id": "current-target",
                    "source_id": target_source_id,
                    "source_ids": [target_source_id],
                }
            ],
        },
    )
    feeds.save_snapshot(
        workspace_id=workspace["id"],
        user_id=alice["id"],
        job_id="job_alice_durable_history",
        payload={
            "generated_at": "2026-07-01T00:00:00+00:00",
            "items": [
                {
                    "id": "alice-private-history",
                    "source_id": target_source_id,
                    "source_ids": [target_source_id],
                }
            ],
        },
    )

    service = FeedArchiveService(tmp_path, store=store)
    first_page = service.history_feed(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=target_source_id,
        limit=1,
        offset=0,
    )
    second_page = service.history_feed(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=target_source_id,
        limit=1,
        offset=1,
    )
    searched = service.history_feed(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        source_id=target_source_id,
        q="needle in durable",
        limit=50,
    )

    assert len(first_page["snapshots"]) == 20
    assert first_page["total_count"] == 2
    assert first_page["item_count"] == len(first_page["items"]) == 1
    assert first_page["has_more"] is True
    assert second_page["total_count"] == 2
    assert second_page["has_more"] is False
    assert {
        first_page["items"][0]["id"],
        second_page["items"][0]["id"],
    } == {"history-a", "history-b"}
    assert [item["id"] for item in searched["items"]] == ["history-b"]
    assert "current-target" not in {
        item["id"] for item in first_page["items"] + second_page["items"]
    }
    assert "alice-private-history" not in {
        item["id"] for item in first_page["items"] + second_page["items"]
    }
