"""Workspace SecretStore HTTP adapters."""

from copy import deepcopy
from typing import Any

from fastapi import Depends, FastAPI
from pydantic import BaseModel, ConfigDict

from .apify_key_pool_routes import pool_api_error
from .context import ApiContext
from .responses import ApiError, ok
from .system_auth import api_context, current_admin
from ..services.apify_key_pool import (
    ApifyKeyBusyError,
    ApifyKeyPoolError,
    apify_key_pool_enabled,
)
from ..services.secret_quota import SecretQuotaError
from ..services.secret_store import SecretValueError
from ..storage.service_store import SecretEnvConflictError


class SecretCreateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    name: str
    kind: str
    provider: str
    env_name: str
    value: str
    base_url: str = ""


class SecretRotateRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    value: str


class SecretConnectionRequest(BaseModel):
    model_config = ConfigDict(extra="forbid")

    base_url: str = ""


def _is_apify_secret(secret: dict[str, Any]) -> bool:
    return (
        str(secret.get("provider") or "").lower() == "apify"
        or str(secret.get("kind") or "").lower() == "apify"
    )


def _secret_or_404(
    context: ApiContext,
    secret_id: str,
    user: dict[str, Any],
) -> dict[str, Any]:
    secret = context.store.get_secret_ref(secret_id)
    if secret is None or secret["workspace_id"] != user["workspace_id"]:
        raise ApiError("not_found", "secret reference not found", status_code=404)
    return secret


