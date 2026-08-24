"""Typed allowlist for workspace runtime system settings."""

from __future__ import annotations

import os
from dataclasses import dataclass
from typing import Any, Literal, Mapping


SettingValue = bool | int
SettingKind = Literal["boolean", "integer"]


@dataclass(frozen=True, slots=True)
class SystemSettingDefinition:
    key: str
    env_name: str
    kind: SettingKind
    default: SettingValue
    category: str
    minimum: int | None = None
    maximum: int | None = None
    risk: str = "low"
    effect_timing: str = "next_operation"
    description: str = ""


def _integer(
    key: str,
    env_name: str,
    default: int,
    category: str,
    minimum: int,
    maximum: int,
    *,
    risk: str = "medium",
    effect_timing: str = "next_operation",
    description: str,
) -> SystemSettingDefinition:
    return SystemSettingDefinition(
        key, env_name, "integer", default, category, minimum, maximum,
        risk, effect_timing, description,
    )


def _boolean(
    key: str,
    env_name: str,
    default: bool,
    category: str,
    *,
    risk: str = "medium",
    effect_timing: str = "next_operation",
    description: str,
) -> SystemSettingDefinition:
    return SystemSettingDefinition(
        key, env_name, "boolean", default, category, None, None,
        risk, effect_timing, description,
    )


_DEFINITIONS = (
    _integer("limits.max_fetch_jobs_per_day", "INFOHUB_MAX_FETCH_JOBS_PER_DAY", 100,
             "capacity", 0, 10_000, description="每用户每日可创建的抓取任务上限。"),
    _integer("limits.max_sources_per_user", "INFOHUB_MAX_SOURCES_PER_USER", 100,
             "capacity", 0, 5_000, description="每用户可启用的来源上限。"),
    _integer("limits.max_ai_items_per_day", "INFOHUB_MAX_AI_ITEMS_PER_DAY", 1_000,
             "capacity", 0, 10_000, description="每用户每日可进入 AI 分析的内容上限。"),
    _integer("limits.max_workspace_ai_attempts_per_day",
             "INFOHUB_MAX_WORKSPACE_AI_ATTEMPTS_PER_DAY", 1_000, "capacity", 0,
             10_000, description="工作区每日 AI 提供商调用尝试上限。"),
    _integer("limits.max_workspace_fetch_attempts_per_day",
             "INFOHUB_MAX_WORKSPACE_FETCH_ATTEMPTS_PER_DAY", 100, "capacity", 0,
             10_000, description="工作区每日上游抓取尝试总上限。"),
    _integer("limits.max_provider_fetch_attempts_per_day",
             "INFOHUB_MAX_PROVIDER_FETCH_ATTEMPTS_PER_DAY", 100, "capacity", 0,
             10_000, description="单个提供商每日抓取尝试上限。"),
    _integer("jobs.max_attempts", "HORIZON_JOB_MAX_ATTEMPTS", 3, "jobs", 1, 10,
             effect_timing="new_jobs", description="新任务冻结的最大尝试次数。"),
    _integer("jobs.retry_base_seconds", "HORIZON_WORKER_RETRY_BASE_SECONDS", 30,
             "jobs", 1, 3_600, effect_timing="next_failure",
             description="任务下次失败时使用的指数退避基数。"),
    _integer("jobs.retention_days", "HORIZON_JOB_RETENTION_DAYS", 14, "jobs", 1,
             365, effect_timing="new_jobs", description="新任务冻结的保留天数。"),
    _boolean("scheduling.automatic_enqueue_enabled", "HORIZON_SCHEDULE_POLL_ENABLED",
             True, "jobs", risk="high", description="是否创建新的周期抓取任务。"),
    _integer("retention.feed_snapshot_days", "HORIZON_FEED_SNAPSHOT_RETENTION_DAYS",
             30, "retention", 1, 3_650, effect_timing="next_maintenance",
             description="Feed 快照保留天数。"),
    _integer("retention.max_feed_snapshots_per_user",
             "HORIZON_MAX_FEED_SNAPSHOTS_PER_USER", 20, "retention", 1, 10_000,
             effect_timing="next_maintenance", description="每用户保留的快照数量上限。"),
    _integer("retention.source_content_days", "HORIZON_SOURCE_CONTENT_RETENTION_DAYS",
             7, "retention", 1, 3_650, effect_timing="next_maintenance",
             description="来源内容缓存保留天数。"),
    _integer("retention.analysis_cache_days", "HORIZON_ANALYSIS_CACHE_RETENTION_DAYS",
             30, "retention", 1, 3_650, effect_timing="next_maintenance",
             description="分析缓存保留天数。"),
    _integer("retention.usage_days", "HORIZON_USAGE_RETENTION_DAYS", 90,
             "retention", 1, 3_650, effect_timing="next_maintenance",
             description="用量事件保留天数。"),
    _boolean("storage.compact_feed_snapshots_enabled",
             "HORIZON_COMPACT_FEED_SNAPSHOTS_ENABLED", True, "storage", risk="high",
             effect_timing="next_snapshot", description="新快照是否使用紧凑存储格式。"),
    _boolean("acquisition.shared_enabled", "HORIZON_SHARED_ACQUISITION_ENABLED", False,
             "acquisition", risk="high", description="是否复用同一来源的中性抓取结果。"),
    _integer("acquisition.min_ttl_minutes",
             "HORIZON_SHARED_ACQUISITION_MIN_TTL_MINUTES", 5, "acquisition", 1,
             1_440, description="共享抓取结果的最小新鲜周期。"),
    _integer("acquisition.max_ttl_minutes",
             "HORIZON_SHARED_ACQUISITION_MAX_TTL_MINUTES", 60, "acquisition", 1,
             1_440, description="共享抓取结果的最大新鲜周期。"),
    _integer("acquisition.fallback_ttl_minutes",
             "HORIZON_SHARED_ACQUISITION_FALLBACK_TTL_MINUTES", 30, "acquisition", 1,
             1_440, description="无调度周期时的共享抓取新鲜周期。"),
    _integer("acquisition.failure_backoff_seconds",
             "HORIZON_SHARED_ACQUISITION_FAILURE_BACKOFF_SECONDS", 30, "acquisition", 1,
             300, effect_timing="next_failure", description="共享抓取失败退避基数。"),
)

