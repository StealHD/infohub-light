"""Runtime resolution and typed state access for workspace system settings."""

from __future__ import annotations

import json
import os
import sqlite3
from dataclasses import asdict
from typing import TYPE_CHECKING, Any, Mapping

from ..storage.system_settings_v31_schema import (
    migration_marker_exists,
    schema_shapes_valid,
)
from .system_settings_registry import (
    SYSTEM_SETTING_DEFINITIONS,
    InvalidSystemSetting,
    SettingValue,
    canonical_setting_key,
    parse_environment_value,
    validate_setting_dependencies,
    validate_setting_value,
)

if TYPE_CHECKING:
    from ..storage.service_store import ServiceStore


class SystemSettingsUnavailable(RuntimeError):
    code = "system_settings_migration_required"


class SystemSettingsGenerationConflict(RuntimeError):
    code = "system_settings_generation_conflict"


def system_settings_ready(connection: sqlite3.Connection) -> bool:
    try:
        return migration_marker_exists(connection) and schema_shapes_valid(connection)
    except sqlite3.Error:
        return False


def _overrides(
    connection: sqlite3.Connection,
    workspace_id: str,
) -> tuple[dict[str, SettingValue], int] | None:
    if not system_settings_ready(connection):
        return None
    row = connection.execute(
        """SELECT overrides_json, generation FROM workspace_system_settings
           WHERE workspace_id=?""",
        (workspace_id,),
    ).fetchone()
    if row is None:
        return None
    try:
        raw = json.loads(str(row["overrides_json"]))
    except (TypeError, json.JSONDecodeError) as error:
        raise SystemSettingsUnavailable("system settings row is corrupt") from error
    if not isinstance(raw, dict):
        raise SystemSettingsUnavailable("system settings row is corrupt")
    values: dict[str, SettingValue] = {}
    for raw_key, value in raw.items():
        key = canonical_setting_key(str(raw_key))
        values[key] = validate_setting_value(key, value)
    return values, int(row["generation"])


def resolve_system_setting(
    store: ServiceStore,
    workspace_id: str,
    key_or_alias: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> SettingValue:
    """Resolve DB override > environment fallback > compiled default."""

    key = canonical_setting_key(key_or_alias)
    conn = connection or store.connect()
    state = _overrides(conn, str(workspace_id))
    if state is not None and key in state[0]:
        return state[0][key]
    return parse_environment_value(SYSTEM_SETTING_DEFINITIONS[key])


def resolve_system_settings(
    store: ServiceStore,
    workspace_id: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> dict[str, SettingValue]:
    conn = connection or store.connect()
    return {
        key: resolve_system_setting(store, workspace_id, key, connection=conn)
        for key in SYSTEM_SETTING_DEFINITIONS
    }


def resolve_system_setting_int(
    store: ServiceStore,
    workspace_id: str,
    key_or_alias: str,
    *,
    connection: sqlite3.Connection | None = None,
) -> int:
    return int(resolve_system_setting(
        store, workspace_id, key_or_alias, connection=connection
    ))


def _normalize_changes(
    changes: Mapping[str, Any],
) -> dict[str, SettingValue | None]:
    if not changes or len(changes) > 20:
        raise InvalidSystemSetting("changes must contain between 1 and 20 settings")
    normalized: dict[str, SettingValue | None] = {}
    for raw_key, value in changes.items():
        key = canonical_setting_key(str(raw_key))
        if key in normalized:
            raise InvalidSystemSetting(f"duplicate system setting: {key}")
        normalized[key] = None if value is None else validate_setting_value(key, value)
    return normalized


class SystemSettingsService:
    """Expose safe metadata and generation-aware settings state."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    def require_ready(self, connection: sqlite3.Connection | None = None) -> None:
        if not system_settings_ready(connection or self.store.connect()):
            raise SystemSettingsUnavailable(
                "global 31 system settings migration must be applied"
            )

    def state(
        self,
        workspace_id: str,
        *,
        connection: sqlite3.Connection | None = None,
    ) -> tuple[dict[str, SettingValue], int]:
        conn = connection or self.store.connect()
        self.require_ready(conn)
        state = _overrides(conn, workspace_id)
        if state is None:
            raise SystemSettingsUnavailable("workspace system settings row is missing")
        return state

    def list_settings(self, workspace_id: str) -> dict[str, Any]:
        overrides, generation = self.state(workspace_id)
        effective = resolve_system_settings(self.store, workspace_id)
        settings: list[dict[str, Any]] = []
        for key, definition in SYSTEM_SETTING_DEFINITIONS.items():
            source = "override" if key in overrides else (
                "environment" if definition.env_name in os.environ else "default"
            )
            metadata = asdict(definition)
            metadata.update({
                "value": effective[key],
                "fallback_value": parse_environment_value(definition),
                "source": source,
                "override": overrides.get(key),
            })
            settings.append(metadata)
        return {"generation": generation, "settings": settings}

    def preview(
        self,
        workspace_id: str,
        *,
        expected_generation: int,
        changes: Mapping[str, Any],
        connection: sqlite3.Connection | None = None,
    ) -> dict[str, Any]:
        conn = connection or self.store.connect()
        overrides, generation = self.state(workspace_id, connection=conn)
        if generation != int(expected_generation):
            raise SystemSettingsGenerationConflict("system settings generation changed")
        normalized = _normalize_changes(changes)
        next_overrides = dict(overrides)
        for key, value in normalized.items():
            if value is None:
                next_overrides.pop(key, None)
            else:
                next_overrides[key] = value
        effective = {
            key: next_overrides.get(key, parse_environment_value(definition))
            for key, definition in SYSTEM_SETTING_DEFINITIONS.items()
        }
        validate_setting_dependencies(effective)
        if (
            "storage.compact_feed_snapshots_enabled" in normalized
            and effective["storage.compact_feed_snapshots_enabled"] is True
            and self.store.feed_storage_v3_migration_required()
        ):
            raise InvalidSystemSetting(
                "compact Feed snapshots require feed storage v3"
            )
        warnings: list[str] = []
        for key, value in normalized.items():
            if value == 0:
                warnings.append(f"{key}=0 will block the next admission")
        if int(effective["limits.max_workspace_fetch_attempts_per_day"]) > int(
            effective["limits.max_provider_fetch_attempts_per_day"]
        ):
            warnings.append(
                "workspace fetch capacity exceeds the per-provider capacity"
            )
        preview_changes = [
            {
                "key": key,
                "env_name": SYSTEM_SETTING_DEFINITIONS[key].env_name,
                "before": resolve_system_setting(
                    self.store, workspace_id, key, connection=conn
                ),
                "after": effective[key],
                "reset": value is None,
                "risk": SYSTEM_SETTING_DEFINITIONS[key].risk,
                "effect_timing": SYSTEM_SETTING_DEFINITIONS[key].effect_timing,
            }
            for key, value in normalized.items()
        ]
        return {
            "base_generation": generation,
            "changes": normalized,
            "next_overrides": next_overrides,
            "preview_changes": preview_changes,
            "warnings": warnings,
        }


__all__ = [
    "SystemSettingsGenerationConflict", "SystemSettingsService",
    "SystemSettingsUnavailable", "resolve_system_setting", "resolve_system_setting_int",
    "resolve_system_settings",
    "system_settings_ready",
]
