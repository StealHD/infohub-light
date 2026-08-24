"""Current-user Agent delegation HTTP routes."""

from __future__ import annotations

from typing import Any, Literal

from fastapi import Depends, FastAPI, Response
from pydantic import BaseModel, ConfigDict, Field, field_validator

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_user
from ..storage.service_store import (
    AGENT_DELEGATION_MAX_ACTIVE,
    AGENT_DELEGATION_TTL_DAYS,
    AgentDelegationLimitError,
)


class AgentDelegationRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str = Field(min_length=1, max_length=80)
    access: Literal["read", "subscriptions_write", "system_settings_write"] = "read"
    diagnostics_scope: Literal["self", "workspace"] = "self"

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


async def agent_delegations_list(
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    settings = context.remote_mcp_settings
    return ok(
        {
            "enabled": settings.enabled,
            "mcp_url": settings.public_url,
            "subscription_writes_enabled": settings.subscription_writes_enabled,
            "system_settings_writes_enabled": settings.system_settings_writes_enabled,
            "openclaw_chat": context.openclaw_chat_settings.public_config(),
            "token_ttl_days": AGENT_DELEGATION_TTL_DAYS,
            "max_active": AGENT_DELEGATION_MAX_ACTIVE,
            "connections": context.store.list_agent_delegations(user["id"]),
        }
    )


async def agent_delegations_create(
    payload: AgentDelegationRequest,
    response: Response,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    settings = context.remote_mcp_settings
    if not settings.enabled:
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
        if not settings.subscription_writes_enabled:
            raise ApiError(
                "subscription_writes_disabled",
                "subscription writes are disabled",
                status_code=409,
                action="Ask an administrator to enable subscription writes.",
            )
    if payload.access == "system_settings_write":
        if user.get("role") not in {"owner", "admin"}:
            raise ApiError(
                "forbidden",
                "system settings connections require owner or admin role",
                status_code=403,
            )
        if not settings.system_settings_writes_enabled:
            raise ApiError(
                "system_settings_writes_disabled",
                "system settings writes are disabled",
                status_code=409,
                action="Ask an administrator to enable system settings writes.",
            )
    if (
        payload.diagnostics_scope == "workspace"
        and user.get("role") not in {"owner", "admin"}
    ):
        raise ApiError(
            "forbidden",
            "workspace diagnostics require owner or admin role",
            status_code=403,
        )
    try:
        connection, token = context.store.create_agent_delegation(
            workspace_id=user["workspace_id"],
            user_id=user["id"],
            name=payload.name,
            access=payload.access,
            diagnostics_scope=payload.diagnostics_scope,
        )
    except PermissionError as exc:
        raise ApiError(
            "forbidden",
            "workspace diagnostics require owner or admin role",
            status_code=403,
        ) from exc
    except AgentDelegationLimitError as exc:
        raise ApiError(
            "agent_delegation_limit",
            str(exc),
            status_code=409,
            action="Revoke an unused connection before creating another.",
        ) from exc
    response.headers["Cache-Control"] = "no-store"
    return ok({"connection": connection, "token": token})


async def agent_delegations_patch(
    delegation_id: str,
    payload: AgentDelegationRenameRequest,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    connection = context.store.rename_agent_delegation(
        user["id"], delegation_id, payload.name
    )
    if connection is None:
        raise ApiError("not_found", "connection not found", status_code=404)
    return ok(connection)


async def agent_delegations_delete(
    delegation_id: str,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    if not context.store.revoke_agent_delegation(user["id"], delegation_id):
        raise ApiError("not_found", "connection not found", status_code=404)
    return ok({"revoked": True})


async def agent_delegations_record_delete(
    delegation_id: str,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    deleted = context.store.delete_revoked_agent_delegation(
        user["id"], delegation_id
    )
    if deleted is None:
        raise ApiError("not_found", "connection not found", status_code=404)
    if deleted is False:
        raise ApiError(
            "agent_delegation_not_revoked",
            "connection must be revoked before deletion",
            status_code=409,
        )
    return ok({"deleted": True})


def register_agent_delegation_routes(app: FastAPI) -> None:
    """Register delegation routes in their compatibility-sensitive order."""

    app.add_api_route(
        "/api/me/agent-delegations", agent_delegations_list, methods=["GET"]
    )
    app.add_api_route(
        "/api/me/agent-delegations",
        agent_delegations_create,
        methods=["POST"],
        status_code=201,
    )
    app.add_api_route(
        "/api/me/agent-delegations/{delegation_id}",
        agent_delegations_patch,
        methods=["PATCH"],
    )
    app.add_api_route(
        "/api/me/agent-delegations/{delegation_id}",
        agent_delegations_delete,
        methods=["DELETE"],
    )
    app.add_api_route(
        "/api/me/agent-delegations/{delegation_id}/record",
        agent_delegations_record_delete,
        methods=["DELETE"],
    )
