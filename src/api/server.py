"""FastAPI entrypoint for the small-group InfoHub service API."""

from __future__ import annotations

import argparse
import logging
import os
import re
import time
import uuid
from contextlib import asynccontextmanager
from copy import deepcopy
from datetime import datetime, timezone
from pathlib import Path
from typing import Any, Literal

import uvicorn
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt, field_validator
from starlette.concurrency import run_in_threadpool

from ..logging_utils import configure_logging
from ..services.feed_archive import FeedArchiveService
from ..services.content_timeline import DEFAULT_FEED_WINDOW_DAYS
from ..services.feed_schedule import (
    ALLOWED_INTERVALS,
    FeedScheduleService,
    NoEnabledSubscriptionsError,
)
from ..services.job_eligibility import JobEligibilityService
from ..services.job_queue import JobQueue
from ..services.quota import QuotaExceeded, QuotaService
from ..services.runtime_status import RuntimeStatusService
from ..services.secret_quota import ApifySecretQuotaService, SecretQuotaError
from ..services.apify_key_pool import (
    ApifyKeyBusyError,
    ApifyKeyDrainPendingError,
    ApifyKeyPoolConflictError,
    ApifyKeyPoolError,
    ApifyKeyPoolService,
    apify_key_pool_enabled,
)
from ..services.source_health import SourceHealthService
from ..services.storage_governance import (
    StorageGovernanceError,
    StorageGovernanceService,
)
from ..services.source_schedule import (
    SOURCE_ALLOWED_INTERVALS,
    SourceScheduleService,
    SourceScheduleUnavailableError,
)
from ..services.subscription_mutation import (
    SubscriptionActor,
    SubscriptionMutationError,
    SubscriptionMutationService,
)
from ..services.secret_store import SecretStore, SecretValueError
from ..services.user_item_state import UserItemStateStore
from ..services.user_content_store import ContentSearchTimeoutError, UserContentStore
from ..services.media_cache import MediaCacheService
from ..services.preferred_source_notifications import (
    NotificationServiceError,
    PreferredSourceNotificationService,
)
from ..services.operation_log import (
    OperationLogQueryService,
    begin_request_context,
    bind_operation_actor,
    end_request_context,
    safe_emit_operation_event,
)
from ..services.notification_email_transport import (
    EmailTransportError,
)
from ..mcp.remote_config import OpenClawChatSettings, RemoteMCPSettings
from ..mcp.remote_server import create_remote_mcp
from ..services.source_type_registry import (
    SourceConfigError,
    YOUTUBE_CHANNEL_SETUP_TYPE,
    catalog_source_setup_type,
    list_source_setup_types,
    source_key as build_source_key,
    validate_secret_env_name,
    validate_source_config,
)
from ..services.youtube_channel import (
    YouTubeChannelError,
    YouTubeChannelResolver,
)
from ..storage.service_store import (
    AGENT_DELEGATION_MAX_ACTIVE,
    AGENT_DELEGATION_TTL_DAYS,
    ROLES,
    SOURCE_SCOPES,
    AgentDelegationLimitError,
    SecretEnvConflictError,
    ServiceStore,
    SourceKeyConflictError,
)
from ..tag_policy import HUB_CHANNELS
from ..ui.auth import AuthSettings, COOKIE_NAME
from ..config_migration import migrate_config_tag_layers
from ..ui.server import STATIC_DIR as LEGACY_STATIC_DIR, _read_json, _write_json, apply_config_action, build_env_status, validate_config_data


_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_PREFIXES = ("sk-", "sk_", "AIza", "xai-", "gsk_", "hf_", "tp-")
_LOGGER = logging.getLogger(__name__)
SERVICE_STATIC_DIR = Path(__file__).resolve().parents[1] / "ui" / "service_static"


def resolve_service_static_dir(
    variant: str | None = None,
    *,
    react_dir: Path | str = SERVICE_STATIC_DIR,
    legacy_dir: Path | str = LEGACY_STATIC_DIR,
) -> Path:
    """Resolve the Service UI without changing the legacy CLI/web asset directory."""

    selected = str(variant or os.getenv("HORIZON_SERVICE_UI_VARIANT", "react")).strip().lower()
    if selected not in {"react", "legacy"}:
        raise ValueError("HORIZON_SERVICE_UI_VARIANT must be react or legacy")
    react_path = Path(react_dir)
    legacy_path = Path(legacy_dir)
    if selected == "legacy":
        return legacy_path
    if (react_path / "index.html").exists():
        return react_path
    _LOGGER.warning("React Service UI build is missing; falling back to legacy assets")
    return legacy_path


