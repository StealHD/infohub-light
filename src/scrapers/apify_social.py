"""Unified Apify-backed public social source scraper."""

from __future__ import annotations

import asyncio
import hashlib
import logging
import os
import re
from dataclasses import dataclass
from datetime import datetime, timezone
from html import unescape
from typing import Any, List, Optional
from urllib.parse import urlparse

import httpx
from dateutil.parser import isoparse

from .apify_client import ApifyClient, ApifyRunCoordinator
from .base import BaseScraper, SourceFetchError
from ..models import (
    ApifySocialConfig,
    ApifySocialPlatform,
    ApifySocialSubscriptionConfig,
    ContentItem,
    SourceType,
)

logger = logging.getLogger(__name__)


@dataclass(frozen=True, slots=True)
class ActorAdapterContract:
    platform: ApifySocialPlatform
    input_style: str
    max_total_charge_usd: float | None = None


ACTOR_ADAPTER_REGISTRY = {
    "xquik/x-tweet-scraper": ActorAdapterContract(
        platform=ApifySocialPlatform.X,
        input_style="xquik",
        max_total_charge_usd=0.02,
    ),
    "apidojo/twitter-scraper-lite": ActorAdapterContract(
        platform=ApifySocialPlatform.X,
        input_style="apidojo",
        max_total_charge_usd=0.02,
    ),
    "apify/instagram-api-scraper": ActorAdapterContract(
        platform=ApifySocialPlatform.INSTAGRAM,
        input_style="instagram",
    ),
    "whoareyouanas/facebook-group-scraper": ActorAdapterContract(
        platform=ApifySocialPlatform.FACEBOOK,
        input_style="facebook",
    ),
    "thescrapelab/apify-telegram-scraper": ActorAdapterContract(
        platform=ApifySocialPlatform.TELEGRAM,
        input_style="telegram",
    ),
}


