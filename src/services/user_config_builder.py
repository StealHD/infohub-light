"""Build existing Horizon Config payloads from user-scoped subscriptions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..models import Config
from ..storage.service_store import ServiceStore
from ..tag_policy import normalize_channel, normalize_tags


def _ensure_sources(data: dict[str, Any]) -> dict[str, Any]:
    sources = data.setdefault("sources", {})
    sources.setdefault("rss", [])
    sources.setdefault("github", [])
    sources.setdefault("hackernews", {"enabled": False})
    sources.setdefault("reddit", {"enabled": False, "subreddits": [], "users": [], "fetch_comments": 5})
    sources.setdefault("telegram", {"enabled": False, "channels": []})
    sources.setdefault(
        "apify_social",
        {
            "enabled": False,
            "token_env": "APIFY_TOKEN",
            "token_envs": ["APIFY_TOKEN"],
            "subscriptions": [],
        },
    )
    return sources


def _entry_with_overrides(record: dict[str, Any]) -> dict[str, Any]:
    entry = deepcopy(record["config"])
    entry.setdefault("enabled", True)
    channel = record.get("override_channel") or record.get("default_channel")
    if channel:
        normalized_channel = normalize_channel(channel)
        entry["channel"] = normalized_channel
        entry["category"] = normalized_channel
        if record["type"] == "telegram_channel":
            entry["hub_channel"] = normalized_channel
    topics = record.get("override_topics") or record.get("default_topics") or []
    if topics:
        normalized_topics = normalize_tags(topics, max_tags=None, allow_custom=True)
        entry["topics"] = normalized_topics
        entry["tags"] = normalized_topics
    personal_tags = record.get("personal_tags") or []
    if personal_tags:
        entry["personal_tags"] = normalize_tags(
            personal_tags,
            max_tags=None,
            allow_custom=True,
        )
    if record.get("analysis_mode"):
        entry["analysis_mode"] = record["analysis_mode"]
    if record.get("secret_env"):
        entry["token_env"] = record["secret_env"]
    return entry


def _append_source(sources: dict[str, Any], record: dict[str, Any]) -> None:
    source_type = str(record["type"])
    entry = _entry_with_overrides(record)

    if source_type == "rss":
        entry.setdefault("name", record["display_name"])
        sources["rss"].append(entry)
        return

    if source_type in {"github", "github_release", "github_user"}:
        if source_type == "github_release":
            entry.setdefault("type", "repo_releases")
        elif source_type == "github_user":
            entry.setdefault("type", "user_events")
        sources["github"].append(entry)
        return

    if source_type == "hackernews":
        sources["hackernews"] = {**entry, "enabled": True}
        return

    if source_type == "reddit_subreddit":
        sources["reddit"]["enabled"] = True
        sources["reddit"].setdefault("subreddits", []).append(entry)
        return

    if source_type == "reddit_user":
        sources["reddit"]["enabled"] = True
        sources["reddit"].setdefault("users", []).append(entry)
        return

    if source_type == "telegram_channel":
        sources["telegram"]["enabled"] = True
        sources["telegram"].setdefault("channels", []).append(entry)
        return

    if source_type == "apify_social":
        apify = sources["apify_social"]
        apify["enabled"] = True
        apify.setdefault("subscriptions", []).append(entry)
        if record.get("secret_env"):
            names = list(apify.get("token_envs") or [])
            if record["secret_env"] not in names:
                names.append(record["secret_env"])
            apify["token_envs"] = names
            apify["token_env"] = names[0]
        return

    if source_type == "ossinsight":
        sources["ossinsight"] = {**entry, "enabled": True}
        return

    if source_type == "openbb":
        sources["openbb"] = {**entry, "enabled": True}
        return

    raise ValueError(f"unsupported source type: {source_type}")


def build_user_config_data(
    *,
    store: ServiceStore,
    workspace_id: str,
    user_id: str,
    base_config: dict[str, Any] | Config,
) -> dict[str, Any]:
    """Return a Config-compatible dict for one user's enabled subscriptions."""

    if isinstance(base_config, Config):
        data = base_config.model_dump(mode="json")
    else:
        data = deepcopy(base_config)
    sources = _ensure_sources(data)
    for key in ("rss", "github"):
        sources[key] = []
    sources["hackernews"] = {"enabled": False, **sources.get("hackernews", {})}
    sources["reddit"] = {**sources["reddit"], "enabled": False, "subreddits": [], "users": []}
    sources["telegram"] = {**sources["telegram"], "enabled": False, "channels": []}
    sources["apify_social"] = {
        **sources["apify_social"],
        "enabled": False,
        "subscriptions": [],
    }

    records = store.list_enabled_user_subscriptions_with_sources(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    for record in records:
        _append_source(sources, record)
    return data


def build_user_config(
    *,
    store: ServiceStore,
    workspace_id: str,
    user_id: str,
    base_config: dict[str, Any] | Config,
) -> Config:
    """Build and validate a Config for one user."""

    return Config.model_validate(
        build_user_config_data(
            store=store,
            workspace_id=workspace_id,
            user_id=user_id,
            base_config=base_config,
        )
    )
