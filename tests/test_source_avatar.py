from __future__ import annotations

import httpx

from src.services.feed_run import (
    FeedRunResult,
    SourceAvatarHint,
    SourceOutcome,
    safe_run_diagnostics,
)
from src.services.media_cache import MAX_SOURCE_AVATAR_BYTES, MediaCacheService
from src.services.source_avatar import SourceAvatarService
from src.services.user_content_store import UserContentStore
from src.storage.service_store import ServiceStore


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "owner-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    return (
        store,
        store.get_default_workspace(),
        store.get_user_by_username("owner"),
    )


def _png(value: bytes = b"avatar") -> tuple[bytes, str]:
    return b"\x89PNG\r\n\x1a\n" + value, "image/png"


def test_source_level_candidate_caches_without_content_item(tmp_path, monkeypatch):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Zero-item RSS",
        config={"url": "https://example.com/feed.xml"},
    )
    cache = MediaCacheService(
        store,
        data_dir=tmp_path,
        fetch_image=lambda _url: _png(),
    )

    result = cache.cache_source_avatar_candidates(
        workspace_id=workspace["id"],
        source_id=source_id,
        remote_urls=["https://example.com/avatar.png"],
    )

    assert result["status"] == "stored"
    assert store.connect().execute(
        "SELECT COUNT(*) FROM user_content_items"
    ).fetchone()[0] == 0
    avatar = cache.avatar_for_source(
        workspace_id=workspace["id"],
        source_id=source_id,
    )
    assert avatar["remote_url"] == "https://example.com/avatar.png"
    assert (tmp_path / avatar["local_path"]).is_file()


def test_source_avatar_candidates_enforce_the_smaller_avatar_byte_limit(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Bounded avatar",
        config={"url": "https://example.com/feed.xml"},
    )
    cache = MediaCacheService(
        store,
        data_dir=tmp_path,
        fetch_image=lambda _url: (
            b"\x89PNG\r\n\x1a\n" + b"x" * MAX_SOURCE_AVATAR_BYTES,
            "image/png",
        ),
    )

    result = cache.cache_source_avatar_candidates(
        workspace_id=workspace["id"],
        source_id=source_id,
        remote_urls=["https://example.com/oversized.png"],
    )

    assert result["status"] == "failed"
    assert cache.avatar_for_source(
        workspace_id=workspace["id"],
        source_id=source_id,
    ) is None


def test_avatar_hints_never_enter_public_run_diagnostics():
    hint = SourceAvatarHint(
        source_id="source-1",
        remote_url="https://example.com/avatar.png?token=private",
        origin="rss_feed_icon",
    )
    outcome = SourceOutcome(
        source_id="source-1",
        subscription_id=None,
        source_key="rss:source-1",
        analysis_mode="full",
        status="succeeded",
        fetched_count=0,
        avatar_hints=(hint,),
    )
    result = FeedRunResult(
        run_id="run-avatar",
        status="succeeded",
        started_at="2026-07-30T00:00:00+00:00",
        finished_at="2026-07-30T00:00:01+00:00",
        source_outcomes=(outcome,),
    )

    diagnostics = safe_run_diagnostics(result, item_count=0)

    assert "avatar" not in diagnostics["source_outcomes"][0]
    assert "private" not in repr(result)
    assert "private" not in str(diagnostics)


def test_bilibili_fallback_requires_uid_and_caches_search_avatar(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="食贫道",
        config={
            "provider": "rsshub",
            "site": "bilibili",
            "route_key": "user_video",
            "params": {"uid": "39627524"},
        },
    )
    calls = []

    class Search:
        def avatar_for_uid(self, *, query, uid):
            calls.append((query, uid))
            return "https://i0.hdslb.com/bfs/face/avatar.jpg"

    cache = MediaCacheService(
        store,
        data_dir=tmp_path,
        fetch_image=lambda _url: _png(b"bilibili"),
    )
    service = SourceAvatarService(
        store,
        data_dir=str(tmp_path),
        media_cache=cache,
        bilibili_search=Search(),
    )

    result = service.refresh_sources(
        workspace_id=workspace["id"],
        source_ids=[source_id],
        resolve_missing_source_ids=[source_id],
    )

    assert calls == [("食贫道", "39627524")]
    assert result[0].status == "stored"
    assert result[0].origin == "bilibili_user_search"


