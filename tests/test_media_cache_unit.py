import asyncio
from datetime import datetime, timezone
from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.models import ContentItem, SourceType
from src.services import media_cache
from src.services import network_policy
from src.storage.service_store import ServiceStore


def test_media_cache_download_uses_narrow_known_media_synthetic_dns_suffixes() -> None:
    response = httpx.Response(
        200,
        content=b"\x89PNG\r\n\x1a\nimage-bytes",
        headers={"content-type": "image/png"},
        request=httpx.Request("GET", "https://pbs.twimg.com/profile_images/avatar.png"),
    )
    fetch_public = AsyncMock(return_value=response)
    with TemporaryDirectory() as directory, patch.object(
        media_cache, "fetch_public_http", fetch_public
    ):
        media_cache.MediaCacheService(
            ServiceStore(Path(directory)), data_dir=directory
        )._download("https://pbs.twimg.com/profile_images/avatar.png")

    assert media_cache.X_MEDIA_HOST_SUFFIXES == ("pbs.twimg.com",)
    assert media_cache.GITHUB_MEDIA_HOST_SUFFIXES == (
        "github.com",
        "githubusercontent.com",
    )
    assert media_cache.YOUTUBE_MEDIA_HOST_SUFFIXES == ("googleusercontent.com",)
    assert media_cache.TRUSTED_MEDIA_HOST_SUFFIXES == (
        "cdninstagram.com",
        "fbcdn.net",
        "pbs.twimg.com",
        "github.com",
        "githubusercontent.com",
        "googleusercontent.com",
    )
    assert fetch_public.await_args.kwargs["synthetic_dns_host_suffixes"] == (
        "cdninstagram.com",
        "fbcdn.net",
        "pbs.twimg.com",
        "github.com",
        "githubusercontent.com",
        "googleusercontent.com",
    )


def test_media_cache_download_is_safe_inside_a_running_event_loop() -> None:
    response = httpx.Response(
        200,
        content=b"\x89PNG\r\n\x1a\navatar",
        headers={"content-type": "image/png"},
        request=httpx.Request("GET", "https://cdninstagram.com/avatar.png"),
    )
    fetch_public = AsyncMock(return_value=response)

    async def download() -> tuple[bytes, str]:
        with TemporaryDirectory() as directory, patch.object(
            media_cache, "fetch_public_http", fetch_public
        ):
            return media_cache.MediaCacheService(
                ServiceStore(Path(directory)), data_dir=directory
            )._download("https://cdninstagram.com/avatar.png")

    data, mime_type = asyncio.run(download())

    assert data == response.content
    assert mime_type == "image/png"
    fetch_public.assert_awaited_once()


def test_media_cache_allows_youtube_avatar_cdn_synthetic_dns(monkeypatch) -> None:
    def fake_getaddrinfo(_host, port, *, type):
        return [(2, 1, 6, "", ("198.18.0.120", port))]

    monkeypatch.setattr(network_policy.socket, "getaddrinfo", fake_getaddrinfo)

    target = network_policy.resolve_public_http_url(
        "https://yt3.googleusercontent.com/channel-avatar.png",
        synthetic_dns_host_suffixes=media_cache.TRUSTED_MEDIA_HOST_SUFFIXES,
    )

    assert target.addresses == ("198.18.0.120",)


