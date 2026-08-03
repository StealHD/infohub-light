"""Source-level avatar discovery and caching independent of content selection."""

from __future__ import annotations

import asyncio
import html
import json
from dataclasses import dataclass
from html.parser import HTMLParser
from typing import Any, Callable, Iterable
from urllib.parse import quote, urljoin

import feedparser

from ..rsshub import (
    BILIBILI_SITE,
    BILIBILI_USER_VIDEO_ROUTE,
    is_managed_rsshub_config,
)
from ..storage.service_store import ServiceStore
from .bilibili_user_search import BilibiliUserSearchService
from .feed_run import FeedRunResult, SourceAvatarHint
from .media_cache import MediaCacheService, PostCommitMediaCleanup
from .network_policy import fetch_public_http


MAX_AVATAR_METADATA_BYTES = 512_000


@dataclass(frozen=True, slots=True)
class SourceAvatarRefresh:
    source_id: str
    status: str
    origin: str = ""


class _FaviconParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.casefold() != "link":
            return
        values = {key.casefold(): str(value or "") for key, value in attrs}
        rel = {part.casefold() for part in values.get("rel", "").split()}
        if not rel.intersection({"icon", "shortcut", "apple-touch-icon"}):
            return
        href = values.get("href", "").strip()
        if href and href not in self.hrefs:
            self.hrefs.append(href)


def _http_url(base_url: str, value: Any) -> str:
    candidate = urljoin(base_url, str(value or "").strip())
    return candidate if candidate.startswith(("https://", "http://")) else ""


def _feed_hints(payload: bytes, feed_url: str, source_id: str) -> list[SourceAvatarHint]:
    parsed = feedparser.parse(payload)
    feed = parsed.feed if isinstance(parsed.feed, dict) else {}
    image = feed.get("image") if isinstance(feed.get("image"), dict) else {}
    hints: list[SourceAvatarHint] = []
    for value in (
        image.get("href"),
        image.get("url"),
        feed.get("icon"),
        feed.get("logo"),
    ):
        url = _http_url(feed_url, value)
        if url:
            hints.append(
                SourceAvatarHint(
                    source_id=source_id,
                    remote_url=url,
                    origin="rss_feed_icon",
                )
            )
            break
    homepage = _http_url(feed_url, feed.get("link"))
    if homepage:
        hints.append(
            SourceAvatarHint(
                source_id=source_id,
                remote_url=homepage,
                origin="rss_feed_homepage",
                kind="page",
            )
        )
    return hints


