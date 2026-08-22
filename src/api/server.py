"""FastAPI entrypoint for the small-group InfoHub service API."""

from __future__ import annotations

import argparse
import hashlib
import logging
import os
import re
import sqlite3
import time
import uuid
from copy import deepcopy
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Callable
from urllib.parse import unquote, urlparse

import uvicorn
import httpx
from dotenv import load_dotenv
from fastapi import Depends, FastAPI, Query, Request, Response
from fastapi.exceptions import RequestValidationError
from fastapi.responses import FileResponse, JSONResponse
from fastapi.staticfiles import StaticFiles
from pydantic import BaseModel, ConfigDict, Field, StrictInt, field_validator
from starlette.middleware.gzip import GZipMiddleware, GZipResponder, IdentityResponder

from .agent_delegation_routes import register_agent_delegation_routes
from .actor_alert_routes import register_actor_alert_routes
from .actorops_admin_routes import register_actorops_admin_routes
from .actorops_retired_routes import register_actorops_retired_routes
from .actorops_v2_alias_routes import register_actorops_v2_alias_routes
from .actorops_v2_control_routes import register_actorops_v2_control_routes
from .actorops_v2_maintenance_routes import (
    register_actorops_v2_maintenance_policy_routes,
)
from .actorops_v2_operator_routes import register_actorops_v2_operator_routes
from .apify_key_pool_routes import pool_api_error, register_apify_key_pool_routes
from .catalog_metadata_routes import register_catalog_metadata_routes
from .catalog_membership_routes import (
    register_catalog_list_route,
    register_catalog_membership_routes,
)
from .context import ApiContext
from .feed_routes import (
    register_dashboard_runtime_routes,
    register_feed_collection_routes,
    register_feed_latest_route,
    register_item_state_routes,
)
from .job_routes import JobCreateRequest, public_job as _public_job, register_job_routes
from .lifespan import build_service_lifespan
from .notification_routes import register_notification_routes
from .notification_transport_routes import register_notification_transport_routes
from .responses import ApiError, error_response, ok
from .schedule_routes import (
    register_feed_schedule_routes,
    register_subscription_schedule_routes,
)
from .secret_routes import (
    register_secret_list_route,
    register_secret_mutation_routes,
)
from .storage_routes import register_storage_routes
from .subscription_routes import (
    register_source_health_route,
    register_subscription_delete_route,
    register_subscription_list_route,
    register_subscription_mutation_routes,
)
from .system_auth import (
    current_admin,
    current_user,
    is_admin as _is_admin,
    register_system_auth_routes,
    require_mutating_member,
    visible_source_or_404 as require_visible_source,
)
from .user_routes import register_user_routes

