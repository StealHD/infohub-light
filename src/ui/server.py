"""Local web server for the private radar UI and config editor."""

from __future__ import annotations

import argparse
import asyncio
import json
import os
import re
import shutil
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import feedparser
import httpx
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from ..config_migration import migrate_config_tag_layers
from ..models import ApifySocialConfig, ApifySocialSubscriptionConfig, Config
from ..rsshub import (
    RSSHUB_ACCESS_KEY_ENV,
    is_managed_rsshub_config,
    normalize_rsshub_base_url,
    rsshub_request_url,
)
from ..scrapers.apify_social import ApifySocialScraper
from ..scrapers.apify_client import ApifyRunCoordinator
from ..services.response_schema import bound_source_response_schemas, extract_response_schema
from ..services.source_update import run_source_update
from ..services.network_policy import fetch_public_http
from ..source_selection import parse_source_ref
from ..storage.manager import ConfigError, _expand_env_vars
from ..tag_policy import CANONICAL_TAGS, canonical_tag, normalize_channel, normalize_tags
from .auth import (
    AuthSettings,
    auth_status,
    clear_session_cookie_header,
    create_session_token,
    session_cookie_header,
    session_token_from_cookie,
    verify_login,
    verify_session_token,
)


STATIC_DIR = Path(__file__).resolve().parent / "static"
_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_PREFIXES = ("sk-", "sk_", "AIza", "xai-", "gsk_", "hf_", "tp-")
_USER_AGENT = "Horizon-Private-Radar/1.0"
_APIFY_SOCIAL_DEFAULT_ACTORS = {
    "x": "xquik/x-tweet-scraper",
    "instagram": "apify/instagram-api-scraper",
    "facebook": "whoareyouanas/facebook-group-scraper",
    "telegram": "thescrapelab/apify-telegram-scraper",
}
_APIFY_SOCIAL_KINDS = {
    "x": {"profile", "keyword"},
    "instagram": {"profile", "hashtag"},
    "facebook": {"page", "group", "post"},
    "telegram": {"channel"},
}


def normalize_config_payload(body: bytes) -> dict[str, Any]:
    """Parse config update body.

    Accepts either a plain config object or {"config": <object>}.
    """
    payload = json.loads(body.decode("utf-8"))
    if isinstance(payload, dict) and isinstance(payload.get("config"), dict):
        return payload["config"]
    if isinstance(payload, dict):
        return payload
    raise ValueError("Request body must be a JSON object")


def validate_config_data(data: dict[str, Any]) -> Config:
    """Validate config data using Horizon's regular config model."""
    try:
        return Config.model_validate(_expand_env_vars(migrate_config_tag_layers(data)))
    except Exception as exc:
        raise ConfigError(str(exc)) from exc


def _bool(value: Any) -> bool:
    if isinstance(value, bool):
        return value
    if isinstance(value, str):
        return value.lower() in {"1", "true", "yes", "on"}
    return bool(value)


def _text(payload: dict[str, Any], key: str, label: str) -> str:
    value = str(payload.get(key, "")).strip()
    if not value:
        raise ValueError(f"{label} 不能为空")
    return value


def _optional_text(payload: dict[str, Any], key: str) -> str | None:
    value = str(payload.get(key, "")).strip()
    return value or None


def _env_name(payload: dict[str, Any], key: str, label: str) -> str:
    value = _text(payload, key, label)
    if value.startswith(_SECRET_PREFIXES) or not _ENV_VAR_RE.fullmatch(value):
        raise ValueError(f"{label} 必须是环境变量名，不能直接填写密钥")
    return value


def _optional_env_name(payload: dict[str, Any], key: str, label: str) -> str | None:
    value = str(payload.get(key, "")).strip()
    if not value:
        return None
    return _env_name({key: value}, key, label)


def _env_names(
    payload: dict[str, Any],
    key: str,
    label: str,
    *,
    fallback: str = "APIFY_TOKEN",
) -> list[str]:
    raw = payload.get(key)
    if isinstance(raw, list):
        pieces = [str(part) for part in raw]
    else:
        pieces = re.split(r"[,，\n]|\\n", str(raw or ""))

    names: list[str] = []
    for piece in pieces:
        name = piece.strip()
        if not name:
            continue
        validated = _env_name({key: name}, key, label)
        if validated not in names:
            names.append(validated)

    if not names:
        names = [_env_name({key: fallback}, key, label)]
    return names


def _tags(
    payload: dict[str, Any],
    key: str = "tags",
    *,
    allowed_tags: list[str] | None = None,
    allow_custom: bool = False,
) -> list[str]:
    raw = payload.get(key, "")
    if isinstance(raw, list):
        pieces = [str(part) for part in raw]
    else:
        pieces = re.split(r"[,，\n]|\\n", str(raw))

    raw_tags: list[str] = []
    for piece in pieces:
        tag = piece.strip().lstrip("#").strip()
        if not tag:
            continue
        if len(tag) > 32:
            raise ValueError("标签长度不能超过 32 个字符")
        raw_tags.append(tag)
    return normalize_tags(
        raw_tags,
        strict=True,
        max_tags=None,
        allowed_tags=allowed_tags,
        allow_custom=allow_custom,
    )