SYSTEM_SETTING_DEFINITIONS = {item.key: item for item in _DEFINITIONS}
SYSTEM_SETTING_ALIASES = {item.env_name: item.key for item in _DEFINITIONS}
MANAGED_SYSTEM_SETTING_ENV_NAMES = frozenset(SYSTEM_SETTING_ALIASES)


class InvalidSystemSetting(ValueError):
    code = "invalid_system_setting"


def canonical_setting_key(key_or_alias: str) -> str:
    key = str(key_or_alias).strip()
    canonical = SYSTEM_SETTING_ALIASES.get(key, key)
    if canonical not in SYSTEM_SETTING_DEFINITIONS:
        raise InvalidSystemSetting(f"unsupported system setting: {key}")
    return canonical


def validate_setting_value(key_or_alias: str, value: Any) -> SettingValue:
    key = canonical_setting_key(key_or_alias)
    definition = SYSTEM_SETTING_DEFINITIONS[key]
    if definition.kind == "boolean":
        if not isinstance(value, bool):
            raise InvalidSystemSetting(f"{key} must be a boolean")
        return value
    if isinstance(value, bool) or not isinstance(value, int):
        raise InvalidSystemSetting(f"{key} must be an integer")
    if value < int(definition.minimum) or value > int(definition.maximum):
        raise InvalidSystemSetting(
            f"{key} must be between {definition.minimum} and {definition.maximum}"
        )
    return value


def parse_environment_value(definition: SystemSettingDefinition) -> SettingValue:
    raw = os.getenv(definition.env_name)
    if raw is None:
        return definition.default
    if definition.kind == "boolean":
        normalized = raw.strip().casefold()
        if normalized in {"1", "true", "yes", "on"}:
            return True
        if normalized in {"0", "false", "no", "off"}:
            return False
        raise InvalidSystemSetting(f"{definition.env_name} must be a boolean")
    try:
        parsed = int(raw.strip())
    except ValueError as error:
        raise InvalidSystemSetting(f"{definition.env_name} must be an integer") from error
    return validate_setting_value(definition.key, parsed)


def validate_setting_dependencies(values: Mapping[str, SettingValue]) -> None:
    minimum = int(values["acquisition.min_ttl_minutes"])
    fallback = int(values["acquisition.fallback_ttl_minutes"])
    maximum = int(values["acquisition.max_ttl_minutes"])
    if not minimum <= fallback <= maximum:
        raise InvalidSystemSetting(
            "acquisition TTL values must satisfy min_ttl <= fallback_ttl <= max_ttl"
        )


__all__ = [
    "InvalidSystemSetting", "MANAGED_SYSTEM_SETTING_ENV_NAMES",
    "SYSTEM_SETTING_ALIASES", "SYSTEM_SETTING_DEFINITIONS", "SettingValue",
    "SystemSettingDefinition", "canonical_setting_key", "parse_environment_value",
    "validate_setting_dependencies", "validate_setting_value",
]