def test_default_avatar_invalidation_inside_outer_transaction_fails_before_mutation(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Rollback avatar",
        config={"url": "https://example.com/rollback-avatar.xml"},
    )
    avatar_path = tmp_path / "media" / "rollback-avatar.png"
    avatar_path.parent.mkdir(parents=True, exist_ok=True)
    avatar_bytes = b"\x89PNG\r\n\x1a\nrollback-avatar"
    avatar_path.write_bytes(avatar_bytes)
    now = "2026-07-17T00:00:00+00:00"
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO media_assets (
            id, workspace_id, source_id, asset_kind, local_path, mime_type,
            byte_size, checksum, visibility_scope, status, created_at, updated_at
        ) VALUES ('med_rollback_avatar', ?, ?, 'source_avatar',
                  'media/rollback-avatar.png', 'image/png', 23, 'checksum',
                  'private', 'ready', ?, ?)
        """,
        (workspace["id"], source_id, now, now),
    )
    conn.commit()
    conn.execute("BEGIN IMMEDIATE")

    with pytest.raises(RuntimeError, match="post_commit_cleanup is required"):
        media_cache.MediaCacheService(
            store, data_dir=tmp_path
        ).invalidate_source_avatar(
            workspace_id=workspace["id"], source_id=source_id
        )

    assert conn.execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'med_rollback_avatar'"
    ).fetchone()[0] == 1
    assert avatar_path.read_bytes() == avatar_bytes
    conn.rollback()

    assert conn.execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'med_rollback_avatar'"
    ).fetchone()[0] == 1
    assert avatar_path.read_bytes() == avatar_bytes


def test_avatar_cache_rollback_restores_old_file_and_removes_created_file(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Transactional avatar",
        config={"url": "https://example.com/avatar.xml"},
    )
    old_path = tmp_path / "media" / "old-avatar.png"
    old_path.parent.mkdir(parents=True, exist_ok=True)
    old_path.write_bytes(b"\x89PNG\r\n\x1a\nold-avatar")
    now = "2026-07-17T00:00:00+00:00"
    conn = store.connect()
    conn.execute(
        """
        INSERT INTO media_assets (
            id, workspace_id, source_id, asset_kind, remote_url, local_path,
            mime_type, byte_size, checksum, visibility_scope, status,
            created_at, updated_at
        ) VALUES ('med_old_avatar', ?, ?, 'source_avatar',
                  'https://old.example/avatar.png', 'media/old-avatar.png',
                  'image/png', 18, 'old-checksum', 'private', 'ready', ?, ?)
        """,
        (workspace["id"], source_id, now, now),
    )
    conn.commit()

    cleanup = media_cache.PostCommitMediaCleanup()
    conn.execute("BEGIN IMMEDIATE")
    result = media_cache.MediaCacheService(
        store,
        data_dir=tmp_path,
        fetch_image=lambda _url: (b"\x89PNG\r\n\x1a\nnew-avatar", "image/png"),
    ).cache_source_avatar_candidates(
        workspace_id=workspace["id"],
        source_id=source_id,
        remote_urls=["https://new.example/avatar.png"],
        commit=False,
        media_cleanup=cleanup,
    )

    assert result["status"] == "stored"
    new_row = conn.execute(
        "SELECT id, local_path FROM media_assets WHERE id = ?",
        (result["asset_id"],),
    ).fetchone()
    assert new_row is not None
    new_path = tmp_path / str(new_row["local_path"])
    assert new_path.exists()
    assert old_path.exists()
    assert conn.execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'med_old_avatar'"
    ).fetchone()[0] == 0

    conn.rollback()
    cleanup.discard()

    assert conn.execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = 'med_old_avatar'"
    ).fetchone()[0] == 1
    assert conn.execute(
        "SELECT COUNT(*) FROM media_assets WHERE id = ?",
        (result["asset_id"],),
    ).fetchone()[0] == 0
    assert old_path.exists()
    assert not new_path.exists()


def test_item_metadata_is_restored_when_outer_media_stage_partially_fails(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    now = datetime.now(timezone.utc)
    first = ContentItem(
        id="rss:media-first",
        source_type=SourceType.RSS,
        title="First",
        url="https://example.com/first",
        published_at=now,
        metadata={
            "remote_media_urls": ["https://media.example/first.png"],
            "image_url": "https://media.example/first.png",
        },
    )
    second = ContentItem(
        id="rss:media-second",
        source_type=SourceType.RSS,
        title="Second",
        url="https://example.com/second",
        published_at=now,
        metadata={"remote_media_urls": 1},
    )
    original_first = dict(first.metadata)
    original_second = dict(second.metadata)
    cleanup = media_cache.PostCommitMediaCleanup()
    connection = store.connect()
    connection.execute("BEGIN IMMEDIATE")

    with pytest.raises(TypeError):
        media_cache.MediaCacheService(
            store,
            data_dir=tmp_path,
            fetch_image=lambda _url: (
                b"\x89PNG\r\n\x1a\nmedia-bytes",
                "image/png",
            ),
        ).cache_items(
            workspace_id=workspace["id"],
            user_id=owner["id"],
            items=[first, second],
            commit=False,
            media_cleanup=cleanup,
        )

    connection.rollback()
    cleanup.discard()

    assert first.metadata == original_first
    assert second.metadata == original_second
    assert connection.execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 0
    assert not [path for path in (tmp_path / "media").rglob("*") if path.is_file()]


def test_chmod_failure_does_not_leave_untracked_media_file(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    item = ContentItem(
        id="rss:chmod-failure",
        source_type=SourceType.RSS,
        title="Chmod failure",
        url="https://example.com/chmod-failure",
        published_at=datetime.now(timezone.utc),
        metadata={
            "remote_media_urls": ["https://media.example/chmod-failure.png"]
        },
    )
    monkeypatch.setattr(
        media_cache.os,
        "chmod",
        lambda *_args, **_kwargs: (_ for _ in ()).throw(OSError("chmod failed")),
    )

    media_cache.MediaCacheService(
        store,
        data_dir=tmp_path,
        fetch_image=lambda _url: (
            b"\x89PNG\r\n\x1a\nmedia-bytes",
            "image/png",
        ),
    ).cache_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[item],
    )

    assert store.connect().execute("SELECT COUNT(*) FROM media_assets").fetchone()[0] == 0
    assert not [path for path in (tmp_path / "media").rglob("*") if path.is_file()]
