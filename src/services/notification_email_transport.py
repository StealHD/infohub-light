"""Workspace-owned SMTP transports for preferred-source notifications."""

from __future__ import annotations

import hashlib
import hmac
import html
import re
import smtplib
import ssl
from dataclasses import dataclass
from datetime import datetime, timezone
from email.message import EmailMessage
from email.utils import formataddr, parseaddr
from typing import Any, Callable
from urllib.parse import urlsplit

from ..storage.service_store import ServiceStore
from .secret_store import SecretStore


UNSET = object()
MAX_EMAIL_ITEMS = 20
TEST_COOLDOWN_SECONDS = 60
SUPPORTED_EMAIL_PROVIDERS = (
    "qq",
    "netease",
    "gmail",
    "resend",
    "amazon_ses",
)
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SES_REGION_RE = re.compile(
    r"^(?:[a-z]{2}|us-gov|us-iso|us-isob)(?:-[a-z0-9]+)+-\d$"
)


class EmailTransportError(RuntimeError):
    """A safe workspace email error suitable for an API error envelope."""

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


@dataclass(frozen=True)
class ResolvedEmailProvider:
    provider: str
    label: str
    smtp_host: str
    smtp_port: int
    smtp_username: str
    security: str = "ssl"


@dataclass(frozen=True)
class EmailProviderPreset:
    provider: str
    label: str
    credential_label: str
    sender_hint: str
    requires_region: bool = False
    requires_smtp_username: bool = False


class EmailProviderRegistry:
    """Resolve fixed SMTP endpoints without accepting browser-supplied hosts."""

    _PRESETS = {
        "qq": EmailProviderPreset(
            provider="qq",
            label="QQ 邮箱",
            credential_label="SMTP 授权码",
            sender_hint="填写完整 QQ 或 Foxmail 邮箱地址",
        ),
        "netease": EmailProviderPreset(
            provider="netease",
            label="网易邮箱",
            credential_label="SMTP 授权码",
            sender_hint="支持 163、126 与 yeah.net 邮箱地址",
        ),
        "gmail": EmailProviderPreset(
            provider="gmail",
            label="Gmail",
            credential_label="App Password",
            sender_hint="填写 Gmail 或 Google Workspace 完整邮箱地址",
        ),
        "resend": EmailProviderPreset(
            provider="resend",
            label="Resend",
            credential_label="API Key",
            sender_hint="发件地址所在域名须已在 Resend 验证",
        ),
        "amazon_ses": EmailProviderPreset(
            provider="amazon_ses",
            label="Amazon SES",
            credential_label="SES SMTP Password",
            sender_hint="使用已验证的 SES 发件地址",
            requires_region=True,
            requires_smtp_username=True,
        ),
    }

    @classmethod
    def list_public(cls) -> list[dict[str, Any]]:
        return [
            {
                "provider": preset.provider,
                "label": preset.label,
                "credential_label": preset.credential_label,
                "sender_hint": preset.sender_hint,
                "requires_region": preset.requires_region,
                "requires_smtp_username": preset.requires_smtp_username,
                "smtp_port": 465,
                "security": "ssl",
            }
            for preset in cls._PRESETS.values()
        ]

    @classmethod
    def resolve(
        cls,
        *,
        provider: Any,
        sender_email: Any,
        region: Any = None,
        smtp_username: Any = None,
    ) -> ResolvedEmailProvider:
        provider_name = str(provider or "").strip().lower()
        preset = cls._PRESETS.get(provider_name)
        if preset is None:
            raise EmailTransportError(
                "invalid_email_transport_provider",
                "email transport provider is not supported",
            )
        sender = normalize_email(
            sender_email,
            code="invalid_email_transport_sender",
        )
        domain = sender.rsplit("@", 1)[1].lower()
        if provider_name == "qq":
            if domain not in {"qq.com", "foxmail.com"}:
                raise EmailTransportError(
                    "invalid_email_transport_sender",
                    "QQ transport requires a QQ or Foxmail sender address",
                )
            host = "smtp.qq.com"
            username = sender
        elif provider_name == "netease":
            if domain not in {"163.com", "126.com", "yeah.net"}:
                raise EmailTransportError(
                    "invalid_email_transport_sender",
                    "NetEase transport requires a 163, 126, or yeah.net sender address",
                )
            host = "smtp.163.com"
            username = sender
        elif provider_name == "gmail":
            host = "smtp.gmail.com"
            username = sender
        elif provider_name == "resend":
            host = "smtp.resend.com"
            username = "resend"
        else:
            normalized_region = str(region or "").strip().lower()
            if not _SES_REGION_RE.fullmatch(normalized_region):
                raise EmailTransportError(
                    "invalid_email_transport_region",
                    "Amazon SES region is invalid",
                )
            username = str(smtp_username or "").strip()
            if (
                not username
                or len(username) > 320
                or any(character in username for character in "\r\n\x00")
            ):
                raise EmailTransportError(
                    "invalid_email_transport_username",
                    "Amazon SES SMTP username is required",
                )
            host = f"email-smtp.{normalized_region}.amazonaws.com"
        return ResolvedEmailProvider(
            provider=provider_name,
            label=preset.label,
            smtp_host=host,
            smtp_port=465,
            smtp_username=username,
        )


