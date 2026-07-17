"""Authenticated same-origin cache for captured content images and source avatars."""

from __future__ import annotations

import asyncio
import hashlib
import os
import tempfile
import uuid
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import urlsplit, urlunsplit

from ..models import ContentItem
from ..storage.service_store import ServiceStore
from .network_policy import fetch_public_http


MAX_IMAGES_PER_ITEM = 6
MAX_IMAGE_BYTES = 8 * 1024 * 1024
INSTAGRAM_MEDIA_HOST_SUFFIXES = ("cdninstagram.com", "fbcdn.net")
X_MEDIA_HOST_SUFFIXES = ("pbs.twimg.com",)
TRUSTED_MEDIA_HOST_SUFFIXES = (
    *INSTAGRAM_MEDIA_HOST_SUFFIXES,
    *X_MEDIA_HOST_SUFFIXES,
)
SOURCE_AVATAR_RECHECK_AFTER = timedelta(hours=24)


def _now_iso() -> str:
    return datetime.now(timezone.utc).isoformat()


def _new_id() -> str:
    return f"med_{uuid.uuid4().hex}"


class PostCommitMediaCleanup:
    """Collect private filesystem cleanup until the owning DB commit succeeds."""

    def __init__(self) -> None:
        self._paths: set[Path] = set()
        self._closed = False

    def add(self, path: Path) -> None:
        if self._closed:
            raise RuntimeError("post-commit media cleanup is already closed")
        self._paths.add(path)

    def run(self) -> int:
        if self._closed:
            return 0
        paths = tuple(self._paths)
        self._paths.clear()
        self._closed = True
        removed = 0
        for path in paths:
            try:
                path.unlink(missing_ok=True)
                removed += 1
            except OSError:
                continue
        return removed

    def discard(self) -> None:
        self._paths.clear()
        self._closed = True


def _remote_identity(url: str) -> str:
    """Return a stable remote identity without rotating signature parameters."""

    try:
        parsed = urlsplit(str(url or "").strip())
        hostname = (parsed.hostname or "").lower()
        if not hostname:
            return ""
        port = parsed.port
    except ValueError:
        return ""
    authority = f"{hostname}:{port}" if port is not None else hostname
    return urlunsplit((parsed.scheme.lower(), authority, parsed.path, "", ""))


def _detected_image_type(data: bytes) -> tuple[str, str] | None:
    if data.startswith(b"\x89PNG\r\n\x1a\n"):
        return "image/png", ".png"
    if data.startswith(b"\xff\xd8\xff"):
        return "image/jpeg", ".jpg"
    if data.startswith((b"GIF87a", b"GIF89a")):
        return "image/gif", ".gif"
    if len(data) >= 12 and data.startswith(b"RIFF") and data[8:12] == b"WEBP":
        return "image/webp", ".webp"
    return None


