"""Source catalog type metadata and validation.

The catalog stores only non-secret source configuration plus a secret
environment variable reference. This module keeps those contracts in one place
so API writes, config imports, and worker payloads use the same rules.
"""

from __future__ import annotations

import re
from dataclasses import dataclass
from typing import Any
from urllib.parse import urlparse


_ENV_VAR_RE = re.compile(r"^[A-Z_][A-Z0-9_]{1,127}$")
_SECRET_PREFIXES = ("sk-", "sk_", "AIza", "xai-", "gsk_", "hf_", "tp-")
_SUPPORTED_REDDIT_SORTS = {"hot", "new", "top", "rising", "controversial"}
_SUPPORTED_REDDIT_TIME_FILTERS = {"hour", "day", "week", "month", "year", "all"}
_APIFY_KINDS = {
    "x": {"profile", "keyword"},
    "instagram": {"profile", "hashtag"},
    "facebook": {"page", "group", "post"},
    "telegram": {"channel"},
}


class SourceConfigError(ValueError):
    """Raised when a catalog source config is invalid."""


@dataclass(frozen=True)
class SourceTypeDefinition:
    type: str
    label: str
    description: str
    required_fields: tuple[str, ...]
    template: dict[str, Any]
    supports_secret_env: bool = False

    def as_dict(self) -> dict[str, Any]:
        return {
            "type": self.type,
            "label": self.label,
            "description": self.description,
            "required_fields": list(self.required_fields),
            "template": dict(self.template),
            "supports_secret_env": self.supports_secret_env,
        }


_SOURCE_TYPES: tuple[SourceTypeDefinition, ...] = (
    SourceTypeDefinition(
        type="rss",
        label="RSS/Atom",
        description="Direct RSS or Atom feed URL.",
        required_fields=("url",),
        template={"name": "Example Feed", "url": "https://example.com/feed.xml"},
        supports_secret_env=True,
    ),
    SourceTypeDefinition(
        type="github_release",
        label="GitHub Releases",
        description="Repository release feed from the GitHub REST API.",
        required_fields=("owner", "repo"),
        template={"owner": "openai", "repo": "codex"},
        supports_secret_env=True,
    ),
    SourceTypeDefinition(
        type="github_user",
        label="GitHub User Events",
        description="Public GitHub user activity events.",
        required_fields=("username",),
        template={"username": "openai"},
        supports_secret_env=True,
    ),
    SourceTypeDefinition(
        type="reddit_subreddit",
        label="Reddit Subreddit",
        description="Public subreddit posts through Reddit JSON endpoints.",
        required_fields=("subreddit",),
        template={"subreddit": "LocalLLaMA", "sort": "hot"},
    ),
    SourceTypeDefinition(
        type="reddit_user",
        label="Reddit User",
        description="Public Reddit user posts.",
        required_fields=("username",),
        template={"username": "spez", "sort": "new"},
    ),
    SourceTypeDefinition(
        type="telegram_channel",
        label="Telegram Public Channel",
        description="Public Telegram channel web preview.",
        required_fields=("channel",),
        template={"channel": "durov"},
    ),
    SourceTypeDefinition(
        type="apify_social",
        label="Apify Social",
        description="Apify-backed public social target.",
        required_fields=("platform", "kind", "target"),
        template={"platform": "x", "kind": "profile", "target": "openai"},
        supports_secret_env=True,
    ),
    SourceTypeDefinition(
        type="hackernews",
        label="Hacker News",
        description="Hacker News top stories from the public Firebase API.",
        required_fields=(),
        template={"fetch_top_stories": 30, "min_score": 100},
    ),
)

_BY_TYPE = {item.type: item for item in _SOURCE_TYPES}


def list_source_types() -> list[dict[str, Any]]:
    """Return source type metadata for API clients."""

    return [item.as_dict() for item in _SOURCE_TYPES]


def validate_secret_env_name(value: str | None) -> str | None:
    """Validate that a value is an environment variable name, not a secret."""

    if value is None or value == "":
        return None
    name = str(value).strip()
    if name.startswith(_SECRET_PREFIXES) or not _ENV_VAR_RE.fullmatch(name):
        raise SourceConfigError("secret_env must be an environment variable name, not a secret value")
    return name


def _text(config: dict[str, Any], key: str, label: str | None = None) -> str:
    value = str(config.get(key) or "").strip()
    if not value:
        raise SourceConfigError(f"{label or key} is required")
    return value


def _bool(value: Any, *, default: bool = True) -> bool:
    if value is None or value == "":
        return default
    if isinstance(value, bool):
        return value
    return str(value).strip().lower() not in {"0", "false", "no", "off"}


def _int(
    config: dict[str, Any],
    key: str,
    *,
    default: int,
    minimum: int | None = None,
    maximum: int | None = None,
) -> int:
    try:
        value = int(config.get(key, default))
    except (TypeError, ValueError) as exc:
        raise SourceConfigError(f"{key} must be an integer") from exc
    if minimum is not None and value < minimum:
        raise SourceConfigError(f"{key} must be at least {minimum}")
    if maximum is not None and value > maximum:
        raise SourceConfigError(f"{key} must be at most {maximum}")
    return value


def _list(value: Any) -> list[str]:
    if value is None or value == "":
        return []
    if isinstance(value, list):
        return [str(item).strip() for item in value if str(item).strip()]
    return [str(value).strip()] if str(value).strip() else []


