"""Notification service, target, and user-settings HTTP adapters."""

from typing import Any, Literal

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import (
    api_context,
    current_admin,
    current_user,
    require_mutating_member,
)


WebhookProvider = Literal[
    "generic_event",
    "generic_text",
    "feishu_lark_v2",
    "wecom",
    "dingtalk",
    "slack",
    "discord",
]
NotificationChannel = Literal["email", "webhook", "telegram"]


class NotificationSettingsPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool | None = None
    channel: NotificationChannel | None = None
    channels: list[NotificationChannel] | None = None
    target_ids: list[str] | None = None
    email_address: str | None = Field(default=None, min_length=3, max_length=320)
    webhook_url: str | None = Field(default=None, min_length=8, max_length=4096)
    webhook_provider: WebhookProvider | None = None
    webhook_signing_secret: str | None = Field(default=None, max_length=4096)
    telegram_chat_id: str | None = Field(default=None, max_length=128)


class NotificationChannelTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    channel: NotificationChannel | None = None


class NotificationTargetCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    scope: Literal["private", "shared"]
    channel: NotificationChannel
    email_address: str | None = Field(default=None, max_length=320)
    webhook_url: str | None = Field(default=None, max_length=4096)
    webhook_provider: WebhookProvider | None = None
    webhook_signing_secret: str | None = Field(default=None, max_length=4096)
    telegram_chat_id: str | None = Field(default=None, max_length=128)


class NotificationTargetPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str | None = Field(default=None, min_length=1, max_length=80)
    enabled: StrictBool | None = None
    email_address: str | None = Field(default=None, max_length=320)
    webhook_url: str | None = Field(default=None, max_length=4096)
    webhook_provider: WebhookProvider | None = None
    webhook_signing_secret: str | None = Field(default=None, max_length=4096)
    telegram_chat_id: str | None = Field(default=None, max_length=128)


class NotificationServiceEmailTransportRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal["qq", "netease", "gmail", "resend", "amazon_ses"] | None = None
    sender_email: str | None = Field(default=None, max_length=320)
    sender_name: str | None = Field(default=None, max_length=80)
    credential: str | None = Field(default=None, max_length=4096)
    region: str | None = Field(default=None, max_length=64)
    smtp_username: str | None = Field(default=None, max_length=320)


class NotificationServiceCreateRequest(NotificationTargetCreateRequest):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["shared"] = "shared"
    telegram_bot_token: str | None = Field(default=None, max_length=256)
    email_transport: NotificationServiceEmailTransportRequest | None = None


class NotificationServicePatchRequest(NotificationTargetPatchRequest):
    model_config = ConfigDict(extra="forbid")

    telegram_bot_token: str | None = Field(default=None, max_length=256)
    email_transport: NotificationServiceEmailTransportRequest | None = None


def public_notification_test_result(result: dict[str, Any]) -> dict[str, Any]:
    """Keep delivery acknowledgements and destinations out of test responses."""

    channel = str(result.get("channel") or "")
    public: dict[str, Any] = {
        "sent": bool(result.get("sent")),
        "channel": channel,
    }
    if result.get("target_id") is not None:
        public["target_id"] = str(result["target_id"])
    if result.get("enabled") is not None:
        public["enabled"] = bool(result["enabled"])
    if channel == "webhook":
        if result.get("provider") is not None:
            public["provider"] = str(result["provider"])
        if result.get("verification") is not None:
            public["verification"] = str(result["verification"])
    return public


def _ready(context: ApiContext) -> None:
    context.require_webhook_providers()
    context.require_notification_targets()


def _public_service(
    context: ApiContext,
    *,
    workspace_id: str,
    user_id: str,
    service_id: str,
) -> dict[str, Any]:
    services = context.notification_targets.list_public_services(
        workspace_id=workspace_id,
        user_id=user_id,
    )["services"]
    for service in services:
        if str(service.get("id")) == service_id:
            return service
    raise ApiError(
        "notification_service_not_found",
        "notification service not found",
        status_code=404,
    )


