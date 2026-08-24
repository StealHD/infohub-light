"""Remote MCP tool-filter compatibility helpers for OpenClaw setup."""

from __future__ import annotations

from typing import Any


LEGACY_READ_TOOL_FILTER = (
    "get_my_feed",
    "get_item",
    "list_subscriptions",
    "source_health",
    "list_jobs",
    "get_job",
    "get_source_setup_guide",
    "search_bilibili_users",
    "list_available_sources",
    "diagnose_source",
    "diagnose_job",
    "query_operation_logs",
)
READ_TOOL_FILTER = (
    *LEGACY_READ_TOOL_FILTER[:8],
    "resolve_source",
    *LEGACY_READ_TOOL_FILTER[8:],
)
LEGACY_FULL_TOOL_FILTER = (
    *LEGACY_READ_TOOL_FILTER[:9],
    "prepare_create_subscription",
    "prepare_update_subscription",
    "prepare_delete_subscription",
    "apply_subscription_change",
    *LEGACY_READ_TOOL_FILTER[9:],
)
FULL_TOOL_FILTER = (
    *READ_TOOL_FILTER[:10],
    "prepare_create_subscription",
    "prepare_update_subscription",
    "prepare_delete_subscription",
    "apply_subscription_change",
    *READ_TOOL_FILTER[10:],
)
SYSTEM_SETTINGS_TOOL_FILTER = (
    *READ_TOOL_FILTER,
    "list_system_settings",
    "prepare_update_system_settings",
    "apply_system_settings_change",
)


def standard_tool_filter_upgrade(
    payload: Any,
) -> tuple[tuple[str, ...] | None, bool]:
    """Upgrade only a byte-for-byte standard legacy Inteliscope filter.

    The boolean reports a custom filter that must remain untouched.
    """

    if not isinstance(payload, dict):
        return None, False
    candidates = [payload]
    for key in ("server", "config"):
        nested = payload.get(key)
        if isinstance(nested, dict):
            candidates.append(nested)
    include: Any = None
    found = False
    for candidate in candidates:
        tool_filter = candidate.get("toolFilter")
        if isinstance(tool_filter, dict) and "include" in tool_filter:
            if set(tool_filter) != {"include"}:
                return None, True
            include = tool_filter.get("include")
            found = True
            break
    if not found:
        return None, False
    if not isinstance(include, list) or not all(
        isinstance(item, str) for item in include
    ):
        return None, True
    current = tuple(include)
    if current == LEGACY_READ_TOOL_FILTER:
        return READ_TOOL_FILTER, False
    if current == LEGACY_FULL_TOOL_FILTER:
        return FULL_TOOL_FILTER, False
    if current in {
        READ_TOOL_FILTER,
        FULL_TOOL_FILTER,
        SYSTEM_SETTINGS_TOOL_FILTER,
    }:
        return None, False
    return None, True
