"""Safe normalization for public YouTube channel subscriptions."""

from __future__ import annotations

from html.parser import HTMLParser
from typing import Any, Awaitable, Callable
from urllib.parse import quote, unquote, urljoin, urlparse

import httpx

from ..security import public_data_contains_credentials
from .network_policy import UnsafeNetworkTarget, fetch_public_http
from .source_type_registry import (
    SourceConfigError,
    normalize_youtube_channel_feed_url,
    validate_source_config,
    youtube_channel_feed_url,
)


YOUTUBE_PAGE_HOSTS = {"youtube.com", "www.youtube.com"}
YOUTUBE_RESOLVE_TIMEOUT_SECONDS = 10.0
YOUTUBE_RESOLVE_MAX_BYTES = 2_000_000
_CHANNEL_TABS = {
    "about",
    "community",
    "featured",
    "live",
    "playlists",
    "shorts",
    "streams",
    "videos",
}
_ALLOWED_CONFIG_KEYS = {
    "analysis_mode",
    "category",
    "channel",
    "enabled",
    "keep_latest_item",
    "name",
    "personal_tags",
    "tags",
    "topics",
    "url",
}


class YouTubeChannelError(ValueError):
    """Stable public failure contract for YouTube channel setup."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int,
        retryable: bool,
        action: str,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.action = action


def _input_error(message: str) -> YouTubeChannelError:
    return YouTubeChannelError(
        "invalid_source_config",
        message,
        status_code=400,
        retryable=False,
        action=(
            "Use a public YouTube channel URL, @handle, channel ID, "
            "or canonical channel feed URL."
        ),
    )


def _not_found_error() -> YouTubeChannelError:
    return YouTubeChannelError(
        "youtube_channel_not_found",
        "The public YouTube channel feed could not be found.",
        status_code=404,
        retryable=False,
        action="Check the channel or use its stable UC channel ID.",
    )


def _upstream_error() -> YouTubeChannelError:
    return YouTubeChannelError(
        "youtube_channel_resolution_failed",
        "YouTube could not be reached safely to resolve this channel.",
        status_code=502,
        retryable=True,
        action="Retry later or use the channel's stable UC channel ID.",
    )


class _RSSLinkParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.hrefs: list[str] = []

    def handle_starttag(
        self,
        tag: str,
        attrs: list[tuple[str, str | None]],
    ) -> None:
        if tag.lower() != "link":
            return
        values = {key.lower(): value or "" for key, value in attrs}
        rel = {part.lower() for part in values.get("rel", "").split()}
        if (
            "alternate" in rel
            and values.get("type", "").split(";", 1)[0].strip().lower()
            == "application/rss+xml"
            and values.get("href")
        ):
            self.hrefs.append(values["href"])


Fetcher = Callable[..., Awaitable[httpx.Response]]


class YouTubeChannelResolver:
    """Resolve accepted channel identities to one canonical public Atom URL."""

    def __init__(self, *, fetcher: Fetcher = fetch_public_http) -> None:
        self.fetcher = fetcher

    async def resolve_config(self, config: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(config, dict):
            raise _input_error("config must be an object")
        raw = dict(config)
        unknown = set(raw) - _ALLOWED_CONFIG_KEYS
        if unknown or public_data_contains_credentials(raw):
            raise _input_error("YouTube channel setup contains unsupported fields")
        value = raw.get("url")
        if not isinstance(value, str) or not value.strip():
            raise _input_error("YouTube channel input is required")

        canonical_url = await self.resolve(value)
        raw["url"] = canonical_url
        raw.setdefault("keep_latest_item", True)
        try:
            return validate_source_config("rss", raw)
        except SourceConfigError as exc:
            raise _input_error(str(exc)) from exc

    async def resolve(self, value: str) -> str:
        text = str(value or "").strip()
        if not text:
            raise _input_error("YouTube channel input is required")

        try:
            return youtube_channel_feed_url(text)
        except SourceConfigError:
            pass
        try:
            return normalize_youtube_channel_feed_url(text)
        except SourceConfigError:
            pass

        identity = self._handle_from_input(text)
        if identity.startswith("https://"):
            return identity
        return await self._resolve_handle(identity)

    def _handle_from_input(self, value: str) -> str:
        if value.startswith("@"):
            return self._validate_handle(value[1:])

        try:
            parsed = urlparse(value)
            host = parsed.hostname
            port = parsed.port
        except ValueError as exc:
            raise _input_error("YouTube channel address is invalid") from exc
        if (
            parsed.scheme != "https"
            or not host
            or host.lower() not in YOUTUBE_PAGE_HOSTS
            or port is not None
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
            or parsed.params
        ):
            raise _input_error("Only public HTTPS YouTube channel addresses are supported")

        parts = [unquote(part) for part in parsed.path.split("/") if part]
        if not parts:
            raise _input_error("YouTube channel address is incomplete")
        if parts[0] == "channel":
            if len(parts) not in {2, 3} or (
                len(parts) == 3 and parts[2].lower() not in _CHANNEL_TABS
            ):
                raise _input_error("YouTube channel address is invalid")
            try:
                return youtube_channel_feed_url(parts[1])
            except SourceConfigError as exc:
                raise _input_error(str(exc)) from exc
        if parts[0].startswith("@"):
            if len(parts) not in {1, 2} or (
                len(parts) == 2 and parts[1].lower() not in _CHANNEL_TABS
            ):
                raise _input_error("YouTube handle address is invalid")
            return self._validate_handle(parts[0][1:])
        raise _input_error("The address must identify a YouTube channel")

    @staticmethod
    def _validate_handle(value: str) -> str:
        handle = str(value or "").strip()
        if (
            not 1 <= len(handle) <= 100
            or any(character.isspace() or ord(character) < 32 for character in handle)
            or any(character in handle for character in "/\\?#%@")
        ):
            raise _input_error("YouTube handle is invalid")
        return handle

    async def _resolve_handle(self, handle: str) -> str:
        page_url = f"https://www.youtube.com/@{quote(handle, safe='._-')}"
        try:
            response = await self.fetcher(
                page_url,
                headers={
                    "Accept": "text/html,application/xhtml+xml",
                    "User-Agent": "InfoHub-Light/YouTube-channel-resolver",
                },
                timeout=YOUTUBE_RESOLVE_TIMEOUT_SECONDS,
                max_redirects=0,
                max_response_bytes=YOUTUBE_RESOLVE_MAX_BYTES,
            )
        except (UnsafeNetworkTarget, httpx.HTTPError) as exc:
            raise _upstream_error() from exc

        if response.status_code == 404:
            raise _not_found_error()
        if response.status_code >= 400 or 300 <= response.status_code < 400:
            raise _upstream_error()
        content_type = response.headers.get("content-type", "")
        if content_type and "text/html" not in content_type.lower():
            raise _upstream_error()

        parser = _RSSLinkParser()
        try:
            parser.feed(response.text)
        except (UnicodeError, ValueError) as exc:
            raise _upstream_error() from exc
        feeds: set[str] = set()
        for href in parser.hrefs:
            try:
                feeds.add(
                    normalize_youtube_channel_feed_url(urljoin(page_url, href))
                )
            except SourceConfigError:
                continue
        if not feeds:
            raise _not_found_error()
        if len(feeds) != 1:
            raise _upstream_error()
        return feeds.pop()