async def notification_targets_get(
    response: Response,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    _ready(context)
    response.headers["Cache-Control"] = "no-store"
    return ok(
        context.notification_targets.list_public_targets(
            workspace_id=str(user["workspace_id"]),
            user_id=str(user["id"]),
        )
    )


async def notification_services_get(
    response: Response,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    _ready(context)
    response.headers["Cache-Control"] = "no-store"
    return ok(
        context.notification_targets.list_public_services(
            workspace_id=str(user["workspace_id"]),
            user_id=str(user["id"]),
        )
    )


def _validate_service_credentials(
    channel: str,
    payload: NotificationServiceCreateRequest | NotificationServicePatchRequest,
) -> None:
    provided = payload.model_fields_set
    if channel != "telegram" and "telegram_bot_token" in provided:
        raise ApiError(
            "invalid_notification_service",
            "Telegram credentials require a Telegram service",
            status_code=400,
        )
    if channel != "email" and "email_transport" in provided:
        raise ApiError(
            "invalid_notification_service",
            "email credentials require an email service",
            status_code=400,
        )
    if "telegram_bot_token" in provided and not str(
        payload.telegram_bot_token or ""
    ).strip():
        raise ApiError(
            "invalid_notification_service",
            "Telegram Bot Token cannot be empty",
            status_code=400,
        )
    if "email_transport" in provided and payload.email_transport is None:
        raise ApiError(
            "invalid_notification_service",
            "email transport settings cannot be null",
            status_code=400,
        )


def _apply_service_transport(
    context: ApiContext,
    payload: NotificationServiceCreateRequest | NotificationServicePatchRequest,
    user: dict[str, Any],
) -> None:
    provided = payload.model_fields_set
    if "telegram_bot_token" in provided:
        context.workspace_telegram_transport.upsert(
            workspace_id=str(user["workspace_id"]),
            actor_user_id=str(user["id"]),
            bot_token=payload.telegram_bot_token,
        )
    if "email_transport" not in provided or payload.email_transport is None:
        return
    email_updates = payload.email_transport.model_dump(exclude_unset=True)
    if not email_updates:
        raise ApiError(
            "invalid_notification_service",
            "email transport settings cannot be empty",
            status_code=400,
        )
    context.workspace_email_transport.upsert(
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        **email_updates,
    )


async def admin_notification_services_create(
    payload: NotificationServiceCreateRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    _ready(context)
    _validate_service_credentials(payload.channel, payload)
    provided = payload.model_fields_set
    target_fields = {
        field: getattr(payload, field)
        for field in (
            "name",
            "scope",
            "channel",
            "email_address",
            "webhook_url",
            "webhook_provider",
            "webhook_signing_secret",
            "telegram_chat_id",
        )
        if field in provided or field in {"name", "scope", "channel"}
    }
    created = context.notification_targets.create(
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        **target_fields,
    )
    _apply_service_transport(context, payload, user)
    request.state.operation_changed_fields = sorted(provided)
    response.headers["Cache-Control"] = "no-store"
    return ok(
        _public_service(
            context,
            workspace_id=str(user["workspace_id"]),
            user_id=str(user["id"]),
            service_id=str(created["id"]),
        )
    )


def _shared_service_or_404(
    context: ApiContext,
    service_id: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    target = context.store.get_notification_target(
        workspace_id=str(user["workspace_id"]),
        target_id=service_id,
    )
    if (
        target is None
        or target.get("archived_at") is not None
        or str(target.get("scope") or "") != "shared"
    ):
        raise ApiError(
            "notification_service_not_found",
            "notification service not found",
            status_code=404,
        )
    return target


async def admin_notification_services_patch(
    service_id: str,
    payload: NotificationServicePatchRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    _ready(context)
    provided = payload.model_fields_set
    if not provided:
        raise ApiError(
            "invalid_notification_service",
            "at least one notification service field is required",
            status_code=400,
        )
    target = _shared_service_or_404(context, service_id, user)
    _validate_service_credentials(str(target["channel"]), payload)
    if any(
        field in provided and getattr(payload, field) is None
        for field in (
            "name",
            "enabled",
            "email_address",
            "webhook_url",
            "webhook_provider",
            "telegram_chat_id",
        )
    ):
        raise ApiError(
            "invalid_notification_service",
            "notification service fields cannot be null",
            status_code=400,
        )
    target_updates = {
        field: getattr(payload, field)
        for field in (
            "name",
            "enabled",
            "email_address",
            "webhook_url",
            "webhook_provider",
            "webhook_signing_secret",
            "telegram_chat_id",
        )
        if field in provided
    }
    if target_updates:
        context.notification_targets.update(
            workspace_id=str(user["workspace_id"]),
            actor_user_id=str(user["id"]),
            target_id=service_id,
            **target_updates,
        )
    _apply_service_transport(context, payload, user)
    request.state.operation_changed_fields = sorted(provided)
    response.headers["Cache-Control"] = "no-store"
    return ok(
        _public_service(
            context,
            workspace_id=str(user["workspace_id"]),
            user_id=str(user["id"]),
            service_id=service_id,
        )
    )


async def admin_notification_services_archive(
    service_id: str,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    _ready(context)
    _shared_service_or_404(context, service_id, user)
    archived = context.notification_targets.archive(
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        target_id=service_id,
    )
    request.state.operation_changed_fields = ["archived"]
    response.headers["Cache-Control"] = "no-store"
    return ok({"service_id": service_id, "archived": archived})


async def admin_notification_services_test_and_enable(
    service_id: str,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    _ready(context)
    result = await run_in_threadpool(
        context.notification_targets.send_test_and_enable,
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        target_id=service_id,
    )
    request.state.operation_changed_fields = ["enabled", "last_test_status"]
    response.headers["Cache-Control"] = "no-store"
    return ok(public_notification_test_result(result))


async def notification_targets_create(
    payload: NotificationTargetCreateRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    _ready(context)
    if payload.scope == "private":
        raise ApiError(
            "notification_target_private_creation_disabled",
            "new private notification targets are no longer available",
            status_code=409,
        )
    created = context.notification_targets.create(
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        **payload.model_dump(exclude_unset=True),
    )
    request.state.operation_changed_fields = sorted(payload.model_fields_set)
    response.headers["Cache-Control"] = "no-store"
    return ok(created)


async def notification_targets_patch(
    target_id: str,
    payload: NotificationTargetPatchRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    _ready(context)
    if not payload.model_fields_set:
        raise ApiError(
            "invalid_notification_target",
            "at least one notification target field is required",
            status_code=400,
        )
    if any(
        field in payload.model_fields_set and getattr(payload, field) is None
        for field in (
            "name",
            "enabled",
            "email_address",
            "webhook_url",
            "webhook_provider",
            "telegram_chat_id",
        )
    ):
        raise ApiError(
            "invalid_notification_target",
            "notification target fields cannot be null",
            status_code=400,
        )
    updated = context.notification_targets.update(
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        target_id=target_id,
        **payload.model_dump(exclude_unset=True),
    )
    request.state.operation_changed_fields = sorted(payload.model_fields_set)
    response.headers["Cache-Control"] = "no-store"
    return ok(updated)


async def notification_targets_archive(
    target_id: str,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    _ready(context)
    archived = context.notification_targets.archive(
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        target_id=target_id,
    )
    request.state.operation_changed_fields = ["archived"]
    response.headers["Cache-Control"] = "no-store"
    return ok({"target_id": target_id, "archived": archived})


async def notification_targets_test(
    target_id: str,
    response: Response,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    _ready(context)
    result = await run_in_threadpool(
        context.notification_targets.send_test,
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        target_id=target_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return ok(public_notification_test_result(result))


async def notification_settings_get(
    response: Response,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    _ready(context)
    response.headers["Cache-Control"] = "no-store"
    return ok(
        context.preferred_source_notifications.get_public_settings(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
        )
    )


async def notification_settings_patch(
    payload: NotificationSettingsPatchRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    _ready(context)
    provided = payload.model_fields_set
    if not provided:
        raise ApiError(
            "invalid_notification_settings",
            "at least one notification setting is required",
            status_code=400,
        )
    if "target_ids" in provided and ({"channel", "channels"} & provided):
        raise ApiError(
            "invalid_notification_settings",
            "target_ids cannot be combined with legacy channel fields",
            status_code=400,
        )
    if "channel" in provided and "channels" in provided:
        raise ApiError(
            "invalid_notification_settings",
            "channel and channels are mutually exclusive",
            status_code=400,
        )
    if any(
        field in provided and getattr(payload, field) is None
        for field in (
            "enabled",
            "channel",
            "channels",
            "target_ids",
            "webhook_provider",
        )
    ):
        raise ApiError(
            "invalid_notification_settings",
            "enabled, channel, channels, and webhook_provider cannot be null",
            status_code=400,
        )
    updates = {
        field: getattr(payload, field)
        for field in (
            "enabled",
            "channel",
            "channels",
            "target_ids",
            "email_address",
            "webhook_url",
            "webhook_provider",
            "webhook_signing_secret",
            "telegram_chat_id",
        )
        if field in provided
    }
    updated = context.preferred_source_notifications.upsert_settings(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        **updates,
    )
    request.state.operation_changed_fields = sorted(provided)
    response.headers["Cache-Control"] = "no-store"
    return ok(updated)


async def notification_settings_test(
    response: Response,
    payload: NotificationChannelTestRequest | None = None,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    _ready(context)
    test_kwargs = (
        {"channel": payload.channel}
        if payload is not None and payload.channel is not None
        else {}
    )
    result = await run_in_threadpool(
        context.preferred_source_notifications.send_test,
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        **test_kwargs,
    )
    response.headers["Cache-Control"] = "no-store"
    return ok(public_notification_test_result(result))


def register_notification_routes(app: FastAPI) -> None:
    """Register notification routes in their compatibility-sensitive order."""

    app.add_api_route(
        "/api/notification-targets", notification_targets_get, methods=["GET"]
    )
    app.add_api_route(
        "/api/notification-services", notification_services_get, methods=["GET"]
    )
    app.add_api_route(
        "/api/admin/notification-services",
        admin_notification_services_create,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/admin/notification-services/{service_id}",
        admin_notification_services_patch,
        methods=["PATCH"],
    )
    app.add_api_route(
        "/api/admin/notification-services/{service_id}",
        admin_notification_services_archive,
        methods=["DELETE"],
    )
    app.add_api_route(
        "/api/admin/notification-services/{service_id}/test-and-enable",
        admin_notification_services_test_and_enable,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/notification-targets", notification_targets_create, methods=["POST"]
    )
    app.add_api_route(
        "/api/notification-targets/{target_id}",
        notification_targets_patch,
        methods=["PATCH"],
    )
    app.add_api_route(
        "/api/notification-targets/{target_id}",
        notification_targets_archive,
        methods=["DELETE"],
    )
    app.add_api_route(
        "/api/notification-targets/{target_id}/test",
        notification_targets_test,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/me/notification-settings", notification_settings_get, methods=["GET"]
    )
    app.add_api_route(
        "/api/me/notification-settings",
        notification_settings_patch,
        methods=["PATCH"],
    )
    app.add_api_route(
        "/api/me/notification-settings/test",
        notification_settings_test,
        methods=["POST"],
    )
