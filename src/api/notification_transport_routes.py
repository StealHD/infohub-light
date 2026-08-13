"""Workspace notification transport HTTP adapters."""

from typing import Any, Literal

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_admin


class NotificationEmailTransportPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    provider: Literal[
        "qq",
        "netease",
        "gmail",
        "resend",
        "amazon_ses",
    ] | None = None
    sender_email: str | None = Field(default=None, min_length=3, max_length=320)
    sender_name: str | None = Field(default=None, min_length=1, max_length=80)
    credential: str | None = Field(default=None, max_length=4096)
    enabled: StrictBool | None = None
    region: str | None = Field(default=None, max_length=64)
    smtp_username: str | None = Field(default=None, max_length=320)


class NotificationEmailTransportTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    recipient_email: str = Field(min_length=3, max_length=320)


class NotificationTelegramTransportPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    bot_token: str | None = Field(default=None, max_length=256)
    enabled: StrictBool | None = None


class NotificationTelegramTransportTestRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    chat_id: str = Field(min_length=1, max_length=128)


async def admin_notification_email_transport_get(
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_notification_targets()
    response.headers["Cache-Control"] = "no-store"
    return ok(
        context.workspace_email_transport.get_public_settings(
            workspace_id=str(user["workspace_id"]),
        )
    )


async def admin_notification_email_transport_patch(
    payload: NotificationEmailTransportPatchRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_notification_targets()
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
    updated = context.workspace_email_transport.upsert(
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        **updates,
    )
    request.state.operation_changed_fields = sorted(provided)
    response.headers["Cache-Control"] = "no-store"
    return ok(updated)


async def admin_notification_email_transport_delete(
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_notification_targets()
    deleted = context.workspace_email_transport.delete(
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
    )
    response.headers["Cache-Control"] = "no-store"
    return ok({"deleted": deleted})


async def admin_notification_email_transport_test(
    payload: NotificationEmailTransportTestRequest,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_notification_targets()
    result = await run_in_threadpool(
        context.workspace_email_transport.send_test,
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        recipient_email=payload.recipient_email,
    )
    response.headers["Cache-Control"] = "no-store"
    return ok(result)


async def admin_notification_telegram_transport_get(
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_notification_targets()
    response.headers["Cache-Control"] = "no-store"
    return ok(
        context.workspace_telegram_transport.get_public_settings(
            workspace_id=str(user["workspace_id"]),
        )
    )


async def admin_notification_telegram_transport_patch(
    payload: NotificationTelegramTransportPatchRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_notification_targets()
    provided = payload.model_fields_set
    if not provided:
        raise ApiError(
            "invalid_telegram_transport",
            "at least one Telegram transport setting is required",
            status_code=400,
        )
    if "enabled" in provided and payload.enabled is None:
        raise ApiError(
            "invalid_telegram_transport",
            "enabled cannot be null",
            status_code=400,
        )
    updates = {
        field: getattr(payload, field)
        for field in ("bot_token", "enabled")
        if field in provided
    }
    updated = context.workspace_telegram_transport.upsert(
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        **updates,
    )
    request.state.operation_changed_fields = sorted(provided)
    response.headers["Cache-Control"] = "no-store"
    return ok(updated)


async def admin_notification_telegram_transport_delete(
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_notification_targets()
    deleted = context.workspace_telegram_transport.delete(
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
    )
    response.headers["Cache-Control"] = "no-store"
    return ok({"deleted": deleted})


async def admin_notification_telegram_transport_test(
    payload: NotificationTelegramTransportTestRequest,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_notification_channels()
    result = await run_in_threadpool(
        context.workspace_telegram_transport.send_test,
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        chat_id=payload.chat_id,
    )
    response.headers["Cache-Control"] = "no-store"
    return ok(
        {
            "sent": bool(result.get("sent")),
            "generation": int(result.get("generation") or 0),
        }
    )


def register_notification_transport_routes(app: FastAPI) -> None:
    """Register workspace transport routes in their stable order."""

    app.add_api_route(
        "/api/admin/notification-email-transport",
        admin_notification_email_transport_get,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/admin/notification-email-transport",
        admin_notification_email_transport_patch,
        methods=["PATCH"],
    )
    app.add_api_route(
        "/api/admin/notification-email-transport",
        admin_notification_email_transport_delete,
        methods=["DELETE"],
    )
    app.add_api_route(
        "/api/admin/notification-email-transport/test",
        admin_notification_email_transport_test,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/admin/notification-telegram-transport",
        admin_notification_telegram_transport_get,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/admin/notification-telegram-transport",
        admin_notification_telegram_transport_patch,
        methods=["PATCH"],
    )
    app.add_api_route(
        "/api/admin/notification-telegram-transport",
        admin_notification_telegram_transport_delete,
        methods=["DELETE"],
    )
    app.add_api_route(
        "/api/admin/notification-telegram-transport/test",
        admin_notification_telegram_transport_test,
        methods=["POST"],
    )
