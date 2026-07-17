"""Shared subscription mutation planning and atomic application.

The Agent-facing planner is deliberately narrower than the REST catalog API:
it can subscribe to visible shared sources, but it can only create and mutate
the caller's own private sources.  REST adapters use the explicit ``rest_*``
methods below so administrator catalog permissions are not accidentally
reduced to the Agent boundary.
"""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any, Literal

from ..storage.service_store import ServiceStore, SourceKeyConflictError
from .media_cache import MediaCacheService
from .quota import QuotaExceeded, QuotaService
from .source_health import SourceHealthService
from .source_schedule import (
    SOURCE_ALLOWED_INTERVALS,
    SourceScheduleService,
    SourceScheduleUnavailableError,
)
from .source_type_registry import (
    SourceConfigError,
    normalize_source_setup_input,
    source_key,
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


@dataclass(frozen=True, slots=True)
class SubscriptionChangePlan:
    kind: Literal["create", "update", "delete"]
    payload: dict[str, Any]
    preview: dict[str, Any]
    target_ids: dict[str, str]
    fingerprints: dict[str, str | None]


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
            normalize_source_setup_input(
                "rss",
                {
                    "url": "https://example.com/metadata-validation",
                    "__source_metadata__": values,
                },
            )
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
            normalized_source = {
                "mode": "existing",
                "source_id": str(target_source["id"]),
            }
            preview_type = str(target_source["type"])
            public_target = self._public_target(
                preview_type, target_source.get("config") or {}
            )
            display_name = str(target_source["display_name"])
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

        payload = {
            "source": normalized_source,
            "source_request": dict(source),
            "subscription": normalized_subscription,
            "schedule": normalized_schedule,
        }
        preview = {
            "action": "create_subscription",
            "source": {
                "display_name": display_name,
                "type": preview_type,
                "public_target": public_target,
            },
            "subscription": dict(normalized_subscription),
            "schedule": dict(normalized_schedule or {"enabled": False}),
            "impact": "Create or enable the caller's subscription.",
            "warnings": [],
        }
        target_ids = {}
        if target_source is not None:
            target_ids["source_id"] = str(target_source["id"])
        if existing_subscription is not None:
            target_ids["subscription_id"] = str(existing_subscription["id"])
        return SubscriptionChangePlan(
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
                        config = validate_source_config(str(source["type"]), value)
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
        payload = {
            "subscription_id": str(subscription_id),
            "source_updates": normalized_source_updates,
            "source_update_request": (
                dict(source_updates) if source_updates is not None else None
            ),
            "subscription_updates": normalized_subscription_updates,
            "schedule_updates": normalized_schedule_updates,
        }
        preview_source = {
            "display_name": normalized_source_updates.get(
                "display_name", source["display_name"]
            )
            if normalized_source_updates is not None
            else source["display_name"],
            "type": source["type"],
            "public_target": self._public_target(
                str(source["type"]),
                (
                    normalized_source_updates.get("config", source["config"])
                    if normalized_source_updates is not None
                    else source["config"]
                ),
            ),
        }
        return SubscriptionChangePlan(
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
        return SubscriptionChangePlan(
            "delete",
            {
                "subscription_id": str(subscription_id),
                "source_disposition": source_disposition,
            },
            {
                "action": "delete_subscription",
                "source": {
                    "display_name": source["display_name"],
                    "type": source["type"],
                    "public_target": self._public_target(
                        str(source["type"]), source.get("config") or {}
                    ),
                },
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

    def _rebuild(
        self, actor: SubscriptionActor, plan: SubscriptionChangePlan
    ) -> SubscriptionChangePlan:
        if not isinstance(plan, SubscriptionChangePlan):
            raise self._error("invalid_request", "invalid subscription change plan")
        if plan.kind == "create":
            return self.plan_create(
                actor,
                source=dict(plan.payload.get("source_request") or {}),
                subscription=dict(plan.payload.get("subscription") or {}),
                schedule=(
                    dict(plan.payload["schedule"])
                    if plan.payload.get("schedule") is not None
                    else None
                ),
            )
        if plan.kind == "update":
            return self.plan_update(
                actor,
                subscription_id=str(plan.payload.get("subscription_id") or ""),
                source_updates=plan.payload.get("source_update_request"),
                subscription_updates=plan.payload.get("subscription_updates"),
                schedule_updates=plan.payload.get("schedule_updates"),
            )
        if plan.kind == "delete":
            return self.plan_delete(
                actor,
                subscription_id=str(plan.payload.get("subscription_id") or ""),
                source_disposition=plan.payload.get("source_disposition", _MISSING),
            )
        raise self._error("invalid_request", "invalid subscription change kind")

    def apply_plan(
        self,
        actor: SubscriptionActor,
        plan: SubscriptionChangePlan,
        *,
        commit: bool = True,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            current = self._rebuild(actor, plan)
            if current.fingerprints != plan.fingerprints:
                raise self._error(
                    "proposal_stale", "proposal targets changed", status_code=409
                )
            result = self._apply_normalized(actor, current)
            if owns_transaction and commit:
                conn.commit()
            return result
        except QuotaExceeded as exc:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise self._error(
                exc.code, str(exc), status_code=429,
                action="Reduce enabled sources or increase the workspace quota.",
            ) from exc
        except SourceKeyConflictError as exc:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise self._error(
                "source_key_conflict",
                str(exc),
                status_code=409,
                action="Use the existing visible source or choose a different source configuration.",
            ) from exc
        except SourceScheduleUnavailableError as exc:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise self._error(
                exc.code,
                str(exc),
                status_code=409,
                action="Enable the subscription and source before enabling its schedule.",
            ) from exc
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise

    def _apply_normalized(
        self, actor: SubscriptionActor, plan: SubscriptionChangePlan
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
            if source_updates is not None:
                source = self._update_source_locked(source, source_updates)
            subscription_updates = plan.payload.get("subscription_updates")
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
        self, source: dict[str, Any], updates: dict[str, Any]
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
    ) -> dict[str, Any]:
        user = self._live_actor(actor)
        source = self._rest_source(actor, source_id)
        if "secret_env" in updates and user.get("role") not in {"owner", "admin"}:
            raise self._error(
                "forbidden", "only admins can assign a source secret", status_code=403
            )
        conn = self.store.connect()
        owns_transaction = not conn.in_transaction
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
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
                )
            if owns_transaction:
                conn.commit()
            return result
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
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
