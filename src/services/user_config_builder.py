"""Build existing Horizon Config payloads from user-scoped subscriptions."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from ..models import Config
from ..rsshub import is_managed_rsshub_config
from ..storage.service_store import ServiceStore
from ..tag_policy import normalize_channel, normalize_tags


def _workspace_apify_pool_enabled() -> bool:
    try:
        from .apify_key_pool import apify_key_pool_enabled
    except ImportError:
        return False
    return apify_key_pool_enabled()


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
    entry["source_id"] = record.get("source_id")
    entry["subscription_id"] = record.get("subscription_id")
    entry["source_key"] = record.get("source_key")
    entry["source_display_name"] = record.get("display_name")
    entry["catalog_source_type"] = record.get("type")
    entry["source_priority"] = int(record.get("priority") or 0)
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
    if record.get("secret_env") and not (
        record.get("type") == "apify_social" and _workspace_apify_pool_enabled()
    ):
        entry["token_env"] = record["secret_env"]
    if record.get("type") == "rss":
        entry["enforce_public_network"] = bool(record.get("enforce_public_network", True))
    return entry


def _record_with_network_policy(store: ServiceStore, record: dict[str, Any]) -> dict[str, Any]:
    prepared = dict(record)
    if prepared.get("type") == "rss":
        if is_managed_rsshub_config(prepared.get("config")):
            prepared["enforce_public_network"] = False
        else:
            owner = store.get_user(str(prepared.get("owner_user_id") or ""))
            prepared["enforce_public_network"] = bool(
                prepared.get("enforce_public_network")
            ) or not (
                owner and owner.get("role") in {"owner", "admin"}
            )
    if prepared.get("type") == "apify_social":
        config = deepcopy(prepared.get("config") or {})
        if config.get("platform") == "instagram" and config.get("kind") == "profile":
            avatar = store.connect().execute(
                """
                SELECT 1 FROM media_assets
                WHERE workspace_id = ? AND source_id = ?
                  AND asset_kind = 'source_avatar' AND status = 'ready'
                LIMIT 1
                """,
                (prepared.get("workspace_id"), prepared.get("source_id")),
            ).fetchone()
            config["fetch_profile_details"] = avatar is None
            prepared["config"] = config
    return prepared


def _disable_non_catalog_sources(sources: dict[str, Any]) -> None:
    """Prevent a user-scoped run from inheriting unrelated global sources."""
    for key in ("twitter", "openbb", "ossinsight"):
        current = sources.get(key)
        if isinstance(current, dict):
            sources[key] = {**current, "enabled": False}


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
        if record.get("secret_env") and not _workspace_apify_pool_enabled():
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
    sources["hackernews"] = {**sources.get("hackernews", {}), "enabled": False}
    sources["reddit"] = {**sources["reddit"], "enabled": False, "subreddits": [], "users": []}
    sources["telegram"] = {**sources["telegram"], "enabled": False, "channels": []}
    sources["apify_social"] = {
        **sources["apify_social"],
        "enabled": False,
        "subscriptions": [],
    }
    _disable_non_catalog_sources(sources)

    records = store.list_enabled_user_subscriptions_with_sources(
        workspace_id=workspace_id,
        user_id=user_id,
    )
    for record in records:
        _append_source(sources, _record_with_network_policy(store, record))
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