def test_github_fallback_uses_the_catalog_owner_without_content(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="github_release",
        display_name="Codex releases",
        config={"owner": "openai", "repo": "codex"},
    )
    requested = []
    cache = MediaCacheService(
        store,
        data_dir=tmp_path,
        fetch_image=lambda url: requested.append(url) or _png(b"github"),
    )

    result = SourceAvatarService(
        store,
        data_dir=str(tmp_path),
        media_cache=cache,
    ).refresh_sources(
        workspace_id=workspace["id"],
        source_ids=[source_id],
        resolve_missing_source_ids=[source_id],
    )

    assert requested == ["https://github.com/openai.png?size=128"]
    assert result[0].status == "stored"
    assert result[0].origin == "github_owner"


def test_reddit_fallback_requires_the_about_identity_to_match(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="reddit_subreddit",
        display_name="LocalLLaMA",
        config={"subreddit": "LocalLLaMA"},
    )
    cache = MediaCacheService(
        store,
        data_dir=tmp_path,
        fetch_image=lambda _url: _png(b"reddit"),
    )
    metadata = (
        b'{"data":{"display_name":"DifferentCommunity",'
        b'"community_icon":"https://styles.redditmedia.com/avatar.png"}}'
    )

    result = SourceAvatarService(
        store,
        data_dir=str(tmp_path),
        media_cache=cache,
        fetch_metadata=lambda *_args: (metadata, "application/json"),
    ).refresh_sources(
        workspace_id=workspace["id"],
        source_ids=[source_id],
        resolve_missing_source_ids=[source_id],
    )

    assert result[0].status == "candidate_missing"
    assert cache.avatar_for_source(
        workspace_id=workspace["id"],
        source_id=source_id,
    ) is None


def test_rss_favicon_fallback_is_bounded_and_accepts_ico(tmp_path, monkeypatch):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Site feed",
        config={"url": "https://example.com/feed.xml"},
    )
    metadata_calls = []

    def fetch_metadata(url, _accept, _max_bytes):
        metadata_calls.append(url)
        if url.endswith("feed.xml"):
            return (
                b"<rss><channel><title>Site</title>"
                b"<link>https://example.com/news</link></channel></rss>",
                "application/rss+xml",
            )
        return (
            b'<html><head><link rel="icon" href="/favicon.ico"></head></html>',
            "text/html",
        )

    def fetch_image(url):
        assert url == "https://example.com/favicon.ico"
        return b"\x00\x00\x01\x00" + b"ico", "image/x-icon"

    cache = MediaCacheService(
        store,
        data_dir=tmp_path,
        fetch_image=fetch_image,
    )
    service = SourceAvatarService(
        store,
        data_dir=str(tmp_path),
        media_cache=cache,
        fetch_metadata=fetch_metadata,
    )

    result = service.refresh_sources(
        workspace_id=workspace["id"],
        source_ids=[source_id],
        resolve_missing_source_ids=[source_id],
    )

    assert metadata_calls == [
        "https://example.com/feed.xml",
        "https://example.com/news",
    ]
    assert result[0].status == "stored"
    avatar = cache.avatar_for_source(
        workspace_id=workspace["id"],
        source_id=source_id,
    )
    assert avatar["mime_type"] == "image/x-icon"


