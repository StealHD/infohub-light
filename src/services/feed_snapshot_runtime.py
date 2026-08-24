"""Runtime switch for compact Feed snapshot writes."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .system_settings import resolve_system_setting
from .system_settings_registry import SYSTEM_SETTING_DEFINITIONS, parse_environment_value

if TYPE_CHECKING:
    from ..storage.service_store import ServiceStore


def compact_feed_snapshots_enabled(
    store: ServiceStore | None = None,
    *,
    workspace_id: str = "default",
) -> bool:
    key = "storage.compact_feed_snapshots_enabled"
    value = (resolve_system_setting(store, workspace_id, key) if store else
             parse_environment_value(SYSTEM_SETTING_DEFINITIONS[key]))
    return bool(value)


__all__ = ["compact_feed_snapshots_enabled"]
