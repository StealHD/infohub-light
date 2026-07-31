"""Workspace-scoped operational alerts for the Apify X Actor route."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import json
import math
import os
import re
import threading
import uuid
from datetime import datetime, timedelta, timezone
from email.utils import parseaddr
from typing import Any, Coroutine

from ..storage.service_store import NOTIFICATION_CHANNELS, ServiceStore
from .network_policy import post_public_http
from .notification_email_transport import (
    EmailTransportError,
    WorkspaceEmailTransportService,
)
from .notification_telegram_transport import (
    TelegramConfigurationError,
    TelegramSendResult,
    normalize_telegram_chat_id,
)
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
from .secret_store import SecretStore
from .workspace_telegram_transport import (
    TelegramTransportServiceError,
    WorkspaceTelegramTransportService,
)
from .notification_targets import (
    NotificationTargetError,
    NotificationTargetService,
)


UNSET = object()
ALERT_EVENTS = (
    "actor_switched",
    "route_exhausted",
    "quota_low",
    "budget_blocked",
    "start_outcome_unknown",
    "recovered",
)
OPENING_ALERT_EVENTS = frozenset(ALERT_EVENTS[:-1])
ALERT_SEVERITIES = frozenset({"info", "warning", "critical"})
MAX_DELIVERY_ATTEMPTS = 3
TEST_COOLDOWN_SECONDS = 60
_RETRY_DELAYS_SECONDS = (60, 300)
_SAFE_CODE_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_SAFE_KEY_RE = re.compile(r"^[A-Za-z0-9][A-Za-z0-9_.:/-]{0,159}$")
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_FEISHU_TEXT_LIMIT = 3_500
_FEISHU_MARKUP_TRANSLATION = str.maketrans({"<": "＜", ">": "＞"})
_ALERT_EVENT_LABELS = {
    "actor_switched": "自动切换 Actor",
    "route_exhausted": "三个 Actor 全部不可用",
    "quota_low": "Apify 额度偏低",
    "budget_blocked": "额度耗尽或费用熔断",
    "start_outcome_unknown": "Actor 启动结果未知",
    "recovered": "故障恢复",
    "test": "测试",
}
_ALERT_SEVERITY_LABELS = {
    "info": "信息",
    "warning": "警告",
    "critical": "严重",
}


class ApifyActorAlertError(RuntimeError):
    """A bounded operational-alert error safe for an API envelope."""

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
        self.code = _safe_code(code, "apify_actor_alert_failed")
        self.status_code = int(status_code)
        self.retryable = bool(retryable)
        self.outcome_unknown = bool(outcome_unknown)


def _safe_code(value: Any, fallback: str) -> str:
    candidate = str(value or "").strip().lower()
    return candidate if _SAFE_CODE_RE.fullmatch(candidate) else fallback


def _bounded_text(value: Any, limit: int) -> str:
    text = " ".join(str(value or "").split())
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _feishu_dynamic_text(value: Any, limit: int) -> str:
    """Bound dynamic alert text and neutralize Feishu inline markup."""

    return _bounded_text(value, limit).translate(_FEISHU_MARKUP_TRANSLATION)


def _json_dumps(value: Any) -> str:
    return json.dumps(
        value,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    )


def _json_object(value: Any) -> dict[str, Any]:
    if isinstance(value, dict):
        return dict(value)
    if not isinstance(value, str) or not value:
        return {}
    try:
        parsed = json.loads(value)
    except (TypeError, ValueError):
        return {}
    return dict(parsed) if isinstance(parsed, dict) else {}


def _utc_now() -> datetime:
    return datetime.now(timezone.utc)


def _iso(value: datetime | str | None = None) -> str:
    if value is None:
        parsed = _utc_now()
    elif isinstance(value, datetime):
        parsed = value
    else:
        try:
            parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
        except ValueError as exc:
            raise ApifyActorAlertError(
                "invalid_apify_actor_alert_settings",
                "alert timestamp must be ISO 8601",
            ) from exc
    if parsed.tzinfo is None:
        raise ApifyActorAlertError(
            "invalid_apify_actor_alert_settings",
            "alert timestamp must include a timezone",
        )
    return parsed.astimezone(timezone.utc).isoformat()


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


def _normalize_email(value: Any) -> str | None:
    candidate = str(value or "").strip()
    if not candidate:
        return None
    if len(candidate) > 320 or any(marker in candidate for marker in ("\r", "\n", "\x00")):
        raise ApifyActorAlertError(
            "invalid_notification_destination",
            "notification email address is invalid",
        )
    display_name, address = parseaddr(candidate)
    if display_name or address != candidate or not _EMAIL_RE.fullmatch(address):
        raise ApifyActorAlertError(
            "invalid_notification_destination",
            "notification email address is invalid",
        )
    return address


def _bounded_multiline_text(lines: list[str], *, limit: int) -> str:
    text = "\n".join(line for line in lines if line is not None)
    if len(text) <= limit:
        return text
    return text[: max(limit - 1, 0)].rstrip() + "…"


def _apify_alert_feishu_body(
    payload: dict[str, Any],
    *,
    test: bool,
) -> dict[str, Any]:
    event_type = _bounded_text(payload.get("event_type"), 64) or "unknown"
    severity = _bounded_text(payload.get("severity"), 32) or "unknown"
    title = (
        "Inteliscope Apify 运行告警测试"
        if test
        else (
            "Inteliscope Apify 恢复通知"
            if event_type == "recovered"
            else "Inteliscope Apify 运行告警"
        )
    )
    lines = [
        title,
        (
            "事件："
            f"{_ALERT_EVENT_LABELS.get(event_type, _feishu_dynamic_text(event_type, 64))}"
        ),
        (
            "级别："
            f"{_ALERT_SEVERITY_LABELS.get(severity, _feishu_dynamic_text(severity, 32))}"
        ),
        f"路由：{_feishu_dynamic_text(payload.get('route'), 160) or 'x/profile'}",
        f"状态：{_feishu_dynamic_text(payload.get('status'), 80) or 'unknown'}",
    ]
    condition_event_type = _bounded_text(
        payload.get("condition_event_type"),
        64,
    )
    if event_type == "recovered" and condition_event_type:
        condition_label = _ALERT_EVENT_LABELS.get(
            condition_event_type,
            _feishu_dynamic_text(condition_event_type, 64),
        )
        lines.append(f"原告警：{condition_label}")
    for label, field in (
        ("Actor", "actor_name"),
        ("当前 Actor", "active_actor_name"),
        ("原因", "reason_code"),
    ):
        value = _feishu_dynamic_text(payload.get(field), 160)
        if value:
            lines.append(f"{label}：{value}")
    occurred_at = _feishu_dynamic_text(payload.get("occurred_at"), 80)
    if occurred_at:
        occurred_label = "告警时间" if event_type == "recovered" else "时间"
        lines.append(f"{occurred_label}：{occurred_at}")
    resolved_at = _feishu_dynamic_text(payload.get("resolved_at"), 80)
    if event_type == "recovered" and resolved_at:
        lines.append(f"恢复时间：{resolved_at}")
    if test:
        lines.append("这是一条模拟告警，不会调用 Actor 或产生 Apify 费用。")
    return {
        "msg_type": "text",
        "content": {
            "text": _bounded_multiline_text(
                lines,
                limit=_FEISHU_TEXT_LIMIT,
            )
        },
    }


def _normalize_events(value: Any, *, default: tuple[str, ...] = ()) -> tuple[str, ...]:
    if value is None:
        return default
    if not isinstance(value, (list, tuple)):
        raise ApifyActorAlertError(
            "invalid_apify_actor_alert_settings",
            "alert events must be a list",
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_event in value:
        event = str(raw_event or "").strip()
        if event not in ALERT_EVENTS or event in seen:
            raise ApifyActorAlertError(
                "invalid_apify_actor_alert_settings",
                "alert events contain an unsupported or duplicate value",
            )
        seen.add(event)
        normalized.append(event)
    return tuple(event for event in ALERT_EVENTS if event in seen)


def _normalize_channels(value: Any) -> list[str]:
    if not isinstance(value, (list, tuple)):
        raise ApifyActorAlertError(
            "invalid_apify_actor_alert_settings",
            "alert channels must be a list",
        )
    normalized: list[str] = []
    seen: set[str] = set()
    for raw_channel in value:
        channel = str(raw_channel or "").strip().lower()
        if channel not in NOTIFICATION_CHANNELS or channel in seen:
            raise ApifyActorAlertError(
                "invalid_apify_actor_alert_settings",
                "alert channels contain an unsupported or duplicate value",
            )
        normalized.append(channel)
        seen.add(channel)
    return normalized


def _public_delivery_status(value: Any) -> str | None:
    status = str(value or "").strip().lower()
    return {
        "pending": "pending",
        "sending": "unknown",
        "succeeded": "sent",
        "failed": "failed",
    }.get(status)


def _run_coroutine(coroutine: Coroutine[Any, Any, Any]) -> Any:
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

    thread = threading.Thread(
        target=runner,
        name="apify-alert-http",
        daemon=True,
    )
    thread.start()
    thread.join()
    if failure:
        raise failure[0]
    return result[0] if result else None


class ApifyActorAlertService:
    """Persist incident transitions and deliver bounded workspace alerts."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        data_dir: str,
        email_transport: WorkspaceEmailTransportService | None = None,
        telegram_transport: WorkspaceTelegramTransportService | None = None,
        notification_targets: NotificationTargetService | None = None,
    ) -> None:
        self.store = store
        self.secret_store = SecretStore(data_dir)
        self.email_transport = email_transport or WorkspaceEmailTransportService(
            store,
            data_dir=data_dir,
        )
        self.telegram_transport = (
            telegram_transport
            or WorkspaceTelegramTransportService(
                store,
                data_dir=data_dir,
            )
        )
        self.notification_targets = (
            notification_targets
            or NotificationTargetService(
                store,
                data_dir=data_dir,
                email_transport=self.email_transport,
                telegram_transport=self.telegram_transport,
            )
        )

    @staticmethod
    def webhook_env_name(*, workspace_id: str) -> str:
        digest = hashlib.sha256(
            str(workspace_id).encode("utf-8")
        ).hexdigest()[:24].upper()
        return f"HORIZON_APIFY_ALERT_WEBHOOK_{digest}"

    @staticmethod
    def webhook_signing_env_name(*, workspace_id: str) -> str:
        digest = hashlib.sha256(
            str(workspace_id).encode("utf-8")
        ).hexdigest()[:24].upper()
        return f"HORIZON_APIFY_ALERT_WEBHOOK_SIGNING_{digest}"

    @staticmethod
    def telegram_chat_env_name(*, workspace_id: str) -> str:
        digest = hashlib.sha256(
            str(workspace_id).encode("utf-8")
        ).hexdigest()[:24].upper()
        return f"HORIZON_APIFY_ALERT_TELEGRAM_CHAT_{digest}"

    def _bound_telegram_chat_id(
        self,
        channel_state: dict[str, Any] | None,
    ) -> str | None:
        if channel_state is None:
            return None
        workspace_id = str(channel_state.get("workspace_id") or "")
        expected_env = self.telegram_chat_env_name(
            workspace_id=workspace_id
        )
        env_name = str(channel_state.get("destination_env_name") or "")
        expected_digest = str(
            channel_state.get("destination_secret_digest") or ""
        )
        if (
            not workspace_id
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

    def _settings_row(self, workspace_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            """
            SELECT *
            FROM apify_actor_alert_settings
            WHERE workspace_id = ?
            """,
            (workspace_id,),
        ).fetchone()
        if row is None:
            return None
        settings = dict(row)
        settings["enabled"] = bool(settings.get("enabled"))
        settings["generation"] = max(0, int(settings.get("generation") or 0))
        try:
            raw_events = json.loads(str(settings.get("events_json") or "[]"))
            settings["events"] = list(_normalize_events(raw_events))
        except (TypeError, ValueError, ApifyActorAlertError):
            settings["events"] = []
        return settings

    def _bound_webhook_secret(
        self,
        settings: dict[str, Any] | None,
    ) -> str | None:
        if settings is None:
            return None
        workspace_id = str(settings.get("workspace_id") or "")
        env_name = str(settings.get("webhook_env_name") or "")
        expected_digest = str(settings.get("webhook_secret_digest") or "")
        expected_env = self.webhook_env_name(workspace_id=workspace_id)
        if (
            not workspace_id
            or env_name != expected_env
            or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
        ):
            return None
        secret = self.secret_store.read().get(expected_env)
        if not secret:
            return None
        actual_digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        return (
            secret
            if hmac.compare_digest(actual_digest, expected_digest)
            else None
        )

    def _bound_webhook_signing_secret(
        self,
        settings: dict[str, Any] | None,
    ) -> str | None:
        if settings is None:
            return None
        workspace_id = str(settings.get("workspace_id") or "")
        env_name = str(
            settings.get("webhook_signing_env_name") or ""
        )
        expected_digest = str(
            settings.get("webhook_signing_secret_digest") or ""
        )
        expected_env = self.webhook_signing_env_name(
            workspace_id=workspace_id
        )
        if (
            not workspace_id
            or env_name != expected_env
            or not re.fullmatch(r"[0-9a-f]{64}", expected_digest)
        ):
            return None
        secret = self.secret_store.read().get(expected_env)
        if not secret:
            return None
        actual_digest = hashlib.sha256(
            secret.encode("utf-8")
        ).hexdigest()
        return (
            secret
            if hmac.compare_digest(actual_digest, expected_digest)
            else None
        )

    @staticmethod
    def _has_webhook_signing_metadata(
        settings: dict[str, Any] | None,
    ) -> bool:
        return bool(
            settings is not None
            and (
                settings.get("webhook_signing_env_name") is not None
                or settings.get("webhook_signing_secret_digest") is not None
            )
        )

    def _webhook_signing_binding_valid(
        self,
        settings: dict[str, Any] | None,
    ) -> bool:
        return (
            not self._has_webhook_signing_metadata(settings)
            or self._bound_webhook_signing_secret(settings) is not None
        )

    def _last_delivery(self, workspace_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            """
            SELECT channel, settings_generation, channel_generation,
                   status, error_code,
                   created_at, started_at, sent_at, updated_at
            FROM apify_actor_alert_deliveries
            WHERE workspace_id = ?
            ORDER BY created_at DESC, id DESC
            LIMIT 1
            """,
            (workspace_id,),
        ).fetchone()
        if row is None:
            return None
        delivery = dict(row)
        delivery["status"] = _public_delivery_status(delivery.get("status"))
        return delivery

    def get_public_settings(self, *, workspace_id: str) -> dict[str, Any]:
        settings = self._settings_row(workspace_id)
        channel_rows = self.store.list_apify_actor_alert_channels(
            workspace_id=workspace_id
        )
        rows_by_channel = {
            str(row["channel"]): row for row in channel_rows
        }
        last_delivery = self._last_delivery(workspace_id)
        if last_delivery is not None:
            delivery_channel = str(last_delivery.get("channel") or "")
            current_channel = rows_by_channel.get(delivery_channel)
            if (
                settings is None
                or current_channel is None
                or int(last_delivery.get("settings_generation") or 0)
                != int(settings.get("generation") or 0)
                or int(last_delivery.get("channel_generation") or 0)
                != int(current_channel.get("generation") or 0)
            ):
                last_delivery = None
        webhook_url = self._bound_webhook_secret(settings) or ""
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
        for channel_name in NOTIFICATION_CHANNELS:
            row = rows_by_channel.get(channel_name)
            last_test_status = (row or {}).get("last_test_status")
            last_test_error = (row or {}).get(
                "last_test_error_code"
            )
            if (
                last_test_status == "failed"
                and last_test_error
                in {
                    "notification_webhook_outcome_unknown",
                    "notification_webhook_response_invalid",
                    "notification_telegram_outcome_unknown",
                    "notification_telegram_response_invalid",
                    "notification_delivery_outcome_unknown",
                }
            ):
                last_test_status = "unknown"
            if channel_name == "email":
                configured = bool(
                    (settings or {}).get("email_address")
                )
                available = bool(configured and email_ready)
            elif channel_name == "webhook":
                configured = bool(webhook_url)
                available = bool(
                    webhook_url
                    and self._webhook_signing_binding_valid(settings)
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
                "last_test_status": last_test_status,
                "last_tested_at": (row or {}).get("last_tested_at"),
                "last_test_error_code": last_test_error,
            }
            if channel_name == "webhook":
                state.update(
                    {
                        "provider": effective_provider,
                        "provider_explicit": stored_provider
                        != LEGACY_AUTO,
                        "signing_secret_configured": bool(
                            self._bound_webhook_signing_secret(settings)
                        ),
                        "verification_mode": webhook_verification_mode(
                            effective_provider
                        ),
                    }
                )
            channel_states[channel_name] = state
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
            self.store.list_apify_actor_alert_target_bindings(
                workspace_id=workspace_id,
                enabled_only=True,
            )
        )
        selected_targets = [
            self.notification_targets.public_target(
                target,
                actor={"id": "", "role": "viewer"},
            )
            for target in target_bindings
        ]
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
            "events": list(
                (settings or {}).get("events") or ALERT_EVENTS
            ),
            "email_configured": channel_states["email"]["configured"],
            "email_transport_ready": email_ready,
            "webhook_configured": bool(webhook_url),
            "webhook_provider": effective_provider,
            "webhook_provider_explicit": stored_provider != LEGACY_AUTO,
            "webhook_signing_secret_configured": bool(
                self._bound_webhook_signing_secret(settings)
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
            "last_alert_status": (
                last_delivery.get("status") if last_delivery else None
            ),
            "last_alerted_at": self._last_alert_time(last_delivery),
            "last_alert_error_code": (
                last_delivery.get("error_code") if last_delivery else None
            ),
            "updated_at": (settings or {}).get("updated_at"),
        }

    @staticmethod
    def _last_alert_time(delivery: dict[str, Any] | None) -> str | None:
        if delivery is None:
            return None
        return (
            delivery.get("sent_at")
            or delivery.get("started_at")
            or delivery.get("updated_at")
            or delivery.get("created_at")
        )

    def upsert_settings(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        enabled: Any = UNSET,
        channel: Any = UNSET,
        channels: Any = UNSET,
        target_ids: Any = UNSET,
        events: Any = UNSET,
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
                raise ApifyActorAlertError(
                    "invalid_apify_actor_alert_settings",
                    "target_ids cannot be combined with legacy channel configuration",
                )
            if not isinstance(target_ids, list):
                raise ApifyActorAlertError(
                    "invalid_notification_targets",
                    "notification target_ids must be a list",
                )
            conn = self.store.connect()
            if conn.in_transaction:
                raise RuntimeError(
                    "Apify Actor alert settings update requires no active transaction"
                )
            try:
                conn.execute("BEGIN IMMEDIATE")
                self._require_admin(
                    workspace_id=workspace_id,
                    actor_user_id=actor_user_id,
                )
                current = self._settings_row(workspace_id)
                target_enabled = self._target_enabled(current, enabled)
                target_events = (
                    tuple(current.get("events") or ())
                    if events is UNSET and current is not None
                    else (
                        ALERT_EVENTS
                        if events is UNSET
                        else _normalize_events(events)
                    )
                )
                now = _iso()
                current_enabled = bool((current or {}).get("enabled"))
                generation = max(
                    1, int((current or {}).get("generation") or 1)
                )
                settings_changed = (
                    target_enabled != current_enabled
                    or tuple(target_events)
                    != tuple((current or {}).get("events") or ())
                )
                if settings_changed:
                    generation += 1
                    conn.execute(
                        """
                        UPDATE apify_actor_alert_deliveries
                        SET status = 'failed',
                            error_code = 'notification_settings_changed',
                            retry_at = NULL, updated_at = ?
                        WHERE workspace_id = ? AND status = 'pending'
                        """,
                        (now, workspace_id),
                    )
                enabled_at = (current or {}).get(
                    "notification_enabled_at"
                )
                if not target_enabled:
                    enabled_at = None
                elif not current_enabled:
                    enabled_at = now
                conn.execute(
                    """
                    INSERT INTO apify_actor_alert_settings (
                        workspace_id, enabled, channel, events_json,
                        webhook_provider, generation,
                        notification_enabled_at, created_at, updated_at
                    ) VALUES (?, ?, 'webhook', ?, 'generic_event', ?, ?, ?, ?)
                    ON CONFLICT(workspace_id) DO UPDATE SET
                        enabled = excluded.enabled,
                        events_json = excluded.events_json,
                        generation = excluded.generation,
                        notification_enabled_at =
                            excluded.notification_enabled_at,
                        updated_at = excluded.updated_at
                    """,
                    (
                        workspace_id,
                        1 if target_enabled else 0,
                        _json_dumps(list(target_events)),
                        generation,
                        enabled_at,
                        now,
                        now,
                    ),
                )
                self.store.set_apify_actor_alert_target_bindings(
                    workspace_id=workspace_id,
                    actor_user_id=actor_user_id,
                    target_ids=[str(value) for value in target_ids],
                    commit=False,
                )
                conn.commit()
            except (LookupError, ValueError) as exc:
                if conn.in_transaction:
                    conn.rollback()
                raise ApifyActorAlertError(
                    "notification_target_unavailable",
                    "one or more shared notification targets are unavailable",
                    status_code=409,
                ) from exc
            except Exception:
                if conn.in_transaction:
                    conn.rollback()
                raise
            return self.get_public_settings(workspace_id=workspace_id)
        shared_targets = [
            target
            for target in self.store.list_notification_targets(
                workspace_id=workspace_id,
                user_id=actor_user_id,
            )
            if target.get("scope") == "shared"
        ]
        legacy_fields_touched = any(
            value is not UNSET
            for value in (
                enabled,
                channel,
                channels,
                events,
                email_address,
                webhook_url,
                webhook_provider,
                webhook_signing_secret,
                telegram_chat_id,
            )
        )
        if shared_targets and legacy_fields_touched:
            by_channel: dict[str, list[dict[str, Any]]] = {
                name: [
                    target
                    for target in shared_targets
                    if str(target.get("channel")) == name
                ]
                for name in NOTIFICATION_CHANNELS
            }

            def unique_target(channel_name: str) -> dict[str, Any]:
                matches = by_channel[channel_name]
                if len(matches) != 1:
                    raise ApifyActorAlertError(
                        "notification_target_legacy_conflict",
                        "legacy alert settings cannot select an ambiguous shared target",
                        status_code=409,
                    )
                return matches[0]

            requested_channels: list[str] | None = None
            if channels is not UNSET:
                requested_channels = _normalize_channels(channels)
            elif channel is not UNSET:
                requested_channels = [
                    self._target_channel(None, channel)
                ]
            if requested_channels is not None:
                selected_ids = [
                    str(unique_target(name)["id"])
                    for name in requested_channels
                ]
            else:
                selected_ids = [
                    str(binding["id"])
                    for binding in self.store.list_apify_actor_alert_target_bindings(
                        workspace_id=workspace_id,
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
                    actor_user_id=actor_user_id,
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
                actor_user_id=actor_user_id,
                enabled=enabled,
                events=events,
                target_ids=selected_ids,
            )
        if channel is not UNSET and channels is not UNSET:
            raise ApifyActorAlertError(
                "invalid_apify_actor_alert_settings",
                "channel and channels are mutually exclusive",
            )
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "Apify Actor alert settings update requires no active transaction"
            )
        expected_url_env = self.webhook_env_name(
            workspace_id=workspace_id
        )
        expected_signing_env = self.webhook_signing_env_name(
            workspace_id=workspace_id
        )
        previous_secrets: dict[str, str | None] = {}
        secrets_written = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._require_admin(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
            )
            current = self._settings_row(workspace_id)
            current_channel_rows = (
                self.store.list_apify_actor_alert_channels(
                    workspace_id=workspace_id
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
            target_enabled = self._target_enabled(current, enabled)
            if channels is not UNSET:
                target_channels = _normalize_channels(channels)
            elif channel is not UNSET:
                target_channels = [
                    self._target_channel(current, channel)
                ]
            else:
                target_channels = list(current_active_channels)
            target_channel = (
                target_channels[0]
                if target_channels
                else str((current or {}).get("channel") or "webhook")
            ).strip().lower()
            if target_channel not in NOTIFICATION_CHANNELS:
                target_channel = "webhook"
            target_events = (
                (
                    tuple(current.get("events") or ())
                    if current is not None
                    else ALERT_EVENTS
                )
                if events is UNSET
                else _normalize_events(events)
            )
            target_email = (
                (current or {}).get("email_address")
                if email_address is UNSET
                else _normalize_email(email_address)
            )

            secret_values = self.secret_store.read()
            current_url_env = str(
                (current or {}).get("webhook_env_name") or ""
            )
            target_url_env = (
                current_url_env
                if current_url_env == expected_url_env
                else None
            )
            target_url_digest = (
                str((current or {}).get("webhook_secret_digest") or "")
                if target_url_env
                else ""
            ) or None
            current_url = self._bound_webhook_secret(current)
            current_provider = normalize_stored_webhook_provider(
                (current or {}).get("webhook_provider")
            )
            if webhook_provider is UNSET:
                target_provider = current_provider
            else:
                if webhook_provider is None:
                    raise ApifyActorAlertError(
                        "invalid_webhook_provider",
                        "webhook provider cannot be null",
                    )
                target_provider = normalize_stored_webhook_provider(
                    webhook_provider
                )
                if target_provider == LEGACY_AUTO:
                    raise ApifyActorAlertError(
                        "invalid_webhook_provider",
                        "legacy_auto is not a selectable webhook provider",
                    )
            provider_changed = target_provider != current_provider
            url_touched = webhook_url is not UNSET
            if provider_changed and not url_touched:
                raise ApifyActorAlertError(
                    "webhook_url_required_for_provider_change",
                    "re-enter the webhook URL when changing provider",
                )
            validated_webhook: str | None = current_url
            if url_touched:
                if webhook_url is None or not str(webhook_url).strip():
                    validated_webhook = None
                    target_url_env = None
                    target_url_digest = None
                else:
                    validated_webhook = validate_webhook_url(
                        webhook_url,
                        target_provider,
                        legacy_compat=target_provider == LEGACY_AUTO,
                    )
                    target_url_env = expected_url_env
                    target_url_digest = hashlib.sha256(
                        validated_webhook.encode("utf-8")
                    ).hexdigest()
            elif validated_webhook:
                validate_webhook_url(
                    validated_webhook,
                    target_provider,
                    legacy_compat=target_provider == LEGACY_AUTO,
                )
            else:
                target_url_env = None
                target_url_digest = None

            current_signing_env = str(
                (current or {}).get("webhook_signing_env_name") or ""
            )
            target_signing_env = (
                current_signing_env
                if current_signing_env == expected_signing_env
                else None
            )
            target_signing_digest = (
                str(
                    (current or {}).get(
                        "webhook_signing_secret_digest"
                    )
                    or ""
                )
                if target_signing_env
                else ""
            ) or None
            current_signing_secret = self._bound_webhook_signing_secret(
                current
            )
            signing_touched = webhook_signing_secret is not UNSET
            validated_signing_secret: str | None = current_signing_secret
            implicit_signing_clear = bool(
                not signing_touched
                and (
                    provider_changed
                    or (url_touched and validated_webhook is None)
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
                        raise ApifyActorAlertError(
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
                raise ApifyActorAlertError(
                    "webhook_signing_not_supported",
                    "selected webhook provider does not support signing",
                )

            webhook_configured = bool(
                target_url_env
                and target_url_digest
                and validated_webhook
            )

            telegram_row = current_channels_by_name.get("telegram")
            expected_telegram_env = self.telegram_chat_env_name(
                workspace_id=workspace_id
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
                        else normalize_telegram_chat_id(
                            telegram_chat_id
                        )
                    )
                except TelegramConfigurationError as exc:
                    raise ApifyActorAlertError(
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

            selected = set(target_channels)
            if target_enabled and "email" in selected and not target_email:
                raise ApifyActorAlertError(
                    "notification_destination_required",
                    "configure an alert email address before enabling email alerts",
                    status_code=409,
                )
            if (
                target_enabled
                and "webhook" in selected
                and not webhook_configured
            ):
                raise ApifyActorAlertError(
                    "notification_destination_required",
                    "configure an alert webhook before enabling webhook alerts",
                    status_code=409,
                )
            if (
                target_enabled
                and "telegram" in selected
                and not validated_telegram_chat_id
            ):
                raise ApifyActorAlertError(
                    "notification_destination_required",
                    "configure an alert Telegram Chat ID before enabling Telegram alerts",
                    status_code=409,
                )

            current_generation = max(
                0,
                int((current or {}).get("generation") or 0),
            )
            global_changed = current is None or any(
                (
                    target_enabled != bool((current or {}).get("enabled")),
                    target_events
                    != (
                        tuple(current.get("events") or ())
                        if current is not None
                        else ALERT_EVENTS
                    ),
                )
            )
            target_generation = current_generation + int(global_changed)
            secret_updates: dict[str, str | None] = {}
            if url_touched:
                secret_updates[expected_url_env] = validated_webhook
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

            now = _iso()
            notification_enabled_at = (current or {}).get(
                "notification_enabled_at"
            )
            if not target_enabled:
                notification_enabled_at = None
            elif (
                not bool((current or {}).get("enabled"))
                or notification_enabled_at is None
            ):
                notification_enabled_at = now
            conn.execute(
                """
                INSERT INTO apify_actor_alert_settings (
                    workspace_id, enabled, channel, events_json, email_address,
                    webhook_env_name, webhook_secret_digest,
                    webhook_provider, webhook_signing_env_name,
                    webhook_signing_secret_digest, notification_enabled_at,
                    generation,
                    last_test_status, last_test_generation,
                    last_test_attempted_at, last_tested_at,
                    last_test_error_code, created_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?
                )
                ON CONFLICT(workspace_id) DO UPDATE SET
                    enabled = excluded.enabled,
                    channel = excluded.channel,
                    events_json = excluded.events_json,
                    email_address = excluded.email_address,
                    webhook_env_name = excluded.webhook_env_name,
                    webhook_secret_digest = excluded.webhook_secret_digest,
                    webhook_provider = excluded.webhook_provider,
                    webhook_signing_env_name =
                        excluded.webhook_signing_env_name,
                    webhook_signing_secret_digest =
                        excluded.webhook_signing_secret_digest,
                    notification_enabled_at =
                        excluded.notification_enabled_at,
                    generation = excluded.generation,
                    last_test_status = excluded.last_test_status,
                    last_test_generation = excluded.last_test_generation,
                    last_test_attempted_at = excluded.last_test_attempted_at,
                    last_tested_at = excluded.last_tested_at,
                    last_test_error_code = excluded.last_test_error_code,
                    updated_at = excluded.updated_at
                """,
                (
                    workspace_id,
                    1 if target_enabled else 0,
                    target_channel,
                    _json_dumps(list(target_events)),
                    target_email,
                    target_url_env,
                    target_url_digest,
                    target_provider,
                    target_signing_env,
                    target_signing_digest,
                    notification_enabled_at,
                    target_generation,
                    (current or {}).get("last_test_status"),
                    (current or {}).get("last_test_generation"),
                    (current or {}).get("last_test_attempted_at"),
                    (current or {}).get("last_tested_at"),
                    (current or {}).get("last_test_error_code"),
                    (current or {}).get("created_at") or now,
                    now,
                ),
            )

            changed_channel_names: set[str] = set()
            channel_specific_changes = {
                "email": (
                    target_email
                    != (current or {}).get("email_address")
                ),
                "webhook": any(
                    (
                        target_url_env
                        != (current or {}).get("webhook_env_name"),
                        target_url_digest
                        != (current or {}).get(
                            "webhook_secret_digest"
                        ),
                        target_provider
                        != str(
                            (current or {}).get("webhook_provider")
                            or LEGACY_AUTO
                        ),
                        target_signing_env
                        != (current or {}).get(
                            "webhook_signing_env_name"
                        ),
                        target_signing_digest
                        != (current or {}).get(
                            "webhook_signing_secret_digest"
                        ),
                    )
                ),
                "telegram": (
                    target_telegram_env
                    != (telegram_row or {}).get(
                        "destination_env_name"
                    )
                    or target_telegram_digest
                    != (telegram_row or {}).get(
                        "destination_secret_digest"
                    )
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
                reset_test = material_changed
                self.store.upsert_apify_actor_alert_channel(
                    workspace_id=workspace_id,
                    channel=channel_name,
                    position=ordered_position,
                    enabled=channel_enabled,
                    enabled_at=enabled_at,
                    generation=generation,
                    destination_env_name=(
                        target_telegram_env
                        if channel_name == "telegram"
                        else None
                    ),
                    destination_secret_digest=(
                        target_telegram_digest
                        if channel_name == "telegram"
                        else None
                    ),
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
            if global_changed:
                conn.execute(
                    """
                    UPDATE apify_actor_alert_deliveries
                    SET status = 'failed',
                        error_code = 'notification_settings_changed',
                        updated_at = ?
                    WHERE workspace_id = ? AND status = 'pending'
                    """,
                    (now, workspace_id),
                )
            else:
                for changed_channel in changed_channel_names:
                    conn.execute(
                        """
                        UPDATE apify_actor_alert_deliveries
                        SET status = 'failed',
                            retry_at = NULL,
                            error_code = 'notification_settings_changed',
                            updated_at = ?
                        WHERE workspace_id = ? AND channel = ?
                          AND status = 'pending'
                        """,
                        (now, workspace_id, changed_channel),
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
                    "Apify alert SecretStore compensation failed"
                ) from compensation_error
            if isinstance(
                exc,
                (WebhookConfigurationError, TelegramConfigurationError),
            ):
                raise ApifyActorAlertError(
                    exc.code,
                    str(exc),
                ) from exc
            raise
        return self.get_public_settings(workspace_id=workspace_id)

    @staticmethod
    def _target_enabled(
        current: dict[str, Any] | None,
        enabled: Any,
    ) -> bool:
        if enabled is UNSET:
            return bool((current or {}).get("enabled"))
        if not isinstance(enabled, bool):
            raise ApifyActorAlertError(
                "invalid_apify_actor_alert_settings",
                "enabled must be a boolean",
            )
        return enabled

    @staticmethod
    def _target_channel(
        current: dict[str, Any] | None,
        channel: Any,
    ) -> str:
        if channel is UNSET:
            candidate = str((current or {}).get("channel") or "webhook")
        elif channel is None:
            candidate = ""
        else:
            candidate = str(channel).strip().lower()
        if candidate not in NOTIFICATION_CHANNELS:
            raise ApifyActorAlertError(
                "invalid_apify_actor_alert_settings",
                "alert channel must be email, webhook, or telegram",
            )
        return candidate

    def open_incident(
        self,
        *,
        workspace_id: str,
        route_key: str,
        incident_key: str,
        event_type: str,
        severity: str,
        payload: dict[str, Any] | None = None,
        opened_at: datetime | str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        route = self._safe_key(route_key, label="route")
        condition = self._safe_key(incident_key, label="incident")
        if event_type not in OPENING_ALERT_EVENTS:
            raise ApifyActorAlertError(
                "invalid_apify_actor_alert_event",
                "opening alert event is unsupported",
            )
        if severity not in ALERT_SEVERITIES:
            raise ApifyActorAlertError(
                "invalid_apify_actor_alert_event",
                "alert severity is unsupported",
            )
        event_at = _iso(opened_at)
        safe_payload = self._safe_incident_details(payload)
        conn = self.store.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        if not commit and not conn.in_transaction:
            raise RuntimeError(
                "non-committing incident creation requires an active transaction"
            )
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            incident_id = f"aai_{uuid.uuid4().hex}"
            inserted = conn.execute(
                """
                INSERT OR IGNORE INTO apify_actor_alert_incidents (
                    id, workspace_id, route_key, incident_key, event_type,
                    severity, status, payload_json, opened_at, last_seen_at,
                    resolved_at, created_at, updated_at
                ) VALUES (?, ?, ?, ?, ?, ?, 'open', ?, ?, ?, NULL, ?, ?)
                """,
                (
                    incident_id,
                    workspace_id,
                    route,
                    condition,
                    event_type,
                    severity,
                    _json_dumps(safe_payload),
                    event_at,
                    event_at,
                    event_at,
                    event_at,
                ),
            )
            created = inserted.rowcount == 1
            if not created:
                row = conn.execute(
                    """
                    SELECT *
                    FROM apify_actor_alert_incidents
                    WHERE workspace_id = ?
                      AND route_key = ?
                      AND incident_key = ?
                      AND status = 'open'
                    """,
                    (workspace_id, route, condition),
                ).fetchone()
                if row is None:
                    raise RuntimeError(
                        "open incident conflict did not resolve to a row"
                    )
                incident_id = str(row["id"])
                previous_payload = _json_object(row["payload_json"])
                merged_payload = {
                    **previous_payload,
                    **{
                        key: value
                        for key, value in safe_payload.items()
                        if value not in {None, ""}
                    },
                }
                conn.execute(
                    """
                    UPDATE apify_actor_alert_incidents
                    SET last_seen_at = ?, payload_json = ?, updated_at = ?
                    WHERE id = ? AND status = 'open'
                    """,
                    (
                        event_at,
                        _json_dumps(merged_payload),
                        event_at,
                        incident_id,
                    ),
                )
            incident = self._incident_row(incident_id)
            if incident is None:
                raise RuntimeError("created incident could not be loaded")
            delivery_staged = bool(
                created
                and self._stage_delivery(
                    incident=incident,
                    event_type=event_type,
                    now=event_at,
                )
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        incident = self._incident_row(incident_id)
        if incident is None:
            raise RuntimeError("incident disappeared after creation")
        return {
            "created": created,
            "delivery_staged": delivery_staged,
            "incident": self._public_incident(incident),
        }

    def resolve_incident(
        self,
        *,
        workspace_id: str,
        route_key: str,
        incident_key: str,
        payload: dict[str, Any] | None = None,
        resolved_at: datetime | str | None = None,
        commit: bool = True,
    ) -> dict[str, Any]:
        route = self._safe_key(route_key, label="route")
        condition = self._safe_key(incident_key, label="incident")
        event_at = _iso(resolved_at)
        conn = self.store.connect()
        owns_transaction = bool(commit and not conn.in_transaction)
        if not commit and not conn.in_transaction:
            raise RuntimeError(
                "non-committing incident resolution requires an active transaction"
            )
        try:
            if owns_transaction:
                conn.execute("BEGIN IMMEDIATE")
            row = conn.execute(
                """
                SELECT *
                FROM apify_actor_alert_incidents
                WHERE workspace_id = ?
                  AND route_key = ?
                  AND incident_key = ?
                  AND status = 'open'
                """,
                (workspace_id, route, condition),
            ).fetchone()
            if row is None:
                if owns_transaction:
                    conn.commit()
                return {
                    "resolved": False,
                    "delivery_staged": False,
                    "incident": None,
                }
            incident_id = str(row["id"])
            merged_payload = {
                **_json_object(row["payload_json"]),
                **self._safe_incident_details(payload),
            }
            updated = conn.execute(
                """
                UPDATE apify_actor_alert_incidents
                SET status = 'resolved',
                    payload_json = ?,
                    resolved_at = ?,
                    last_seen_at = ?,
                    updated_at = ?
                WHERE id = ? AND status = 'open'
                """,
                (
                    _json_dumps(merged_payload),
                    event_at,
                    event_at,
                    event_at,
                    incident_id,
                ),
            )
            if updated.rowcount != 1:
                if owns_transaction:
                    conn.commit()
                return {
                    "resolved": False,
                    "delivery_staged": False,
                    "incident": None,
                }
            incident = self._incident_row(incident_id)
            if incident is None:
                raise RuntimeError("resolved incident could not be loaded")
            opening_channels = {
                str(opening["channel"])
                for opening in conn.execute(
                    """
                    SELECT DISTINCT delivery.channel
                    FROM apify_actor_alert_deliveries AS delivery
                    JOIN apify_actor_alert_settings AS settings
                      ON settings.workspace_id = delivery.workspace_id
                    JOIN apify_actor_alert_channels AS channel_state
                      ON channel_state.workspace_id = delivery.workspace_id
                     AND channel_state.channel = delivery.channel
                    WHERE delivery.incident_id = ?
                      AND delivery.event_type != 'recovered'
                      AND delivery.settings_generation = settings.generation
                      AND delivery.channel_generation =
                          channel_state.generation
                    """,
                    (incident_id,),
                ).fetchall()
            }
            opening_target_ids = {
                str(opening["target_id"])
                for opening in conn.execute(
                    """
                    SELECT DISTINCT target_id
                    FROM apify_actor_alert_deliveries
                    WHERE incident_id = ?
                      AND event_type != 'recovered'
                      AND target_id IS NOT NULL
                    """,
                    (incident_id,),
                ).fetchall()
                if opening["target_id"]
            }
            delivery_staged = bool(
                (opening_channels or opening_target_ids)
                and self._stage_delivery(
                    incident=incident,
                    event_type="recovered",
                    now=event_at,
                    allowed_channels=opening_channels,
                    allowed_target_ids=opening_target_ids,
                )
            )
            if owns_transaction:
                conn.commit()
        except Exception:
            if owns_transaction and conn.in_transaction:
                conn.rollback()
            raise
        incident = self._incident_row(incident_id)
        if incident is None:
            raise RuntimeError("incident disappeared after resolution")
        return {
            "resolved": True,
            "delivery_staged": delivery_staged,
            "incident": self._public_incident(incident),
        }

    @staticmethod
    def _safe_key(value: Any, *, label: str) -> str:
        candidate = str(value or "").strip()
        if not _SAFE_KEY_RE.fullmatch(candidate):
            raise ApifyActorAlertError(
                "invalid_apify_actor_alert_event",
                f"{label} key is invalid",
            )
        return candidate

    @staticmethod
    def _safe_incident_details(
        payload: dict[str, Any] | None,
    ) -> dict[str, Any]:
        source = payload if isinstance(payload, dict) else {}
        reason_code = _safe_code(source.get("reason_code"), "")
        return {
            "actor_name": _bounded_text(source.get("actor_name"), 160),
            "active_actor_name": _bounded_text(
                source.get("active_actor_name"),
                160,
            ),
            "reason_code": reason_code,
        }

    def _incident_row(self, incident_id: str) -> dict[str, Any] | None:
        row = self.store.connect().execute(
            """
            SELECT *
            FROM apify_actor_alert_incidents
            WHERE id = ?
            """,
            (incident_id,),
        ).fetchone()
        if row is None:
            return None
        incident = dict(row)
        incident["payload"] = self._safe_incident_details(
            _json_object(incident.pop("payload_json", None))
        )
        return incident

    def _channel_can_deliver(
        self,
        settings: dict[str, Any] | None,
        channel_state: dict[str, Any] | None,
        *,
        event_type: str,
        event_at: datetime,
    ) -> bool:
        if (
            settings is None
            or channel_state is None
            or not bool(settings.get("enabled"))
            or not bool(channel_state.get("enabled"))
            or event_type not in set(settings.get("events") or ())
        ):
            return False
        global_enabled_at = _parse_time(
            settings.get("notification_enabled_at")
        )
        channel_enabled_at = _parse_time(
            channel_state.get("enabled_at")
        )
        if (
            global_enabled_at is None
            or channel_enabled_at is None
            or event_at <= max(global_enabled_at, channel_enabled_at)
        ):
            return False
        workspace_id = str(settings.get("workspace_id") or "")
        channel = str(channel_state.get("channel") or "")
        if channel == "email":
            return bool(
                settings.get("email_address")
                and self.email_transport.is_ready(
                    workspace_id=workspace_id
                )
            )
        if channel == "webhook":
            return bool(
                self._bound_webhook_secret(settings)
                and self._webhook_signing_binding_valid(settings)
            )
        if channel == "telegram":
            return bool(
                self._bound_telegram_chat_id(channel_state)
                and self.telegram_transport.is_ready(
                    workspace_id=workspace_id
                )
            )
        return False

    def _stage_delivery(
        self,
        *,
        incident: dict[str, Any],
        event_type: str,
        now: str,
        allowed_channels: set[str] | None = None,
        allowed_target_ids: set[str] | None = None,
    ) -> int:
        workspace_id = str(incident["workspace_id"])
        settings = self._settings_row(workspace_id)
        if settings is None:
            return 0
        event_at = _parse_time(now)
        if event_at is None:
            return 0
        target_bindings = (
            self.store.list_apify_actor_alert_target_bindings(
                workspace_id=workspace_id,
            )
        )
        channel_rows = self.store.list_apify_actor_alert_channels(
            workspace_id=workspace_id
        )
        payload = self._delivery_payload(
            incident,
            event_type=event_type,
        )
        staged = 0
        if target_bindings:
            global_enabled_at = _parse_time(
                settings.get("notification_enabled_at")
            )
            for target in target_bindings:
                target_id = str(target.get("id") or "")
                if (
                    allowed_target_ids is not None
                    and target_id not in allowed_target_ids
                ):
                    continue
                target_enabled_at = _parse_time(
                    target.get("enabled_at")
                )
                binding_enabled_at = _parse_time(
                    target.get("binding_enabled_at")
                )
                if (
                    not bool(settings.get("enabled"))
                    or event_type
                    not in set(settings.get("events") or ())
                    or not bool(target.get("binding_enabled"))
                    or global_enabled_at is None
                    or target_enabled_at is None
                    or binding_enabled_at is None
                    or event_at
                    <= max(
                        global_enabled_at,
                        target_enabled_at,
                        binding_enabled_at,
                    )
                    or not self.notification_targets.target_is_available(
                        target
                    )
                ):
                    continue
                inserted = self.store.connect().execute(
                    """
                    INSERT OR IGNORE INTO apify_actor_alert_deliveries (
                        id, workspace_id, incident_id, event_type, channel,
                        settings_generation, channel_generation,
                        target_id, target_name_snapshot,
                        target_config_generation,
                        target_activation_generation, binding_generation,
                        payload_json, status, attempts, retry_at, error_code,
                        created_at, started_at, sent_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, 1, ?, ?, ?, ?, ?, ?,
                        'pending', 0, NULL, NULL, ?, NULL, NULL, ?
                    )
                    """,
                    (
                        f"aad_{uuid.uuid4().hex}",
                        workspace_id,
                        incident["id"],
                        event_type,
                        str(target["channel"]),
                        settings["generation"],
                        target_id,
                        str(target["name"]),
                        int(target.get("config_generation") or 0),
                        int(target.get("activation_generation") or 0),
                        int(target.get("binding_generation") or 0),
                        _json_dumps(payload),
                        now,
                        now,
                    ),
                )
                staged += max(0, int(inserted.rowcount))
            return staged
        for channel_state in channel_rows:
            channel_name = str(channel_state.get("channel") or "")
            if (
                allowed_channels is not None
                and channel_name not in allowed_channels
            ):
                continue
            if not self._channel_can_deliver(
                settings,
                channel_state,
                event_type=event_type,
                event_at=event_at,
            ):
                continue
            inserted = self.store.connect().execute(
                """
                INSERT OR IGNORE INTO apify_actor_alert_deliveries (
                    id, workspace_id, incident_id, event_type, channel,
                    settings_generation, channel_generation,
                    payload_json, status, attempts, retry_at, error_code,
                    created_at, started_at, sent_at, updated_at
                ) VALUES (
                    ?, ?, ?, ?, ?, ?, ?, ?, 'pending', 0, NULL, NULL, ?,
                    NULL, NULL, ?
                )
                """,
                (
                    f"aad_{uuid.uuid4().hex}",
                    workspace_id,
                    incident["id"],
                    event_type,
                    channel_name,
                    settings["generation"],
                    int(channel_state.get("generation") or 0),
                    _json_dumps(payload),
                    now,
                    now,
                ),
            )
            staged += max(0, int(inserted.rowcount))
        return staged

    def _delivery_payload(
        self,
        incident: dict[str, Any],
        *,
        event_type: str,
    ) -> dict[str, Any]:
        details = self._safe_incident_details(incident.get("payload"))
        resolved = event_type == "recovered"
        payload = {
            "schema_version": 1,
            "incident_id": _bounded_text(incident.get("id"), 80),
            "event_type": event_type,
            "condition_event_type": _bounded_text(
                incident.get("event_type"),
                40,
            ),
            "severity": (
                "info"
                if resolved
                else str(incident.get("severity") or "warning")
            ),
            "route": _bounded_text(incident.get("route_key"), 64),
            "status": "resolved" if resolved else "open",
            "actor_name": details["actor_name"],
            "active_actor_name": details["active_actor_name"],
            "reason_code": details["reason_code"],
            "occurred_at": _bounded_text(
                (
                    incident.get("resolved_at")
                    if resolved
                    else incident.get("opened_at")
                ),
                80,
            ),
            "resolved_at": (
                _bounded_text(incident.get("resolved_at"), 80)
                if resolved
                else ""
            ),
        }
        return self._sanitize_delivery_payload(payload)

    @staticmethod
    def _sanitize_delivery_payload(payload: Any) -> dict[str, Any]:
        source = payload if isinstance(payload, dict) else {}
        event_type = str(source.get("event_type") or "")
        if event_type not in ALERT_EVENTS and event_type != "test":
            event_type = ""
        condition_event = str(source.get("condition_event_type") or "")
        if condition_event not in OPENING_ALERT_EVENTS:
            condition_event = ""
        severity = str(source.get("severity") or "")
        if severity not in ALERT_SEVERITIES:
            severity = "warning"
        status = str(source.get("status") or "")
        if status not in {"open", "resolved", "test"}:
            status = "open"
        return {
            "schema_version": 1,
            "incident_id": _bounded_text(source.get("incident_id"), 80),
            "event_type": event_type,
            "condition_event_type": condition_event,
            "severity": severity,
            "route": _bounded_text(source.get("route"), 64),
            "status": status,
            "actor_name": _bounded_text(source.get("actor_name"), 160),
            "active_actor_name": _bounded_text(
                source.get("active_actor_name"),
                160,
            ),
            "reason_code": _safe_code(source.get("reason_code"), ""),
            "occurred_at": _bounded_text(source.get("occurred_at"), 80),
            "resolved_at": _bounded_text(source.get("resolved_at"), 80),
            "test": bool(source.get("test")),
        }

    def list_incidents(
        self,
        *,
        workspace_id: str,
        limit: int = 20,
    ) -> list[dict[str, Any]]:
        bounded_limit = max(1, min(int(limit), 100))
        rows = self.store.connect().execute(
            """
            SELECT *
            FROM apify_actor_alert_incidents
            WHERE workspace_id = ?
            ORDER BY opened_at DESC, id DESC
            LIMIT ?
            """,
            (workspace_id, bounded_limit),
        ).fetchall()
        return [self._public_incident(dict(row)) for row in rows]

    def _public_incident_deliveries(
        self,
        *,
        incident_id: str,
    ) -> list[dict[str, Any]]:
        rows = self.store.connect().execute(
            """
            SELECT id, event_type, channel, target_id,
                   target_name_snapshot, status, error_code,
                   created_at, started_at, sent_at, updated_at
            FROM apify_actor_alert_deliveries
            WHERE incident_id = ?
            ORDER BY created_at DESC, id DESC
            """,
            (incident_id,),
        ).fetchall()
        return [
            {
                "event_type": (
                    str(row["event_type"])
                    if str(row["event_type"]) in ALERT_EVENTS
                    else ""
                ),
                "channel": (
                    str(row["channel"])
                    if str(row["channel"]) in NOTIFICATION_CHANNELS
                    else ""
                ),
                "target_id": (
                    str(row["target_id"]) if row["target_id"] else None
                ),
                "target_name": (
                    str(row["target_name_snapshot"])
                    if row["target_id"]
                    else None
                ),
                "status": _public_delivery_status(row["status"]),
                "error_code": (
                    _safe_code(row["error_code"], "") or None
                ),
                "created_at": row["created_at"],
                "started_at": row["started_at"],
                "sent_at": row["sent_at"],
                "updated_at": row["updated_at"],
            }
            for row in rows
        ]

    def _public_incident(
        self,
        incident: dict[str, Any],
    ) -> dict[str, Any]:
        details = self._safe_incident_details(
            incident.get("payload")
            or _json_object(incident.get("payload_json"))
        )
        event_type = str(incident.get("event_type") or "")
        severity = str(incident.get("severity") or "")
        status = str(incident.get("status") or "")
        deliveries = self._public_incident_deliveries(
            incident_id=str(incident.get("id") or "")
        )
        latest_delivery = deliveries[0] if deliveries else None
        return {
            "schema_version": 3,
            "id": _bounded_text(incident.get("id"), 80),
            "route": _bounded_text(incident.get("route_key"), 64),
            "event_type": (
                event_type if event_type in OPENING_ALERT_EVENTS else ""
            ),
            "severity": (
                severity if severity in ALERT_SEVERITIES else "warning"
            ),
            "status": status if status in {"open", "resolved"} else "open",
            "actor_name": details["actor_name"],
            "active_actor_name": details["active_actor_name"],
            "reason_code": details["reason_code"],
            "opened_at": incident.get("opened_at"),
            "last_seen_at": incident.get("last_seen_at"),
            "resolved_at": incident.get("resolved_at"),
            "deliveries": deliveries,
            "delivery_status": (
                latest_delivery.get("status")
                if latest_delivery is not None
                else None
            ),
            "delivery_error_code": (
                latest_delivery.get("error_code")
                if latest_delivery is not None
                else None
            ),
        }

    def dispatch_pending(
        self,
        *,
        workspace_id: str | None = None,
        limit: int = 20,
    ) -> dict[str, int]:
        summary = {
            "claimed": 0,
            "succeeded": 0,
            "failed": 0,
            "retried": 0,
            "unknown": 0,
        }
        bounded_limit = max(0, min(int(limit), 100))
        while summary["claimed"] < bounded_limit:
            claim = self._claim_next_delivery(workspace_id=workspace_id)
            if claim is None:
                break
            summary["claimed"] += 1
            if claim.get("preflight_failed"):
                summary["failed"] += 1
                continue
            delivery = claim["delivery"]
            settings = claim["settings"]
            try:
                self._send_payload(
                    settings,
                    delivery["payload"],
                    test=False,
                )
            except ApifyActorAlertError as exc:
                if exc.outcome_unknown:
                    self._mark_delivery_unknown(
                        str(delivery["id"]),
                        error_code=exc.code,
                    )
                    summary["unknown"] += 1
                    continue
                if (
                    exc.retryable
                    and int(delivery["attempts"]) < MAX_DELIVERY_ATTEMPTS
                ):
                    self._retry_delivery(delivery, error_code=exc.code)
                    summary["retried"] += 1
                else:
                    self._finish_delivery(
                        str(delivery["id"]),
                        succeeded=False,
                        error_code=exc.code,
                    )
                    summary["failed"] += 1
            except Exception:
                # Once the call begins, an unclassified exception may mean the
                # receiver accepted it. Keep ``sending`` and never replay.
                self._mark_delivery_unknown(
                    str(delivery["id"]),
                    error_code="notification_delivery_outcome_unknown",
                )
                summary["unknown"] += 1
            else:
                self._finish_delivery(
                    str(delivery["id"]),
                    succeeded=True,
                )
                summary["succeeded"] += 1
        return summary

    def _claim_next_delivery(
        self,
        *,
        workspace_id: str | None,
    ) -> dict[str, Any] | None:
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "Apify Actor alert dispatch requires no active transaction"
            )
        try:
            conn.execute("BEGIN IMMEDIATE")
            now = _iso()
            workspace_clause = (
                " AND workspace_id = ?" if workspace_id is not None else ""
            )
            parameters: tuple[Any, ...] = (
                (now, workspace_id)
                if workspace_id is not None
                else (now,)
            )
            row = conn.execute(
                f"""
                SELECT *
                FROM apify_actor_alert_deliveries
                WHERE status = 'pending'
                  AND (retry_at IS NULL OR retry_at <= ?)
                  {workspace_clause}
                ORDER BY created_at, id
                LIMIT 1
                """,
                parameters,
            ).fetchone()
            if row is None:
                conn.commit()
                return None
            delivery = dict(row)
            delivery["payload"] = self._sanitize_delivery_payload(
                _json_object(delivery.pop("payload_json", None))
            )
            settings = self._settings_row(str(delivery["workspace_id"]))
            target = None
            target_binding = None
            channel_state = None
            resolved_settings = None
            if delivery.get("target_id"):
                target = self.store.get_notification_target(
                    workspace_id=str(delivery["workspace_id"]),
                    target_id=str(delivery["target_id"]),
                )
                target_binding = next(
                    (
                        candidate
                        for candidate in self.store.list_apify_actor_alert_target_bindings(
                            workspace_id=str(delivery["workspace_id"]),
                        )
                        if str(candidate.get("id"))
                        == str(delivery["target_id"])
                    ),
                    None,
                )
                preflight_error = self._target_delivery_preflight_error(
                    delivery,
                    settings,
                    target,
                    target_binding,
                )
                if preflight_error is None and target is not None:
                    try:
                        resolved_settings = (
                            self.notification_targets.delivery_settings(
                                target
                            )
                        )
                    except NotificationTargetError as exc:
                        preflight_error = exc.code
            else:
                channel_state = self.store.get_apify_actor_alert_channel(
                    workspace_id=str(delivery["workspace_id"]),
                    channel=str(delivery.get("channel") or ""),
                )
                preflight_error = self._delivery_preflight_error(
                    delivery,
                    settings,
                    channel_state,
                )
            if preflight_error is not None:
                conn.execute(
                    """
                    UPDATE apify_actor_alert_deliveries
                    SET status = 'failed', error_code = ?, updated_at = ?
                    WHERE id = ? AND status = 'pending'
                    """,
                    (preflight_error, now, delivery["id"]),
                )
                conn.commit()
                return {
                    "preflight_failed": True,
                    "delivery": delivery,
                    "settings": settings,
                }
            updated = conn.execute(
                """
                UPDATE apify_actor_alert_deliveries
                SET status = 'sending',
                    attempts = attempts + 1,
                    started_at = ?,
                    error_code = NULL,
                    updated_at = ?
                WHERE id = ? AND status = 'pending'
                """,
                (now, now, delivery["id"]),
            )
            if updated.rowcount != 1:
                conn.rollback()
                return None
            delivery["status"] = "sending"
            delivery["attempts"] = int(delivery.get("attempts") or 0) + 1
            delivery["started_at"] = now
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        assert settings is not None
        if resolved_settings is not None:
            return {
                "preflight_failed": False,
                "delivery": delivery,
                "settings": resolved_settings,
            }
        assert channel_state is not None
        return {
            "preflight_failed": False,
            "delivery": delivery,
            "settings": {
                **settings,
                "channel": str(delivery["channel"]),
                "_channel_state": channel_state,
            },
        }

    def _delivery_preflight_error(
        self,
        delivery: dict[str, Any],
        settings: dict[str, Any] | None,
        channel_state: dict[str, Any] | None,
    ) -> str | None:
        if (
            settings is None
            or channel_state is None
            or not bool(settings.get("enabled"))
            or not bool(channel_state.get("enabled"))
        ):
            return "notification_settings_changed"
        if (
            int(delivery.get("settings_generation") or 0)
            != int(settings.get("generation") or 0)
            or int(delivery.get("channel_generation") or 0)
            != int(channel_state.get("generation") or 0)
            or str(delivery.get("channel") or "")
            != str(channel_state.get("channel") or "")
            or str(delivery.get("event_type") or "")
            not in set(settings.get("events") or ())
        ):
            return "notification_settings_changed"
        payload = delivery.get("payload") or {}
        if (
            str(payload.get("event_type") or "")
            != str(delivery.get("event_type") or "")
            or not str(payload.get("route") or "")
        ):
            return "notification_payload_invalid"
        global_enabled_at = _parse_time(
            settings.get("notification_enabled_at")
        )
        channel_enabled_at = _parse_time(
            channel_state.get("enabled_at")
        )
        occurred_at = _parse_time(payload.get("occurred_at"))
        created_at = _parse_time(delivery.get("created_at"))
        if (
            global_enabled_at is None
            or channel_enabled_at is None
            or occurred_at is None
            or created_at is None
            or occurred_at
            <= max(global_enabled_at, channel_enabled_at)
            or created_at
            <= max(global_enabled_at, channel_enabled_at)
        ):
            return "notification_delivery_stale"
        channel = str(channel_state.get("channel") or "")
        if channel == "webhook":
            if not self._bound_webhook_secret(settings):
                return "notification_destination_required"
            if not self._webhook_signing_binding_valid(settings):
                return "invalid_webhook_signing_secret"
            return None
        if channel == "email":
            if not settings.get("email_address"):
                return "notification_destination_required"
            if not self.email_transport.is_ready(
                workspace_id=str(settings.get("workspace_id") or "")
            ):
                return "notification_channel_unavailable"
            return None
        if channel == "telegram":
            if not self._bound_telegram_chat_id(channel_state):
                return "notification_destination_required"
            if not self.telegram_transport.is_ready(
                workspace_id=str(settings.get("workspace_id") or "")
            ):
                return "notification_channel_unavailable"
            return None
        return "notification_settings_changed"

    def _target_delivery_preflight_error(
        self,
        delivery: dict[str, Any],
        settings: dict[str, Any] | None,
        target: dict[str, Any] | None,
        binding: dict[str, Any] | None,
    ) -> str | None:
        if (
            settings is None
            or target is None
            or binding is None
            or not bool(settings.get("enabled"))
            or not bool(binding.get("binding_enabled"))
            or not self.notification_targets.target_is_available(target)
        ):
            return "notification_target_changed"
        if (
            int(delivery.get("settings_generation") or 0)
            != int(settings.get("generation") or 0)
            or int(delivery.get("target_config_generation") or 0)
            != int(target.get("config_generation") or 0)
            or int(delivery.get("target_activation_generation") or 0)
            != int(target.get("activation_generation") or 0)
            or int(delivery.get("binding_generation") or 0)
            != int(binding.get("binding_generation") or 0)
            or str(delivery.get("channel") or "")
            != str(target.get("channel") or "")
            or str(delivery.get("event_type") or "")
            not in set(settings.get("events") or ())
        ):
            return "notification_target_changed"
        payload = delivery.get("payload") or {}
        if (
            str(payload.get("event_type") or "")
            != str(delivery.get("event_type") or "")
            or not str(payload.get("route") or "")
        ):
            return "notification_payload_invalid"
        watermarks = (
            _parse_time(settings.get("notification_enabled_at")),
            _parse_time(target.get("enabled_at")),
            _parse_time(binding.get("binding_enabled_at")),
        )
        occurred_at = _parse_time(payload.get("occurred_at"))
        created_at = _parse_time(delivery.get("created_at"))
        if (
            any(value is None for value in watermarks)
            or occurred_at is None
            or created_at is None
        ):
            return "notification_delivery_stale"
        watermark = max(
            value for value in watermarks if value is not None
        )
        if occurred_at <= watermark or created_at <= watermark:
            return "notification_delivery_stale"
        return None

    def _retry_delivery(
        self,
        delivery: dict[str, Any],
        *,
        error_code: str,
    ) -> None:
        attempts = max(1, int(delivery.get("attempts") or 1))
        delay_index = min(attempts - 1, len(_RETRY_DELAYS_SECONDS) - 1)
        retry_at = _utc_now() + timedelta(
            seconds=_RETRY_DELAYS_SECONDS[delay_index]
        )
        now = _iso()
        updated = self.store.connect().execute(
            """
            UPDATE apify_actor_alert_deliveries
            SET status = 'pending',
                retry_at = ?,
                error_code = ?,
                updated_at = ?
            WHERE id = ? AND status = 'sending'
            """,
            (
                retry_at.isoformat(),
                _safe_code(error_code, "notification_delivery_failed"),
                now,
                delivery["id"],
            ),
        )
        self.store.connect().commit()
        if updated.rowcount != 1:
            raise RuntimeError("alert delivery is no longer sending")

    def _finish_delivery(
        self,
        delivery_id: str,
        *,
        succeeded: bool,
        error_code: str | None = None,
    ) -> None:
        now = _iso()
        updated = self.store.connect().execute(
            """
            UPDATE apify_actor_alert_deliveries
            SET status = ?,
                retry_at = NULL,
                error_code = ?,
                sent_at = ?,
                updated_at = ?
            WHERE id = ? AND status = 'sending'
            """,
            (
                "succeeded" if succeeded else "failed",
                (
                    None
                    if succeeded
                    else _safe_code(
                        error_code,
                        "notification_delivery_failed",
                    )
                ),
                now if succeeded else None,
                now,
                delivery_id,
            ),
        )
        self.store.connect().commit()
        if updated.rowcount != 1:
            raise RuntimeError("alert delivery is no longer sending")

    def _mark_delivery_unknown(
        self,
        delivery_id: str,
        *,
        error_code: str,
    ) -> None:
        """Keep a started delivery non-replayable while exposing a safe state."""

        now = _iso()
        updated = self.store.connect().execute(
            """
            UPDATE apify_actor_alert_deliveries
            SET error_code = ?, retry_at = NULL, updated_at = ?
            WHERE id = ? AND status = 'sending'
            """,
            (
                _safe_code(
                    error_code,
                    "notification_delivery_outcome_unknown",
                ),
                now,
                delivery_id,
            ),
        )
        self.store.connect().commit()
        if updated.rowcount != 1:
            raise RuntimeError("alert delivery is no longer sending")

    def send_test(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        channel: str | None = None,
    ) -> dict[str, Any]:
        target_channel = str(
            channel
            or self.get_public_settings(
                workspace_id=workspace_id
            )["channel"]
        ).strip().lower()
        if target_channel not in NOTIFICATION_CHANNELS:
            raise ApifyActorAlertError(
                "invalid_apify_actor_alert_settings",
                "alert channel must be email, webhook, or telegram",
            )
        settings = self._claim_test_attempt(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            channel=target_channel,
        )
        payload = self._sanitize_delivery_payload(
            {
                "event_type": "test",
                "severity": "info",
                "route": "x/profile",
                "status": "test",
                "reason_code": "manual_test",
                "occurred_at": _iso(),
                "test": True,
            }
        )
        try:
            send_result = self._send_payload(
                settings,
                payload,
                test=True,
            )
        except ApifyActorAlertError as exc:
            self._record_test_result(
                workspace_id=workspace_id,
                channel=target_channel,
                generation=int(
                    settings["_channel_state"]["generation"]
                ),
                status="failed",
                error_code=exc.code,
            )
            raise ApifyActorAlertError(
                (
                    "apify_actor_alert_test_outcome_unknown"
                    if exc.outcome_unknown
                    else "apify_actor_alert_test_failed"
                ),
                (
                    "Apify Actor alert test outcome is unknown; do not retry"
                    if exc.outcome_unknown
                    else "Apify Actor alert test could not be delivered"
                ),
                status_code=exc.status_code,
                retryable=exc.retryable and not exc.outcome_unknown,
                outcome_unknown=exc.outcome_unknown,
            ) from exc
        except Exception as exc:
            self._record_test_result(
                workspace_id=workspace_id,
                channel=target_channel,
                generation=int(
                    settings["_channel_state"]["generation"]
                ),
                status="failed",
                error_code="notification_delivery_outcome_unknown",
            )
            raise ApifyActorAlertError(
                "apify_actor_alert_test_outcome_unknown",
                "Apify Actor alert test outcome is unknown; do not retry",
                status_code=502,
                outcome_unknown=True,
            ) from exc
        if not self._record_test_result(
            workspace_id=workspace_id,
            channel=target_channel,
            generation=int(
                settings["_channel_state"]["generation"]
            ),
            status="sent",
        ):
            raise ApifyActorAlertError(
                "apify_actor_alert_test_outcome_unknown",
                "alert settings changed while the test was running; "
                "do not retry",
                status_code=409,
                outcome_unknown=True,
            )
        result: dict[str, Any] = {
            "sent": True,
            "channel": str(settings["channel"]),
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

    def _claim_test_attempt(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        channel: str,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "Apify Actor alert test requires no active transaction"
            )
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._require_admin(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
            )
            settings = self._settings_row(workspace_id)
            if settings is None:
                raise ApifyActorAlertError(
                    "notification_destination_required",
                    "configure Apify Actor alerts before sending a test",
                    status_code=409,
                )
            channel_state = self.store.get_apify_actor_alert_channel(
                workspace_id=workspace_id,
                channel=channel,
            )
            if channel_state is None:
                raise ApifyActorAlertError(
                    "notification_destination_required",
                    "configure the alert channel before sending a test",
                    status_code=409,
                )
            if channel == "webhook" and not self._bound_webhook_secret(
                settings
            ):
                raise ApifyActorAlertError(
                    "notification_destination_required",
                    "configure an alert webhook before sending a test",
                    status_code=409,
                )
            if (
                channel == "webhook"
                and not self._webhook_signing_binding_valid(settings)
            ):
                raise ApifyActorAlertError(
                    "invalid_webhook_signing_secret",
                    "configured alert webhook signing secret is unavailable",
                    status_code=409,
                )
            if channel == "email":
                if not settings.get("email_address"):
                    raise ApifyActorAlertError(
                        "notification_destination_required",
                        "configure an alert email address before sending a test",
                        status_code=409,
                    )
                if not self.email_transport.is_ready(
                    workspace_id=workspace_id
                ):
                    raise ApifyActorAlertError(
                        "notification_channel_unavailable",
                        "workspace email transport is not ready",
                        status_code=409,
                    )
            if channel == "telegram":
                if not self._bound_telegram_chat_id(channel_state):
                    raise ApifyActorAlertError(
                        "notification_destination_required",
                        "configure an alert Telegram Chat ID before sending a test",
                        status_code=409,
                    )
                if not self.telegram_transport.is_ready(
                    workspace_id=workspace_id
                ):
                    raise ApifyActorAlertError(
                        "notification_channel_unavailable",
                        "workspace Telegram transport is not ready",
                        status_code=409,
                    )
            if channel not in NOTIFICATION_CHANNELS:
                raise ApifyActorAlertError(
                    "notification_channel_unavailable",
                    "alert channel is unavailable",
                    status_code=409,
                )
            now = _utc_now()
            previous = _parse_time(
                channel_state.get("last_test_attempted_at")
            )
            if (
                previous is not None
                and (now - previous).total_seconds() < TEST_COOLDOWN_SECONDS
            ):
                raise ApifyActorAlertError(
                    "apify_actor_alert_test_rate_limited",
                    "wait before sending another Apify Actor alert test",
                    status_code=429,
                    retryable=True,
                )
            attempted_at = now.isoformat()
            conn.execute(
                """
                UPDATE apify_actor_alert_channels
                SET last_test_attempted_at = ?, updated_at = ?
                WHERE workspace_id = ? AND channel = ?
                """,
                (
                    attempted_at,
                    attempted_at,
                    workspace_id,
                    channel,
                ),
            )
            if str(settings.get("channel") or "") == channel:
                conn.execute(
                    """
                    UPDATE apify_actor_alert_settings
                    SET last_test_attempted_at = ?, updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (attempted_at, attempted_at, workspace_id),
                )
            channel_state["last_test_attempted_at"] = attempted_at
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        return {
            **settings,
            "channel": channel,
            "_channel_state": channel_state,
        }

    def _record_test_result(
        self,
        *,
        workspace_id: str,
        channel: str,
        generation: int,
        status: str,
        error_code: str | None = None,
    ) -> bool:
        if status not in {"sent", "failed"}:
            raise ValueError("alert test status is invalid")
        now = _iso()
        safe_error = (
            _safe_code(error_code, "notification_delivery_failed")
            if status == "failed"
            else None
        )
        conn = self.store.connect()
        try:
            conn.execute("BEGIN IMMEDIATE")
            updated = conn.execute(
                """
                UPDATE apify_actor_alert_channels
                SET last_test_status = ?,
                    last_test_generation = ?,
                    last_tested_at = ?,
                    last_test_error_code = ?,
                    updated_at = ?
                WHERE workspace_id = ? AND channel = ?
                  AND generation = ?
                """,
                (
                    status,
                    generation,
                    now,
                    safe_error,
                    now,
                    workspace_id,
                    channel,
                    generation,
                ),
            )
            settings = self._settings_row(workspace_id)
            if (
                updated.rowcount == 1
                and settings is not None
                and str(settings.get("channel") or "") == channel
            ):
                conn.execute(
                    """
                    UPDATE apify_actor_alert_settings
                    SET last_test_status = ?,
                        last_test_generation = ?,
                        last_tested_at = ?,
                        last_test_error_code = ?,
                        updated_at = ?
                    WHERE workspace_id = ?
                    """,
                    (
                        status,
                        generation,
                        now,
                        safe_error,
                        now,
                        workspace_id,
                    ),
                )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        return updated.rowcount == 1

    def _send_payload(
        self,
        settings: dict[str, Any],
        payload: dict[str, Any],
        *,
        test: bool,
    ) -> WebhookSendResult | TelegramSendResult | None:
        safe_payload = self._sanitize_delivery_payload(payload)
        channel = str(settings.get("channel") or "")
        if channel == "webhook":
            return self._send_webhook(
                settings,
                safe_payload,
                test=test,
            )
        if channel == "email":
            self._send_email(settings, safe_payload, test=test)
            return None
        if channel == "telegram":
            return self._send_telegram(
                settings,
                safe_payload,
                test=test,
            )
        raise ApifyActorAlertError(
            "notification_channel_unavailable",
            "alert channel is unavailable",
            status_code=409,
        )

    def _send_webhook(
        self,
        settings: dict[str, Any],
        payload: dict[str, Any],
        *,
        test: bool,
    ) -> WebhookSendResult:
        webhook_url = (
            str(settings.get("_resolved_destination") or "")
            or self._bound_webhook_secret(settings)
        )
        if not webhook_url:
            raise ApifyActorAlertError(
                "notification_destination_required",
                "alert webhook is not configured",
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
            raise ApifyActorAlertError(
                "invalid_webhook_signing_secret",
                "configured alert webhook signing secret is unavailable",
                status_code=409,
            )
        stored_provider = normalize_stored_webhook_provider(
            settings.get("webhook_provider")
        )
        effective_provider = resolve_webhook_provider(
            stored_provider,
            webhook_url,
        )
        event_name = (
            "inteliscope.apify_actor.test"
            if test
            else (
                "inteliscope.apify_actor.recovered"
                if payload.get("event_type") == "recovered"
                else "inteliscope.apify_actor.alert"
            )
        )
        data = {
            **payload,
            **({"test": True} if test else {}),
        }
        text = _bounded_text(
            _apify_alert_feishu_body(
                payload,
                test=test,
            )["content"]["text"],
            webhook_text_limit(effective_provider),
        )
        try:
            result = _run_coroutine(
                asyncio.wait_for(
                    send_notification_webhook(
                        provider=stored_provider,
                        webhook_url=webhook_url,
                        event=event_name,
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
            raise ApifyActorAlertError(
                exc.code,
                str(exc),
                status_code=400,
            ) from exc
        except WebhookDeliveryError as exc:
            raise ApifyActorAlertError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                outcome_unknown=exc.outcome_unknown,
            ) from exc
        except TimeoutError as exc:
            raise ApifyActorAlertError(
                "notification_webhook_outcome_unknown",
                "notification webhook outcome is unknown",
                status_code=502,
                outcome_unknown=True,
            ) from exc
        except Exception as exc:
            raise ApifyActorAlertError(
                "notification_webhook_outcome_unknown",
                "notification webhook outcome is unknown",
                status_code=502,
                outcome_unknown=True,
            ) from exc
        if not isinstance(result, WebhookSendResult):
            raise ApifyActorAlertError(
                "notification_webhook_outcome_unknown",
                "notification webhook outcome is unknown",
                status_code=502,
                outcome_unknown=True,
            )
        return result

    def _send_telegram(
        self,
        settings: dict[str, Any],
        payload: dict[str, Any],
        *,
        test: bool,
    ) -> TelegramSendResult:
        channel_state = settings.get("_channel_state")
        if not isinstance(channel_state, dict):
            channel_state = self.store.get_apify_actor_alert_channel(
                workspace_id=str(settings.get("workspace_id") or ""),
                channel="telegram",
            )
        chat_id = (
            str(settings.get("_resolved_destination") or "")
            or self._bound_telegram_chat_id(channel_state)
        )
        if not chat_id:
            raise ApifyActorAlertError(
                "notification_destination_required",
                "alert Telegram Chat ID is not configured",
                status_code=409,
            )
        text = _bounded_multiline_text(
            [
                (
                    "Inteliscope Apify 运行告警测试"
                    if test
                    else (
                        "Inteliscope Apify 恢复通知"
                        if payload.get("event_type") == "recovered"
                        else "Inteliscope Apify 运行告警"
                    )
                ),
                f"路由：{payload.get('route') or 'x/profile'}",
                f"事件：{payload.get('event_type') or 'unknown'}",
                f"状态：{payload.get('status') or 'unknown'}",
                (
                    f"Actor：{payload['actor_name']}"
                    if payload.get("actor_name")
                    else ""
                ),
                (
                    f"当前 Actor：{payload['active_actor_name']}"
                    if payload.get("active_actor_name")
                    else ""
                ),
                (
                    f"原因：{payload['reason_code']}"
                    if payload.get("reason_code")
                    else ""
                ),
            ],
            limit=4096,
        )
        try:
            return self.telegram_transport.send_message(
                workspace_id=str(settings.get("workspace_id") or ""),
                chat_id=chat_id,
                text=text,
            )
        except TelegramTransportServiceError as exc:
            raise ApifyActorAlertError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                outcome_unknown=exc.outcome_unknown,
            ) from exc

    def _send_email(
        self,
        settings: dict[str, Any],
        payload: dict[str, Any],
        *,
        test: bool,
    ) -> None:
        recipient = _normalize_email(
            settings.get("_resolved_destination")
            or settings.get("email_address")
        )
        if not recipient:
            raise ApifyActorAlertError(
                "notification_destination_required",
                "alert email address is not configured",
                status_code=409,
            )
        title = (
            "故障告警测试"
            if test
            else (
                "X 抓取路由已恢复"
                if payload.get("event_type") == "recovered"
                else "X 抓取路由状态变化"
            )
        )
        details = [
            f"路由：{payload.get('route') or 'x/profile'}",
            f"事件：{payload.get('event_type') or 'unknown'}",
            f"状态：{payload.get('status') or 'unknown'}",
        ]
        if payload.get("actor_name"):
            details.append(f"Actor：{payload['actor_name']}")
        if payload.get("active_actor_name"):
            details.append(f"当前 Actor：{payload['active_actor_name']}")
        if payload.get("reason_code"):
            details.append(f"原因：{payload['reason_code']}")
        try:
            self.email_transport.send_operational_alert(
                workspace_id=str(settings.get("workspace_id") or ""),
                recipient_email=recipient,
                payload={
                    **payload,
                    "kind": (
                        "operational_alert_test"
                        if test
                        else "operational_alert"
                    ),
                    "title": title,
                    "summary": "\n".join(details),
                },
            )
        except EmailTransportError as exc:
            raise ApifyActorAlertError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                outcome_unknown=exc.outcome_unknown,
            ) from exc

    def _require_admin(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
    ) -> dict[str, Any]:
        actor = self.store.get_user(actor_user_id)
        if (
            actor is None
            or not bool(actor.get("enabled"))
            or str(actor.get("workspace_id")) != str(workspace_id)
            or str(actor.get("role") or "") not in {"owner", "admin"}
        ):
            raise ApifyActorAlertError(
                "forbidden",
                "owner or admin role required",
                status_code=403,
            )
        return actor