class SourceAvatarService:
    """Resolve free avatar metadata and persist only authenticated local media."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        data_dir: str,
        media_cache: MediaCacheService | None = None,
        bilibili_search: BilibiliUserSearchService | None = None,
        fetch_metadata: Callable[[str, str, int], tuple[bytes, str]] | None = None,
    ) -> None:
        self.store = store
        self.media_cache = media_cache or MediaCacheService(
            store,
            data_dir=data_dir,
        )
        self.bilibili_search = bilibili_search or BilibiliUserSearchService()
        self._fetch_metadata = fetch_metadata or self._download_metadata

    @staticmethod
    def hints_from_result(result: FeedRunResult) -> tuple[SourceAvatarHint, ...]:
        return tuple(
            hint
            for outcome in result.source_outcomes
            for hint in outcome.avatar_hints
        )

    def refresh_run_result(
        self,
        *,
        workspace_id: str,
        result: FeedRunResult,
        commit: bool = True,
        media_cleanup: PostCommitMediaCleanup | None = None,
    ) -> list[SourceAvatarRefresh]:
        attempted = {
            outcome.source_id
            for outcome in result.source_outcomes
            if outcome.source_id
        }
        resolve_missing = {
            outcome.source_id
            for outcome in result.source_outcomes
            if outcome.source_id and outcome.status == "succeeded"
        }
        return self.refresh_sources(
            workspace_id=workspace_id,
            source_ids=attempted,
            hints=self.hints_from_result(result),
            resolve_missing_source_ids=resolve_missing,
            commit=commit,
            media_cleanup=media_cleanup,
        )

    def refresh_sources(
        self,
        *,
        workspace_id: str,
        source_ids: Iterable[str],
        hints: Iterable[SourceAvatarHint] = (),
        resolve_missing_source_ids: Iterable[str] = (),
        commit: bool = True,
        media_cleanup: PostCommitMediaCleanup | None = None,
    ) -> list[SourceAvatarRefresh]:
        grouped: dict[str, list[SourceAvatarHint]] = {}
        for hint in hints:
            grouped.setdefault(hint.source_id, []).append(hint)
        resolve_missing = {str(value) for value in resolve_missing_source_ids}
        results: list[SourceAvatarRefresh] = []
        for source_id in dict.fromkeys(str(value) for value in source_ids if value):
            source = self.store.get_source(source_id)
            if (
                source is None
                or str(source.get("workspace_id") or "") != workspace_id
            ):
                results.append(
                    SourceAvatarRefresh(source_id, "identity_mismatch")
                )
                continue
            current = self.media_cache.avatar_for_source(
                workspace_id=workspace_id,
                source_id=source_id,
            )
            source_hints = grouped.get(source_id, [])
            image_hints = [hint for hint in source_hints if hint.kind == "image"]
            primary_result = self._cache_hints(
                workspace_id=workspace_id,
                source_id=source_id,
                hints=image_hints,
                commit=commit,
                media_cleanup=media_cleanup,
            )
            if (
                primary_result is not None
                and primary_result.status in {"stored", "unchanged"}
            ):
                results.append(primary_result)
                continue
            current = self.media_cache.avatar_for_source(
                workspace_id=workspace_id,
                source_id=source_id,
            )
            if current is not None or source_id not in resolve_missing:
                results.append(
                    primary_result
                    or SourceAvatarRefresh(
                        source_id,
                        "unchanged" if current else "candidate_missing",
                    )
                )
                continue
            fallback_hints = self._free_fallback_hints(
                source,
                source_hints=source_hints,
            )
            fallback_result = self._cache_hints(
                workspace_id=workspace_id,
                source_id=source_id,
                hints=fallback_hints,
                commit=commit,
                media_cleanup=media_cleanup,
            )
            results.append(
                fallback_result
                or primary_result
                or SourceAvatarRefresh(source_id, "candidate_missing")
            )
        return results

    def _cache_hints(
        self,
        *,
        workspace_id: str,
        source_id: str,
        hints: Iterable[SourceAvatarHint],
        commit: bool,
        media_cleanup: PostCommitMediaCleanup | None,
    ) -> SourceAvatarRefresh | None:
        saw_candidate = False
        for hint in hints:
            if hint.kind != "image":
                continue
            saw_candidate = True
            cached = self.media_cache.cache_source_avatar_candidates(
                workspace_id=workspace_id,
                source_id=source_id,
                remote_urls=[hint.remote_url],
                commit=commit,
                media_cleanup=media_cleanup,
            )
            if cached["status"] in {"stored", "unchanged"}:
                return SourceAvatarRefresh(
                    source_id,
                    cached["status"],
                    hint.origin,
                )
        if saw_candidate:
            current = self.media_cache.avatar_for_source(
                workspace_id=workspace_id,
                source_id=source_id,
            )
            return SourceAvatarRefresh(
                source_id,
                "kept_previous" if current else "failed",
            )
        return None

    def _free_fallback_hints(
        self,
        source: dict[str, Any],
        *,
        source_hints: list[SourceAvatarHint],
    ) -> list[SourceAvatarHint]:
        source_id = str(source["id"])
        source_type = str(source.get("type") or "")
        config = source.get("config") if isinstance(source.get("config"), dict) else {}
        if source_type == "rss" and self._is_bilibili(config):
            uid = str((config.get("params") or {}).get("uid") or "")
            try:
                avatar = self.bilibili_search.avatar_for_uid(
                    query=str(source.get("display_name") or ""),
                    uid=uid,
                )
            except (ValueError, OSError):
                avatar = None
            return (
                [
                    SourceAvatarHint(
                        source_id=source_id,
                        remote_url=avatar,
                        origin="bilibili_user_search",
                    )
                ]
                if avatar
                else []
            )
        if source_type in {"github_release", "github_user"}:
            identity = str(
                (
                    config.get("owner")
                    if source_type == "github_release"
                    else config.get("username")
                )
                or ""
            ).strip()
            if identity:
                return [
                    SourceAvatarHint(
                        source_id=source_id,
                        remote_url=(
                            f"https://github.com/{quote(identity, safe='')}.png?size=128"
                        ),
                        origin="github_owner"
                        if source_type == "github_release"
                        else "github_user",
                    )
                ]
            return []
        if source_type in {"reddit_subreddit", "reddit_user"}:
            return self._reddit_hints(source_type, source_id, config)
        if source_type == "rss":
            if source_hints:
                return self._favicon_hints(
                    source_id,
                    [hint for hint in source_hints if hint.kind == "page"],
                )
            hints: list[SourceAvatarHint] = []
            if not source_hints:
                feed_url = str(config.get("url") or "").strip()
                if feed_url.startswith(("https://", "http://")):
                    try:
                        payload, _content_type = self._fetch_metadata(
                            feed_url,
                            "application/atom+xml,application/rss+xml,application/xml,text/xml",
                            MAX_AVATAR_METADATA_BYTES,
                        )
                        hints.extend(_feed_hints(payload, feed_url, source_id))
                    except Exception:
                        pass
            image_hints = [hint for hint in hints if hint.kind == "image"]
            page_hints = [hint for hint in hints if hint.kind == "page"]
            return [
                *image_hints,
                *self._favicon_hints(source_id, page_hints),
            ]
        return []

    @staticmethod
    def _is_bilibili(config: dict[str, Any]) -> bool:
        return bool(
            is_managed_rsshub_config(config)
            and config.get("site") == BILIBILI_SITE
            and config.get("route_key") == BILIBILI_USER_VIDEO_ROUTE
        )

    def _reddit_hints(
        self,
        source_type: str,
        source_id: str,
        config: dict[str, Any],
    ) -> list[SourceAvatarHint]:
        key = "subreddit" if source_type == "reddit_subreddit" else "username"
        identity = str(config.get(key) or "").strip()
        for prefix in ("r/", "u/", "/r/", "/u/"):
            if identity.casefold().startswith(prefix):
                identity = identity[len(prefix) :]
                break
        if not identity:
            return []
        path = (
            f"/r/{quote(identity, safe='')}/about.json"
            if source_type == "reddit_subreddit"
            else f"/user/{quote(identity, safe='')}/about.json"
        )
        try:
            payload, _content_type = self._fetch_metadata(
                f"https://www.reddit.com{path}",
                "application/json",
                MAX_AVATAR_METADATA_BYTES,
            )
            parsed = json.loads(payload)
        except Exception:
            return []
        data = parsed.get("data") if isinstance(parsed, dict) else None
        if not isinstance(data, dict):
            return []
        observed = str(
            (
                data.get("display_name")
                if source_type == "reddit_subreddit"
                else data.get("name")
            )
            or ""
        ).strip()
        if observed.casefold() != identity.casefold():
            return []
        for value in (
            data.get("community_icon"),
            data.get("icon_img"),
            data.get("snoovatar_img"),
        ):
            url = html.unescape(str(value or "").strip())
            if url.startswith(("https://", "http://")):
                return [
                    SourceAvatarHint(
                        source_id=source_id,
                        remote_url=url,
                        origin="reddit_about",
                    )
                ]
        return []

    def _favicon_hints(
        self,
        source_id: str,
        page_hints: Iterable[SourceAvatarHint],
    ) -> list[SourceAvatarHint]:
        for page_hint in page_hints:
            try:
                payload, _content_type = self._fetch_metadata(
                    page_hint.remote_url,
                    "text/html",
                    MAX_AVATAR_METADATA_BYTES,
                )
            except Exception:
                continue
            parser = _FaviconParser()
            try:
                parser.feed(payload.decode("utf-8", errors="replace"))
                parser.close()
            except Exception:
                continue
            hints = [
                SourceAvatarHint(
                    source_id=source_id,
                    remote_url=url,
                    origin="rss_homepage_icon",
                )
                for href in parser.hrefs
                if (
                    url := _http_url(page_hint.remote_url, href)
                )
            ]
            default_icon = _http_url(page_hint.remote_url, "/favicon.ico")
            if default_icon and all(
                hint.remote_url != default_icon for hint in hints
            ):
                hints.append(
                    SourceAvatarHint(
                        source_id=source_id,
                        remote_url=default_icon,
                        origin="rss_homepage_default_icon",
                    )
                )
            if hints:
                return hints
        return []

    @staticmethod
    def _download_metadata(
        url: str,
        accept: str,
        max_bytes: int,
    ) -> tuple[bytes, str]:
        response = asyncio.run(
            fetch_public_http(
                url,
                headers={
                    "Accept": accept,
                    "Accept-Encoding": "identity",
                    "User-Agent": "Inteliscope-Source-Avatar/1.0",
                },
                timeout=10.0,
                max_response_bytes=max_bytes,
            )
        )
        response.raise_for_status()
        return (
            response.content,
            str(response.headers.get("content-type") or ""),
        )
