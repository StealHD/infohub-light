"""User subscription and source-health HTTP adapters."""

from typing import Any, Literal

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, Field, StrictBool, StrictInt, field_validator

from .context import ApiContext
from .responses import ApiError, ok
from .schedule_routes import bulk_source_schedule_jobs, source_schedule_payload
from .system_auth import (
    api_context,
    current_user,
    require_mutating_member,
    visible_source_or_404,
)
from ..services.subscription_mutation import SubscriptionActor


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


async def subscriptions_list(
    schedule_view: Literal["full", "summary"] = "full",
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    subscriptions = context.store.list_user_subscriptions(user["id"])
    schedules = context.source_schedules.list_user_subscription_schedules(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        subscriptions=subscriptions,
    )
    availability = context.runtime_status.availability()
    last_jobs: dict[str, dict[str, Any]] = {}
    active_jobs: dict[str, dict[str, Any]] = {}
    if schedule_view == "full":
        last_jobs, active_jobs = bulk_source_schedule_jobs(
            user, schedules, context.store
        )
    return ok(
        {
            "subscriptions": [
                {
                    **subscription,
                    "schedule": source_schedule_payload(
                        schedules[str(subscription["id"])],
                        worker_status=str(availability["worker_status"]),
                        view=schedule_view,
                        last_job=last_jobs.get(str(subscription["id"])),
                        active_job=active_jobs.get(str(subscription["id"])),
                    ),
                }
                for subscription in subscriptions
            ]
        }
    )


async def source_health_get(
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    return ok(
        context.source_health.user_projection(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            feed_window_days=context.feed_window_days(),
        )
    )


async def subscriptions_create(
    payload: SubscriptionRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    if payload.notify_on_new_items and (
        payload.analysis_mode == "personal_only" or not payload.enabled
    ):
        raise ApiError(
            "invalid_subscription_notification",
            "disabled or personal_only subscriptions cannot send new-item notifications",
            status_code=400,
            action=(
                "Enable the subscription in full analysis mode or leave "
                "notifications disabled."
            ),
        )
    visible_source_or_404(context.store, payload.source_id, user)
    notification_values = (
        {"notify_on_new_items": payload.notify_on_new_items}
        if "notify_on_new_items" in payload.model_fields_set
        else {}
    )
    subscription = context.subscription_mutations.rest_create_subscription(
        SubscriptionActor.from_user(user),
        source_id=payload.source_id,
        values={
            "enabled": payload.enabled,
            "override_channel": payload.override_channel,
            "override_topics": payload.override_topics,
            "personal_tags": payload.personal_tags,
            "analysis_mode": payload.analysis_mode,
            "priority": payload.priority,
            **notification_values,
        },
    )
    request.state.operation_source_id = str(subscription["source_id"])
    request.state.operation_subscription_id = str(subscription["id"])
    request.state.operation_changed_fields = sorted(payload.model_fields_set)
    return ok(subscription)


async def subscriptions_patch(
    subscription_id: str,
    payload: SubscriptionPatchRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
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
    current = context.store.get_subscription(subscription_id)
    if payload.notify_on_new_items is True and (
        payload.analysis_mode == "personal_only"
        or payload.enabled is False
        or (
            payload.enabled is not True
            and current is not None
            and current.get("user_id") == user["id"]
            and not bool(current.get("enabled"))
        )
    ):
        raise ApiError(
            "invalid_subscription_notification",
            "disabled or personal_only subscriptions cannot send new-item notifications",
            status_code=400,
            action=(
                "Enable the subscription in full analysis mode before enabling "
                "notifications."
            ),
        )
    if (
        payload.notify_on_new_items is True
        and payload.analysis_mode is None
        and current is not None
        and current.get("user_id") == user["id"]
        and current.get("analysis_mode") == "personal_only"
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
    updated = context.subscription_mutations.rest_update_subscription(
        SubscriptionActor.from_user(user),
        subscription_id=subscription_id,
        updates=updates,
    )
    request.state.operation_source_id = str(updated["source_id"])
    request.state.operation_changed_fields = sorted(provided)
    return ok(updated)


async def subscriptions_delete(
    subscription_id: str,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    context.subscription_mutations.rest_delete_subscription(
        SubscriptionActor.from_user(user), subscription_id=subscription_id
    )
    return ok({"deleted": True})


def register_subscription_list_route(app: FastAPI) -> None:
    app.add_api_route(
        "/api/me/subscriptions", subscriptions_list, methods=["GET"]
    )


def register_source_health_route(app: FastAPI) -> None:
    app.add_api_route(
        "/api/me/source-health", source_health_get, methods=["GET"]
    )


def register_subscription_mutation_routes(app: FastAPI) -> None:
    app.add_api_route(
        "/api/me/subscriptions", subscriptions_create, methods=["POST"]
    )
    app.add_api_route(
        "/api/me/subscriptions/{subscription_id}",
        subscriptions_patch,
        methods=["PATCH"],
    )


def register_subscription_delete_route(app: FastAPI) -> None:
    app.add_api_route(
        "/api/me/subscriptions/{subscription_id}",
        subscriptions_delete,
        methods=["DELETE"],
    )