async def admin_secrets_list(
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    context.secret_values.load_into_environ()
    secrets = context.store.list_secret_refs(workspace_id=user["workspace_id"])
    return ok({"secrets": [context.public_secret(secret) for secret in secrets]})


async def admin_secrets_create(
    payload: SecretCreateRequest,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    name, kind, provider, env_name, base_url = context.validate_secret_metadata(
        payload
    )
    if context.store.get_secret_ref_by_env(
        workspace_id=user["workspace_id"], env_name=env_name
    ):
        raise ApiError(
            "secret_env_conflict",
            "the environment name is already registered",
            status_code=409,
        )
    secret: dict[str, Any] | None = None
    try:
        context.secret_values.set(env_name, payload.value)
        context.secret_values.load_into_environ()
        secret = context.store.create_secret_ref(
            workspace_id=user["workspace_id"],
            owner_user_id=user["id"],
            name=name,
            env_name=env_name,
            kind=kind,
            provider=provider,
            base_url=base_url,
            scope="workspace",
        )
        if kind == "apify" and provider == "apify":
            context.apify_key_pool.append_secret(secret["id"])
        if kind == "ai":
            base_data, base_config = context.read_base_config()
            if base_config.ai.api_key_env == env_name:
                synchronized = deepcopy(base_data)
                context.synchronize_ai_connection(synchronized, secret)
                context.write_base_config(synchronized)
    except SecretEnvConflictError as exc:
        context.secret_values.delete(env_name)
        context.secret_values.load_into_environ()
        raise ApiError(
            "secret_env_conflict",
            "the environment name is already registered",
            status_code=409,
        ) from exc
    except ApifyKeyPoolError as exc:
        if secret is not None:
            context.store.delete_secret_ref(str(secret["id"]))
        context.secret_values.delete(env_name)
        context.secret_values.load_into_environ()
        raise pool_api_error(exc) from exc
    except SecretValueError as exc:
        raise ApiError("invalid_secret", str(exc), status_code=400) from exc
    except Exception:
        if secret is not None:
            context.store.delete_secret_ref(str(secret["id"]))
        context.secret_values.delete(env_name)
        context.secret_values.load_into_environ()
        raise
    return ok(context.public_secret(secret))


async def admin_secrets_rotate(
    secret_id: str,
    payload: SecretRotateRequest,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    secret = _secret_or_404(context, secret_id, user)
    apify_lifecycle: dict[str, Any] | None = None
    if _is_apify_secret(secret):
        apify_lifecycle = context.apify_key_pool.secret_lifecycle(secret_id)
        try:
            if apify_key_pool_enabled():
                context.apify_key_pool.ensure_secret_mutable(secret_id)
            elif apify_lifecycle["managed"] and (
                int(apify_lifecycle["active_run_count"]) > 0
                or apify_lifecycle["status"] == "draining"
            ):
                raise ApifyKeyBusyError()
        except ApifyKeyPoolError as exc:
            raise pool_api_error(exc) from exc
    try:
        context.secret_values.set(secret["env_name"], payload.value)
        context.secret_values.load_into_environ()
    except SecretValueError as exc:
        raise ApiError("invalid_secret", str(exc), status_code=400) from exc
    updated = context.store.touch_secret_ref(secret_id)
    if _is_apify_secret(secret):
        if apify_lifecycle and apify_lifecycle["managed"]:
            try:
                context.apify_key_pool.mark_secret_rotated(secret_id)
            except ApifyKeyPoolError as exc:
                raise pool_api_error(exc) from exc
        for source in context.store.list_sources_using_secret(
            workspace_id=user["workspace_id"],
            env_name=secret["env_name"],
        ):
            context.source_health.reset_source(
                workspace_id=user["workspace_id"],
                source_id=source["id"],
            )
    return ok(context.public_secret(updated))


async def admin_secrets_update_connection(
    secret_id: str,
    payload: SecretConnectionRequest,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    secret = _secret_or_404(context, secret_id, user)
    if str(secret.get("kind") or "").lower() != "ai":
        raise ApiError(
            "invalid_secret",
            "Base URL is supported only for AI keys",
            status_code=400,
        )
    base_url = context.normalize_ai_secret_base_url(payload.base_url)
    updated = context.store.update_secret_base_url(secret_id, base_url=base_url)
    base_data, base_config = context.read_base_config()
    if base_config.ai.api_key_env == secret["env_name"]:
        synchronized = deepcopy(base_data)
        context.synchronize_ai_connection(synchronized, updated)
        context.write_base_config(synchronized)
    return ok(context.public_secret(updated))


async def admin_secrets_quota(
    secret_id: str,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    secret = _secret_or_404(context, secret_id, user)
    if not _is_apify_secret(secret):
        raise ApiError(
            "quota_not_supported",
            "该 Provider 暂不支持额度查询。",
            status_code=400,
        )
    token = context.secret_values.read().get(secret["env_name"], "").strip()
    if not token:
        raise ApiError(
            "secret_not_configured",
            "该 Key 尚未配置真实值，无法查询额度。",
            status_code=409,
            action="请先轮换并保存有效的 Apify Token。",
        )
    try:
        quota_data = await context.secret_quota.fetch(
            secret_id=secret_id, token=token
        )
    except SecretQuotaError as exc:
        raise ApiError(
            exc.code,
            exc.message,
            status_code=exc.status_code,
            retryable=exc.retryable,
            action=exc.action,
        ) from exc
    lifecycle = context.apify_key_pool.secret_lifecycle(secret_id)
    if lifecycle["managed"]:
        context.apify_key_pool.record_member_quota(
            workspace_id=str(user["workspace_id"]),
            secret_id=secret_id,
            remaining_included_credits_usd=float(
                quota_data["remaining_included_credits_usd"]
            ),
            checked_at=str(quota_data["checked_at"]),
            cycle_start_at=str(quota_data["cycle_start_at"]),
            cycle_end_at=str(quota_data["cycle_end_at"]),
            monthly_included_credits_usd=float(
                quota_data["monthly_included_credits_usd"]
            ),
            monthly_usage_usd=float(quota_data["monthly_usage_usd"]),
            max_monthly_usage_usd=float(quota_data["max_monthly_usage_usd"]),
            remaining_hard_limit_usd=float(quota_data["remaining_hard_limit_usd"]),
        )
    return ok(quota_data)


async def admin_secrets_delete(
    secret_id: str,
    user: dict[str, Any] = Depends(current_admin),
    context: ApiContext = Depends(api_context),
) -> dict[str, Any]:
    secret = _secret_or_404(context, secret_id, user)
    if context.secret_usage(secret):
        raise ApiError(
            "secret_in_use",
            "secret is still referenced by AI or a catalog source",
            status_code=409,
            action="Reassign every reference before deleting this secret.",
        )
    if _is_apify_secret(secret):
        try:
            lifecycle = context.apify_key_pool.secret_lifecycle(secret_id)
            if lifecycle["managed"]:
                if apify_key_pool_enabled():
                    context.apify_key_pool.ensure_secret_mutable(secret_id)
                elif lifecycle["busy"]:
                    if int(lifecycle["active_run_count"]) > 0:
                        raise ApifyKeyBusyError()
                    context.apify_key_pool.begin_drain(secret_id)
                    context.apify_key_pool.complete_drain_and_failover(
                        str(user["workspace_id"])
                    )
                context.apify_key_pool.remove_secret(secret_id)
        except ApifyKeyPoolError as exc:
            raise pool_api_error(exc) from exc
    context.secret_values.delete(secret["env_name"])
    context.secret_values.load_into_environ()
    context.store.delete_secret_ref(secret_id)
    return ok({"deleted": True, "id": secret_id})


def register_secret_list_route(app: FastAPI) -> None:
    app.add_api_route("/api/admin/secrets", admin_secrets_list, methods=["GET"])


def register_secret_mutation_routes(app: FastAPI) -> None:
    app.add_api_route("/api/admin/secrets", admin_secrets_create, methods=["POST"])
    app.add_api_route(
        "/api/admin/secrets/{secret_id}/value",
        admin_secrets_rotate,
        methods=["PUT"],
    )
    app.add_api_route(
        "/api/admin/secrets/{secret_id}/connection",
        admin_secrets_update_connection,
        methods=["PATCH"],
    )
    app.add_api_route(
        "/api/admin/secrets/{secret_id}/quota",
        admin_secrets_quota,
        methods=["GET"],
    )
    app.add_api_route(
        "/api/admin/secrets/{secret_id}", admin_secrets_delete, methods=["DELETE"]
    )
