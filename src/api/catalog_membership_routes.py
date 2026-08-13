"""Catalog browsing, sharing, and subscription HTTP adapters."""

from typing import Any, Literal

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import (
    api_context,
    current_user,
    is_admin,
    require_mutating_member,
    visible_source_or_404,
)
from ..services.subscription_mutation import SubscriptionActor


class SourceShareRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    scope: Literal["public", "workspace"]


def _manageable_source_or_404(
    context: ApiContext,
    source_id: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    source = context.store.get_source(source_id)
    if source is None or source.get("workspace_id") != user.get("workspace_id"):
        raise ApiError("not_found", "source not found", status_code=404)
    if (
        source.get("scope") == "private"
        and source.get("owner_user_id") != user.get("id")
    ):
        raise ApiError("not_found", "source not found", status_code=404)
    return source


async def catalog_sources(
    include_disabled: bool = False,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    if include_disabled and not is_admin(user):
        raise ApiError(
            "forbidden",
            "admin role required to list disabled sources",
            status_code=403,
        )
    sources = context.store.list_visible_sources(
        user,
        include_disabled=include_disabled,
    )
    return ok(
        {"sources": [context.public_source(source, user) for source in sources]}
    )


async def catalog_source_usage(
    source_id: str,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    visible_source_or_404(context.store, source_id, user)
    return ok(
        {
            "source_id": source_id,
            **context.store.source_subscription_usage(source_id),
        }
    )


async def catalog_source_share(
    source_id: str,
    payload: SourceShareRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    shared = context.subscription_mutations.rest_share_source(
        SubscriptionActor.from_user(user),
        source_id=source_id,
        target_scope=payload.scope,
    )
    request.state.operation_changed_fields = ["scope"]
    return ok(
        {
            "source": context.public_source(shared, user),
            "management_transferred": True,
            "notice": "来源地址和管理权已转交工作区管理员；你的取消订阅不会影响其他成员。",
        }
    )


async def catalog_delete(
    source_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    source = _manageable_source_or_404(context, source_id, user)
    if source["scope"] != "private" and not is_admin(user):
        raise ApiError(
            "forbidden", "only admins can delete shared sources", status_code=403
        )
    if source["scope"] == "private" and source["owner_user_id"] != user["id"]:
        raise ApiError(
            "forbidden",
            "cannot delete another user's private source",
            status_code=403,
        )
    updated = context.subscription_mutations.rest_update_source(
        SubscriptionActor.from_user(user),
        source_id=source_id,
        updates={"enabled": False},
    )
    internal_safe = dict(updated)
    internal_safe.pop("enforce_public_network", None)
    request.state.operation_changed_fields = ["enabled"]
    return ok(internal_safe)


async def catalog_subscribe(
    source_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    visible_source_or_404(context.store, source_id, user)
    subscription = context.subscription_mutations.rest_create_subscription(
        SubscriptionActor.from_user(user),
        source_id=source_id,
        values={},
    )
    request.state.operation_subscription_id = str(subscription["id"])
    return ok({"subscription": subscription})


async def catalog_unsubscribe(
    source_id: str,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    require_mutating_member(user)
    visible_source_or_404(context.store, source_id, user)
    subscription = context.store.get_user_subscription_for_source(
        user["id"], source_id
    )
    if not subscription:
        raise ApiError("not_found", "subscription not found", status_code=404)
    request.state.operation_subscription_id = str(subscription["id"])
    return ok(
        {
            "deleted": context.subscription_mutations.rest_delete_subscription(
                SubscriptionActor.from_user(user),
                subscription_id=subscription["id"],
            )
        }
    )


def register_catalog_list_route(app: FastAPI) -> None:
    app.add_api_route("/api/catalog/sources", catalog_sources, methods=["GET"])


def register_catalog_membership_routes(app: FastAPI) -> None:
    """Register Catalog membership routes in their stable order."""

    app.add_api_route(
        "/api/catalog/sources/{source_id}/usage",
        catalog_source_usage,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/catalog/sources/{source_id}/share",
        catalog_source_share,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/catalog/sources/{source_id}", catalog_delete, methods=["DELETE"]
    )
    app.add_api_route(
        "/api/catalog/sources/{source_id}/subscribe",
        catalog_subscribe,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/catalog/sources/{source_id}/subscription",
        catalog_unsubscribe,
        methods=["DELETE"],
    )