from ..logging_utils import (
    configure_logging,
    error_fingerprint,
)
from ..services.feed_read import FeedReadService
from ..services.feed_end_messages import (
    FeedEndMessagesDisabled,
    FeedEndMessagesService,
)
from ..services.content_timeline import DEFAULT_FEED_WINDOW_DAYS
from ..services.feed_schedule import FeedScheduleService
from ..services.job_queue import JobQueue
from ..services.quota import QuotaExceeded, QuotaService
from ..services.runtime_status import RuntimeStatusService
from ..services.secret_quota import ApifySecretQuotaService
from ..services.apify_key_pool import (
    ApifyKeyBusyError,
    ApifyKeyDrainPendingError,
    ApifyKeyPoolConflictError,
    ApifyKeyPoolError,
    ApifyKeyPoolService,
    apify_key_pool_enabled,
)
from .actorops_source_lifecycle import ActorOpsSourceLifecycle
from ..services.actorops.binding_service import ActorOpsBindingError
from ..services.actorops.repository import ActorOpsNotFound, ActorOpsRepository
from ..services.source_health import SourceHealthService
from ..services.source_summary import SourceSummaryError, SourceSummaryService
from ..services.storage_governance import (
    StorageGovernanceError,
    StorageGovernanceService,
)
from ..services.source_schedule import SourceScheduleService
from ..services.subscription_mutation import (
    SubscriptionActor,
    SubscriptionMutationError,
    SubscriptionMutationService,
)
from ..services.secret_store import SecretStore, SecretValueError
from ..services.user_item_state import UserItemStateStore
from ..services.user_content_store import UserContentStore
from ..services.media_cache import MediaCacheService, PostCommitMediaCleanup
from ..services.preferred_source_notifications import (
    NotificationServiceError,
    PreferredSourceNotificationService,
)
from ..services.apify_actor_alerts import (
    ApifyActorAlertError,
    ApifyActorAlertService,
)
from ..services.notification_targets import (
    NotificationTargetError,
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
from ..services.workspace_telegram_transport import (
    TelegramTransportServiceError,
)
from ..mcp.remote_config import OpenClawChatSettings, RemoteMCPSettings
from ..mcp.remote_server import create_remote_mcp
from ..services.source_type_registry import (
    INSTAGRAM_PROFILE_SETUP_TYPE,
    PLATFORM_PROFILE_SETUP_TYPES,
    SourceConfigError,
    X_PROFILE_SETUP_TYPE,
    YOUTUBE_CHANNEL_SETUP_TYPE,
    catalog_source_setup_type,
    normalize_platform_profile_setup_config,
    platform_for_profile_setup_type,
    project_catalog_source_config_for_web,
    source_key as build_source_key,
    validate_secret_env_name,
    validate_source_config,
)
from ..services.youtube_channel import (
    YouTubeChannelError,
    YouTubeChannelResolver,
)
from ..storage.service_store import (
    SOURCE_SCOPES,
    ServiceStore,
    SourceKeyConflictError,
)
from ..tag_policy import HUB_CHANNELS
from ..auth import AuthSettings, COOKIE_NAME
from ..config_migration import migrate_config_tag_layers
from ..services.config_runtime import (
    _read_json,
    _write_json,
    apply_config_action,
    build_env_status,
    public_config_data,
    validate_config_data,
)


_ENV_VAR_RE = re.compile(r"^[A-Za-z_][A-Za-z0-9_]*$")
_SECRET_PREFIXES = ("sk-", "sk_", "AIza", "xai-", "gsk_", "hf_", "tp-")
_LOGGER = logging.getLogger(__name__)
SERVICE_STATIC_DIR = Path(__file__).resolve().parents[1] / "ui" / "service_static"
_NONRETRYABLE_ACTOR_OUTPUT_FAILURES = frozenset(
    {
        "apify_actor_contract_mismatch",
        "apify_actor_metadata_only",
        "apify_actor_placeholder",
    }
)


def resolve_service_static_dir(
    *,
    react_dir: Path | str = SERVICE_STATIC_DIR,
) -> Path:
    """Return the sole React UI directory, whether or not it is built yet."""

    return Path(react_dir)


def _normalize_frontend_path(frontend_path: str) -> str | None:
    """Decode and validate a frontend path before routing or resolving files."""

    if len(frontend_path) > 8192:
        return None
    decoded_path = frontend_path
    for _ in range(16):
        next_path = unquote(decoded_path)
        if next_path == decoded_path:
            break
        decoded_path = next_path
    else:
        if unquote(decoded_path) != decoded_path:
            return None
    if (
        "\x00" in decoded_path
        or "\\" in decoded_path
        or decoded_path.startswith("/")
    ):
        return None
    if any(part in {".", ".."} for part in decoded_path.split("/")):
        return None
    return decoded_path


def _accepts_gzip(accept_encoding: str) -> bool:
    explicit: list[float] = []
    wildcard: list[float] = []
    for member in accept_encoding.split(","):
        parts = [part.strip() for part in member.split(";")]
        coding = parts[0].lower()
        if coding not in {"gzip", "*"}:
            continue
        quality = 1.0
        for parameter in parts[1:]:
            name, separator, raw_value = parameter.partition("=")
            if separator and name.strip().lower() == "q":
                try:
                    quality = float(raw_value.strip())
                except ValueError:
                    quality = 0.0
                if not 0.0 <= quality <= 1.0:
                    quality = 0.0
                break
        (explicit if coding == "gzip" else wildcard).append(quality)
    if explicit:
        return max(explicit) > 0.0
    return bool(wildcard and max(wildcard) > 0.0)


class NegotiatedGZipMiddleware(GZipMiddleware):
    """Normalize Accept-Encoding so Starlette honors gzip q-values."""

    async def __call__(self, scope: dict[str, Any], receive: Any, send: Any) -> None:
        if scope.get("type") != "http":
            await super().__call__(scope, receive, send)
            return
        headers = list(scope.get("headers", []))
        accept_encoding = ",".join(
            value.decode("latin-1")
            for name, value in headers
            if name.lower() == b"accept-encoding"
        )
        responder = (
            GZipResponder(
                self.app,
                self.minimum_size,
                compresslevel=self.compresslevel,
            )
            if _accepts_gzip(accept_encoding)
            else IdentityResponder(self.app, self.minimum_size)
        )
        await responder(scope, receive, send)


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


def _sanitize_user(user: dict[str, Any]) -> dict[str, Any]:
    return ServiceStore.sanitize_user(user)


class SourceSummaryRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    article_ids: list[str] = Field(min_length=1, max_length=100)

    @field_validator("article_ids", mode="before")
    @classmethod
    def validate_article_ids(cls, value: Any) -> list[str]:
        if not isinstance(value, list):
            raise ValueError("article_ids must be a list")
        normalized: list[str] = []
        for candidate in value:
            if not isinstance(candidate, str):
                raise ValueError("article_ids must contain strings")
            article_id = candidate.strip()
            if not article_id or len(article_id) > 256 or "\x00" in article_id:
                raise ValueError("article_ids must contain 1 to 256 safe characters")
            if article_id not in normalized:
                normalized.append(article_id)
        if not normalized:
            raise ValueError("article_ids must contain at least one item")
        return normalized


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


class ConfigImportSourcesRequest(BaseModel):
    dry_run: bool = False
    subscribe_current_user: bool = True


class ConfigActionRequest(BaseModel):
    action: str
    payload: dict[str, Any] = Field(default_factory=dict)


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
    ("POST", "/api/notification-targets"): (
        "notification",
        "target_create",
    ),
    ("PATCH", "/api/notification-targets/{target_id}"): (
        "notification",
        "target_update",
    ),
    ("DELETE", "/api/notification-targets/{target_id}"): (
        "notification",
        "target_archive",
    ),
    ("POST", "/api/notification-targets/{target_id}/test"): (
        "notification",
        "target_test",
    ),
    ("POST", "/api/admin/notification-services"): (
        "notification",
        "service_create",
    ),
    ("PATCH", "/api/admin/notification-services/{service_id}"): (
        "notification",
        "service_update",
    ),
    ("DELETE", "/api/admin/notification-services/{service_id}"): (
        "notification",
        "service_archive",
    ),
    (
        "POST",
        "/api/admin/notification-services/{service_id}/test-and-enable",
    ): ("notification", "service_test_enable"),
    ("POST", "/api/config/action"): ("source", "compat_config_action"),
    ("POST", "/api/feed/source-summary"): (
        "request",
        "source_summary_generate",
    ),
    ("POST", "/api/admin/feed-end-messages/refresh"): (
        "job",
        "feed_end_messages_refresh",
    ),
    ("POST", "/api/users"): ("account", "member_create"),
    ("PATCH", "/api/users/{user_id}"): ("account", "member_update"),
    ("DELETE", "/api/users/{user_id}"): ("account", "member_delete"),
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
    ("PATCH", "/api/admin/notification-telegram-transport"): (
        "notification",
        "telegram_transport_update",
    ),
    ("DELETE", "/api/admin/notification-telegram-transport"): (
        "notification",
        "telegram_transport_delete",
    ),
    ("POST", "/api/admin/notification-telegram-transport/test"): (
        "notification",
        "telegram_transport_test",
    ),
    ("PUT", "/api/admin/apify-key-pool/order"): ("secret", "pool_reorder"),
    ("PUT", "/api/admin/apify-key-pool/validation-key"): (
        "secret",
        "validation_key_update",
    ),
    ("POST", "/api/admin/apify-key-pool/{secret_id}/drain"): (
        "secret",
        "pool_drain",
    ),
    (
        "POST",
        "/api/admin/apify-routes/{route_id}/pool-candidates/refresh",
    ): ("source", "actorops_v2_discovery_create"),
    (
        "POST",
        "/api/admin/apify-routes/{route_id}/active-pool/promote",
    ): ("source", "actorops_v2_candidate_promote"),
    ("PATCH", "/api/admin/apify-routes/{route_id}/price-cap"): (
        "source",
        "actorops_v2_price_cap",
    ),
    (
        "POST",
        "/api/admin/sources/{source_id}/apify-binding/activate",
    ): ("source", "actorops_v2_binding_enable"),
    ("PATCH", "/api/admin/apify-actor-alert-settings"): (
        "notification",
        "apify_alert_settings_update",
    ),
    ("POST", "/api/admin/apify-actor-alert-settings/test"): (
        "notification",
        "apify_alert_settings_test",
    ),
    ("POST", "/api/admin/secrets"): ("secret", "create"),
    ("PUT", "/api/admin/secrets/{secret_id}/value"): ("secret", "rotate"),
    ("PATCH", "/api/admin/secrets/{secret_id}/connection"): (
        "secret",
        "connection_update",
    ),
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
    ("PATCH", "/api/me/items/{article_id}/state"): (
        "account",
        "item_state_update",
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
    workspace_telegram_transport = (
        preferred_source_notifications.telegram_transport
    )
    notification_targets = preferred_source_notifications.notification_targets
    apify_actor_alerts = ApifyActorAlertService(
        store,
        data_dir=str(data_path),
        email_transport=workspace_email_transport,
        telegram_transport=workspace_telegram_transport,
        notification_targets=notification_targets,
    )
    apify_key_pool = ApifyKeyPoolService(store, secret_store=secret_values)

    def require_webhook_providers_v14() -> None:
        if store.webhook_providers_v14_migration_required():
            raise ApiError(
                "migration_required",
                "Webhook providers v14 migration must be applied before notification delivery is used",
                status_code=503,
                action=(
                    "Stop API and Worker, then run "
                    "scripts/migrate_webhook_providers_v14.py --apply."
                ),
            )

    def require_notification_channels_v15() -> None:
        if store.multichannel_notifications_v15_migration_required():
            raise ApiError(
                "migration_required",
                "notification channels v15 migration must be applied before notification delivery is used",
                status_code=503,
                action=(
                    "Stop API and Worker, then run "
                    "scripts/migrate_notification_channels_v15.py --apply."
                ),
            )

    def require_notification_targets_v16() -> None:
        require_notification_channels_v15()
        if store.notification_targets_v16_migration_required():
            raise ApiError(
                "migration_required",
                "notification targets v16 migration must be applied before notification delivery is used",
                status_code=503,
                action=(
                    "Stop API and Worker, then run "
                    "scripts/migrate_notification_targets_v16.py --apply."
                ),
            )

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
    feed_reader = FeedReadService(store)
    feed_end_messages = FeedEndMessagesService(store)
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
        if (
            base_config is not None
            and base_config.feed_end_messages.ai_key_env == secret["env_name"]
        ):
            usages.append(
                {
                    "type": "ai",
                    "id": "feed-end-messages",
                    "name": "信息流触底文案",
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
            "base_url": str(secret.get("base_url") or ""),
            "is_set": bool(secret_values.status(secret["env_name"])["is_set"]),
            "used_by": secret_usage(secret),
            "created_at": secret["created_at"],
            "updated_at": secret["updated_at"],
        }

    def validate_feed_end_messages_key(
        config: Config,
        *,
        workspace_id: str,
    ) -> None:
        """Validate a direct terminal-copy Key binding without global coupling."""

        key_env = str(config.feed_end_messages.ai_key_env or "").strip()
        if not key_env:
            return
        secret = store.get_secret_ref_by_env(
            workspace_id=workspace_id,
            env_name=key_env,
        )
        if secret is None or str(secret.get("kind") or "").lower() != "ai":
            raise ApiError(
                "invalid_feed_end_messages_ai_key",
                "触底文案 AI Key 必须选择已保存的 AI Key。",
                status_code=400,
            )

    def validate_global_ai_key_provider(
        config: Config,
        *,
        workspace_id: str,
    ) -> dict[str, Any] | None:
        secret = store.get_secret_ref_by_env(
            workspace_id=workspace_id,
            env_name=config.ai.api_key_env,
        )
        if secret is None:
            return None
        if (
            str(secret.get("kind") or "").lower() != "ai"
        ):
            raise ApiError(
                "invalid_ai_key",
                "AI Key 必须选择已保存的 AI Key。",
                status_code=400,
            )
        return secret

    def normalize_ai_secret_base_url(value: str) -> str:
        base_url = str(value or "").strip()
        if not base_url:
            return ""
        if len(base_url) > 2048:
            raise ApiError(
                "invalid_secret",
                "AI Base URL must contain at most 2048 characters",
                status_code=400,
            )
        parsed = urlparse(base_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.netloc
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ApiError(
                "invalid_secret",
                "AI Base URL must be an http/https URL without credentials, query, or fragment",
                status_code=400,
            )
        return base_url.rstrip("/")

    def synchronize_ai_connection(
        data: dict[str, Any],
        secret: dict[str, Any],
    ) -> None:
        """Project the selected Key's connection into the legacy AI config field."""

        ai_settings = data.setdefault("ai", {})
        base_url = str(secret.get("base_url") or "").strip()
        if base_url:
            ai_settings["base_url"] = base_url
        else:
            ai_settings.pop("base_url", None)

    def validate_secret_metadata(payload: Any) -> tuple[str, str, str, str, str]:
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
        if kind != "ai" and str(payload.base_url or "").strip():
            raise ApiError(
                "invalid_secret",
                "Base URL is supported only for AI keys",
                status_code=400,
            )
        base_url = normalize_ai_secret_base_url(payload.base_url) if kind == "ai" else ""
        return name, kind, provider, env_name, base_url


    def source_setup_availability(
        workspace_id: str,
    ) -> tuple[int, dict[str, tuple[str, str | None]]]:
        repository = ActorOpsRepository(store.connect(), workspace_id)
        statuses: dict[str, tuple[str, str | None]] = {}
        generations: list[int] = []
        for setup_type, platform in (
            (X_PROFILE_SETUP_TYPE, "x"),
            (INSTAGRAM_PROFILE_SETUP_TYPE, "instagram"),
        ):
            try:
                row = store.connect().execute(
                    """SELECT route_id FROM actor_routes_v2
                       WHERE workspace_id=? AND platform=?
                         AND target_type='profile' AND capability='items'""",
                    (workspace_id, platform),
                ).fetchone()
                route = repository.get_route(str(row["route_id"])) if row else None
            except sqlite3.OperationalError:
                # ActorOps schema readiness is local to Actor-backed sources;
                # ordinary RSS/GitHub setup remains available.
                route = None
            if route is not None:
                generations.append(route.generation)
            if route is None:
                statuses[setup_type] = (
                    "temporarily_unavailable",
                    "platform_setup_pending",
                )
            else:
                # Route mode, Candidate readiness and credentials are
                # execution gates.  They must not prevent an operator from
                # creating the pending Binding that Discovery will prepare.
                statuses[setup_type] = ("ready", None)
        return max(generations, default=1), statuses

    def workspace_catalog_source_setup_type(
        workspace_id: str,
        source_type: str,
        config: Any,
    ) -> str:
        setup_type = catalog_source_setup_type(source_type, config)
        if (
            setup_type != "apify_social"
            or not isinstance(config, dict)
            or not config.get("profile_id")
        ):
            return setup_type
        try:
            route = ActorOpsRepository(
                store.connect(), workspace_id
            ).get_route(str(config["profile_id"]))
        except ActorOpsNotFound:
            return setup_type
        identity = (
            route.route_key.platform,
            route.route_key.target_type,
            route.route_key.capability,
        )
        if identity == ("x", "profile", "items"):
            return X_PROFILE_SETUP_TYPE
        if identity == ("instagram", "profile", "items"):
            return INSTAGRAM_PROFILE_SETUP_TYPE
        return setup_type

    def public_source(source: dict[str, Any], user: dict[str, Any]) -> dict[str, Any]:
        item = dict(source)
        item.pop("enforce_public_network", None)
        item["setup_type"] = workspace_catalog_source_setup_type(
            str(source["workspace_id"]),
            str(source.get("type") or ""),
            source.get("config"),
        )
        if (
            item["setup_type"] in PLATFORM_PROFILE_SETUP_TYPES
            or str(source.get("type") or "") == "apify_social"
        ):
            item["config"] = project_catalog_source_config_for_web(
                str(source.get("type") or ""),
                source.get("config"),
                setup_type=str(item["setup_type"]),
            )
            item.pop("secret_env", None)
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
            env_name = source.get("secret_env")
            item["secret_configured"] = bool(
                env_name and secret_values.status(str(env_name))["is_set"]
            )
            if not _is_admin(user) or item["setup_type"] in PLATFORM_PROFILE_SETUP_TYPES:
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
        post_commit_cleanup: PostCommitMediaCleanup | None = None,
    ) -> dict[str, Any]:
        reject_pool_managed_source_secret(
            str(source.get("type") or ""),
            supplied="secret_env" in updates,
        )
        return subscription_mutations.rest_update_source(
            SubscriptionActor.from_user(user),
            source_id=str(source["id"]),
            updates=updates,
            post_commit_cleanup=post_commit_cleanup,
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

    app = FastAPI(
        title="InfoHub Light Service API",
        lifespan=build_service_lifespan(
            store,
            remote_mcp.server.session_manager if remote_mcp else None,
        ),
    )
    app.add_middleware(NegotiatedGZipMiddleware, minimum_size=1024, compresslevel=5)
    app.state.service_store = store
    app.state.subscription_mutations = subscription_mutations
    app.state.preferred_source_notifications = preferred_source_notifications
    app.state.notification_targets = notification_targets
    app.state.workspace_email_transport = workspace_email_transport
    app.state.workspace_telegram_transport = workspace_telegram_transport
    app.state.apify_actor_alerts = apify_actor_alerts
    app.state.remote_mcp = remote_mcp.server if remote_mcp else None
    app.state.youtube_channel_resolver = youtube_channels
    app.state.source_summary_service = SourceSummaryService(store, quota=quota)
    app.state.api_context = ApiContext(
        store=store,
        job_queue=queue,
        feed_reader=feed_reader,
        feed_schedules=feed_schedules,
        source_schedules=source_schedules,
        subscription_mutations=subscription_mutations,
        item_state=item_state,
        user_content=user_content,
        media_cache=media_cache,
        data_path=data_path,
        feed_window_days=lambda: current_feed_window_days(),
        quota=quota,
        runtime_status=runtime_status,
        storage_governance=storage_governance,
        apify_key_pool=apify_key_pool,
        apify_actor_alerts=apify_actor_alerts,
        source_setup_availability=source_setup_availability,
        public_source=public_source,
        secret_values=secret_values,
        secret_quota=secret_quota,
        source_health=source_health,
        public_secret=public_secret,
        secret_usage=secret_usage,
        validate_secret_metadata=validate_secret_metadata,
        read_base_config=lambda: read_base_config(),
        write_base_config=lambda data: write_base_config(data),
        synchronize_ai_connection=synchronize_ai_connection,
        normalize_ai_secret_base_url=normalize_ai_secret_base_url,
        preferred_source_notifications=preferred_source_notifications,
        notification_targets=notification_targets,
        workspace_email_transport=workspace_email_transport,
        workspace_telegram_transport=workspace_telegram_transport,
        auth_settings=auth_settings,
        remote_mcp_settings=remote_mcp_settings,
        openclaw_chat_settings=openclaw_chat_settings,
        require_webhook_providers=require_webhook_providers_v14,
        require_notification_channels=require_notification_channels_v15,
        require_notification_targets=require_notification_targets_v16,
        readiness_checks=(
            require_webhook_providers_v14,
            require_notification_targets_v16,
        ),
    )
    register_actorops_v2_maintenance_policy_routes(app, app.state.api_context)
    register_actorops_v2_control_routes(app, app.state.api_context)
    register_actorops_v2_operator_routes(app, app.state.api_context)
    register_actorops_v2_alias_routes(app, app.state.api_context)
    register_actorops_retired_routes(app)

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
            fingerprint = error_fingerprint()
            _LOGGER.exception(
                "api_request_failed method=%s route=%s request_id=%s",
                request.method,
                route_template if isinstance(route_template, str) else "-",
                request_id,
                extra={
                    "stage": "request",
                    "error_code": "internal_error",
                },
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
                    error_fingerprint=fingerprint,
                    stage="request",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    route=route_template,
                    method=(
                        request.method
                        if request.method in {"POST", "PUT", "PATCH", "DELETE"}
                        else None
                    ),
                    status_code=500,
                )
            else:
                safe_emit_operation_event(
                    category="request",
                    action="unhandled_error",
                    outcome="failed",
                    level="error",
                    workspace_id=getattr(
                        request.state, "operation_workspace_id", None
                    ),
                    actor_user_id=getattr(
                        request.state, "operation_actor_user_id", None
                    ),
                    error_code="internal_error",
                    error_fingerprint=fingerprint,
                    stage="request",
                    duration_ms=int((time.perf_counter() - started) * 1000),
                    route=(
                        route_template
                        if isinstance(route_template, str)
                        else None
                    ),
                    method=(
                        request.method
                        if request.method
                        in {"GET", "POST", "PUT", "PATCH", "DELETE"}
                        else None
                    ),
                    status_code=500,
                )
            response = error_response(
                ApiError(
                    "internal_error",
                    "request failed unexpectedly",
                    status_code=500,
                    retryable=True,
                    action=(
                        "Retry with the returned request ID and inspect "
                        "the private diagnostics."
                    ),
                )
            )
            if (
                request.url.path.startswith("/api/")
                or request.url.path == "/mcp"
            ):
                response.headers["X-Request-ID"] = request_id
            return response
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
                    "Do not retry this test; refresh settings and confirm the "
                    "receiver before any manual action."
                    if exc.outcome_unknown
                    else (
                        "Wait at least 60 seconds before sending another test."
                        if exc.code == "notification_test_rate_limited"
                        else (
                            "Review the saved notification channel and send another test."
                            if exc.status_code < 500
                            else "Retry later without changing the Feed or source job."
                        )
                    )
                ),
            )
        )

    @app.exception_handler(NotificationTargetError)
    async def _notification_target_error_handler(
        request: Request,
        exc: NotificationTargetError,
    ) -> JSONResponse:
        mark_operation_error(request, exc.code)
        return error_response(
            ApiError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                action=(
                    "Do not retry this test automatically; confirm the target "
                    "before any manual action."
                    if exc.outcome_unknown
                    else (
                        "Wait at least 60 seconds before testing this target again."
                        if exc.code == "notification_target_test_rate_limited"
                        else "Review the notification target and retry."
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

    @app.exception_handler(TelegramTransportServiceError)
    async def _telegram_transport_error_handler(
        request: Request,
        exc: TelegramTransportServiceError,
    ) -> JSONResponse:
        mark_operation_error(request, exc.code)
        return error_response(
            ApiError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                action=(
                    "Do not retry this test; refresh the transport state and "
                    "confirm the Telegram receiver before any manual action."
                    if exc.outcome_unknown
                    else (
                        "Wait at least 60 seconds before sending another test."
                        if exc.code
                        == "telegram_transport_test_rate_limited"
                        else (
                            "Save the Bot Token, send a test, then enable the transport."
                            if exc.status_code < 500
                            else "Review Telegram availability and retry later."
                        )
                    )
                ),
            )
        )

    @app.exception_handler(ApifyActorAlertError)
    async def _apify_actor_alert_error_handler(
        request: Request,
        exc: ApifyActorAlertError,
    ) -> JSONResponse:
        mark_operation_error(request, exc.code)
        return error_response(
            ApiError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                action=(
                    "Do not retry this test; refresh settings and confirm the "
                    "receiver before any manual action."
                    if exc.outcome_unknown
                    else (
                        "Wait at least 60 seconds before sending another test."
                        if exc.code == "apify_actor_alert_test_rate_limited"
                        else "Review the saved alert channel and retry."
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

    def visible_source_or_404(source_id: str, user: dict[str, Any]) -> dict[str, Any]:
        return require_visible_source(store, source_id, user)

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
        data.setdefault(
            "feed_end_messages",
            config.feed_end_messages.model_dump(mode="json"),
        )
        return {
            "path": str(data_path / "config.json"),
            "config": public_config_data(data),
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
        if source_type in PLATFORM_PROFILE_SETUP_TYPES:
            try:
                normalized = normalize_platform_profile_setup_config(
                    source_type,
                    config,
                )
            except SourceConfigError as exc:
                raise ApiError(
                    "invalid_source_config",
                    str(exc),
                    status_code=400,
                ) from exc
            return (
                "apify_social",
                normalized,
                build_source_key("apify_social", normalized),
            )
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

    register_system_auth_routes(app)
    register_notification_routes(app)

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

        feed_end_payload = (
            payload
            if action == "set_feed_end_messages"
            else payload.get("feed_end_messages", {})
            if action == "set_settings_bundle"
            else None
        )
        if isinstance(feed_end_payload, dict) and feed_end_payload.get(
            "ai_generation_enabled"
        ) is True and (
            not str(feed_end_payload.get("ai_key_env") or "").strip()
            or not str(feed_end_payload.get("model") or "").strip()
        ):
            raise ApiError(
                "invalid_feed_end_messages_ai_key",
                "启用触底文案 AI 生成时必须选择已保存的 AI Key 并填写模型。",
                status_code=400,
            )

        base_data, _base_config = read_base_config()
        updated = apply_config_action(base_data, action, payload)
        if action in {"set_ai", "set_feed_end_messages"} or (
            action == "set_settings_bundle"
            and bool({"ai", "feed_end_messages"} & set(payload))
        ):
            updated_config = validate_config_data(updated)
            global_ai_secret = validate_global_ai_key_provider(
                updated_config,
                workspace_id=user["workspace_id"],
            )
            if global_ai_secret is not None:
                updated.setdefault("ai", {})["provider"] = str(
                    global_ai_secret["provider"]
                ).lower()
                synchronize_ai_connection(updated, global_ai_secret)
                updated_config = validate_config_data(updated)
            validate_feed_end_messages_key(
                updated_config,
                workspace_id=user["workspace_id"],
            )
        write_base_config(updated)
        return ok(config_response(user))

    register_user_routes(app)

    register_catalog_list_route(app)

    register_storage_routes(app)

    register_secret_list_route(app)

    register_notification_transport_routes(app)

    register_apify_key_pool_routes(app)

    register_actorops_admin_routes(app, store=store, operation_logs=operation_logs)

    register_actor_alert_routes(app)

    register_secret_mutation_routes(app)
    register_catalog_metadata_routes(app)

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
            payload.type in (
                YOUTUBE_CHANNEL_SETUP_TYPE,
                *PLATFORM_PROFILE_SETUP_TYPES,
            )
            and payload.secret_env is not None
        ):
            raise ApiError(
                "invalid_source_config",
                "This source setup does not accept per-source credentials.",
                status_code=400,
            )
        catalog_type, normalized_config, key = await resolve_catalog_source_config(
            payload.type,
            payload.config,
        )
        lifecycle = ActorOpsSourceLifecycle(
            store, workspace_id=str(user["workspace_id"])
        )
        normalized_config = lifecycle.normalize_config(
            catalog_type, normalized_config
        )
        key = build_source_key(catalog_type, normalized_config)
        managed = lifecycle.is_managed(catalog_type, normalized_config)
        enforce_public_network = (
            catalog_source_setup_type(catalog_type, normalized_config)
            == YOUTUBE_CHANNEL_SETUP_TYPE
        )
        existing_source = store.get_source_by_key(
            workspace_id=str(user["workspace_id"]),
            source_key=key,
        )
        source_enabled = bool(
            existing_source.get("enabled")
            if managed and existing_source is not None
            else payload.enabled if not managed else False
        )
        connection = store.connect()
        owns_transaction = not connection.in_transaction
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
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
                enabled=source_enabled,
            )
            if managed:
                source = lifecycle.after_create(str(source["id"]))
            if owns_transaction:
                connection.commit()
        except SourceKeyConflictError as exc:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise ApiError(
                "source_key_conflict",
                str(exc),
                status_code=409,
                action="Use the existing visible source or choose a different source configuration.",
            ) from exc
        except ActorOpsBindingError as exc:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise ApiError(
                exc.code,
                "ActorOps v2 could not prepare this source binding.",
                status_code=409,
            ) from exc
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
            raise
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
        setup_type = workspace_catalog_source_setup_type(
            str(user["workspace_id"]),
            str(source["type"]),
            source.get("config"),
        )
        if (
            "secret_env" in provided
            and setup_type
            in (YOUTUBE_CHANNEL_SETUP_TYPE, *PLATFORM_PROFILE_SETUP_TYPES)
            and payload.secret_env is not None
        ):
            raise ApiError(
                "invalid_source_config",
                "This source setup does not accept per-source credentials.",
                status_code=400,
            )

        lifecycle = ActorOpsSourceLifecycle(
            store, workspace_id=str(user["workspace_id"])
        )
        previous_config = (
            dict(source["config"])
            if isinstance(source.get("config"), dict)
            else {}
        )
        managed_before = lifecycle.is_managed(
            str(source["type"]), previous_config
        )
        updates: dict[str, Any] = {}
        for field_name in (
            "display_name",
            "description",
            "default_channel",
            "default_topics",
        ):
            if field_name in provided:
                value = getattr(payload, field_name)
                if field_name != "default_topics" or value is not None:
                    updates[field_name] = value

        if "config" in provided and payload.config is not None:
            request_setup_type = setup_type
            request_config = dict(payload.config)
            if setup_type in PLATFORM_PROFILE_SETUP_TYPES:
                current = lifecycle.normalize_config(
                    str(source["type"]),
                    previous_config,
                    source_id=source_id,
                )
                request_config = {
                    field_name: current[field_name]
                    for field_name in ("target", "fetch_limit", "analysis_mode")
                    if field_name in current
                } | request_config
            elif managed_before and source["type"] == "apify_social":
                request_setup_type = "apify_social"
                current = lifecycle.normalize_config(
                    str(source["type"]),
                    previous_config,
                    source_id=source_id,
                )
                request_config = current | request_config
            catalog_type, normalized_config, _key = (
                await resolve_catalog_source_config(
                    request_setup_type, request_config
                )
            )
            if catalog_type != source["type"]:
                raise ApiError(
                    "invalid_source_config",
                    "source storage type cannot be changed",
                    status_code=400,
                )
            normalized_config = lifecycle.normalize_config(
                catalog_type,
                normalized_config,
                source_id=source_id,
            )
            managed_after_config = lifecycle.is_managed(
                catalog_type, normalized_config
            )
            if managed_before and not managed_after_config:
                raise ApiError(
                    "invalid_source_config",
                    "ActorOps-managed sources must keep a registered v2 RouteKey.",
                    status_code=400,
                )
            updates["config"] = normalized_config
            updates["source_key"] = build_source_key(
                catalog_type, normalized_config
            )
            if (
                source["type"] == "rss"
                and catalog_source_setup_type(
                    catalog_type, normalized_config
                )
                == YOUTUBE_CHANNEL_SETUP_TYPE
            ):
                updates["enforce_public_network"] = True

        if "secret_env" in provided:
            updates["secret_env"] = _validate_secret_env(payload.secret_env)
        requested_enabled = (
            bool(payload.enabled) if "enabled" in provided else None
        )
        if requested_enabled is not None:
            updates["enabled"] = requested_enabled

        next_config = updates.get("config", previous_config)
        managed_after = lifecycle.is_managed(
            str(source["type"]), next_config
        )
        connection = store.connect()
        cleanup = PostCommitMediaCleanup()
        owns_transaction = not connection.in_transaction
        try:
            if owns_transaction:
                connection.execute("BEGIN IMMEDIATE")
            updated = update_catalog_source(
                source,
                updates,
                user=user,
                post_commit_cleanup=cleanup,
            )
            if managed_after:
                updated = lifecycle.after_update(
                    source_id,
                    previous_config=previous_config,
                    requested_enabled=requested_enabled,
                )
            if owns_transaction:
                connection.commit()
                cleanup.run()
        except SourceKeyConflictError as exc:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
                cleanup.discard()
            raise ApiError(
                "source_key_conflict",
                str(exc),
                status_code=409,
                action=(
                    "Keep the current source configuration or choose a different source."
                ),
            ) from exc
        except ActorOpsBindingError as exc:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
                cleanup.discard()
            raise ApiError(
                exc.code,
                "ActorOps v2 could not update this source binding.",
                status_code=409,
            ) from exc
        except Exception:
            if owns_transaction and connection.in_transaction:
                connection.rollback()
                cleanup.discard()
            raise
        request.state.operation_changed_fields = sorted(provided)
        return ok(public_source(updated, user))

    register_catalog_membership_routes(app)

    register_subscription_list_route(app)

    register_agent_delegation_routes(app)

    register_source_health_route(app)

    register_feed_schedule_routes(app)

    register_subscription_mutation_routes(app)

    register_subscription_schedule_routes(app)

    register_subscription_delete_route(app)

    register_item_state_routes(app)
    register_job_routes(app)
    register_dashboard_runtime_routes(app)
    register_feed_latest_route(app)

    @app.get("/api/feed/end-messages")
    async def feed_end_messages_get(
        response: Response,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        _data, config = read_base_config()
        response.headers["Cache-Control"] = "no-store"
        return ok(
            feed_end_messages.public_state(
                workspace_id=user["workspace_id"],
                config=config,
            )
        )

    @app.post("/api/feed/source-summary")
    async def feed_source_summary(
        payload: SourceSummaryRequest,
        response: Response,
        user: dict[str, Any] = Depends(current_user),
    ) -> dict[str, Any]:
        if user.get("role") == "viewer":
            raise ApiError(
                "forbidden",
                "viewer users cannot generate AI summaries",
                status_code=403,
            )
        _data, config = read_base_config()
        try:
            result = await app.state.source_summary_service.generate(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                article_ids=payload.article_ids,
                ai_config=config.ai,
            )
        except SourceSummaryError as exc:
            raise ApiError(
                exc.code,
                exc.message,
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        response.headers["Cache-Control"] = "no-store"
        return ok(result)

    @app.post("/api/admin/feed-end-messages/refresh")
    async def feed_end_messages_refresh(
        request: Request,
        response: Response,
        user: dict[str, Any] = Depends(current_admin),
    ) -> dict[str, Any]:
        _data, config = read_base_config()
        try:
            result = feed_end_messages.request_refresh(
                workspace_id=user["workspace_id"],
                requested_by_user_id=user["id"],
                config=config,
            )
        except FeedEndMessagesDisabled as exc:
            raise ApiError(
                exc.code,
                str(exc),
                status_code=409,
                action="Enable AI and feed end message generation before refreshing.",
            ) from exc
        request.state.operation_changed_fields = ["feed_end_messages.refresh"]
        response.headers["Cache-Control"] = "no-store"
        return ok(result)

    register_feed_collection_routes(app)

    @app.api_route(
        "/api",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def api_root_not_found() -> dict[str, Any]:
        raise ApiError("not_found", "API endpoint not found", status_code=404)

    @app.api_route(
        "/api/{_path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
        include_in_schema=False,
    )
    async def api_not_found(_path: str) -> dict[str, Any]:
        raise ApiError("not_found", "API endpoint not found", status_code=404)

    @app.api_route(
        "/favicon.ico",
        methods=["GET", "HEAD"],
        include_in_schema=False,
    )
    async def legacy_favicon() -> Response:
        return Response(
            status_code=204,
            headers={"Cache-Control": "public, max-age=86400"},
        )

    if remote_mcp is not None:
        app.add_route(
            "/mcp",
            remote_mcp.exact_path_app,
            methods=["GET", "HEAD", "POST", "DELETE"],
            name="remote-mcp",
            include_in_schema=False,
        )
    else:
        @app.api_route(
            "/mcp",
            methods=["GET", "HEAD", "POST", "DELETE"],
            include_in_schema=False,
        )
        async def remote_mcp_disabled() -> JSONResponse:
            return JSONResponse(
                status_code=404,
                content={"error": "remote_mcp_disabled"},
            )

    @app.api_route(
        "/mcp/{_path:path}",
        methods=["GET", "HEAD", "POST", "PUT", "PATCH", "DELETE", "OPTIONS"],
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
        if assets_path.exists() and index_path.exists():
            static_root = static_path.resolve()

            @app.api_route(
                "/{frontend_path:path}",
                methods=["GET", "HEAD"],
                include_in_schema=False,
            )
            async def service_frontend(frontend_path: str) -> Response:
                normalized_path = _normalize_frontend_path(frontend_path)
                if normalized_path is None:
                    return Response(status_code=404)

                route_prefix = normalized_path.split("/", 1)[0]
                if route_prefix in {"api", "mcp"}:
                    return Response(status_code=404)

                try:
                    static_file = (static_root / normalized_path).resolve()
                    static_file.relative_to(static_root)
                except (OSError, RuntimeError, ValueError):
                    return Response(status_code=404)

                if static_file.is_file():
                    return FileResponse(static_file)

                final_segment = normalized_path.rstrip("/").rsplit("/", 1)[-1]
                if "." in final_segment:
                    return Response(status_code=404)

                return FileResponse(
                    index_path,
                    media_type="text/html",
                    headers={"Cache-Control": "no-cache"},
                )
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
    uvicorn.run(
        app,
        host=args.host,
        port=args.port,
        log_config=None,
        access_log=False,
    )


if __name__ == "__main__":
    main()
