"""Current Service configuration validation and mutation helpers."""

from __future__ import annotations

import json
import os
import re
import shutil
from copy import deepcopy
from pathlib import Path
from typing import Any
from urllib.parse import urlparse

from ..config_migration import migrate_config_tag_layers
from ..models import Config
from ..rsshub import RSSHUB_ACCESS_KEY_ENV, normalize_rsshub_base_url
from ..storage.manager import ConfigError, _expand_env_vars
from ..tag_policy import CANONICAL_TAGS, canonical_tag, normalize_channel, normalize_tags

_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_PREFIXES = ("sk-", "sk_", "AIza", "xai-", "gsk_", "hf_", "tp-")
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
_RETIRED_CONFIG_KEYS = frozenset({"email", "webhook", "premium_analysis", "article_graph"})


def public_config_data(data: dict[str, Any]) -> dict[str, Any]:
    """Return the current API projection without mutating legacy disk input."""
    return {
        key: deepcopy(value)
        for key, value in data.items()
        if key not in _RETIRED_CONFIG_KEYS
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
            "feed_end_messages": "set_feed_end_messages",
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
            "fetch_limit": _number(payload, "fetch_limit", default=3, minimum=1, maximum=100, integer=True),
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

    elif action == "set_feed_end_messages":
        allowed_fields = {
            "ai_generation_enabled",
            "refresh_days",
            "style_preset",
            "style_prompt",
            "list_count",
            "ai_key_env",
            "model",
        }
        unknown_fields = sorted(set(payload) - allowed_fields)
        if unknown_fields:
            raise ValueError(
                f"未知触底文案设置字段: {', '.join(unknown_fields)}"
            )
        generation_enabled = payload.get("ai_generation_enabled", False)
        if not isinstance(generation_enabled, bool):
            raise ValueError("ai_generation_enabled 必须是布尔值")
        raw_style_preset = payload.get("style_preset", "restrained")
        if not isinstance(raw_style_preset, str):
            raise ValueError("style_preset 必须是字符串")
        style_preset = raw_style_preset.strip() or "restrained"
        if style_preset not in {"restrained", "warm", "light_humor"}:
            raise ValueError(
                "style_preset 必须是 restrained、warm 或 light_humor"
            )
        raw_style_prompt = payload.get("style_prompt", "")
        if not isinstance(raw_style_prompt, str):
            raise ValueError("style_prompt 必须是字符串")
        style_prompt = raw_style_prompt.strip()
        if len(style_prompt) > 500:
            raise ValueError("style_prompt 不能超过 500 个字符")
        if "\x00" in style_prompt:
            raise ValueError("style_prompt 不能包含空字符")
        list_count = payload.get("list_count", 12)
        if isinstance(list_count, bool) or not isinstance(list_count, int):
            raise ValueError("list_count 必须是整数")
        if list_count < 3 or list_count > 30:
            raise ValueError("list_count 必须在 3 到 30 之间")
        updated["feed_end_messages"] = {
            "ai_generation_enabled": generation_enabled,
            "refresh_days": _integer_choice(
                payload,
                "refresh_days",
                default=7,
                allowed={1, 7, 30},
            ),
            "style_preset": style_preset,
            "style_prompt": style_prompt,
            "list_count": list_count,
            "ai_key_env": _optional_env_name(
                payload,
                "ai_key_env",
                "触底文案 AI Key 环境变量名",
            )
            or "",
            "model": _optional_text(payload, "model") or "",
        }

    elif action == "set_tags":
        updated["tags"] = _topic_library(payload)

    elif action == "set_personal_tags":
        updated["personal_tags"] = _personal_tags(payload)

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
        if config.feed_end_messages.ai_generation_enabled:
            add(
                config.feed_end_messages.ai_key_env,
                "feed_end_messages.ai_key_env",
            )
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
