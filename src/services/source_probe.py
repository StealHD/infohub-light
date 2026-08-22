"""Bounded, non-persisting probes for current source definitions."""

from __future__ import annotations

import asyncio
import json
import os
from datetime import datetime, timedelta, timezone
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import Request, urlopen

import feedparser
import httpx
from bs4 import BeautifulSoup

from ..models import ApifySocialConfig, ApifySocialSubscriptionConfig
from ..rsshub import RSSHUB_ACCESS_KEY_ENV, is_managed_rsshub_config, rsshub_request_url
from ..scrapers.apify_client import ApifyRunCoordinator
from ..scrapers.apify_social import ApifySocialScraper
from .config_runtime import (
    _ai_tags,
    _apify_social_defaults,
    _apify_social_kind,
    _apify_social_platform,
    _env_names,
    _http_url,
    _number,
    _optional_env_name,
    _personal_tags,
    _text,
    _validated_apify_social_target,
)
from .network_policy import fetch_public_http
from .response_schema import bound_source_response_schemas, extract_response_schema

_USER_AGENT = "Horizon-Private-Radar/1.0"


def _fetch_text(
    url: str,
    *,
    headers: dict[str, str] | None = None,
    enforce_public_network: bool = False,
) -> str:
    if enforce_public_network:
        try:
            response = asyncio.run(
                fetch_public_http(
                    url,
                    headers={"User-Agent": _USER_AGENT, **(headers or {})},
                    timeout=20.0,
                )
            )
        except httpx.HTTPError as exc:
            raise ValueError(f"无法连接源端: {exc}") from exc
        if response.status_code >= 400:
            raise ValueError(f"源端返回 HTTP {response.status_code}")
        return response.content[:2_000_000].decode("utf-8", errors="replace")
    request = Request(url, headers={"User-Agent": _USER_AGENT, **(headers or {})})
    try:
        with urlopen(request, timeout=20) as response:
            raw = response.read(2_000_000)
            return raw.decode("utf-8", errors="replace")
    except HTTPError as exc:
        raise ValueError(f"源端返回 HTTP {exc.code}") from exc
    except URLError as exc:
        reason = getattr(exc, "reason", exc)
        raise ValueError(f"无法连接源端: {reason}") from exc


def _fetch_json(url: str, *, headers: dict[str, str] | None = None) -> Any:
    text = _fetch_text(url, headers=headers)
    try:
        return json.loads(text)
    except json.JSONDecodeError as exc:
        raise ValueError("源端返回的不是有效 JSON") from exc


def _github_headers() -> dict[str, str]:
    headers = {"Accept": "application/vnd.github.v3+json"}
    token = os.getenv("GITHUB_TOKEN")
    if token:
        headers["Authorization"] = f"token {token}"
    return headers


def _source_test_result(
    payload: dict[str, Any],
    result: dict[str, Any],
    *,
    upstream: Any | None = None,
    upstream_schema: dict[str, Any] | None = None,
    normalized: Any | None = None,
) -> dict[str, Any]:
    """Attach bounded, value-free response structure diagnostics to a test result."""

    source_type = str(result.get("source_type") or payload.get("source_type") or "unknown")
    source_id = str(payload.get("source_id") or source_type)
    observed_upstream = upstream_schema
    if observed_upstream is None and upstream is not None:
        observed_upstream = extract_response_schema(upstream)
    response_schemas = bound_source_response_schemas(
        [{
            "source_id": source_id,
            "catalog_type": source_type,
            "capture_status": "captured" if observed_upstream is not None else "unavailable",
            "upstream": observed_upstream
            or {"root_type": "null", "fields": [], "truncated": False},
            "normalized": extract_response_schema(result if normalized is None else normalized),
        }]
    )
    return {**result, "response_schemas": response_schemas}


