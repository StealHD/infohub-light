"""Owner/Admin preview-first runtime system settings routes."""

from __future__ import annotations

from typing import Any

from fastapi import Depends, FastAPI, Request, Response
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt
from starlette.concurrency import run_in_threadpool

from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_admin
from ..services.operation_log import safe_emit_operation_event
from ..services.system_settings import (
    SystemSettingsGenerationConflict,
    SystemSettingsUnavailable,
)
from ..services.system_settings_proposals import (
    SystemSettingProposalError,
    SystemSettingsActor,
)
from ..services.system_settings_registry import (
    InvalidSystemSetting,
    canonical_setting_key,
)


class SystemSettingChangeRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    key: str = Field(min_length=1, max_length=128)
    value: StrictBool | StrictInt | None


class PrepareSystemSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    expected_generation: StrictInt = Field(ge=1)
    changes: list[SystemSettingChangeRequest] = Field(min_length=1, max_length=20)


class ApplySystemSettingsRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    confirmation: str = Field(min_length=1, max_length=160)


def _actor(user: dict[str, Any]) -> SystemSettingsActor:
    return SystemSettingsActor(
        workspace_id=str(user["workspace_id"]),
        user_id=str(user["id"]),
        channel="web",
    )


def _changes(items: list[SystemSettingChangeRequest]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        key = canonical_setting_key(item.key)
        if key in result:
            raise InvalidSystemSetting(f"duplicate system setting: {key}")
        result[key] = item.value
    return result


def _api_error(error: Exception) -> ApiError:
    if isinstance(error, InvalidSystemSetting):
        return ApiError(error.code, str(error), status_code=400)
    if isinstance(error, SystemSettingsUnavailable):
        return ApiError(
            error.code,
            "系统参数数据库迁移尚未完成。",
            status_code=503,
            action=(
                "停止 API 和 Worker，然后运行 "
                "scripts/migrate_system_settings_v31.py --apply。"
            ),
        )
    if isinstance(error, SystemSettingsGenerationConflict):
        return ApiError(error.code, "系统参数已更新，请刷新后重新预览。", status_code=409)
    if isinstance(error, SystemSettingProposalError):
        status = 404 if error.code.endswith("not_found") else (
            403 if error.code.endswith(("required", "invalid")) else 409
        )
        return ApiError(error.code, str(error), status_code=status)
    return ApiError("system_settings_unavailable", "系统参数当前不可用。", status_code=503)


def _record(
    request: Request,
    user: dict[str, Any],
    *,
    action: str,
    changed_keys: list[str],
) -> None:
    request.state.operation_changed_fields = changed_keys
    safe_emit_operation_event(
        category="system_settings",
        action=action,
        outcome="succeeded",
        workspace_id=str(user["workspace_id"]),
        actor_user_id=str(user["id"]),
        changed_fields=changed_keys,
        counts={"settings": len(changed_keys)},
        route=str(request.scope.get("route").path),
        method=str(request.method),
        status_code=200,
    )
    request.state.operation_logged = True


async def list_system_settings(
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(
            context.system_settings.list_settings, str(user["workspace_id"])
        )
    except (InvalidSystemSetting, SystemSettingsUnavailable) as error:
        raise _api_error(error) from error
    response.headers["Cache-Control"] = "no-store"
    return ok(result)


async def prepare_system_settings(
    payload: PrepareSystemSettingsRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    try:
        changes = _changes(payload.changes)
        result = await run_in_threadpool(
            context.system_setting_proposals.prepare,
            _actor(user),
            expected_generation=payload.expected_generation,
            changes=changes,
        )
    except (
        InvalidSystemSetting,
        SystemSettingsUnavailable,
        SystemSettingsGenerationConflict,
        SystemSettingProposalError,
    ) as error:
        raise _api_error(error) from error
    _record(request, user, action="proposal_prepare", changed_keys=sorted(changes))
    response.headers["Cache-Control"] = "no-store"
    return ok(result)


async def apply_system_settings(
    proposal_id: str,
    payload: ApplySystemSettingsRequest,
    request: Request,
    response: Response,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    try:
        result = await run_in_threadpool(
            context.system_setting_proposals.apply,
            _actor(user),
            proposal_id=proposal_id,
            confirmation=payload.confirmation,
        )
    except (
        InvalidSystemSetting,
        SystemSettingsUnavailable,
        SystemSettingsGenerationConflict,
        SystemSettingProposalError,
    ) as error:
        raise _api_error(error) from error
    _record(
        request, user, action="proposal_apply",
        changed_keys=list(result["changed_keys"]),
    )
    response.headers["Cache-Control"] = "no-store"
    return ok(result)


def register_system_settings_routes(app: FastAPI) -> None:
    app.add_api_route(
        "/api/admin/system-settings", list_system_settings, methods=["GET"]
    )
    app.add_api_route(
        "/api/admin/system-settings/proposals",
        prepare_system_settings,
        methods=["POST"],
    )
    app.add_api_route(
        "/api/admin/system-settings/proposals/{proposal_id}/apply",
        apply_system_settings,
        methods=["POST"],
    )


__all__ = ["register_system_settings_routes"]