def normalize_email(value: Any, *, code: str) -> str:
    candidate = str(value or "").strip()
    if (
        not candidate
        or len(candidate) > 320
        or any(character in candidate for character in "\r\n\x00")
    ):
        raise EmailTransportError(code, "email address is invalid")
    display_name, address = parseaddr(candidate)
    if display_name or address != candidate or not _EMAIL_RE.fullmatch(address):
        raise EmailTransportError(code, "email address is invalid")
    local, domain = address.rsplit("@", 1)
    return f"{local}@{domain.lower()}"


def normalize_sender_name(value: Any) -> str:
    candidate = " ".join(str(value or "").split())
    if (
        not candidate
        or len(candidate) > 80
        or any(character in candidate for character in "\r\n\x00")
    ):
        raise EmailTransportError(
            "invalid_email_transport_sender_name",
            "email sender name is invalid",
        )
    return candidate


def _safe_article_url(value: Any) -> str:
    candidate = str(value or "").strip()
    if (
        not candidate
        or len(candidate) > 2_000
        or any(character in candidate for character in "\r\n\x00")
    ):
        return ""
    try:
        parsed = urlsplit(candidate)
    except ValueError:
        return ""
    if (
        parsed.scheme not in {"http", "https"}
        or not parsed.hostname
        or parsed.username is not None
        or parsed.password is not None
    ):
        return ""
    return candidate


def _bounded_header(value: Any, limit: int) -> str:
    candidate = " ".join(str(value or "").split())
    return candidate[:limit]


