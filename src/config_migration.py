"""Configuration compatibility migrations."""

from __future__ import annotations

from copy import deepcopy
from typing import Any

from .tag_policy import CANONICAL_TAGS, clean_custom_tag, normalize_tags


def _append_unique(values: list[str], value: str) -> None:
    if value and value not in values:
        values.append(value)


def split_ai_and_personal_tags(values: Any) -> tuple[list[str], list[str]]:
    """Normalize legacy tag lists as reading topics.

    The old implementation moved unknown values into ``personal_tags`` because
    ``tags`` represented a fixed AI taxonomy. Tags now represent reading
    topics, so custom values must remain in the topic layer.
    """
    if not isinstance(values, list):
        return [], []
    return normalize_tags(values, strict=False, max_tags=None, allow_custom=True), []


def normalize_personal_tags(values: Any) -> list[str]:
    """Normalize user-owned personal tags without mapping them into AI taxonomy."""
    personal_tags: list[str] = []
    if not isinstance(values, list):
        return personal_tags
    for raw in values:
        text = str(raw or "").strip()
        if not text:
            continue
        _append_unique(personal_tags, clean_custom_tag(text))
    return personal_tags


def _migrate_source_item(item: Any) -> None:
    if not isinstance(item, dict):
        return
    ai_tags, moved_personal = split_ai_and_personal_tags(item.get("tags", []))
    existing_personal = normalize_personal_tags(item.get("personal_tags", []))
    item["tags"] = ai_tags
    personal_tags = existing_personal[:]
    for tag in moved_personal:
        _append_unique(personal_tags, tag)
    if personal_tags:
        item["personal_tags"] = personal_tags
    else:
        item.pop("personal_tags", None)


def _migrate_source_list(items: Any) -> None:
    if not isinstance(items, list):
        return
    for item in items:
        _migrate_source_item(item)


def _collect_source_personal_tags(sources: dict[str, Any]) -> list[str]:
    collected: list[str] = []

    def collect_item(item: Any) -> None:
        if not isinstance(item, dict):
            return
        for tag in normalize_personal_tags(item.get("personal_tags", [])):
            _append_unique(collected, tag)

    def collect_list(items: Any) -> None:
        if isinstance(items, list):
            for item in items:
                collect_item(item)

    collect_list(sources.get("rss"))
    collect_list(sources.get("github"))
    reddit = sources.get("reddit")
    if isinstance(reddit, dict):
        collect_list(reddit.get("subreddits"))
        collect_list(reddit.get("users"))
    telegram = sources.get("telegram")
    if isinstance(telegram, dict):
        collect_list(telegram.get("channels"))
    apify_social = sources.get("apify_social")
    if isinstance(apify_social, dict):
        collect_list(apify_social.get("subscriptions"))
    return collected


def migrate_config_tag_layers(data: dict[str, Any]) -> dict[str, Any]:
    """Move legacy custom tags out of AI tag fields into personal_tags."""
    migrated = deepcopy(data)

    ai_tags, moved_personal = split_ai_and_personal_tags(migrated.get("tags", []))
    existing_personal = normalize_personal_tags(migrated.get("personal_tags", []))
    migrated["tags"] = ai_tags or list(CANONICAL_TAGS)
    personal_tags = existing_personal[:]
    for tag in moved_personal:
        _append_unique(personal_tags, tag)
    migrated["personal_tags"] = personal_tags

    sources = migrated.get("sources")
    if isinstance(sources, dict):
        _migrate_source_list(sources.get("rss"))
        _migrate_source_list(sources.get("github"))

        reddit = sources.get("reddit")
        if isinstance(reddit, dict):
            _migrate_source_list(reddit.get("subreddits"))
            _migrate_source_list(reddit.get("users"))

        telegram = sources.get("telegram")
        if isinstance(telegram, dict):
            _migrate_source_list(telegram.get("channels"))

        apify_social = sources.get("apify_social")
        if isinstance(apify_social, dict):
            _migrate_source_list(apify_social.get("subscriptions"))
        for tag in _collect_source_personal_tags(sources):
            _append_unique(personal_tags, tag)

    migrated["personal_tags"] = personal_tags
    return migrated