def test_youtube_channel_avatar_uses_canonical_channel_identity(tmp_path, monkeypatch):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    channel_id = "UCabcdefghijklmnopqrstuv"
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Example Channel",
        config={
            "url": (
                "https://www.youtube.com/feeds/videos.xml?"
                f"channel_id={channel_id}"
            )
        },
    )
    requested_pages = []
    requested_images = []
    cache = MediaCacheService(
        store,
        data_dir=tmp_path,
        fetch_image=lambda url: requested_images.append(url) or _png(b"youtube"),
    )
    service = SourceAvatarService(
        store,
        data_dir=str(tmp_path),
        media_cache=cache,
        fetch_metadata=lambda *_args: (_ for _ in ()).throw(
            AssertionError("YouTube must not fall back to a generic favicon")
        ),
        fetch_youtube_metadata=lambda url: (
            requested_pages.append(url)
            or (
                b'<html><head><meta content="https://yt3.googleusercontent.com/'
                b'channel-avatar=s900-c-k-c0x00ffffff-no-rj&amp;v=1" '
                b'property="og:image"></head></html>',
                "text/html; charset=utf-8",
            )
        ),
    )

    result = service.refresh_sources(
        workspace_id=workspace["id"],
        source_ids=[source_id],
        resolve_missing_source_ids=[source_id],
    )

    assert requested_pages == [f"https://www.youtube.com/channel/{channel_id}"]
    assert requested_images == [
        "https://yt3.googleusercontent.com/"
        "channel-avatar=s900-c-k-c0x00ffffff-no-rj&v=1"
    ]
    assert result[0].status == "stored"
    assert result[0].origin == "youtube_channel_og_image"


def test_youtube_channel_avatar_does_not_use_generic_favicon_when_missing(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="No avatar channel",
        config={
            "url": (
                "https://www.youtube.com/feeds/videos.xml?"
                "channel_id=UCabcdefghijklmnopqrstuv"
            )
        },
    )
    service = SourceAvatarService(
        store,
        data_dir=str(tmp_path),
        fetch_metadata=lambda *_args: (_ for _ in ()).throw(
            AssertionError("YouTube must not use the generic RSS favicon path")
        ),
        fetch_youtube_metadata=lambda _url: (
            b"<html><head><link rel='icon' href='/favicon.ico'></head></html>",
            "text/html",
        ),
    )

    result = service.refresh_sources(
        workspace_id=workspace["id"],
        source_ids=[source_id],
        resolve_missing_source_ids=[source_id],
    )

    assert result[0].status == "candidate_missing"


def test_youtube_channel_metadata_request_uses_bounded_no_redirect_fetch(monkeypatch):
    calls = []

    async def fetch(url, **kwargs):
        calls.append((url, kwargs))
        return httpx.Response(
            200,
            headers={"content-type": "text/html"},
            content=b"<html></html>",
            request=httpx.Request("GET", url),
        )

    monkeypatch.setattr("src.services.source_avatar.fetch_public_http", fetch)

    payload, content_type = SourceAvatarService._download_youtube_metadata(
        "https://www.youtube.com/channel/UCabcdefghijklmnopqrstuv"
    )

    assert payload == b"<html></html>"
    assert content_type == "text/html"
    assert calls[0][1]["max_redirects"] == 0
    assert calls[0][1]["max_response_bytes"] == 2_000_000
    assert calls[0][1]["allow_partial_response"] is True


def test_current_avatar_projection_replaces_stale_snapshot_url(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Projected source",
        config={"url": "https://example.com/feed.xml"},
    )
    cache = MediaCacheService(
        store,
        data_dir=tmp_path,
        fetch_image=lambda _url: _png(),
    )
    cached = cache.cache_source_avatar_candidates(
        workspace_id=workspace["id"],
        source_id=source_id,
        remote_urls=["https://example.com/current.png"],
    )
    item = {
        "id": "rss:item:1",
        "source_id": source_id,
        "presentation": {
            "source": {
                "id": source_id,
                "name": "Projected source",
                "avatar_url": "/api/media/stale",
            }
        },
    }

    UserContentStore(store)._apply_current_source_avatars(
        workspace_id=workspace["id"],
        items=[item],
    )

    assert item["presentation"]["source"]["avatar_url"] == (
        f"/api/media/{cached['asset_id']}"
    )


def test_paid_social_backfill_never_fetches_metadata(tmp_path, monkeypatch):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="X profile",
        config={"platform": "x", "kind": "profile", "target": "openai"},
    )

    def forbidden(*_args):
        raise AssertionError("paid social backfill must not fetch")

    result = SourceAvatarService(
        store,
        data_dir=str(tmp_path),
        fetch_metadata=forbidden,
    ).refresh_sources(
        workspace_id=workspace["id"],
        source_ids=[source_id],
        resolve_missing_source_ids=[source_id],
    )

    assert result[0].status == "candidate_missing"
