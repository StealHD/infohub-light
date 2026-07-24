"""Reddit scraper implementation."""

import asyncio
import calendar
import logging
import re
from datetime import datetime, timezone
from email.utils import parsedate_to_datetime
from typing import Any, List, Optional, cast

import feedparser
import httpx

from .base import BaseScraper
from ..models import (
    ContentItem,
    RedditConfig,
    RedditSubredditConfig,
    RedditUserConfig,
    SourceType,
)

logger = logging.getLogger(__name__)

REDDIT_BASE = "https://www.reddit.com"
USER_AGENT = (
    "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) "
    "AppleWebKit/537.36 (KHTML, like Gecko) "
    "Chrome/135.0.0.0 Safari/537.36"
)
REDDIT_HEADERS = {
    "User-Agent": USER_AGENT,
    "Accept": "application/json,text/plain,*/*",
    "Accept-Language": "en-US,en;q=0.9",
    "Referer": f"{REDDIT_BASE}/",
}
MAX_COMMENT_CONCURRENCY = 2


class RedditBlockedError(Exception):
    """Raised when Reddit blocks an unauthenticated JSON listing request."""


class RedditScraper(BaseScraper):
    """Scraper for Reddit posts and comments."""

    def __init__(self, config: RedditConfig, http_client: httpx.AsyncClient):
        super().__init__(config.model_dump(), http_client)
        self.reddit_config = config
        self._comment_semaphore = asyncio.Semaphore(MAX_COMMENT_CONCURRENCY)

    async def fetch(self, since: datetime) -> List[ContentItem]:
        if not self.config.get("enabled", True):
            return []

        tasks = []
        for sub_cfg in self.reddit_config.subreddits:
            if sub_cfg.enabled:
                tasks.append(self._fetch_subreddit(sub_cfg, since))
        for user_cfg in self.reddit_config.users:
            if user_cfg.enabled:
                tasks.append(self._fetch_user(user_cfg, since))

        if not tasks:
            return []

        results = await asyncio.gather(*tasks, return_exceptions=True)
        items = []
        for result in results:
            if isinstance(result, Exception):
                logger.warning(
                    "Reddit source fetch failed error_code=%s",
                    type(result).__name__,
                )
                if self.strict_errors:
                    raise result
            elif isinstance(result, list):
                items.extend(result)
        return items

    async def _fetch_subreddit(
        self, cfg: RedditSubredditConfig, since: datetime
    ) -> List[ContentItem]:
        params: dict[str, Any] = {"limit": min(cfg.fetch_limit, 100), "raw_json": 1}
        if cfg.sort in ("top", "controversial"):
            params["t"] = cfg.time_filter

        url = f"{REDDIT_BASE}/r/{cfg.subreddit}/{cfg.sort}.json"
        try:
            data = await self._reddit_get(url, params)
        except RedditBlockedError:
            logger.warning(
                "Reddit blocked JSON listing; falling back to RSS"
            )
            return await self._fetch_subreddit_rss(cfg, since)
        if data is not None:
            self.observe_upstream_response(data)
        if not data:
            return []

        posts = [
            child["data"]
            for child in data.get("data", {}).get("children", [])
            if child.get("kind") == "t3"
        ]
        return await self._process_posts(
            posts,
            since,
            "subreddit",
            cfg.subreddit,
            cfg.min_score,
            cfg,
        )

    async def _fetch_subreddit_rss(
        self, cfg: RedditSubredditConfig, since: datetime
    ) -> List[ContentItem]:
        rss_url = f"{REDDIT_BASE}/r/{cfg.subreddit}/{cfg.sort}/.rss"

        try:
            response = await self.client.get(
                rss_url,
                headers={
                    **REDDIT_HEADERS,
                    "Accept": "application/atom+xml,application/xml,text/xml,*/*",
                },
                follow_redirects=True,
            )
            response.raise_for_status()
        except httpx.HTTPError as e:
            logger.warning(
                "Reddit RSS fallback failed error_code=%s",
                type(e).__name__,
            )
            if self.strict_errors:
                raise
            return []

        feed = feedparser.parse(response.text)
        self.observe_upstream_response(
            {"feed": dict(feed.feed), "entries": [dict(entry) for entry in feed.entries]}
        )
        items = []
        for entry in feed.entries[: cfg.fetch_limit]:
            published_at = self._parse_rss_date(entry)
            if not published_at or published_at < since:
                continue

            entry_id = str(
                entry.get("id") or entry.get("link") or entry.get("title", "")
            )
            title = str(entry.get("title") or "Untitled")
            link = str(entry.get("link") or f"{REDDIT_BASE}/r/{cfg.subreddit}/")
            content = self._strip_html(str(entry.get("summary") or ""))

            items.append(
                ContentItem(
                    id=self._generate_id("reddit", "subreddit-rss", entry_id),
                    source_type=SourceType.REDDIT,
                    title=title,
                    url=cast(Any, link),
                    content=content,
                    author=str(entry.get("author") or "unknown"),
                    published_at=published_at,
                    metadata={
                        "score": None,
                        "upvote_ratio": None,
                        "num_comments": None,
                        "subreddit": cfg.subreddit,
                        "is_self": None,
                        "flair": None,
                        "discussion_url": link,
                        "fallback": "rss",
                        **self._tag_metadata(cfg),
                    },
                )
            )
        return items

    async def _fetch_user(
        self, cfg: RedditUserConfig, since: datetime
    ) -> List[ContentItem]:
        params: dict[str, Any] = {
            "limit": min(cfg.fetch_limit, 100),
            "sort": cfg.sort,
            "raw_json": 1,
        }
        url = f"{REDDIT_BASE}/user/{cfg.username}/submitted.json"
        data = await self._reddit_get(url, params)
        if data is not None:
            self.observe_upstream_response(data)
        if not data:
            return []

        posts = [
            child["data"]
            for child in data.get("data", {}).get("children", [])
            if child.get("kind") == "t3"
        ]
        return await self._process_posts(
            posts,
            since,
            "user",
            cfg.username,
            min_score=0,
            source_config=cfg,
        )

    async def _process_posts(
        self,
        posts: list,
        since: datetime,
        subtype: str,
        source_name: str,
        min_score: int,
        source_config: RedditSubredditConfig | RedditUserConfig,
    ) -> List[ContentItem]:
        valid_posts = []
        comment_tasks = []
        fetch_comments = self.reddit_config.fetch_comments

        for post in posts:
            created = datetime.fromtimestamp(
                post.get("created_utc", 0), tz=timezone.utc
            )
            if created < since:
                continue
            if post.get("score", 0) < min_score:
                continue
            valid_posts.append(post)
            if fetch_comments > 0:
                comment_tasks.append(
                    self._fetch_comments(post.get("subreddit", ""), post["id"])
                )
            else:
                comment_tasks.append(self._empty_comments())

        if not valid_posts:
            return []

        all_comments = await asyncio.gather(*comment_tasks, return_exceptions=True)

        items = []
        for post, comments in zip(valid_posts, all_comments):
            if isinstance(comments, Exception):
                comments = []
            item = self._parse_post(
                post,
                cast(List[dict], comments),
                subtype,
                source_config,
            )
            if item:
                items.append(item)
        return items

    @staticmethod
    async def _empty_comments() -> List[dict]:
        return []

    @staticmethod
    def _parse_rss_date(entry: dict) -> Optional[datetime]:
        for field in ["published", "updated", "created"]:
            parsed_field = f"{field}_parsed"
            if parsed_field in entry and entry[parsed_field]:
                return datetime.fromtimestamp(
                    calendar.timegm(entry[parsed_field]), tz=timezone.utc
                )
            if field in entry:
                try:
                    parsed = parsedate_to_datetime(entry[field])
                    if parsed.tzinfo is None:
                        parsed = parsed.replace(tzinfo=timezone.utc)
                    return parsed
                except Exception:
                    continue
        return None

    @staticmethod
    def _strip_html(value: str) -> str:
        text = re.sub(r"<[^>]+>", " ", value)
        return re.sub(r"\s+", " ", text).strip()

    async def _fetch_comments(self, subreddit: str, post_id: str) -> List[dict]:
        fetch_limit = self.reddit_config.fetch_comments
        url = f"{REDDIT_BASE}/r/{subreddit}/comments/{post_id}.json"
        params = {"limit": fetch_limit, "depth": 1, "sort": "top", "raw_json": 1}

        async with self._comment_semaphore:
            data = await self._reddit_get(url, params)
        if data is not None:
            self.observe_upstream_response(data)
        if not data or not isinstance(data, list) or len(data) < 2:
            return []

        comments = []
        for child in data[1].get("data", {}).get("children", []):
            if child.get("kind") != "t1":
                continue
            c = child["data"]
            if c.get("body") and not c.get("distinguished") == "moderator":
                comments.append(c)

        comments.sort(key=lambda c: c.get("score", 0), reverse=True)
        return comments[:fetch_limit]

    def _parse_post(
        self,
        post: dict,
        comments: List[dict],
        subtype: str,
        source_config: RedditSubredditConfig | RedditUserConfig,
    ) -> Optional[ContentItem]:
        post_id = post["id"]
        title = post.get("title", "")
        is_self = post.get("is_self", False)
        subreddit = post.get("subreddit", "")
        discussion_url = f"https://www.reddit.com{post.get('permalink', '')}"

        # For link posts, use the external URL; for self posts, use the discussion URL
        url = discussion_url if is_self else post.get("url", discussion_url)

        author = post.get("author", "unknown")
        created = datetime.fromtimestamp(post.get("created_utc", 0), tz=timezone.utc)

        # Build content
        parts = []
        if post.get("selftext"):
            text = post["selftext"]
            if len(text) > 1500:
                text = text[:1497] + "..."
            parts.append(text)

        if comments:
            parts.append("\n--- Top Comments ---")
            for c in comments:
                commenter = c.get("author", "anon")
                body = c.get("body", "")
                body = body.strip()
                if len(body) > 500:
                    body = body[:497] + "..."
                score = c.get("score", 0)
                parts.append(f"[{commenter} ({score} pts)]: {body}")

        content = "\n\n".join(parts)

        return ContentItem(
            id=self._generate_id("reddit", subtype, post_id),
            source_type=SourceType.REDDIT,
            title=title,
            url=cast(Any, url),
            content=content,
            author=author,
            published_at=created,
            metadata={
                "score": post.get("score", 0),
                "upvote_ratio": post.get("upvote_ratio"),
                "num_comments": post.get("num_comments", 0),
                "subreddit": subreddit,
                "is_self": is_self,
                "flair": post.get("link_flair_text"),
                "discussion_url": discussion_url,
                **self._tag_metadata(source_config),
            },
        )

    async def _reddit_get(self, url: str, params: dict) -> Optional[Any]:
        try:
            response = await self.client.get(
                url,
                params=params,
                headers=REDDIT_HEADERS,
                follow_redirects=True,
            )
            if response.status_code == 429:
                retry_after = int(response.headers.get("Retry-After", 5))
                logger.warning("Reddit rate limited, retrying after %ds", retry_after)
                await asyncio.sleep(retry_after)
                response = await self.client.get(
                    url,
                    params=params,
                    headers=REDDIT_HEADERS,
                    follow_redirects=True,
                )
            if response.status_code == 403 and "/comments/" in url:
                logger.info(
                    "Reddit blocked comments request; continuing without comments"
                )
                return None
            if response.status_code == 403:
                raise RedditBlockedError(url)
            response.raise_for_status()
            return response.json()
        except RedditBlockedError:
            raise
        except httpx.HTTPError as e:
            logger.warning(
                "Reddit request failed error_code=%s",
                type(e).__name__,
            )
            if self.strict_errors:
                raise
            return None
