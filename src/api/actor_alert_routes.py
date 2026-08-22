"""Apify Actor alert settings and incident HTTP adapters."""

from typing import Any, Literal

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool
from starlette.concurrency import run_in_threadpool

from .context import ApiContext
from .notification_routes import (
    NotificationChannelTestRequest,
    public_notification_test_result,
)
from .responses import ApiError, ok
from .system_auth import api_context, current_admin


class ApifyActorAlertSettingsPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    enabled: StrictBool | None = None
    channel: Literal["email", "webhook", "telegram"] | None = None
    channels: list[Literal["email", "webhook", "telegram"]] | None = None
    target_ids: list[str] | None = None
    events: list[
        Literal[
            "actor_switched",
            "route_exhausted",
            "quota_low",
            "budget_blocked",
            "start_outcome_unknown",
            "recovered",
        ]
    ] | None = None
    email_address: str | None = Field(default=None, max_length=320)
    webhook_url: str | None = Field(default=None, max_length=4096)
    webhook_provider: Literal[
        "generic_event",
        "generic_text",
        "feishu_lark_v2",
        "wecom",
        "dingtalk",
        "slack",
        "discord",
    ] | None = None
    webhook_signing_secret: str | None = Field(default=None, max_length=4096)
    telegram_chat_id: str | None = Field(default=None, max_length=128)


def _require_actor_alerts(context: ApiContext) -> None:
    context.require_webhook_providers()
    context.require_notification_targets()


async def admin_apify_actor_alert_settings(
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    _require_actor_alerts(context)
    response.headers["Cache-Control"] = "no-store"
    return ok(
        context.apify_actor_alerts.get_public_settings(
            workspace_id=str(user["workspace_id"])
        )
    )


async def admin_apify_actor_alert_settings_patch(
    payload: ApifyActorAlertSettingsPatchRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    _require_actor_alerts(context)
    if not payload.model_fields_set:
        raise ApiError(
            "invalid_apify_actor_alert_settings",
            "at least one alert setting is required",
            status_code=400,
        )
    if "target_ids" in payload.model_fields_set and (
        {"channel", "channels"} & payload.model_fields_set
    ):
        raise ApiError(
            "invalid_apify_actor_alert_settings",
            "target_ids cannot be combined with legacy channel fields",
            status_code=400,
        )
    if {"channel", "channels"} <= payload.model_fields_set:
        raise ApiError(
            "invalid_apify_actor_alert_settings",
            "channel and channels are mutually exclusive",
            status_code=400,
        )
    if any(
        field in payload.model_fields_set and getattr(payload, field) is None
        for field in (
            "enabled",
            "channel",
            "channels",
            "target_ids",
            "events",
            "webhook_provider",
        )
    ):
        raise ApiError(
            "invalid_apify_actor_alert_settings",
            "enabled, channel, channels, events, and webhook_provider cannot be null",
            status_code=400,
        )
    updates = {field: getattr(payload, field) for field in payload.model_fields_set}
    updated = context.apify_actor_alerts.upsert_settings(
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        **updates,
    )
    request.state.operation_changed_fields = sorted(updates)
    response.headers["Cache-Control"] = "no-store"
    return ok(updated)


async def admin_apify_actor_alert_settings_test(
    response: Response,
    payload: NotificationChannelTestRequest | None = None,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    _require_actor_alerts(context)
    test_kwargs = (
        {"channel": payload.channel}
        if payload is not None and payload.channel is not None
        else {}
    )
    result = await run_in_threadpool(
        context.apify_actor_alerts.send_test,
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        **test_kwargs,
    )
    response.headers["Cache-Control"] = "no-store"
    return ok(public_notification_test_result(result))


async def admin_apify_actor_alert_incidents(
    response: Response,
    limit: int = 20,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    _require_actor_alerts(context)
    response.headers["Cache-Control"] = "no-store"
    return ok(
        {
            "schema_version": 3,
            "incidents": context.apify_actor_alerts.list_incidents(
                workspace_id=str(user["workspace_id"]),
                limit=max(1, min(int(limit), 100)),
            ),
        }
    )


def register_actor_alert_routes(app: FastAPI) -> None:
    """Register Actor alert routes in their stable order."""

    app.add_api_route(
        "/api/admin/apify-actor-alert-settings",
        admin_apify_actor_alert_settings,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/admin/apify-actor-alert-settings",
        admin_apify_actor_alert_settings_patch,
        methods=["PATCH"],
    )
    app.add_api_route(
        "/api/admin/apify-actor-alert-settings/test",
        admin_apify_actor_alert_settings_test,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/admin/apify-actor-alert-incidents",
        admin_apify_actor_alert_incidents,
        methods=["GET"],
    )
