"""Twitter scraper using Apify altimis/scweet actor."""

import asyncio
import logging
import os
from datetime import datetime, timezone
from html import unescape
from typing import List, Optional

from dateutil.parser import isoparse
import httpx

from .base import BaseScraper
from ..models import ContentItem, SourceType, TwitterConfig

logger = logging.getLogger(__name__)

_APIFY_BASE = "https://api.apify.com/v2"
_POLL_INTERVAL = 3.0
_MAX_WAIT = 180


class TwitterScraper(BaseScraper):
    """Fetch tweets via the Apify altimis/scweet actor."""

    def __init__(self, config: TwitterConfig, http_client: httpx.AsyncClient):
        super().__init__(config, http_client)
        self.config = config

    async def fetch(self, since: datetime) -> List[ContentItem]:
        if not self.config.enabled:
            return []

        users = [u.strip().lstrip("@") for u in self.config.users if u.strip()]
        if not users:
            logger.debug("No Twitter users configured, skipping.")
            return []

        token = os.environ.get(self.config.apify_token_env)
        if not token:
            logger.warning("Twitter Apify credential is unavailable; source skipped")
            return []

        logger.info("Fetching Twitter profiles count=%d", len(users))

        run_id, dataset_id = await self._start_run(token, users)
        if not run_id:
            return []

        succeeded = await self._wait_for_run(token, run_id)
        if not succeeded:
            return []

        raw_items = await self._fetch_dataset(token, dataset_id)
        items = []
        for raw in raw_items:
            if isinstance(raw, dict) and raw.get("noResults"):
                continue
            parsed = self._parse_item(raw, since)
            if parsed:
                items.append(parsed)

        logger.info("Fetched Twitter items count=%d", len(items))
        return items

    async def _start_run(
        self, token: str, users: List[str]
    ) -> tuple[Optional[str], Optional[str]]:
        payload = {
            "source_mode": "profiles",
            "profile_urls": users,
            "search_sort": "Latest",
            "max_items": max(100, self.config.fetch_limit),
        }
        url = f"{_APIFY_BASE}/acts/{self.config.actor_id}/runs?token={token}"
        try:
            resp = await self.client.post(url, json=payload, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()["data"]
            run_id = data["id"]
            dataset_id = data["defaultDatasetId"]
            logger.debug("Started Twitter Apify run")
            return run_id, dataset_id
        except Exception as exc:
            logger.error(
                "Failed to start Twitter Apify run error_code=%s",
                type(exc).__name__,
            )
            return None, None

    async def _wait_for_run(self, token: str, run_id: str) -> bool:
        url = f"{_APIFY_BASE}/actor-runs/{run_id}?token={token}"
        elapsed = 0.0
        while elapsed < _MAX_WAIT:
            try:
                resp = await self.client.get(url, timeout=10.0)
                resp.raise_for_status()
                status = resp.json()["data"]["status"]
                if status == "SUCCEEDED":
                    return True
                if status in ("FAILED", "ABORTED", "TIMED-OUT"):
                    logger.error("Twitter Apify run ended status=%s", status)
                    return False
            except Exception as exc:
                logger.warning(
                    "Twitter Apify run poll failed error_code=%s",
                    type(exc).__name__,
                )
            await asyncio.sleep(_POLL_INTERVAL)
            elapsed += _POLL_INTERVAL
        logger.warning("Twitter Apify run timed out seconds=%d", _MAX_WAIT)
        return False

    async def _fetch_dataset(self, token: str, dataset_id: str) -> list:
        url = f"{_APIFY_BASE}/datasets/{dataset_id}/items?token={token}"
        try:
            resp = await self.client.get(url, timeout=30.0)
            resp.raise_for_status()
            return resp.json()
        except Exception as exc:
            logger.error(
                "Failed to fetch Twitter Apify dataset error_code=%s",
                type(exc).__name__,
            )
            return []

    async def fetch_replies_for_item(self, item: ContentItem) -> List[str]:
        """Fetch reply texts for one tweet using scweet search mode."""
        if not self.config.fetch_reply_text:
            return []

        token = os.environ.get(self.config.apify_token_env)
        if not token:
            return []

        conversation_id = str(item.metadata.get("conversation_id") or "")
        if not conversation_id:
            return []

        max_replies = max(self.config.max_replies_per_tweet, 0)
        if max_replies == 0:
            return []

        max_items = max(100, max_replies * 5)
        payload = {
            "source_mode": "search",
            "search_query": f"conversation_id:{conversation_id}",
            "search_sort": "Latest",
            "max_items": max_items,
        }

        url = f"{_APIFY_BASE}/acts/{self.config.actor_id}/runs?token={token}"
        try:
            resp = await self.client.post(url, json=payload, timeout=30.0)
            resp.raise_for_status()
            data = resp.json()["data"]
            run_id = data["id"]
            dataset_id = data["defaultDatasetId"]
        except Exception as exc:
            logger.warning(
                "Failed to start Twitter reply run error_code=%s",
                type(exc).__name__,
            )
            return []

        if not await self._wait_for_run(token, run_id):
            return []

        rows = await self._fetch_dataset(token, dataset_id)
        return self._extract_reply_lines(item, rows, max_replies)

    def _extract_reply_lines(self, item: ContentItem, rows: list, max_replies: int) -> List[str]:
        """Convert scweet rows into compact reply lines."""
        min_likes = max(self.config.reply_min_likes, 0)
        tweet_id = str(item.metadata.get("tweet_id") or "")
        own_author = (item.author or "").lstrip("@")
        candidates = []

        for row in rows:
            if not isinstance(row, dict) or row.get("noResults"):
                continue

            row_id = str(row.get("id") or "")
            if row_id.startswith("tweet-"):
                row_id = row_id[6:]
            if tweet_id and row_id == tweet_id:
                continue

            user = row.get("user") or {}
            handle = (
                user.get("handle")
                or row.get("handle")
                or user.get("username")
                or "unknown"
            )
            if handle and own_author and handle.lower() == own_author.lower():
                continue

            text = unescape((row.get("text") or "").strip())
            if not text:
                continue

            likes = int(row.get("favorite_count") or 0)
            replies = int(row.get("reply_count") or 0)
            if likes < min_likes:
                continue

            score = likes * 2 + replies
            line = f"[@{handle} | ❤️ {likes} | 💬 {replies}] {text[:280]}"
            candidates.append((score, line))

        candidates.sort(key=lambda x: x[0], reverse=True)
        return [line for _, line in candidates[:max_replies]]

    @staticmethod
    def append_discussion_content(item: ContentItem, reply_lines: List[str]) -> bool:
        """Append reply lines under Top Comments marker."""
        if not reply_lines:
            return False

        existing = item.content or ""
        marker = "--- Top Comments ---"
        block = "\n".join(reply_lines)

        if marker in existing:
            if block in existing:
                return False
            item.content = existing + "\n" + block
            return True

        if existing:
            item.content = existing + f"\n\n{marker}\n" + block
        else:
            item.content = f"{marker}\n" + block
        return True

    def _parse_item(self, item: dict, since: datetime) -> Optional[ContentItem]:
        try:
            created_at_str = item.get("created_at")
            if not created_at_str:
                return None

            try:
                published_at = datetime.strptime(
                    created_at_str, "%a %b %d %H:%M:%S %z %Y"
                )
            except ValueError:
                published_at = isoparse(created_at_str)

            if published_at.tzinfo is None:
                published_at = published_at.replace(tzinfo=timezone.utc)

            if published_at < since:
                return None

            tweet_id = str(item.get("id_str") or item.get("id") or "")
            if not tweet_id:
                return None

            # Normalize tweet_id: scweet prefixes with "tweet-"
            raw_id = item.get("id") or ""
            numeric_id = (
                str(raw_id).replace("tweet-", "")
                if str(raw_id).startswith("tweet-")
                else tweet_id
            )
            conversation_id = str(
                item.get("conversation_id")
                or item.get("tweet", {}).get("conversation_id")
                or numeric_id
            )

            user = item.get("user") or {}
            screen_name = (
                user.get("screen_name")
                or user.get("username")
                or user.get("handle")
                or item.get("handle")
                or item.get("username")
                or "unknown"
            )
            author = user.get("name") or screen_name

            text = item.get("full_text") or item.get("text") or ""
            if not text:
                return None
            text = unescape(text)

            url = item.get("url")
            if not url:
                permalink = item.get("permalink")
                if permalink and screen_name != "unknown":
                    url = f"https://twitter.com/{screen_name}{permalink}"
                else:
                    url = f"https://twitter.com/{screen_name}/status/{tweet_id}"

            title_body = text[:50].replace("\n", " ").strip()
            if len(text) > 50:
                title_body += "..."

            return ContentItem(
                id=self._generate_id(SourceType.TWITTER.value, "tweet", numeric_id),
                source_type=SourceType.TWITTER,
                title=f"@{screen_name}: {title_body}",
                url=url,
                content=text,
                author=author,
                published_at=published_at,
                metadata={
                    "tweet_id": numeric_id,
                    "conversation_id": conversation_id,
                    "favorite_count": item.get("favorite_count", 0),
                    "retweet_count": item.get("retweet_count", 0),
                    "reply_count": item.get("reply_count", 0),
                    "view_count": item.get("view_count"),
                    "is_reply": item.get("is_reply", False),
                    "in_reply_to_status_id": item.get("in_reply_to_status_id"),
                    "in_reply_to_screen_name": item.get("in_reply_to_screen_name"),
                },
            )
        except Exception as exc:
            logger.debug(
                "Failed to parse Twitter item error_code=%s",
                type(exc).__name__,
            )
            return None