class WorkspaceEmailTransportService:
    """Manage and send one tested SMTP transport per workspace."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        data_dir: str,
        smtp_factory: Callable[..., Any] | None = None,
        ssl_context_factory: Callable[[], Any] | None = None,
    ) -> None:
        self.store = store
        self.secret_store = SecretStore(data_dir)
        self.smtp_factory = smtp_factory or smtplib.SMTP_SSL
        self.ssl_context_factory = ssl_context_factory or ssl.create_default_context

    @staticmethod
    def credential_env_name(*, workspace_id: str) -> str:
        digest = hashlib.sha256(
            str(workspace_id).encode("utf-8")
        ).hexdigest()[:24].upper()
        return f"HORIZON_WORKSPACE_EMAIL_{digest}"

    def _bound_credential(
        self,
        transport: dict[str, Any],
    ) -> str | None:
        workspace_id = str(transport.get("workspace_id") or "")
        env_name = str(transport.get("credential_env_name") or "")
        expected_env = self.credential_env_name(workspace_id=workspace_id)
        expected_digest = str(
            transport.get("credential_secret_digest") or ""
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
        actual_digest = hashlib.sha256(secret.encode("utf-8")).hexdigest()
        return (
            secret
            if hmac.compare_digest(actual_digest, expected_digest)
            else None
        )

    @staticmethod
    def _resolved(transport: dict[str, Any]) -> ResolvedEmailProvider:
        return EmailProviderRegistry.resolve(
            provider=transport.get("provider"),
            sender_email=transport.get("sender_email"),
            region=transport.get("region"),
            smtp_username=transport.get("smtp_username"),
        )

    def _can_enable(self, transport: dict[str, Any]) -> bool:
        try:
            self._resolved(transport)
        except EmailTransportError:
            return False
        return bool(
            self._bound_credential(transport)
            and transport.get("last_test_status") == "sent"
            and int(transport.get("last_test_generation") or -1)
            == int(transport.get("generation") or 0)
        )

    def is_ready(self, *, workspace_id: str) -> bool:
        transport = self.store.get_workspace_email_transport(
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
        transport = self.store.get_workspace_email_transport(
            workspace_id=workspace_id
        )
        base = {
            "schema_version": 1,
            "configured": False,
            "provider": None,
            "sender_email": None,
            "sender_name": "Inteliscope",
            "region": None,
            "smtp_username": None,
            "enabled": False,
            "credential_configured": False,
            "generation": 0,
            "last_test_status": None,
            "last_test_generation": None,
            "last_tested_at": None,
            "last_test_error_code": None,
            "can_enable": False,
            "ready": False,
            "connection": None,
            "providers": EmailProviderRegistry.list_public(),
            "updated_at": None,
        }
        if transport is None:
            return base
        credential_configured = bool(self._bound_credential(transport))
        can_enable = self._can_enable(transport)
        connection: dict[str, Any] | None = None
        try:
            resolved = self._resolved(transport)
            connection = {
                "smtp_host": resolved.smtp_host,
                "smtp_port": resolved.smtp_port,
                "security": resolved.security,
                "smtp_username": resolved.smtp_username,
            }
        except EmailTransportError:
            pass
        return {
            **base,
            "configured": True,
            "provider": transport.get("provider"),
            "sender_email": transport.get("sender_email"),
            "sender_name": transport.get("sender_name"),
            "region": transport.get("region"),
            "smtp_username": transport.get("smtp_username"),
            "enabled": bool(transport.get("enabled")),
            "credential_configured": credential_configured,
            "generation": int(transport.get("generation") or 0),
            "last_test_status": transport.get("last_test_status"),
            "last_test_generation": transport.get("last_test_generation"),
            "last_tested_at": transport.get("last_tested_at"),
            "last_test_error_code": transport.get(
                "last_test_error_code"
            ),
            "can_enable": can_enable,
            "ready": bool(transport.get("enabled") and can_enable),
            "connection": connection,
            "updated_at": transport.get("updated_at"),
        }

    def upsert(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        provider: Any = UNSET,
        sender_email: Any = UNSET,
        sender_name: Any = UNSET,
        credential: Any = UNSET,
        enabled: Any = UNSET,
        region: Any = UNSET,
        smtp_username: Any = UNSET,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "email transport update requires no active transaction"
            )
        expected_env = self.credential_env_name(
            workspace_id=workspace_id
        )
        previous_secret = self.secret_store.read().get(expected_env)
        secret_touched = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._require_admin(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
            )
            current = self.store.get_workspace_email_transport(
                workspace_id=workspace_id
            )
            target_provider = str(
                (current or {}).get("provider")
                if provider is UNSET
                else provider
            ).strip().lower()
            target_sender_email = normalize_email(
                (current or {}).get("sender_email")
                if sender_email is UNSET
                else sender_email,
                code="invalid_email_transport_sender",
            )
            target_sender_name = normalize_sender_name(
                (current or {}).get("sender_name") or "Inteliscope"
                if sender_name is UNSET
                else sender_name
            )
            target_region = (
                (current or {}).get("region")
                if region is UNSET
                else (str(region).strip().lower() if region is not None else None)
            )
            target_smtp_username = (
                (current or {}).get("smtp_username")
                if smtp_username is UNSET
                else (
                    str(smtp_username).strip()
                    if smtp_username is not None
                    else None
                )
            )
            resolved = EmailProviderRegistry.resolve(
                provider=target_provider,
                sender_email=target_sender_email,
                region=target_region,
                smtp_username=target_smtp_username,
            )
            if target_provider != "amazon_ses":
                target_region = None
                target_smtp_username = None

            material_fields = (
                "provider",
                "sender_email",
                "sender_name",
                "region",
                "smtp_username",
            )
            target_values = {
                "provider": target_provider,
                "sender_email": target_sender_email,
                "sender_name": target_sender_name,
                "region": target_region,
                "smtp_username": target_smtp_username,
            }
            material_changed = current is None or any(
                (current or {}).get(field) != target_values[field]
                for field in material_fields
            )
            account_changed = current is None or any(
                (current or {}).get(field) != target_values[field]
                for field in (
                    "provider",
                    "sender_email",
                    "region",
                    "smtp_username",
                )
            )
            credential_changed = credential is not UNSET
            current_env = str(
                (current or {}).get("credential_env_name") or ""
            )
            target_env: str | None = (
                expected_env if current_env == expected_env else None
            )
            target_digest: str | None = (
                str(
                    (current or {}).get("credential_secret_digest")
                    or ""
                )
                if target_env
                else None
            ) or None
            credential_value: str | None = None
            clear_credential = False
            if credential_changed:
                if credential is None or not str(credential).strip():
                    clear_credential = True
                else:
                    credential_value = SecretStore.validate_value(
                        str(credential)
                    )
            elif account_changed:
                clear_credential = True
            elif current is None or not self._bound_credential(current):
                target_env = None
                target_digest = None

            if clear_credential:
                target_env = None
                target_digest = None
                self.secret_store.delete(expected_env)
                secret_touched = True
            elif credential_value is not None:
                target_env = expected_env
                target_digest = hashlib.sha256(
                    credential_value.encode("utf-8")
                ).hexdigest()
                self.secret_store.set(expected_env, credential_value)
                secret_touched = True

            changed_generation = material_changed or credential_changed
            target_generation = int(
                (current or {}).get("generation") or 0
            )
            if changed_generation:
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
            if changed_generation:
                target_enabled = False
                last_test_status = None
                last_test_generation = None
                last_tested_at = None
                last_test_error_code = None

            future_transport = {
                "workspace_id": workspace_id,
                **target_values,
                "credential_env_name": target_env,
                "credential_secret_digest": target_digest,
                "generation": target_generation,
                "last_test_status": last_test_status,
                "last_test_generation": last_test_generation,
            }
            if target_enabled and not self._can_enable(future_transport):
                raise EmailTransportError(
                    "email_transport_test_required",
                    "test the current email transport before enabling it",
                    status_code=409,
                )

            self.store.upsert_workspace_email_transport(
                workspace_id=workspace_id,
                provider=resolved.provider,
                sender_email=target_sender_email,
                sender_name=target_sender_name,
                region=target_region,
                smtp_username=target_smtp_username,
                enabled=target_enabled,
                credential_env_name=target_env,
                credential_secret_digest=target_digest,
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
            disabled_now = bool(
                not target_enabled
                and (
                    enabled is not UNSET
                    or (current and current.get("enabled"))
                )
            )
            if changed_generation or disabled_now:
                self.store.invalidate_pending_email_deliveries(
                    workspace_id=workspace_id,
                    commit=False,
                )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            if secret_touched:
                if previous_secret is None:
                    self.secret_store.delete(expected_env)
                else:
                    self.secret_store.set(expected_env, previous_secret)
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
                "email transport deletion requires no active transaction"
            )
        expected_env = self.credential_env_name(
            workspace_id=workspace_id
        )
        previous_secret = self.secret_store.read().get(expected_env)
        secret_touched = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._require_admin(
                workspace_id=workspace_id,
                actor_user_id=actor_user_id,
            )
            current = self.store.get_workspace_email_transport(
                workspace_id=workspace_id
            )
            if current is None:
                self.secret_store.delete(expected_env)
                secret_touched = True
                conn.commit()
                return False
            self.secret_store.delete(expected_env)
            secret_touched = True
            self.store.invalidate_pending_email_deliveries(
                workspace_id=workspace_id,
                commit=False,
            )
            deleted = self.store.delete_workspace_email_transport(
                workspace_id=workspace_id,
                commit=False,
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            if secret_touched and previous_secret is not None:
                self.secret_store.set(expected_env, previous_secret)
            raise
        return deleted

    def send_test(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        recipient_email: Any,
    ) -> dict[str, Any]:
        recipient = normalize_email(
            recipient_email,
            code="invalid_notification_destination",
        )
        attempt = self.store.claim_workspace_email_transport_test_attempt(
            workspace_id=workspace_id,
            actor_user_id=actor_user_id,
            cooldown_seconds=TEST_COOLDOWN_SECONDS,
        )
        reason = attempt.get("reason")
        if reason == "forbidden":
            raise EmailTransportError(
                "forbidden",
                "owner or admin role required",
                status_code=403,
            )
        if reason == "not_configured":
            raise EmailTransportError(
                "email_transport_not_configured",
                "configure the email transport before testing it",
                status_code=409,
            )
        if reason == "rate_limited":
            raise EmailTransportError(
                "email_transport_test_rate_limited",
                "wait before sending another email transport test",
                status_code=429,
                retryable=True,
            )
        transport = attempt["transport"]
        generation = int(transport.get("generation") or 0)
        payload = {
            "kind": "test",
            "source_name": "Inteliscope",
            "title": "邮件发送服务测试",
            "summary": "这是一封测试邮件，用于验证工作区统一发件服务。",
            "url": "https://example.com/inteliscope-email-transport-test",
        }
        try:
            self._send(
                transport=transport,
                recipient=recipient,
                payload=payload,
                require_enabled=False,
            )
        except EmailTransportError as exc:
            self.store.record_workspace_email_transport_test(
                workspace_id=workspace_id,
                generation=generation,
                status="failed",
                error_code=exc.code,
            )
            raise
        recorded = self.store.record_workspace_email_transport_test(
            workspace_id=workspace_id,
            generation=generation,
            status="sent",
        )
        if recorded is None:
            raise EmailTransportError(
                "email_transport_changed",
                "email transport changed while the test was running",
                status_code=409,
                outcome_unknown=True,
            )
        return {
            "sent": True,
            "generation": generation,
        }

    def send_notification(
        self,
        *,
        workspace_id: str,
        recipient_email: Any,
        payload: dict[str, Any],
    ) -> None:
        transport = self.store.get_workspace_email_transport(
            workspace_id=workspace_id
        )
        if transport is None:
            raise EmailTransportError(
                "notification_channel_unavailable",
                "workspace email transport is not configured",
                status_code=409,
                outcome_unknown=True,
            )
        recipient = normalize_email(
            recipient_email,
            code="invalid_notification_destination",
        )
        self._send(
            transport=transport,
            recipient=recipient,
            payload=payload,
            require_enabled=True,
        )

    def _send(
        self,
        *,
        transport: dict[str, Any],
        recipient: str,
        payload: dict[str, Any],
        require_enabled: bool,
    ) -> None:
        if require_enabled and not (
            transport.get("enabled") and self._can_enable(transport)
        ):
            raise EmailTransportError(
                "notification_channel_unavailable",
                "workspace email transport is not ready",
                status_code=409,
                outcome_unknown=True,
            )
        credential = self._bound_credential(transport)
        if not credential:
            raise EmailTransportError(
                "email_transport_credential_unavailable",
                "email transport credential is not configured",
                status_code=409,
                outcome_unknown=require_enabled,
            )
        resolved = self._resolved(transport)
        message = self._build_message(
            transport=transport,
            recipient=recipient,
            payload=payload,
        )
        try:
            with self.smtp_factory(
                resolved.smtp_host,
                resolved.smtp_port,
                timeout=20,
                context=self.ssl_context_factory(),
            ) as server:
                server.login(resolved.smtp_username, credential)
                server.send_message(message)
        except smtplib.SMTPAuthenticationError as exc:
            raise EmailTransportError(
                "notification_email_authentication_failed",
                "email transport authentication was rejected",
                status_code=502,
            ) from exc
        except smtplib.SMTPRecipientsRefused as exc:
            raise EmailTransportError(
                "notification_email_recipient_rejected",
                "notification email recipient was rejected",
                status_code=502,
            ) from exc
        except (
            smtplib.SMTPDataError,
            smtplib.SMTPHeloError,
            smtplib.SMTPNotSupportedError,
            smtplib.SMTPSenderRefused,
        ) as exc:
            raise EmailTransportError(
                "notification_email_rejected",
                "notification email was rejected",
                status_code=502,
            ) from exc
        except Exception as exc:
            raise EmailTransportError(
                "notification_email_unavailable",
                "notification email could not be delivered",
                status_code=502,
                retryable=True,
                outcome_unknown=True,
            ) from exc

    @staticmethod
    def _build_message(
        *,
        transport: dict[str, Any],
        recipient: str,
        payload: dict[str, Any],
    ) -> EmailMessage:
        test_delivery = payload.get("kind") == "test"
        raw_items = (
            [payload]
            if test_delivery
            else list(payload.get("items") or [])[:MAX_EMAIL_ITEMS]
        )
        items = [item for item in raw_items if isinstance(item, dict)]
        if not items:
            raise EmailTransportError(
                "notification_delivery_failed",
                "notification payload did not contain any items",
                status_code=500,
            )
        message = EmailMessage()
        if test_delivery:
            item = items[0]
            source_name = _bounded_header(
                item.get("source_name") or "Inteliscope",
                80,
            )
            title = _bounded_header(
                item.get("title") or "推送测试",
                160,
            )
            message["Subject"] = f"[Inteliscope] {source_name}：{title}"
        else:
            message["Subject"] = (
                f"[Inteliscope] {len(items)} 条偏好来源新内容"
            )
        message["From"] = formataddr(
            (
                str(transport["sender_name"]),
                str(transport["sender_email"]),
            )
        )
        message["To"] = recipient
        text_sections: list[str] = []
        html_sections: list[str] = []
        for index, item in enumerate(items, start=1):
            source_name = str(item.get("source_name") or "Inteliscope")
            title = str(item.get("title") or "新内容")
            summary = str(item.get("summary") or "")
            url = _safe_article_url(item.get("url"))
            text_sections.append(
                "\n".join(
                    part
                    for part in (
                        f"{index}. [{source_name}] {title}",
                        summary,
                        url,
                    )
                    if part
                )
            )
            html_sections.append(
                "<li>"
                f"<h3>{html.escape(title)}</h3>"
                f"<p>{html.escape(source_name)}</p>"
                + (f"<p>{html.escape(summary)}</p>" if summary else "")
                + (
                    f'<p><a href="{html.escape(url, quote=True)}">打开原文</a></p>'
                    if url
                    else ""
                )
                + "</li>"
            )
        message.set_content("\n\n".join(text_sections))
        message.add_alternative(
            "<html><body><ol>"
            + "".join(html_sections)
            + "</ol></body></html>",
            subtype="html",
        )
        return message

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
            raise EmailTransportError(
                "forbidden",
                "owner or admin role required",
                status_code=403,
            )
        return actor
