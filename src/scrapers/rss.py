"""RSS feed scraper implementation."""

import calendar
import hashlib
import logging
import os
import re
from datetime import datetime, timezone
from typing import Any, Callable, List
from email.utils import parsedate_to_datetime
from urllib.parse import urlparse
import httpx
import feedparser

from .base import BaseScraper
from ..models import ContentItem, SourceType, RSSSourceConfig
from ..services.network_policy import fetch_public_http

logger = logging.getLogger(__name__)


class RSSScraper(BaseScraper):
    """Scraper for RSS/Atom feeds."""

    def __init__(
        self,
        sources: List[RSSSourceConfig],
        http_client: httpx.AsyncClient,
        public_http_transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
    ):
        """Initialize RSS scraper.

        Args:
            sources: List of RSS feed configurations
            http_client: Shared async HTTP client
        """
        super().__init__({"sources": sources}, http_client)
        self.public_http_transport_factory = public_http_transport_factory

    async def fetch(self, since: datetime) -> List[ContentItem]:
        """Fetch RSS feed items.

        Args:
            since: Only fetch items published after this time

        Returns:
            List[ContentItem]: Fetched content items
        """
        items = []
        sources = self.config["sources"]

        for source in sources:
            if not source.enabled:
                continue

            feed_items = await self._fetch_feed(source, since)
            items.extend(feed_items)

        return items

    async def _fetch_feed(
        self, source: RSSSourceConfig, since: datetime
    ) -> List[ContentItem]:
        """Fetch items from a single RSS feed.

        Args:
            source: RSS feed configuration
            since: Only fetch items after this time

        Returns:
            List[ContentItem]: Feed content items
        """
        items = []

        try:
            # Expand environment variables in URL (e.g. ${LWN_TOKEN})
            feed_url = re.sub(
                r"\$\{(\w+)\}",
                lambda m: os.environ.get(m.group(1), m.group(0)).strip(),
                str(source.url),
            )

            response = await self._request_feed(
                feed_url,
                enforce_public_network=source.enforce_public_network,
            )

            # Parse feed
            feed = feedparser.parse(response.text)
            self.observe_upstream_response(
                {"feed": dict(feed.feed), "entries": [dict(entry) for entry in feed.entries]}
            )
            feed_icon_url = self._feed_icon_url(feed.feed)

            dated_entries = []
            for entry in feed.entries:
                published_at = self._parse_date(entry)
                if published_at is not None:
                    dated_entries.append((published_at, entry))

            selected = [
                candidate for candidate in dated_entries if candidate[0] >= since
            ]
            if not selected and source.keep_latest_item and dated_entries:
                selected = [max(dated_entries, key=lambda candidate: candidate[0])]
            latest = max(selected, key=lambda candidate: candidate[0], default=None)

            for published_at, entry in selected:

                # Generate unique ID from feed URL and entry ID
                feed_id = str(source.url).split("//")[1].replace("/", "_")
                entry_id = entry.get("id", entry.get("link", ""))
                entry_hash = hashlib.sha256(str(entry_id).encode("utf-8")).hexdigest()[
                    :16
                ]

                # Extract content
                content = self._extract_content(entry)
                entry_url = entry.get("link", str(source.url))
                media = self._extract_media_inventory(entry, content, entry_url)
                media_urls = media["image_urls"]

                entry_tags = [tag.term for tag in entry.get("tags", [])]
                source_tags = list(source.tags)

                retention_policy = (
                    "latest_per_source"
                    if source.keep_latest_item
                    and latest is not None
                    and entry is latest[1]
                    else "time_window"
                )
                item = ContentItem(
                    id=self._generate_id("rss", feed_id, entry_hash),
                    source_type=SourceType.RSS,
                    title=entry.get("title", "Untitled"),
                    url=entry_url,
                    content=content,
                    author=entry.get("author", source.name),
                    published_at=published_at,
                    metadata={
                        "feed_name": source.name,
                        "category": source.category,
                        **({"feed_icon_url": feed_icon_url} if feed_icon_url else {}),
                        **({"image_url": media_urls[0], "media_urls": media_urls} if media_urls else {}),
                        "media_image_count": media["image_count"],
                        "media_video_count": media["video_count"],
                        "media_audio_count": media["audio_count"],
                        **({"upstream_content_format": media["format"]} if media["format"] else {}),
                        **self._tag_metadata(source),
                        "tags": list(dict.fromkeys(source_tags + entry_tags)),
                        "retention_policy": retention_policy,
                    },
                )
                items.append(item)

        except httpx.HTTPError as e:
            logger.warning("Error fetching RSS feed %s: %s", source.name, e)
            if self.strict_errors:
                raise
        except Exception as e:
            logger.warning("Error parsing RSS feed %s: %s", source.name, e)
            if self.strict_errors:
                raise

        return items

    async def _request_feed(
        self,
        feed_url: str,
        *,
        enforce_public_network: bool,
    ) -> httpx.Response:
        if enforce_public_network:
            response = await fetch_public_http(
                feed_url,
                transport_factory=self.public_http_transport_factory,
            )
        else:
            response = await self.client.get(feed_url, follow_redirects=True)
        response.raise_for_status()
        return response

    def _parse_date(self, entry: dict) -> datetime:
        """Parse publication date from feed entry.

        Args:
            entry: Feed entry data

        Returns:
            datetime: Parsed publication date or None
        """
        # Try different date fields
        for field in ["published", "updated", "created"]:
            if field in entry:
                try:
                    # Try parsing structured time first
                    if f"{field}_parsed" in entry and entry[f"{field}_parsed"]:
                        return datetime.fromtimestamp(
                            calendar.timegm(entry[f"{field}_parsed"]), tz=timezone.utc
                        )
                    # Fallback to string parsing
                    date_str = entry[field]
                    return parsedate_to_datetime(date_str)
                except Exception:
                    continue

        return None

    def _extract_content(self, entry: dict) -> str:
        """Extract text content from feed entry.

        Args:
            entry: Feed entry data

        Returns:
            str: Extracted text content
        """
        if "content" in entry and entry.content:
            # content is usually a list
            return entry.content[0].get("value", "")
        if "summary" in entry:
            return entry.summary
        if "description" in entry:
            return entry.description

        return ""

    @staticmethod
    def _feed_icon_url(feed: dict) -> str:
        image = feed.get("image") if isinstance(feed.get("image"), dict) else {}
        for value in (
            image.get("href"),
            image.get("url"),
            feed.get("icon"),
            feed.get("logo"),
        ):
            url = str(value or "").strip()
            if url.startswith(("https://", "http://")):
                return url
        return ""

    @staticmethod
    def _extract_media_urls(entry: dict, content: str) -> list[str]:
        return RSSScraper._extract_media_inventory(entry, content, "")["image_urls"]

    @staticmethod
    def _extract_media_inventory(entry: dict, content: str, item_url: Any) -> dict[str, Any]:
        urls: list[str] = []
        attachment_images: list[str] = []
        video_count = 0
        audio_count = 0

        def add(value, *, attachment: bool = False) -> None:
            url = str(value or "").strip()
            if url.startswith(("https://", "http://")) and url not in urls:
                urls.append(url)
            if attachment and url in urls and url not in attachment_images:
                attachment_images.append(url)

        for key in ("media_content", "enclosures"):
            for media in entry.get(key, []) or []:
                if not isinstance(media, dict):
                    continue
                mime = str(media.get("type") or "").lower()
                medium = str(media.get("medium") or media.get("media_type") or "").lower()
                is_video = bool(media.get("isVideo") or media.get("is_video")) or mime.startswith("video/") or medium == "video"
                is_audio = mime.startswith("audio/") or medium == "audio"
                if is_video:
                    video_count += 1
                    continue
                if is_audio:
                    audio_count += 1
                    continue
                if mime.startswith("image/") or medium in {"image", "photo"} or not mime:
                    add(media.get("url") or media.get("href"), attachment=True)
        if video_count == 0:
            for media in entry.get("media_thumbnail", []) or []:
                if isinstance(media, dict):
                    add(media.get("url") or media.get("href"))
        for match in re.finditer(
            r"<img\b[^>]*\bsrc=[\"']([^\"']+)[\"']",
            str(content or ""),
            flags=re.IGNORECASE,
        ):
            add(match.group(1))

        host = (urlparse(str(item_url or "")).hostname or "").lower()
        if host in {
            "b23.tv", "bilibili.com", "m.bilibili.com", "www.bilibili.com",
            "youtu.be", "youtube.com", "www.youtube.com",
        }:
            # Preview thumbnails are not source photos and must not inflate the image label.
            urls = []
            attachment_images = []

        content_format = ""
        attachment_total = len(attachment_images) + video_count + audio_count
        if attachment_total > 1:
            content_format = "gallery"
        elif video_count:
            content_format = "video"
        elif audio_count:
            content_format = "audio"
        elif len(attachment_images) > 1:
            content_format = "gallery"
        elif len(attachment_images) == 1:
            content_format = "image"
        return {
            "image_urls": urls,
            "image_count": len(urls),
            "video_count": video_count,
            "audio_count": audio_count,
            "format": content_format,
        }
