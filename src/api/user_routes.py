"""Workspace member-administration HTTP routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Request
from pydantic import BaseModel, ConfigDict

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_admin
from ..storage.service_store import (
    ROLES,
    UserActiveJobsError,
    UsernameConflictError,
)


class UserCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str
    password: str
    role: str = "member"
    display_name: str | None = None
    enabled: bool = True


class UserPatchRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    username: str | None = None
    role: str | None = None
    display_name: str | None = None
    enabled: bool | None = None
    password: str | None = None


async def users_list(
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    users = context.store.list_users(workspace_id=user["workspace_id"])
    return ok({"users": [context.store.sanitize_user(item) for item in users]})


async def users_create(
    payload: UserCreateRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    if payload.role not in ROLES or payload.role == "owner":
        raise ApiError("invalid_role", "role must be admin, member, or viewer")
    try:
        created = context.store.create_user(
            workspace_id=user["workspace_id"],
            username=payload.username,
            password=payload.password,
            role=payload.role,
            display_name=payload.display_name,
            enabled=payload.enabled,
        )
    except UsernameConflictError as exc:
        raise ApiError(
            "username_conflict",
            "username already exists",
            status_code=409,
            action="Choose another username.",
        ) from exc
    request.state.operation_subject_user_id = str(created["id"])
    request.state.operation_changed_fields = [
        "display_name",
        "enabled",
        "password",
        "role",
        "username",
    ]
    return ok(context.store.sanitize_user(created))


async def users_patch(
    user_id: str,
    payload: UserPatchRequest,
    request: Request,
    admin: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    current = context.store.get_user(user_id)
    if current is None or current["workspace_id"] != admin["workspace_id"]:
        raise ApiError("not_found", "user not found", status_code=404)
    if current["role"] == "owner":
        raise ApiError(
            "owner_protected",
            "owner accounts cannot be changed by member administration",
            status_code=409,
        )
    if payload.role is not None and (
        payload.role not in ROLES or payload.role == "owner"
    ):
        raise ApiError(
            "invalid_role",
            "role must be admin, member, or viewer",
            status_code=400,
        )
    password = payload.password.strip() if payload.password else None
    try:
        updated = context.store.update_user(
            user_id,
            username=payload.username,
            role=payload.role,
            enabled=payload.enabled,
            display_name=payload.display_name,
            password=password or None,
        )
    except UsernameConflictError as exc:
        raise ApiError(
            "username_conflict",
            "username already exists",
            status_code=409,
            action="Choose another username.",
        ) from exc
    request.state.operation_subject_user_id = user_id
    request.state.operation_changed_fields = sorted(payload.model_fields_set)
    return ok(context.store.sanitize_user(updated))


async def users_delete(
    user_id: str,
    request: Request,
    admin: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    current = context.store.get_user(user_id)
    if current is None or current["workspace_id"] != admin["workspace_id"]:
        raise ApiError("not_found", "user not found", status_code=404)
    if current["role"] == "owner":
        raise ApiError(
            "owner_protected",
            "owner accounts cannot be deleted",
            status_code=409,
        )
    if user_id == admin["id"]:
        raise ApiError(
            "cannot_delete_self",
            "administrators cannot delete their current account",
            status_code=409,
            action="Ask another administrator to delete this account.",
        )
    try:
        deleted = context.store.delete_user(
            user_id,
            reassigned_user_id=str(admin["id"]),
        )
    except UserActiveJobsError as exc:
        raise ApiError(
            "user_has_active_jobs",
            "the account still has a running job",
            status_code=409,
            retryable=True,
            action="Wait for the running job to finish, then retry deletion.",
        ) from exc
    request.state.operation_subject_user_id = user_id
    request.state.operation_changed_fields = ["deleted"]
    return ok({"deleted": deleted, "id": user_id})


def register_user_routes(app: FastAPI) -> None:
    """Register member routes in their compatibility-sensitive order."""

    app.add_api_route("/api/users", users_list, methods=["GET"])
    app.add_api_route("/api/users", users_create, methods=["POST"])
    app.add_api_route("/api/users/{user_id}", users_patch, methods=["PATCH"])
    app.add_api_route("/api/users/{user_id}", users_delete, methods=["DELETE"])