def _ai_tags(payload: dict[str, Any], key: str = "tags") -> list[str]:
    if key == "tags" and payload.get("topics") not in (None, ""):
        return _tags(payload, key="topics", allow_custom=True)
    return _tags(payload, key=key, allow_custom=True)


def _topic_library(payload: dict[str, Any]) -> list[str]:
    raw = payload["topics"] if "topics" in payload else payload.get("tags", "")
    pieces = [str(part) for part in raw] if isinstance(raw, list) else re.split(r"[,，\n]|\\n", str(raw))
    topics: list[str] = []
    seen: set[str] = set()
    for piece in pieces:
        topic = re.sub(r"\s+", " ", piece.strip().lstrip("#").strip())
        if not topic:
            continue
        if len(topic) > 40:
            raise ValueError("主题长度不能超过 40 个字符")
        topic = canonical_tag(topic) or topic
        key = topic.casefold()
        if key in seen:
            continue
        seen.add(key)
        topics.append(topic)
    if len(topics) > 100:
        raise ValueError("主题数量不能超过 100")
    return topics


def _personal_tags(payload: dict[str, Any], key: str = "personal_tags") -> list[str]:
    return _tags(payload, key=key, allow_custom=True)


def _channel(payload: dict[str, Any], key: str = "channel") -> str | None:
    raw = payload.get(key)
    if raw in (None, "") and key != "category":
        raw = payload.get("category")
    if raw in (None, "") and key == "category":
        raw = payload.get("channel")
    if raw in (None, ""):
        return None
    return normalize_channel(raw)


def _merge_tag_library(data: dict[str, Any], tags: list[str]) -> None:
    library = data.setdefault("tags", [])
    if not isinstance(library, list):
        library = []
        data["tags"] = library
    data["tags"] = normalize_tags(
        [*library, *tags],
        strict=True,
        max_tags=None,
        allow_custom=True,
    ) or list(CANONICAL_TAGS)


def _merge_personal_tag_library(data: dict[str, Any], tags: list[str]) -> None:
    library = data.setdefault("personal_tags", [])
    if not isinstance(library, list):
        library = []
        data["personal_tags"] = library
    data["personal_tags"] = normalize_tags(
        [*library, *tags],
        strict=True,
        max_tags=None,
        allow_custom=True,
    )


def _index(payload: dict[str, Any], key: str = "index") -> int | None:
    raw = payload.get(key)
    if raw is None or raw == "":
        return None
    try:
        idx = int(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError("index 必须是数字") from exc
    if idx < 0:
        raise ValueError("index 不能小于 0")
    return idx


def _http_url(value: str, label: str) -> str:
    parsed = urlparse(value)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise ValueError(f"{label} 必须是 http/https URL")
    return value


def _apify_social_defaults() -> dict[str, Any]:
    return {
        "enabled": True,
        "token_env": "APIFY_TOKEN",
        "token_envs": ["APIFY_TOKEN"],
        "timeout_seconds": 180,
        "actors": {
            key: {"actor_id": actor_id}
            for key, actor_id in _APIFY_SOCIAL_DEFAULT_ACTORS.items()
        },
        "subscriptions": [],
    }


def _apify_social_platform(payload: dict[str, Any]) -> str:
    platform = str(payload.get("platform") or "").strip().lower()
    if platform == "twitter":
        platform = "x"
    if platform not in _APIFY_SOCIAL_KINDS:
        raise ValueError("Apify 平台必须是 x、instagram、facebook 或 telegram")
    return platform


def _apify_social_kind(payload: dict[str, Any], platform: str) -> str:
    kind = str(payload.get("kind") or "").strip().lower()
    if kind not in _APIFY_SOCIAL_KINDS[platform]:
        allowed = "、".join(sorted(_APIFY_SOCIAL_KINDS[platform]))
        raise ValueError(f"{platform} 类型必须是 {allowed}")
    return kind


def _facebook_url(value: str) -> str:
    url = _http_url(value, "Facebook URL")
    parsed = urlparse(url)
    host = (parsed.hostname or "").lower()
    if host != "facebook.com" and not host.endswith(".facebook.com"):
        raise ValueError("Facebook 目标必须是 facebook.com 的公开 Page、Group 或帖子 URL")
    return url


def _x_handle(value: str) -> str:
    raw = value.strip()
    if raw.startswith("http"):
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host not in {"x.com", "twitter.com"} and not host.endswith(".x.com") and not host.endswith(".twitter.com"):
            raise ValueError("X 账号 URL 必须来自 x.com 或 twitter.com")
        raw = parsed.path.strip("/").split("/")[0]
    handle = raw.lstrip("@").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{1,15}", handle):
        raise ValueError("X 账号格式不正确，请填写 @OpenAI、OpenAI 或公开主页 URL")
    return handle


def _instagram_profile(value: str) -> str:
    raw = value.strip()
    if raw.startswith("http"):
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host != "instagram.com" and not host.endswith(".instagram.com"):
            raise ValueError("Instagram 主页 URL 必须来自 instagram.com")
        raw = parsed.path.strip("/").split("/")[0]
    profile = raw.lstrip("@").strip().strip("/")
    if not re.fullmatch(r"[A-Za-z0-9._]{1,30}", profile):
        raise ValueError("Instagram 主页格式不正确，请填写 openai、@openai 或公开主页 URL")
    return profile


def _instagram_hashtag(value: str) -> str:
    raw = value.strip()
    if raw.startswith("http"):
        parsed = urlparse(raw)
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) >= 3 and parts[0] == "explore" and parts[1] == "tags":
            raw = parts[2]
    tag = raw.lstrip("#").strip().strip("/")
    if not re.fullmatch(r"[\w.]{1,80}", tag, flags=re.UNICODE):
        raise ValueError("Instagram hashtag 格式不正确，请填写 #aiagents 或 aiagents")
    return f"#{tag}"