class ApiError(Exception):
    """Structured API error converted to the public error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
        action: str = "",
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.action = action


def ok(data: Any) -> dict[str, Any]:
    return {"ok": True, "data": data}


def _public_job(job: dict[str, Any]) -> dict[str, Any]:
    """Remove worker-internal lease credentials from API responses."""
    return {key: value for key, value in job.items() if key != "claim_token"}


def error_response(exc: ApiError) -> JSONResponse:
    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
                "action": exc.action,
            },
        },
    )


def _validate_secret_env(value: str | None) -> str | None:
    try:
        return validate_secret_env_name(value)
    except SourceConfigError as exc:
        raise ApiError(
            "invalid_secret_env",
            str(exc),
            status_code=400,
            action="Store the real secret in .env or the deployment environment.",
        ) from exc


def _is_admin(user: dict[str, Any]) -> bool:
    return user.get("role") in {"owner", "admin"}


def _sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return ServiceStore.sanitize_user(user)


class LoginRequest(BaseModel):
    username: str
    password: str


class UserCreateRequest(BaseModel):
    username: str
    password: str
    role: str = "member"
    display_name: str | None = None
    enabled: bool = True


class UserPatchRequest(BaseModel):
    role: str | None = None
    display_name: str | None = None
    enabled: bool | None = None
    password: str | None = None


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


class NotificationSettingsPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool | None = None
    channel: Literal["email", "webhook"] | None = None
    email_address: str | None = Field(default=None, min_length=3, max_length=320)
    webhook_url: str | None = Field(default=None, min_length=8, max_length=4096)


class NotificationEmailTransportPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal[
        "qq",
        "netease",
        "gmail",
        "resend",
        "amazon_ses",
    ] | None = None
    sender_email: str | None = Field(
        default=None,
        min_length=3,
        max_length=320,
    )
    sender_name: str | None = Field(
        default=None,
        min_length=1,
        max_length=80,
    )
    credential: str | None = Field(default=None, max_length=4096)
    enabled: StrictBool | None = None
    region: str | None = Field(default=None, max_length=64)
    smtp_username: str | None = Field(default=None, max_length=320)


class NotificationEmailTransportTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_email: str = Field(min_length=3, max_length=320)


class SourceCreateRequest(BaseModel):
    scope: str | None = None
    type: str
    display_name: str
    description: str = ""
    default_channel: str | None = None
    default_topics: list[str] = Field(default_factory=list)
    config: dict[str, Any] = Field(default_factory=dict)
    secret_env: str | None = None
    enabled: bool = True


class SourcePatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    display_name: str | None = None
    description: str | None = None
    default_channel: str | None = None
    default_topics: list[str] | None = None
    config: dict[str, Any] | None = None
    secret_env: str | None = None
    enabled: bool | None = None


class SourceShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["public", "workspace"]


class SecretCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    provider: str
    env_name: str
    value: str


class SecretRotateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


class ApifyKeyPoolOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_ids: list[str]
    expected_generation: StrictInt = Field(ge=1)


class SubscriptionRequest(BaseModel):
    source_id: str
    enabled: bool = True
    override_channel: str | None = None
    override_topics: list[str] = Field(default_factory=list)
    personal_tags: list[str] = Field(default_factory=list)
    analysis_mode: str = "full"
    priority: StrictInt = Field(default=0, ge=0, le=100)
    notify_on_new_items: StrictBool = False


class SubscriptionPatchRequest(BaseModel):
    enabled: bool | None = None
    override_channel: str | None = None
    override_topics: list[str] | None = None
    personal_tags: list[str] | None = None
    analysis_mode: str | None = None
    priority: StrictInt | None = Field(default=None, ge=0, le=100)
    notify_on_new_items: StrictBool | None = None
    on_disable: Literal["keep", "save", "dismiss"] | None = None

    @field_validator("priority")
    @classmethod
    def validate_priority_is_not_null(cls, value: int | None) -> int:
        if value is None:
            raise ValueError("priority must be an integer between 0 and 100")
        return value


class FeedSchedulePatchRequest(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None


class SourceSchedulePatchRequest(BaseModel):
    enabled: bool | None = None
    interval_minutes: int | None = None


class JobCreateRequest(BaseModel):
    source_id: str | None = None
    subscription_id: str | None = None
    payload: dict[str, Any] = Field(default_factory=dict)
    priority: int = 0


class ItemStatePatchRequest(BaseModel):
    is_read: bool | None = None
    is_saved: bool | None = None
    is_later: bool | None = None
    dismissed: bool | None = None


class ItemFeedbackRequest(BaseModel):
    feedback_type: str
    value: int | None = None
    reason: str = ""
    metadata: dict[str, Any] = Field(default_factory=dict)


class AgentDelegationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    access: Literal["read", "subscriptions_write"] = "read"

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("name is required")
        return name


class AgentDelegationRenameRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)

    @field_validator("name")
    @classmethod
    def validate_name(cls, value: str) -> str:
        name = value.strip()
        if not name:
            raise ValueError("name is required")
        return name


class ConfigImportSourcesRequest(BaseModel):
    dry_run: bool = False
    subscribe_current_user: bool = True


class ConfigActionRequest(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


class StoragePlanRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    operation: Literal["cleanup", "archive", "restore", "delete_archive"]
    payload: dict[str, Any] = Field(default_factory=dict)


class StoragePlanApplyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str = Field(default="", max_length=240)


SOURCE_UPSERT_ACTIONS = {
    "upsert_rss": "rss",
    "upsert_github_release": "github_release",
    "upsert_github_user": "github_user",
    "upsert_reddit_subreddit": "reddit_subreddit",
    "upsert_telegram_channel": "telegram_channel",
    "upsert_apify_social_subscription": "apify_social",
}

SOURCE_DELETE_ACTIONS = {
    "delete_rss",
    "delete_github",
    "delete_reddit_subreddit",
    "delete_telegram_channel",
    "delete_apify_social_subscription",
}

SOURCE_META_KEYS = {
    "source_id",
    "subscription_id",
    "scope",
    "source_enabled",
    "subscription_enabled",
    "source_display_name",
}

MUTATION_OPERATION_ROUTES: dict[tuple[str, str], tuple[str, str]] = {
    ("POST", "/api/auth/login"): ("auth", "login"),
    ("POST", "/api/auth/logout"): ("auth", "logout"),
    ("POST", "/api/me/password"): ("account", "password_change"),
    ("PATCH", "/api/me/notification-settings"): (
        "notification",
        "settings_update",
    ),
    ("POST", "/api/me/notification-settings/test"): (
        "notification",
        "settings_test",
    ),
    ("POST", "/api/config/action"): ("source", "compat_config_action"),
    ("POST", "/api/users"): ("account", "member_create"),
    ("PATCH", "/api/users/{user_id}"): ("account", "member_update"),
    ("PATCH", "/api/admin/notification-email-transport"): (
        "notification",
        "email_transport_update",
    ),
    ("DELETE", "/api/admin/notification-email-transport"): (
        "notification",
        "email_transport_delete",
    ),
    ("POST", "/api/admin/notification-email-transport/test"): (
        "notification",
        "email_transport_test",
    ),
    ("PUT", "/api/admin/apify-key-pool/order"): ("secret", "pool_reorder"),
    ("POST", "/api/admin/apify-key-pool/{secret_id}/drain"): (
        "secret",
        "pool_drain",
    ),
    ("POST", "/api/admin/secrets"): ("secret", "create"),
    ("PUT", "/api/admin/secrets/{secret_id}/value"): ("secret", "rotate"),
    ("DELETE", "/api/admin/secrets/{secret_id}"): ("secret", "delete"),
    ("POST", "/api/admin/storage/plans"): ("storage", "plan_preview"),
    ("POST", "/api/admin/storage/plans/{plan_id}/apply"): (
        "storage",
        "plan_apply",
    ),
    ("POST", "/api/catalog/import-config-sources"): ("source", "import"),
    ("POST", "/api/catalog/sources"): ("source", "create"),
    ("PATCH", "/api/catalog/sources/{source_id}"): ("source", "update"),
    ("POST", "/api/catalog/sources/{source_id}/share"): ("source", "share"),
    ("DELETE", "/api/catalog/sources/{source_id}"): ("source", "disable"),
    ("POST", "/api/catalog/sources/{source_id}/subscribe"): (
        "subscription",
        "create",
    ),
    ("DELETE", "/api/catalog/sources/{source_id}/subscription"): (
        "subscription",
        "delete",
    ),
    ("POST", "/api/me/agent-delegations"): ("agent", "delegation_create"),
    ("PATCH", "/api/me/agent-delegations/{delegation_id}"): (
        "agent",
        "delegation_rename",
    ),
    ("DELETE", "/api/me/agent-delegations/{delegation_id}"): (
        "agent",
        "delegation_revoke",
    ),
    ("DELETE", "/api/me/agent-delegations/{delegation_id}/record"): (
        "agent",
        "delegation_delete",
    ),
    ("PATCH", "/api/me/feed-schedule"): ("schedule", "feed_update"),
    ("POST", "/api/me/subscriptions"): ("subscription", "create"),
    ("PATCH", "/api/me/subscriptions/{subscription_id}"): (
        "subscription",
        "update",
    ),
    ("PATCH", "/api/me/subscriptions/{subscription_id}/schedule"): (
        "schedule",
        "source_update",
    ),
    ("DELETE", "/api/me/subscriptions/{subscription_id}"): (
        "subscription",
        "delete",
    ),
    ("POST", "/api/jobs/source-test"): ("job", "source_test_queue"),
    ("POST", "/api/jobs/source-fetch"): ("job", "source_fetch_queue"),
    ("POST", "/api/jobs/user-feed-refresh"): ("job", "feed_refresh_queue"),
    ("POST", "/api/source/test"): ("job", "compat_source_test_queue"),
    ("POST", "/api/source/update"): ("job", "compat_source_update_queue"),
    ("POST", "/api/jobs/{job_id}/cancel"): ("job", "cancel"),
    ("POST", "/api/jobs/{job_id}/retry"): ("job", "retry"),
}


def create_app(
    *,
    data_dir: Path | str = "data",
    static_dir: Path | str | None = None,
    log_dir: Path | str | None = None,
) -> FastAPI:
    """Create the FastAPI app with a local SQLite-backed service store."""

    data_path = Path(data_dir)
    operation_logs = OperationLogQueryService(
        Path(log_dir) if log_dir is not None else data_path.parent / "logs"
    )
    static_path = Path(static_dir) if static_dir is not None else resolve_service_static_dir()
    store = ServiceStore(data_path)
    store.initialize()
    queue = JobQueue(store)
    runtime_status = RuntimeStatusService(store)
    source_health = SourceHealthService(store)
    youtube_channels = YouTubeChannelResolver()
    storage_governance = StorageGovernanceService(store)
    secret_values = SecretStore(data_path)
    secret_quota = ApifySecretQuotaService()
    secret_values.load_into_environ()
    preferred_source_notifications = PreferredSourceNotificationService(
        store,
        data_dir=str(data_path),
    )
    workspace_email_transport = (
        preferred_source_notifications.email_transport
    )
    apify_key_pool = ApifyKeyPoolService(store, secret_store=secret_values)
    quota = QuotaService(
        store,
        max_fetch_jobs_per_day=int(os.getenv("INFOHUB_MAX_FETCH_JOBS_PER_DAY", "100")),
        max_sources_per_user=int(os.getenv("INFOHUB_MAX_SOURCES_PER_USER", "100")),
        max_ai_items_per_day=int(os.getenv("INFOHUB_MAX_AI_ITEMS_PER_DAY", "1000")),
        max_workspace_ai_attempts_per_day=int(
            os.getenv("INFOHUB_MAX_WORKSPACE_AI_ATTEMPTS_PER_DAY", "1000")
        ),
        max_workspace_fetch_attempts_per_day=int(
            os.getenv("INFOHUB_MAX_WORKSPACE_FETCH_ATTEMPTS_PER_DAY", "100")
        ),
        max_provider_fetch_attempts_per_day=int(
            os.getenv("INFOHUB_MAX_PROVIDER_FETCH_ATTEMPTS_PER_DAY", "100")
        ),
    )
    feed_schedules = FeedScheduleService(store, quota=quota)
    source_schedules = SourceScheduleService(store, quota=quota)
    feed_archive = FeedArchiveService(data_path, store=store)
    item_state = UserItemStateStore(store)
    user_content = UserContentStore(store)
    media_cache = MediaCacheService(store, data_dir=data_path)
    subscription_mutations = SubscriptionMutationService(
        store,
        quota=quota,
        source_schedules=source_schedules,
        source_health=source_health,
        media_cache=media_cache,
    )
    auth_settings = AuthSettings.from_env()
    remote_mcp_settings = RemoteMCPSettings.from_env()
    openclaw_chat_settings = OpenClawChatSettings.from_env()

    def is_apify_secret(secret: dict[str, Any]) -> bool:
        return (
            str(secret.get("provider") or "").lower() == "apify"
            or str(secret.get("kind") or "").lower() == "apify"
        )

    def secret_usage(secret: dict[str, Any]) -> list[dict[str, str]]:
        pool_managed_apify = (
            apify_key_pool_enabled()
            and is_apify_secret(secret)
        )
        usages = []
        if not pool_managed_apify:
            usages = [
                {
                    "type": "source",
                    "id": str(source["id"]),
                    "name": str(source.get("display_name") or source["id"]),
                }
                for source in store.list_sources_using_secret(
                    workspace_id=secret["workspace_id"],
                    env_name=secret["env_name"],
                )
            ]
        try:
            _base_data, base_config = read_base_config()
        except Exception:
            base_config = None
        if base_config is not None and base_config.ai.api_key_env == secret["env_name"]:
            usages.append(
                {
                    "type": "ai",
                    "id": "global-ai",
                    "name": str(base_config.ai.provider.value),
                }
            )
        return usages

    def public_secret(secret: dict[str, Any]) -> dict[str, Any]:
        return {
            "id": secret["id"],
            "name": secret["name"],
            "kind": secret["kind"],
            "provider": secret["provider"],
            "env_name": secret["env_name"],
            "is_set": bool(secret_values.status(secret["env_name"])["is_set"]),
            "used_by": secret_usage(secret),
            "created_at": secret["created_at"],
            "updated_at": secret["updated_at"],
        }

    def validate_secret_metadata(payload: SecretCreateRequest) -> tuple[str, str, str, str]:
        name = str(payload.name or "").strip()
        kind = str(payload.kind or "").strip().lower()
        provider = str(payload.provider or "").strip().lower()
        if not name:
            raise ApiError("invalid_secret", "secret name is required", status_code=400)
        if kind not in {"ai", "apify"}:
            raise ApiError("invalid_secret", "secret kind must be ai or apify", status_code=400)
        allowed_providers = {"gemini", "openai", "anthropic", "deepseek"} if kind == "ai" else {"apify"}
        if provider not in allowed_providers:
            raise ApiError(
                "invalid_secret",
                f"provider is not valid for {kind}",
                status_code=400,
            )
        try:
            env_name = secret_values.validate_env_name(payload.env_name)
            secret_values.validate_value(payload.value)
        except SecretValueError as exc:
            raise ApiError("invalid_secret", str(exc), status_code=400) from exc
        return name, kind, provider, env_name

    def public_source(source: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
        item = dict(source)
        item.pop("enforce_public_network", None)
        item["setup_type"] = catalog_source_setup_type(
            str(source.get("type") or ""),
            source.get("config"),
        )
        avatar = media_cache.avatar_for_source(
            workspace_id=str(source["workspace_id"]),
            source_id=str(source["id"]),
        )
        item["avatar_url"] = f"/api/media/{avatar['id']}" if avatar else ""
        pool_managed_apify = (
            source.get("type") == "apify_social" and apify_key_pool_enabled()
        )
        if pool_managed_apify:
            pool = apify_key_pool.public_state(str(source["workspace_id"]))
            active_secret_id = pool.get("active_secret_id")
            active_secret = (
                store.get_secret_ref(str(active_secret_id))
                if active_secret_id
                else None
            )
            item["secret_configured"] = bool(
                active_secret
                and secret_values.read().get(str(active_secret["env_name"]))
            )
            item.pop("secret_env", None)
        else:
            env_name = item.get("secret_env")
            item["secret_configured"] = bool(
                env_name and secret_values.status(str(env_name))["is_set"]
            )
            if not _is_admin(user):
                item.pop("secret_env", None)
        return item

    def reject_pool_managed_source_secret(
        source_type: str,
        *,
        supplied: bool,
    ) -> None:
        if (
            supplied
            and source_type == "apify_social"
            and apify_key_pool_enabled()
        ):
            raise ApiError(
                "apify_key_pool_managed",
                "Apify source credentials are managed by the workspace Key pool.",
                status_code=409,
                action="Manage Apify Keys in Settings and omit secret_env.",
            )

    def pool_api_error(exc: ApifyKeyPoolError) -> ApiError:
        return ApiError(
            exc.code,
            "The Apify Key pool cannot complete this transition safely.",
            status_code=409,
            retryable=bool(getattr(exc, "retryable", False)),
            action=(
                "Wait for active Actor Runs to reach a terminal state and retry."
                if isinstance(exc, ApifyKeyDrainPendingError)
                else "Refresh the Key pool state and retry."
            ),
        )

    def create_subscription_with_quota(
        *,
        user: dict[str, Any],
        source_id: str,
        **values: Any,
    ) -> dict[str, Any]:
        return subscription_mutations.rest_create_subscription(
            SubscriptionActor.from_user(user),
            source_id=source_id,
            values=values,
        )

    def update_subscription_with_quota(
        *,
        user: dict[str, Any],
        subscription_id: str,
        updates: dict[str, Any],
    ) -> dict[str, Any]:
        return subscription_mutations.rest_update_subscription(
            SubscriptionActor.from_user(user),
            subscription_id=subscription_id,
            updates=updates,
        )

    def visible_sources(
        user: dict[str, Any],
        *,
        include_disabled: bool = False,
    ) -> list[dict[str, Any]]:
        return [
            public_source(source, user)
            for source in store.list_visible_sources(
                user,
                include_disabled=include_disabled,
            )
        ]

    def update_catalog_source(
        source: dict[str, Any],
        updates: dict[str, Any],
        *,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        reject_pool_managed_source_secret(
            str(source.get("type") or ""),
            supplied="secret_env" in updates,
        )
        return subscription_mutations.rest_update_source(
            SubscriptionActor.from_user(user),
            source_id=str(source["id"]),
            updates=updates,
        )

    def upsert_catalog_source(
        *, user: dict[str, Any], **values: Any
    ) -> dict[str, Any]:
        reject_pool_managed_source_secret(
            str(values.get("source_type") or ""),
            supplied=values.get("secret_env") is not None,
        )
        return subscription_mutations.rest_upsert_source(
            SubscriptionActor.from_user(user), values=values
        )

    remote_mcp = (
        create_remote_mcp(
            store,
            remote_mcp_settings,
            mutation_service=subscription_mutations,
            runtime_status=runtime_status,
            operation_logs=operation_logs,
            secret_is_set=lambda env_name: bool(
                secret_values.status(env_name)["is_set"]
            ),
        )
        if remote_mcp_settings.enabled
        else None
    )

    @asynccontextmanager
    async def app_lifespan(_app: FastAPI):
        if remote_mcp is None:
            yield
            return
        async with remote_mcp.server.session_manager.run():
            yield

    app = FastAPI(title="InfoHub Light Service API", lifespan=app_lifespan)
    app.state.service_store = store
    app.state.subscription_mutations = subscription_mutations
    app.state.preferred_source_notifications = preferred_source_notifications
    app.state.workspace_email_transport = workspace_email_transport
    app.state.remote_mcp = remote_mcp.server if remote_mcp else None
    app.state.youtube_channel_resolver = youtube_channels

    @app.middleware("http")
    async def _remote_mcp_body_limit(request: Request, call_next):
        if request.url.path == "/mcp":
            content_length = request.headers.get("content-length")
            if content_length:
                try:
                    too_large = int(content_length) > 256 * 1024
                except ValueError:
                    too_large = True
                if too_large:
                    return JSONResponse(
                        status_code=413,
                        content={"error": "request_body_too_large"},
                    )
        return await call_next(request)

    @app.middleware("http")
    async def _frontend_cache_headers(request: Request, call_next):
        response = await call_next(request)
        if response.status_code < 400 and request.url.path.startswith("/assets/"):
            response.headers["Cache-Control"] = "public, max-age=31536000, immutable"
        elif (
            response.status_code < 400
            and not request.url.path.startswith("/api/")
            and response.headers.get("content-type", "").startswith("text/html")
        ):
            response.headers["Cache-Control"] = "no-cache"
        return response

    @app.middleware("http")
    async def _api_database_transaction_boundary(request: Request, call_next):
        database_scoped = request.url.path.startswith("/api/") or request.url.path == "/mcp"
        if not database_scoped or request.url.path == "/api/health/live":
            return await call_next(request)

        with store.request_connection_scope():
            conn = store.connect()
            try:
                response = await call_next(request)
            except BaseException:
                if conn.in_transaction:
                    conn.rollback()
                raise
            else:
                if conn.in_transaction:
                    conn.rollback()
                    request.state.operation_error_code = (
                        "database_transaction_leak"
                    )
                    _LOGGER.error(
                        "API database transaction leaked method=%s route=%s",
                        request.method,
                        getattr(request.scope.get("route"), "path", "-"),
                    )
                    return error_response(
                        ApiError(
                            "database_transaction_leak",
                            "request did not finish its database transaction",
                            status_code=500,
                            retryable=True,
                            action="Retry the request and inspect the API logs.",
                        )
                    )
                return response

    @app.middleware("http")
    async def _request_operation_context(request: Request, call_next):
        request_id = f"req_{uuid.uuid4().hex}"
        token = begin_request_context(request_id)
        started = time.perf_counter()
        try:
            response = await call_next(request)
        except Exception:
            route = request.scope.get("route")
            route_template = getattr(route, "path", None)
            _LOGGER.exception(
                "api_request_failed method=%s route=%s request_id=%s",
                request.method,
                route_template if isinstance(route_template, str) else "-",
                request_id,
            )
            operation = (
                MUTATION_OPERATION_ROUTES.get((request.method, route_template))
                if isinstance(route_template, str)
                else None
            )
            if operation is not None:
                category, action = operation
                safe_emit_operation_event(
                    category=category,
                    action=action,
                    outcome="failed",
                    level="error",
                    workspace_id=getattr(
                        request.state, "operation_workspace_id", None
                    ),
                    actor_user_id=getattr(
                        request.state, "operation_actor_user_id", None
                    ),
                    subject_user_id=(
                        getattr(request.state, "operation_subject_user_id", None)
                    ),
                    job_id=(
                        getattr(request.state, "operation_job_id", None)
                    ),
                    source_id=(
                        getattr(request.state, "operation_source_id", None)
                    ),
                    subscription_id=(
                        getattr(request.state, "operation_subscription_id", None)
                    ),
                    error_code=(
                        getattr(request.state, "operation_error_code", None)
                        or "internal_error"
                    ),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    route=route_template,
                    method=(
                        request.method
                        if request.method in {"POST", "PUT", "PATCH", "DELETE"}
                        else None
                    ),
                    status_code=500,
                )
            raise
        else:
            if request.url.path.startswith("/api/") or request.url.path == "/mcp":
                response.headers["X-Request-ID"] = request_id
            route = request.scope.get("route")
            route_template = getattr(route, "path", None)
            operation = (
                MUTATION_OPERATION_ROUTES.get((request.method, route_template))
                if isinstance(route_template, str)
                else None
            )
            if operation is not None and not getattr(
                request.state, "operation_logged", False
            ):
                category, action = operation
                status_code = int(response.status_code)
                explicit_outcome = getattr(
                    request.state, "operation_outcome", None
                )
                explicit_level = getattr(request.state, "operation_level", None)
                if status_code < 400 and explicit_outcome is not None:
                    outcome = explicit_outcome
                    level = explicit_level or (
                        "warning"
                        if outcome in {"partial", "retried", "skipped"}
                        else "info"
                    )
                elif status_code < 400:
                    outcome = "succeeded"
                    level = "info"
                elif status_code in {400, 401, 403, 404, 409, 422, 429}:
                    outcome = "denied"
                    level = "warning"
                else:
                    outcome = "failed"
                    level = "error"
                path_params = request.path_params
                include_path_ids = status_code < 400
                safe_emit_operation_event(
                    category=category,
                    action=action,
                    outcome=outcome,
                    level=level,
                    workspace_id=getattr(
                        request.state, "operation_workspace_id", None
                    ),
                    actor_user_id=getattr(
                        request.state, "operation_actor_user_id", None
                    ),
                    subject_user_id=(
                        getattr(request.state, "operation_subject_user_id", None)
                        or (
                            str(path_params["user_id"])
                            if include_path_ids and "user_id" in path_params
                            else None
                        )
                    ),
                    job_id=(
                        getattr(request.state, "operation_job_id", None)
                        or (
                            str(path_params["job_id"])
                            if include_path_ids and "job_id" in path_params
                            else None
                        )
                    ),
                    source_id=(
                        getattr(request.state, "operation_source_id", None)
                        or (
                            str(path_params["source_id"])
                            if include_path_ids and "source_id" in path_params
                            else None
                        )
                    ),
                    subscription_id=(
                        getattr(request.state, "operation_subscription_id", None)
                        or (
                            str(path_params["subscription_id"])
                            if include_path_ids
                            and "subscription_id" in path_params
                            else None
                        )
                    ),
                    error_code=getattr(
                        request.state, "operation_error_code", None
                    ),
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    changed_fields=getattr(
                        request.state, "operation_changed_fields", None
                    ),
                    counts=getattr(request.state, "operation_counts", None),
                    route=route_template,
                    method=request.method,
                    status_code=status_code,
                )
            return response
        finally:
            end_request_context(token)

    def mark_operation_error(request: Request, code: str) -> None:
        request.state.operation_error_code = code

    @app.exception_handler(ApiError)
    async def _api_error_handler(request: Request, exc: ApiError) -> JSONResponse:
        mark_operation_error(request, exc.code)
        return error_response(exc)

    @app.exception_handler(SubscriptionMutationError)
    async def _subscription_mutation_error_handler(
        request: Request, exc: SubscriptionMutationError
    ) -> JSONResponse:
        mark_operation_error(request, exc.code)
        return error_response(
            ApiError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                action=exc.action,
            )
        )

    @app.exception_handler(NotificationServiceError)
    async def _notification_service_error_handler(
        request: Request,
        exc: NotificationServiceError,
    ) -> JSONResponse:
        mark_operation_error(request, exc.code)
        return error_response(
            ApiError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                action=(
                    "Wait at least 60 seconds before sending another test."
                    if exc.code == "notification_test_rate_limited"
                    else (
                        "Review the saved notification channel and send another test."
                        if exc.status_code < 500
                        else "Retry later without changing the Feed or source job."
                    )
                ),
            )
        )

    @app.exception_handler(EmailTransportError)
    async def _email_transport_error_handler(
        request: Request,
        exc: EmailTransportError,
    ) -> JSONResponse:
        mark_operation_error(request, exc.code)
        return error_response(
            ApiError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                action=(
                    "Wait at least 60 seconds before sending another test."
                    if exc.code == "email_transport_test_rate_limited"
                    else (
                        "Save the provider settings, send a test, then enable the transport."
                        if exc.status_code < 500
                        else "Review the provider credential and retry the test."
                    )
                ),
            )
        )

    @app.exception_handler(QuotaExceeded)
    async def _quota_error_handler(request: Request, exc: QuotaExceeded) -> JSONResponse:
        mark_operation_error(request, exc.code)
        user = store.get_session_user(request.cookies.get(COOKIE_NAME))
        if user:
            try:
                quota.record_quota_reject(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                    quota="api_admission",
                )
            except Exception:
                if store.connect().in_transaction:
                    store.connect().rollback()
                _LOGGER.exception("failed to persist quota rejection metric")
        return error_response(
            ApiError(
                exc.code,
                exc.message,
                status_code=429,
                action="Reduce job frequency or increase the workspace quota.",
            )
        )

    @app.exception_handler(ValueError)
    async def _value_error_handler(request: Request, exc: ValueError) -> JSONResponse:
        mark_operation_error(request, "invalid_request")
        return error_response(ApiError("invalid_request", str(exc), status_code=400))

    @app.exception_handler(StorageGovernanceError)
    async def _storage_governance_error_handler(
        request: Request,
        exc: StorageGovernanceError,
    ) -> JSONResponse:
        mark_operation_error(request, exc.code)
        return error_response(
            ApiError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
            )
        )

    @app.exception_handler(RequestValidationError)
    async def _request_validation_error_handler(request: Request, exc: RequestValidationError) -> JSONResponse:
        mark_operation_error(request, "invalid_request")
        errors = exc.errors()
        message = "invalid request"
        if errors:
            first = errors[0]
            location = ".".join(str(part) for part in first.get("loc", []) if part != "body")
            detail = str(first.get("msg") or "invalid value")
            message = f"{location}: {detail}" if location else detail
        return error_response(
            ApiError(
                "invalid_request",
                message,
                status_code=400,
                action="Fix the request payload or query parameters.",
            )
        )

    async def current_user(request: Request) -> dict[str, Any]:
        token = request.cookies.get(COOKIE_NAME)
        user = store.get_session_user(token)
        if not user:
            raise ApiError("unauthorized", "login required", status_code=401, action="Log in and retry.")
        bind_operation_actor(
            workspace_id=str(user["workspace_id"]),
            user_id=str(user["id"]),
        )
        request.state.operation_workspace_id = str(user["workspace_id"])
        request.state.operation_actor_user_id = str(user["id"])
        return user

    async def current_admin(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        if not _is_admin(user):
            raise ApiError("forbidden", "admin role required", status_code=403)
        return user

    def require_mutating_member(user: dict[str, Any]) -> None:
        if user.get("role") == "viewer":
            raise ApiError(
                "forbidden",
                "viewer users cannot change sources, subscriptions, or jobs",
                status_code=403,
            )

    def visible_source_or_404(source_id: str, user: dict[str, Any]) -> dict[str, Any]:
        for source in store.list_visible_sources(user):
            if source["id"] == source_id:
                return source
        raise ApiError("not_found", "source not found", status_code=404)

    def manageable_source_or_404(
        source_id: str,
        user: dict[str, Any],
    ) -> dict[str, Any]:
        source = store.get_source(source_id)
        if source is None or source.get("workspace_id") != user.get("workspace_id"):
            raise ApiError("not_found", "source not found", status_code=404)
        if source.get("scope") == "private" and source.get("owner_user_id") != user.get("id"):
            raise ApiError("not_found", "source not found", status_code=404)
        return source

    def feed_schedule_response(user: dict[str, Any]) -> dict[str, Any]:
        schedule = feed_schedules.get_user_schedule(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
        )
        last_job = queue.get_job(str(schedule.get("last_job_id") or ""))
        if last_job and (
            last_job.get("workspace_id") != user["workspace_id"]
            or last_job.get("user_id") != user["id"]
        ):
            last_job = None
        active_row = store.connect().execute(
            """
            SELECT * FROM fetch_jobs
            WHERE workspace_id = ?
              AND user_id = ?
              AND job_type = 'user_feed_refresh'
              AND status IN ('queued', 'running')
            ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
            LIMIT 1
            """,
            (user["workspace_id"], user["id"]),
        ).fetchone()
        active_job = store._job(active_row)
        worker_status = runtime_status.summary(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
        )["worker_status"]
        return {
            "schema_version": 1,
            "enabled": bool(schedule["enabled"]),
            "interval_minutes": int(schedule["interval_minutes"]),
            "allowed_intervals": list(ALLOWED_INTERVALS),
            "next_run_at": schedule.get("next_run_at"),
            "last_evaluated_at": schedule.get("last_evaluated_at"),
            "last_enqueued_at": schedule.get("last_enqueued_at"),
            "last_skip_reason": schedule.get("last_skip_reason"),
            "last_job": _public_job(last_job) if last_job else None,
            "active_job": _public_job(active_job) if active_job else None,
            "worker_status": worker_status,
        }

    def source_schedule_response(
        user: dict[str, Any], subscription_id: str
    ) -> dict[str, Any]:
        try:
            schedule = source_schedules.get_subscription_schedule(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                subscription_id=subscription_id,
            )
        except LookupError as exc:
            raise ApiError(
                "not_found", "subscription not found", status_code=404
            ) from exc
        last_job = queue.get_job(str(schedule.get("last_job_id") or ""))
        if last_job and (
            last_job.get("workspace_id") != user["workspace_id"]
            or last_job.get("user_id") != user["id"]
            or last_job.get("subscription_id") != subscription_id
        ):
            last_job = None
        active_row = store.connect().execute(
            """
            SELECT * FROM fetch_jobs
            WHERE workspace_id = ?
              AND user_id = ?
              AND subscription_id = ?
              AND job_type = 'source_fetch'
              AND status IN ('queued', 'running')
            ORDER BY CASE status WHEN 'running' THEN 0 ELSE 1 END, created_at
            LIMIT 1
            """,
            (user["workspace_id"], user["id"], subscription_id),
        ).fetchone()
        active_job = store._job(active_row)
        worker_status = runtime_status.summary(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
        )["worker_status"]
        return {
            "schema_version": 1,
            "subscription_id": subscription_id,
            "source_id": schedule["source_id"],
            "enabled": bool(schedule["enabled"]),
            "interval_minutes": int(schedule["interval_minutes"]),
            "allowed_intervals": list(SOURCE_ALLOWED_INTERVALS),
            "next_run_at": schedule.get("next_run_at"),
            "last_evaluated_at": schedule.get("last_evaluated_at"),
            "last_enqueued_at": schedule.get("last_enqueued_at"),
            "last_skip_reason": schedule.get("last_skip_reason"),
            "last_job": _public_job(last_job) if last_job else None,
            "active_job": _public_job(active_job) if active_job else None,
            "worker_status": worker_status,
        }

    def read_base_config() -> tuple[dict[str, Any], Any]:
        config_path = data_path / "config.json"
        if not config_path.exists():
            raise ApiError("config_not_found", "data/config.json not found", status_code=404)
        data = migrate_config_tag_layers(_read_json(config_path))
        config = validate_config_data(data)
        return data, config

    def current_feed_window_days() -> int:
        try:
            _data, config = read_base_config()
        except ApiError as exc:
            if exc.code == "config_not_found":
                return DEFAULT_FEED_WINDOW_DAYS
            raise
        return int(config.filtering.feed_window_days)

    def write_base_config(data: dict[str, Any]) -> None:
        validate_config_data(data)
        _write_json(data_path / "config.json", migrate_config_tag_layers(data))

    def reset_service_sources(data: dict[str, Any]) -> dict[str, Any]:
        sources = data.setdefault("sources", {})
        sources["rss"] = []
        sources["github"] = []
        sources.setdefault("hackernews", {"enabled": False})
        sources["reddit"] = {
            **sources.get("reddit", {}),
            "enabled": False,
            "subreddits": [],
            "users": [],
        }
        sources["telegram"] = {
            **sources.get("telegram", {}),
            "enabled": False,
            "channels": [],
        }
        sources["apify_social"] = {
            **sources.get("apify_social", {}),
            "enabled": False,
            "subscriptions": [],
        }
        return sources

    def entry_from_record(record: dict[str, Any]) -> dict[str, Any]:
        entry = deepcopy(record.get("config") or {})
        entry["enabled"] = bool(record.get("subscription_enabled"))
        entry["source_id"] = record["source_id"]
        entry["subscription_id"] = record["subscription_id"]
        entry["scope"] = record["scope"]
        entry["source_enabled"] = bool(record.get("source_enabled"))
        entry["subscription_enabled"] = bool(record.get("subscription_enabled"))
        entry["source_display_name"] = record.get("display_name") or ""
        channel = record.get("override_channel") or record.get("default_channel")
        if channel:
            entry["channel"] = channel
            entry["category"] = channel
            if record.get("type") == "telegram_channel":
                entry["hub_channel"] = channel
        topics = record.get("override_topics") or record.get("default_topics") or []
        if topics:
            entry["topics"] = list(topics)
            entry["tags"] = list(topics)
        personal_tags = record.get("personal_tags") or []
        if personal_tags:
            entry["personal_tags"] = list(personal_tags)
        if record.get("analysis_mode"):
            entry["analysis_mode"] = record["analysis_mode"]
        if record.get("secret_env") and not entry.get("token_env"):
            entry["token_env"] = record["secret_env"]
        return entry

    def append_record_source(sources: dict[str, Any], record: dict[str, Any]) -> None:
        source_type = str(record.get("type") or "")
        entry = entry_from_record(record)
        if source_type == "rss":
            entry.setdefault("name", record.get("display_name") or "")
            sources["rss"].append(entry)
            return
        if source_type in {"github", "github_release", "github_user"}:
            if source_type == "github_release":
                entry.setdefault("type", "repo_releases")
            elif source_type == "github_user":
                entry.setdefault("type", "user_events")
            sources["github"].append(entry)
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
            sources["apify_social"]["enabled"] = True
            sources["apify_social"].setdefault("subscriptions", []).append(entry)
            return
        if source_type == "hackernews":
            sources["hackernews"] = {**entry, "enabled": bool(record.get("subscription_enabled"))}

    def build_config_data_for_user(base_data: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
        data = deepcopy(base_data)
        sources = reset_service_sources(data)
        records = store.list_user_subscriptions_with_sources(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
        )
        for record in records:
            append_record_source(sources, record)
        return data

    def config_response(user: dict[str, Any]) -> dict[str, Any]:
        base_data, _base_config = read_base_config()
        data = build_config_data_for_user(base_data, user)
        config = validate_config_data(data)
        return {
            "path": str(data_path / "config.json"),
            "config": data,
            "taxonomy": {
                "channels": list(HUB_CHANNELS),
                "topics": list(config.tags),
            },
            "env_status": build_env_status(config),
            "service": {
                "current_user": _sanitize_user(user),
                "sources": visible_sources(user),
                "subscriptions": store.list_user_subscriptions(user["id"]),
            },
        }

    def source_entries_for_action(data: dict[str, Any], action: str) -> list[dict[str, Any]]:
        sources = data.setdefault("sources", {})
        if action == "upsert_rss":
            return sources.setdefault("rss", [])
        if action in {"upsert_github_release", "upsert_github_user"}:
            return sources.setdefault("github", [])
        if action == "upsert_reddit_subreddit":
            return sources.setdefault("reddit", {}).setdefault("subreddits", [])
        if action == "upsert_telegram_channel":
            return sources.setdefault("telegram", {}).setdefault("channels", [])
        if action == "upsert_apify_social_subscription":
            return sources.setdefault("apify_social", {}).setdefault("subscriptions", [])
        raise ApiError("unsupported_source_action", f"unsupported source action: {action}", status_code=400)

    def payload_index(payload: dict[str, Any]) -> int | None:
        raw = payload.get("index")
        if raw is None or raw == "":
            return None
        try:
            return int(raw)
        except (TypeError, ValueError) as exc:
            raise ApiError("invalid_index", "index must be an integer", status_code=400) from exc

    def source_item_for_upsert(data: dict[str, Any], action: str, payload: dict[str, Any]) -> dict[str, Any]:
        entries = source_entries_for_action(data, action)
        if not entries:
            raise ApiError("invalid_source_action", "source action did not produce an entry", status_code=400)
        idx = payload_index(payload)
        if idx is None:
            return entries[-1]
        if idx >= len(entries):
            raise ApiError("invalid_index", "index is out of range", status_code=400)
        return entries[idx]

    def source_display_name(source_type: str, item: dict[str, Any]) -> str:
        if source_type == "rss":
            return str(item.get("name") or item.get("url") or "RSS Source")
        if source_type == "github_release":
            return f"{item.get('owner')}/{item.get('repo')} releases"
        if source_type == "github_user":
            return str(item.get("username") or "GitHub User")
        if source_type == "reddit_subreddit":
            return f"r/{item.get('subreddit')}"
        if source_type == "telegram_channel":
            return f"@{item.get('channel')}"
        if source_type == "apify_social":
            return f"{item.get('platform')}:{item.get('target')}"
        return source_type

    def source_channel(item: dict[str, Any]) -> str | None:
        return item.get("channel") or item.get("category") or item.get("hub_channel")

    def source_default_channel(source_type: str, item: dict[str, Any]) -> str | None:
        if source_type == "telegram_channel":
            return item.get("hub_channel") or item.get("category")
        return source_channel(item)

    def source_topics(item: dict[str, Any]) -> list[str]:
        value = item.get("topics") or item.get("tags") or []
        return list(value) if isinstance(value, list) else []

    def source_personal_tags(item: dict[str, Any]) -> list[str]:
        value = item.get("personal_tags") or []
        return list(value) if isinstance(value, list) else []

    def source_secret_env(item: dict[str, Any]) -> str | None:
        return _validate_secret_env(item.get("secret_env") or item.get("token_env"))

    def catalog_config_from_item(item: dict[str, Any]) -> dict[str, Any]:
        return {
            key: value
            for key, value in item.items()
            if key not in SOURCE_META_KEYS
            and key
            not in {
                "enabled",
                "channel",
                "category",
                "hub_channel",
                "topics",
                "tags",
                "personal_tags",
                "analysis_mode",
                "token_env",
                "secret_env",
            }
        }

    def catalog_config_for_source_type(source_type: str, item: dict[str, Any]) -> dict[str, Any]:
        config = catalog_config_from_item(item)
        if source_type == "telegram_channel" and item.get("channel"):
            config["channel"] = item["channel"]
        return config

    def can_update_catalog_source(source: dict[str, Any], user: dict[str, Any]) -> bool:
        if source["scope"] != "private":
            return _is_admin(user)
        return source["owner_user_id"] == user["id"]

    def default_source_scope(user: dict[str, Any]) -> str:
        if user.get("role") == "viewer":
            raise ApiError("forbidden", "viewer cannot create sources", status_code=403)
        return "public" if _is_admin(user) else "private"

    def validate_catalog_source_config(source_type: str, config: dict[str, Any]) -> tuple[dict[str, Any], str]:
        try:
            normalized = validate_source_config(source_type, config)
            return normalized, build_source_key(source_type, normalized)
        except SourceConfigError as exc:
            raise ApiError("invalid_source_config", str(exc), status_code=400) from exc

    async def resolve_catalog_source_config(
        source_type: str,
        config: dict[str, Any],
    ) -> tuple[str, dict[str, Any], str]:
        if source_type != YOUTUBE_CHANNEL_SETUP_TYPE:
            normalized, key = validate_catalog_source_config(source_type, config)
            return source_type, normalized, key
        try:
            normalized = await youtube_channels.resolve_config(config)
        except YouTubeChannelError as exc:
            raise ApiError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
                retryable=exc.retryable,
                action=exc.action,
            ) from exc
        return "rss", normalized, build_source_key("rss", normalized)

    def source_import_candidates(data: dict[str, Any]) -> list[dict[str, Any]]:
        sources = data.get("sources") or {}
        candidates: list[dict[str, Any]] = []

        def add(source_type: str, item: dict[str, Any], *, secret_env: str | None = None) -> None:
            config = catalog_config_for_source_type(source_type, item)
            try:
                normalized, key = validate_catalog_source_config(source_type, config)
                env_name = _validate_secret_env(secret_env or item.get("secret_env") or item.get("token_env"))
            except ApiError as exc:
                candidates.append(
                    {
                        "source_type": source_type,
                        "display_name": source_display_name(source_type, item),
                        "error": {"code": exc.code, "message": exc.message},
                    }
                )
                return
            candidates.append(
                {
                    "source_type": source_type,
                    "display_name": source_display_name(source_type, item),
                    "description": str(item.get("description") or ""),
                    "default_channel": source_default_channel(source_type, item),
                    "default_topics": source_topics(item),
                    "config": normalized,
                    "secret_env": env_name,
                    "enabled": bool(item.get("enabled", True)),
                    "source_key": key,
                }
            )

        for item in sources.get("rss") or []:
            if isinstance(item, dict):
                add("rss", item)

        for item in sources.get("github") or []:
            if not isinstance(item, dict):
                continue
            github_type = "github_user" if item.get("type") == "user_events" else "github_release"
            add(github_type, item)

        hackernews = sources.get("hackernews") or {}
        if isinstance(hackernews, dict) and hackernews.get("enabled"):
            add("hackernews", hackernews)

        reddit = sources.get("reddit") or {}
        if isinstance(reddit, dict):
            for item in reddit.get("subreddits") or []:
                if isinstance(item, dict):
                    add("reddit_subreddit", item)
            for item in reddit.get("users") or []:
                if isinstance(item, dict):
                    add("reddit_user", item)

        telegram = sources.get("telegram") or {}
        if isinstance(telegram, dict):
            for item in telegram.get("channels") or []:
                if isinstance(item, dict):
                    add("telegram_channel", item)

        apify = sources.get("apify_social") or {}
        if isinstance(apify, dict):
            default_secret = apify.get("token_env")
            for item in apify.get("subscriptions") or []:
                if isinstance(item, dict):
                    add("apify_social", item, secret_env=item.get("token_env") or default_secret)

        return candidates

    def import_config_sources(payload: ConfigImportSourcesRequest, user: dict[str, Any]) -> dict[str, Any]:
        base_data, _base_config = read_base_config()
        candidates = source_import_candidates(base_data)
        result: dict[str, Any] = {
            "dry_run": payload.dry_run,
            "created": 0,
            "updated": 0,
            "skipped": 0,
            "errors": [],
            "candidates": candidates,
        }
        if payload.dry_run:
            result["skipped"] = len([item for item in candidates if item.get("error")])
            result["errors"] = [item["error"] for item in candidates if item.get("error")]
            return result

        for candidate in candidates:
            if candidate.get("error"):
                result["skipped"] += 1
                result["errors"].append(candidate["error"])
                continue
            existing = store.get_source_by_key(
                workspace_id=user["workspace_id"],
                source_key=candidate["source_key"],
            )
            try:
                source = upsert_catalog_source(
                    user=user,
                    workspace_id=user["workspace_id"],
                    scope="public",
                    owner_user_id=user["id"],
                    source_type=candidate["source_type"],
                    display_name=candidate["display_name"],
                    description=candidate["description"],
                    default_channel=candidate["default_channel"],
                    default_topics=candidate["default_topics"],
                    config=candidate["config"],
                    source_key=candidate["source_key"],
                    secret_env=candidate["secret_env"],
                    enabled=candidate["enabled"],
                )
            except SourceKeyConflictError as exc:
                result["skipped"] += 1
                result["errors"].append(
                    {
                        "code": "source_key_conflict",
                        "message": str(exc),
                        "source_key": candidate["source_key"],
                    }
                )
                continue
            if existing:
                result["updated"] += 1
            else:
                result["created"] += 1
            if payload.subscribe_current_user and source:
                create_subscription_with_quota(
                    user=user,
                    source_id=source["id"],
                    enabled=True,
                )
        return result

    def apply_service_source_upsert(
        action: str,
        payload: dict[str, Any],
        user: dict[str, Any],
    ) -> dict[str, Any]:
        if user.get("role") == "viewer":
            raise ApiError("forbidden", "viewer cannot create or update sources", status_code=403)
        if not _is_admin(user) and any(
            str(payload.get(key) or "").strip()
            for key in ("secret_env", "token_env", "token_envs", "apify_token_env")
        ):
            raise ApiError(
                "forbidden",
                "only admins can assign a source secret",
                status_code=403,
            )
        base_data, _base_config = read_base_config()
        working_data = build_config_data_for_user(base_data, user)
        updated_working = apply_config_action(working_data, action, payload)
        item = source_item_for_upsert(updated_working, action, payload)

        source_type = SOURCE_UPSERT_ACTIONS[action]
        source_id = str(payload.get("source_id") or "").strip() or None
        source = visible_source_or_404(source_id, user) if source_id else None
        channel = source_default_channel(source_type, item)
        topics = source_topics(item)
        personal_tags = source_personal_tags(item)
        analysis_mode = str(item.get("analysis_mode") or "full")
        enabled = bool(item.get("enabled", True))
        secret_env = source_secret_env(item)
        normalized_config, key = validate_catalog_source_config(
            source_type,
            catalog_config_for_source_type(source_type, item),
        )
        mutable_source = True
        try:
            if source:
                mutable_source = can_update_catalog_source(source, user)
                if not mutable_source and source["scope"] == "private":
                    raise ApiError("forbidden", "cannot update another user's private source", status_code=403)
                if mutable_source:
                    updated_source = update_catalog_source(
                        source,
                        {
                            "display_name": source_display_name(source_type, item),
                            "default_channel": channel,
                            "default_topics": topics,
                            "config": normalized_config,
                            "source_key": key,
                            "secret_env": secret_env,
                            "enabled": True,
                        },
                        user=user,
                    )
                    source_id = updated_source["id"]
            else:
                updated_source = upsert_catalog_source(
                    user=user,
                    workspace_id=user["workspace_id"],
                    scope=default_source_scope(user),
                    owner_user_id=user["id"],
                    source_type=source_type,
                    display_name=source_display_name(source_type, item),
                    default_channel=channel,
                    default_topics=topics,
                    config=normalized_config,
                    source_key=key,
                    secret_env=secret_env,
                    enabled=True,
                )
                source_id = updated_source["id"]
        except SourceKeyConflictError as exc:
            raise ApiError(
                "source_key_conflict",
                str(exc),
                status_code=409,
                action="Use the existing visible source or choose a different source configuration.",
            ) from exc

        subscription = create_subscription_with_quota(
            user=user,
            source_id=source_id,
            enabled=enabled,
            override_channel=None if mutable_source else channel,
            override_topics=[] if mutable_source else topics,
            personal_tags=personal_tags,
            analysis_mode=analysis_mode,
        )
        if _is_admin(user):
            base_data["tags"] = updated_working.get("tags", base_data.get("tags", []))
            base_data["personal_tags"] = updated_working.get(
                "personal_tags",
                base_data.get("personal_tags", []),
            )
            write_base_config(base_data)
        return subscription

    def apply_service_source_delete(payload: dict[str, Any], user: dict[str, Any]) -> None:
        source_id = str(payload.get("source_id") or "").strip()
        if not source_id:
            raise ApiError("source_id_required", "source_id is required for service source deletion", status_code=400)
        source = visible_source_or_404(source_id, user)
        if source["scope"] != "private" and not _is_admin(user):
            subscription_id = str(payload.get("subscription_id") or "").strip()
            if subscription_id:
                subscription = store.get_subscription(subscription_id)
                if subscription and subscription.get("user_id") == user["id"]:
                    subscription_mutations.rest_delete_subscription(
                        SubscriptionActor.from_user(user),
                        subscription_id=subscription_id,
                    )
                return
            for subscription in store.list_user_subscriptions(user["id"]):
                if subscription["source_id"] == source_id:
                    subscription_mutations.rest_delete_subscription(
                        SubscriptionActor.from_user(user),
                        subscription_id=subscription["id"],
                    )
                    return
            return
        if source["scope"] == "private" and source["owner_user_id"] != user["id"]:
            raise ApiError("forbidden", "cannot delete another user's private source", status_code=403)
        subscription_mutations.rest_update_source(
            SubscriptionActor.from_user(user),
            source_id=source_id,
            updates={"enabled": False},
        )

    def compatibility_job_payload(raw_payload: dict[str, Any]) -> JobCreateRequest:
        source_id = str(raw_payload.get("source_id") or "").strip() or None
        subscription_id = str(raw_payload.get("subscription_id") or "").strip() or None
        priority = int(raw_payload.get("priority") or 0)
        payload = {
            key: value
            for key, value in raw_payload.items()
            if key not in {"source_id", "subscription_id", "priority"}
        }
        return JobCreateRequest(
            source_id=source_id,
            subscription_id=subscription_id,
            payload=payload,
            priority=priority,
        )

    def queued_job_response(job: dict[str, Any], message: str) -> dict[str, Any]:
        return {**job, "message": message}

    def job_or_404(job_id: str, user: dict[str, Any]) -> dict[str, Any]:
        job = queue.get_job(job_id)
        if not job or job["workspace_id"] != user["workspace_id"]:
            raise ApiError("not_found", "job not found", status_code=404)
        if job["user_id"] != user["id"] and not _is_admin(user):
            raise ApiError("forbidden", "cannot access another user's job", status_code=403)
        return job

    def visible_item_or_404(article_id: str, user: dict[str, Any]) -> None:
        if not item_state.is_visible(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            article_id=article_id,
        ):
            raise ApiError("not_found", "item not found", status_code=404)

    def target_user_for_scope(requested_user_id: str | None, user: dict[str, Any]) -> dict[str, Any]:
        if not requested_user_id or requested_user_id == user["id"]:
            return user
        if not _is_admin(user):
            raise ApiError(
                "forbidden",
                "current user cannot inspect another user's feed or archive",
                status_code=403,
                action="Use your own user scope or ask an admin.",
            )
        target = store.get_user(requested_user_id)
        if not target or target["workspace_id"] != user["workspace_id"]:
            raise ApiError("not_found", "target user not found", status_code=404)
        return target

    def validate_archive_params(
        *,
        date_from: str | None = None,
        date_to: str | None = None,
        sort: str = "published_at",
        order: str = "desc",
        group_by: str | None = None,
        bucket: str = "none",
    ) -> None:
        if sort not in {"published_at", "score", "source", "channel", "id"}:
            raise ApiError("invalid_sort", "sort must be published_at, score, source, channel, or id", status_code=400)
        if order not in {"asc", "desc"}:
            raise ApiError("invalid_order", "order must be asc or desc", status_code=400)
        if date_from and date_to and date_from > date_to:
            raise ApiError("invalid_date_range", "date_from must be before date_to", status_code=400)
        if group_by is not None and group_by not in {"channel", "topic", "entity", "source"}:
            raise ApiError("invalid_group_by", "group_by must be channel, topic, entity, or source", status_code=400)
        if bucket not in {"none", "day", "week"}:
            raise ApiError("invalid_bucket", "bucket must be none, day, or week", status_code=400)

    @app.get("/api/auth/status")
    async def auth_status(request: Request) -> dict[str, Any]:
        user = store.get_session_user(request.cookies.get(COOKIE_NAME))
        return ok(
            {
                "authenticated": bool(user),
                "user": _sanitize_user(user) if user else None,
            }
        )

    @app.get("/api/health/live")
    async def health_live() -> dict[str, Any]:
        return ok(
            {
                "status": "live",
                "version": os.getenv("INTELISCOPE_VERSION", "1.5.0"),
                "revision": os.getenv("INTELISCOPE_BUILD_REVISION", "unknown"),
                "built_at": os.getenv("INTELISCOPE_BUILT_AT", "unknown"),
            }
        )

    @app.get("/api/health/ready")
    async def health_ready() -> dict[str, Any]:
        store.connect().execute("SELECT 1").fetchone()
        if store.feed_v2_migration_required():
            raise ApiError(
                "migration_required",
                "user feed v2 migration must be applied before feed jobs can run",
                status_code=503,
                action="Stop services and run the explicit feed v2 migration command.",
            )
        if store.content_index_v4_migration_required():
            raise ApiError(
                "migration_required",
                "user content v4 migration must be applied before feed jobs can run",
                status_code=503,
                action="Stop services and run scripts/migrate_user_content_v4.py --apply.",
            )
        if store.content_timeline_v11_migration_required():
            raise ApiError(
                "migration_required",
                "content timeline v11 migration must be applied before feed reads or jobs can run",
                status_code=503,
                action=(
                    "Stop services and run "
                    "scripts/migrate_content_timeline_v11.py --apply."
                ),
            )
        if not store.has_enabled_user():
            raise ApiError(
                "auth_not_configured",
                "no enabled service user is configured",
                status_code=503,
                action=(
                    "Set HORIZON_AUTH_PASSWORD or HORIZON_AUTH_PASSWORD_HASH, "
                    "then restart horizon-api."
                ),
            )
        summary = runtime_status.summary(workspace_id=store.get_default_workspace()["id"])
        require_worker = os.getenv("HORIZON_REQUIRE_WORKER_FOR_READINESS", "false").lower() == "true"
        if require_worker and summary["worker_status"] != "ready":
            raise ApiError(
                "worker_unavailable",
                f"worker status is {summary['worker_status']}",
                status_code=503,
                retryable=True,
                action="Start or inspect horizon-worker.",
            )
        return ok(
            {
                "status": "ready",
                "database": "ready",
                "worker_status": summary["worker_status"],
                "checked_at": summary["checked_at"],
            }
        )

    @app.post("/api/auth/login")
    async def auth_login(
        payload: LoginRequest,
        request: Request,
        response: Response,
    ) -> dict[str, Any]:
        user = store.authenticate_user(payload.username, payload.password)
        if not user:
            raise ApiError("invalid_credentials", "username or password is incorrect", status_code=401)
        bind_operation_actor(
            workspace_id=str(user["workspace_id"]),
            user_id=str(user["id"]),
        )
        request.state.operation_workspace_id = str(user["workspace_id"])
        request.state.operation_actor_user_id = str(user["id"])
        token = store.create_session(
            user["id"],
            ttl_seconds=auth_settings.session_ttl_seconds,
        )
        response.set_cookie(
            COOKIE_NAME,
            token,
            httponly=True,
            samesite="lax",
            secure=auth_settings.cookie_secure,
            max_age=auth_settings.session_ttl_seconds,
        )
        return ok({"authenticated": True, "user": _sanitize_user(user)})

    @app.post("/api/auth/logout")
    async def auth_logout(request: Request, response: Response) -> dict[str, Any]:
        session_token = request.cookies.get(COOKIE_NAME)
        user = store.get_session_user(session_token)
        if user is not None:
            bind_operation_actor(
                workspace_id=str(user["workspace_id"]),
                user_id=str(user["id"]),
            )
            request.state.operation_workspace_id = str(user["workspace_id"])
            request.state.operation_actor_user_id = str(user["id"])
        store.delete_session(session_token)
        response.delete_cookie(
            COOKIE_NAME,
            httponly=True,
            samesite="lax",
            secure=auth_settings.cookie_secure,
        )
        return ok({"authenticated": False, "user": None})

    @app.post("/api/me/password")
    async def me_password_change(
        payload: PasswordChangeRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        authenticated = store.authenticate_user(user["username"], payload.current_password)
        if authenticated is None or authenticated["id"] != user["id"]:
            raise ApiError(
                "invalid_current_password",
                "current password is incorrect",
                status_code=400,
            )
        store.update_user(user["id"], password=payload.new_password)
        request.state.operation_changed_fields = ["password"]
        return ok({"changed": True})

    @app.get("/api/me/notification-settings")
    async def notification_settings_get(
        response: Response,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return ok(
            preferred_source_notifications.get_public_settings(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
            )
        )

    @app.patch("/api/me/notification-settings")
    async def notification_settings_patch(
        payload: NotificationSettingsPatchRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        provided = payload.model_fields_set
        if not provided:
            raise ApiError(
                "invalid_notification_settings",
                "at least one notification setting is required",
                status_code=400,
            )
        if (
            ("enabled" in provided and payload.enabled is None)
            or ("channel" in provided and payload.channel is None)
        ):
            raise ApiError(
                "invalid_notification_settings",
                "enabled and channel cannot be null",
                status_code=400,
            )
        updates = {
            field: getattr(payload, field)
            for field in (
                "enabled",
                "channel",
                "email_address",
                "webhook_url",
            )
            if field in provided
        }
        updated = preferred_source_notifications.upsert_settings(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            **updates,
        )
        request.state.operation_changed_fields = sorted(provided)
        response.headers["Cache-Control"] = "no-store"
        return ok(updated)

    @app.post("/api/me/notification-settings/test")
    async def notification_settings_test(
        response: Response,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        result = await run_in_threadpool(
            preferred_source_notifications.send_test,
            workspace_id=user["workspace_id"],
            user_id=user["id"],
        )
        response.headers["Cache-Control"] = "no-store"
        return ok(result)

    @app.get("/api/config")
    async def config_get(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return ok(config_response(user))

    @app.post("/api/config/action")
    async def config_action(
        request_payload: ConfigActionRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        action = request_payload.action
        payload = request_payload.payload
        if action in SOURCE_UPSERT_ACTIONS:
            apply_service_source_upsert(action, payload, user)
            return ok(config_response(user))
        if action in SOURCE_DELETE_ACTIONS:
            apply_service_source_delete(payload, user)
            return ok(config_response(user))
        if not _is_admin(user):
            raise ApiError("forbidden", "admin role required", status_code=403)

        base_data, _base_config = read_base_config()
        updated = apply_config_action(base_data, action, payload)
        write_base_config(updated)
        return ok(config_response(user))

    @app.get("/api/users")
    async def users_list(user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        users = store.list_users(workspace_id=user["workspace_id"])
        return ok({"users": [_sanitize_user(item) for item in users]})

    @app.post("/api/users")
    async def users_create(
        payload: UserCreateRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        if payload.role not in ROLES:
            raise ApiError("invalid_role", "role must be owner, admin, member, or viewer")
        created = store.create_user(
            workspace_id=user["workspace_id"],
            username=payload.username,
            password=payload.password,
            role=payload.role,
            display_name=payload.display_name,
            enabled=payload.enabled,
        )
        request.state.operation_subject_user_id = str(created["id"])
        request.state.operation_changed_fields = [
            "display_name",
            "enabled",
            "password",
            "role",
            "username",
        ]
        return ok(_sanitize_user(created))

    @app.patch("/api/users/{user_id}")
    async def users_patch(
        user_id: str,
        payload: UserPatchRequest,
        request: Request,
        _admin: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        if payload.role is not None and payload.role not in ROLES:
            raise ApiError("invalid_role", "role must be owner, admin, member, or viewer", status_code=400)
        updated = store.update_user(
            user_id,
            role=payload.role,
            enabled=payload.enabled,
            display_name=payload.display_name,
            password=payload.password.strip() if payload.password and payload.password.strip() else None,
        )
        request.state.operation_changed_fields = sorted(payload.model_fields_set)
        return ok(_sanitize_user(updated))

    @app.get("/api/catalog/sources")
    async def catalog_sources(
        include_disabled: bool = False,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if include_disabled and not _is_admin(user):
            raise ApiError(
                "forbidden",
                "admin role required to list disabled sources",
                status_code=403,
            )
        return ok(
            {
                "sources": visible_sources(
                    user,
                    include_disabled=include_disabled,
                )
            }
        )

    @app.get("/api/admin/storage/summary")
    async def admin_storage_summary(
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return ok(
            await run_in_threadpool(
                storage_governance.summary,
                workspace_id=str(user["workspace_id"]),
            )
        )

    @app.post("/api/admin/storage/plans")
    async def admin_storage_plan_create(
        payload: StoragePlanRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        plan = await run_in_threadpool(
            storage_governance.create_plan,
            workspace_id=str(user["workspace_id"]),
            actor_user_id=str(user["id"]),
            actor_role=str(user["role"]),
            operation=payload.operation,
            payload=payload.payload,
        )
        request.state.operation_changed_fields = ["operation", "preview"]
        response.headers["Cache-Control"] = "no-store"
        return ok(plan)

    @app.post("/api/admin/storage/plans/{plan_id}/apply")
    async def admin_storage_plan_apply(
        plan_id: str,
        payload: StoragePlanApplyRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        plan = await run_in_threadpool(
            storage_governance.apply_plan,
            workspace_id=str(user["workspace_id"]),
            actor_user_id=str(user["id"]),
            actor_role=str(user["role"]),
            plan_id=plan_id,
            confirmation=payload.confirmation,
        )
        request.state.operation_changed_fields = [
            str(plan.get("operation") or "storage"),
            "apply",
        ]
        response.headers["Cache-Control"] = "no-store"
        return ok(plan)

    @app.get("/api/admin/storage/archives")
    async def admin_storage_archives(
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return ok(
            await run_in_threadpool(
                storage_governance.list_archives,
                workspace_id=str(user["workspace_id"]),
            )
        )

    @app.get("/api/admin/secrets")
    async def admin_secrets_list(
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        secret_values.load_into_environ()
        secrets = store.list_secret_refs(workspace_id=user["workspace_id"])
        return ok({"secrets": [public_secret(secret) for secret in secrets]})

    @app.get("/api/admin/notification-email-transport")
    async def admin_notification_email_transport_get(
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        response.headers["Cache-Control"] = "no-store"
        return ok(
            workspace_email_transport.get_public_settings(
                workspace_id=str(user["workspace_id"]),
            )
        )

    @app.patch("/api/admin/notification-email-transport")
    async def admin_notification_email_transport_patch(
        payload: NotificationEmailTransportPatchRequest,
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        provided = payload.model_fields_set
        if not provided:
            raise ApiError(
                "invalid_email_transport",
                "at least one email transport setting is required",
                status_code=400,
            )
        required_when_provided = {
            "provider",
            "sender_email",
            "sender_name",
            "enabled",
        }
        if any(
            field in provided and getattr(payload, field) is None
            for field in required_when_provided
        ):
            raise ApiError(
                "invalid_email_transport",
                "provider, sender_email, sender_name, and enabled cannot be null",
                status_code=400,
            )
        updates = {
            field: getattr(payload, field)
            for field in (
                "provider",
                "sender_email",
                "sender_name",
                "credential",
                "enabled",
                "region",
                "smtp_username",
            )
            if field in provided
        }
        updated = workspace_email_transport.upsert(
            workspace_id=str(user["workspace_id"]),
            actor_user_id=str(user["id"]),
            **updates,
        )
        request.state.operation_changed_fields = sorted(provided)
        response.headers["Cache-Control"] = "no-store"
        return ok(updated)

    @app.delete("/api/admin/notification-email-transport")
    async def admin_notification_email_transport_delete(
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        deleted = workspace_email_transport.delete(
            workspace_id=str(user["workspace_id"]),
            actor_user_id=str(user["id"]),
        )
        response.headers["Cache-Control"] = "no-store"
        return ok({"deleted": deleted})

    @app.post("/api/admin/notification-email-transport/test")
    async def admin_notification_email_transport_test(
        payload: NotificationEmailTransportTestRequest,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        result = await run_in_threadpool(
            workspace_email_transport.send_test,
            workspace_id=str(user["workspace_id"]),
            actor_user_id=str(user["id"]),
            recipient_email=payload.recipient_email,
        )
        response.headers["Cache-Control"] = "no-store"
        return ok(result)

    @app.get("/api/admin/apify-key-pool")
    async def admin_apify_key_pool(
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        return ok(apify_key_pool.public_state(str(user["workspace_id"])))

    @app.put("/api/admin/apify-key-pool/order")
    async def admin_apify_key_pool_order(
        payload: ApifyKeyPoolOrderRequest,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        try:
            state = apify_key_pool.reorder(
                str(user["workspace_id"]),
                expected_generation=int(payload.expected_generation),
                secret_ids=payload.secret_ids,
            )
        except ValueError as exc:
            raise ApiError(
                "invalid_request",
                "secret_ids must contain every pool member exactly once",
                status_code=400,
            ) from exc
        except ApifyKeyPoolError as exc:
            raise pool_api_error(exc) from exc
        return ok(state)

    @app.post("/api/admin/apify-key-pool/{secret_id}/drain")
    async def admin_apify_key_pool_drain(
        secret_id: str,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        state = apify_key_pool.public_state(str(user["workspace_id"]))
        if secret_id not in {
            str(member["secret_id"]) for member in state["members"]
        }:
            raise ApiError("not_found", "Apify Key pool member not found", status_code=404)
        try:
            state = apify_key_pool.begin_drain(secret_id)
            if state["status"] == "draining":
                try:
                    state = apify_key_pool.complete_drain_and_failover(
                        str(user["workspace_id"])
                    )
                except ApifyKeyDrainPendingError:
                    state = apify_key_pool.public_state(str(user["workspace_id"]))
        except ApifyKeyPoolError as exc:
            raise pool_api_error(exc) from exc
        return ok(state)

    @app.post("/api/admin/secrets")
    async def admin_secrets_create(
        payload: SecretCreateRequest,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        name, kind, provider, env_name = validate_secret_metadata(payload)
        if store.get_secret_ref_by_env(workspace_id=user["workspace_id"], env_name=env_name):
            raise ApiError(
                "secret_env_conflict",
                "the environment name is already registered",
                status_code=409,
            )
        secret: dict[str, Any] | None = None
        try:
            secret_values.set(env_name, payload.value)
            secret_values.load_into_environ()
            secret = store.create_secret_ref(
                workspace_id=user["workspace_id"],
                owner_user_id=user["id"],
                name=name,
                env_name=env_name,
                kind=kind,
                provider=provider,
                scope="workspace",
            )
            if kind == "apify" and provider == "apify":
                apify_key_pool.append_secret(secret["id"])
        except SecretEnvConflictError as exc:
            secret_values.delete(env_name)
            secret_values.load_into_environ()
            raise ApiError(
                "secret_env_conflict",
                "the environment name is already registered",
                status_code=409,
            ) from exc
        except ApifyKeyPoolError as exc:
            if secret is not None:
                store.delete_secret_ref(str(secret["id"]))
            secret_values.delete(env_name)
            secret_values.load_into_environ()
            raise pool_api_error(exc) from exc
        except SecretValueError as exc:
            raise ApiError("invalid_secret", str(exc), status_code=400) from exc
        except Exception:
            if secret is not None:
                store.delete_secret_ref(str(secret["id"]))
            secret_values.delete(env_name)
            secret_values.load_into_environ()
            raise
        return ok(public_secret(secret))

    @app.put("/api/admin/secrets/{secret_id}/value")
    async def admin_secrets_rotate(
        secret_id: str,
        payload: SecretRotateRequest,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        secret = store.get_secret_ref(secret_id)
        if secret is None or secret["workspace_id"] != user["workspace_id"]:
            raise ApiError("not_found", "secret reference not found", status_code=404)
        apify_lifecycle: dict[str, Any] | None = None
        if is_apify_secret(secret):
            apify_lifecycle = apify_key_pool.secret_lifecycle(secret_id)
            try:
                if apify_key_pool_enabled():
                    apify_key_pool.ensure_secret_mutable(secret_id)
                elif (
                    apify_lifecycle["managed"]
                    and (
                        int(apify_lifecycle["active_run_count"]) > 0
                        or apify_lifecycle["status"] == "draining"
                    )
                ):
                    raise ApifyKeyBusyError()
            except ApifyKeyPoolError as exc:
                raise pool_api_error(exc) from exc
        try:
            secret_values.set(secret["env_name"], payload.value)
            secret_values.load_into_environ()
        except SecretValueError as exc:
            raise ApiError("invalid_secret", str(exc), status_code=400) from exc
        updated = store.touch_secret_ref(secret_id)
        if is_apify_secret(secret):
            if apify_lifecycle and apify_lifecycle["managed"]:
                try:
                    apify_key_pool.mark_secret_rotated(secret_id)
                except ApifyKeyPoolError as exc:
                    raise pool_api_error(exc) from exc
            for source in store.list_sources_using_secret(
                workspace_id=user["workspace_id"],
                env_name=secret["env_name"],
            ):
                source_health.reset_source(
                    workspace_id=user["workspace_id"],
                    source_id=source["id"],
                )
        return ok(public_secret(updated))

    @app.get("/api/admin/secrets/{secret_id}/quota")
    async def admin_secrets_quota(
        secret_id: str,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        secret = store.get_secret_ref(secret_id)
        if secret is None or secret["workspace_id"] != user["workspace_id"]:
            raise ApiError("not_found", "secret reference not found", status_code=404)
        if not is_apify_secret(secret):
            raise ApiError(
                "quota_not_supported",
                "该 Provider 暂不支持额度查询。",
                status_code=400,
            )
        token = secret_values.read().get(secret["env_name"], "").strip()
        if not token:
            raise ApiError(
                "secret_not_configured",
                "该 Key 尚未配置真实值，无法查询额度。",
                status_code=409,
                action="请先轮换并保存有效的 Apify Token。",
            )
        try:
            quota_data = await secret_quota.fetch(secret_id=secret_id, token=token)
        except SecretQuotaError as exc:
            raise ApiError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
                retryable=exc.retryable,
                action=exc.action,
            ) from exc
        lifecycle = apify_key_pool.secret_lifecycle(secret_id)
        if lifecycle["managed"]:
            apify_key_pool.record_member_quota(
                workspace_id=str(user["workspace_id"]),
                secret_id=secret_id,
                remaining_included_credits_usd=float(
                    quota_data["remaining_included_credits_usd"]
                ),
                checked_at=str(quota_data["checked_at"]),
                cycle_start_at=str(quota_data["cycle_start_at"]),
                cycle_end_at=str(quota_data["cycle_end_at"]),
                monthly_included_credits_usd=float(
                    quota_data["monthly_included_credits_usd"]
                ),
                monthly_usage_usd=float(quota_data["monthly_usage_usd"]),
                max_monthly_usage_usd=float(
                    quota_data["max_monthly_usage_usd"]
                ),
                remaining_hard_limit_usd=float(
                    quota_data["remaining_hard_limit_usd"]
                ),
            )
        return ok(quota_data)

    @app.delete("/api/admin/secrets/{secret_id}")
    async def admin_secrets_delete(
        secret_id: str,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        secret = store.get_secret_ref(secret_id)
        if secret is None or secret["workspace_id"] != user["workspace_id"]:
            raise ApiError("not_found", "secret reference not found", status_code=404)
        if secret_usage(secret):
            raise ApiError(
                "secret_in_use",
                "secret is still referenced by AI or a catalog source",
                status_code=409,
                action="Reassign every reference before deleting this secret.",
            )
        if is_apify_secret(secret):
            try:
                lifecycle = apify_key_pool.secret_lifecycle(secret_id)
                if lifecycle["managed"]:
                    if apify_key_pool_enabled():
                        apify_key_pool.ensure_secret_mutable(secret_id)
                    elif lifecycle["busy"]:
                        if int(lifecycle["active_run_count"]) > 0:
                            raise ApifyKeyBusyError()
                        apify_key_pool.begin_drain(secret_id)
                        apify_key_pool.complete_drain_and_failover(
                            str(user["workspace_id"])
                        )
                    apify_key_pool.remove_secret(secret_id)
            except ApifyKeyPoolError as exc:
                raise pool_api_error(exc) from exc
        secret_values.delete(secret["env_name"])
        secret_values.load_into_environ()
        store.delete_secret_ref(secret_id)
        return ok({"deleted": True, "id": secret_id})

    @app.get("/api/catalog/source-types")
    async def catalog_source_types(_user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return ok({"source_types": list_source_setup_types()})

    @app.post("/api/catalog/import-config-sources")
    async def catalog_import_config_sources(
        payload: ConfigImportSourcesRequest,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        return ok(import_config_sources(payload, user))

    @app.post("/api/catalog/sources")
    async def catalog_create(
        payload: SourceCreateRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        reject_pool_managed_source_secret(
            payload.type,
            supplied="secret_env" in payload.model_fields_set,
        )
        if payload.secret_env is not None and not _is_admin(user):
            raise ApiError(
                "forbidden",
                "only admins can assign a source secret",
                status_code=403,
            )
        scope = payload.scope or default_source_scope(user)
        if scope not in SOURCE_SCOPES:
            raise ApiError("invalid_scope", "scope must be public, workspace, or private")
        if scope != "private" and not _is_admin(user):
            raise ApiError("forbidden", "only admins can create public or workspace sources", status_code=403)
        if (
            payload.type == YOUTUBE_CHANNEL_SETUP_TYPE
            and payload.secret_env is not None
        ):
            raise ApiError(
                "invalid_source_config",
                "YouTube channel subscriptions do not accept credentials.",
                status_code=400,
            )
        catalog_type, normalized_config, key = await resolve_catalog_source_config(
            payload.type,
            payload.config,
        )
        enforce_public_network = (
            catalog_source_setup_type(catalog_type, normalized_config)
            == YOUTUBE_CHANNEL_SETUP_TYPE
        )
        try:
            source = upsert_catalog_source(
                user=user,
                workspace_id=user["workspace_id"],
                scope=scope,
                owner_user_id=user["id"],
                source_type=catalog_type,
                display_name=payload.display_name,
                description=payload.description,
                default_channel=payload.default_channel,
                default_topics=payload.default_topics,
                config=normalized_config,
                source_key=key,
                secret_env=_validate_secret_env(payload.secret_env),
                enforce_public_network=enforce_public_network,
                enabled=payload.enabled,
            )
        except SourceKeyConflictError as exc:
            raise ApiError(
                "source_key_conflict",
                str(exc),
                status_code=409,
                action="Use the existing visible source or choose a different source configuration.",
            ) from exc
        request.state.operation_source_id = str(source["id"])
        request.state.operation_changed_fields = sorted(payload.model_fields_set)
        return ok(public_source(source, user))

    @app.patch("/api/catalog/sources/{source_id}")
    async def catalog_patch(
        source_id: str,
        payload: SourcePatchRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        source = manageable_source_or_404(source_id, user)
        reject_pool_managed_source_secret(
            str(source["type"]),
            supplied="secret_env" in payload.model_fields_set,
        )
        if "secret_env" in payload.model_fields_set and not _is_admin(user):
            raise ApiError(
                "forbidden",
                "only admins can assign a source secret",
                status_code=403,
            )
        if source["scope"] != "private" and not _is_admin(user):
            raise ApiError("forbidden", "only admins can update shared sources", status_code=403)
        if source["scope"] == "private" and source["owner_user_id"] != user["id"]:
            raise ApiError("forbidden", "cannot update another user's private source", status_code=403)
        provided = payload.model_fields_set
        setup_type = catalog_source_setup_type(
            str(source["type"]),
            source.get("config"),
        )
        if (
            "secret_env" in provided
            and setup_type == YOUTUBE_CHANNEL_SETUP_TYPE
            and payload.secret_env is not None
        ):
            raise ApiError(
                "invalid_source_config",
                "YouTube channel subscriptions do not accept credentials.",
                status_code=400,
            )
        updates: dict[str, Any] = {}
        if "display_name" in provided:
            updates["display_name"] = payload.display_name
        if "description" in provided:
            updates["description"] = payload.description
        if "default_channel" in provided:
            updates["default_channel"] = payload.default_channel
        if "default_topics" in provided and payload.default_topics is not None:
            updates["default_topics"] = payload.default_topics
        if "config" in provided and payload.config is not None:
            catalog_type, normalized_config, key = await resolve_catalog_source_config(
                setup_type,
                payload.config,
            )
            if catalog_type != source["type"]:
                raise ApiError(
                    "invalid_source_config",
                    "source storage type cannot be changed",
                    status_code=400,
                )
            updates["config"] = normalized_config
            updates["source_key"] = key
            if (
                source["type"] == "rss"
                and catalog_source_setup_type(catalog_type, normalized_config)
                == YOUTUBE_CHANNEL_SETUP_TYPE
            ):
                updates["enforce_public_network"] = True
        if "secret_env" in provided:
            updates["secret_env"] = _validate_secret_env(payload.secret_env)
        if "enabled" in provided:
            updates["enabled"] = payload.enabled
        try:
            updated = update_catalog_source(source, updates, user=user)
        except SourceKeyConflictError as exc:
            raise ApiError(
                "source_key_conflict",
                str(exc),
                status_code=409,
                action="Keep the current source configuration or choose a different source.",
            ) from exc
        request.state.operation_changed_fields = sorted(provided)
        return ok(public_source(updated, user))

    @app.get("/api/catalog/sources/{source_id}/usage")
    async def catalog_source_usage(
        source_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        visible_source_or_404(source_id, user)
        return ok({"source_id": source_id, **store.source_subscription_usage(source_id)})

    @app.post("/api/catalog/sources/{source_id}/share")
    async def catalog_source_share(
        source_id: str,
        payload: SourceShareRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        shared = subscription_mutations.rest_share_source(
            SubscriptionActor.from_user(user),
            source_id=source_id,
            target_scope=payload.scope,
        )
        request.state.operation_changed_fields = ["scope"]
        return ok(
            {
                "source": public_source(shared, user),
                "management_transferred": True,
                "notice": "来源地址和管理权已转交工作区管理员；你的取消订阅不会影响其他成员。",
            }
        )

    @app.delete("/api/catalog/sources/{source_id}")
    async def catalog_delete(
        source_id: str,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        source = manageable_source_or_404(source_id, user)
        if source["scope"] != "private" and not _is_admin(user):
            raise ApiError("forbidden", "only admins can delete shared sources", status_code=403)
        if source["scope"] == "private" and source["owner_user_id"] != user["id"]:
            raise ApiError("forbidden", "cannot delete another user's private source", status_code=403)
        updated = subscription_mutations.rest_update_source(
            SubscriptionActor.from_user(user),
            source_id=source_id,
            updates={"enabled": False},
        )
        internal_safe = dict(updated)
        internal_safe.pop("enforce_public_network", None)
        request.state.operation_changed_fields = ["enabled"]
        return ok(internal_safe)

    @app.post("/api/catalog/sources/{source_id}/subscribe")
    async def catalog_subscribe(
        source_id: str,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        visible_source_or_404(source_id, user)
        subscription = create_subscription_with_quota(
            user=user,
            source_id=source_id,
        )
        request.state.operation_subscription_id = str(subscription["id"])
        return ok({"subscription": subscription})

    @app.delete("/api/catalog/sources/{source_id}/subscription")
    async def catalog_unsubscribe(
        source_id: str,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        visible_source_or_404(source_id, user)
        subscription = store.get_user_subscription_for_source(user["id"], source_id)
        if not subscription:
            raise ApiError("not_found", "subscription not found", status_code=404)
        request.state.operation_subscription_id = str(subscription["id"])
        return ok(
            {
                "deleted": subscription_mutations.rest_delete_subscription(
                    SubscriptionActor.from_user(user),
                    subscription_id=subscription["id"],
                )
            }
        )

    @app.get("/api/me/subscriptions")
    async def subscriptions_list(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        subscriptions = store.list_user_subscriptions(user["id"])
        return ok(
            {
                "subscriptions": [
                    {
                        **subscription,
                        "schedule": source_schedule_response(user, subscription["id"]),
                    }
                    for subscription in subscriptions
                ]
            }
        )

    @app.get("/api/me/agent-delegations")
    async def agent_delegations_list(
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return ok(
            {
                "enabled": remote_mcp_settings.enabled,
                "mcp_url": remote_mcp_settings.public_url,
                "subscription_writes_enabled": (
                    remote_mcp_settings.subscription_writes_enabled
                ),
                "openclaw_chat": openclaw_chat_settings.public_config(),
                "token_ttl_days": AGENT_DELEGATION_TTL_DAYS,
                "max_active": AGENT_DELEGATION_MAX_ACTIVE,
                "connections": store.list_agent_delegations(user["id"]),
            }
        )

    @app.post("/api/me/agent-delegations", status_code=201)
    async def agent_delegations_create(
        payload: AgentDelegationRequest,
        response: Response,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if not remote_mcp_settings.enabled:
            raise ApiError(
                "remote_mcp_disabled",
                "Remote MCP is disabled",
                status_code=409,
                action="Ask an administrator to enable Remote MCP.",
            )
        if payload.access == "subscriptions_write":
            if user.get("role") == "viewer":
                raise ApiError(
                    "forbidden",
                    "viewer users cannot create subscription write connections",
                    status_code=403,
                )
            if not remote_mcp_settings.subscription_writes_enabled:
                raise ApiError(
                    "subscription_writes_disabled",
                    "subscription writes are disabled",
                    status_code=409,
                    action="Ask an administrator to enable subscription writes.",
                )
        try:
            connection, token = store.create_agent_delegation(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                name=payload.name,
                access=payload.access,
            )
        except AgentDelegationLimitError as exc:
            raise ApiError(
                "agent_delegation_limit",
                str(exc),
                status_code=409,
                action="Revoke an unused connection before creating another.",
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        return ok({"connection": connection, "token": token})

    @app.patch("/api/me/agent-delegations/{delegation_id}")
    async def agent_delegations_patch(
        delegation_id: str,
        payload: AgentDelegationRenameRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        connection = store.rename_agent_delegation(
            user["id"], delegation_id, payload.name
        )
        if connection is None:
            raise ApiError("not_found", "connection not found", status_code=404)
        return ok(connection)

    @app.delete("/api/me/agent-delegations/{delegation_id}")
    async def agent_delegations_delete(
        delegation_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if not store.revoke_agent_delegation(user["id"], delegation_id):
            raise ApiError("not_found", "connection not found", status_code=404)
        return ok({"revoked": True})

    @app.delete("/api/me/agent-delegations/{delegation_id}/record")
    async def agent_delegations_record_delete(
        delegation_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        deleted = store.delete_revoked_agent_delegation(user["id"], delegation_id)
        if deleted is None:
            raise ApiError("not_found", "connection not found", status_code=404)
        if deleted is False:
            raise ApiError(
                "agent_delegation_not_revoked",
                "connection must be revoked before deletion",
                status_code=409,
            )
        return ok({"deleted": True})

    @app.get("/api/me/source-health")
    async def source_health_get(
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return ok(
            source_health.user_projection(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                feed_window_days=current_feed_window_days(),
            )
        )

    @app.get("/api/me/feed-schedule")
    async def feed_schedule_get(
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return ok(feed_schedule_response(user))

    @app.patch("/api/me/feed-schedule")
    async def feed_schedule_patch(
        payload: FeedSchedulePatchRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        if payload.enabled is None and payload.interval_minutes is None:
            raise ApiError(
                "invalid_feed_schedule",
                "enabled or interval_minutes is required",
                status_code=400,
            )
        if (
            payload.interval_minutes is not None
            and payload.interval_minutes not in ALLOWED_INTERVALS
        ):
            raise ApiError(
                "invalid_feed_schedule",
                "interval_minutes must be one of "
                + ", ".join(str(value) for value in ALLOWED_INTERVALS),
                status_code=400,
            )
        try:
            feed_schedules.update_user_schedule(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                enabled=payload.enabled,
                interval_minutes=payload.interval_minutes,
            )
        except NoEnabledSubscriptionsError as exc:
            raise ApiError(
                exc.code,
                str(exc),
                status_code=409,
                action="Enable at least one subscription and retry.",
            ) from exc
        except ValueError as exc:
            raise ApiError(
                "invalid_feed_schedule",
                str(exc),
                status_code=400,
            ) from exc
        request.state.operation_changed_fields = sorted(payload.model_fields_set)
        return ok(feed_schedule_response(user))

    @app.post("/api/me/subscriptions")
    async def subscriptions_create(
        payload: SubscriptionRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        if payload.notify_on_new_items and (
            payload.analysis_mode == "personal_only" or not payload.enabled
        ):
            raise ApiError(
                "invalid_subscription_notification",
                "disabled or personal_only subscriptions cannot send new-item notifications",
                status_code=400,
                action="Enable the subscription in full analysis mode or leave notifications disabled.",
            )
        visible_source_or_404(payload.source_id, user)
        notification_values = (
            {"notify_on_new_items": payload.notify_on_new_items}
            if "notify_on_new_items" in payload.model_fields_set
            else {}
        )
        subscription = create_subscription_with_quota(
            user=user,
            source_id=payload.source_id,
            enabled=payload.enabled,
            override_channel=payload.override_channel,
            override_topics=payload.override_topics,
            personal_tags=payload.personal_tags,
            analysis_mode=payload.analysis_mode,
            priority=payload.priority,
            **notification_values,
        )
        request.state.operation_source_id = str(subscription["source_id"])
        request.state.operation_subscription_id = str(subscription["id"])
        request.state.operation_changed_fields = sorted(payload.model_fields_set)
        return ok(subscription)

    @app.patch("/api/me/subscriptions/{subscription_id}")
    async def subscriptions_patch(
        subscription_id: str,
        payload: SubscriptionPatchRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        provided = payload.model_fields_set
        updates = {
            field: getattr(payload, field)
            for field in (
                "enabled",
                "override_channel",
                "override_topics",
                "personal_tags",
                "analysis_mode",
                "priority",
                "notify_on_new_items",
            )
            if field in provided
        }
        current_subscription = store.get_subscription(subscription_id)
        if (
            payload.notify_on_new_items is True
            and (
                payload.analysis_mode == "personal_only"
                or payload.enabled is False
                or (
                    payload.enabled is not True
                    and current_subscription is not None
                    and current_subscription.get("user_id") == user["id"]
                    and not bool(current_subscription.get("enabled"))
                )
            )
        ):
            raise ApiError(
                "invalid_subscription_notification",
                "disabled or personal_only subscriptions cannot send new-item notifications",
                status_code=400,
                action="Enable the subscription in full analysis mode before enabling notifications.",
            )
        if (
            payload.notify_on_new_items is True
            and payload.analysis_mode is None
            and current_subscription is not None
            and current_subscription.get("user_id") == user["id"]
            and current_subscription.get("analysis_mode") == "personal_only"
        ):
            raise ApiError(
                "invalid_subscription_notification",
                "personal_only subscriptions cannot send new-item notifications",
                status_code=400,
                action="Use full analysis mode before enabling notifications.",
            )
        if payload.analysis_mode == "personal_only":
            updates["notify_on_new_items"] = False
        if "on_disable" in provided:
            if payload.enabled is not False:
                raise ApiError(
                    "invalid_disable_disposition",
                    "on_disable is only valid when disabling a subscription",
                    status_code=400,
                )
            updates["disable_disposition"] = payload.on_disable or "remove"
        updated = update_subscription_with_quota(
            user=user,
            subscription_id=subscription_id,
            updates=updates,
        )
        request.state.operation_source_id = str(updated["source_id"])
        request.state.operation_changed_fields = sorted(provided)
        return ok(updated)

    @app.get("/api/me/subscriptions/{subscription_id}/schedule")
    async def subscription_schedule_get(
        subscription_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return ok(source_schedule_response(user, subscription_id))

    @app.patch("/api/me/subscriptions/{subscription_id}/schedule")
    async def subscription_schedule_patch(
        subscription_id: str,
        payload: SourceSchedulePatchRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        if payload.enabled is None and payload.interval_minutes is None:
            raise ApiError(
                "invalid_source_schedule",
                "enabled or interval_minutes is required",
                status_code=400,
            )
        if (
            payload.interval_minutes is not None
            and payload.interval_minutes not in SOURCE_ALLOWED_INTERVALS
        ):
            raise ApiError(
                "invalid_source_schedule",
                "interval_minutes must be one of "
                + ", ".join(str(value) for value in SOURCE_ALLOWED_INTERVALS),
                status_code=400,
            )
        try:
            subscription_mutations.rest_update_schedule(
                SubscriptionActor.from_user(user),
                subscription_id=subscription_id,
                updates={
                    "enabled": payload.enabled,
                    "interval_minutes": payload.interval_minutes,
                },
            )
        except LookupError as exc:
            raise ApiError(
                "not_found", "subscription not found", status_code=404
            ) from exc
        except SourceScheduleUnavailableError as exc:
            raise ApiError(
                exc.code,
                str(exc),
                status_code=409,
                action="Enable the subscription and source before enabling its schedule.",
            ) from exc
        request.state.operation_changed_fields = sorted(payload.model_fields_set)
        return ok(source_schedule_response(user, subscription_id))

    @app.delete("/api/me/subscriptions/{subscription_id}")
    async def subscriptions_delete(
        subscription_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        subscription_mutations.rest_delete_subscription(
            SubscriptionActor.from_user(user),
            subscription_id=subscription_id,
        )
        return ok({"deleted": True})

    @app.get("/api/me/item-state")
    async def me_item_state(
        article_ids: str = "",
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        ids = [part.strip() for part in str(article_ids or "").split(",") if part.strip()]
        return ok(
            {
                "states": item_state.get_states(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                    article_ids=ids,
                )
            }
        )

    @app.patch("/api/me/items/{article_id}/state")
    async def me_item_state_update(
        article_id: str,
        payload: ItemStatePatchRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        visible_item_or_404(article_id, user)
        return ok(
            item_state.update_state(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                article_id=article_id,
                is_read=payload.is_read,
                is_saved=payload.is_saved,
                is_later=payload.is_later,
                dismissed=payload.dismissed,
            )
        )

    @app.post("/api/me/items/{article_id}/feedback")
    async def me_item_feedback(
        article_id: str,
        payload: ItemFeedbackRequest,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        visible_item_or_404(article_id, user)
        try:
            return ok(
                item_state.record_feedback(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                    article_id=article_id,
                    feedback_type=payload.feedback_type,
                    value=payload.value,
                    reason=payload.reason,
                    metadata=payload.metadata,
                )
            )
        except ValueError as exc:
            raise ApiError("invalid_feedback_type", str(exc), status_code=400) from exc

    def create_job(payload: JobCreateRequest, job_type: str, user: dict[str, Any]) -> dict[str, Any]:
        require_mutating_member(user)
        if job_type in {"source_test", "source_fetch"} and not payload.source_id and not _is_admin(user):
            raise ApiError(
                "forbidden",
                "members must run source jobs through a visible catalog source_id",
                status_code=403,
            )
        if payload.source_id:
            visible_source_or_404(payload.source_id, user)
        if job_type == "user_feed_refresh":
            conn = store.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                job, created = queue.create_user_feed_refresh_if_absent(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                    payload=payload.payload,
                    priority=payload.priority,
                    max_attempts=int(os.getenv("HORIZON_JOB_MAX_ATTEMPTS", "3")),
                    retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
                )
                if created:
                    quota.ensure_job_allowed(
                        workspace_id=user["workspace_id"],
                        user_id=user["id"],
                    )
                    quota.record_job_usage(
                        workspace_id=user["workspace_id"],
                        user_id=user["id"],
                        event_type=job_type,
                        commit=False,
                    )
                conn.commit()
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
            return {
                **_public_job(job),
                "deduplicated": not created,
            }
        if job_type == "source_fetch" and payload.subscription_id:
            subscription = store.get_subscription(payload.subscription_id)
            if (
                subscription is None
                or subscription["user_id"] != user["id"]
                or subscription["source_id"] != payload.source_id
            ):
                raise ApiError(
                    "not_found", "subscription not found", status_code=404
                )
            conn = store.connect()
            try:
                conn.execute("BEGIN IMMEDIATE")
                job, created = queue.create_source_fetch_if_absent(
                    workspace_id=user["workspace_id"],
                    user_id=user["id"],
                    source_id=str(payload.source_id),
                    subscription_id=payload.subscription_id,
                    payload=payload.payload,
                    priority=payload.priority,
                    max_attempts=int(os.getenv("HORIZON_JOB_MAX_ATTEMPTS", "3")),
                    retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
                )
                if created:
                    quota.ensure_job_allowed(
                        workspace_id=user["workspace_id"],
                        user_id=user["id"],
                    )
                    quota.record_job_usage(
                        workspace_id=user["workspace_id"],
                        user_id=user["id"],
                        event_type=job_type,
                        commit=False,
                    )
                conn.commit()
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
            return {**_public_job(job), "deduplicated": not created}
        quota.ensure_job_allowed(workspace_id=user["workspace_id"], user_id=user["id"])
        job = queue.create_job(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            source_id=payload.source_id,
            subscription_id=payload.subscription_id,
            job_type=job_type,
            payload=payload.payload,
            priority=payload.priority,
            max_attempts=int(os.getenv("HORIZON_JOB_MAX_ATTEMPTS", "3")),
            retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
        )
        quota.record_job_usage(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            event_type=job_type,
        )
        return _public_job(job)

    def mark_queued_job_operation(request: Request, job: dict[str, Any]) -> None:
        request.state.operation_job_id = str(job["id"])
        if job.get("source_id"):
            request.state.operation_source_id = str(job["source_id"])
        if job.get("subscription_id"):
            request.state.operation_subscription_id = str(job["subscription_id"])
        deduplicated = bool(job.get("deduplicated"))
        request.state.operation_outcome = "skipped" if deduplicated else "queued"
        request.state.operation_level = "info"
        request.state.operation_counts = {"deduplicated": int(deduplicated)}

    @app.post("/api/jobs/source-test")
    async def jobs_source_test(
        payload: JobCreateRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        job = create_job(payload, "source_test", user)
        mark_queued_job_operation(request, job)
        return ok(job)

    @app.post("/api/jobs/source-fetch")
    async def jobs_source_fetch(
        payload: JobCreateRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        job = create_job(payload, "source_fetch", user)
        mark_queued_job_operation(request, job)
        return ok(job)

    @app.post("/api/jobs/user-feed-refresh")
    async def jobs_user_feed_refresh(
        payload: JobCreateRequest,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        job = create_job(payload, "user_feed_refresh", user)
        mark_queued_job_operation(request, job)
        return ok(job)

    @app.post("/api/source/test")
    async def source_test_compat(
        payload: dict[str, Any],
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        job = create_job(compatibility_job_payload(payload), "source_test", user)
        mark_queued_job_operation(request, job)
        return ok(queued_job_response(job, "测试任务已排队，Worker 会异步执行。"))

    @app.post("/api/source/update")
    async def source_update_compat(
        payload: dict[str, Any],
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        job = create_job(compatibility_job_payload(payload), "source_fetch", user)
        mark_queued_job_operation(request, job)
        return ok(queued_job_response(job, "更新任务已排队，Worker 会异步执行。"))

    @app.get("/api/jobs/{job_id}")
    async def jobs_get(job_id: str, user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return ok(_public_job(job_or_404(job_id, user)))

    @app.post("/api/jobs/{job_id}/cancel")
    async def jobs_cancel(
        job_id: str,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        job_or_404(job_id, user)
        try:
            cancelled = _public_job(
                queue.cancel_job(
                    job_id,
                    user_id=None if _is_admin(user) else user["id"],
                )
            )
            request.state.operation_outcome = "cancelled"
            return ok(cancelled)
        except ValueError as exc:
            raise ApiError("job_not_cancelable", str(exc), status_code=409) from exc

    @app.post("/api/jobs/{job_id}/retry")
    async def jobs_retry(
        job_id: str,
        request: Request,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        require_mutating_member(user)
        conn = store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            current = job_or_404(job_id, user)
            eligibility = JobEligibilityService(store).evaluate(current)
            if not eligibility.allowed:
                raise ApiError(
                    "job_not_retryable",
                    f"job is no longer eligible: {eligibility.reason}",
                    status_code=409,
                    action="Re-enable the user, source, or subscription before retrying.",
                )
            metered = current.get("job_type") in {
                "source_test",
                "source_fetch",
                "user_feed_refresh",
            }
            if metered:
                quota.ensure_job_allowed(
                    workspace_id=current["workspace_id"],
                    user_id=current["user_id"],
                )
            retried = queue.retry_job(
                job_id,
                user_id=None if _is_admin(user) else user["id"],
                commit=False,
            )
            if metered and retried["id"] == job_id:
                quota.record_job_usage(
                    workspace_id=current["workspace_id"],
                    user_id=current["user_id"],
                    event_type=current["job_type"],
                    commit=False,
                )
            conn.commit()
            request.state.operation_outcome = "retried"
            return ok(_public_job(retried))
        except ValueError as exc:
            if conn.in_transaction:
                conn.rollback()
            raise ApiError("job_not_retryable", str(exc), status_code=409) from exc
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

    @app.get("/api/jobs")
    async def jobs_list(
        status: str | None = None,
        limit: int = 50,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return ok(
            {
                "jobs": [_public_job(job) for job in queue.list_jobs(
                    workspace_id=user["workspace_id"],
                    user_id=None if _is_admin(user) else user["id"],
                    status=status,
                    limit=max(1, min(int(limit), 200)),
                )]
            }
        )

    @app.get("/api/dashboard/summary")
    async def dashboard_summary(user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        sources = store.list_visible_sources(user)
        subscriptions = store.list_user_subscriptions(user["id"])
        jobs = queue.list_jobs(
            workspace_id=user["workspace_id"],
            user_id=None if _is_admin(user) else user["id"],
        )
        latest = feed_archive.latest_feed(workspace_id=user["workspace_id"], user_id=user["id"])
        item_state_counts = item_state.count_flags(workspace_id=user["workspace_id"], user_id=user["id"])
        runtime = runtime_status.summary(workspace_id=user["workspace_id"], user_id=user["id"])
        return ok(
            {
                "source_count": len(sources),
                "subscription_count": len(subscriptions),
                "queued_job_count": len([job for job in jobs if job["status"] == "queued"]),
                "running_job_count": len([job for job in jobs if job["status"] == "running"]),
                "failed_job_count": len([job for job in jobs if job["status"] == "failed"]),
                "latest_generated_at": latest.get("generated_at"),
                "item_state_counts": item_state_counts,
                "current_user": _sanitize_user(user),
                "runtime": {
                    "worker_status": runtime["worker_status"],
                    "oldest_queued_age_seconds": runtime["oldest_queued_age_seconds"],
                    "stale_running_count": runtime["stale_running_count"],
                },
            }
        )

    @app.get("/api/ops/runtime")
    async def ops_runtime(user: dict[str, Any] = Depends(current_admin)) -> dict[str, Any]:
        return ok(runtime_status.summary(workspace_id=user["workspace_id"]))

    @app.get("/api/feed/latest")
    async def feed_latest(
        user_id: str | None = None,
        hide_dismissed: bool = False,
        unread_first: bool = False,
        saved_first: bool = False,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        target = target_user_for_scope(user_id, user)
        return ok(
            feed_archive.latest_feed(
                workspace_id=target["workspace_id"],
                user_id=target["id"],
                hide_dismissed=hide_dismissed,
                unread_first=unread_first,
                saved_first=saved_first,
                feed_window_days=current_feed_window_days(),
            )
        )

    @app.get("/api/feed/search")
    async def feed_search(
        q: str,
        limit: int = 50,
        cursor: str | None = None,
        submitted: bool = False,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        normalized_q = str(q or "").strip()
        if not normalized_q or len(normalized_q) > 160:
            raise ApiError(
                "invalid_query",
                "q must contain between 1 and 160 characters",
                status_code=400,
            )
        if len(normalized_q) == 1 and not submitted:
            raise ApiError(
                "query_requires_submit",
                "single-character searches must be submitted explicitly",
                status_code=400,
            )
        if limit < 1 or limit > 50:
            raise ApiError(
                "invalid_limit",
                "limit must be between 1 and 50",
                status_code=400,
            )
        try:
            result = feed_archive.search_feed(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                q=normalized_q,
                limit=limit,
                cursor=str(cursor or "").strip() or None,
                feed_window_days=current_feed_window_days(),
            )
        except ContentSearchTimeoutError as exc:
            raise ApiError(
                "search_timeout",
                "content search exceeded the one-second budget",
                status_code=503,
                action="Retry the search or use a more specific keyword.",
            ) from exc
        except ValueError as exc:
            raise ApiError(
                "invalid_cursor",
                str(exc),
                status_code=400,
            ) from exc
        return ok(result)

    @app.get("/api/feed/saved")
    async def feed_saved(
        limit: int = 200,
        offset: int = 0,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return ok(
            user_content.saved_items(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                limit=max(1, min(int(limit), 200)),
                offset=max(0, int(offset)),
            )
        )

    @app.get("/api/feed/ignored")
    async def feed_ignored(
        limit: int = 200,
        offset: int = 0,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        return ok(
            user_content.dismissed_items(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                limit=max(1, min(int(limit), 200)),
                offset=max(0, int(offset)),
            )
        )

    @app.get("/api/feed/items/{article_id}")
    async def feed_item_detail(
        article_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        item = user_content.detail_item(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            article_id=article_id,
        )
        if item is None:
            raise ApiError("not_found", "item not found", status_code=404)
        return ok(item)

    @app.get("/api/media/{asset_id}")
    async def media_asset(
        asset_id: str,
        user: dict[str, Any] = Depends(current_user),
    ) -> FileResponse:
        asset = media_cache.authorized_asset(
            asset_id=asset_id,
            workspace_id=user["workspace_id"],
            user_id=user["id"],
        )
        if asset is None:
            raise ApiError("not_found", "media not found", status_code=404)
        path = (data_path / str(asset["local_path"])).resolve()
        media_root = (data_path / "media").resolve()
        if media_root not in path.parents or not path.is_file():
            raise ApiError("not_found", "media not found", status_code=404)
        return FileResponse(
            path,
            media_type=str(asset.get("mime_type") or "application/octet-stream"),
            headers={"Cache-Control": "private, max-age=31536000, immutable"},
        )

    @app.get("/api/feed/history")
    async def feed_history(
        user_id: str | None = None,
        q: str | None = None,
        source_id: str | None = None,
        limit: int = 200,
        offset: int = 0,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        target = target_user_for_scope(user_id, user)
        normalized_q = str(q or "").strip()
        if len(normalized_q) > 160:
            raise ApiError(
                "invalid_query",
                "q must be at most 160 characters",
                status_code=400,
            )
        if limit < 1 or limit > 200:
            raise ApiError(
                "invalid_limit",
                "limit must be between 1 and 200",
                status_code=400,
            )
        if offset < 0:
            raise ApiError(
                "invalid_offset",
                "offset must be non-negative",
                status_code=400,
            )
        normalized_source_id = str(source_id or "").strip() or None
        if normalized_source_id:
            visible_source_ids = {
                str(source["id"])
                for source in store.list_visible_sources(
                    target,
                    include_disabled=True,
                )
            }
            if normalized_source_id not in visible_source_ids:
                raise ApiError("not_found", "source not found", status_code=404)
        return ok(
            feed_archive.history_feed(
                workspace_id=target["workspace_id"],
                user_id=target["id"],
                q=normalized_q or None,
                source_id=normalized_source_id,
                limit=limit,
                offset=offset,
                feed_window_days=current_feed_window_days(),
            )
        )

    @app.get("/api/archive/graph")
    async def archive_graph(_user: dict[str, Any] = Depends(current_user)) -> dict[str, Any]:
        return ok(feed_archive.article_graph())

    @app.get("/api/archive/items")
    async def archive_items(
        user_id: str | None = None,
        channel: str | None = None,
        topic: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float = 0.0,
        limit: int = 100,
        offset: int = 0,
        sort: str = "published_at",
        order: str = "desc",
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        validate_archive_params(date_from=date_from, date_to=date_to, sort=sort, order=order)
        target = target_user_for_scope(user_id, user)
        return ok(
            feed_archive.archive_items(
                user_id=target["id"],
                channel=channel,
                topic=topic,
                source=source,
                date_from=date_from,
                date_to=date_to,
                min_score=min_score,
                limit=max(1, min(int(limit), 200)),
                offset=max(int(offset), 0),
                sort=sort,
                order=order,
            )
        )

    @app.get("/api/archive/trends")
    async def archive_trends(
        user_id: str | None = None,
        group_by: str = "channel",
        bucket: str = "none",
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        validate_archive_params(group_by=group_by, bucket=bucket)
        target = target_user_for_scope(user_id, user)
        return ok({"trends": feed_archive.archive_trends(group_by=group_by, user_id=target["id"], bucket=bucket)})

    @app.get("/api/archive/facets")
    async def archive_facets(
        user_id: str | None = None,
        channel: str | None = None,
        topic: str | None = None,
        source: str | None = None,
        date_from: str | None = None,
        date_to: str | None = None,
        min_score: float = 0.0,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        validate_archive_params(date_from=date_from, date_to=date_to)
        target = target_user_for_scope(user_id, user)
        return ok(
            feed_archive.archive_facets(
                user_id=target["id"],
                channel=channel,
                topic=topic,
                source=source,
                date_from=date_from,
                date_to=date_to,
                min_score=min_score,
            )
        )

    @app.get("/api/archive/source-quality")
    async def archive_source_quality(
        user_id: str | None = None,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        target = target_user_for_scope(user_id, user)
        return ok({"sources": feed_archive.source_quality(user_id=target["id"])})

    @app.api_route("/api/{_path:path}", methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"])
    async def api_not_found(_path: str) -> dict[str, Any]:
        raise ApiError("not_found", "API endpoint not found", status_code=404)

    if remote_mcp is not None:
        app.add_route(
            "/mcp",
            remote_mcp.exact_path_app,
            methods=["GET", "POST", "DELETE"],
            name="remote-mcp",
            include_in_schema=False,
        )
    else:
        @app.api_route(
            "/mcp",
            methods=["GET", "POST", "DELETE"],
            include_in_schema=False,
        )
        async def remote_mcp_disabled() -> JSONResponse:
            return JSONResponse(
                status_code=404,
                content={"error": "remote_mcp_disabled"},
            )

    @app.api_route(
        "/mcp/{_path:path}",
        methods=["GET", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def remote_mcp_non_exact_path(_path: str) -> JSONResponse:
        return JSONResponse(
            status_code=404,
            content={"error": "not_found"},
        )

    if static_path.exists():
        assets_path = static_path / "assets"
        if assets_path.exists():
            app.mount("/assets", StaticFiles(directory=str(assets_path)), name="service-assets")
            index_path = static_path / "index.html"

            @app.get("/{frontend_path:path}", include_in_schema=False)
            async def service_frontend(frontend_path: str) -> FileResponse:
                del frontend_path
                return FileResponse(index_path, media_type="text/html")
        else:
            app.mount("/", StaticFiles(directory=str(static_path), html=True), name="static")

    return app


def main() -> None:
    parser = argparse.ArgumentParser(description="Serve InfoHub Light service API")
    parser.add_argument("--host", default=os.getenv("HORIZON_WEB_HOST", "0.0.0.0"))
    parser.add_argument("--port", type=int, default=int(os.getenv("HORIZON_WEB_PORT", "8080")))
    parser.add_argument("--data-dir", default="data")
    parser.add_argument("--log-dir", default="logs")
    args = parser.parse_args()

    load_dotenv()
    configure_logging(log_dir=args.log_dir, service="api")
    app = create_app(data_dir=args.data_dir, log_dir=args.log_dir)
    uvicorn.run(app, host=args.host, port=args.port)


if __name__ == "__main__":
    main()
