"""Local web server for the private radar UI and config editor."""

from __future__ import annotations

import argparse
import json
import os
import re
import shutil
from copy import deepcopy
from functools import partial
from http import HTTPStatus
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.parse import unquote, urlparse
from urllib.request import Request, urlopen

import feedparser
from bs4 import BeautifulSoup
from dotenv import load_dotenv

from ..models import Config
from ..storage.manager import ConfigError, _expand_env_vars


STATIC_DIR = Path(__file__).resolve().parent / "static"
_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_PREFIXES = ("sk-", "sk_", "AIza", "xai-", "gsk_", "hf_", "tp-")
_USER_AGENT = "Horizon-Private-Radar/1.0"


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
        return Config.model_validate(_expand_env_vars(data))
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


def _tags(payload: dict[str, Any], key: str = "tags") -> list[str]:
    raw = payload.get(key, "")
    if isinstance(raw, list):
        pieces = [str(part) for part in raw]
    else:
        pieces = re.split(r"[,，\n]", str(raw))

    tags: list[str] = []
    for piece in pieces:
        tag = piece.strip().lstrip("#").strip()
        if not tag:
            continue
        if len(tag) > 32:
            raise ValueError("标签长度不能超过 32 个字符")
        if tag not in tags:
            tags.append(tag)
    return tags


def _merge_tag_library(data: dict[str, Any], tags: list[str]) -> None:
    library = data.setdefault("tags", [])
    if not isinstance(library, list):
        library = []
        data["tags"] = library
    for tag in tags:
        if tag not in library:
            library.append(tag)


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


def _fetch_text(url: str, *, headers: dict[str, str] | None = None) -> str:
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


def run_source_test(payload: dict[str, Any]) -> dict[str, Any]:
    """Test one source definition without saving it or calling AI."""
    source_type = _text(payload, "source_type", "信源类型")

    if source_type == "rss":
        url = _http_url(_text(payload, "url", "RSS URL"), "RSS URL")
        feed = feedparser.parse(_fetch_text(url))
        entries = list(feed.entries or [])
        if not entries:
            raise ValueError("RSS/Atom 可连接，但没有解析到条目")
        first = entries[0]
        return {
            "ok": True,
            "source_type": source_type,
            "count": len(entries),
            "sample_title": str(first.get("title") or "Untitled"),
            "sample_url": str(first.get("link") or url),
            "message": f"RSS/Atom 可用，解析到 {len(entries)} 条。",
        }

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
        return {
            "ok": True,
            "source_type": source_type,
            "count": len(releases),
            "sample_title": str(first.get("name") or first.get("tag_name") or "Release"),
            "sample_url": str(first.get("html_url") or f"https://github.com/{owner}/{repo}/releases"),
            "message": f"GitHub Release 可用，预览到 {len(releases)} 条。",
        }

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
        return {
            "ok": True,
            "source_type": source_type,
            "count": len(events),
            "sample_title": f"{first.get('type', 'Event')} · {repo}",
            "sample_url": f"https://github.com/{repo}",
            "message": f"GitHub 用户动态可用，预览到 {len(events)} 条。",
        }

    if source_type == "hackernews":
        story_ids = _fetch_json("https://hacker-news.firebaseio.com/v0/topstories.json")
        if not isinstance(story_ids, list) or not story_ids:
            raise ValueError("Hacker News 没有返回 top stories")
        first = _fetch_json(f"https://hacker-news.firebaseio.com/v0/item/{story_ids[0]}.json")
        return {
            "ok": True,
            "source_type": source_type,
            "count": min(len(story_ids), int(payload.get("fetch_top_stories") or 30)),
            "sample_title": str(first.get("title") or "HN story"),
            "sample_url": str(first.get("url") or f"https://news.ycombinator.com/item?id={story_ids[0]}"),
            "message": "Hacker News 可用。",
        }

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
        return {
            "ok": True,
            "source_type": source_type,
            "count": len(posts),
            "sample_title": str(first.get("title") or "Reddit post"),
            "sample_url": f"https://www.reddit.com{permalink}",
            "message": f"Reddit 可用，预览到 {len(posts)} 条。",
        }

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
        return {
            "ok": True,
            "source_type": source_type,
            "count": len(messages),
            "sample_title": title[:80] or f"@{channel} message",
            "sample_url": f"https://t.me/{channel}/{post_id}" if post_id else f"https://t.me/s/{channel}",
            "message": f"Telegram 公共频道可用，预览到 {len(messages)} 条。",
        }

    raise ValueError(f"未知信源类型: {source_type}")


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