def _telegram_channel(value: str) -> str:
    raw = value.strip()
    if raw.startswith("http"):
        parsed = urlparse(raw)
        host = (parsed.hostname or "").lower()
        if host != "t.me":
            raise ValueError("Telegram 频道 URL 必须来自 t.me")
        path = parsed.path.strip("/")
        if path.startswith("s/"):
            path = path[2:]
        raw = path.split("/")[0]
    channel = raw.lstrip("@").strip()
    if not re.fullmatch(r"[A-Za-z0-9_]{5,64}", channel):
        raise ValueError("Telegram 频道格式不正确，请填写 zaihuapd、@zaihuapd 或 https://t.me/zaihuapd")
    return channel


def _validated_apify_social_target(platform: str, kind: str, target: str) -> str:
    target = target.strip()
    if platform == "x":
        if kind == "profile":
            return _x_handle(target)
        if len(target) > 200:
            raise ValueError("X 关键词不能超过 200 个字符")
        if not target:
            raise ValueError("X 关键词不能为空")
        return target
    if platform == "instagram":
        return _instagram_hashtag(target) if kind == "hashtag" else _instagram_profile(target)
    if platform == "facebook":
        return _facebook_url(target)
    if platform == "telegram":
        return _telegram_channel(target)
    raise ValueError("未知 Apify 平台")


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


def source_update_payload(payload: dict[str, Any]) -> tuple[str, int | None, int]:
    """Validate and normalize a source update request body."""

    source_type = _text(payload, "source_type", "source_type")
    raw_hours = payload.get("hours", 24)
    if raw_hours == "":
        raw_hours = 24
    try:
        hours = int(raw_hours)
    except (TypeError, ValueError) as exc:
        raise ValueError("hours 必须是 1 到 720 之间的数字") from exc
    if hours < 1 or hours > 720:
        raise ValueError("hours 必须是 1 到 720 之间的数字")

    raw_index = payload.get("index")
    source_ref = parse_source_ref(source_type, raw_index)
    return source_ref.source_type, source_ref.index, hours


def _number(
    payload: dict[str, Any],
    key: str,
    *,
    default: float | int,
    minimum: float | int | None = None,
    maximum: float | int | None = None,
    integer: bool = False,
) -> float | int:
    raw = payload.get(key, default)
    try:
        value = int(raw) if integer else float(raw)
    except (TypeError, ValueError) as exc:
        raise ValueError(f"{key} 必须是数字") from exc
    if minimum is not None and value < minimum:
        raise ValueError(f"{key} 不能小于 {minimum}")
    if maximum is not None and value > maximum:
        raise ValueError(f"{key} 不能大于 {maximum}")
    return value


def _integer_choice(
    payload: dict[str, Any],
    key: str,
    *,
    default: int,
    allowed: set[int],
) -> int:
    raw = payload.get(key, default)
    if isinstance(raw, bool) or not isinstance(raw, int):
        raise ValueError(f"{key} 必须是允许的整数选项")
    value = raw
    if value not in allowed:
        choices = " 或 ".join(str(item) for item in sorted(allowed))
        raise ValueError(f"{key} 必须是 {choices}")
    return value


def _ensure_sources(data: dict[str, Any]) -> dict[str, Any]:
    sources = data.setdefault("sources", {})
    sources.setdefault("rss", [])
    sources.setdefault("github", [])
    sources.setdefault("hackernews", {"enabled": True})
    sources.setdefault("reddit", {"enabled": False, "subreddits": [], "users": [], "fetch_comments": 5})
    sources.setdefault("telegram", {"enabled": False, "channels": []})
    sources.setdefault("apify_social", _apify_social_defaults())
    return sources


def _upsert_list_item(items: list[dict[str, Any]], idx: int | None, item: dict[str, Any]) -> None:
    if idx is None:
        items.append(item)
        return
    if idx >= len(items):
        raise ValueError(f"index {idx} 超出范围")
    items[idx] = item


def _delete_list_item(items: list[dict[str, Any]], idx: int | None) -> None:
    if idx is None:
        raise ValueError("删除操作需要 index")
    if idx >= len(items):
        raise ValueError(f"index {idx} 超出范围")
    del items[idx]


