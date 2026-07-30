"""Workspace-owned Telegram Bot transport for notification fan-out."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
from typing import Any

from ..storage.service_store import ServiceStore
from .notification_telegram_transport import (
    TelegramConfigurationError,
    TelegramDeliveryError,
    TelegramSendResult,
    normalize_telegram_bot_token,
    normalize_telegram_chat_id,
    send_telegram_message,
)
from .secret_store import SecretStore


UNSET = object()
TEST_COOLDOWN_SECONDS = 60


class TelegramTransportServiceError(RuntimeError):
    """Safe workspace Telegram transport error for API envelopes."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = int(status_code)
        self.retryable = bool(retryable)
        self.outcome_unknown = bool(outcome_unknown)


class WorkspaceTelegramTransportService:
    """Manage one tested, write-only Telegram Bot token per workspace."""

    def __init__(self, store: ServiceStore, *, data_dir: str) -> None:
        self.store = store
        self.secret_store = SecretStore(data_dir)

    @staticmethod
    def token_env_name(*, workspace_id: str) -> str:
        digest = hashlib.sha256(
            str(workspace_id).encode("utf-8")
        ).hexdigest()[:24].upper()
        return f"HORIZON_WORKSPACE_TELEGRAM_{digest}"

    def _bound_token(
        self,
        transport: dict[str, Any] | None,
    ) -> str | None:
        if transport is None:
            return None
        workspace_id = str(transport.get("workspace_id") or "")
        expected_env = self.token_env_name(workspace_id=workspace_id)
        env_name = str(transport.get("token_env_name") or "")
        expected_digest = str(
            transport.get("token_secret_digest") or ""
        )
        if (
            not workspace_id
            or env_name != expected_env
            or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
        ):
            return None
        token = self.secret_store.read().get(expected_env)
        if not token:
            return None
        actual_digest = hashlib.sha256(
            token.encode("utf-8")
        ).hexdigest()
        return (
            token
            if hmac.compare_digest(actual_digest, expected_digest)
            else None
        )

    def _can_enable(self, transport: dict[str, Any]) -> bool:
        return bool(
            self._bound_token(transport)
            and transport.get("last_test_status") == "sent"
            and int(transport.get("last_test_generation") or -1)
            == int(transport.get("generation") or 0)
        )

    def is_ready(self, *, workspace_id: str) -> bool:
        transport = self.store.get_workspace_telegram_transport(
            workspace_id=workspace_id
        )
        return bool(
            transport
            and transport.get("enabled")
            and self._can_enable(transport)
        )

    def get_public_settings(
        self,
        *,
        workspace_id: str,
    ) -> dict[str, Any]:
        transport = self.store.get_workspace_telegram_transport(
            workspace_id=workspace_id
        )
        base = {
            "schema_version": 1,
            "configured": False,
            "token_configured": False,
            "enabled": False,
            "generation": 0,
            "last_test_status": None,
            "last_test_generation": None,
            "last_tested_at": None,
            "last_test_error_code": None,
            "can_enable": False,
            "ready": False,
            "updated_at": None,
        }
        if transport is None:
            return base
        token_configured = bool(self._bound_token(transport))
        can_enable = self._can_enable(transport)
        last_test_status = transport.get("last_test_status")
        if (
            last_test_status == "failed"
            and transport.get("last_test_error_code")
            in {
                "notification_telegram_outcome_unknown",
                "notification_telegram_response_invalid",
            }
        ):
            last_test_status = "unknown"
        return {
            **base,
            "configured": True,
            "token_configured": token_configured,
            "enabled": bool(transport.get("enabled")),
            "generation": int(transport.get("generation") or 0),
            "last_test_status": last_test_status,
            "last_test_generation": transport.get(
                "last_test_generation"
            ),
            "last_tested_at": transport.get("last_tested_at"),
            "last_test_error_code": transport.get(
                "last_test_error_code"
            ),
            "can_enable": can_enable,
            "ready": bool(transport.get("enabled") and can_enable),
            "updated_at": transport.get("updated_at"),
        }

    def upsert(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        bot_token: Any = UNSET,
        enabled: Any = UNSET,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "Telegram transport update requires no active transaction"
            )
        expected_env = self.token_env_name(workspace_id=workspace_id)
        previous_secret = self.secret_store.read().get(expected_env)
        secret_touched = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._require_admin(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
            )
            current = self.store.get_workspace_telegram_transport(
                workspace_id=workspace_id
            )
            current_ready = bool(
                current
                and current.get("enabled")
                and self._can_enable(current)
            )
            token_touched = bot_token is not UNSET
            token_value = self._bound_token(current)
            if token_touched:
                token_value = (
                    None
                    if bot_token is None or not str(bot_token).strip()
                    else normalize_telegram_bot_token(bot_token)
                )
            target_env = expected_env if token_value else None
            target_digest = (
                hashlib.sha256(token_value.encode("utf-8")).hexdigest()
                if token_value
                else None
            )
            target_generation = int(
                (current or {}).get("generation") or 0
            )
            if current is None or token_touched:
                target_generation += 1
            target_enabled = bool(
                (current or {}).get("enabled", False)
                if enabled is UNSET or enabled is None
                else enabled
            )
            last_test_status = (current or {}).get("last_test_status")
            last_test_generation = (current or {}).get(
                "last_test_generation"
            )
            last_tested_at = (current or {}).get("last_tested_at")
            last_test_error_code = (current or {}).get(
                "last_test_error_code"
            )
            if current is None or token_touched:
                target_enabled = False
                last_test_status = None
                last_test_generation = None
                last_tested_at = None
                last_test_error_code = None
            future = {
                "workspace_id": workspace_id,
                "enabled": target_enabled,
                "token_env_name": target_env,
                "token_secret_digest": target_digest,
                "generation": target_generation,
                "last_test_status": last_test_status,
                "last_test_generation": last_test_generation,
            }
            if target_enabled and not self._can_enable(future):
                raise TelegramTransportServiceError(
                    "telegram_transport_test_required",
                    "test the current Telegram Bot before enabling it",
                    status_code=409,
                )
            future_ready = bool(
                target_enabled and self._can_enable(future)
            )
            if token_touched:
                if token_value is None:
                    self.secret_store.delete(expected_env)
                    os.environ.pop(expected_env, None)
                else:
                    self.secret_store.set(expected_env, token_value)
                    os.environ[expected_env] = token_value
                secret_touched = True
            self.store.upsert_workspace_telegram_transport(
                workspace_id=workspace_id,
                enabled=target_enabled,
                token_env_name=target_env,
                token_secret_digest=target_digest,
                generation=target_generation,
                last_test_status=last_test_status,
                last_test_generation=last_test_generation,
                last_test_attempted_at=(current or {}).get(
                    "last_test_attempted_at"
                ),
                last_tested_at=last_tested_at,
                last_test_error_code=last_test_error_code,
                commit=False,
            )
            if (
                current is None
                or token_touched
                or target_enabled != bool((current or {}).get("enabled"))
            ):
                self.store.invalidate_notification_channel_deliveries(
                    workspace_id=workspace_id,
                    channel="telegram",
                    commit=False,
                )
            if future_ready and not current_ready:
                self.store.advance_notification_channel_watermarks(
                    workspace_id=workspace_id,
                    channel="telegram",
                    commit=False,
                )
            conn.commit()
        except TelegramConfigurationError as exc:
            if conn.in_transaction:
                conn.rollback()
            raise TelegramTransportServiceError(
                exc.code,
                str(exc),
            ) from exc
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            if secret_touched:
                if previous_secret is None:
                    self.secret_store.delete(expected_env)
                    os.environ.pop(expected_env, None)
                else:
                    self.secret_store.set(expected_env, previous_secret)
                    os.environ[expected_env] = previous_secret
            raise
        return self.get_public_settings(workspace_id=workspace_id)

    def delete(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
    ) -> bool:
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "Telegram transport deletion requires no active transaction"
            )
        expected_env = self.token_env_name(workspace_id=workspace_id)
        previous_secret = self.secret_store.read().get(expected_env)
        secret_touched = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._require_admin(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
            )
            current = self.store.get_workspace_telegram_transport(
                workspace_id=workspace_id
            )
            self.secret_store.delete(expected_env)
            os.environ.pop(expected_env, None)
            secret_touched = True
            self.store.invalidate_notification_channel_deliveries(
                workspace_id=workspace_id,
                channel="telegram",
                commit=False,
            )
            deleted = self.store.delete_workspace_telegram_transport(
                workspace_id=workspace_id,
                commit=False,
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            if secret_touched and previous_secret is not None:
                self.secret_store.set(expected_env, previous_secret)
                os.environ[expected_env] = previous_secret
            raise
        return bool(current is not None and deleted)

    def send_test(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        chat_id: Any,
    ) -> dict[str, Any]:
        normalized_chat_id = normalize_telegram_chat_id(chat_id)
        attempt = (
            self.store.claim_workspace_telegram_transport_test_attempt(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
                cooldown_seconds=TEST_COOLDOWN_SECONDS,
            )
        )
        reason = attempt.get("reason")
        if reason == "forbidden":
            raise TelegramTransportServiceError(
                "forbidden",
                "owner or admin role required",
                status_code=403,
            )
        if reason == "not_configured":
            raise TelegramTransportServiceError(
                "telegram_transport_not_configured",
                "configure the Telegram Bot before testing it",
                status_code=409,
            )
        if reason == "rate_limited":
            raise TelegramTransportServiceError(
                "telegram_transport_test_rate_limited",
                "wait before sending another Telegram transport test",
                status_code=429,
                retryable=True,
            )
        transport = attempt["transport"]
        generation = int(transport.get("generation") or 0)
        try:
            result = self.send_message(
                workspace_id=workspace_id,
                chat_id=normalized_chat_id,
                text=(
                    "Inteliscope Telegram Bot 测试\n"
                    "这是一条模拟消息，用于验证工作区共享 Bot Token。"
                ),
                require_enabled=False,
                transport=transport,
            )
        except TelegramTransportServiceError as exc:
            self.store.record_workspace_telegram_transport_test(
                workspace_id=workspace_id,
                generation=generation,
                status="failed",
                error_code=exc.code,
            )
            raise
        recorded = self.store.record_workspace_telegram_transport_test(
            workspace_id=workspace_id,
            generation=generation,
            status="sent",
        )
        if recorded is None:
            raise TelegramTransportServiceError(
                "telegram_transport_changed",
                "Telegram transport changed while the test was running",
                status_code=409,
                outcome_unknown=True,
            )
        return {
            "sent": True,
            "generation": generation,
            "message_id": result.message_id,
            "verification": result.verification,
        }

    def send_message(
        self,
        *,
        workspace_id: str,
        chat_id: Any,
        text: Any,
        require_enabled: bool = True,
        transport: dict[str, Any] | None = None,
    ) -> TelegramSendResult:
        current = transport or self.store.get_workspace_telegram_transport(
            workspace_id=workspace_id
        )
        if current is None:
            raise TelegramTransportServiceError(
                "telegram_transport_not_configured",
                "Telegram transport is not configured",
                status_code=409,
            )
        if require_enabled and not self.is_ready(workspace_id=workspace_id):
            raise TelegramTransportServiceError(
                "notification_channel_unavailable",
                "workspace Telegram transport is not ready",
                status_code=409,
            )
        token = self._bound_token(current)
        if not token:
            raise TelegramTransportServiceError(
                "telegram_transport_token_unavailable",
                "Telegram Bot token is unavailable",
                status_code=409,
            )
        try:
            result = asyncio.run(
                asyncio.wait_for(
                    send_telegram_message(
                        token,
                        normalize_telegram_chat_id(chat_id),
                        str(text),
                        timeout=5.0,
                    ),
                    timeout=6.0,
                )
            )
        except TelegramConfigurationError as exc:
            raise TelegramTransportServiceError(
                exc.code,
                str(exc),
            ) from exc
        except TelegramDeliveryError as exc:
            raise TelegramTransportServiceError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                outcome_unknown=exc.outcome_unknown,
            ) from exc
        except TimeoutError as exc:
            raise TelegramTransportServiceError(
                "notification_telegram_outcome_unknown",
                "Telegram delivery outcome is unknown",
                status_code=502,
                outcome_unknown=True,
            ) from exc
        except Exception as exc:
            raise TelegramTransportServiceError(
                "notification_telegram_outcome_unknown",
                "Telegram delivery outcome is unknown",
                status_code=502,
                outcome_unknown=True,
            ) from exc
        if not isinstance(result, TelegramSendResult):
            raise TelegramTransportServiceError(
                "notification_telegram_outcome_unknown",
                "Telegram delivery outcome is unknown",
                status_code=502,
                outcome_unknown=True,
            )
        return result

    def _require_admin(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
    ) -> None:
        actor = self.store.get_user(actor_user_id)
        if (
            actor is None
            or not bool(actor.get("enabled"))
            or str(actor.get("workspace_id")) != str(workspace_id)
            or str(actor.get("role") or "") not in {"owner", "admin"}
        ):
            raise TelegramTransportServiceError(
                "forbidden",
                "owner or admin role required",
                status_code=403,
            )