async def _run_apify_social_source_test(
    payload: dict[str, Any],
    *,
    apify_coordinator: ApifyRunCoordinator | None = None,
) -> dict[str, Any]:
    platform = _apify_social_platform(payload)
    kind = _apify_social_kind(payload, platform)
    target = _validated_apify_social_target(
        platform,
        kind,
        _text(payload, "target", "Apify 目标"),
    )
    subscription_token_env = _optional_env_name(payload, "token_env", "Apify Key 环境变量名")
    if subscription_token_env:
        token_envs = [subscription_token_env]
    else:
        token_envs = _env_names(
            {"token_envs": payload.get("token_envs")},
            "token_envs",
            "Apify Token 环境变量名",
            fallback="APIFY_TOKEN",
        )
    if apify_coordinator is None and not any(
        os.getenv(name) for name in token_envs
    ):
        joined = "、".join(token_envs)
        raise ValueError(f"{joined} 均未设置，测试 Apify 订阅前请先写入 .env 并重启服务")

    actors = _apify_social_defaults()["actors"]
    actor_id = str(payload.get("actor_id") or "").strip()
    if actor_id:
        actors[platform] = {"actor_id": actor_id}

    subscription = ApifySocialSubscriptionConfig(
        source_id=str(payload.get("source_id") or "") or None,
        platform=platform,
        kind=kind,
        target=target,
        token_env=subscription_token_env,
        fetch_limit=1,
        enabled=True,
        tags=_ai_tags(payload),
        personal_tags=_personal_tags(payload),
        analysis_mode=str(payload.get("analysis_mode") or "full"),
    )
    config = ApifySocialConfig(
        enabled=True,
        token_env=token_envs[0],
        token_envs=token_envs,
        timeout_seconds=int(_number(payload, "timeout_seconds", default=120, minimum=1, maximum=900, integer=True)),
        actors=actors,
        subscriptions=[subscription],
    )

    async with httpx.AsyncClient(timeout=30.0) as client:
        scraper = ApifySocialScraper(
            config,
            client,
            apify_coordinator=apify_coordinator,
        )
        items = await scraper.fetch(datetime.now(timezone.utc) - timedelta(days=3650))

    if not items:
        raise ValueError("Apify Actor 可运行，但没有返回可解析的公开内容")
    first = items[0]
    result = {
        "ok": True,
        "source_type": "apify_social",
        "count": len(items),
        "sample_title": first.title,
        "sample_url": str(first.url),
        "sample_image_url": str(first.metadata.get("image_url") or ""),
        "message": f"Apify {platform}/{kind} 可用，预览到 {len(items)} 条。",
    }
    return _source_test_result(
        payload,
        result,
        upstream_schema=scraper.upstream_response_schema,
        normalized=[item.model_dump(mode="json") for item in items],
    )