def _base_config(config: dict[str, Any]) -> dict[str, Any]:
    data = dict(config or {})
    data["enabled"] = _bool(data.get("enabled"), default=True)
    for key in ("topics", "tags", "personal_tags"):
        if key in data:
            data[key] = _list(data.get(key))
    if "token_env" in data:
        data["token_env"] = validate_secret_env_name(data.get("token_env"))
    return data


def _validate_http_url(url: str) -> str:
    parsed = urlparse(url)
    if parsed.scheme not in {"http", "https"} or not parsed.netloc:
        raise SourceConfigError("url must be an http or https URL")
    return url


def _validate_choice(value: str, allowed: set[str], label: str) -> str:
    if value not in allowed:
        raise SourceConfigError(f"{label} must be one of {', '.join(sorted(allowed))}")
    return value


def validate_source_config(source_type: str, config: dict[str, Any] | None) -> dict[str, Any]:
    """Validate and normalize source catalog config for one source type."""

    source_type = str(source_type or "").strip()
    if source_type not in _BY_TYPE:
        raise SourceConfigError(f"unsupported source type: {source_type}")
    data = _base_config(config or {})

    if source_type == "rss":
        url = _validate_http_url(_text(data, "url", "url"))
        data["url"] = url
        data["name"] = str(data.get("name") or url).strip()
        return data

    if source_type == "github_release":
        data["owner"] = _text(data, "owner", "owner")
        data["repo"] = _text(data, "repo", "repo")
        data["type"] = "repo_releases"
        return data

    if source_type == "github_user":
        data["username"] = _text(data, "username", "username")
        data["type"] = "user_events"
        return data

    if source_type == "reddit_subreddit":
        data["subreddit"] = _text(data, "subreddit", "subreddit").removeprefix("r/").strip()
        data["sort"] = _validate_choice(str(data.get("sort") or "hot"), _SUPPORTED_REDDIT_SORTS, "sort")
        data["time_filter"] = _validate_choice(
            str(data.get("time_filter") or "day"),
            _SUPPORTED_REDDIT_TIME_FILTERS,
            "time_filter",
        )
        data["fetch_limit"] = _int(data, "fetch_limit", default=25, minimum=1, maximum=100)
        data["min_score"] = _int(data, "min_score", default=10, minimum=0)
        return data

    if source_type == "reddit_user":
        data["username"] = _text(data, "username", "username").removeprefix("u/").strip()
        data["sort"] = _validate_choice(str(data.get("sort") or "new"), _SUPPORTED_REDDIT_SORTS, "sort")
        data["fetch_limit"] = _int(data, "fetch_limit", default=10, minimum=1, maximum=100)
        return data

    if source_type == "telegram_channel":
        data["channel"] = _text(data, "channel", "channel").lstrip("@").strip()
        data["fetch_limit"] = _int(data, "fetch_limit", default=20, minimum=1, maximum=100)
        return data

    if source_type == "apify_social":
        platform = str(data.get("platform") or "").strip().lower()
        if platform not in _APIFY_KINDS:
            raise SourceConfigError("platform must be one of facebook, instagram, telegram, x")
        kind = str(data.get("kind") or "").strip().lower()
        _validate_choice(kind, _APIFY_KINDS[platform], "kind")
        target = _text(data, "target", "target")
        data["platform"] = platform
        data["kind"] = kind
        data["target"] = target
        data["fetch_limit"] = _int(data, "fetch_limit", default=20, minimum=1, maximum=100)
        analysis_mode = str(data.get("analysis_mode") or "full").strip()
        if analysis_mode not in {"full", "personal_only"}:
            raise SourceConfigError("analysis_mode must be full or personal_only")
        data["analysis_mode"] = analysis_mode
        return data

    if source_type == "hackernews":
        data["fetch_top_stories"] = _int(data, "fetch_top_stories", default=30, minimum=1, maximum=500)
        data["min_score"] = _int(data, "min_score", default=100, minimum=0)
        return data

    raise SourceConfigError(f"unsupported source type: {source_type}")


def source_key(source_type: str, config: dict[str, Any]) -> str:
    """Build a stable identity key for idempotent catalog writes."""

    normalized = validate_source_config(source_type, config)
    if source_type == "rss":
        return f"rss:{normalized['url']}"
    if source_type == "github_release":
        return f"github_release:{normalized['owner'].lower()}/{normalized['repo'].lower()}"
    if source_type == "github_user":
        return f"github_user:{normalized['username'].lower()}"
    if source_type == "reddit_subreddit":
        return f"reddit_subreddit:{normalized['subreddit'].lower()}"
    if source_type == "reddit_user":
        return f"reddit_user:{normalized['username'].lower()}"
    if source_type == "telegram_channel":
        return f"telegram_channel:{normalized['channel'].lower()}"
    if source_type == "apify_social":
        return (
            "apify_social:"
            f"{normalized['platform']}:{normalized['kind']}:{normalized['target'].lower()}"
        )
    if source_type == "hackernews":
        return "hackernews:top"
    raise SourceConfigError(f"unsupported source type: {source_type}")


def build_source_payload(source: dict[str, Any]) -> dict[str, Any]:
    """Return a worker/test payload from one catalog source row."""

    source_type = str(source.get("type") or "")
    payload = validate_source_config(source_type, source.get("config") or {})
    payload["source_type"] = source_type
    secret_env = validate_secret_env_name(source.get("secret_env"))
    if secret_env and not payload.get("token_env"):
        payload["token_env"] = secret_env
    return payload
