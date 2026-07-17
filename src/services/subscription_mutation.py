"""Shared subscription mutation planning and atomic application.

The Agent-facing planner is deliberately narrower than the REST catalog API:
it can subscribe to visible shared sources, but it can only create and mutate
the caller's own private sources.  REST adapters use the explicit ``rest_*``
methods below so administrator catalog permissions are not accidentally
reduced to the Agent boundary.
"""

from __future__ import annotations

import json
from dataclasses import dataclass
from typing import Any, Literal

from ..storage.service_store import ServiceStore, SourceKeyConflictError
from .media_cache import MediaCacheService, PostCommitMediaCleanup
from .quota import QuotaExceeded, QuotaService
from .source_health import SourceHealthService
from .source_schedule import (
    DEFAULT_SOURCE_INTERVAL_MINUTES,
    SOURCE_ALLOWED_INTERVALS,
    SourceScheduleService,
    SourceScheduleUnavailableError,
)
from .source_type_registry import (
    SourceConfigError,
    normalize_source_setup_input,
    project_catalog_source_public_summary,
    source_key,
    validate_normalized_source_setup,
    validate_public_source_metadata,
    validate_source_config,
)


_MISSING = object()
_WRITABLE_ROLES = {"owner", "admin", "member"}
_SOURCE_UPDATE_FIELDS = {
    "display_name",
    "description",
    "default_channel",
    "default_topics",
    "config",
    "enabled",
}
_SUBSCRIPTION_FIELDS = {
    "enabled",
    "override_channel",
    "override_topics",
    "personal_tags",
    "analysis_mode",
    "priority",
}
_SCHEDULE_FIELDS = {"enabled", "interval_minutes"}
_PLAN_SNAPSHOT_VERSION = 1
_PLAN_FACTORY_TOKEN = object()
_PLAN_SNAPSHOT_KEYS = {
    "version",
    "kind",
    "normalized",
    "preview",
    "targets",
    "fingerprints",
}
_CATALOG_SOURCE_TYPES = {
    "rss",
    "github_release",
    "github_user",
    "reddit_subreddit",
    "reddit_user",
    "telegram_channel",
    "apify_social",
    "hackernews",
}