def apply_config_action(
    data: dict[str, Any],
    action: str,
    payload: dict[str, Any],
) -> dict[str, Any]:
    """Apply one validated UI action to config data and return updated copy."""
    if action == "set_settings_bundle":
        action_by_section = {
            "ai": "set_ai",
            "rsshub": "set_rsshub",
            "filtering": "set_filtering",
            "topics": "set_tags",
        }
        if not payload:
            raise ValueError("设置组合至少需要一个配置分区")
        unknown_sections = sorted(set(payload) - set(action_by_section))
        if unknown_sections:
            raise ValueError(f"未知设置分区: {', '.join(unknown_sections)}")

        bundled = deepcopy(data)
        for section, section_action in action_by_section.items():
            if section not in payload:
                continue
            section_payload = payload[section]
            if not isinstance(section_payload, dict):
                raise ValueError(f"{section} 必须是 JSON object")
            bundled = apply_config_action(bundled, section_action, section_payload)
        return bundled

    updated = migrate_config_tag_layers(deepcopy(data))
    sources = _ensure_sources(updated)

    if action == "upsert_rss":
        idx = _index(payload)
        tags = _ai_tags(payload)
        personal_tags = _personal_tags(payload)
        item = {
            "name": _text(payload, "name", "RSS 名称"),
            "url": _http_url(_text(payload, "url", "RSS URL"), "RSS URL"),
            "enabled": _bool(payload.get("enabled", True)),
        }
        channel = _channel(payload, "category")
        if channel:
            item["channel"] = channel
            item["category"] = channel
        if tags:
            item["topics"] = tags
            item["tags"] = tags
        if personal_tags:
            item["personal_tags"] = personal_tags
        _upsert_list_item(sources["rss"], idx, item)
        _merge_tag_library(updated, tags)
        _merge_personal_tag_library(updated, personal_tags)

    elif action == "delete_rss":
        _delete_list_item(sources["rss"], _index(payload))

    elif action == "upsert_github_release":
        idx = _index(payload)
        tags = _ai_tags(payload)
        personal_tags = _personal_tags(payload)
        item = {
            "type": "repo_releases",
            "owner": _text(payload, "owner", "GitHub owner"),
            "repo": _text(payload, "repo", "GitHub repo"),
            "enabled": _bool(payload.get("enabled", True)),
        }
        channel = _channel(payload)
        if channel:
            item["channel"] = channel
            item["category"] = channel
        if tags:
            item["topics"] = tags
            item["tags"] = tags
        if personal_tags:
            item["personal_tags"] = personal_tags
        _upsert_list_item(sources["github"], idx, item)
        _merge_tag_library(updated, tags)
        _merge_personal_tag_library(updated, personal_tags)

    elif action == "upsert_github_user":
        idx = _index(payload)
        tags = _ai_tags(payload)
        personal_tags = _personal_tags(payload)
        item = {
            "type": "user_events",
            "username": _text(payload, "username", "GitHub username"),
            "enabled": _bool(payload.get("enabled", True)),
        }
        channel = _channel(payload)
        if channel:
            item["channel"] = channel
            item["category"] = channel
        if tags:
            item["topics"] = tags
            item["tags"] = tags
        if personal_tags:
            item["personal_tags"] = personal_tags
        _upsert_list_item(sources["github"], idx, item)
        _merge_tag_library(updated, tags)
        _merge_personal_tag_library(updated, personal_tags)

    elif action == "delete_github":
        _delete_list_item(sources["github"], _index(payload))

    elif action == "set_hackernews":
        sources["hackernews"] = {
            "enabled": _bool(payload.get("enabled", True)),
            "fetch_top_stories": _number(payload, "fetch_top_stories", default=30, minimum=1, maximum=500, integer=True),
            "min_score": _number(payload, "min_score", default=100, minimum=0, integer=True),
        }

    elif action == "upsert_reddit_subreddit":
        reddit = sources.setdefault("reddit", {"enabled": True, "subreddits": [], "users": [], "fetch_comments": 5})
        reddit.setdefault("subreddits", [])
        idx = _index(payload)
        tags = _ai_tags(payload)
        personal_tags = _personal_tags(payload)
        item = {
            "subreddit": _text(payload, "subreddit", "Subreddit"),
            "enabled": _bool(payload.get("enabled", True)),
            "sort": str(payload.get("sort") or "hot"),
            "time_filter": str(payload.get("time_filter") or "day"),
            "fetch_limit": _number(payload, "fetch_limit", default=20, minimum=1, maximum=100, integer=True),
            "min_score": _number(payload, "min_score", default=10, minimum=0, integer=True),
        }
        channel = _channel(payload)
        if channel:
            item["channel"] = channel
            item["category"] = channel
        if tags:
            item["topics"] = tags
            item["tags"] = tags
        if personal_tags:
            item["personal_tags"] = personal_tags
        _upsert_list_item(reddit["subreddits"], idx, item)
        reddit["enabled"] = _bool(payload.get("reddit_enabled", reddit.get("enabled", True)))
        _merge_tag_library(updated, tags)
        _merge_personal_tag_library(updated, personal_tags)

    elif action == "delete_reddit_subreddit":
        reddit = sources.setdefault("reddit", {"enabled": True, "subreddits": [], "users": [], "fetch_comments": 5})
        reddit.setdefault("subreddits", [])
        _delete_list_item(reddit["subreddits"], _index(payload))

    elif action == "upsert_telegram_channel":
        telegram = sources.setdefault("telegram", {"enabled": True, "channels": []})
        telegram.setdefault("channels", [])
        idx = _index(payload)
        tags = _ai_tags(payload)
        personal_tags = _personal_tags(payload)
        item = {
            "channel": _text(payload, "channel", "Telegram channel").lstrip("@"),
            "enabled": _bool(payload.get("enabled", True)),
            "fetch_limit": _number(payload, "fetch_limit", default=20, minimum=1, maximum=100, integer=True),
        }
        hub_channel = _channel(payload, "category")
        if hub_channel:
            item["hub_channel"] = hub_channel
            item["category"] = hub_channel
        if tags:
            item["topics"] = tags
            item["tags"] = tags
        if personal_tags:
            item["personal_tags"] = personal_tags
        _upsert_list_item(telegram["channels"], idx, item)
        telegram["enabled"] = _bool(payload.get("telegram_enabled", telegram.get("enabled", True)))
        _merge_tag_library(updated, tags)
        _merge_personal_tag_library(updated, personal_tags)

    elif action == "delete_telegram_channel":
        telegram = sources.setdefault("telegram", {"enabled": True, "channels": []})
        telegram.setdefault("channels", [])
        _delete_list_item(telegram["channels"], _index(payload))

    elif action == "set_apify_social_settings":
        current = sources.setdefault("apify_social", _apify_social_defaults())
        defaults = _apify_social_defaults()
        actors = current.setdefault("actors", defaults["actors"])
        current["enabled"] = _bool(payload.get("enabled", current.get("enabled", True)))
        token_envs = _env_names(
            {"token_envs": payload.get("token_envs")},
            "token_envs",
            "Apify Token 环境变量名",
            fallback=str(payload.get("token_env", current.get("token_env", "APIFY_TOKEN"))),
        )
        current["token_env"] = token_envs[0]
        current["token_envs"] = token_envs
        current["timeout_seconds"] = _number(
            payload,
            "timeout_seconds",
            default=current.get("timeout_seconds", 180),
            minimum=1,
            maximum=900,
            integer=True,
        )
        for platform in _APIFY_SOCIAL_DEFAULT_ACTORS:
            key = f"actor_{platform}"
            actor_id = str(
                payload.get(
                    key,
                    actors.get(platform, {}).get(
                        "actor_id",
                        _APIFY_SOCIAL_DEFAULT_ACTORS[platform],
                    ),
                )
            ).strip()
            if not actor_id:
                raise ValueError(f"{platform} Actor ID 不能为空")
            actors[platform] = {"actor_id": actor_id}
        current["actors"] = actors
        current.setdefault("subscriptions", [])

    elif action == "upsert_apify_social_subscription":
        apify = sources.setdefault("apify_social", _apify_social_defaults())
        apify.setdefault("subscriptions", [])
        apify.setdefault("actors", _apify_social_defaults()["actors"])
        apify.setdefault("token_env", "APIFY_TOKEN")
        apify.setdefault("token_envs", [apify.get("token_env", "APIFY_TOKEN")])
        apify.setdefault("timeout_seconds", 180)
        idx = _index(payload)
        platform = _apify_social_platform(payload)
        kind = _apify_social_kind(payload, platform)
        target = _validated_apify_social_target(
            platform,
            kind,
            _text(payload, "target", "Apify 目标"),
        )
        tags = _ai_tags(payload)
        personal_tags = _personal_tags(payload)
        token_env = _optional_env_name(payload, "token_env", "Apify Key 环境变量名")
        analysis_mode = str(payload.get("analysis_mode") or "full").strip()
        if analysis_mode not in {"full", "personal_only"}:
            raise ValueError("analysis_mode 必须是 full 或 personal_only")
        item = {
            "platform": platform,
            "kind": kind,
            "target": target,
            "fetch_limit": _number(payload, "fetch_limit", default=20, minimum=1, maximum=100, integer=True),
            "enabled": _bool(payload.get("enabled", True)),
            "analysis_mode": analysis_mode,
        }
        if token_env:
            item["token_env"] = token_env
        channel = _channel(payload)
        if channel:
            item["channel"] = channel
            item["category"] = channel
        if tags:
            item["topics"] = tags
            item["tags"] = tags
        if personal_tags:
            item["personal_tags"] = personal_tags
        _upsert_list_item(apify["subscriptions"], idx, item)
        apify["enabled"] = _bool(payload.get("apify_social_enabled", apify.get("enabled", True)))
        _merge_tag_library(updated, tags)
        _merge_personal_tag_library(updated, personal_tags)

    elif action == "delete_apify_social_subscription":
        apify = sources.setdefault("apify_social", _apify_social_defaults())
        apify.setdefault("subscriptions", [])
        _delete_list_item(apify["subscriptions"], _index(payload))

    elif action == "set_rsshub":
        updated["rsshub"] = {
            "base_url": normalize_rsshub_base_url(
                _text(payload, "base_url", "RSSHub Base URL")
            )
        }

    elif action == "set_filtering":
        filtering = updated.setdefault("filtering", {})
        filtering["ai_score_threshold"] = _number(payload, "ai_score_threshold", default=7.5, minimum=0, maximum=10)
        filtering["featured_score_threshold"] = _number(payload, "featured_score_threshold", default=7.5, minimum=0, maximum=10)
        filtering["daily_push_score_threshold"] = _number(payload, "daily_push_score_threshold", default=8.5, minimum=0, maximum=10)
        filtering["daily_push_limit"] = _number(payload, "daily_push_limit", default=10, minimum=1, maximum=50, integer=True)
        filtering["homepage_min_score"] = _number(payload, "homepage_min_score", default=6.0, minimum=0, maximum=10)
        filtering["time_window_hours"] = _number(payload, "time_window_hours", default=24, minimum=1, maximum=720, integer=True)
        filtering["feed_window_days"] = _integer_choice(
            payload,
            "feed_window_days",
            default=7,
            allowed={7, 14, 30},
        )
        filtering["rss_initial_fetch_window_hours"] = _integer_choice(
            payload,
            "rss_initial_fetch_window_hours",
            default=168,
            allowed={168, 720},
        )
        filtering["recent_item_limit"] = _number(payload, "recent_item_limit", default=20, minimum=1, maximum=200, integer=True)

    elif action == "set_ai":
        ai = updated.setdefault("ai", {})
        ai["enabled"] = _bool(payload.get("enabled", True))
        ai["provider"] = _text(payload, "provider", "AI provider")
        ai["model"] = _text(payload, "model", "AI model")
        ai["api_key_env"] = _env_name(payload, "api_key_env", "API Key 环境变量名")
        base_url = _optional_text(payload, "base_url")
        if base_url:
            ai["base_url"] = _http_url(base_url, "AI Base URL")
        else:
            ai.pop("base_url", None)
        languages = [
            part.strip()
            for part in str(payload.get("languages", "zh")).split(",")
            if part.strip()
        ]
        ai["languages"] = languages or ["zh"]
        ai["analysis_content_chars"] = _number(
            payload,
            "analysis_content_chars",
            default=ai.get("analysis_content_chars", 1000),
            minimum=100,
            maximum=10000,
            integer=True,
        )
        ai["analysis_comments_chars"] = _number(
            payload,
            "analysis_comments_chars",
            default=ai.get("analysis_comments_chars", 1500),
            minimum=0,
            maximum=20000,
            integer=True,
        )
        ai["summary_max_chars"] = _number(
            payload,
            "summary_max_chars",
            default=ai.get("summary_max_chars", 200),
            minimum=100,
            maximum=500,
            integer=True,
        )
        ai["analysis_max_output_tokens"] = _number(
            payload,
            "analysis_max_output_tokens",
            default=ai.get("analysis_max_output_tokens", 800),
            minimum=256,
            maximum=2048,
            integer=True,
        )
        ai["enrichment_content_chars"] = _number(
            payload,
            "enrichment_content_chars",
            default=ai.get("enrichment_content_chars", 4000),
            minimum=500,
            maximum=30000,
            integer=True,
        )

    elif action == "set_tags":
        updated["tags"] = _topic_library(payload)

    elif action == "set_personal_tags":
        updated["personal_tags"] = _personal_tags(payload)

    elif action == "set_webhook":
        webhook = updated.setdefault("webhook", {})
        webhook["enabled"] = _bool(payload.get("enabled", False))
        webhook["url_env"] = _env_name(payload, "url_env", "Webhook URL 环境变量名")
        webhook["platform"] = str(payload.get("platform") or "generic")
        webhook["delivery"] = str(payload.get("delivery") or "summary_and_items")
        webhook["layout"] = str(payload.get("layout") or "markdown")
        webhook["fallback_layout"] = str(payload.get("fallback_layout") or "markdown")
        webhook["overview_position"] = str(payload.get("overview_position") or "last")
        webhook["languages"] = [
            part.strip()
            for part in str(payload.get("languages", "zh")).split(",")
            if part.strip()
        ] or ["zh"]
        body_text = str(payload.get("request_text") or "#{message_title}\n\n#{summary?limit=3500&split=---}")
        webhook["request_body"] = {"text": body_text}
        webhook["headers"] = str(payload.get("headers") or "")

    else:
        raise ValueError(f"未知配置操作: {action}")

    validate_config_data(updated)
    return updated


