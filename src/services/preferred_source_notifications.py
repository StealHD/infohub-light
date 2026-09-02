"""Durable notifications for newly published items from preferred sources."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import logging
import os
import re
import threading
import uuid
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Coroutine
from urllib.parse import urlsplit

from ..storage.service_store import NOTIFICATION_CHANNELS, ServiceStore
from .network_policy import post_public_http
from .notification_candidate_provenance import notification_candidate_subscription_ids
from .notification_webhook_transport import (
    DINGTALK,
    FEISHU_LARK_V2,
    GENERIC_EVENT,
    LEGACY_AUTO,
    WebhookConfigurationError,
    WebhookDeliveryError,
    WebhookSendResult,
    normalize_stored_webhook_provider,
    resolve_webhook_provider,
    send_notification_webhook,
    validate_signing_secret,
    validate_webhook_url,
    webhook_provider_options,
    webhook_text_limit,
    webhook_verification_mode,
)
from .notification_email_transport import (
    EmailTransportError,
    WorkspaceEmailTransportService,
)
from .notification_telegram_transport import (
    TelegramConfigurationError,
    TelegramSendResult,
    normalize_telegram_chat_id,
)
from .secret_store import SecretStore
from .workspace_telegram_transport import (
    TelegramTransportServiceError,
    WorkspaceTelegramTransportService,
)
from .notification_targets import (
    NotificationTargetError,
    NotificationTargetService,
)


logger = logging.getLogger(__name__)
UNSET = object()
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SAFE_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_MAX_DELIVERIES_PER_TICK = 20
_TEST_COOLDOWN_SECONDS = 60
_FEISHU_TEXT_LIMIT = 3_500
_FEISHU_MARKUP_TRANSLATION = str.maketrans({"<": "＜", ">": "＞"})


class NotificationServiceError(RuntimeError):
    """A safe notification error suitable for an API error envelope."""

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
        self.status_code = status_code
        self.retryable = retryable
        self.outcome_unknown = outcome_unknown


def _new_id() -> str:
    return f"psnd_{uuid.uuid4().hex}"


def _json_dumps(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, default=str)


def _json_loads(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return value
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return parsed if isinstance(parsed, dict) else {}


def _parse_time(value: Any) -> datetime | None:
    if not value:
        return None
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def _bounded_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    return text if len(text) <= limit else text[: max(limit - 1, 0)].rstrip() + "…"


def _feishu_dynamic_text(value: Any, limit: int) -> str:
    """Bound untrusted text and neutralize Feishu inline markup such as <at>."""

    return _bounded_text(value, limit).translate(_FEISHU_MARKUP_TRANSLATION)


def _safe_article_url(value: Any) -> str:
    candidate = str(value or "").strip()
    if (
        not candidate
        or len(candidate) > 2_000
        or "\r" in candidate
        or "\n" in candidate
        or "\x00" in candidate
    ):
        return ""
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
    except ValueError:
        return ""
    if (
        parsed.scheme not in {"http", "https"}
        or not hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    return candidate


def _normalize_email(value: Any) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if "\r" in candidate or "\n" in candidate:
        raise NotificationServiceError(
            "invalid_notification_destination",
            "notification email address is invalid",
        )
    display_name, address = parseaddr(candidate)
    if display_name or address != candidate or not _EMAIL_RE.fullmatch(address):
        raise NotificationServiceError(
            "invalid_notification_destination",
            "notification email address is invalid",
        )
    return address


def _normalize_channels(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise NotificationServiceError(
            "invalid_notification_channels",
            "notification channels must be a list",
        )
    channels: list[str] = []
    seen: set[str] = set()
    for raw_channel in value:
        channel = str(raw_channel or "").strip().lower()
        if channel not in NOTIFICATION_CHANNELS or channel in seen:
            raise NotificationServiceError(
                "invalid_notification_channels",
                "notification channels contain an unsupported or duplicate value",
            )
        seen.add(channel)
        channels.append(channel)
    return channels


def _bounded_multiline_text(lines: list[str], *, limit: int) -> str:
    text = "\n".join(line for line in lines if line is not None)
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def _preferred_source_feishu_body(payload: dict[str, Any]) -> dict[str, Any]:
    test_delivery = payload.get("kind") == "test"
    if test_delivery:
        items = [payload]
        lines = [
            "Inteliscope 新内容通知测试",
            "这是一条模拟消息，用于验证当前 Webhook。",
        ]
    else:
        raw_items = payload.get("items")
        items = (
            [item for item in raw_items if isinstance(item, dict)]
            if isinstance(raw_items, list)
            else []
        )[:_MAX_DELIVERIES_PER_TICK]
        lines = [f"Inteliscope 新内容通知（{len(items)} 条）"]

    item_count = len(items)
    if item_count <= 1:
        title_limit, source_limit, summary_limit = 300, 160, 600
        published_limit, url_limit = 80, 1_000
    elif item_count <= 5:
        title_limit, source_limit, summary_limit = 120, 60, 100
        published_limit, url_limit = 32, 200
    elif item_count <= 10:
        title_limit, source_limit, summary_limit = 80, 40, 0
        published_limit, url_limit = 32, 120
    else:
        title_limit, source_limit, summary_limit = 90, 40, 0
        published_limit, url_limit = 0, 0

    for index, item in enumerate(items, start=1):
        title = (
            _feishu_dynamic_text(item.get("title"), title_limit)
            or "未命名内容"
        )
        lines.extend(("", f"{index}. {title}"))
        source_name = _feishu_dynamic_text(item.get("source_name"), source_limit)
        if source_name:
            lines.append(f"来源：{source_name}")
        summary = (
            _feishu_dynamic_text(item.get("summary"), summary_limit)
            if summary_limit
            else ""
        )
        if summary:
            lines.append(f"摘要：{summary}")
        published_at = (
            _feishu_dynamic_text(item.get("published_at"), published_limit)
            if published_limit
            else ""
        )
        if published_at:
            lines.append(f"发布时间：{published_at}")
        article_url = _safe_article_url(item.get("url")) if url_limit else ""
        if article_url:
            lines.append(
                f"链接：{_feishu_dynamic_text(article_url, url_limit)}"
            )

    return {
        "msg_type": "text",
        "content": {
            "text": _bounded_multiline_text(
                lines,
                limit=_FEISHU_TEXT_LIMIT,
            )
        },
    }


def _preferred_source_webhook_text(
    payload: dict[str, Any],
    *,
    limit: int,
) -> str:
    rendered = str(
        _preferred_source_feishu_body(payload)["content"]["text"]
    )
    if len(rendered) <= limit:
        return rendered
    if payload.get("kind") == "test":
        return _bounded_text(rendered, limit)
    raw_items = payload.get("items")
    items = (
        [item for item in raw_items if isinstance(item, dict)]
        if isinstance(raw_items, list)
        else []
    )[:_MAX_DELIVERIES_PER_TICK]
    header = f"Inteliscope 新内容通知（{len(items)} 条）"
    prefix_budget = sum(len(f"\n{index}. ") for index in range(1, len(items) + 1))
    title_budget = max(
        8,
        (limit - len(header) - prefix_budget) // max(1, len(items)),
    )
    lines = [header]
    for index, item in enumerate(items, start=1):
        title = (
            _feishu_dynamic_text(
                item.get("title"),
                min(90, title_budget),
            )
            or "未命名内容"
        )
        lines.append(f"{index}. {title}")
    return _bounded_multiline_text(lines, limit=limit)


def _run_coroutine(coroutine: Coroutine[Any, Any, Any]) -> Any:
    """Run one transport coroutine from Worker or an async API thread safely."""

    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coroutine)

    result: list[Any] = []
    failure: list[BaseException] = []

    def runner() -> None:
        try:
            result.append(asyncio.run(coroutine))
        except BaseException as exc:  # forwarded to the calling request/thread
            failure.append(exc)

    thread = threading.Thread(target=runner, name="notification-http", daemon=True)
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return result[0] if result else None


class PreferredSourceNotificationService:
    """Stage new-item deltas transactionally and deliver them after commit."""

    def __init__(self, store: ServiceStore, *, data_dir: str) -> None:
        self.store = store
        self.data_dir = str(data_dir)
        self.secret_store = SecretStore(data_dir)
        self.email_transport = WorkspaceEmailTransportService(
            store,
            data_dir=data_dir,
        )
        self.telegram_transport = WorkspaceTelegramTransportService(
            store,
            data_dir=data_dir,
        )
        self.notification_targets = NotificationTargetService(
            store,
            data_dir=data_dir,
            email_transport=self.email_transport,
            telegram_transport=self.telegram_transport,
        )

    @staticmethod
    def webhook_env_name(*, workspace_id: str, user_id: str) -> str:
        digest = hashlib.sha256(
            f"{workspace_id}:{user_id}".encode("utf-8")
        ).hexdigest()[:24].upper()
        return f"HORIZON_USER_WEBHOOK_{digest}"

    @staticmethod
    def webhook_signing_env_name(
        *,
        workspace_id: str,
        user_id: str,
    ) -> str:
        digest = hashlib.sha256(
            f"{workspace_id}:{user_id}".encode("utf-8")
        ).hexdigest()[:24].upper()
        return f"HORIZON_USER_WEBHOOK_SIGNING_{digest}"

    @staticmethod
    def telegram_chat_env_name(
        *,
        workspace_id: str,
        user_id: str,
    ) -> str:
        digest = hashlib.sha256(
            f"{workspace_id}:{user_id}".encode("utf-8")
        ).hexdigest()[:24].upper()
        return f"HORIZON_USER_TELEGRAM_CHAT_{digest}"

    def _bound_telegram_chat_id(
        self,
        channel_state: dict[str, Any] | None,
    ) -> str | None:
        if channel_state is None:
            return None
        workspace_id = str(channel_state.get("workspace_id") or "")
        user_id = str(channel_state.get("user_id") or "")
        expected_env = self.telegram_chat_env_name(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        env_name = str(channel_state.get("destination_env_name") or "")
        expected_digest = str(
            channel_state.get("destination_secret_digest") or ""
        )
        if (
            not workspace_id
            or not user_id
            or env_name != expected_env
            or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
        ):
            return None
        value = self.secret_store.read().get(expected_env)
        if not value:
            return None
        actual_digest = hashlib.sha256(
            str(value).encode("utf-8")
        ).hexdigest()
        return (
            str(value)
            if hmac.compare_digest(actual_digest, expected_digest)
            else None
        )

    def _bound_webhook_env_name(
        self,
        settings: dict[str, Any],
    ) -> str | None:
        workspace_id = str(settings.get("workspace_id") or "")
        user_id = str(settings.get("user_id") or "")
        env_name = str(settings.get("webhook_env_name") or "")
        if not workspace_id or not user_id or not env_name:
            return None
        expected = self.webhook_env_name(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        return env_name if env_name == expected else None

    def _bound_webhook_secret(
        self,
        settings: dict[str, Any],
    ) -> str | None:
        env_name = self._bound_webhook_env_name(settings)
        expected_digest = str(
            settings.get("webhook_secret_digest") or ""
        )
        if not env_name or not expected_digest:
            return None
        secret = self.secret_store.read().get(env_name)
        if not secret:
            return None
        actual_digest = hashlib.sha256(
            str(secret).encode("utf-8")
        ).hexdigest()
        return (
            str(secret)
            if hmac.compare_digest(actual_digest, expected_digest)
            else None
        )

    def _bound_webhook_signing_secret(
        self,
        settings: dict[str, Any],
    ) -> str | None:
        workspace_id = str(settings.get("workspace_id") or "")
        user_id = str(settings.get("user_id") or "")
        env_name = str(
            settings.get("webhook_signing_env_name") or ""
        )
        expected_env = self.webhook_signing_env_name(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        expected_digest = str(
            settings.get("webhook_signing_secret_digest") or ""
        )
        if (
            not workspace_id
            or not user_id
            or env_name != expected_env
            or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
        ):
            return None
        secret = self.secret_store.read().get(expected_env)
        if not secret:
            return None
        actual_digest = hashlib.sha256(
            str(secret).encode("utf-8")
        ).hexdigest()
        return (
            str(secret)
            if hmac.compare_digest(actual_digest, expected_digest)
            else None
        )

    @staticmethod
    def _has_webhook_signing_metadata(
        settings: dict[str, Any],
    ) -> bool:
        return (
            settings.get("webhook_signing_env_name") is not None
            or settings.get("webhook_signing_secret_digest") is not None
        )

    def _webhook_signing_binding_valid(
        self,
        settings: dict[str, Any],
    ) -> bool:
        return (
            not self._has_webhook_signing_metadata(settings)
            or self._bound_webhook_signing_secret(settings) is not None
        )

    def get_public_settings(
        self,
        *,
        workspace_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        settings = self.store.get_user_notification_settings(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        channel_rows = self.store.list_user_notification_channels(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        rows_by_channel = {
            str(row["channel"]): row for row in channel_rows
        }
        webhook_url = (
            self._bound_webhook_secret(settings or {}) or ""
        )
        if settings is None:
            stored_provider = GENERIC_EVENT
            effective_provider = GENERIC_EVENT
        else:
            try:
                stored_provider = normalize_stored_webhook_provider(
                    settings.get("webhook_provider")
                )
                effective_provider = resolve_webhook_provider(
                    stored_provider,
                    webhook_url,
                )
            except WebhookConfigurationError:
                stored_provider = LEGACY_AUTO
                effective_provider = GENERIC_EVENT
        email_ready = self.email_transport.is_ready(
            workspace_id=workspace_id
        )
        telegram_ready = self.telegram_transport.is_ready(
            workspace_id=workspace_id
        )
        channel_states: dict[str, dict[str, Any]] = {}
        for channel in NOTIFICATION_CHANNELS:
            row = rows_by_channel.get(channel)
            test_status = (row or {}).get("last_test_status")
            error_code = (row or {}).get("last_test_error_code")
            if (
                test_status == "failed"
                and error_code
                in {
                    "notification_webhook_outcome_unknown",
                    "notification_webhook_response_invalid",
                    "notification_telegram_outcome_unknown",
                    "notification_telegram_response_invalid",
                    "notification_delivery_outcome_unknown",
                }
            ):
                test_status = "unknown"
            if channel == "email":
                configured = bool((settings or {}).get("email_address"))
                available = bool(configured and email_ready)
            elif channel == "webhook":
                configured = bool(webhook_url)
                available = bool(
                    webhook_url
                    and self._webhook_signing_binding_valid(
                        settings or {}
                    )
                )
            else:
                configured = bool(
                    self._bound_telegram_chat_id(row)
                )
                available = bool(configured and telegram_ready)
            state: dict[str, Any] = {
                "enabled": bool((row or {}).get("enabled")),
                "configured": configured,
                "available": available,
                "generation": int((row or {}).get("generation") or 0),
                "enabled_at": (row or {}).get("enabled_at"),
                "last_test_status": test_status,
                "last_tested_at": (row or {}).get("last_tested_at"),
                "last_test_error_code": error_code,
            }
            if channel == "webhook":
                state.update(
                    {
                        "provider": effective_provider,
                        "provider_explicit": stored_provider
                        != LEGACY_AUTO,
                        "signing_secret_configured": bool(
                            self._bound_webhook_signing_secret(
                                settings or {}
                            )
                        ),
                        "verification_mode": webhook_verification_mode(
                            effective_provider
                        ),
                    }
                )
            channel_states[channel] = state
        active_channels = [
            str(row["channel"])
            for row in channel_rows
            if bool(row.get("enabled"))
        ]
        fallback_channel = str(
            (settings or {}).get("channel") or "webhook"
        )
        primary_channel = (
            active_channels[0]
            if active_channels
            else (
                fallback_channel
                if fallback_channel in NOTIFICATION_CHANNELS
                else "webhook"
            )
        )
        primary_state = channel_states[primary_channel]
        target_bindings = (
            self.store.list_user_notification_target_bindings(
                workspace_id=workspace_id,
                user_id=user_id,
                enabled_only=True,
            )
        )
        actor = self.store.get_user(user_id)
        selected_targets = (
            [
                self.notification_targets.public_target(
                    target,
                    actor=actor,
                )
                for target in target_bindings
            ]
            if actor is not None
            else []
        )
        if selected_targets:
            active_channels = list(
                dict.fromkeys(
                    str(target["channel"])
                    for target in selected_targets
                )
            )
            primary_channel = active_channels[0]
            primary_state = channel_states[primary_channel]
        return {
            "schema_version": 4,
            "enabled": bool((settings or {}).get("enabled")),
            "target_ids": [
                str(target["id"]) for target in selected_targets
            ],
            "selected_targets": selected_targets,
            "channels": active_channels,
            "channel": primary_channel,
            "channel_states": channel_states,
            "email_configured": channel_states["email"]["configured"],
            "email_transport_ready": email_ready,
            "webhook_configured": bool(webhook_url),
            "webhook_provider": effective_provider,
            "webhook_provider_explicit": stored_provider != LEGACY_AUTO,
            "webhook_signing_secret_configured": bool(
                self._bound_webhook_signing_secret(settings or {})
            ),
            "webhook_verification_mode": webhook_verification_mode(
                effective_provider
            ),
            "webhook_provider_options": webhook_provider_options(),
            "telegram_configured": channel_states["telegram"][
                "configured"
            ],
            "telegram_transport_ready": telegram_ready,
            "last_test_status": primary_state["last_test_status"],
            "last_tested_at": primary_state["last_tested_at"],
            "last_test_error_code": primary_state[
                "last_test_error_code"
            ],
            "updated_at": (settings or {}).get("updated_at"),
        }

    def upsert_settings(
        self,
        *,
        workspace_id: str,
        user_id: str,
        enabled: Any = UNSET,
        channel: Any = UNSET,
        channels: Any = UNSET,
        target_ids: Any = UNSET,
        email_address: Any = UNSET,
        webhook_url: Any = UNSET,
        webhook_provider: Any = UNSET,
        webhook_signing_secret: Any = UNSET,
        telegram_chat_id: Any = UNSET,
    ) -> dict[str, Any]:
        if target_ids is not UNSET:
            legacy_fields = (
                channel,
                channels,
                email_address,
                webhook_url,
                webhook_provider,
                webhook_signing_secret,
                telegram_chat_id,
            )
            if any(value is not UNSET for value in legacy_fields):
                raise NotificationServiceError(
                    "invalid_notification_settings",
                    "target_ids cannot be combined with legacy channel configuration",
                )
            if not isinstance(target_ids, list):
                raise NotificationServiceError(
                    "invalid_notification_targets",
                    "notification target_ids must be a list",
                )
            user = self.store.get_user(user_id)
            if (
                user is None
                or str(user.get("workspace_id")) != str(workspace_id)
                or not bool(user.get("enabled"))
                or str(user.get("role") or "")
                not in {"owner", "admin", "member"}
            ):
                raise NotificationServiceError(
                    "notification_target_unavailable",
                    "notification targets are unavailable for this account",
                    status_code=409,
                )
            conn = self.store.connect()
            if conn.in_transaction:
                raise RuntimeError(
                    "notification settings update requires no active transaction"
                )
            try:
                conn.execute("BEGIN IMMEDIATE")
                self.store.set_user_notification_target_bindings(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    target_ids=[str(value) for value in target_ids],
                    commit=False,
                )
                self.store.upsert_user_notification_settings(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    **(
                        {}
                        if enabled is UNSET
                        else {"enabled": bool(enabled)}
                    ),
                    commit=False,
                )
                conn.commit()
            except (LookupError, ValueError) as exc:
                if conn.in_transaction:
                    conn.rollback()
                raise NotificationServiceError(
                    "notification_target_unavailable",
                    "one or more notification targets are unavailable",
                    status_code=409,
                ) from exc
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
            return self.get_public_settings(
                workspace_id=workspace_id,
                user_id=user_id,
            )
        visible_targets = self.store.list_notification_targets(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        legacy_fields_touched = any(
            value is not UNSET
            for value in (
                enabled,
                channel,
                channels,
                email_address,
                webhook_url,
                webhook_provider,
                webhook_signing_secret,
                telegram_chat_id,
            )
        )
        if visible_targets and legacy_fields_touched:
            by_channel: dict[str, list[dict[str, Any]]] = {
                name: [
                    target
                    for target in visible_targets
                    if str(target.get("channel")) == name
                ]
                for name in NOTIFICATION_CHANNELS
            }

            def unique_target(channel_name: str) -> dict[str, Any]:
                matches = by_channel[channel_name]
                if len(matches) != 1:
                    raise NotificationServiceError(
                        "notification_target_legacy_conflict",
                        "legacy notification settings cannot select an ambiguous target",
                        status_code=409,
                    )
                return matches[0]

            requested_channels: list[str] | None = None
            if channels is not UNSET:
                requested_channels = _normalize_channels(channels)
            elif channel is not UNSET:
                requested_channels = [
                    str(channel or "").strip().lower()
                ]
            if requested_channels is not None:
                selected_ids = [
                    str(unique_target(name)["id"])
                    for name in requested_channels
                ]
            else:
                selected_ids = [
                    str(binding["id"])
                    for binding in self.store.list_user_notification_target_bindings(
                        workspace_id=workspace_id,
                        user_id=user_id,
                        enabled_only=True,
                    )
                ]
            target_updates = {
                "email": (
                    {"email_address": email_address}
                    if email_address is not UNSET
                    else {}
                ),
                "webhook": {
                    key: value
                    for key, value in (
                        ("webhook_url", webhook_url),
                        ("webhook_provider", webhook_provider),
                        (
                            "webhook_signing_secret",
                            webhook_signing_secret,
                        ),
                    )
                    if value is not UNSET
                },
                "telegram": (
                    {"telegram_chat_id": telegram_chat_id}
                    if telegram_chat_id is not UNSET
                    else {}
                ),
            }
            for channel_name, updates in target_updates.items():
                if not updates:
                    continue
                target = unique_target(channel_name)
                self.notification_targets.update(
                    workspace_id=workspace_id,
                    actor_user_id=user_id,
                    target_id=str(target["id"]),
                    **updates,
                )
                if (
                    requested_channels is None
                    and not selected_ids
                ):
                    selected_ids.append(str(target["id"]))
            return self.upsert_settings(
                workspace_id=workspace_id,
                user_id=user_id,
                enabled=enabled,
                target_ids=selected_ids,
            )
        if channel is not UNSET and channels is not UNSET:
            raise NotificationServiceError(
                "invalid_notification_settings",
                "channel and channels are mutually exclusive",
            )
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "notification settings update requires no active transaction"
            )
        previous_secrets: dict[str, str | None] = {}
        secrets_written = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            user = self.store.get_user(user_id)
            if (
                user is None
                or str(user.get("workspace_id")) != str(workspace_id)
                or not bool(user.get("enabled"))
                or str(user.get("role") or "")
                not in {"owner", "admin", "member"}
            ):
                raise NotificationServiceError(
                    "notification_channel_unavailable",
                    "notification settings are unavailable for this account",
                    status_code=409,
                )
            current = self.store.get_user_notification_settings(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            current_channel_rows = (
                self.store.list_user_notification_channels(
                    workspace_id=workspace_id,
                    user_id=user_id,
                )
            )
            current_channels_by_name = {
                str(row["channel"]): row
                for row in current_channel_rows
            }
            current_active_channels = [
                str(row["channel"])
                for row in current_channel_rows
                if bool(row.get("enabled"))
            ]
            target_enabled = bool(
                (current or {}).get("enabled", False)
                if enabled is UNSET or enabled is None
                else enabled
            )
            if channels is not UNSET:
                target_channels = _normalize_channels(channels)
            elif channel is not UNSET:
                target_channels = [
                    str(channel or "").strip().lower()
                ]
            else:
                target_channels = list(current_active_channels)
            target_channel = (
                target_channels[0]
                if target_channels
                else str((current or {}).get("channel") or "webhook")
            ).strip().lower()
            if target_channel not in NOTIFICATION_CHANNELS:
                raise NotificationServiceError(
                    "invalid_notification_channel",
                    "notification channel must be email, webhook, or telegram",
                )
            target_email = (
                (current or {}).get("email_address")
                if email_address is UNSET
                else _normalize_email(email_address)
            )
            expected_url_env = self.webhook_env_name(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            expected_signing_env = self.webhook_signing_env_name(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            secret_values = self.secret_store.read()
            stored_url_env = str(
                (current or {}).get("webhook_env_name") or ""
            )
            current_url_env = (
                stored_url_env
                if stored_url_env == expected_url_env
                else ""
            )
            target_url_env = current_url_env or None
            target_url_digest = (
                str((current or {}).get("webhook_secret_digest") or "")
                if current_url_env
                else None
            ) or None
            current_url = self._bound_webhook_secret(current or {})
            current_provider = normalize_stored_webhook_provider(
                (current or {}).get("webhook_provider")
            )
            if webhook_provider is UNSET:
                target_provider = current_provider
            else:
                if webhook_provider is None:
                    raise NotificationServiceError(
                        "invalid_webhook_provider",
                        "webhook provider cannot be null",
                    )
                target_provider = normalize_stored_webhook_provider(
                    webhook_provider
                )
                if target_provider == LEGACY_AUTO:
                    raise NotificationServiceError(
                        "invalid_webhook_provider",
                        "legacy_auto is not a selectable webhook provider",
                    )
            provider_changed = target_provider != current_provider
            url_touched = webhook_url is not UNSET
            if provider_changed and not url_touched:
                raise NotificationServiceError(
                    "webhook_url_required_for_provider_change",
                    "re-enter the webhook URL when changing provider",
                )
            validated_url: str | None = current_url
            if url_touched:
                if webhook_url is None or not str(webhook_url).strip():
                    validated_url = None
                    target_url_env = None
                    target_url_digest = None
                else:
                    validated_url = validate_webhook_url(
                        webhook_url,
                        target_provider,
                        legacy_compat=target_provider == LEGACY_AUTO,
                    )
                    target_url_env = expected_url_env
                    target_url_digest = hashlib.sha256(
                        validated_url.encode("utf-8")
                    ).hexdigest()
            elif validated_url:
                validate_webhook_url(
                    validated_url,
                    target_provider,
                    legacy_compat=target_provider == LEGACY_AUTO,
                )

            stored_signing_env = str(
                (current or {}).get("webhook_signing_env_name") or ""
            )
            current_signing_env = (
                stored_signing_env
                if stored_signing_env == expected_signing_env
                else ""
            )
            target_signing_env = current_signing_env or None
            target_signing_digest = (
                str(
                    (current or {}).get(
                        "webhook_signing_secret_digest"
                    )
                    or ""
                )
                if current_signing_env
                else None
            ) or None
            current_signing_secret = self._bound_webhook_signing_secret(
                current or {}
            )
            signing_touched = webhook_signing_secret is not UNSET
            validated_signing_secret: str | None = current_signing_secret
            implicit_signing_clear = bool(
                not signing_touched
                and (
                    provider_changed
                    or (url_touched and validated_url is None)
                )
            )
            if implicit_signing_clear:
                validated_signing_secret = None
                target_signing_env = None
                target_signing_digest = None
                signing_touched = True
            if signing_touched and not implicit_signing_clear:
                if (
                    webhook_signing_secret is None
                    or not str(webhook_signing_secret).strip()
                ):
                    validated_signing_secret = None
                    target_signing_env = None
                    target_signing_digest = None
                else:
                    if target_provider not in {
                        FEISHU_LARK_V2,
                        DINGTALK,
                    }:
                        raise NotificationServiceError(
                            "webhook_signing_not_supported",
                            "selected webhook provider does not support signing",
                        )
                    validated_signing_secret = validate_signing_secret(
                        webhook_signing_secret
                    )
                    target_signing_env = expected_signing_env
                    target_signing_digest = hashlib.sha256(
                        validated_signing_secret.encode("utf-8")
                    ).hexdigest()
            if (
                target_provider not in {FEISHU_LARK_V2, DINGTALK}
                and target_signing_digest
            ):
                raise NotificationServiceError(
                    "webhook_signing_not_supported",
                    "selected webhook provider does not support signing",
                )

            telegram_row = current_channels_by_name.get("telegram")
            expected_telegram_env = self.telegram_chat_env_name(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            stored_telegram_env = str(
                (telegram_row or {}).get("destination_env_name") or ""
            )
            current_telegram_env = (
                stored_telegram_env
                if stored_telegram_env == expected_telegram_env
                else ""
            )
            current_telegram_chat_id = self._bound_telegram_chat_id(
                telegram_row
            )
            telegram_touched = telegram_chat_id is not UNSET
            validated_telegram_chat_id = current_telegram_chat_id
            if telegram_touched:
                try:
                    validated_telegram_chat_id = (
                        None
                        if telegram_chat_id is None
                        or not str(telegram_chat_id).strip()
                        else normalize_telegram_chat_id(telegram_chat_id)
                    )
                except TelegramConfigurationError as exc:
                    raise NotificationServiceError(
                        exc.code,
                        str(exc),
                    ) from exc
            target_telegram_env = (
                expected_telegram_env
                if validated_telegram_chat_id
                else None
            )
            target_telegram_digest = (
                hashlib.sha256(
                    validated_telegram_chat_id.encode("utf-8")
                ).hexdigest()
                if validated_telegram_chat_id
                else None
            )
            webhook_configured = bool(
                validated_url and target_url_env and target_url_digest
            )
            selected = set(target_channels)
            if target_enabled and "email" in selected and not target_email:
                raise NotificationServiceError(
                    "notification_destination_required",
                    "configure a notification email address before enabling email delivery",
                    status_code=409,
                )
            if (
                target_enabled
                and "webhook" in selected
                and not webhook_configured
            ):
                raise NotificationServiceError(
                    "notification_destination_required",
                    "configure a webhook before enabling webhook delivery",
                    status_code=409,
                )
            if (
                target_enabled
                and "telegram" in selected
                and not validated_telegram_chat_id
            ):
                raise NotificationServiceError(
                    "notification_destination_required",
                    "configure a Telegram Chat ID before enabling Telegram delivery",
                    status_code=409,
                )

            secret_updates: dict[str, str | None] = {}
            if url_touched:
                secret_updates[expected_url_env] = validated_url
            if signing_touched:
                secret_updates[expected_signing_env] = (
                    validated_signing_secret
                )
            if telegram_touched:
                secret_updates[expected_telegram_env] = (
                    validated_telegram_chat_id
                )
            if secret_updates:
                previous_secrets = {
                    name: secret_values.get(name)
                    for name in secret_updates
                }
                self.secret_store.replace_many(secret_updates)
                for name, value in secret_updates.items():
                    if value is None:
                        os.environ.pop(name, None)
                    else:
                        os.environ[name] = value
                secrets_written = True
            store_updates: dict[str, Any] = {}
            if enabled is not UNSET:
                store_updates["enabled"] = enabled
            if channel is not UNSET or channels is not UNSET:
                store_updates["channel"] = target_channel
            if email_address is not UNSET:
                store_updates["email_address"] = target_email
            if url_touched:
                store_updates["webhook_env_name"] = target_url_env
                store_updates["webhook_secret_digest"] = (
                    target_url_digest
                )
            elif (
                stored_url_env
                and (
                    not current_url_env
                    or not target_url_digest
                )
            ):
                store_updates["webhook_env_name"] = None
                store_updates["webhook_secret_digest"] = None
            if webhook_provider is not UNSET:
                store_updates["webhook_provider"] = target_provider
            if signing_touched:
                store_updates["webhook_signing_env_name"] = (
                    target_signing_env
                )
                store_updates["webhook_signing_secret_digest"] = (
                    target_signing_digest
                )
            elif (
                stored_signing_env
                and (
                    not current_signing_env
                    or not target_signing_digest
                )
            ):
                store_updates["webhook_signing_env_name"] = None
                store_updates["webhook_signing_secret_digest"] = None
            self.store.upsert_user_notification_settings(
                workspace_id=workspace_id,
                user_id=user_id,
                commit=False,
                **store_updates,
            )
            now = datetime.now(timezone.utc).isoformat()
            changed_channel_names: set[str] = set()
            channel_specific_changes = {
                "email": email_address is not UNSET,
                "webhook": bool(
                    url_touched
                    or webhook_provider is not UNSET
                    or signing_touched
                ),
                "telegram": telegram_touched
                or bool(
                    stored_telegram_env
                    and not current_telegram_env
                ),
            }
            for position, channel_name in enumerate(
                NOTIFICATION_CHANNELS
            ):
                existing_channel = current_channels_by_name.get(
                    channel_name
                )
                channel_enabled = channel_name in selected
                enabled_changed = channel_enabled != bool(
                    (existing_channel or {}).get("enabled")
                )
                material_changed = bool(
                    existing_channel is None
                    or enabled_changed
                    or channel_specific_changes[channel_name]
                )
                generation = int(
                    (existing_channel or {}).get("generation") or 0
                )
                if material_changed:
                    generation += 1
                    changed_channel_names.add(channel_name)
                enabled_at = (existing_channel or {}).get("enabled_at")
                if not channel_enabled:
                    enabled_at = None
                elif enabled_changed or enabled_at is None:
                    enabled_at = now
                ordered_position = (
                    target_channels.index(channel_name)
                    if channel_name in selected
                    else len(target_channels) + position
                )
                destination_env_name = (
                    target_telegram_env
                    if channel_name == "telegram"
                    else None
                )
                destination_secret_digest = (
                    target_telegram_digest
                    if channel_name == "telegram"
                    else None
                )
                reset_test = material_changed
                self.store.upsert_user_notification_channel(
                    workspace_id=workspace_id,
                    user_id=user_id,
                    channel=channel_name,
                    position=ordered_position,
                    enabled=channel_enabled,
                    enabled_at=enabled_at,
                    generation=generation,
                    destination_env_name=destination_env_name,
                    destination_secret_digest=destination_secret_digest,
                    last_test_status=(
                        None
                        if reset_test
                        else (existing_channel or {}).get(
                            "last_test_status"
                        )
                    ),
                    last_test_generation=(
                        None
                        if reset_test
                        else (existing_channel or {}).get(
                            "last_test_generation"
                        )
                    ),
                    last_test_attempted_at=(
                        (existing_channel or {}).get(
                            "last_test_attempted_at"
                        )
                    ),
                    last_tested_at=(
                        None
                        if reset_test
                        else (existing_channel or {}).get(
                            "last_tested_at"
                        )
                    ),
                    last_test_error_code=(
                        None
                        if reset_test
                        else (existing_channel or {}).get(
                            "last_test_error_code"
                        )
                    ),
                    commit=False,
                )
            for changed_channel in changed_channel_names:
                conn.execute(
                    """
                    UPDATE preferred_source_notification_deliveries
                    SET status = 'failed',
                        error_code = 'notification_settings_changed',
                        updated_at = ?
                    WHERE workspace_id = ? AND user_id = ?
                      AND channel = ?
                      AND status = 'pending'
                    """,
                    (
                        now,
                        workspace_id,
                        user_id,
                        changed_channel,
                    ),
                )
            conn.commit()
        except Exception as exc:
            compensation_error: Exception | None = None
            try:
                if secrets_written:
                    # Keep the SQLite write lock until SecretStore has been
                    # restored so a later successful PATCH cannot be
                    # overwritten by this failed request's compensation.
                    self.secret_store.replace_many(previous_secrets)
                    for name, value in previous_secrets.items():
                        if value is None:
                            os.environ.pop(name, None)
                        else:
                            os.environ[name] = value
            except Exception as restore_exc:
                compensation_error = restore_exc
            finally:
                if conn.in_transaction:
                    conn.rollback()
            if compensation_error is not None:
                raise RuntimeError(
                    "notification SecretStore compensation failed"
                ) from compensation_error
            if isinstance(exc, (LookupError, PermissionError)):
                raise NotificationServiceError(
                    "notification_channel_unavailable",
                    "notification settings are unavailable for this account",
                    status_code=409,
                ) from exc
            if isinstance(exc, WebhookConfigurationError):
                raise NotificationServiceError(
                    exc.code,
                    str(exc),
                ) from exc
            if (
                isinstance(exc, ValueError)
                and "destination" in str(exc).lower()
            ):
                raise NotificationServiceError(
                    "notification_destination_required",
                    "configure the active notification destination before enabling delivery",
                    status_code=409,
                ) from exc
            raise
        return self.get_public_settings(
            workspace_id=workspace_id,
            user_id=user_id,
        )

    def stage_for_job(
        self,
        *,
        job: dict[str, Any],
        snapshot_id: str,
        snapshot_created: bool,
    ) -> int:
        """Insert pending deliveries while the Feed/job transaction is open."""

        conn = self.store.connect()
        if not conn.in_transaction:
            raise RuntimeError(
                "preferred-source notification staging requires the Feed transaction"
            )
        if job.get("job_type") not in {"source_fetch", "user_feed_refresh"}:
            return 0
        workspace_id = str(job["workspace_id"])
        user_id = str(job["user_id"])
        settings = self.store.get_user_notification_settings(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if settings is None or not bool(settings.get("enabled")):
            return 0
        account_enabled_at = _parse_time(settings.get("notification_enabled_at"))
        if account_enabled_at is None:
            return 0
        account_generation = int(
            settings.get("notification_generation") or 0
        )
        target_bindings = (
            self.store.list_user_notification_target_bindings(
                workspace_id=workspace_id,
                user_id=user_id,
            )
        )
        channel_rows = self.store.list_user_notification_channels(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        active_channels: list[dict[str, Any]] = []
        if target_bindings:
            for target in target_bindings:
                if (
                    bool(target.get("binding_enabled"))
                    and target.get("binding_enabled_at")
                    and self.notification_targets.target_is_available(target)
                ):
                    active_channels.append(
                        {**target, "_target_mode": True}
                    )
        else:
            for channel_state in channel_rows:
                if not bool(channel_state.get("enabled")):
                    continue
                channel_name = str(channel_state.get("channel") or "")
                channel_enabled_at = _parse_time(
                    channel_state.get("enabled_at")
                )
                if channel_enabled_at is None:
                    continue
                if channel_name == "email":
                    available = bool(
                        settings.get("email_address")
                        and self.email_transport.is_ready(
                            workspace_id=workspace_id
                        )
                    )
                elif channel_name == "webhook":
                    available = bool(
                        self._bound_webhook_secret(settings)
                        and self._webhook_signing_binding_valid(settings)
                    )
                elif channel_name == "telegram":
                    available = bool(
                        self._bound_telegram_chat_id(channel_state)
                        and self.telegram_transport.is_ready(
                            workspace_id=workspace_id
                        )
                    )
                else:
                    available = False
                if available:
                    active_channels.append(channel_state)
        if not active_channels:
            return 0

        snapshot = conn.execute(
            """
            SELECT rowid AS snapshot_rowid, *
            FROM user_feed_snapshots
            WHERE id = ? AND workspace_id = ? AND user_id = ?
            """,
            (snapshot_id, workspace_id, user_id),
        ).fetchone()
        if snapshot is None:
            return 0
        if str(snapshot["job_id"] or "") != str(job["id"]):
            return 0
        previous = conn.execute(
            """
            SELECT id
            FROM user_feed_snapshots
            WHERE workspace_id = ? AND user_id = ? AND rowid < ?
            ORDER BY generated_at DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (workspace_id, user_id, snapshot["snapshot_rowid"]),
        ).fetchone()
        if previous is None:
            return 0
        previous_ids = {
            str(row["article_id"])
            for row in conn.execute(
                """
                SELECT article_id
                FROM user_feed_items
                WHERE snapshot_id = ?
                """,
                (previous["id"],),
            ).fetchall()
        }
        current_rows = conn.execute(
            """
            SELECT article_id, source_id, subscription_id, item_json
            FROM user_feed_items
            WHERE snapshot_id = ?
            ORDER BY position, id
            """,
            (snapshot_id,),
        ).fetchall()
        staged = 0
        subscription_cache: dict[str, dict[str, Any] | None] = {}
        source_cache: dict[str, dict[str, Any] | None] = {}
        now = datetime.now(timezone.utc).isoformat()
        for row in current_rows:
            article_id = str(row["article_id"])
            if article_id in previous_ids:
                continue
            item = _json_loads(row["item_json"])
            if not item or str(item.get("analysis_mode") or "") == "personal_only":
                continue
            published_at = _parse_time(item.get("published_at"))
            if published_at is None:
                continue
            subscription_ids = notification_candidate_subscription_ids(
                item,
                row_source_id=row["source_id"],
                row_subscription_id=row["subscription_id"],
                job=job,
            )
            for subscription_id in subscription_ids:
                if subscription_id not in subscription_cache:
                    subscription_cache[subscription_id] = self.store.get_subscription(
                        subscription_id
                    )
                subscription = subscription_cache[subscription_id]
                if (
                    subscription is None
                    or str(subscription.get("user_id")) != user_id
                    or not bool(subscription.get("enabled"))
                    or not bool(subscription.get("notify_on_new_items"))
                    or str(subscription.get("analysis_mode")) == "personal_only"
                ):
                    continue
                subscription_enabled_at = _parse_time(
                    subscription.get("notification_enabled_at")
                )
                if subscription_enabled_at is None:
                    continue
                subscription_generation = (
                    self.store.get_subscription_notification_generation(
                        subscription_id
                    )
                )
                if subscription_generation is None:
                    continue
                source_id = str(subscription.get("source_id") or "")
                if not source_id:
                    continue
                if source_id not in source_cache:
                    source_cache[source_id] = self.store.get_source(source_id)
                source = source_cache[source_id]
                if source is None or not bool(source.get("enabled")):
                    continue
                payload = self._delivery_payload(
                    item,
                    article_id=article_id,
                    source_name=str(source.get("display_name") or ""),
                    test=False,
                )
                for channel_state in active_channels:
                    target_mode = bool(
                        channel_state.get("_target_mode")
                    )
                    if target_mode:
                        target_enabled_at = _parse_time(
                            channel_state.get("enabled_at")
                        )
                        binding_enabled_at = _parse_time(
                            channel_state.get("binding_enabled_at")
                        )
                        if (
                            target_enabled_at is None
                            or binding_enabled_at is None
                        ):
                            continue
                        enabled_at = max(
                            account_enabled_at,
                            target_enabled_at,
                            binding_enabled_at,
                            subscription_enabled_at,
                        )
                    else:
                        channel_enabled_at = _parse_time(
                            channel_state.get("enabled_at")
                        )
                        if channel_enabled_at is None:
                            continue
                        enabled_at = max(
                            account_enabled_at,
                            channel_enabled_at,
                            subscription_enabled_at,
                        )
                    if published_at <= enabled_at:
                        continue
                    inserted = conn.execute(
                        """
                        INSERT OR IGNORE INTO preferred_source_notification_deliveries (
                            id, workspace_id, user_id, subscription_id,
                            source_id, snapshot_id, job_id, article_id,
                            channel, payload_json, status, attempts,
                            account_notification_generation,
                            channel_notification_generation,
                            subscription_notification_generation,
                            target_id, target_name_snapshot,
                            target_config_generation,
                            target_activation_generation,
                            binding_generation,
                            created_at, updated_at
                        ) VALUES (
                            ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                            'pending', 0, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                        )
                        """,
                        (
                            _new_id(),
                            workspace_id,
                            user_id,
                            subscription_id,
                            source_id,
                            snapshot_id,
                            str(job["id"]),
                            article_id,
                            str(channel_state["channel"]),
                            _json_dumps(payload),
                            account_generation,
                            (
                                0
                                if target_mode
                                else int(
                                    channel_state.get("generation") or 0
                                )
                            ),
                            subscription_generation,
                            (
                                str(channel_state["id"])
                                if target_mode
                                else None
                            ),
                            (
                                str(channel_state["name"])
                                if target_mode
                                else ""
                            ),
                            (
                                int(
                                    channel_state.get(
                                        "config_generation"
                                    )
                                    or 0
                                )
                                if target_mode
                                else 0
                            ),
                            (
                                int(
                                    channel_state.get(
                                        "activation_generation"
                                    )
                                    or 0
                                )
                                if target_mode
                                else 0
                            ),
                            (
                                int(
                                    channel_state.get(
                                        "binding_generation"
                                    )
                                    or 0
                                )
                                if target_mode
                                else 0
                            ),
                            now,
                            now,
                        ),
                    )
                    staged += max(int(inserted.rowcount), 0)
        return staged

    def dispatch_pending(
        self,
        *,
        job_id: str | None = None,
        limit: int = _MAX_DELIVERIES_PER_TICK,
    ) -> dict[str, int]:
        """Best-effort batched dispatch; claimed rows are never retried."""

        summary = {"claimed": 0, "succeeded": 0, "failed": 0}
        delivery_limit = max(
            0,
            min(int(limit), _MAX_DELIVERIES_PER_TICK),
        )
        while summary["claimed"] < delivery_limit:
            deliveries = self._claim_pending_batch(
                job_id=job_id,
                limit=delivery_limit - summary["claimed"],
            )
            if not deliveries:
                break
            summary["claimed"] += len(deliveries)
            unfinished_deliveries = deliveries
            send_started = False
            try:
                first = deliveries[0]
                user = self.store.get_user(str(first["user_id"]))
                if (
                    user is None
                    or not bool(user.get("enabled"))
                    or str(user.get("workspace_id"))
                    != str(first["workspace_id"])
                ):
                    raise NotificationServiceError(
                        "notification_user_disabled",
                        "notification user was disabled before delivery",
                        status_code=409,
                    )
                settings = self.store.get_user_notification_settings(
                    workspace_id=str(first["workspace_id"]),
                    user_id=str(first["user_id"]),
                )
                target_mode = bool(first.get("target_id"))
                target: dict[str, Any] | None = None
                binding: dict[str, Any] | None = None
                channel_state: dict[str, Any] | None = None
                if target_mode:
                    target = self.store.get_notification_target(
                        workspace_id=str(first["workspace_id"]),
                        target_id=str(first["target_id"]),
                    )
                    binding = next(
                        (
                            candidate
                            for candidate in self.store.list_user_notification_target_bindings(
                                workspace_id=str(first["workspace_id"]),
                                user_id=str(first["user_id"]),
                            )
                            if str(candidate.get("id"))
                            == str(first["target_id"])
                        ),
                        None,
                    )
                else:
                    channel_state = (
                        self.store.get_user_notification_channel(
                            workspace_id=str(first["workspace_id"]),
                            user_id=str(first["user_id"]),
                            channel=str(first["channel"]),
                        )
                    )
                if settings is None or not bool(settings.get("enabled")):
                    raise NotificationServiceError(
                        "notification_settings_changed",
                        "notification settings changed before delivery",
                        status_code=409,
                    )
                if target_mode:
                    if (
                        target is None
                        or binding is None
                        or not bool(binding.get("binding_enabled"))
                        or not self.notification_targets.target_is_available(
                            target
                        )
                    ):
                        raise NotificationServiceError(
                            "notification_target_changed",
                            "notification target changed before delivery",
                            status_code=409,
                        )
                else:
                    if channel_state is None or not bool(
                        channel_state.get("enabled")
                    ):
                        raise NotificationServiceError(
                            "notification_settings_changed",
                            "notification settings changed before delivery",
                            status_code=409,
                        )
                    if (
                        str(first.get("channel") or "") == "webhook"
                        and not self._webhook_signing_binding_valid(
                            settings
                        )
                    ):
                        raise NotificationServiceError(
                            "invalid_webhook_signing_secret",
                            "configured webhook signing secret is unavailable",
                            status_code=409,
                        )
                account_enabled_at = _parse_time(
                    settings.get("notification_enabled_at")
                )
                account_generation = int(
                    settings.get("notification_generation") or 0
                )
                channel_enabled_at = (
                    _parse_time(channel_state.get("enabled_at"))
                    if channel_state is not None
                    else None
                )
                channel_generation = (
                    int(channel_state.get("generation") or 0)
                    if channel_state is not None
                    else 0
                )
                target_enabled_at = (
                    _parse_time(target.get("enabled_at"))
                    if target is not None
                    else None
                )
                binding_enabled_at = (
                    _parse_time(binding.get("binding_enabled_at"))
                    if binding is not None
                    else None
                )
                if (
                    account_enabled_at is None
                    or (
                        target_mode
                        and (
                            target_enabled_at is None
                            or binding_enabled_at is None
                        )
                    )
                    or (not target_mode and channel_enabled_at is None)
                ):
                    raise NotificationServiceError(
                        "notification_settings_changed",
                        "notification settings changed before delivery",
                        status_code=409,
                    )
                active_deliveries: list[dict[str, Any]] = []
                inactive_ids: list[str] = []
                stale_ids: list[str] = []
                for delivery in deliveries:
                    subscription = self.store.get_subscription(
                        str(delivery["subscription_id"])
                    )
                    source = self.store.get_source(str(delivery["source_id"]))
                    if (
                        subscription is None
                        or str(subscription.get("user_id"))
                        != str(delivery["user_id"])
                        or str(subscription.get("source_id"))
                        != str(delivery["source_id"])
                        or not bool(subscription.get("enabled"))
                        or not bool(subscription.get("notify_on_new_items"))
                        or str(subscription.get("analysis_mode"))
                        == "personal_only"
                        or source is None
                        or str(source.get("workspace_id"))
                        != str(delivery["workspace_id"])
                        or not bool(source.get("enabled"))
                    ):
                        inactive_ids.append(str(delivery["id"]))
                        continue
                    subscription_generation = (
                        self.store.get_subscription_notification_generation(
                            str(delivery["subscription_id"])
                        )
                    )
                    if (
                        int(
                            delivery.get(
                                "account_notification_generation"
                            )
                            or 0
                        )
                        != account_generation
                        or (
                            target_mode
                            and (
                                int(
                                    delivery.get(
                                        "target_config_generation"
                                    )
                                    or 0
                                )
                                != int(
                                    target.get("config_generation")
                                    if target
                                    else 0
                                )
                                or int(
                                    delivery.get(
                                        "target_activation_generation"
                                    )
                                    or 0
                                )
                                != int(
                                    target.get("activation_generation")
                                    if target
                                    else 0
                                )
                                or int(
                                    delivery.get(
                                        "binding_generation"
                                    )
                                    or 0
                                )
                                != int(
                                    binding.get("binding_generation")
                                    if binding
                                    else 0
                                )
                            )
                        )
                        or (
                            not target_mode
                            and int(
                                delivery.get(
                                    "channel_notification_generation"
                                )
                                or 0
                            )
                            != channel_generation
                        )
                        or int(
                            delivery.get(
                                "subscription_notification_generation"
                            )
                            or 0
                        )
                        != int(subscription_generation or 0)
                    ):
                        stale_ids.append(str(delivery["id"]))
                        continue
                    subscription_enabled_at = _parse_time(
                        subscription.get("notification_enabled_at")
                    )
                    published_at = _parse_time(
                        delivery["payload"].get("published_at")
                    )
                    staged_at = _parse_time(delivery.get("created_at"))
                    if (
                        subscription_enabled_at is None
                        or subscription_generation is None
                    ):
                        stale_ids.append(str(delivery["id"]))
                        continue
                    current_watermark = (
                        max(
                            account_enabled_at,
                            target_enabled_at,
                            binding_enabled_at,
                            subscription_enabled_at,
                        )
                        if (
                            target_mode
                            and target_enabled_at is not None
                            and binding_enabled_at is not None
                        )
                        else max(
                            account_enabled_at,
                            channel_enabled_at,
                            subscription_enabled_at,
                        )
                    )
                    if (
                        published_at is None
                        or staged_at is None
                        or published_at <= current_watermark
                        or staged_at <= current_watermark
                    ):
                        stale_ids.append(str(delivery["id"]))
                        continue
                    active_deliveries.append(delivery)
                unfinished_deliveries = active_deliveries
                if inactive_ids:
                    self._finish_deliveries(
                        inactive_ids,
                        succeeded=False,
                        error_code="notification_subscription_disabled",
                    )
                    summary["failed"] += len(inactive_ids)
                if stale_ids:
                    self._finish_deliveries(
                        stale_ids,
                        succeeded=False,
                        error_code="notification_delivery_stale",
                    )
                    summary["failed"] += len(stale_ids)
                if not active_deliveries:
                    continue
                send_started = True
                delivery_settings = (
                    self.notification_targets.delivery_settings(
                        target,
                        user_id=str(first["user_id"]),
                    )
                    if target is not None
                    else {
                        **settings,
                        "channel": str(first["channel"]),
                        "_channel_state": channel_state,
                    }
                )
                self._send_payload(
                    delivery_settings,
                    self._batch_delivery_payload(active_deliveries),
                )
            except NotificationTargetError as exc:
                if not exc.outcome_unknown:
                    self._finish_deliveries(
                        [
                            str(delivery["id"])
                            for delivery in unfinished_deliveries
                        ],
                        succeeded=False,
                        error_code=exc.code,
                    )
                    summary["failed"] += len(unfinished_deliveries)
            except NotificationServiceError as exc:
                if not exc.outcome_unknown:
                    self._finish_deliveries(
                        [
                            str(delivery["id"])
                            for delivery in unfinished_deliveries
                        ],
                        succeeded=False,
                        error_code=exc.code,
                    )
                    summary["failed"] += len(unfinished_deliveries)
            except Exception:
                if not send_started:
                    self._finish_deliveries(
                        [
                            str(delivery["id"])
                            for delivery in unfinished_deliveries
                        ],
                        succeeded=False,
                        error_code="notification_delivery_failed",
                    )
                    summary["failed"] += len(unfinished_deliveries)
            else:
                active_ids = [
                    str(delivery["id"])
                    for delivery in active_deliveries
                ]
                self._finish_deliveries(active_ids, succeeded=True)
                summary["succeeded"] += len(active_ids)
        return summary

    def send_test(
        self,
        *,
        workspace_id: str,
        user_id: str,
        channel: str | None = None,
    ) -> dict[str, Any]:
        """Send fixed sample content without changing outbox or Feed cursors."""

        settings = self.store.get_user_notification_settings(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        if settings is None:
            raise NotificationServiceError(
                "notification_destination_required",
                "configure notification settings before sending a test",
                status_code=409,
            )
        target_channel = str(
            channel
            or self.get_public_settings(
                workspace_id=workspace_id,
                user_id=user_id,
            )["channel"]
        ).strip().lower()
        if target_channel not in NOTIFICATION_CHANNELS:
            raise NotificationServiceError(
                "invalid_notification_channel",
                "notification channel must be email, webhook, or telegram",
            )
        attempt = self.store.claim_user_notification_test_attempt(
            workspace_id=workspace_id,
            user_id=user_id,
            channel=target_channel,
            cooldown_seconds=_TEST_COOLDOWN_SECONDS,
        )
        if attempt.get("reason") == "user_disabled":
            raise NotificationServiceError(
                "notification_channel_unavailable",
                "notification test is unavailable for this account",
                status_code=409,
            )
        if not bool(attempt["claimed"]):
            raise NotificationServiceError(
                "notification_test_rate_limited",
                "wait before sending another notification test",
                status_code=429,
                retryable=True,
            )
        settings = attempt["settings"]
        payload = self._delivery_payload(
            {
                "title": "Inteliscope 推送测试",
                "summary_zh": "这是一条模拟的新内容通知，用于验证当前通知通道。",
                "url": "https://example.com/inteliscope-notification-test",
                "published_at": datetime.now(timezone.utc).isoformat(),
            },
            article_id="notification-test",
            source_name="Inteliscope",
            test=True,
        )
        channel_state = settings.get("_channel_state") or {}
        generation = int(channel_state.get("generation") or 0)
        try:
            send_result = self._send_payload(settings, payload)
        except NotificationServiceError as exc:
            self.store.record_user_notification_test(
                workspace_id=workspace_id,
                user_id=user_id,
                channel=target_channel,
                status="failed",
                generation=generation,
                error_code=exc.code,
            )
            raise NotificationServiceError(
                (
                    "notification_test_outcome_unknown"
                    if exc.outcome_unknown
                    else "notification_test_failed"
                ),
                (
                    "notification test outcome is unknown; do not retry"
                    if exc.outcome_unknown
                    else "notification test could not be delivered"
                ),
                status_code=exc.status_code,
                retryable=exc.retryable and not exc.outcome_unknown,
                outcome_unknown=exc.outcome_unknown,
            ) from exc
        except Exception as exc:
            error = NotificationServiceError(
                "notification_test_outcome_unknown",
                "notification test outcome is unknown; do not retry",
                status_code=502,
                outcome_unknown=True,
            )
            self.store.record_user_notification_test(
                workspace_id=workspace_id,
                user_id=user_id,
                channel=target_channel,
                status="failed",
                generation=generation,
                error_code="notification_delivery_outcome_unknown",
            )
            raise error from exc
        recorded = self.store.record_user_notification_test(
            workspace_id=workspace_id,
            user_id=user_id,
            channel=target_channel,
            status="sent",
            generation=generation,
        )
        if recorded is None:
            raise NotificationServiceError(
                "notification_test_outcome_unknown",
                "notification settings changed while the test was running; "
                "do not retry",
                status_code=409,
                outcome_unknown=True,
            )
        result: dict[str, Any] = {
            "sent": True,
            "channel": target_channel,
        }
        if isinstance(send_result, WebhookSendResult):
            result.update(
                {
                    "provider": send_result.provider,
                    "verification": send_result.verification,
                }
            )
        elif isinstance(send_result, TelegramSendResult):
            result.update(
                {
                    "message_id": send_result.message_id,
                    "verification": send_result.verification,
                }
            )
        return result

    @staticmethod
    def _delivery_payload(
        item: dict[str, Any],
        *,
        article_id: str,
        source_name: str,
        test: bool,
    ) -> dict[str, Any]:
        presentation = (
            item.get("presentation")
            if isinstance(item.get("presentation"), dict)
            else {}
        )
        content = (
            presentation.get("content")
            if isinstance(presentation.get("content"), dict)
            else {}
        )
        summary = (
            item.get("summary_zh")
            or content.get("summary")
            or content.get("excerpt")
            or item.get("excerpt")
            or ""
        )
        return {
            "schema_version": 1,
            "kind": "test" if test else "new_item",
            "article_id": _bounded_text(article_id, 256),
            "source_name": _bounded_text(source_name, 160),
            "title": _bounded_text(item.get("title") or content.get("title"), 300),
            "summary": _bounded_text(summary, 600),
            "published_at": _bounded_text(item.get("published_at"), 80),
            "url": _safe_article_url(item.get("url")),
        }

    @staticmethod
    def _batch_delivery_payload(
        deliveries: list[dict[str, Any]],
    ) -> dict[str, Any]:
        items: list[dict[str, Any]] = []
        seen_article_ids: set[str] = set()
        for delivery in deliveries:
            article_id = str(delivery.get("article_id") or "")
            if article_id in seen_article_ids:
                continue
            seen_article_ids.add(article_id)
            items.append(delivery["payload"])
            if len(items) >= _MAX_DELIVERIES_PER_TICK:
                break
        return {
            "schema_version": 1,
            "kind": "new_items",
            "items": items,
        }

    def _claim_pending_batch(
        self,
        *,
        job_id: str | None,
        limit: int,
    ) -> list[dict[str, Any]]:
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError("notification dispatch requires no active transaction")
        try:
            conn.execute("BEGIN IMMEDIATE")
            job_clause = " AND job_id = ?" if job_id is not None else ""
            parameters: tuple[Any, ...] = (job_id,) if job_id is not None else ()
            row = conn.execute(
                f"""
                SELECT workspace_id, user_id, channel, target_id, job_id
                FROM preferred_source_notification_deliveries
                WHERE status = 'pending'{job_clause}
                ORDER BY created_at, id
                LIMIT 1
                """,
                parameters,
            ).fetchone()
            if row is None:
                conn.commit()
                return []
            article_rows = conn.execute(
                """
                SELECT article_id, MIN(created_at) AS first_created_at
                FROM preferred_source_notification_deliveries
                WHERE status = 'pending'
                  AND workspace_id = ?
                  AND user_id = ?
                  AND channel = ?
                  AND target_id IS ?
                  AND job_id IS ?
                GROUP BY article_id
                ORDER BY first_created_at, article_id
                LIMIT ?
                """,
                (
                    row["workspace_id"],
                    row["user_id"],
                    row["channel"],
                    row["target_id"],
                    row["job_id"],
                    max(
                        1,
                        min(int(limit), _MAX_DELIVERIES_PER_TICK),
                    ),
                ),
            ).fetchall()
            article_ids = [
                str(candidate["article_id"])
                for candidate in article_rows
            ]
            if not article_ids:
                conn.commit()
                return []
            article_placeholders = ",".join(
                "?" for _value in article_ids
            )
            rows = conn.execute(
                f"""
                SELECT id
                FROM preferred_source_notification_deliveries
                WHERE status = 'pending'
                  AND workspace_id = ?
                  AND user_id = ?
                  AND channel = ?
                  AND target_id IS ?
                  AND job_id IS ?
                  AND article_id IN ({article_placeholders})
                ORDER BY created_at, id
                """,
                (
                    row["workspace_id"],
                    row["user_id"],
                    row["channel"],
                    row["target_id"],
                    row["job_id"],
                    *article_ids,
                ),
            ).fetchall()
            delivery_ids = [str(candidate["id"]) for candidate in rows]
            if not delivery_ids:
                conn.commit()
                return []
            now = datetime.now(timezone.utc).isoformat()
            placeholders = ",".join("?" for _value in delivery_ids)
            updated = conn.execute(
                f"""
                UPDATE preferred_source_notification_deliveries
                SET status = 'sending',
                    attempts = attempts + 1,
                    started_at = ?,
                    updated_at = ?
                WHERE id IN ({placeholders}) AND status = 'pending'
                """,
                (now, now, *delivery_ids),
            )
            if updated.rowcount != len(delivery_ids):
                conn.rollback()
                return []
            claimed_rows = conn.execute(
                f"""
                SELECT *
                FROM preferred_source_notification_deliveries
                WHERE id IN ({placeholders})
                ORDER BY created_at, id
                """,
                delivery_ids,
            ).fetchall()
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        return [
            delivery
            for claimed_row in claimed_rows
            if (
                delivery
                := self.store._preferred_source_notification_delivery(
                    claimed_row
                )
            )
        ]

    def _finish_deliveries(
        self,
        delivery_ids: list[str],
        *,
        succeeded: bool,
        error_code: str | None = None,
    ) -> None:
        if not delivery_ids:
            return
        safe_error = (
            error_code
            if error_code and _SAFE_ERROR_CODE_RE.fullmatch(error_code)
            else "notification_delivery_failed"
        )
        now = datetime.now(timezone.utc).isoformat()
        placeholders = ",".join("?" for _value in delivery_ids)
        updated = self.store.connect().execute(
            f"""
            UPDATE preferred_source_notification_deliveries
            SET status = ?,
                error_code = ?,
                sent_at = ?,
                updated_at = ?
            WHERE id IN ({placeholders}) AND status = 'sending'
            """,
            (
                "succeeded" if succeeded else "failed",
                None if succeeded else safe_error,
                now if succeeded else None,
                now,
                *delivery_ids,
            ),
        )
        self.store.connect().commit()
        if updated.rowcount != len(delivery_ids):
            raise RuntimeError("notification deliveries are no longer sending")

    def _send_payload(
        self,
        settings: dict[str, Any],
        payload: dict[str, Any],
    ) -> WebhookSendResult | TelegramSendResult | None:
        channel = str(settings.get("channel") or "")
        if channel == "webhook":
            return self._send_webhook(settings, payload)
        if channel == "email":
            self._send_email(settings, payload)
            return None
        if channel == "telegram":
            return self._send_telegram(settings, payload)
        raise NotificationServiceError(
            "invalid_notification_channel",
            "notification channel must be email, webhook, or telegram",
        )

    def _send_telegram(
        self,
        settings: dict[str, Any],
        payload: dict[str, Any],
    ) -> TelegramSendResult:
        channel_state = settings.get("_channel_state")
        if not isinstance(channel_state, dict):
            channel_state = self.store.get_user_notification_channel(
                workspace_id=str(settings.get("workspace_id") or ""),
                user_id=str(settings.get("user_id") or ""),
                channel="telegram",
            )
        chat_id = (
            str(settings.get("_resolved_destination") or "")
            or self._bound_telegram_chat_id(channel_state)
        )
        if not chat_id:
            raise NotificationServiceError(
                "notification_destination_required",
                "Telegram Chat ID is not configured",
                status_code=409,
            )
        text = _preferred_source_webhook_text(
            payload,
            limit=4096,
        )
        try:
            return self.telegram_transport.send_message(
                workspace_id=str(settings.get("workspace_id") or ""),
                chat_id=chat_id,
                text=text,
            )
        except TelegramTransportServiceError as exc:
            raise NotificationServiceError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                outcome_unknown=exc.outcome_unknown,
            ) from exc

    def _send_webhook(
        self,
        settings: dict[str, Any],
        payload: dict[str, Any],
    ) -> WebhookSendResult:
        webhook_url = (
            str(settings.get("_resolved_destination") or "")
            or self._bound_webhook_secret(settings)
        )
        if not webhook_url:
            raise NotificationServiceError(
                "notification_destination_required",
                "notification webhook is not configured",
                status_code=409,
            )
        signing_secret = (
            settings.get("_resolved_signing_secret")
            if "_notification_target" in settings
            else self._bound_webhook_signing_secret(settings)
        )
        if (
            (
                bool(
                    (
                        settings.get("_notification_target")
                        if isinstance(
                            settings.get("_notification_target"), dict
                        )
                        else {}
                    ).get("webhook_signing_env_name")
                )
                if "_notification_target" in settings
                else self._has_webhook_signing_metadata(settings)
            )
            and signing_secret is None
        ):
            raise NotificationServiceError(
                "invalid_webhook_signing_secret",
                "configured webhook signing secret is unavailable",
                status_code=409,
            )
        stored_provider = normalize_stored_webhook_provider(
            settings.get("webhook_provider")
        )
        effective_provider = resolve_webhook_provider(
            stored_provider,
            webhook_url,
        )
        event = (
            "inteliscope.preferred_source.test"
            if payload.get("kind") == "test"
            else "inteliscope.preferred_source.new_items"
        )
        data = (
            {**payload, "test": True}
            if payload.get("kind") == "test"
            else {
                "schema_version": 1,
                "items": list(payload.get("items") or [])[
                    :_MAX_DELIVERIES_PER_TICK
                ],
            }
        )
        text = _preferred_source_webhook_text(
            payload,
            limit=webhook_text_limit(effective_provider),
        )
        try:
            result = _run_coroutine(
                asyncio.wait_for(
                    send_notification_webhook(
                        provider=stored_provider,
                        webhook_url=webhook_url,
                        event=event,
                        data=data,
                        text=text,
                        signing_secret=signing_secret,
                        timeout=5.0,
                        post=post_public_http,
                    ),
                    timeout=6.0,
                )
            )
        except WebhookConfigurationError as exc:
            raise NotificationServiceError(
                exc.code,
                str(exc),
                status_code=400,
            ) from exc
        except WebhookDeliveryError as exc:
            raise NotificationServiceError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                outcome_unknown=exc.outcome_unknown,
            ) from exc
        except TimeoutError as exc:
            raise NotificationServiceError(
                "notification_webhook_outcome_unknown",
                "notification webhook outcome is unknown",
                status_code=502,
                outcome_unknown=True,
            ) from exc
        except Exception as exc:
            raise NotificationServiceError(
                "notification_webhook_outcome_unknown",
                "notification webhook outcome is unknown",
                status_code=502,
                outcome_unknown=True,
            ) from exc
        if not isinstance(result, WebhookSendResult):
            raise NotificationServiceError(
                "notification_webhook_outcome_unknown",
                "notification webhook outcome is unknown",
                status_code=502,
                outcome_unknown=True,
            )
        return result

    def _send_email(
        self,
        settings: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        recipient = _normalize_email(
            settings.get("_resolved_destination")
            or settings.get("email_address")
        )
        if not recipient:
            raise NotificationServiceError(
                "notification_destination_required",
                "notification email address is not configured",
                status_code=409,
            )
        try:
            self.email_transport.send_notification(
                workspace_id=str(settings.get("workspace_id") or ""),
                recipient_email=recipient,
                payload=payload,
            )
        except EmailTransportError as exc:
            raise NotificationServiceError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                outcome_unknown=exc.outcome_unknown,
            ) from exc