class MediaCacheService:
    """Download bounded image assets and rewrite items to protected local URLs."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        data_dir: Path | str,
        fetch_image: Callable[[str], tuple[bytes, str]] | None = None,
    ) -> None:
        self.store = store
        self.data_dir = Path(data_dir)
        self.media_dir = self.data_dir / "media"
        self._fetch_image = fetch_image or self._download

    def cache_items(
        self,
        *,
        workspace_id: str,
        user_id: str,
        items: list[ContentItem],
    ) -> None:
        for item in items:
            self._cache_item(workspace_id=workspace_id, user_id=user_id, item=item)
        self.store.connect().commit()

    def _cache_item(self, *, workspace_id: str, user_id: str, item: ContentItem) -> None:
        metadata = item.metadata
        source_id = str(metadata.get("source_id") or "") or None
        remote_urls = self._unique_urls(
            [
                *(metadata.get("remote_media_urls") or []),
                *(metadata.get("media_urls") or []),
                metadata.get("remote_image_url"),
                metadata.get("image_url"),
            ]
        )[:MAX_IMAGES_PER_ITEM]
        metadata["remote_media_urls"] = remote_urls
        local_urls: list[str] = []
        for index, remote_url in enumerate(remote_urls):
            asset = self._existing_asset(
                workspace_id=workspace_id,
                user_id=user_id,
                source_id=source_id,
                article_id=item.id,
                asset_kind="content_image",
                remote_url=remote_url,
            )
            if asset is None:
                asset = self._cache_url(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    source_id=source_id,
                    article_id=item.id,
                    asset_kind="content_image",
                    remote_url=remote_url,
                    alt=str(item.title or f"图片 {index + 1}"),
                    visibility_scope="private",
                )
            if asset is not None:
                local_urls.append(f"/api/media/{asset['id']}")
        metadata["media_urls"] = local_urls
        metadata["image_url"] = local_urls[0] if local_urls else ""

        if source_id:
            avatar = self.avatar_for_source(workspace_id=workspace_id, source_id=source_id)
            avatar_remote = next(
                iter(
                    self._unique_urls(
                        [
                            metadata.get("author_avatar_url"),
                            metadata.get("source_avatar_url"),
                            metadata.get("profile_pic_url"),
                            metadata.get("feed_icon_url"),
                        ]
                    )
                ),
                "",
            )
            source = self.store.get_source(source_id)
            if avatar_remote and source:
                avatar = self._refresh_source_avatar(
                    workspace_id=workspace_id,
                    source_id=source_id,
                    remote_url=avatar_remote,
                    alt=str(source.get("display_name") or item.author or "来源头像"),
                    visibility_scope=str(source.get("scope") or "private"),
                    current=avatar,
                )
            metadata["avatar_url"] = f"/api/media/{avatar['id']}" if avatar else ""

    @staticmethod
    def _avatar_is_recent(avatar: dict[str, Any]) -> bool:
        try:
            updated_at = datetime.fromisoformat(str(avatar.get("updated_at") or ""))
        except ValueError:
            return False
        if updated_at.tzinfo is None:
            updated_at = updated_at.replace(tzinfo=timezone.utc)
        return datetime.now(timezone.utc) - updated_at.astimezone(timezone.utc) < SOURCE_AVATAR_RECHECK_AFTER

    def _refresh_source_avatar(
        self,
        *,
        workspace_id: str,
        source_id: str,
        remote_url: str,
        alt: str,
        visibility_scope: str,
        current: dict[str, Any] | None,
    ) -> dict[str, Any] | None:
        current_identity = _remote_identity(str((current or {}).get("remote_url") or ""))
        candidate_identity = _remote_identity(remote_url)
        if (
            current is not None
            and current_identity
            and current_identity == candidate_identity
            and self._avatar_is_recent(current)
        ):
            return current

        prepared = self._prepare_image(remote_url)
        if prepared is None:
            return current
        data, mime_type, suffix, checksum = prepared
        if current is not None and str(current.get("checksum") or "") == checksum:
            now = _now_iso()
            self.store.connect().execute(
                "UPDATE media_assets SET remote_url = ?, updated_at = ? WHERE id = ?",
                (remote_url, now, current["id"]),
            )
            return self.asset(str(current["id"]))

        candidate = self._store_prepared_asset(
            workspace_id=workspace_id,
            user_id=None,
            source_id=source_id,
            article_id=None,
            asset_kind="source_avatar",
            remote_url=remote_url,
            alt=alt,
            visibility_scope=visibility_scope,
            data=data,
            mime_type=mime_type,
            suffix=suffix,
            checksum=checksum,
        )
        if candidate is None:
            return current
        self._prune_source_avatars(
            workspace_id=workspace_id,
            source_id=source_id,
            keep_id=str(candidate["id"]),
        )
        return candidate

    def _cache_url(
        self,
        *,
        workspace_id: str,
        user_id: str | None,
        source_id: str | None,
        article_id: str | None,
        asset_kind: str,
        remote_url: str,
        alt: str,
        visibility_scope: str,
    ) -> dict[str, Any] | None:
        prepared = self._prepare_image(remote_url)
        if prepared is None:
            return None
        data, mime_type, suffix, checksum = prepared
        return self._store_prepared_asset(
            workspace_id=workspace_id,
            user_id=user_id,
            source_id=source_id,
            article_id=article_id,
            asset_kind=asset_kind,
            remote_url=remote_url,
            alt=alt,
            visibility_scope=visibility_scope,
            data=data,
            mime_type=mime_type,
            suffix=suffix,
            checksum=checksum,
        )

    def _prepare_image(self, remote_url: str) -> tuple[bytes, str, str, str] | None:
        try:
            data, _declared_mime = self._fetch_image(remote_url)
        except Exception:
            return None
        if not data or len(data) > MAX_IMAGE_BYTES:
            return None
        detected = _detected_image_type(data)
        if detected is None:
            return None
        mime_type, suffix = detected
        return data, mime_type, suffix, hashlib.sha256(data).hexdigest()

    def _store_prepared_asset(
        self,
        *,
        workspace_id: str,
        user_id: str | None,
        source_id: str | None,
        article_id: str | None,
        asset_kind: str,
        remote_url: str,
        alt: str,
        visibility_scope: str,
        data: bytes,
        mime_type: str,
        suffix: str,
        checksum: str,
    ) -> dict[str, Any] | None:
        asset_id = _new_id()
        relative_path = Path("media") / checksum[:2] / f"{asset_id}{suffix}"
        destination = self.data_dir / relative_path
        destination.parent.mkdir(parents=True, exist_ok=True)
        temporary_path: Path | None = None
        try:
            with tempfile.NamedTemporaryFile(
                dir=destination.parent,
                prefix=f".{asset_id}-",
                suffix=".tmp",
                delete=False,
            ) as handle:
                handle.write(data)
                handle.flush()
                os.fsync(handle.fileno())
                temporary_path = Path(handle.name)
            os.replace(temporary_path, destination)
            os.chmod(destination, 0o600)
        except OSError:
            if temporary_path is not None:
                temporary_path.unlink(missing_ok=True)
            return None
        now = _now_iso()
        self.store.connect().execute(
            """
            INSERT INTO media_assets (
                id, workspace_id, user_id, source_id, article_id,
                asset_kind, remote_url, local_path, mime_type, byte_size,
                checksum, alt, visibility_scope, status, created_at, updated_at
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'ready', ?, ?)
            """,
            (
                asset_id,
                workspace_id,
                user_id,
                source_id,
                article_id,
                asset_kind,
                remote_url,
                str(relative_path),
                mime_type,
                len(data),
                checksum,
                alt[:240],
                visibility_scope,
                now,
                now,
            ),
        )
        return self.asset(asset_id)

    def _prune_source_avatars(
        self,
        *,
        workspace_id: str,
        source_id: str,
        keep_id: str,
    ) -> None:
        rows = self.store.connect().execute(
            """
            SELECT id, local_path FROM media_assets
            WHERE workspace_id = ? AND source_id = ?
              AND asset_kind = 'source_avatar' AND id != ?
            """,
            (workspace_id, source_id, keep_id),
        ).fetchall()
        self.store.connect().execute(
            """
            DELETE FROM media_assets
            WHERE workspace_id = ? AND source_id = ?
              AND asset_kind = 'source_avatar' AND id != ?
            """,
            (workspace_id, source_id, keep_id),
        )
        media_root = self.media_dir.resolve()
        for row in rows:
            path = (self.data_dir / str(row["local_path"])).resolve()
            if path.is_relative_to(media_root):
                path.unlink(missing_ok=True)

    def _download(self, url: str) -> tuple[bytes, str]:
        response = asyncio.run(
            fetch_public_http(
                url,
                headers={"Accept": "image/*"},
                timeout=15.0,
                max_response_bytes=MAX_IMAGE_BYTES,
                synthetic_dns_host_suffixes=TRUSTED_MEDIA_HOST_SUFFIXES,
            )
        )
        response.raise_for_status()
        return response.content, str(response.headers.get("content-type") or "")

    def asset(self, asset_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            "SELECT * FROM media_assets WHERE id = ? AND status = 'ready'",
            (asset_id,),
        ).fetchone()
        return dict(row) if row is not None else None

    def avatar_for_source(self, *, workspace_id: str, source_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            """
            SELECT * FROM media_assets
            WHERE workspace_id = ? AND source_id = ?
              AND asset_kind = 'source_avatar' AND status = 'ready'
            ORDER BY created_at DESC, id DESC LIMIT 1
            """,
            (workspace_id, source_id),
        ).fetchone()
        return dict(row) if row is not None else None

    def invalidate_source_avatar(
        self,
        *,
        workspace_id: str,
        source_id: str,
        post_commit_cleanup: PostCommitMediaCleanup | None = None,
    ) -> int:
        """Remove a cached avatar after the source identity changes."""

        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        cleanup = post_commit_cleanup or PostCommitMediaCleanup()
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            rows = conn.execute(
                """
                SELECT id, local_path FROM media_assets
                WHERE workspace_id = ? AND source_id = ? AND asset_kind = 'source_avatar'
                """,
                (workspace_id, source_id),
            ).fetchall()
            conn.execute(
                """
                DELETE FROM media_assets
                WHERE workspace_id = ? AND source_id = ? AND asset_kind = 'source_avatar'
                """,
                (workspace_id, source_id),
            )
            media_root = self.media_dir.resolve()
            for row in rows:
                path = (self.data_dir / str(row["local_path"])).resolve()
                if path.is_relative_to(media_root):
                    cleanup.add(path)
            if owns_transaction:
                conn.commit()
                cleanup.run()
            return len(rows)
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
                cleanup.discard()
            raise

    def authorized_asset(
        self,
        *,
        asset_id: str,
        workspace_id: str,
        user_id: str,
    ) -> dict[str, Any] | None:
        asset = self.asset(asset_id)
        if asset is None or asset["workspace_id"] != workspace_id:
            return None
        if asset.get("user_id"):
            return asset if asset["user_id"] == user_id else None
        source_id = asset.get("source_id")
        if not source_id:
            return None
        source = self.store.get_source(str(source_id))
        if source is None or source["workspace_id"] != workspace_id:
            return None
        if source["scope"] in {"public", "workspace"}:
            return asset
        return asset if source.get("owner_user_id") == user_id else None

    def _existing_asset(
        self,
        *,
        workspace_id: str,
        user_id: str | None,
        source_id: str | None,
        article_id: str | None,
        asset_kind: str,
        remote_url: str,
    ) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            """
            SELECT * FROM media_assets
            WHERE workspace_id = ? AND user_id IS ? AND source_id IS ?
              AND article_id IS ? AND asset_kind = ? AND remote_url = ?
              AND status = 'ready'
            ORDER BY created_at DESC LIMIT 1
            """,
            (workspace_id, user_id, source_id, article_id, asset_kind, remote_url),
        ).fetchone()
        return dict(row) if row is not None else None

    @staticmethod
    def _unique_urls(values: list[Any]) -> list[str]:
        result: list[str] = []
        for value in values:
            url = str(value or "").strip()
            if not url.startswith(("https://", "http://")) or url in result:
                continue
            result.append(url)
        return result