def build_env_status(config: Config) -> list[dict[str, Any]]:
    """Return referenced env vars and whether they are set, without values."""
    refs: dict[str, list[str]] = {}

    def add(name: str | None, used_by: str) -> None:
        if not name:
            return
        refs.setdefault(name, []).append(used_by)

    if getattr(config.ai, "enabled", True):
        add(config.ai.api_key_env, "ai.api_key_env")
        add(config.ai.azure_endpoint_env, "ai.azure_endpoint_env")
    if config.webhook and config.webhook.enabled:
        add(config.webhook.url_env, "webhook.url_env")
    if config.email and config.email.enabled:
        add(config.email.password_env, "email.password_env")
    add(RSSHUB_ACCESS_KEY_ENV, "rsshub.access_key")
    if config.sources.twitter and config.sources.twitter.enabled:
        add(config.sources.twitter.apify_token_env, "sources.twitter.apify_token_env")
    if config.sources.apify_social:
        apify_social = config.sources.apify_social
        enabled_subscriptions = [
            subscription
            for subscription in apify_social.subscriptions
            if subscription.enabled
        ]
        if apify_social.enabled and enabled_subscriptions:
            uses_global_tokens = any(
                not subscription.token_env
                for subscription in enabled_subscriptions
            )
            if uses_global_tokens:
                add(apify_social.token_env, "sources.apify_social.token_env")
                for token_env in apify_social.token_envs:
                    add(token_env, "sources.apify_social.token_envs")
            for index, subscription in enumerate(apify_social.subscriptions):
                if subscription.enabled and subscription.token_env:
                    add(
                        subscription.token_env,
                        f"sources.apify_social.subscriptions[{index}].token_env",
                    )

    return [
        {"name": name, "set": bool(os.getenv(name)), "used_by": sorted(used_by)}
        for name, used_by in sorted(refs.items())
    ]


