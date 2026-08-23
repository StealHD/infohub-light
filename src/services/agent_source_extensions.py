"""Focused Agent source types that extend the legacy public registry."""

from __future__ import annotations

import re
from functools import lru_cache
from typing import Any
from urllib.parse import ParseResult, urlparse


_ALIASES = {
    "github_release": "github",
    "reddit_subreddit": "reddit",
    "telegram_channel": "telegram",
    "youtube_channel": "youtube",
    "x": "twitter",
    "x_profile": "twitter",
    "instagram_profile": "instagram",
    "hacker_news": "hackernews",
}
_EXTENSION_TYPES = frozenset(
    {"github_user", "reddit_user", "instagram", "hackernews"}
)
_GITHUB_USER_RE = re.compile(
    r"^[A-Za-z0-9](?:[A-Za-z0-9-]{0,37}[A-Za-z0-9])?$"
)
_REDDIT_USER_RE = re.compile(r"^[A-Za-z0-9_-]{3,20}$")
_INSTAGRAM_HANDLE_RE = re.compile(r"^[A-Za-z0-9._]{1,30}$")
_INSTAGRAM_RESERVED = frozenset(
    {"accounts", "developer", "direct", "explore", "p", "reel", "reels", "stories"}
)


def canonical_agent_source_type(source_type: str) -> str:
    """Return a compatibility alias as its stable public Agent type."""

    value = str(source_type or "").strip().casefold()
    return _ALIASES.get(value, value)


def is_extension_source_type(source_type: str) -> bool:
    return source_type in _EXTENSION_TYPES


@lru_cache(maxsize=1)
def extension_definitions() -> tuple[Any, ...]:
    """Build focused definitions after the core registry has initialized."""

    from . import source_type_registry as core

    instagram_guide = core._guide_source(
        "Instagram Profile",
        "Instagram 账号",
        "Follow public posts from one Instagram account.",
        "关注一个 Instagram 账号的公开内容。",
        self_service=True,
        requires_web_setup=False,
        en_web_setup_note=(
            "Creation prepares a disabled ActorOps binding. An administrator "
            "must verify and activate it before the source can collect."
        ),
        zh_web_setup_note=(
            "创建时只准备停用的 ActorOps 绑定；管理员核验并启用后才具备采集条件。"
        ),
        fields={
            "handle": core._guide_field(
                "Handle",
                "账号",
                "Public Instagram handle or profile URL.",
                "公开 Instagram 账号或主页网址。",
                ("name", "@name", "https://www.instagram.com/name/"),
                ("名称", "@名称", "https://www.instagram.com/名称/"),
                ("instagram", "@instagram"),
                ("instagram", "@instagram"),
                "Copy the handle from the public profile URL.",
                "从公开主页网址中复制账号。",
            )
        },
    )
    instagram_field = core.SourceFieldDefinition(
        name="handle",
        label="Handle",
        input_type="text",
        required=True,
        default=None,
        options=(),
        minimum=None,
        maximum=None,
        help="Public Instagram account handle or profile URL.",
    )
    return (
        core.AgentSourceTypeDefinition(
            "github_user",
            "github_user",
            ("username",),
            core._BY_TYPE["github_user"].fields[:1],
            core._GUIDE_METADATA["github_user"],
        ),
        core.AgentSourceTypeDefinition(
            "reddit_user",
            "reddit_user",
            ("username",),
            core._BY_TYPE["reddit_user"].fields,
            core._GUIDE_METADATA["reddit_user"],
        ),
        core.AgentSourceTypeDefinition(
            "instagram",
            "apify_social",
            ("handle",),
            (instagram_field,),
            instagram_guide,
        ),
        core.AgentSourceTypeDefinition(
            "hackernews",
            "hackernews",
            (),
            core._BY_TYPE["hackernews"].fields,
            core._GUIDE_METADATA["hackernews"],
        ),
    )


def extension_definition(source_type: str) -> Any | None:
    return next(
        (item for item in extension_definitions() if item.type == source_type),
        None,
    )


def normalize_extension_aliases(
    source_type: str, config: dict[str, Any]
) -> dict[str, Any]:
    """Convert public locators into one catalog validator input."""

    data = dict(config)
    if source_type == "github_user" and "username" in data:
        data["username"] = _github_username(data["username"])
    elif source_type == "reddit_user" and "username" in data:
        data["username"] = _reddit_username(data["username"])
    elif source_type == "instagram" and "handle" in data:
        data = {
            "platform": "instagram",
            "kind": "profile",
            "target": _instagram_handle(data["handle"]),
        }
    return data