def _ensure_sources(data: dict[str, Any]) -> dict[str, Any]:
    sources = data.setdefault("sources", {})
    sources.setdefault("rss", [])
    sources.setdefault("github", [])
    sources.setdefault("hackernews", {"enabled": True})
    sources.setdefault("reddit", {"enabled": False, "subreddits": [], "users": [], "fetch_comments": 5})
    sources.setdefault("telegram", {"enabled": False, "channels": []})
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
    updated = deepcopy(data)
    sources = _ensure_sources(updated)

    if action == "upsert_rss":
        idx = _index(payload)
        tags = _tags(payload)
        item = {
            "name": _text(payload, "name", "RSS 名称"),
            "url": _http_url(_text(payload, "url", "RSS URL"), "RSS URL"),
            "enabled": _bool(payload.get("enabled", True)),
        }
        category = _optional_text(payload, "category")
        if category:
            item["category"] = category
        if tags:
            item["tags"] = tags
        _upsert_list_item(sources["rss"], idx, item)
        _merge_tag_library(updated, tags)

    elif action == "delete_rss":
        _delete_list_item(sources["rss"], _index(payload))

    elif action == "upsert_github_release":
        idx = _index(payload)
        tags = _tags(payload)
        item = {
            "type": "repo_releases",
            "owner": _text(payload, "owner", "GitHub owner"),
            "repo": _text(payload, "repo", "GitHub repo"),
            "enabled": _bool(payload.get("enabled", True)),
        }
        if tags:
            item["tags"] = tags
        _upsert_list_item(sources["github"], idx, item)
        _merge_tag_library(updated, tags)

    elif action == "upsert_github_user":
        idx = _index(payload)
        tags = _tags(payload)
        item = {
            "type": "user_events",
            "username": _text(payload, "username", "GitHub username"),
            "enabled": _bool(payload.get("enabled", True)),
        }
        if tags:
            item["tags"] = tags
        _upsert_list_item(sources["github"], idx, item)
        _merge_tag_library(updated, tags)

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
        tags = _tags(payload)
        item = {
            "subreddit": _text(payload, "subreddit", "Subreddit"),
            "enabled": _bool(payload.get("enabled", True)),
            "sort": str(payload.get("sort") or "hot"),
            "time_filter": str(payload.get("time_filter") or "day"),
            "fetch_limit": _number(payload, "fetch_limit", default=20, minimum=1, maximum=100, integer=True),
            "min_score": _number(payload, "min_score", default=10, minimum=0, integer=True),
        }
        if tags:
            item["tags"] = tags
        _upsert_list_item(reddit["subreddits"], idx, item)
        reddit["enabled"] = _bool(payload.get("reddit_enabled", reddit.get("enabled", True)))
        _merge_tag_library(updated, tags)

    elif action == "delete_reddit_subreddit":
        reddit = sources.setdefault("reddit", {"enabled": True, "subreddits": [], "users": [], "fetch_comments": 5})
        reddit.setdefault("subreddits", [])
        _delete_list_item(reddit["subreddits"], _index(payload))

    elif action == "upsert_telegram_channel":
        telegram = sources.setdefault("telegram", {"enabled": True, "channels": []})
        telegram.setdefault("channels", [])
        idx = _index(payload)
        tags = _tags(payload)
        item = {
            "channel": _text(payload, "channel", "Telegram channel").lstrip("@"),
            "enabled": _bool(payload.get("enabled", True)),
            "fetch_limit": _number(payload, "fetch_limit", default=20, minimum=1, maximum=100, integer=True),
        }
        if tags:
            item["tags"] = tags
        _upsert_list_item(telegram["channels"], idx, item)
        telegram["enabled"] = _bool(payload.get("telegram_enabled", telegram.get("enabled", True)))
        _merge_tag_library(updated, tags)

    elif action == "delete_telegram_channel":
        telegram = sources.setdefault("telegram", {"enabled": True, "channels": []})
        telegram.setdefault("channels", [])
        _delete_list_item(telegram["channels"], _index(payload))

    elif action == "set_filtering":
        filtering = updated.setdefault("filtering", {})
        filtering["ai_score_threshold"] = _number(payload, "ai_score_threshold", default=7.5, minimum=0, maximum=10)
        filtering["featured_score_threshold"] = _number(payload, "featured_score_threshold", default=7.5, minimum=0, maximum=10)
        filtering["daily_push_score_threshold"] = _number(payload, "daily_push_score_threshold", default=8.5, minimum=0, maximum=10)
        filtering["daily_push_limit"] = _number(payload, "daily_push_limit", default=10, minimum=1, maximum=50, integer=True)
        filtering["homepage_min_score"] = _number(payload, "homepage_min_score", default=6.0, minimum=0, maximum=10)
        filtering["time_window_hours"] = _number(payload, "time_window_hours", default=24, minimum=1, maximum=720, integer=True)
        filtering["recent_item_limit"] = _number(payload, "recent_item_limit", default=20, minimum=1, maximum=200, integer=True)

    elif action == "set_ai":
        ai = updated.setdefault("ai", {})
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

    elif action == "set_tags":
        updated["tags"] = _tags(payload)

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

    add(config.ai.api_key_env, "ai.api_key_env")
    add(config.ai.azure_endpoint_env, "ai.azure_endpoint_env")
    if config.webhook:
        add(config.webhook.url_env, "webhook.url_env")
    if config.email:
        add(config.email.password_env, "email.password_env")
    if config.sources.twitter:
        add(config.sources.twitter.apify_token_env, "sources.twitter.apify_token_env")

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

    def _send_json(self, payload: dict[str, Any], status: int = 200) -> None:
        body = json.dumps(payload, ensure_ascii=False, indent=2).encode("utf-8")
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        self.end_headers()
        self.wfile.write(body)

    def _send_error_json(self, message: str, status: int) -> None:
        self._send_json({"error": message}, status=status)

    def do_GET(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/config":
            self._handle_get_config()
            return
        if path == "/api/env":
            self._handle_get_env()
            return
        super().do_GET()

    def do_POST(self) -> None:
        path = urlparse(self.path).path
        if path == "/api/config":
            self._send_error_json(
                "直接保存整份配置已关闭，请使用 /api/config/action 的结构化表单接口",
                HTTPStatus.METHOD_NOT_ALLOWED,
            )
            return
        if path == "/api/config/action":
            self._handle_config_action()
            return
        if path == "/api/source/test":
            self._handle_source_test()
            return
        self._send_error_json("Not found", HTTPStatus.NOT_FOUND)

    def do_PUT(self) -> None:
        self.do_POST()

    def translate_path(self, path: str) -> str:
        """Serve generated site files first, then bundled static assets."""
        parsed_path = urlparse(path).path
        parsed_path = unquote(parsed_path)
        if parsed_path in {"", "/"}:
            parsed_path = "/index.html"

        rel = Path(parsed_path.lstrip("/"))
        if ".." in rel.parts:
            return str(self.static_dir / "__missing__")

        if rel.name in {"index.html", "app.js", "styles.css"}:
            return str(self.static_dir / rel)

        generated = self.data_dir / "site" / rel
        if generated.exists():
            return str(generated)

        return str(self.static_dir / rel)

    def _handle_get_config(self) -> None:
        if not self.config_path.exists():
            self._send_error_json("data/config.json not found", HTTPStatus.NOT_FOUND)
            return

        try:
            data = _read_json(self.config_path)
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
            data = _read_json(self.config_path)
            config = validate_config_data(data)
        except Exception as exc:
            self._send_error_json(str(exc), HTTPStatus.BAD_REQUEST)
            return

        self._send_json({"env_status": build_env_status(config)})

    def _handle_save_config(self) -> None:
        try:
            length = int(self.headers.get("Content-Length", "0"))
            data = normalize_config_payload(self.rfile.read(length))
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
            length = int(self.headers.get("Content-Length", "0"))
            request = json.loads(self.rfile.read(length).decode("utf-8"))
            action = str(request.get("action") or "")
            payload = request.get("payload") or {}
            if not isinstance(payload, dict):
                raise ValueError("payload 必须是 JSON object")
            data = _read_json(self.config_path)
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
            length = int(self.headers.get("Content-Length", "0"))
            payload = json.loads(self.rfile.read(length).decode("utf-8"))
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