def _read_json(path: Path) -> dict[str, Any]:
    return json.loads(path.read_text(encoding="utf-8"))


def _write_json(path: Path, data: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    if path.exists():
        shutil.copy2(path, path.with_suffix(".json.bak"))
    path.write_text(
        json.dumps(data, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )


class RadarWebHandler(SimpleHTTPRequestHandler):
    """Serve static radar UI and local JSON config API."""

    def __init__(
        self,
        *args,
        data_dir: Path,
        static_dir: Path,
        **kwargs,
    ):
        self.data_dir = data_dir
        self.config_path = data_dir / "config.json"
        self.static_dir = static_dir
        super().__init__(*args, directory=str(static_dir), **kwargs)

    def log_message(self, format: str, *args) -> None:
        """Keep default HTTP logs concise."""
        print(f"{self.address_string()} - - {format % args}")

    def end_headers(self) -> None:
        """Avoid stale browser caches while the generated UI changes locally."""
        self.send_header("Cache-Control", "no-store, max-age=0")
        self.send_header("Pragma", "no-cache")
        self.send_header("Expires", "0")
        super().end_headers()

    def _send_json(
        self,
        payload: dict[str, Any],
        status: int = 200,
        *,
        headers: dict[str, str] | None = None,
    ) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        for name, value in (headers or {}).items():
            self.send_header(name, value)
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int) -> None:
        self._send_json({"error": message}, status=status)

    def _auth_settings(self) -> AuthSettings:
        return AuthSettings.from_env()

    def _authenticated_username(self, settings: AuthSettings | None = None) -> str | None:
        auth = settings or self._auth_settings()
        token = session_token_from_cookie(self.headers.get("Cookie"))
        return verify_session_token(auth, token)

    def _require_admin(self) -> bool:
        auth = self._auth_settings()
        if not auth.enabled:
            return True
        if not auth.configured:
            self._send_error_json(
                "后台鉴权已启用，但未设置 HORIZON_AUTH_PASSWORD 或 HORIZON_AUTH_PASSWORD_HASH",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return False
        if self._authenticated_username(auth):
            return True
        self._send_error_json("需要登录后才能访问后台配置", HTTPStatus.UNAUTHORIZED)
        return False

    def _read_json_body(self) -> Any:
        length = int(self.headers.get("Content-Length", "0"))
        return json.loads(self.rfile.read(length).decode("utf-8"))

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/auth/status":
            self._handle_auth_status()
            return
        if path == "/api/config":
            if not self._require_admin():
                return
            self._handle_get_config()
            return
        if path == "/api/env":
            if not self._require_admin():
                return
            self._handle_get_env()
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/auth/login":
            self._handle_auth_login()
            return
        if path == "/api/auth/logout":
            self._handle_auth_logout()
            return
        if path == "/api/config":
            if not self._require_admin():
                return
            self._send_error_json(
                "直接保存整份配置已关闭，请使用 /api/config/action 的结构化表单接口",
                HTTPStatus.METHOD_NOT_ALLOWED,
            )
            return
        if path == "/api/config/action":
            if not self._require_admin():
                return
            self._handle_config_action()
            return
        if path == "/api/source/test":
            if not self._require_admin():
                return
            self._handle_source_test()
            return
        if path == "/api/source/update":
            if not self._require_admin():
                return
            self._handle_source_update()
            return
        self._send_error_json("Not found", HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        self.do_POST()

    def translate_path(self, path: str) -> str:
        """Serve fresh bundled assets while keeping generated data/media."""
        parsed_path = urlparse(path).path
        parsed_path = unquote(parsed_path)
        if parsed_path in {"", "/"}:
            parsed_path = "/index.html"

        rel = Path(parsed_path.lstrip("/"))
        if ".." in rel.parts:
            return str(self.static_dir / "__missing__")

        bundled_asset = self.static_dir / rel
        if rel.suffix in {".html", ".js", ".css"} and bundled_asset.exists():
            return str(bundled_asset)

        generated = self.data_dir / "site" / rel
        if generated.exists():
            return str(generated)

        return str(bundled_asset)

    def _handle_auth_status(self) -> None:
        auth = self._auth_settings()
        username = self._authenticated_username(auth)
        self._send_json(auth_status(auth, username))

    def _handle_auth_login(self) -> None:
        auth = self._auth_settings()
        if not auth.enabled:
            self._send_json({"ok": True, "auth": auth_status(auth, auth.username)})
            return
        if not auth.configured:
            self._send_error_json(
                "后台鉴权已启用，但未设置 HORIZON_AUTH_PASSWORD 或 HORIZON_AUTH_PASSWORD_HASH",
                HTTPStatus.SERVICE_UNAVAILABLE,
            )
            return
        try:
            payload = self._read_json_body()
            if not isinstance(payload, dict):
                raise ValueError("payload 必须是 JSON object")
            username = str(payload.get("username") or "")
            password = str(payload.get("password") or "")
        except json.JSONDecodeError as exc:
            self._send_error_json(f"Invalid JSON: {exc}", HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
            return

        if not verify_login(auth, username, password):
            self._send_error_json("用户名或密码不正确", HTTPStatus.UNAUTHORIZED)
            return

        token = create_session_token(auth, auth.username)
        self._send_json(
            {"ok": True, "auth": auth_status(auth, auth.username)},
            headers={"Set-Cookie": session_cookie_header(auth, token)},
        )

    def _handle_auth_logout(self) -> None:
        auth = self._auth_settings()
        self._send_json(
            {"ok": True, "auth": auth_status(auth, None)},
            headers={"Set-Cookie": clear_session_cookie_header(auth)},
        )

    def _handle_get_config(self) -> None:
        if not self.config_path.exists():
            self._send_error_json("data/config.json not found", HTTPStatus.NOT_FOUND)
            return

        try:
            data = migrate_config_tag_layers(_read_json(self.config_path))
            config = validate_config_data(data)
        except Exception as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
            return

        self._send_json(
            {
                "path": str(self.config_path),
                "config": data,
                "env_status": build_env_status(config),
            }
        )

    def _handle_get_env(self) -> None:
        try:
            data = migrate_config_tag_layers(_read_json(self.config_path))
            config = validate_config_data(data)
        except Exception as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
            return

        self._send_json({"env_status": build_env_status(config)})

    def _handle_save_config(self) -> None:
        try:
            data = migrate_config_tag_layers(
                normalize_config_payload(json.dumps(self._read_json_body()).encode("utf-8"))
            )
            config = validate_config_data(data)
            _write_json(self.config_path, data)
        except json.JSONDecodeError as exc:
            self._send_error_json(f"Invalid JSON: {exc}", HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
            return

        self._send_json(
            {
                "ok": True,
                "path": str(self.config_path),
                "env_status": build_env_status(config),
            }
        )

    def _handle_config_action(self) -> None:
        try:
            request = self._read_json_body()
            action = str(request.get("action") or "")
            payload = request.get("payload") or {}
            if not isinstance(payload, dict):
                raise ValueError("payload 必须是 JSON object")
            data = migrate_config_tag_layers(_read_json(self.config_path))
            updated = apply_config_action(data, action, payload)
            config = validate_config_data(updated)
            _write_json(self.config_path, updated)
        except json.JSONDecodeError as exc:
            self._send_error_json(f"Invalid JSON: {exc}", HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
            return

        self._send_json(
            {
                "ok": True,
                "path": str(self.config_path),
                "config": updated,
                "env_status": build_env_status(config),
            }
        )

    def _handle_source_test(self) -> None:
        try:
            payload = self._read_json_body()
            if not isinstance(payload, dict):
                raise ValueError("payload 必须是 JSON object")
            result = run_source_test(payload)
        except json.JSONDecodeError as exc:
            self._send_error_json(f"Invalid JSON: {exc}", HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
            return

        self._send_json(result)

    def _handle_source_update(self) -> None:
        try:
            payload = self._read_json_body()
            if not isinstance(payload, dict):
                raise ValueError("payload 必须是 JSON object")
            source_type, index, hours = source_update_payload(payload)
            result = run_source_update(
                data_dir=self.data_dir,
                source_type=source_type,
                index=index,
                hours=hours,
            )
        except json.JSONDecodeError as exc:
            self._send_error_json(f"Invalid JSON: {exc}", HTTPStatus.BAD_REQUEST)
            return
        except Exception as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
            return

        self._send_json(result)


def main() -> None:
    """CLI entry point for horizon-web."""
    parser = argparse.ArgumentParser(description="Serve Horizon private radar UI")
    parser.add_argument("--host", default=os.getenv("HORIZON_WEB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("HORIZON_WEB_PORT", "8080")))
    parser.add_argument("--data-dir", default="data")
    args = parser.parse_args()

    load_dotenv()
    data_dir = Path(args.data_dir)
    data_dir.mkdir(parents=True, exist_ok=True)
    (data_dir / "site").mkdir(parents=True, exist_ok=True)

    handler = partial(
        RadarWebHandler,
        data_dir=data_dir,
        static_dir=STATIC_DIR,
    )
    server = ThreadingHTTPServer((args.host, args.port), handler)
    print(f"Horizon web UI serving on http://{args.host}:{args.port}")
    print(f"Config API: http://{args.host}:{args.port}/api/config")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        pass
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