def reverse_extension_input(
    source_type: str, config: dict[str, Any]
) -> dict[str, Any]:
    if source_type == "github_user":
        return {
            key: config[key]
            for key in ("username", "fetch_limit")
            if key in config
        }
    if source_type == "reddit_user":
        return {
            key: config[key]
            for key in ("username", "sort", "fetch_limit")
            if key in config
        }
    if source_type == "instagram":
        return {"handle": config.get("target")}
    if source_type == "hackernews":
        return {
            key: config[key]
            for key in ("fetch_top_stories", "min_score")
            if key in config
        }
    raise ValueError("unsupported extension source type")


def extension_catalog_match(
    source_type: str, catalog_type: str, config: object
) -> bool:
    if source_type == "github_user":
        return catalog_type == "github_user"
    if source_type == "reddit_user":
        return catalog_type == "reddit_user"
    if source_type == "hackernews":
        return catalog_type == "hackernews"
    return bool(
        source_type == "instagram"
        and catalog_type == "apify_social"
        and isinstance(config, dict)
        and (
            config.get("profile_id") == "instagram/profile/items"
            or (
                config.get("platform") == "instagram"
                and config.get("kind") == "profile"
            )
        )
        and isinstance(config.get("target"), str)
        and config.get("target")
    )


def project_agent_public_target(
    source_type: str, config: dict[str, Any]
) -> Any:
    """Project a normalized source identity without exposing private config."""

    if source_type == "rss":
        if config.get("provider") == "rsshub":
            return {
                key: config.get(key) for key in ("site", "route_key", "params")
            }
        return config.get("url")
    if source_type == "github_release":
        return f"{config.get('owner', '')}/{config.get('repo', '')}".strip("/")
    if source_type in {"github_user", "reddit_user"}:
        return config.get("username")
    if source_type == "reddit_subreddit":
        return config.get("subreddit")
    if source_type == "telegram_channel":
        return config.get("channel")
    if source_type == "apify_social":
        return {key: config.get(key) for key in ("platform", "kind", "target")}
    if source_type == "hackernews":
        return {
            key: config.get(key) for key in ("fetch_top_stories", "min_score")
        }
    return None


def _github_username(value: Any) -> str:
    text = str(value or "").strip()
    parsed = _safe_public_url(text)
    if parsed.scheme:
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"github.com", "www.github.com"}
            or parsed.username
            or parsed.password
            or parsed.port
            or parsed.query
            or parsed.fragment
        ):
            raise _source_error("username must be a public GitHub account name")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 1 or parsed.path not in {f"/{parts[0]}", f"/{parts[0]}/"}:
            raise _source_error("username must be a public GitHub account name")
        text = parts[0]
    text = text.strip("/")
    if not _GITHUB_USER_RE.fullmatch(text) or "--" in text:
        raise _source_error("username must be a public GitHub account name")
    return text


def _reddit_username(value: Any) -> str:
    text = str(value or "").strip()
    parsed = _safe_public_url(text)
    if parsed.scheme:
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname
            not in {"reddit.com", "www.reddit.com", "old.reddit.com"}
            or parsed.username
            or parsed.password
            or parsed.port
            or parsed.query
            or parsed.fragment
        ):
            raise _source_error("username must be a public Reddit account name")
        parts = [part for part in parsed.path.split("/") if part]
        if (
            len(parts) != 2
            or parts[0].casefold() not in {"u", "user"}
            or parsed.path not in {f"/{parts[0]}/{parts[1]}", f"/{parts[0]}/{parts[1]}/"}
        ):
            raise _source_error("username must be a public Reddit account name")
        text = parts[1]
    text = re.sub(r"^(?:u/|user/)", "", text.strip("/"), flags=re.IGNORECASE)
    if not _REDDIT_USER_RE.fullmatch(text):
        raise _source_error("username must be a public Reddit account name")
    return text


def _instagram_handle(value: Any) -> str:
    text = str(value or "").strip()
    parsed = _safe_public_url(text)
    if parsed.scheme:
        if (
            parsed.scheme not in {"http", "https"}
            or parsed.hostname not in {"instagram.com", "www.instagram.com"}
            or parsed.username
            or parsed.password
            or parsed.port
            or parsed.query
            or parsed.fragment
        ):
            raise _source_error("handle must be a public Instagram account name")
        parts = [part for part in parsed.path.split("/") if part]
        if len(parts) != 1 or parsed.path not in {f"/{parts[0]}", f"/{parts[0]}/"}:
            raise _source_error("handle must be a public Instagram account name")
        text = parts[0]
    handle = text.strip("/").lstrip("@")
    if (
        handle.casefold() in _INSTAGRAM_RESERVED
        or not _INSTAGRAM_HANDLE_RE.fullmatch(handle)
    ):
        raise _source_error("handle must be a public Instagram account name")
    return handle


def _safe_public_url(value: str) -> ParseResult:
    try:
        parsed = urlparse(value)
        parsed.hostname
        parsed.port
    except ValueError as exc:
        raise _source_error("public account URL is invalid") from exc
    return parsed


def _source_error(message: str) -> Exception:
    from .source_type_registry import SourceConfigError

    return SourceConfigError(message)