def run_source_test(
    payload: dict[str, Any],
    *,
    apify_coordinator: ApifyRunCoordinator | None = None,
) -> dict[str, Any]:
    """Test one source definition without saving it or calling AI."""
    source_type = _text(payload, "source_type", "信源类型")

    if source_type == "apify_social":
        return asyncio.run(
            _run_apify_social_source_test(
                payload,
                apify_coordinator=apify_coordinator,
            )
        )

    if source_type == "rss":
        feed_url = _http_url(_text(payload, "url", "RSS URL"), "RSS URL")
        request_url = feed_url
        if is_managed_rsshub_config(payload):
            request_url = rsshub_request_url(
                feed_url,
                payload,
                access_key=os.getenv(RSSHUB_ACCESS_KEY_ENV),
            )
        if payload.get("enforce_public_network"):
            feed_text = _fetch_text(request_url, enforce_public_network=True)
        else:
            feed_text = _fetch_text(request_url)
        feed = feedparser.parse(feed_text)
        entries = list(feed.entries or [])
        if not entries:
            raise ValueError("RSS/Atom 可连接，但没有解析到条目")
        first = entries[0]
        result = {
            "ok": True,
            "source_type": source_type,
            "count": len(entries),
            "sample_title": str(first.get("title") or "Untitled"),
            # Never return the route-scoped access code when a feed omits its
            # own item link.
            "sample_url": str(first.get("link") or feed_url),
            "message": f"RSS/Atom 可用，解析到 {len(entries)} 条。",
        }
        return _source_test_result(
            payload,
            result,
            upstream={"feed": dict(feed.feed or {}), "entries": [dict(entry) for entry in entries]},
        )

    if source_type == "github_release":
        owner = _text(payload, "owner", "GitHub owner")
        repo = _text(payload, "repo", "GitHub repo")
        url = f"https://api.github.com/repos/{owner}/{repo}/releases?per_page=5"
        releases = _fetch_json(url, headers=_github_headers())
        if not isinstance(releases, list):
            raise ValueError("GitHub releases 返回格式异常")
        if not releases:
            raise ValueError("GitHub 仓库可连接，但最近没有 release")
        first = releases[0]
        result = {
            "ok": True,
            "source_type": source_type,
            "count": len(releases),
            "sample_title": str(first.get("name") or first.get("tag_name") or "Release"),
            "sample_url": str(first.get("html_url") or f"https://github.com/{owner}/{repo}/releases"),
            "message": f"GitHub Release 可用，预览到 {len(releases)} 条。",
        }
        return _source_test_result(payload, result, upstream=releases)

    if source_type == "github_user":
        username = _text(payload, "username", "GitHub username")
        url = f"https://api.github.com/users/{username}/events/public?per_page=5"
        events = _fetch_json(url, headers=_github_headers())
        if not isinstance(events, list):
            raise ValueError("GitHub 用户动态返回格式异常")
        if not events:
            raise ValueError("GitHub 用户可连接，但最近没有公开动态")
        first = events[0]
        repo = first.get("repo", {}).get("name", username)
        result = {
            "ok": True,
            "source_type": source_type,
            "count": len(events),
            "sample_title": f"{first.get('type', 'Event')} · {repo}",
            "sample_url": f"https://github.com/{repo}",
            "message": f"GitHub 用户动态可用，预览到 {len(events)} 条。",
        }
        return _source_test_result(payload, result, upstream=events)

    if source_type == "hackernews":
        story_ids = _fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
        if not isinstance(story_ids, list) or not story_ids:
            raise ValueError("Hacker News 没有返回 top stories")
        first = _fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story_ids[0]}.json")
        result = {
            "ok": True,
            "source_type": source_type,
            "count": min(len(story_ids), int(payload.get("fetch_top_stories") or 30)),
            "sample_title": str(first.get("title") or "HN story"),
            "sample_url": str(first.get("url") or f"https://news.ycombinator.com/item?id={story_ids[0]}"),
            "message": "Hacker News 可用。",
        }
        return _source_test_result(
            payload,
            result,
            upstream={"topstories": story_ids, "item": first},
        )

    if source_type == "reddit_subreddit":
        subreddit = _text(payload, "subreddit", "Subreddit")
        sort = str(payload.get("sort") or "hot")
        url = f"https://www.reddit.com/r/{subreddit}/{sort}.json?limit=5&raw_json=1"
        data = _fetch_json(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://www.reddit.com/",
            },
        )
        posts = [
            child.get("data", {})
            for child in data.get("data", {}).get("children", [])
            if child.get("kind") == "t3"
        ]
        if not posts:
            raise ValueError("Reddit 可连接，但没有解析到帖子")
        first = posts[0]
        permalink = first.get("permalink") or f"/r/{subreddit}/"
        result = {
            "ok": True,
            "source_type": source_type,
            "count": len(posts),
            "sample_title": str(first.get("title") or "Reddit post"),
            "sample_url": f"https://www.reddit.com{permalink}",
            "message": f"Reddit 可用，预览到 {len(posts)} 条。",
        }
        return _source_test_result(payload, result, upstream=data)

    if source_type == "reddit_user":
        username = _text(payload, "username", "Reddit username").removeprefix("u/").strip()
        sort = str(payload.get("sort") or "new")
        url = f"https://www.reddit.com/user/{username}/submitted.json?limit=5&sort={sort}&raw_json=1"
        data = _fetch_json(
            url,
            headers={
                "Accept": "application/json,text/plain,*/*",
                "Referer": "https://www.reddit.com/",
            },
        )
        posts = [
            child.get("data", {})
            for child in data.get("data", {}).get("children", [])
            if child.get("kind") == "t3"
        ]
        if not posts:
            raise ValueError("Reddit 用户可连接，但没有解析到公开帖子")
        first = posts[0]
        permalink = first.get("permalink") or f"/user/{username}/"
        result = {
            "ok": True,
            "source_type": source_type,
            "count": len(posts),
            "sample_title": str(first.get("title") or "Reddit post"),
            "sample_url": f"https://www.reddit.com{permalink}",
            "message": f"Reddit 用户可用，预览到 {len(posts)} 条。",
        }
        return _source_test_result(payload, result, upstream=data)

    if source_type == "telegram_channel":
        channel = _text(payload, "channel", "Telegram channel").lstrip("@")
        html = _fetch_text(f"https://t.me/s/{channel}")
        soup = BeautifulSoup(html, "html.parser")
        messages = soup.select("div.tgme_widget_message[data-post]")
        if not messages:
            raise ValueError("Telegram 页面可连接，但没有解析到公开消息")
        first = messages[-1]
        text_el = first.select_one("div.tgme_widget_message_text")
        title = (text_el.get_text(" ", strip=True) if text_el else "").strip()
        post_id = str(first.get("data-post") or "").split("/")[-1]
        result = {
            "ok": True,
            "source_type": source_type,
            "count": len(messages),
            "sample_title": title[:80] or f"@{channel} message",
            "sample_url": f"https://t.me/{channel}/{post_id}" if post_id else f"https://t.me/s/{channel}",
            "message": f"Telegram 公共频道可用，预览到 {len(messages)} 条。",
        }
        upstream = []
        for message in messages:
            message_time = message.select_one("time")
            message_text = message.select_one("div.tgme_widget_message_text")
            upstream.append({
                "data_post": message.get("data-post"),
                "datetime": message_time.get("datetime") if message_time else None,
                "text": message_text.get_text(" ", strip=True) if message_text else None,
            })
        return _source_test_result(payload, result, upstream=upstream)

    raise ValueError(f"未知信源类型: {source_type}")
