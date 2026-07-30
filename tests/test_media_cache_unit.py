from pathlib import Path
from tempfile import TemporaryDirectory
from unittest.mock import AsyncMock, patch

import httpx
import pytest

from src.services import media_cache
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
    assert media_cache.TRUSTED_MEDIA_HOST_SUFFIXES == (
        "cdninstagram.com",
        "fbcdn.net",
        "pbs.twimg.com",
        "github.com",
        "githubusercontent.com",
    )
    assert fetch_public.await_args.kwargs["synthetic_dns_host_suffixes"] == (
        "cdninstagram.com",
        "fbcdn.net",
        "pbs.twimg.com",
        "github.com",
        "githubusercontent.com",
    )


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