class ApifySocialScraper(BaseScraper):
    """Fetch configured public social subscriptions through Apify actors."""

    def __init__(
        self,
        config: ApifySocialConfig,
        http_client: httpx.AsyncClient,
        apify_coordinator: ApifyRunCoordinator | None = None,
    ):
        super().__init__(config.model_dump(), http_client)
        self.social_config = config
        self.apify_coordinator = apify_coordinator

    async def fetch(self, since: datetime) -> List[ContentItem]:
        if not self.social_config.enabled:
            return []

        subscriptions = [sub for sub in self.social_config.subscriptions if sub.enabled]
        if not subscriptions:
            return []

        tasks = [self._fetch_subscription(sub, since) for sub in subscriptions]
        results = await asyncio.gather(*tasks, return_exceptions=True)

        items: list[ContentItem] = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(
                    "Apify social subscription failed error_code=%s",
                    type(result).__name__,
                )
                if self.strict_errors:
                    raise result
            elif isinstance(result, list):
                items.extend(result)
        return items

    async def _fetch_subscription(
        self,
        sub: ApifySocialSubscriptionConfig,
        since: datetime,
    ) -> list[ContentItem]:
        token_records = (
            self._token_records(sub.token_env)
            if self.apify_coordinator is None
            else None
        )
        if self.apify_coordinator is None and not token_records:
            logger.warning(
                "Apify social credential is unavailable; source skipped"
            )
            if self.strict_errors:
                token_envs = ", ".join(self._token_env_names(sub.token_env))
                raise SourceFetchError(
                    f"Apify token not found in env var(s): {token_envs}",
                    retryable=False,
                )
            return []

        apify = ApifyClient(
            tokens=token_records,
            coordinator=self.apify_coordinator,
            http_client=self.client,
            timeout_seconds=self.social_config.timeout_seconds,
        )
        actor_id = self._actor_id(sub.platform)
        contract = self._actor_contract(actor_id, sub.platform)
        actor_input = self._actor_input(sub)
        rows = await apify.run_actor(
            actor_id,
            actor_input,
            max_total_charge_usd=contract.max_total_charge_usd,
            logical_run_id=self._logical_run_id(sub),
        )
        self.observe_upstream_response(rows)

        candidate_rows = [row for row in rows if self._is_content_candidate(row)]
        if rows and not candidate_rows:
            raise SourceFetchError(
                "Apify actor returned placeholder records instead of social posts",
                retryable=False,
                code="apify_demo_mode",
            )
        items: list[ContentItem] = []
        for row in candidate_rows:
            parsed = self._parse_row(row, sub, since)
            if parsed:
                items.append(parsed)
            if len(items) >= sub.fetch_limit:
                break

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
                    "No new Apify social items; keeping latest stale items count=%d",
                    len(items),
                )
        if (
            items
            and sub.platform == ApifySocialPlatform.INSTAGRAM
            and sub.kind == "profile"
            and sub.fetch_profile_details
            and not any(item.metadata.get("author_avatar_url") for item in items)
        ):
            profile_rows = await apify.run_actor(
                actor_id,
                {
                    "directUrls": [self._instagram_url(sub)],
                    "resultsType": "details",
                    "resultsLimit": 1,
                },
                logical_run_id=self._logical_run_id(sub),
            )
            self.observe_upstream_response(profile_rows)
            avatar_url = self._instagram_profile_avatar(profile_rows)
            if avatar_url:
                for item in items:
                    item.metadata["author_avatar_url"] = avatar_url
        logger.info(
            "Fetched Apify social items count=%d",
            len(items),
        )
        return items

    @staticmethod
    def _should_keep_latest_when_stale(sub: ApifySocialSubscriptionConfig) -> bool:
        return sub.kind in {"profile", "channel", "page", "group", "post"}

    @staticmethod
    def _logical_run_id(sub: ApifySocialSubscriptionConfig) -> str | None:
        return sub.source_id or sub.subscription_id or sub.source_key

    def _actor_id(self, platform: ApifySocialPlatform) -> str:
        actors = self.social_config.actors
        return getattr(actors, platform.value).actor_id

    @staticmethod
    def _actor_contract(
        actor_id: str,
        platform: ApifySocialPlatform,
    ) -> ActorAdapterContract:
        normalized = actor_id.replace("~", "/").lower()
        return ACTOR_ADAPTER_REGISTRY.get(
            normalized,
            ActorAdapterContract(platform=platform, input_style="legacy"),
        )

    @staticmethod
    def _is_content_candidate(row: dict[str, Any]) -> bool:
        if row.get("noResults") or row.get("demo"):
            return False
        row_type = str(
            row.get("resultType")
            or row.get("result_type")
            or row.get("type")
            or row.get("recordType")
            or row.get("record_type")
            or ""
        ).strip().lower()
        return row_type not in {
            "diagnostic",
            "diagnostics",
            "run-report",
            "run_report",
            "receipt",
            "stats",
        }

    def _token_env_names(self, token_env: Optional[str] = None) -> list[str]:
        if token_env:
            return [token_env]
        return self.social_config.token_envs or [self.social_config.token_env]

    def _token_records(self, token_env: Optional[str] = None) -> list[tuple[str, str]]:
        env_names = self._token_env_names(token_env)
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
            contract = self._actor_contract(self._actor_id(platform), platform)
            if contract.input_style in {"xquik", "apidojo"}:
                payload = (
                    {"searchTerms": [sub.target.strip()]}
                    if sub.kind == "keyword"
                    else {"twitterHandles": [self._x_handle(sub.target)]}
                )
                payload["maxItems"] = sub.fetch_limit
                if contract.input_style == "apidojo":
                    payload["sort"] = "Latest"
                return payload
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

        user = row.get("user") or row.get("author") or {}
        screen_name = (
            user.get("screen_name")
            or user.get("username")
            or user.get("userName")
            or user.get("handle")
            or row.get("handle")
            or row.get("username")
            or self._x_handle(sub.target)
            or "unknown"
        )
        author = user.get("name") or screen_name
        text = unescape(
            (row.get("full_text") or row.get("fullText") or row.get("text") or "").strip()
        )
        if not text:
            return None

        avatar_url = str(
            user.get("profilePicture")
            or user.get("profileImageUrl")
            or user.get("profile_image_url_https")
            or ""
        ).strip()
        media = self._x_media_inventory(row)
        media_urls = media["image_urls"]

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
                    "favorite_count": row.get(
                        "favorite_count",
                        row.get("likeCount", row.get("like_count", 0)),
                    ),
                    "retweet_count": row.get("retweet_count", row.get("retweetCount", 0)),
                    "reply_count": row.get("reply_count", row.get("replyCount", 0)),
                    **({"author_avatar_url": avatar_url} if avatar_url else {}),
                    **({"image_url": media_urls[0], "media_urls": media_urls} if media_urls else {}),
                    **self._media_metadata(media),
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

        media = self._instagram_media_inventory(row)
        media_urls = media["image_urls"]
        metadata = {
            "shortcode": shortcode,
            "likes": row.get("likesCount") or row.get("likeCount"),
            "comments": row.get("commentsCount") or row.get("commentCount"),
        }
        if media_urls:
            metadata["image_url"] = media_urls[0]
            metadata["media_urls"] = media_urls
        metadata.update(self._media_metadata(media))
        owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
        avatar_url = str(
            row.get("profilePicUrl")
            or row.get("profilePicture")
            or owner.get("profilePicUrl")
            or owner.get("profilePicture")
            or ""
        ).strip()
        if avatar_url:
            metadata["author_avatar_url"] = avatar_url

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
            "personal_tags": list(sub.personal_tags),
            "analysis_mode": sub.analysis_mode.value,
            "source_id": sub.source_id,
            "subscription_id": sub.subscription_id,
            "source_key": sub.source_key,
            "source_display_name": sub.source_display_name,
            "catalog_source_type": sub.catalog_source_type,
            "source_priority": int(sub.source_priority or 0),
        }
        if sub.analysis_mode.value == "personal_only":
            metadata["show_in_personal_feed"] = True
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

    @staticmethod
    def _media_metadata(media: dict[str, Any]) -> dict[str, Any]:
        metadata = {
            "media_image_count": int(media.get("image_count") or 0),
            "media_video_count": int(media.get("video_count") or 0),
            "media_audio_count": int(media.get("audio_count") or 0),
        }
        content_format = str(media.get("format") or "")
        if content_format:
            metadata["upstream_content_format"] = content_format
        return metadata

    @staticmethod
    def _declared_media_kind(value: dict[str, Any]) -> str:
        raw = str(
            value.get("type")
            or value.get("mediaType")
            or value.get("media_type")
            or value.get("productType")
            or value.get("__typename")
            or ""
        ).strip().lower()
        if value.get("isVideo") or value.get("is_video") or value.get("videoUrl") or value.get("video_url"):
            return "video"
        if "video" in raw or raw in {"animated_gif", "reel", "clip"}:
            return "video"
        if "audio" in raw or raw in {"podcast", "voice"}:
            return "audio"
        if raw in {"photo", "image", "graphimage"}:
            return "image"
        return ""

    @staticmethod
    def _inventory_format(*, images: int, videos: int, audio: int) -> str:
        if images + videos + audio > 1:
            return "gallery"
        if videos:
            return "video"
        if audio:
            return "audio"
        if images > 1:
            return "gallery"
        if images == 1:
            return "image"
        return ""

    @classmethod
    def _instagram_media_urls(cls, row: dict[str, Any]) -> list[str]:
        return cls._instagram_media_inventory(row)["image_urls"]

    @classmethod
    def _instagram_media_inventory(cls, row: dict[str, Any]) -> dict[str, Any]:
        urls: list[str] = []
        videos = 0
        audio = 0

        def image_url(value: dict[str, Any]) -> str:
            for key in (
                "displayUrl", "displayURL", "display_url", "imageUrl",
                "image_url", "thumbnailUrl", "thumbnail_url", "thumbnail", "image",
            ):
                candidate = str(value.get(key) or "").strip()
                if cls._is_http_url(candidate):
                    return candidate
            return ""

        children: list[dict[str, Any]] = []
        for key in ("childPosts", "children", "carouselMedia", "sidecarChildren"):
            value = row.get(key)
            if isinstance(value, list):
                children.extend(child for child in value if isinstance(child, dict))
        candidates = [row, *children]
        for candidate in candidates:
            kind = cls._declared_media_kind(candidate)
            if kind == "video":
                videos += 1
                continue
            if kind == "audio":
                audio += 1
                continue
            url = image_url(candidate)
            if url and url not in urls:
                urls.append(url)
        return {
            "image_urls": urls,
            "image_count": len(urls),
            "video_count": videos,
            "audio_count": audio,
            "format": cls._inventory_format(images=len(urls), videos=videos, audio=audio),
        }

    @classmethod
    def _x_media_urls(cls, row: dict[str, Any]) -> list[str]:
        return cls._x_media_inventory(row)["image_urls"]

    @classmethod
    def _x_media_inventory(cls, row: dict[str, Any]) -> dict[str, Any]:
        urls: list[str] = []
        videos: set[str] = set()
        audio: set[str] = set()

        def visit(value: Any) -> None:
            if isinstance(value, dict):
                kind = cls._declared_media_kind(value)
                identity = str(
                    value.get("id_str")
                    or value.get("id")
                    or value.get("media_key")
                    or value.get("videoUrl")
                    or value.get("video_url")
                    or ""
                ).strip()
                if kind == "video":
                    videos.add(identity or f"video:{len(videos)}")
                    return
                if kind == "audio":
                    audio.add(identity or f"audio:{len(audio)}")
                    return
                for key in (
                    "media_url_https",
                    "media_url",
                    "displayUrl",
                    "imageUrl",
                ):
                    url = str(value.get(key) or "").strip()
                    if cls._is_http_url(url) and url not in urls:
                        urls.append(url)
                for key in (
                    "media",
                    "photos",
                    "images",
                    "extended_entities",
                    "extendedEntities",
                    "entities",
                    "attachments",
                ):
                    visit(value.get(key))
            elif isinstance(value, list):
                for item in value:
                    visit(item)

        visit(row)
        return {
            "image_urls": urls,
            "image_count": len(urls),
            "video_count": len(videos),
            "audio_count": len(audio),
            "format": cls._inventory_format(images=len(urls), videos=len(videos), audio=len(audio)),
        }

    @classmethod
    def _instagram_profile_avatar(cls, rows: list[dict[str, Any]]) -> str:
        for row in rows:
            owner = row.get("owner") if isinstance(row.get("owner"), dict) else {}
            for value in (
                row.get("profilePicUrl"),
                row.get("profilePicture"),
                row.get("profile_pic_url"),
                owner.get("profilePicUrl"),
                owner.get("profilePicture"),
            ):
                url = str(value or "").strip()
                if cls._is_http_url(url):
                    return url
        return ""