class SubscriptionMutationError(ValueError):
    """Stable domain error suitable for REST and MCP adapters."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        action: str = "",
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code
        self.action = action


@dataclass(frozen=True, slots=True)
class SubscriptionActor:
    workspace_id: str
    user_id: str
    role: str

    @classmethod
    def from_user(cls, user: dict[str, Any]) -> "SubscriptionActor":
        return cls(
            str(user["workspace_id"]),
            str(user["id"]),
            str(user["role"]),
        )


@dataclass(frozen=True, slots=True, init=False)
class SubscriptionChangePlan:
    kind: Literal["create", "update", "delete"]
    _payload_json: str
    _preview_json: str
    _target_ids_json: str
    _fingerprints_json: str
    _factory_token: object

    def __init__(self, *_args: Any, **_kwargs: Any) -> None:
        raise TypeError(
            "subscription change plans require a planner or restore entrypoint"
        )

    @classmethod
    def _from_validated_snapshot(
        cls,
        kind: Literal["create", "update", "delete"],
        payload: dict[str, Any],
        preview: dict[str, Any],
        target_ids: dict[str, str],
        fingerprints: dict[str, str | None],
    ) -> "SubscriptionChangePlan":
        if kind not in {"create", "update", "delete"}:
            raise ValueError("invalid subscription change kind")
        plan = object.__new__(cls)
        object.__setattr__(plan, "kind", kind)
        object.__setattr__(plan, "_payload_json", cls._seal(payload, "payload"))
        object.__setattr__(plan, "_preview_json", cls._seal(preview, "preview"))
        object.__setattr__(
            plan, "_target_ids_json", cls._seal(target_ids, "target_ids")
        )
        object.__setattr__(
            plan,
            "_fingerprints_json",
            cls._seal(fingerprints, "fingerprints"),
        )
        object.__setattr__(plan, "_factory_token", _PLAN_FACTORY_TOKEN)
        return plan

    @staticmethod
    def _seal(value: dict[str, Any], field: str) -> str:
        if not isinstance(value, dict):
            raise TypeError(f"{field} must be an object")
        try:
            return json.dumps(
                value,
                ensure_ascii=False,
                sort_keys=True,
                separators=(",", ":"),
                allow_nan=False,
            )
        except (TypeError, ValueError) as exc:
            raise TypeError(f"{field} must contain canonical JSON data") from exc

    @staticmethod
    def _copy(serialized: str) -> dict[str, Any]:
        value = json.loads(serialized)
        if not isinstance(value, dict):  # guarded by _seal; retain fail-closed shape
            raise TypeError("sealed plan field must be an object")
        return value

    @property
    def payload(self) -> dict[str, Any]:
        return self._copy(self._payload_json)

    @property
    def preview(self) -> dict[str, Any]:
        return self._copy(self._preview_json)

    @property
    def target_ids(self) -> dict[str, str]:
        return self._copy(self._target_ids_json)

    @property
    def fingerprints(self) -> dict[str, str | None]:
        return self._copy(self._fingerprints_json)

    def to_snapshot(self) -> dict[str, Any]:
        """Return the versioned JSON-safe representation used by proposals."""

        return {
            "version": _PLAN_SNAPSHOT_VERSION,
            "kind": self.kind,
            "normalized": self.payload,
            "preview": self.preview,
            "targets": self.target_ids,
            "fingerprints": self.fingerprints,
        }


class SubscriptionMutationService:
    """Plan Agent-safe changes and apply every lifecycle change atomically."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        quota: QuotaService | None = None,
        source_schedules: SourceScheduleService | None = None,
        source_health: SourceHealthService | None = None,
        media_cache: MediaCacheService | None = None,
    ) -> None:
        self.store = store
        self.quota = quota or QuotaService(store)
        self.source_schedules = source_schedules or SourceScheduleService(
            store, quota=self.quota
        )
        self.source_health = source_health or SourceHealthService(store)
        self.media_cache = media_cache

    @staticmethod
    def _error(
        code: str,
        message: str,
        *,
        status_code: int = 400,
        action: str = "",
    ) -> SubscriptionMutationError:
        return SubscriptionMutationError(
            code, message, status_code=status_code, action=action
        )

    def _live_actor(self, actor: SubscriptionActor) -> dict[str, Any]:
        user = self.store.get_user(actor.user_id)
        if (
            user is None
            or str(user["workspace_id"]) != actor.workspace_id
            or not bool(user.get("enabled"))
        ):
            raise self._error("not_found", "user not found", status_code=404)
        if str(user.get("role")) not in _WRITABLE_ROLES:
            raise self._error(
                "forbidden", "viewer cannot modify subscriptions", status_code=403
            )
        return user

    @staticmethod
    def _strict_bool(value: Any, field: str) -> bool:
        if not isinstance(value, bool):
            raise SubscriptionMutationError(
                "invalid_request", f"{field} must be a boolean"
            )
        return value

    @staticmethod
    def _strict_string_or_none(value: Any, field: str) -> str | None:
        if value is not None and not isinstance(value, str):
            raise SubscriptionMutationError(
                "invalid_request", f"{field} must be a string or null"
            )
        return value

    @staticmethod
    def _string_list(value: Any, field: str) -> list[str]:
        if not isinstance(value, list) or any(
            not isinstance(item, str) for item in value
        ):
            raise SubscriptionMutationError(
                "invalid_request", f"{field} must be a list of strings"
            )
        return list(value)

    def _normalize_subscription(
        self,
        values: dict[str, Any] | None,
        *,
        create: bool,
    ) -> dict[str, Any]:
        if values is None:
            values = {}
        if not isinstance(values, dict):
            raise self._error("invalid_request", "subscription must be an object")
        unknown = set(values) - _SUBSCRIPTION_FIELDS
        if unknown:
            raise self._error(
                "invalid_request",
                f"unsupported subscription field: {sorted(unknown)[0]}",
            )
        result: dict[str, Any] = {}
        for field, value in values.items():
            if field == "enabled":
                result[field] = self._strict_bool(value, field)
            elif field == "override_channel":
                result[field] = self._strict_string_or_none(value, field)
            elif field in {"override_topics", "personal_tags"}:
                result[field] = self._string_list(value, field)
            elif field == "analysis_mode":
                if value not in {"full", "personal_only"}:
                    raise self._error(
                        "invalid_request",
                        "analysis_mode must be full or personal_only",
                    )
                result[field] = value
            elif field == "priority":
                if isinstance(value, bool) or not isinstance(value, int) or not 0 <= value <= 100:
                    raise self._error(
                        "invalid_request",
                        "priority must be an integer between 0 and 100",
                    )
                result[field] = value
        if create:
            return {
                "enabled": True,
                "override_channel": None,
                "override_topics": [],
                "personal_tags": [],
                "analysis_mode": "full",
                "priority": 0,
                **result,
            }
        return result

    def _normalize_schedule(
        self, values: dict[str, Any] | None
    ) -> dict[str, Any] | None:
        if values is None:
            return None
        if not isinstance(values, dict):
            raise self._error("invalid_source_schedule", "schedule must be an object")
        unknown = set(values) - _SCHEDULE_FIELDS
        if unknown:
            raise self._error(
                "invalid_source_schedule",
                f"unsupported schedule field: {sorted(unknown)[0]}",
            )
        result: dict[str, Any] = {}
        if "enabled" in values:
            try:
                result["enabled"] = self._strict_bool(values["enabled"], "enabled")
            except SubscriptionMutationError as exc:
                raise self._error("invalid_source_schedule", str(exc)) from exc
        if "interval_minutes" in values:
            interval = values["interval_minutes"]
            if (
                isinstance(interval, bool)
                or not isinstance(interval, int)
                or interval not in SOURCE_ALLOWED_INTERVALS
            ):
                raise self._error(
                    "invalid_source_schedule",
                    "interval_minutes must be one of "
                    + ", ".join(str(item) for item in SOURCE_ALLOWED_INTERVALS),
                )
            result["interval_minutes"] = interval
        return result

    def _reject_agent_sensitive_metadata(self, values: dict[str, Any]) -> None:
        """Reuse Task 1 credential classification for non-config source fields."""

        try:
            validate_public_source_metadata(values)
        except SourceConfigError as exc:
            if str(exc) == "credentials are not accepted; configure secrets in Web":
                raise self._error("invalid_source_config", str(exc)) from exc

    @staticmethod
    def _visible(source: dict[str, Any], actor: SubscriptionActor) -> bool:
        return bool(
            source.get("workspace_id") == actor.workspace_id
            and source.get("enabled")
            and (
                source.get("scope") in {"public", "workspace"}
                or (
                    source.get("scope") == "private"
                    and source.get("owner_user_id") == actor.user_id
                )
            )
        )

    def _subscription_context(
        self, actor: SubscriptionActor, subscription_id: str
    ) -> tuple[dict[str, Any], dict[str, Any], dict[str, Any] | None]:
        subscription = self.store.get_subscription(subscription_id)
        if subscription is None or subscription.get("user_id") != actor.user_id:
            raise self._error(
                "not_found", "subscription not found", status_code=404
            )
        source = self.store.get_source(str(subscription["source_id"]))
        if source is None or source.get("workspace_id") != actor.workspace_id:
            raise self._error(
                "not_found", "subscription not found", status_code=404
            )
        return subscription, source, self.store.get_source_schedule(subscription_id)

    @staticmethod
    def _fingerprints(
        source: dict[str, Any] | None,
        subscription: dict[str, Any] | None,
        schedule: dict[str, Any] | None,
    ) -> dict[str, str | None]:
        return {
            "source": str(source["updated_at"]) if source is not None else None,
            "subscription": (
                str(subscription["updated_at"])
                if subscription is not None
                else None
            ),
            "schedule": str(schedule["updated_at"]) if schedule is not None else None,
        }

    @staticmethod
    def _public_target(source_type: str, config: dict[str, Any]) -> Any:
        if source_type == "rss":
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
            return {
                key: config.get(key) for key in ("platform", "kind", "target")
            }
        if source_type == "hackernews":
            return {
                key: config.get(key)
                for key in ("fetch_top_stories", "min_score")
            }
        return None

    @staticmethod
    def _require_exact_keys(
        value: Any,
        expected: set[str],
        field: str,
    ) -> dict[str, Any]:
        if not isinstance(value, dict) or set(value) != expected:
            raise ValueError(f"{field} has an invalid schema")
        return value

    @staticmethod
    def _require_identifier(value: Any, field: str) -> str:
        if not isinstance(value, str) or not value:
            raise ValueError(f"{field} must be a non-empty string")
        return value

    def _validate_fingerprints(
        self, value: Any
    ) -> dict[str, str | None]:
        fingerprints = self._require_exact_keys(
            value, {"source", "subscription", "schedule"}, "fingerprints"
        )
        if any(
            item is not None and (not isinstance(item, str) or not item)
            for item in fingerprints.values()
        ):
            raise ValueError("fingerprints contain an invalid value")
        return fingerprints

    def _validate_public_summary(self, value: Any) -> dict[str, Any]:
        summary = self._require_exact_keys(
            value, {"display_name", "type", "public_target"}, "source summary"
        )
        display_name = summary["display_name"]
        source_type = summary["type"]
        target = summary["public_target"]
        if not isinstance(display_name, str) or not display_name:
            raise ValueError("source summary display_name is invalid")
        if source_type not in _CATALOG_SOURCE_TYPES | {"unknown"}:
            raise ValueError("source summary type is invalid")
        if target == "web_setup_required":
            if display_name != "Web-managed source":
                raise ValueError("opaque source summary is invalid")
        elif source_type in {
            "rss",
            "github_release",
            "github_user",
            "reddit_subreddit",
            "reddit_user",
            "telegram_channel",
        }:
            if not isinstance(target, str) or not target:
                raise ValueError("source summary target is invalid")
        elif source_type == "apify_social":
            target_values = self._require_exact_keys(
                target, {"platform", "kind", "target"}, "social target"
            )
            if any(not isinstance(item, str) or not item for item in target_values.values()):
                raise ValueError("social target is invalid")
        elif source_type == "hackernews":
            target_values = self._require_exact_keys(
                target,
                {"fetch_top_stories", "min_score"},
                "hackernews target",
            )
            if any(isinstance(item, bool) or not isinstance(item, int) for item in target_values.values()):
                raise ValueError("hackernews target is invalid")
        else:
            raise ValueError("unknown source summary must be opaque")
        self._reject_agent_sensitive_metadata(summary)
        return summary

    def _validate_schedule_preview(self, value: Any) -> dict[str, Any]:
        preview = self._require_exact_keys(
            value, {"enabled", "interval_minutes"}, "schedule preview"
        )
        if not isinstance(preview["enabled"], bool):
            raise ValueError("schedule preview enabled is invalid")
        interval = preview["interval_minutes"]
        if (
            isinstance(interval, bool)
            or not isinstance(interval, int)
            or interval not in SOURCE_ALLOWED_INTERVALS
        ):
            raise ValueError("schedule preview interval is invalid")
        return preview

    @staticmethod
    def _final_schedule_preview(
        existing_schedule: dict[str, Any] | None,
        updates: dict[str, Any] | None,
    ) -> dict[str, Any]:
        result = {
            "enabled": bool(existing_schedule and existing_schedule.get("enabled")),
            "interval_minutes": int(
                (existing_schedule or {}).get(
                    "interval_minutes", DEFAULT_SOURCE_INTERVAL_MINUTES
                )
            ),
        }
        if updates:
            result.update(updates)
        return result

    def _validate_source_updates_snapshot(
        self,
        source_type: str,
        value: Any,
    ) -> dict[str, Any] | None:
        if value is None:
            return None
        if not isinstance(value, dict):
            raise ValueError("source updates must be an object or null")
        allowed = _SOURCE_UPDATE_FIELDS | {"source_key", "enforce_public_network"}
        if set(value) - allowed:
            raise ValueError("source updates contain an unsupported field")
        for field, item in value.items():
            if field in {"display_name", "description"}:
                if not isinstance(item, str) or (
                    field == "display_name" and not item.strip()
                ):
                    raise ValueError("source metadata is invalid")
            elif field == "default_channel":
                if item is not None and not isinstance(item, str):
                    raise ValueError("source default channel is invalid")
            elif field == "default_topics":
                if not isinstance(item, list) or any(
                    not isinstance(topic, str) for topic in item
                ):
                    raise ValueError("source default topics are invalid")
            elif field == "enabled" and not isinstance(item, bool):
                raise ValueError("source enabled is invalid")
        has_config = "config" in value
        if has_config:
            config = value["config"]
            if not isinstance(config, dict):
                raise ValueError("source config is invalid")
            normalized = (
                validate_normalized_source_setup("rss", "rss", config)["config"]
                if source_type == "rss"
                else validate_source_config(source_type, config)
            )
            if normalized != config or value.get("source_key") != source_key(
                source_type, config
            ):
                raise ValueError("source config identity is invalid")
            if source_type == "rss":
                if value.get("enforce_public_network") is not True:
                    raise ValueError("RSS public network marker is invalid")
            elif "enforce_public_network" in value:
                raise ValueError("unexpected public network marker")
        elif "source_key" in value or "enforce_public_network" in value:
            raise ValueError("source identity fields require config")
        self._reject_agent_sensitive_metadata(value)
        return value

    def _expected_preview(
        self,
        kind: Literal["create", "update", "delete"],
        payload: dict[str, Any],
    ) -> dict[str, Any]:
        if kind == "create":
            source_values = payload["source"]
            if source_values["mode"] == "private":
                preview_source = {
                    "display_name": source_values["display_name"],
                    "type": source_values["agent_type"],
                    "public_target": self._public_target(
                        source_values["catalog_source_type"],
                        source_values["config"],
                    ),
                }
            else:
                preview_source = source_values["public_summary"]
            return {
                "action": "create_subscription",
                "source": preview_source,
                "subscription": payload["subscription"],
                "schedule": payload["schedule_preview"],
                "impact": "Create or enable the caller's subscription.",
                "warnings": [],
            }
        if kind == "update":
            return {
                "action": "update_subscription",
                "source": payload["preview_source"],
                "subscription": payload["subscription_updates"] or {},
                "schedule": payload["schedule_updates"] or {},
                "impact": "Update the selected private source or subscription.",
                "warnings": [],
            }
        disposition = payload["source_disposition"]
        return {
            "action": "delete_subscription",
            "source": payload["preview_source"],
            "subscription": {"id": payload["subscription_id"]},
            "schedule": {},
            "source_disposition": disposition,
            "impact": "Delete the caller's subscription.",
            "warnings": (
                ["The private source will also be disabled."]
                if disposition == "disable_private"
                else []
            ),
        }

    def _validate_plan_parts(
        self,
        kind: Literal["create", "update", "delete"],
        payload: Any,
        preview: Any,
        target_ids: Any,
        fingerprints: Any,
    ) -> None:
        targets = target_ids
        fingerprints = self._validate_fingerprints(fingerprints)
        if kind == "create":
            normalized = self._require_exact_keys(
                payload,
                {"source", "subscription", "schedule", "schedule_preview"},
                "create plan",
            )
            source_values = normalized["source"]
            if not isinstance(source_values, dict):
                raise ValueError("source plan is invalid")
            if source_values.get("mode") == "private":
                self._require_exact_keys(
                    source_values,
                    {
                        "mode",
                        "agent_type",
                        "catalog_source_type",
                        "display_name",
                        "description",
                        "default_channel",
                        "default_topics",
                        "config",
                        "source_key",
                        "enforce_public_network",
                    },
                    "private source plan",
                )
                if not isinstance(source_values["display_name"], str) or not source_values[
                    "display_name"
                ].strip():
                    raise ValueError("private source display name is invalid")
                if not isinstance(source_values["description"], str):
                    raise ValueError("private source description is invalid")
                if source_values["default_channel"] is not None and not isinstance(
                    source_values["default_channel"], str
                ):
                    raise ValueError("private source channel is invalid")
                if not isinstance(source_values["default_topics"], list) or any(
                    not isinstance(item, str)
                    for item in source_values["default_topics"]
                ):
                    raise ValueError("private source topics are invalid")
                setup = validate_normalized_source_setup(
                    source_values["agent_type"],
                    source_values["catalog_source_type"],
                    source_values["config"],
                )
                policy = setup["policy"]
                if (
                    policy.get("resolution_mode") != "create_or_existing"
                    or policy.get("self_service") is not True
                    or source_values["catalog_source_type"] == "apify_social"
                    or source_values["enforce_public_network"]
                    is not bool(policy.get("public_network_only", False))
                    or source_values["source_key"]
                    != source_key(
                        source_values["catalog_source_type"], source_values["config"]
                    )
                ):
                    raise ValueError("private source policy is invalid")
                self._reject_agent_sensitive_metadata(
                    {
                        key: source_values[key]
                        for key in (
                            "display_name",
                            "description",
                            "default_channel",
                            "default_topics",
                        )
                    }
                )
                if targets != {} or any(
                    fingerprints[key] is not None
                    for key in ("source", "subscription", "schedule")
                ):
                    raise ValueError("private create targets are invalid")
            elif source_values.get("mode") == "existing":
                self._require_exact_keys(
                    source_values,
                    {"mode", "source_id", "public_summary"},
                    "existing source plan",
                )
                source_id = self._require_identifier(
                    source_values["source_id"], "source_id"
                )
                self._validate_public_summary(source_values["public_summary"])
                if not isinstance(targets, dict) or set(targets) not in (
                    {"source_id"},
                    {"source_id", "subscription_id"},
                ):
                    raise ValueError("existing create targets are invalid")
                if targets["source_id"] != source_id:
                    raise ValueError("existing create source target is invalid")
                if fingerprints["source"] is None:
                    raise ValueError("existing create source fingerprint is invalid")
                if "subscription_id" in targets:
                    self._require_identifier(
                        targets["subscription_id"], "subscription_id"
                    )
                    if fingerprints["subscription"] is None:
                        raise ValueError("subscription fingerprint is invalid")
                elif fingerprints["subscription"] is not None or fingerprints[
                    "schedule"
                ] is not None:
                    raise ValueError("missing subscription target is invalid")
            else:
                raise ValueError("source mode is invalid")
            subscription = self._normalize_subscription(
                normalized["subscription"], create=True
            )
            if subscription != normalized["subscription"]:
                raise ValueError("subscription snapshot is not normalized")
            schedule = self._normalize_schedule(normalized["schedule"])
            if schedule != normalized["schedule"]:
                raise ValueError("schedule snapshot is not normalized")
            schedule_preview = self._validate_schedule_preview(
                normalized["schedule_preview"]
            )
            if (
                source_values["mode"] == "private"
                or "subscription_id" not in targets
            ) and schedule_preview != self._final_schedule_preview(None, schedule):
                raise ValueError("schedule preview does not match final schedule")
        elif kind == "update":
            normalized = self._require_exact_keys(
                payload,
                {
                    "subscription_id",
                    "catalog_source_type",
                    "source_updates",
                    "subscription_updates",
                    "schedule_updates",
                    "preview_source",
                },
                "update plan",
            )
            self._require_identifier(normalized["subscription_id"], "subscription_id")
            source_type = normalized["catalog_source_type"]
            if source_type not in _CATALOG_SOURCE_TYPES:
                raise ValueError("catalog source type is invalid")
            self._validate_source_updates_snapshot(
                source_type, normalized["source_updates"]
            )
            if normalized["subscription_updates"] is not None:
                subscription_updates = self._normalize_subscription(
                    normalized["subscription_updates"], create=False
                )
                if subscription_updates != normalized["subscription_updates"]:
                    raise ValueError("subscription updates are not normalized")
            schedule_updates = self._normalize_schedule(
                normalized["schedule_updates"]
            )
            if schedule_updates != normalized["schedule_updates"]:
                raise ValueError("schedule updates are not normalized")
            self._validate_public_summary(normalized["preview_source"])
            if all(
                normalized[key] is None
                for key in (
                    "source_updates",
                    "subscription_updates",
                    "schedule_updates",
                )
            ):
                raise ValueError("update plan has no updates")
            if not isinstance(targets, dict) or set(targets) != {
                "source_id",
                "subscription_id",
            }:
                raise ValueError("update targets are invalid")
            if targets["subscription_id"] != normalized["subscription_id"]:
                raise ValueError("update subscription target is invalid")
            self._require_identifier(targets["source_id"], "source_id")
            if fingerprints["source"] is None or fingerprints["subscription"] is None:
                raise ValueError("update fingerprints are invalid")
        else:
            normalized = self._require_exact_keys(
                payload,
                {"subscription_id", "source_disposition", "preview_source"},
                "delete plan",
            )
            self._require_identifier(normalized["subscription_id"], "subscription_id")
            if normalized["source_disposition"] not in {"keep", "disable_private"}:
                raise ValueError("source disposition is invalid")
            self._validate_public_summary(normalized["preview_source"])
            if not isinstance(targets, dict) or set(targets) != {
                "source_id",
                "subscription_id",
            }:
                raise ValueError("delete targets are invalid")
            if targets["subscription_id"] != normalized["subscription_id"]:
                raise ValueError("delete subscription target is invalid")
            self._require_identifier(targets["source_id"], "source_id")
            if fingerprints["source"] is None or fingerprints["subscription"] is None:
                raise ValueError("delete fingerprints are invalid")
        if preview != self._expected_preview(kind, payload):
            raise ValueError("preview does not match normalized plan")

    def _build_plan(
        self,
        kind: Literal["create", "update", "delete"],
        payload: dict[str, Any],
        preview: dict[str, Any],
        target_ids: dict[str, str],
        fingerprints: dict[str, str | None],
    ) -> SubscriptionChangePlan:
        self._validate_plan_parts(
            kind, payload, preview, target_ids, fingerprints
        )
        return SubscriptionChangePlan._from_validated_snapshot(
            kind, payload, preview, target_ids, fingerprints
        )

    def restore_plan_snapshot(self, snapshot: dict[str, Any]) -> SubscriptionChangePlan:
        """Restore only an exact, versioned, normalized plan snapshot."""

        try:
            data = self._require_exact_keys(
                snapshot, _PLAN_SNAPSHOT_KEYS, "plan snapshot"
            )
            version = data["version"]
            if (
                isinstance(version, bool)
                or not isinstance(version, int)
                or version != _PLAN_SNAPSHOT_VERSION
            ):
                raise ValueError("unsupported plan snapshot version")
            kind = data["kind"]
            if kind not in {"create", "update", "delete"}:
                raise ValueError("invalid plan snapshot kind")
            self._validate_plan_parts(
                kind,
                data["normalized"],
                data["preview"],
                data["targets"],
                data["fingerprints"],
            )
            return SubscriptionChangePlan._from_validated_snapshot(
                kind,
                data["normalized"],
                data["preview"],
                data["targets"],
                data["fingerprints"],
            )
        except (KeyError, TypeError, ValueError, SourceConfigError, SubscriptionMutationError) as exc:
            raise self._error(
                "invalid_plan_snapshot", "invalid subscription change plan snapshot"
            ) from exc

    def plan_create(
        self,
        actor: SubscriptionActor,
        *,
        source: dict[str, Any],
        subscription: dict[str, Any] | None,
        schedule: dict[str, Any] | None,
    ) -> SubscriptionChangePlan:
        self._live_actor(actor)
        if not isinstance(source, dict):
            raise self._error("invalid_request", "source must be an object")
        mode = source.get("mode")
        normalized_subscription = self._normalize_subscription(subscription, create=True)
        normalized_schedule = self._normalize_schedule(schedule)
        target_source: dict[str, Any] | None = None
        existing_subscription: dict[str, Any] | None = None
        existing_schedule: dict[str, Any] | None = None

        if mode == "existing":
            if set(source) != {"mode", "source_id"}:
                raise self._error(
                    "invalid_request", "existing source requires only source_id"
                )
            target_source = self.store.get_source(str(source.get("source_id") or ""))
            if target_source is None or not self._visible(target_source, actor):
                raise self._error("not_found", "source not found", status_code=404)
            existing_subscription = self.store.get_user_subscription_for_source(
                actor.user_id, str(target_source["id"])
            )
            if existing_subscription is not None:
                existing_schedule = self.store.get_source_schedule(
                    str(existing_subscription["id"])
                )
            safe_summary = project_catalog_source_public_summary(target_source)
            normalized_source = {
                "mode": "existing",
                "source_id": str(target_source["id"]),
                "public_summary": safe_summary,
            }
            preview_type = str(safe_summary["type"])
            public_target = safe_summary["public_target"]
            display_name = str(safe_summary["display_name"])
        elif mode == "private":
            allowed = {
                "mode",
                "type",
                "display_name",
                "description",
                "default_channel",
                "default_topics",
                "config",
            }
            unknown = set(source) - allowed
            if unknown:
                raise self._error(
                    "invalid_request", f"unsupported source field: {sorted(unknown)[0]}"
                )
            agent_type = str(source.get("type") or "")
            raw_display_name = source.get("display_name")
            if not isinstance(raw_display_name, str):
                raise self._error("invalid_request", "display_name must be a string")
            display_name = raw_display_name.strip()
            if not display_name:
                raise self._error("invalid_request", "display_name is required")
            raw_description = source.get("description", "")
            if not isinstance(raw_description, str):
                raise self._error("invalid_request", "description must be a string")
            default_channel = source.get("default_channel")
            self._strict_string_or_none(default_channel, "default_channel")
            default_topics = self._string_list(
                source.get("default_topics", []), "default_topics"
            )
            self._reject_agent_sensitive_metadata(
                {
                    "display_name": display_name,
                    "description": raw_description,
                    "default_channel": default_channel,
                    "default_topics": default_topics,
                }
            )
            try:
                setup = normalize_source_setup_input(
                    agent_type, source.get("config") or {}
                )
            except SourceConfigError as exc:
                code = (
                    "source_requires_web_setup"
                    if str(exc) == "source_requires_web_setup"
                    else "invalid_source_config"
                )
                raise self._error(code, str(exc)) from exc
            policy = setup.get("policy") or {}
            if (
                policy.get("resolution_mode") != "create_or_existing"
                or policy.get("self_service") is not True
                or "catalog_source_type" not in setup
                or "config" not in setup
            ):
                raise self._error(
                    "source_requires_web_setup", "source_requires_web_setup"
                )
            catalog_type = str(setup["catalog_source_type"])
            if catalog_type == "apify_social":
                raise self._error(
                    "source_requires_web_setup", "source_requires_web_setup"
                )
            config = dict(setup["config"])
            key = source_key(catalog_type, config)
            if self.store.get_source_by_key(
                workspace_id=actor.workspace_id, source_key=key
            ) is not None:
                raise self._error(
                    "source_key_conflict",
                    "source_key already belongs to another catalog source",
                    status_code=409,
                    action="Use the existing visible source or choose a different source configuration.",
                )
            normalized_source = {
                "mode": "private",
                "agent_type": agent_type,
                "catalog_source_type": catalog_type,
                "display_name": display_name,
                "description": raw_description,
                "default_channel": default_channel,
                "default_topics": default_topics,
                "config": config,
                "source_key": key,
                "enforce_public_network": bool(
                    policy.get("public_network_only", False)
                ),
            }
            preview_type = agent_type
            public_target = self._public_target(catalog_type, config)
        else:
            raise self._error(
                "invalid_request", "source mode must be existing or private"
            )

        schedule_preview = self._final_schedule_preview(
            existing_schedule if existing_subscription is not None else None,
            normalized_schedule,
        )
        payload = {
            "source": normalized_source,
            "subscription": normalized_subscription,
            "schedule": normalized_schedule,
            "schedule_preview": schedule_preview,
        }
        preview = {
            "action": "create_subscription",
            "source": {
                "display_name": display_name,
                "type": preview_type,
                "public_target": public_target,
            },
            "subscription": dict(normalized_subscription),
            "schedule": dict(schedule_preview),
            "impact": "Create or enable the caller's subscription.",
            "warnings": [],
        }
        target_ids = {}
        if target_source is not None:
            target_ids["source_id"] = str(target_source["id"])
        if existing_subscription is not None:
            target_ids["subscription_id"] = str(existing_subscription["id"])
        return self._build_plan(
            "create",
            payload,
            preview,
            target_ids,
            self._fingerprints(
                target_source, existing_subscription, existing_schedule
            ),
        )

    def plan_update(
        self,
        actor: SubscriptionActor,
        *,
        subscription_id: str,
        source_updates: dict[str, Any] | None,
        subscription_updates: dict[str, Any] | None,
        schedule_updates: dict[str, Any] | None,
    ) -> SubscriptionChangePlan:
        self._live_actor(actor)
        subscription, source, schedule = self._subscription_context(
            actor, subscription_id
        )
        if all(
            values is None
            for values in (source_updates, subscription_updates, schedule_updates)
        ):
            raise self._error("invalid_request", "at least one update is required")

        normalized_source_updates: dict[str, Any] | None = None
        if source_updates is not None:
            if not isinstance(source_updates, dict):
                raise self._error("invalid_request", "source_updates must be an object")
            unknown = set(source_updates) - _SOURCE_UPDATE_FIELDS
            if unknown:
                raise self._error(
                    "invalid_request", f"unsupported source field: {sorted(unknown)[0]}"
                )
            if (
                source.get("scope") != "private"
                or source.get("owner_user_id") != actor.user_id
            ):
                raise self._error(
                    "forbidden",
                    "Agent changes cannot modify shared sources",
                    status_code=403,
                )
            normalized_source_updates = {}
            for field, value in source_updates.items():
                if field in {"display_name", "description"}:
                    if not isinstance(value, str):
                        raise self._error(
                            "invalid_request", f"{field} must be a string"
                        )
                    if field == "display_name" and not value.strip():
                        raise self._error(
                            "invalid_request", "display_name is required"
                        )
                    normalized_source_updates[field] = value
                elif field == "default_channel":
                    normalized_source_updates[field] = self._strict_string_or_none(
                        value, field
                    )
                elif field == "default_topics":
                    normalized_source_updates[field] = self._string_list(value, field)
                elif field == "enabled":
                    normalized_source_updates[field] = self._strict_bool(value, field)
                elif field == "config":
                    if not isinstance(value, dict):
                        raise self._error(
                            "invalid_source_config", "config must be an object"
                        )
                    try:
                        if source["type"] == "rss":
                            setup = normalize_source_setup_input("rss", value)
                            policy = setup.get("policy") or {}
                            if (
                                setup.get("catalog_source_type") != "rss"
                                or policy.get("public_network_only") is not True
                            ):
                                raise SourceConfigError("source_requires_web_setup")
                            config = dict(setup["config"])
                            normalized_source_updates[
                                "enforce_public_network"
                            ] = True
                        else:
                            config = validate_source_config(
                                str(source["type"]), value
                            )
                        key = source_key(str(source["type"]), config)
                    except SourceConfigError as exc:
                        raise self._error(
                            "invalid_source_config", str(exc)
                        ) from exc
                    normalized_source_updates["config"] = config
                    normalized_source_updates["source_key"] = key
            self._reject_agent_sensitive_metadata(dict(source_updates))
        normalized_subscription_updates = (
            None
            if subscription_updates is None
            else self._normalize_subscription(subscription_updates, create=False)
        )
        normalized_schedule_updates = self._normalize_schedule(schedule_updates)
        preview_source_values = dict(source)
        if normalized_source_updates is not None:
            preview_source_values.update(normalized_source_updates)
        preview_source = project_catalog_source_public_summary(
            preview_source_values
        )
        payload = {
            "subscription_id": str(subscription_id),
            "catalog_source_type": str(source["type"]),
            "source_updates": normalized_source_updates,
            "subscription_updates": normalized_subscription_updates,
            "schedule_updates": normalized_schedule_updates,
            "preview_source": preview_source,
        }
        return self._build_plan(
            "update",
            payload,
            {
                "action": "update_subscription",
                "source": preview_source,
                "subscription": dict(normalized_subscription_updates or {}),
                "schedule": dict(normalized_schedule_updates or {}),
                "impact": "Update the selected private source or subscription.",
                "warnings": [],
            },
            {
                "source_id": str(source["id"]),
                "subscription_id": str(subscription["id"]),
            },
            self._fingerprints(source, subscription, schedule),
        )

    def plan_delete(
        self,
        actor: SubscriptionActor,
        *,
        subscription_id: str,
        source_disposition: Any = _MISSING,
    ) -> SubscriptionChangePlan:
        self._live_actor(actor)
        subscription, source, schedule = self._subscription_context(
            actor, subscription_id
        )
        if source_disposition is _MISSING:
            raise self._error("invalid_request", "source_disposition is required")
        if source_disposition not in {"keep", "disable_private"}:
            raise self._error(
                "invalid_request",
                "source_disposition must be keep or disable_private",
            )
        if source_disposition == "disable_private" and (
            source.get("scope") != "private"
            or source.get("owner_user_id") != actor.user_id
        ):
            raise self._error(
                "forbidden",
                "disable_private requires the caller's private source",
                status_code=403,
            )
        preview_source = project_catalog_source_public_summary(source)
        return self._build_plan(
            "delete",
            {
                "subscription_id": str(subscription_id),
                "source_disposition": source_disposition,
                "preview_source": preview_source,
            },
            {
                "action": "delete_subscription",
                "source": preview_source,
                "subscription": {"id": str(subscription_id)},
                "schedule": {},
                "source_disposition": source_disposition,
                "impact": "Delete the caller's subscription.",
                "warnings": (
                    ["The private source will also be disabled."]
                    if source_disposition == "disable_private"
                    else []
                ),
            },
            {
                "source_id": str(source["id"]),
                "subscription_id": str(subscription["id"]),
            },
            self._fingerprints(source, subscription, schedule),
        )

    def _revalidate_live_plan(
        self, actor: SubscriptionActor, plan: SubscriptionChangePlan
    ) -> None:
        if (
            not isinstance(plan, SubscriptionChangePlan)
            or plan._factory_token is not _PLAN_FACTORY_TOKEN
        ):
            raise self._error("invalid_request", "invalid subscription change plan")
        try:
            self._validate_plan_parts(
                plan.kind,
                plan.payload,
                plan.preview,
                plan.target_ids,
                plan.fingerprints,
            )
        except (
            KeyError,
            TypeError,
            ValueError,
            SourceConfigError,
            SubscriptionMutationError,
        ) as exc:
            raise self._error(
                "invalid_plan_snapshot", "invalid subscription change plan snapshot"
            ) from exc
        self._live_actor(actor)
        payload = plan.payload
        expected_target_ids: dict[str, str] = {}
        live_context_valid = True
        if plan.kind == "create":
            source_values = payload.get("source")
            if not isinstance(source_values, dict):
                raise self._error("invalid_request", "invalid sealed source plan")
            if source_values.get("mode") == "existing":
                source = self.store.get_source(
                    str(source_values.get("source_id") or "")
                )
                if source is None or not self._visible(source, actor):
                    raise self._error("not_found", "source not found", status_code=404)
                subscription = self.store.get_user_subscription_for_source(
                    actor.user_id, str(source["id"])
                )
                schedule = (
                    self.store.get_source_schedule(str(subscription["id"]))
                    if subscription is not None
                    else None
                )
                expected_target_ids["source_id"] = str(source["id"])
                if subscription is not None:
                    expected_target_ids["subscription_id"] = str(subscription["id"])
                live_context_valid = bool(
                    source_values["public_summary"]
                    == project_catalog_source_public_summary(source)
                    and payload["schedule_preview"]
                    == self._final_schedule_preview(schedule, payload.get("schedule"))
                )
            elif source_values.get("mode") == "private":
                source = None
                subscription = None
                schedule = None
                existing = self.store.get_source_by_key(
                    workspace_id=actor.workspace_id,
                    source_key=str(source_values.get("source_key") or ""),
                )
                if existing is not None:
                    raise self._error(
                        "source_key_conflict",
                        "source_key already belongs to another catalog source",
                        status_code=409,
                        action="Use the existing visible source or choose a different source configuration.",
                    )
            else:
                raise self._error("invalid_request", "invalid sealed source mode")
        elif plan.kind in {"update", "delete"}:
            subscription, source, schedule = self._subscription_context(
                actor, str(payload.get("subscription_id") or "")
            )
            expected_target_ids = {
                "source_id": str(source["id"]),
                "subscription_id": str(subscription["id"]),
            }
            if payload.get("source_updates") is not None and (
                source.get("scope") != "private"
                or source.get("owner_user_id") != actor.user_id
            ):
                raise self._error(
                    "forbidden",
                    "Agent changes cannot modify shared sources",
                    status_code=403,
                )
            if payload.get("source_disposition") == "disable_private" and (
                source.get("scope") != "private"
                or source.get("owner_user_id") != actor.user_id
            ):
                raise self._error(
                    "forbidden",
                    "disable_private requires the caller's private source",
                    status_code=403,
                )
            if plan.kind == "update":
                preview_source_values = dict(source)
                if payload.get("source_updates") is not None:
                    preview_source_values.update(payload["source_updates"])
                live_context_valid = bool(
                    payload.get("catalog_source_type") == source.get("type")
                    and payload.get("preview_source")
                    == project_catalog_source_public_summary(preview_source_values)
                )
            else:
                live_context_valid = bool(
                    payload.get("preview_source")
                    == project_catalog_source_public_summary(source)
                )
        else:  # pragma: no cover - constructor rejects this state
            raise self._error("invalid_request", "invalid subscription change kind")

        if expected_target_ids != plan.target_ids or self._fingerprints(
            source, subscription, schedule
        ) != plan.fingerprints:
            raise self._error(
                "proposal_stale", "proposal targets changed", status_code=409
            )
        if not live_context_valid:
            raise self._error(
                "invalid_plan_snapshot", "invalid subscription change plan snapshot"
            )

    def apply_plan(
        self,
        actor: SubscriptionActor,
        plan: SubscriptionChangePlan,
        *,
        commit: bool = True,
        post_commit_cleanup: PostCommitMediaCleanup | None = None,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        if (not owns_transaction or not commit) and post_commit_cleanup is None:
            raise self._error(
                "post_commit_cleanup_required",
                "post_commit_cleanup is required for a caller-owned transaction",
                status_code=500,
            )
        cleanup = post_commit_cleanup or PostCommitMediaCleanup()
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            self._revalidate_live_plan(actor, plan)
            result = self._apply_normalized(actor, plan, cleanup=cleanup)
            if owns_transaction and commit:
                conn.commit()
                cleanup.run()
            return result
        except QuotaExceeded as exc:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
                cleanup.discard()
            raise self._error(
                exc.code, str(exc), status_code=429,
                action="Reduce enabled sources or increase the workspace quota.",
            ) from exc
        except SourceKeyConflictError as exc:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
                cleanup.discard()
            raise self._error(
                "source_key_conflict",
                str(exc),
                status_code=409,
                action="Use the existing visible source or choose a different source configuration.",
            ) from exc
        except SourceScheduleUnavailableError as exc:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
                cleanup.discard()
            raise self._error(
                exc.code,
                str(exc),
                status_code=409,
                action="Enable the subscription and source before enabling its schedule.",
            ) from exc
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
                cleanup.discard()
            raise

    def _apply_normalized(
        self,
        actor: SubscriptionActor,
        plan: SubscriptionChangePlan,
        *,
        cleanup: PostCommitMediaCleanup,
    ) -> dict[str, Any]:
        if plan.kind == "create":
            source_values = plan.payload["source"]
            if source_values["mode"] == "private":
                source_id = self.store.create_source(
                    workspace_id=actor.workspace_id,
                    scope="private",
                    owner_user_id=actor.user_id,
                    source_type=source_values["catalog_source_type"],
                    display_name=source_values["display_name"],
                    description=source_values["description"],
                    default_channel=source_values["default_channel"],
                    default_topics=source_values["default_topics"],
                    config=source_values["config"],
                    source_key=source_values["source_key"],
                    secret_env=None,
                    enforce_public_network=source_values[
                        "enforce_public_network"
                    ],
                    enabled=True,
                    commit=False,
                )
            else:
                source_id = source_values["source_id"]
            subscription_values = dict(plan.payload["subscription"])
            if subscription_values.get("enabled", True):
                self.quota.ensure_source_allowed(
                    workspace_id=actor.workspace_id,
                    user_id=actor.user_id,
                    source_id=source_id,
                )
            subscription = self.store.create_subscription(
                user_id=actor.user_id,
                source_id=source_id,
                commit=False,
                **subscription_values,
            )
            schedule = self._apply_schedule(
                actor, subscription, plan.payload.get("schedule")
            )
            source = self.store.get_source(source_id)
            if source is None:
                raise LookupError("created source not found")
            return {
                "action": "created",
                "source": source,
                "subscription": subscription,
                "schedule": schedule,
            }

        subscription, source, _schedule = self._subscription_context(
            actor, plan.payload["subscription_id"]
        )
        if plan.kind == "update":
            source_updates = plan.payload.get("source_updates")
            subscription_updates = plan.payload.get("subscription_updates")
            source_will_enable = bool(
                source_updates is not None
                and source_updates.get("enabled") is True
                and not source.get("enabled")
            )
            subscription_will_be_enabled = bool(
                subscription_updates.get("enabled", subscription.get("enabled"))
                if subscription_updates is not None
                else subscription.get("enabled")
            )
            if source_will_enable and subscription_will_be_enabled:
                self.quota.ensure_source_reenable_allowed(
                    workspace_id=actor.workspace_id,
                    user_id=actor.user_id,
                    source_id=str(source["id"]),
                )
            if source_updates is not None:
                source = self._update_source_locked(
                    source, source_updates, cleanup=cleanup
                )
            if subscription_updates is not None:
                if subscription_updates.get("enabled") is True:
                    self.quota.ensure_source_allowed(
                        workspace_id=actor.workspace_id,
                        user_id=actor.user_id,
                        source_id=str(source["id"]),
                    )
                subscription = self.store.update_subscription(
                    str(subscription["id"]),
                    commit=False,
                    **subscription_updates,
                )
            schedule = self._apply_schedule(
                actor, subscription, plan.payload.get("schedule_updates")
            )
            return {
                "action": "updated",
                "source": source,
                "subscription": subscription,
                "schedule": schedule,
            }

        source_id = str(source["id"])
        deleted = self.store.delete_subscription(
            str(subscription["id"]), user_id=actor.user_id
        )
        if not deleted:
            raise self._error(
                "not_found", "subscription not found", status_code=404
            )
        source_disabled = False
        if plan.payload["source_disposition"] == "disable_private":
            remaining = self.store.connect().execute(
                "SELECT 1 FROM user_subscriptions WHERE source_id = ? LIMIT 1",
                (source_id,),
            ).fetchone()
            if remaining is not None:
                raise self._error(
                    "forbidden",
                    "private source is still subscribed",
                    status_code=403,
                )
            self.store.update_source(source_id, enabled=False, commit=False)
            source_disabled = True
        return {
            "action": "deleted",
            "deleted": True,
            "subscription_id": str(subscription["id"]),
            "source_id": source_id,
            "source_disabled": source_disabled,
        }

    def _apply_schedule(
        self,
        actor: SubscriptionActor,
        subscription: dict[str, Any],
        updates: dict[str, Any] | None,
    ) -> dict[str, Any]:
        if updates is not None:
            return self.source_schedules.update_subscription_schedule(
                workspace_id=actor.workspace_id,
                user_id=actor.user_id,
                subscription_id=str(subscription["id"]),
                **updates,
            )
        return self.source_schedules.get_subscription_schedule(
            workspace_id=actor.workspace_id,
            user_id=actor.user_id,
            subscription_id=str(subscription["id"]),
        )

    def _update_source_locked(
        self,
        source: dict[str, Any],
        updates: dict[str, Any],
        *,
        cleanup: PostCommitMediaCleanup,
    ) -> dict[str, Any]:
        config_changed = (
            "config" in updates and updates["config"] != source.get("config")
        )
        source_key_changed = (
            "source_key" in updates
            and updates["source_key"] != source.get("source_key")
        )
        updated = self.store.update_source(
            str(source["id"]), commit=False, **updates
        )
        if config_changed:
            self.source_health.reset_source(
                workspace_id=str(source["workspace_id"]),
                source_id=str(source["id"]),
                commit=False,
            )
        if source_key_changed and self.media_cache is not None:
            self.media_cache.invalidate_source_avatar(
                workspace_id=str(source["workspace_id"]),
                source_id=str(source["id"]),
                post_commit_cleanup=cleanup,
            )
        return updated

    # REST uses an explicit mutation context instead of the Agent-safe planner.
    # This keeps administrator shared-source rights intact while sharing the
    # transaction-sensitive lifecycle operations.
    def rest_create_subscription(
        self,
        actor: SubscriptionActor,
        *,
        source_id: str,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        self._live_actor(actor)
        source = self.store.get_source(source_id)
        if source is None or not self._visible(source, actor):
            raise self._error("not_found", "source not found", status_code=404)
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            if bool(values.get("enabled", True)):
                self.quota.ensure_source_allowed(
                    workspace_id=actor.workspace_id,
                    user_id=actor.user_id,
                    source_id=source_id,
                )
            result = self.store.create_subscription(
                user_id=actor.user_id,
                source_id=source_id,
                commit=False,
                **values,
            )
            if owns_transaction:
                conn.commit()
            return result
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise

    def rest_update_subscription(
        self,
        actor: SubscriptionActor,
        *,
        subscription_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        self._live_actor(actor)
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            subscription, _source, _schedule = self._subscription_context(
                actor, subscription_id
            )
            if updates.get("enabled") is True:
                self.quota.ensure_source_allowed(
                    workspace_id=actor.workspace_id,
                    user_id=actor.user_id,
                    source_id=str(subscription["source_id"]),
                )
            result = self.store.update_subscription(
                subscription_id, commit=False, **updates
            )
            if owns_transaction:
                conn.commit()
            return result
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise

    def rest_delete_subscription(
        self,
        actor: SubscriptionActor,
        *,
        subscription_id: str,
    ) -> bool:
        self._live_actor(actor)
        self._subscription_context(actor, subscription_id)
        return self.store.delete_subscription(
            subscription_id, user_id=actor.user_id
        )

    def rest_update_schedule(
        self,
        actor: SubscriptionActor,
        *,
        subscription_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        self._live_actor(actor)
        return self.source_schedules.update_subscription_schedule(
            workspace_id=actor.workspace_id,
            user_id=actor.user_id,
            subscription_id=subscription_id,
            **updates,
        )

    def _rest_source(
        self, actor: SubscriptionActor, source_id: str
    ) -> dict[str, Any]:
        user = self._live_actor(actor)
        source = self.store.get_source(source_id)
        if source is None or source.get("workspace_id") != actor.workspace_id:
            raise self._error("not_found", "source not found", status_code=404)
        if (
            source.get("scope") == "private"
            and source.get("owner_user_id") != actor.user_id
        ):
            raise self._error("not_found", "source not found", status_code=404)
        if source.get("scope") != "private" and user.get("role") not in {
            "owner",
            "admin",
        }:
            raise self._error(
                "forbidden", "only admins can update shared sources", status_code=403
            )
        return source

    def rest_update_source(
        self,
        actor: SubscriptionActor,
        *,
        source_id: str,
        updates: dict[str, Any],
        post_commit_cleanup: PostCommitMediaCleanup | None = None,
    ) -> dict[str, Any]:
        user = self._live_actor(actor)
        source = self._rest_source(actor, source_id)
        if "secret_env" in updates and user.get("role") not in {"owner", "admin"}:
            raise self._error(
                "forbidden", "only admins can assign a source secret", status_code=403
            )
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        if not owns_transaction and post_commit_cleanup is None:
            raise self._error(
                "post_commit_cleanup_required",
                "post_commit_cleanup is required for a caller-owned transaction",
                status_code=500,
            )
        cleanup = post_commit_cleanup or PostCommitMediaCleanup()
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            if updates.get("enabled") is True and not source.get("enabled"):
                enabled_subscribers = conn.execute(
                    """
                    SELECT user_id
                    FROM user_subscriptions
                    WHERE source_id = ? AND enabled = 1
                    ORDER BY user_id
                    """,
                    (source_id,),
                ).fetchall()
                for subscriber in enabled_subscribers:
                    self.quota.ensure_source_reenable_allowed(
                        workspace_id=actor.workspace_id,
                        user_id=str(subscriber["user_id"]),
                        source_id=source_id,
                    )
            config_changed = (
                "config" in updates and updates["config"] != source.get("config")
            )
            secret_changed = (
                "secret_env" in updates
                and updates["secret_env"] != source.get("secret_env")
            )
            key_changed = (
                "source_key" in updates
                and updates["source_key"] != source.get("source_key")
            )
            result = self.store.update_source(source_id, commit=False, **updates)
            if config_changed or secret_changed:
                self.source_health.reset_source(
                    workspace_id=actor.workspace_id,
                    source_id=source_id,
                    commit=False,
                )
            if key_changed and self.media_cache is not None:
                self.media_cache.invalidate_source_avatar(
                    workspace_id=actor.workspace_id,
                    source_id=source_id,
                    post_commit_cleanup=cleanup,
                )
            if owns_transaction:
                conn.commit()
                cleanup.run()
            return result
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
                cleanup.discard()
            raise

    def rest_upsert_source(
        self,
        actor: SubscriptionActor,
        *,
        values: dict[str, Any],
    ) -> dict[str, Any]:
        user = self._live_actor(actor)
        if values.get("workspace_id") != actor.workspace_id:
            raise self._error("not_found", "workspace not found", status_code=404)
        scope = values.get("scope")
        if scope != "private" and user.get("role") not in {"owner", "admin"}:
            raise self._error(
                "forbidden",
                "only admins can create public or workspace sources",
                status_code=403,
            )
        if scope == "private" and values.get("owner_user_id") != actor.user_id:
            raise self._error(
                "forbidden", "cannot create another user's private source", status_code=403
            )
        if values.get("secret_env") is not None and user.get("role") not in {
            "owner",
            "admin",
        }:
            raise self._error(
                "forbidden", "only admins can assign a source secret", status_code=403
            )
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            existing = self.store.get_source_by_key(
                workspace_id=actor.workspace_id,
                source_key=str(values["source_key"]),
            )
            result = self.store.upsert_source(**values)
            if existing and (
                values["config"] != existing.get("config")
                or values.get("secret_env") != existing.get("secret_env")
            ):
                self.source_health.reset_source(
                    workspace_id=actor.workspace_id,
                    source_id=str(existing["id"]),
                    commit=False,
                )
            if owns_transaction:
                conn.commit()
            return result
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
