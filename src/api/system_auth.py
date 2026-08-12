"""System health and session-authentication API routes."""

from __future__ import annotations

import os
from typing import Any

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field

from .context import ApiContext
from .responses import ApiError, ok
from ..auth import COOKIE_NAME
from ..logging_utils import logging_health_status
from ..services.operation_log import bind_operation_actor
from ..storage.service_store import ServiceStore


class LoginRequest(BaseModel):
    username: str
    password: str


class PasswordChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    current_password: str
    new_password: str = Field(min_length=8, max_length=200)


def api_context(request: Request) -> ApiContext:
    """Resolve the app-owned typed API context for a request."""

    return request.app.state.api_context


async def current_user(
    request: Request,
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    """Require a current session and bind its actor to operation logging."""

    token = request.cookies.get(COOKIE_NAME)
    user = context.store.get_session_user(token)
    if not user:
        raise ApiError(
            "unauthorized",
            "login required",
            status_code=401,
            action="Log in and retry.",
        )
    _bind_request_actor(request, user)
    return user


def _bind_request_actor(request: Request, user: dict[str, Any]) -> None:
    workspace_id = str(user["workspace_id"])
    user_id = str(user["id"])
    bind_operation_actor(workspace_id=workspace_id, user_id=user_id)
    request.state.operation_workspace_id = workspace_id
    request.state.operation_actor_user_id = user_id


async def auth_status(
    request: Request,
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    user = context.store.get_session_user(request.cookies.get(COOKIE_NAME))
    return ok(
        {
            "authenticated": bool(user),
            "user": context.store.sanitize_user(user) if user else None,
        }
    )


async def health_live() -> dict[str, Any]:
    return ok(
        {
            "status": "live",
            "version": os.getenv("INTELISCOPE_VERSION", "1.5.0"),
            "revision": os.getenv("INTELISCOPE_BUILD_REVISION", "unknown"),
            "built_at": os.getenv("INTELISCOPE_BUILT_AT", "unknown"),
        }
    )


async def health_ready(
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    store = context.store
    store.connect().execute("SELECT 1").fetchone()
    _require_content_migrations(store)
    for readiness_check in context.readiness_checks:
        readiness_check()
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
    availability = context.runtime_status.availability()
    logging_status = logging_health_status()["status"]
    require_worker = (
        os.getenv("HORIZON_REQUIRE_WORKER_FOR_READINESS", "false").lower()
        == "true"
    )
    if require_worker and availability["worker_status"] != "ready":
        raise ApiError(
            "worker_unavailable",
            f"worker status is {availability['worker_status']}",
            status_code=503,
            retryable=True,
            action="Start or inspect horizon-worker.",
        )
    return ok(
        {
            "status": "ready",
            "database": "ready",
            "worker_status": availability["worker_status"],
            "logging_status": logging_status,
            "checked_at": availability["checked_at"],
        }
    )


def _require_content_migrations(store: ServiceStore) -> None:
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


async def auth_login(
    payload: LoginRequest,
    request: Request,
    response: Response,
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    user = context.store.authenticate_user(payload.username, payload.password)
    if not user:
        raise ApiError(
            "invalid_credentials",
            "username or password is incorrect",
            status_code=401,
        )
    _bind_request_actor(request, user)
    token = context.store.create_session(
        user["id"],
        ttl_seconds=context.auth_settings.session_ttl_seconds,
    )
    response.set_cookie(
        COOKIE_NAME,
        token,
        httponly=True,
        samesite="lax",
        secure=context.auth_settings.cookie_secure,
        max_age=context.auth_settings.session_ttl_seconds,
    )
    return ok(
        {
            "authenticated": True,
            "user": context.store.sanitize_user(user),
        }
    )


async def auth_logout(
    request: Request,
    response: Response,
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    session_token = request.cookies.get(COOKIE_NAME)
    user = context.store.get_session_user(session_token)
    if user is not None:
        _bind_request_actor(request, user)
    context.store.delete_session(session_token)
    response.delete_cookie(
        COOKIE_NAME,
        httponly=True,
        samesite="lax",
        secure=context.auth_settings.cookie_secure,
    )
    return ok({"authenticated": False, "user": None})


async def me_password_change(
    payload: PasswordChangeRequest,
    request: Request,
    user: dict[str, Any] = Depends(current_user),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    authenticated = context.store.authenticate_user(
        user["username"], payload.current_password
    )
    if authenticated is None or authenticated["id"] != user["id"]:
        raise ApiError(
            "invalid_current_password",
            "current password is incorrect",
            status_code=400,
        )
    context.store.update_user(user["id"], password=payload.new_password)
    request.state.operation_changed_fields = ["password"]
    return ok({"changed": True})


def register_system_auth_routes(app: FastAPI) -> None:
    """Register system/auth routes in their compatibility-sensitive order."""

    app.add_api_route("/api/auth/status", auth_status, methods=["GET"])
    app.add_api_route("/api/health/live", health_live, methods=["GET"])
    app.add_api_route("/api/health/ready", health_ready, methods=["GET"])
    app.add_api_route("/api/auth/login", auth_login, methods=["POST"])
    app.add_api_route("/api/auth/logout", auth_logout, methods=["POST"])
    app.add_api_route("/api/me/password", me_password_change, methods=["POST"])
