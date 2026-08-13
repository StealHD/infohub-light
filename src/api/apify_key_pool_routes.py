"""Workspace Apify Key pool HTTP adapters."""

from typing import Any

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictInt

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_admin
from ..services.apify_key_pool import (
    ApifyKeyDrainPendingError,
    ApifyKeyPoolError,
)


class ApifyKeyPoolOrderRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_ids: list[str]
    expected_generation: StrictInt = Field(ge=1)


class ApifyValidationKeyRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    secret_id: str | None = Field(default=None, min_length=1, max_length=128)
    expected_generation: StrictInt = Field(ge=1)


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


async def admin_apify_key_pool(
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_apify_actor_resilience()
    return ok(context.apify_key_pool.public_state(str(user["workspace_id"])))


async def admin_apify_key_pool_order(
    payload: ApifyKeyPoolOrderRequest,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_apify_actor_resilience()
    try:
        state = context.apify_key_pool.reorder(
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


async def admin_apify_validation_key(
    payload: ApifyValidationKeyRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_apify_actor_resilience()
    try:
        state = context.apify_key_pool.set_validation_key(
            str(user["workspace_id"]),
            secret_id=payload.secret_id,
            expected_generation=int(payload.expected_generation),
        )
    except LookupError as exc:
        raise ApiError(
            "not_found", "Apify Key pool member not found", status_code=404
        ) from exc
    except ApifyKeyPoolError as exc:
        raise pool_api_error(exc) from exc
    resilience = context.apify_actor_resilience_for(str(user["workspace_id"]))
    resilience.emit_event(
        phase="validation_key",
        outcome="succeeded",
        reason_code=("assigned" if payload.secret_id else "unassigned"),
        request_id=getattr(request.state, "operation_request_id", None),
    )
    request.state.operation_changed_fields = ["validation_key"]
    response.headers["Cache-Control"] = "no-store"
    return ok(state)


async def admin_apify_key_pool_drain(
    secret_id: str,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.require_apify_actor_resilience()
    state = context.apify_key_pool.public_state(str(user["workspace_id"]))
    if secret_id not in {str(member["secret_id"]) for member in state["members"]}:
        raise ApiError(
            "not_found", "Apify Key pool member not found", status_code=404
        )
    try:
        state = context.apify_key_pool.begin_drain(secret_id)
        if state["status"] == "draining":
            try:
                state = context.apify_key_pool.complete_drain_and_failover(
                    str(user["workspace_id"])
                )
            except ApifyKeyDrainPendingError:
                state = context.apify_key_pool.public_state(
                    str(user["workspace_id"])
                )
    except ApifyKeyPoolError as exc:
        raise pool_api_error(exc) from exc
    return ok(state)


def register_apify_key_pool_routes(app: FastAPI) -> None:
    """Register Key pool routes in their stable order."""

    app.add_api_route(
        "/api/admin/apify-key-pool", admin_apify_key_pool, methods=["GET"]
    )
    app.add_api_route(
        "/api/admin/apify-key-pool/order",
        admin_apify_key_pool_order,
        methods=["PUT"],
    )
    app.add_api_route(
        "/api/admin/apify-key-pool/validation-key",
        admin_apify_validation_key,
        methods=["PUT"],
    )
    app.add_api_route(
        "/api/admin/apify-key-pool/{secret_id}/drain",
        admin_apify_key_pool_drain,
        methods=["POST"],
    )
