"""Unified Apify-backed public social source scraper."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from html import unescape
from typing import Any, List, Optional
from urllib.parse import urlparse

import httpx
from dateutil.parser import isoparse

from .apify_client import ApifyClient
from .base import BaseScraper
from ..models import (
    ApifySocialConfig,
    ApifySocialPlatform,
    ApifySocialSubscriptionConfig,
    ContentItem,
    SourceType,
)

logger = logging.getLogger(__name__)


class ApifySocialScraper(BaseScraper):
    """Fetch configured public social subscriptions through Apify actors."""

    def __init__(self, config: ApifySocialConfig, http_client: httpx.AsyncClient):
        super().__init__(config.model_dump(), http_client)
        self.social_config = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        if not self.social_config.enabled:
            return []

        token_records = self._token_records()
        if not token_records:
            token_envs = ", ".join(self.social_config.token_envs or [self.social_config.token_env])
            logger.warning(
                "Apify tokens not found in env vars '%s'. Skipping Apify social sources.",
                token_envs,
            )
            return []

        subscriptions = [sub for sub in self.social_config.subscriptions if sub.enabled]
        if not subscriptions:
            return []

        apify = ApifyClient(
            tokens=token_records,
            http_client=self.client,
            timeout_seconds=self.social_config.timeout_seconds,
        )
        tasks = [self._fetch_subscription(apify, sub, since) for sub in subscriptions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        items: list[ContentItem] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning("Apify social subscription failed: %s", result)
            elif isinstance(result, list):
                items.extend(result)
        return items

    async def _fetch_subscription(
        self,
        apify: ApifyClient,
        sub: ApifySocialSubscriptionConfig,
        since: datetime,
    ) -> list[ContentItem]:
        actor_id = self._actor_id(sub.platform)
        actor_input = self._actor_input(sub)
        rows = await apify.run_actor(actor_id, actor_input)

        candidate_rows = [row for row in rows if not row.get("noResults")]
        items: list[ContentItem] = []
        for row in candidate_rows:
            parsed = self._parse_row(row, sub, since)
            if parsed:
                items.append(parsed)

        if not items and candidate_rows and self._should_keep_latest_when_stale(sub):
            oldest_since = datetime.min.replace(tzinfo=timezone.utc)
            for row in candidate_rows:
                parsed = self._parse_row(row, sub, oldest_since)
                if parsed:
                    items.append(parsed)
                if len(items) >= sub.fetch_limit:
                    break
            if items:
                logger.info(
                    "No Apify social items newer than %s for %s/%s %s; keeping latest %d stale item(s)",
                    since.isoformat(),
                    sub.platform.value,
                    sub.kind,
                    sub.target,
                    len(items),
                )
        logger.info(
            "Fetched %d Apify social items for %s/%s %s",
            len(items),
            sub.platform.value,
            sub.kind,
            sub.target,
        )
        return items

    @staticmethod
    def _should_keep_latest_when_stale(sub: ApifySocialSubscriptionConfig) -> bool:
        return sub.kind in {"profile", "channel", "page", "group", "post"}

    def _actor_id(self, platform: ApifySocialPlatform) -> str:
        actors = self.social_config.actors
        return getattr(actors, platform.value).actor_id

    def _token_records(self) -> list[tuple[str, str]]:
        env_names = self.social_config.token_envs or [self.social_config.token_env]
        records: list[tuple[str, str]] = []
        seen: set[str] = set()
        for env_name in env_names:
            name = str(env_name or "").strip()
            if not name or name in seen:
                continue
            seen.add(name)
            token = os.environ.get(name)
            if token:
                records.append((name, token))
        return records

    def _actor_input(self, sub: ApifySocialSubscriptionConfig) -> dict[str, Any]:
        platform = sub.platform
        if platform == ApifySocialPlatform.X:
            if sub.kind == "keyword":
                return {
                    "source_mode": "search",
                    "search_query": sub.target.strip(),
                    "search_sort": "Latest",
                    "max_items": sub.fetch_limit,
                }
            return {
                "source_mode": "profiles",
                "profile_urls": [self._x_handle(sub.target)],
                "search_sort": "Latest",
                "max_items": sub.fetch_limit,
            }

        if platform == ApifySocialPlatform.INSTAGRAM:
            return {
                "directUrls": [self._instagram_url(sub)],
                "resultsLimit": sub.fetch_limit,
            }

        if platform == ApifySocialPlatform.FACEBOOK:
            return {
                "startUrls": [{"url": sub.target.strip()}],
                "maxPosts": sub.fetch_limit,
            }

        if platform == ApifySocialPlatform.TELEGRAM:
            return {
                "channels": [
                    {
                        "channelName": self._telegram_channel(sub.target),
                        "limit": sub.fetch_limit,
                    }
                ],
                "failOnError": False,
            }

        raise ValueError(f"Unsupported Apify social platform: {platform}")

    def _parse_row(
        self,
        row: dict[str, Any],
        sub: ApifySocialSubscriptionConfig,
        since: datetime,
    ) -> Optional[ContentItem]:
        if sub.platform == ApifySocialPlatform.X:
            return self._parse_x(row, sub, since)
        if sub.platform == ApifySocialPlatform.INSTAGRAM:
            return self._parse_instagram(row, sub, since)
        if sub.platform == ApifySocialPlatform.FACEBOOK:
            return self._parse_facebook(row, sub, since)
        if sub.platform == ApifySocialPlatform.TELEGRAM:
            return self._parse_telegram(row, sub, since)
        return None

    def _parse_x(
        self,
        row: dict[str, Any],
        sub: ApifySocialSubscriptionConfig,
        since: datetime,
    ) -> Optional[ContentItem]:
        published_at = self._first_datetime(row, ["created_at", "createdAt", "timestamp"])
        if not published_at or published_at < since:
            return None

        raw_id = str(row.get("id_str") or row.get("id") or "")
        tweet_id = raw_id[6:] if raw_id.startswith("tweet-") else raw_id
        if not tweet_id:
            return None

        user = row.get("user") or {}
        screen_name = (
            user.get("screen_name")
            or user.get("username")
            or user.get("handle")
            or row.get("handle")
            or row.get("username")
            or self._x_handle(sub.target)
            or "unknown"
        )
        author = user.get("name") or screen_name
        text = unescape((row.get("full_text") or row.get("text") or "").strip())
        if not text:
            return None

        url = row.get("url")
        if not url:
            permalink = row.get("permalink")
            url = (
                f"https://twitter.com/{screen_name}{permalink}"
                if permalink and screen_name != "unknown"
                else f"https://twitter.com/{screen_name}/status/{tweet_id}"
            )

        return ContentItem(
            id=self._generate_id(SourceType.TWITTER.value, "tweet", tweet_id),
            source_type=SourceType.TWITTER,
            title=f"@{screen_name}: {self._make_title(text, 70)}",
            url=url,
            content=text,
            author=author,
            published_at=published_at,
            metadata=self._metadata(
                sub,
                {
                    "tweet_id": tweet_id,
                    "conversation_id": str(row.get("conversation_id") or tweet_id),
                    "favorite_count": row.get("favorite_count", 0),
                    "retweet_count": row.get("retweet_count", 0),
                    "reply_count": row.get("reply_count", 0),
                },
            ),
        )

    def _parse_instagram(
        self,
        row: dict[str, Any],
        sub: ApifySocialSubscriptionConfig,
        since: datetime,
    ) -> Optional[ContentItem]:
        published_at = self._first_datetime(
            row,
            ["timestamp", "takenAt", "createdAt", "created_at", "date"],
        )
        if not published_at or published_at < since:
            return None

        shortcode = str(
            row.get("shortCode")
            or row.get("shortcode")
            or row.get("code")
            or row.get("id")
            or ""
        )
        url = str(row.get("url") or "")
        if not url and shortcode:
            url = f"https://www.instagram.com/p/{shortcode}/"
        if not url:
            return None
        if not shortcode:
            shortcode = self._stable_hash(url)

        caption = (
            row.get("caption")
            or row.get("text")
            or row.get("description")
            or ""
        )
        if isinstance(caption, dict):
            caption = caption.get("text") or ""
        content = str(caption).strip()
        author = (
            row.get("ownerUsername")
            or row.get("username")
            or (row.get("owner") or {}).get("username")
            or self._instagram_author_from_target(sub.target)
            or "instagram"
        )

        media_urls = self._instagram_media_urls(row)
        metadata = {
            "shortcode": shortcode,
            "likes": row.get("likesCount") or row.get("likeCount"),
            "comments": row.get("commentsCount") or row.get("commentCount"),
        }
        if media_urls:
            metadata["image_url"] = media_urls[0]
            metadata["media_urls"] = media_urls

        return ContentItem(
            id=self._generate_id(SourceType.INSTAGRAM.value, "post", shortcode),
            source_type=SourceType.INSTAGRAM,
            title=self._make_title(content or f"Instagram post by {author}", 80),
            url=url,
            content=content,
            author=str(author),
            published_at=published_at,
            metadata=self._metadata(sub, metadata),
        )

    def _parse_facebook(
        self,
        row: dict[str, Any],
        sub: ApifySocialSubscriptionConfig,
        since: datetime,
    ) -> Optional[ContentItem]:
        published_at = self._first_datetime(
            row,
            ["date", "time", "timestamp", "createdAt", "created_time"],
        )
        if not published_at or published_at < since:
            return None

        url = str(
            row.get("post_url")
            or row.get("postUrl")
            or row.get("url")
            or row.get("permalink_url")
            or ""
        )
        if not url:
            return None
        native_id = str(
            row.get("post_id")
            or row.get("postId")
            or row.get("id")
            or self._stable_hash(url)
        )
        content = str(
            row.get("text")
            or row.get("message")
            or row.get("caption")
            or ""
        ).strip()
        author = (
            row.get("author")
            or row.get("pageName")
            or row.get("groupName")
            or row.get("page")
            or row.get("group")
            or "facebook"
        )

        return ContentItem(
            id=self._generate_id(SourceType.FACEBOOK.value, "post", native_id),
            source_type=SourceType.FACEBOOK,
            title=self._make_title(content or f"Facebook post by {author}", 80),
            url=url,
            content=content,
            author=str(author),
            published_at=published_at,
            metadata=self._metadata(
                sub,
                {
                    "post_id": native_id,
                    "likes": row.get("likes") or row.get("likesCount"),
                    "comments": row.get("comments") or row.get("commentsCount"),
                    "shares": row.get("shares") or row.get("sharesCount"),
                },
            ),
        )

    def _parse_telegram(
        self,
        row: dict[str, Any],
        sub: ApifySocialSubscriptionConfig,
        since: datetime,
    ) -> Optional[ContentItem]:
        published_at = self._first_datetime(
            row,
            ["Date", "date", "timestamp", "createdAt"],
        )
        if not published_at or published_at < since:
            return None

        channel = str(
            row.get("Channel_Handle")
            or row.get("channel")
            or row.get("channelName")
            or self._telegram_channel(sub.target)
        ).lstrip("@")
        message_id = str(row.get("Id") or row.get("id") or row.get("messageId") or "")
        if not message_id:
            return None

        msg_url = str(row.get("Url") or row.get("url") or f"https://t.me/{channel}/{message_id}")
        link_preview = str(row.get("LinkPreview_Url") or row.get("linkPreviewUrl") or "")
        canonical_url = link_preview if self._is_http_url(link_preview) else msg_url
        body = str(row.get("Body") or row.get("body") or row.get("text") or "").strip()
        if not body:
            return None

        return ContentItem(
            id=self._generate_id(SourceType.TELEGRAM.value, channel, message_id),
            source_type=SourceType.TELEGRAM,
            title=self._make_title(body, 80),
            url=canonical_url,
            content=body,
            author=channel,
            published_at=published_at,
            metadata=self._metadata(
                sub,
                {
                    "msg_url": msg_url,
                    "channel": channel,
                    "message_id": message_id,
                },
            ),
        )

    def _metadata(
        self,
        sub: ApifySocialSubscriptionConfig,
        extra: dict[str, Any],
    ) -> dict[str, Any]:
        metadata = {
            "apify_platform": sub.platform.value,
            "apify_kind": sub.kind,
            "apify_target": sub.target,
            "tags": list(sub.tags),
        }
        metadata.update(extra)
        return metadata

    @staticmethod
    def _first_datetime(row: dict[str, Any], keys: list[str]) -> Optional[datetime]:
        for key in keys:
            raw = row.get(key)
            parsed = ApifySocialScraper._parse_datetime(raw)
            if parsed:
                return parsed
        return None

    @staticmethod
    def _parse_datetime(raw: Any) -> Optional[datetime]:
        if raw in (None, ""):
            return None
        if isinstance(raw, (int, float)):
            value = raw / 1000 if raw > 10_000_000_000 else raw
            return datetime.fromtimestamp(value, tz=timezone.utc)
        text = str(raw).strip()
        if not text:
            return None
        try:
            dt = datetime.strptime(text, "%a %b %d %H:%M:%S %z %Y")
        except ValueError:
            try:
                dt = isoparse(text)
            except (TypeError, ValueError):
                return None
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        return dt

    @staticmethod
    def _make_title(text: str, limit: int) -> str:
        normalized = re.sub(r"\s+", " ", text).strip()
        if len(normalized) <= limit:
            return normalized
        return normalized[:limit].rstrip() + "..."

    @staticmethod
    def _stable_hash(value: str) -> str:
        return hashlib.sha1(value.encode("utf-8")).hexdigest()[:12]

    @staticmethod
    def _x_handle(target: str) -> str:
        raw = target.strip()
        if raw.startswith("http"):
            path = urlparse(raw).path.strip("/")
            raw = path.split("/")[0] if path else raw
        return raw.lstrip("@").strip()

    @staticmethod
    def _instagram_url(sub: ApifySocialSubscriptionConfig) -> str:
        raw = sub.target.strip()
        if raw.startswith("http"):
            return raw
        if sub.kind == "hashtag":
            tag = raw.lstrip("#").strip().strip("/")
            return f"https://www.instagram.com/explore/tags/{tag}/"
        profile = raw.lstrip("@").strip().strip("/")
        return f"https://www.instagram.com/{profile}/"

    @staticmethod
    def _instagram_author_from_target(target: str) -> str:
        raw = target.strip()
        if raw.startswith("http"):
            path = urlparse(raw).path.strip("/")
            parts = [part for part in path.split("/") if part]
            if parts and parts[0] != "explore":
                return parts[0]
            return ""
        return raw.lstrip("@#").strip()

    @staticmethod
    def _telegram_channel(target: str) -> str:
        raw = target.strip()
        if raw.startswith("http"):
            path = urlparse(raw).path.strip("/")
            if path.startswith("s/"):
                path = path[2:]
            raw = path.split("/")[0] if path else raw
        return raw.lstrip("@").strip()

    @staticmethod
    def _is_http_url(value: str) -> bool:
        parsed = urlparse(value)
        return parsed.scheme in {"http", "https"} and bool(parsed.netloc)

    @classmethod
    def _instagram_media_urls(cls, row: dict[str, Any]) -> list[str]:
        urls: list[str] = []

        def add(value: Any) -> None:
            if not isinstance(value, str):
                return
            url = value.strip()
            if url and cls._is_http_url(url) and url not in urls:
                urls.append(url)

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                for key in (
                    "displayUrl",
                    "displayURL",
                    "display_url",
                    "imageUrl",
                    "image_url",
                    "thumbnailUrl",
                    "thumbnail_url",
                    "thumbnail",
                    "image",
                ):
                    add(value.get(key))
                for key in (
                    "images",
                    "media",
                    "childPosts",
                    "children",
                    "carouselMedia",
                    "latestPosts",
                    "sidecarChildren",
                ):
                    visit(value.get(key))
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(row)
        return urls
