"""Reusable private and workspace notification destinations."""

from __future__ import annotations

import asyncio
import hashlib
import hmac
import os
import re
import threading
import unicodedata
import uuid
from datetime import datetime, timezone
from email.utils import parseaddr
from typing import Any, Coroutine

from ..storage.service_store import (
    NOTIFICATION_CHANNEL_SET,
    NOTIFICATION_TARGET_SCOPE_SET,
    ServiceStore,
)
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
    WebhookConfigurationError,
    WebhookDeliveryError,
    WebhookSendResult,
    normalize_stored_webhook_provider,
    send_notification_webhook,
    validate_signing_secret,
    validate_webhook_url,
    webhook_provider_options,
    webhook_verification_mode,
)
from .secret_store import SecretStore
from .workspace_telegram_transport import (
    TelegramTransportServiceError,
    WorkspaceTelegramTransportService,
)


UNSET = object()
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SAFE_ERROR_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_TEST_COOLDOWN_SECONDS = 60


class NotificationTargetError(RuntimeError):
    """A bounded error suitable for the public API envelope."""

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
        self.code = (
            code
            if _SAFE_ERROR_RE.fullmatch(str(code or ""))
            else "notification_target_failed"
        )
        self.status_code = int(status_code)
        self.retryable = bool(retryable)
        self.outcome_unknown = bool(outcome_unknown)


def _run_coroutine(coro: Coroutine[Any, Any, Any]) -> Any:
    try:
        asyncio.get_running_loop()
    except RuntimeError:
        return asyncio.run(coro)
    result: dict[str, Any] = {}
    error: list[BaseException] = []

    def runner() -> None:
        try:
            result["value"] = asyncio.run(coro)
        except BaseException as exc:  # pragma: no cover - defensive boundary
            error.append(exc)

    thread = threading.Thread(target=runner, daemon=True)
    thread.start()
    thread.join()
    if error:
        raise error[0]
    return result.get("value")


def _normalize_name(value: Any) -> tuple[str, str]:
    name = " ".join(str(value or "").split())
    if not 1 <= len(name) <= 80:
        raise NotificationTargetError(
            "invalid_notification_target_name",
            "notification target name must contain 1 to 80 characters",
        )
    name_key = unicodedata.normalize("NFKC", name).casefold()
    if not name_key or len(name_key) > 160:
        raise NotificationTargetError(
            "invalid_notification_target_name",
            "notification target name is invalid",
        )
    return name, name_key


def _normalize_email(value: Any) -> str:
    candidate = str(value or "").strip()
    display_name, address = parseaddr(candidate)
    if (
        not candidate
        or "\r" in candidate
        or "\n" in candidate
        or display_name
        or address != candidate
        or not _EMAIL_RE.fullmatch(address)
    ):
        raise NotificationTargetError(
            "invalid_notification_destination",
            "notification email address is invalid",
        )
    return address


class NotificationTargetService:
    """Own target CRUD, authorization, readiness, tests, and secret binding."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        data_dir: str,
        email_transport: WorkspaceEmailTransportService,
        telegram_transport: WorkspaceTelegramTransportService,
    ) -> None:
        self.store = store
        self.secret_store = SecretStore(data_dir)
        self.email_transport = email_transport
        self.telegram_transport = telegram_transport

    @staticmethod
    def destination_env_name(target_id: str) -> str:
        suffix = hashlib.sha256(target_id.encode("utf-8")).hexdigest()[:24]
        return f"HORIZON_NOTIFICATION_TARGET_{suffix.upper()}_DESTINATION"

    @staticmethod
    def signing_env_name(target_id: str) -> str:
        suffix = hashlib.sha256(target_id.encode("utf-8")).hexdigest()[:24]
        return f"HORIZON_NOTIFICATION_TARGET_{suffix.upper()}_SIGNING_SECRET"

    def list_public_targets(
        self,
        *,
        workspace_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        actor = self._actor(
            workspace_id=workspace_id,
            user_id=user_id,
            writable=False,
        )
        targets = self.store.list_notification_targets(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        return {
            "schema_version": 1,
            "targets": [
                self.public_target(target, actor=actor)
                for target in targets
            ],
            "webhook_provider_options": webhook_provider_options(),
        }

    def list_public_services(
        self,
        *,
        workspace_id: str,
        user_id: str,
    ) -> dict[str, Any]:
        """Project notification targets as reusable admin-managed services."""

        actor = self._actor(
            workspace_id=workspace_id,
            user_id=user_id,
            writable=False,
        )
        targets = self.store.list_notification_targets(
            workspace_id=workspace_id,
            user_id=user_id,
        )
        is_admin = str(actor.get("role") or "") in {"owner", "admin"}
        services: list[dict[str, Any]] = []
        for target in targets:
            public = self.public_target(target, actor=actor)
            shared = str(target.get("scope") or "") == "shared"
            public.update(
                {
                    "legacy_private": not shared,
                    "can_validate": bool(
                        is_admin
                        and shared
                        and public.get("configured")
                        and self._transport_configured(target)
                    ),
                }
            )
            services.append(public)
        email = self.email_transport.get_public_settings(
            workspace_id=workspace_id
        )
        telegram = self.telegram_transport.get_public_settings(
            workspace_id=workspace_id
        )
        return {
            "schema_version": 1,
            "services": services,
            "channel_credentials": {
                "email": {
                    "configured": bool(
                        email.get("configured")
                        and email.get("credential_configured")
                    ),
                    "ready": bool(email.get("ready")),
                    "generation": int(email.get("generation") or 0),
                    "provider": email.get("provider"),
                    "sender_name": email.get("sender_name"),
                    "region": email.get("region"),
                    "sender_email_configured": bool(
                        email.get("sender_email")
                    ),
                    "smtp_username_configured": bool(
                        email.get("smtp_username")
                    ),
                    "providers": email.get("providers") or [],
                },
                "telegram": {
                    "configured": bool(
                        telegram.get("configured")
                        and telegram.get("token_configured")
                    ),
                    "ready": bool(telegram.get("ready")),
                    "generation": int(telegram.get("generation") or 0),
                },
                "webhook": {
                    "configured": True,
                    "ready": True,
                    "generation": 0,
                },
            },
            "webhook_provider_options": webhook_provider_options(),
            "can_manage": is_admin,
        }

    def public_target(
        self,
        target: dict[str, Any],
        *,
        actor: dict[str, Any],
    ) -> dict[str, Any]:
        configured = self._destination(target) is not None
        tested = (
            target.get("last_test_status") == "sent"
            and int(target.get("last_test_config_generation") or 0)
            == int(target.get("config_generation") or 0)
        )
        transport_ready = self._transport_ready(target)
        archived = target.get("archived_at") is not None
        available = bool(
            not archived
            and target.get("enabled")
            and configured
            and tested
            and transport_ready
        )
        can_edit = bool(
            not archived
            and str(actor.get("role") or "") != "viewer"
            and (
                (
                    target.get("scope") == "private"
                    and str(target.get("owner_user_id"))
                    == str(actor.get("id"))
                )
                or (
                    target.get("scope") == "shared"
                    and str(actor.get("role") or "") in {"owner", "admin"}
                )
            )
        )
        usage = self.store.notification_target_usage(
            workspace_id=str(target["workspace_id"]),
            target_id=str(target["id"]),
        )
        test_status = target.get("last_test_status")
        if (
            test_status == "failed"
            and str(target.get("last_test_error_code") or "").endswith(
                ("outcome_unknown", "response_invalid")
            )
        ):
            test_status = "unknown"
        public: dict[str, Any] = {
            "id": str(target["id"]),
            "name": str(target["name"]),
            "scope": str(target["scope"]),
            "channel": str(target["channel"]),
            "configured": configured,
            "enabled": bool(target.get("enabled")),
            "available": available,
            "transport_ready": transport_ready,
            "config_generation": int(
                target.get("config_generation") or 1
            ),
            "activation_generation": int(
                target.get("activation_generation") or 0
            ),
            "enabled_at": target.get("enabled_at"),
            "last_test_status": test_status,
            "last_tested_at": target.get("last_tested_at"),
            "last_test_error_code": target.get("last_test_error_code"),
            "can_edit": can_edit,
            "can_test": bool(can_edit and configured and transport_ready),
            "can_enable": bool(can_edit and configured and tested),
            "usage": usage,
            "updated_at": target.get("updated_at"),
        }
        if target.get("channel") == "webhook":
            provider = normalize_stored_webhook_provider(
                target.get("webhook_provider")
            )
            public.update(
                {
                    "webhook_provider": provider,
                    "webhook_signing_secret_configured": bool(
                        self._signing_secret(target)
                    ),
                    "webhook_verification_mode": webhook_verification_mode(
                        provider
                    ),
                }
            )
        return public

    def create(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        name: Any,
        scope: Any,
        channel: Any,
        email_address: Any = UNSET,
        webhook_url: Any = UNSET,
        webhook_provider: Any = UNSET,
        webhook_signing_secret: Any = UNSET,
        telegram_chat_id: Any = UNSET,
    ) -> dict[str, Any]:
        actor = self._actor(
            workspace_id=workspace_id,
            user_id=actor_user_id,
            writable=True,
        )
        target_scope = str(scope or "").strip().lower()
        target_channel = str(channel or "").strip().lower()
        if target_scope not in NOTIFICATION_TARGET_SCOPE_SET:
            raise NotificationTargetError(
                "invalid_notification_target_scope",
                "notification target scope must be private or shared",
            )
        if (
            target_scope == "shared"
            and str(actor.get("role") or "") not in {"owner", "admin"}
        ):
            raise NotificationTargetError(
                "forbidden",
                "shared notification targets require owner or admin",
                status_code=403,
            )
        if target_channel not in NOTIFICATION_CHANNEL_SET:
            raise NotificationTargetError(
                "invalid_notification_channel",
                "notification target channel is invalid",
            )
        self._validate_configuration_fields(
            channel=target_channel,
            email_address=email_address,
            webhook_url=webhook_url,
            webhook_provider=webhook_provider,
            webhook_signing_secret=webhook_signing_secret,
            telegram_chat_id=telegram_chat_id,
        )
        target_name, name_key = _normalize_name(name)
        target_id = f"ntg_{uuid.uuid4().hex}"
        destination, provider, signing = self._validated_configuration(
            channel=target_channel,
            email_address=email_address,
            webhook_url=webhook_url,
            webhook_provider=webhook_provider,
            webhook_signing_secret=webhook_signing_secret,
            telegram_chat_id=telegram_chat_id,
            require_destination=True,
        )
        destination_env = self.destination_env_name(target_id)
        signing_env = self.signing_env_name(target_id)
        secret_updates = {
            destination_env: destination,
            signing_env: signing,
        }
        previous = self.secret_store.read()
        secrets_written = False
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "notification target creation requires no active transaction"
            )
        try:
            conn.execute("BEGIN IMMEDIATE")
            self._actor(
                workspace_id=workspace_id,
                user_id=actor_user_id,
                writable=True,
            )
            self._assert_name_available(
                workspace_id=workspace_id,
                scope=target_scope,
                owner_user_id=(
                    actor_user_id if target_scope == "private" else None
                ),
                name_key=name_key,
            )
            self.secret_store.replace_many(secret_updates)
            self._sync_environment(secret_updates)
            secrets_written = True
            self.store.create_notification_target(
                target_id=target_id,
                workspace_id=workspace_id,
                scope=target_scope,
                owner_user_id=(
                    actor_user_id if target_scope == "private" else None
                ),
                name=target_name,
                name_key=name_key,
                channel=target_channel,
                destination_env_name=destination_env,
                destination_secret_digest=self._digest(destination),
                webhook_provider=provider,
                webhook_signing_env_name=signing_env if signing else None,
                webhook_signing_secret_digest=(
                    self._digest(signing) if signing else None
                ),
                commit=False,
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            if secrets_written:
                rollback = {
                    key: previous.get(key)
                    for key in secret_updates
                }
                self.secret_store.replace_many(rollback)
                self._sync_environment(rollback)
            raise
        target = self.store.get_notification_target(
            workspace_id=workspace_id,
            target_id=target_id,
        )
        if target is None:
            raise RuntimeError("notification target disappeared after create")
        return self.public_target(target, actor=actor)

    def update(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        target_id: str,
        name: Any = UNSET,
        enabled: Any = UNSET,
        email_address: Any = UNSET,
        webhook_url: Any = UNSET,
        webhook_provider: Any = UNSET,
        webhook_signing_secret: Any = UNSET,
        telegram_chat_id: Any = UNSET,
    ) -> dict[str, Any]:
        actor = self._actor(
            workspace_id=workspace_id,
            user_id=actor_user_id,
            writable=True,
        )
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "notification target update requires no active transaction"
            )
        previous_secrets: dict[str, str | None] = {}
        secrets_written = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            target = self._editable_target(
                workspace_id=workspace_id,
                actor=actor,
                target_id=target_id,
            )
            target_name = str(target["name"])
            name_key = str(target["name_key"])
            if name is not UNSET:
                target_name, name_key = _normalize_name(name)
                self._assert_name_available(
                    workspace_id=workspace_id,
                    scope=str(target["scope"]),
                    owner_user_id=target.get("owner_user_id"),
                    name_key=name_key,
                    exclude_target_id=target_id,
                )
            config_fields_touched = any(
                value is not UNSET
                for value in (
                    email_address,
                    webhook_url,
                    webhook_provider,
                    webhook_signing_secret,
                    telegram_chat_id,
                )
            )
            self._validate_configuration_fields(
                channel=str(target["channel"]),
                email_address=email_address,
                webhook_url=webhook_url,
                webhook_provider=webhook_provider,
                webhook_signing_secret=webhook_signing_secret,
                telegram_chat_id=telegram_chat_id,
            )
            destination = self._destination(target)
            signing = self._signing_secret(target)
            provider = target.get("webhook_provider")
            destination_env = str(
                target.get("destination_env_name")
                or self.destination_env_name(target_id)
            )
            signing_env = str(
                target.get("webhook_signing_env_name")
                or self.signing_env_name(target_id)
            )
            if config_fields_touched:
                destination, provider, signing = (
                    self._validated_configuration(
                        channel=str(target["channel"]),
                        email_address=(
                            email_address
                            if email_address is not UNSET
                            else destination
                        ),
                        webhook_url=(
                            webhook_url
                            if webhook_url is not UNSET
                            else destination
                        ),
                        webhook_provider=(
                            webhook_provider
                            if webhook_provider is not UNSET
                            else provider
                        ),
                        webhook_signing_secret=(
                            webhook_signing_secret
                            if webhook_signing_secret is not UNSET
                            else signing
                        ),
                        telegram_chat_id=(
                            telegram_chat_id
                            if telegram_chat_id is not UNSET
                            else destination
                        ),
                        require_destination=True,
                    )
                )
                destination_env = self.destination_env_name(target_id)
                signing_env = self.signing_env_name(target_id)
                secret_updates = {
                    destination_env: destination,
                    signing_env: signing,
                }
                current_secrets = self.secret_store.read()
                previous_secrets = {
                    key: current_secrets.get(key)
                    for key in secret_updates
                }
                old_destination_env = str(
                    target.get("destination_env_name") or ""
                )
                old_signing_env = str(
                    target.get("webhook_signing_env_name") or ""
                )
                if old_destination_env and old_destination_env != destination_env:
                    if not self._secret_is_referenced_elsewhere(
                        old_destination_env,
                        target_id=target_id,
                    ):
                        secret_updates[old_destination_env] = None
                        previous_secrets[old_destination_env] = (
                            current_secrets.get(old_destination_env)
                        )
                if old_signing_env and old_signing_env != signing_env:
                    if not self._secret_is_referenced_elsewhere(
                        old_signing_env,
                        target_id=target_id,
                    ):
                        secret_updates[old_signing_env] = None
                        previous_secrets[old_signing_env] = (
                            current_secrets.get(old_signing_env)
                        )
                self.secret_store.replace_many(secret_updates)
                self._sync_environment(secret_updates)
                secrets_written = True
            now = datetime.now(timezone.utc).isoformat()
            target_enabled = bool(target.get("enabled"))
            target_enabled_at = target.get("enabled_at")
            config_generation = int(target["config_generation"])
            activation_generation = int(
                target["activation_generation"]
            )
            last_test_status = target.get("last_test_status")
            last_test_generation = target.get(
                "last_test_config_generation"
            )
            last_tested_at = target.get("last_tested_at")
            last_test_error_code = target.get("last_test_error_code")
            if config_fields_touched:
                config_generation += 1
                activation_generation += 1
                target_enabled = False
                target_enabled_at = None
                last_test_status = None
                last_test_generation = None
                last_tested_at = None
                last_test_error_code = None
                self.store.fail_pending_notification_target_deliveries(
                    workspace_id=workspace_id,
                    target_id=target_id,
                    error_code="notification_target_changed",
                    commit=False,
                )
            if enabled is not UNSET:
                requested_enabled = bool(enabled)
                if requested_enabled != target_enabled:
                    if requested_enabled:
                        if (
                            last_test_status != "sent"
                            or int(last_test_generation or 0)
                            != config_generation
                            or not self._transport_ready(
                                {
                                    **target,
                                    "channel": target["channel"],
                                }
                            )
                        ):
                            raise NotificationTargetError(
                                "notification_target_test_required",
                                "test the current notification target before enabling it",
                                status_code=409,
                            )
                        target_enabled_at = now
                    else:
                        target_enabled_at = None
                    target_enabled = requested_enabled
                    activation_generation += 1
                    self.store.fail_pending_notification_target_deliveries(
                        workspace_id=workspace_id,
                        target_id=target_id,
                        error_code="notification_target_changed",
                        commit=False,
                    )
            conn.execute(
                """
                UPDATE notification_targets
                SET name = ?, name_key = ?, enabled = ?, enabled_at = ?,
                    config_generation = ?, activation_generation = ?,
                    destination_env_name = ?,
                    destination_secret_digest = ?,
                    secret_binding_kind = ?,
                    webhook_provider = ?, webhook_signing_env_name = ?,
                    webhook_signing_secret_digest = ?,
                    last_test_status = ?,
                    last_test_config_generation = ?,
                    last_test_attempted_at = ?,
                    last_tested_at = ?, last_test_error_code = ?,
                    updated_at = ?
                WHERE workspace_id = ? AND id = ? AND archived_at IS NULL
                """,
                (
                    target_name,
                    name_key,
                    1 if target_enabled else 0,
                    target_enabled_at,
                    config_generation,
                    activation_generation,
                    (
                        destination_env
                        if config_fields_touched
                        else target.get("destination_env_name")
                    ),
                    (
                        self._digest(destination)
                        if config_fields_touched
                        else target.get("destination_secret_digest")
                    ),
                    (
                        "target_v16"
                        if config_fields_touched
                        else target.get("secret_binding_kind")
                    ),
                    provider if target["channel"] == "webhook" else None,
                    (
                        signing_env
                        if config_fields_touched and signing
                        else (
                            target.get("webhook_signing_env_name")
                            if not config_fields_touched
                            else None
                        )
                    ),
                    (
                        self._digest(signing)
                        if config_fields_touched and signing
                        else (
                            target.get("webhook_signing_secret_digest")
                            if not config_fields_touched
                            else None
                        )
                    ),
                    last_test_status,
                    last_test_generation,
                    (
                        None
                        if config_fields_touched
                        else target.get("last_test_attempted_at")
                    ),
                    last_tested_at,
                    last_test_error_code,
                    now,
                    workspace_id,
                    target_id,
                ),
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            if secrets_written:
                self.secret_store.replace_many(previous_secrets)
                self._sync_environment(previous_secrets)
            raise
        updated = self.store.get_notification_target(
            workspace_id=workspace_id,
            target_id=target_id,
        )
        if updated is None:
            raise LookupError("notification target was not found after update")
        return self.public_target(updated, actor=actor)

    def archive(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        target_id: str,
    ) -> bool:
        actor = self._actor(
            workspace_id=workspace_id,
            user_id=actor_user_id,
            writable=True,
        )
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "notification target archive requires no active transaction"
            )
        previous_secrets: dict[str, str | None] = {}
        secrets_written = False
        try:
            conn.execute("BEGIN IMMEDIATE")
            target = self._editable_target(
                workspace_id=workspace_id,
                actor=actor,
                target_id=target_id,
            )
            usage = self.store.notification_target_usage(
                workspace_id=workspace_id,
                target_id=target_id,
            )
            if any(usage.values()):
                raise NotificationTargetError(
                    "notification_target_in_use",
                    "remove notification target bindings before archiving it",
                    status_code=409,
                )
            secret_updates = {
                str(value): None
                for value in (
                    target.get("destination_env_name"),
                    target.get("webhook_signing_env_name"),
                )
                if value
                and not self._secret_is_referenced_elsewhere(
                    str(value),
                    target_id=target_id,
                )
            }
            current_secrets = self.secret_store.read()
            previous_secrets = {
                key: current_secrets.get(key)
                for key in secret_updates
            }
            if secret_updates:
                self.secret_store.replace_many(secret_updates)
                self._sync_environment(secret_updates)
                secrets_written = True
            now = datetime.now(timezone.utc).isoformat()
            updated = conn.execute(
                """
                UPDATE notification_targets
                SET enabled = 0, enabled_at = NULL,
                    activation_generation = activation_generation + 1,
                    destination_env_name = NULL,
                    destination_secret_digest = NULL,
                    webhook_signing_env_name = NULL,
                    webhook_signing_secret_digest = NULL,
                    archived_at = ?, updated_at = ?
                WHERE workspace_id = ? AND id = ? AND archived_at IS NULL
                """,
                (now, now, workspace_id, target_id),
            )
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            if secrets_written:
                self.secret_store.replace_many(previous_secrets)
                self._sync_environment(previous_secrets)
            raise
        return updated.rowcount == 1

    def send_test(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        target_id: str,
    ) -> dict[str, Any]:
        actor = self._actor(
            workspace_id=workspace_id,
            user_id=actor_user_id,
            writable=True,
        )
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "notification target test requires no active transaction"
            )
        try:
            conn.execute("BEGIN IMMEDIATE")
            target = self._editable_target(
                workspace_id=workspace_id,
                actor=actor,
                target_id=target_id,
            )
            if self._destination(target) is None:
                raise NotificationTargetError(
                    "notification_destination_required",
                    "configure the notification target before testing",
                    status_code=409,
                )
            if not self._transport_ready(target):
                raise NotificationTargetError(
                    "notification_channel_unavailable",
                    "notification transport is unavailable",
                    status_code=409,
                )
            previous_attempt = target.get("last_test_attempted_at")
            if previous_attempt:
                try:
                    previous_time = datetime.fromisoformat(
                        str(previous_attempt).replace("Z", "+00:00")
                    )
                except ValueError:
                    previous_time = None
                if previous_time is not None and previous_time.tzinfo is not None:
                    elapsed = (
                        datetime.now(timezone.utc)
                        - previous_time.astimezone(timezone.utc)
                    ).total_seconds()
                    if elapsed < _TEST_COOLDOWN_SECONDS:
                        raise NotificationTargetError(
                            "notification_target_test_rate_limited",
                            "wait before testing this notification target again",
                            status_code=429,
                            retryable=True,
                        )
            attempted_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE notification_targets
                SET last_test_attempted_at = ?, updated_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (attempted_at, attempted_at, workspace_id, target_id),
            )
            generation = int(target["config_generation"])
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        try:
            result = self._send_test_payload(target)
        except NotificationTargetError as exc:
            self._record_test(
                workspace_id=workspace_id,
                target_id=target_id,
                generation=generation,
                status="unknown" if exc.outcome_unknown else "failed",
                error_code=exc.code,
            )
            raise
        except Exception as exc:
            self._record_test(
                workspace_id=workspace_id,
                target_id=target_id,
                generation=generation,
                status="unknown",
                error_code="notification_delivery_outcome_unknown",
            )
            raise NotificationTargetError(
                "notification_target_test_outcome_unknown",
                "notification target test outcome is unknown; do not retry",
                status_code=502,
                outcome_unknown=True,
            ) from exc
        if not self._record_test(
            workspace_id=workspace_id,
            target_id=target_id,
            generation=generation,
            status="sent",
            error_code=None,
        ):
            raise NotificationTargetError(
                "notification_target_test_outcome_unknown",
                "notification target changed while the test was running",
                status_code=409,
                outcome_unknown=True,
            )
        response: dict[str, Any] = {
            "sent": True,
            "target_id": target_id,
            "channel": str(target["channel"]),
        }
        if isinstance(result, WebhookSendResult):
            response.update(
                {
                    "provider": result.provider,
                    "verification": result.verification,
                }
            )
        elif isinstance(result, TelegramSendResult):
            response["verification"] = result.verification
        return response

    def send_test_and_enable(
        self,
        *,
        workspace_id: str,
        actor_user_id: str,
        target_id: str,
    ) -> dict[str, Any]:
        """Send one service test, then atomically validate and enable it."""

        actor = self._actor(
            workspace_id=workspace_id,
            user_id=actor_user_id,
            writable=True,
        )
        if str(actor.get("role") or "") not in {"owner", "admin"}:
            raise NotificationTargetError(
                "forbidden",
                "notification services require owner or admin",
                status_code=403,
            )
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "notification service test requires no active transaction"
            )
        try:
            conn.execute("BEGIN IMMEDIATE")
            target = self._editable_target(
                workspace_id=workspace_id,
                actor=actor,
                target_id=target_id,
            )
            if str(target.get("scope") or "") != "shared":
                raise NotificationTargetError(
                    "notification_service_legacy_private",
                    "legacy private targets cannot be validated as shared services",
                    status_code=409,
                )
            if self._destination(target) is None:
                raise NotificationTargetError(
                    "notification_destination_required",
                    "configure the notification service before testing",
                    status_code=409,
                )
            if not self._transport_configured(target):
                raise NotificationTargetError(
                    "notification_channel_unavailable",
                    "configure the shared channel credential before testing",
                    status_code=409,
                )
            previous_attempt = target.get("last_test_attempted_at")
            if previous_attempt:
                try:
                    previous_time = datetime.fromisoformat(
                        str(previous_attempt).replace("Z", "+00:00")
                    )
                except ValueError:
                    previous_time = None
                if previous_time is not None and previous_time.tzinfo is not None:
                    elapsed = (
                        datetime.now(timezone.utc)
                        - previous_time.astimezone(timezone.utc)
                    ).total_seconds()
                    if elapsed < _TEST_COOLDOWN_SECONDS:
                        raise NotificationTargetError(
                            "notification_target_test_rate_limited",
                            "wait before testing this notification service again",
                            status_code=429,
                            retryable=True,
                        )
            attempted_at = datetime.now(timezone.utc).isoformat()
            conn.execute(
                """
                UPDATE notification_targets
                SET last_test_attempted_at = ?, updated_at = ?
                WHERE workspace_id = ? AND id = ?
                """,
                (attempted_at, attempted_at, workspace_id, target_id),
            )
            generation = int(target["config_generation"])
            conn.commit()
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise

        transport_generation: int | None = None
        try:
            destination = self._destination(target)
            if destination is None:
                raise NotificationTargetError(
                    "notification_destination_required",
                    "notification service destination is unavailable",
                    status_code=409,
                )
            channel = str(target["channel"])
            if channel == "email":
                try:
                    transport_generation = (
                        self.email_transport.send_service_test(
                            workspace_id=workspace_id,
                            recipient_email=destination,
                        )
                    )
                except EmailTransportError as exc:
                    raise NotificationTargetError(
                        exc.code,
                        str(exc),
                        status_code=exc.status_code,
                        retryable=exc.retryable,
                        outcome_unknown=exc.outcome_unknown,
                    ) from exc
                result: WebhookSendResult | TelegramSendResult | None = None
            elif channel == "telegram":
                transport = self.store.get_workspace_telegram_transport(
                    workspace_id=workspace_id
                )
                if transport is None:
                    raise NotificationTargetError(
                        "telegram_transport_not_configured",
                        "configure the Telegram Bot before testing",
                        status_code=409,
                    )
                transport_generation = int(
                    transport.get("generation") or 0
                )
                try:
                    result = self.telegram_transport.send_message(
                        workspace_id=workspace_id,
                        chat_id=destination,
                        text=(
                            "Inteliscope 通知服务测试\n"
                            "这是一条模拟消息，用于验证当前通知服务。"
                        ),
                        require_enabled=False,
                        transport=transport,
                    )
                except TelegramTransportServiceError as exc:
                    raise NotificationTargetError(
                        exc.code,
                        str(exc),
                        status_code=exc.status_code,
                        retryable=exc.retryable,
                        outcome_unknown=exc.outcome_unknown,
                    ) from exc
            else:
                result = self._send_test_payload(target)
        except NotificationTargetError as exc:
            self._record_test(
                workspace_id=workspace_id,
                target_id=target_id,
                generation=generation,
                status="unknown" if exc.outcome_unknown else "failed",
                error_code=exc.code,
            )
            raise
        except Exception as exc:
            self._record_test(
                workspace_id=workspace_id,
                target_id=target_id,
                generation=generation,
                status="unknown",
                error_code="notification_delivery_outcome_unknown",
            )
            raise NotificationTargetError(
                "notification_target_test_outcome_unknown",
                "notification service test outcome is unknown; do not retry",
                status_code=502,
                outcome_unknown=True,
            ) from exc

        activated = self.store.activate_notification_service_after_test(
            workspace_id=workspace_id,
            target_id=target_id,
            target_generation=generation,
            channel=str(target["channel"]),
            transport_generation=transport_generation,
        )
        if activated is None:
            self._record_test(
                workspace_id=workspace_id,
                target_id=target_id,
                generation=generation,
                status="unknown",
                error_code="notification_target_test_outcome_unknown",
            )
            raise NotificationTargetError(
                "notification_target_test_outcome_unknown",
                "notification service changed while the test was running",
                status_code=409,
                outcome_unknown=True,
            )
        response: dict[str, Any] = {
            "sent": True,
            "enabled": True,
            "target_id": target_id,
            "channel": str(target["channel"]),
        }
        if isinstance(result, WebhookSendResult):
            response.update(
                {
                    "provider": result.provider,
                    "verification": result.verification,
                }
            )
        elif isinstance(result, TelegramSendResult):
            response["verification"] = result.verification
        return response

    def delivery_settings(
        self,
        target: dict[str, Any],
        *,
        user_id: str | None = None,
    ) -> dict[str, Any]:
        destination = self._destination(target)
        if destination is None:
            raise NotificationTargetError(
                "notification_destination_required",
                "notification target destination is unavailable",
                status_code=409,
            )
        signing = self._signing_secret(target)
        if target.get("webhook_signing_env_name") and signing is None:
            raise NotificationTargetError(
                "invalid_webhook_signing_secret",
                "notification target signing secret is unavailable",
                status_code=409,
            )
        return {
            "workspace_id": str(target["workspace_id"]),
            "user_id": user_id,
            "channel": str(target["channel"]),
            "email_address": (
                destination if target["channel"] == "email" else None
            ),
            "webhook_provider": target.get("webhook_provider"),
            "_resolved_destination": destination,
            "_resolved_signing_secret": signing,
            "_notification_target": target,
            "_channel_state": target,
        }

    def target_is_available(self, target: dict[str, Any]) -> bool:
        return bool(
            target.get("archived_at") is None
            and target.get("enabled")
            and target.get("enabled_at")
            and self._destination(target) is not None
            and target.get("last_test_status") == "sent"
            and int(target.get("last_test_config_generation") or 0)
            == int(target.get("config_generation") or 0)
            and self._transport_ready(target)
        )

    def _send_test_payload(
        self,
        target: dict[str, Any],
    ) -> WebhookSendResult | TelegramSendResult | None:
        destination = self._destination(target)
        if destination is None:
            raise NotificationTargetError(
                "notification_destination_required",
                "notification target destination is unavailable",
                status_code=409,
            )
        channel = str(target["channel"])
        if channel == "email":
            try:
                self.email_transport.send_notification(
                    workspace_id=str(target["workspace_id"]),
                    recipient_email=destination,
                    payload={
                        "schema_version": 1,
                        "kind": "test",
                        "article_id": "notification-target-test",
                        "source_name": "Inteliscope",
                        "title": "Inteliscope 通知目标测试",
                        "summary": "这是一条模拟消息，用于验证当前通知目标。",
                        "published_at": datetime.now(timezone.utc).isoformat(),
                        "url": "https://example.com/inteliscope-notification-target-test",
                    },
                )
            except EmailTransportError as exc:
                raise NotificationTargetError(
                    exc.code,
                    str(exc),
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                    outcome_unknown=exc.outcome_unknown,
                ) from exc
            return None
        if channel == "telegram":
            try:
                return self.telegram_transport.send_message(
                    workspace_id=str(target["workspace_id"]),
                    chat_id=destination,
                    text=(
                        "Inteliscope 通知目标测试\n"
                        "这是一条模拟消息，用于验证当前通知目标。"
                    ),
                )
            except TelegramTransportServiceError as exc:
                raise NotificationTargetError(
                    exc.code,
                    str(exc),
                    status_code=exc.status_code,
                    retryable=exc.retryable,
                    outcome_unknown=exc.outcome_unknown,
                ) from exc
        provider = normalize_stored_webhook_provider(
            target.get("webhook_provider")
        )
        signing = self._signing_secret(target)
        try:
            result = _run_coroutine(
                asyncio.wait_for(
                    send_notification_webhook(
                        provider=provider,
                        webhook_url=destination,
                        event="inteliscope.notification_target.test",
                        data={
                            "schema_version": 1,
                            "test": True,
                            "message": "Inteliscope notification target test",
                        },
                        text="Inteliscope 通知目标测试：这是一条模拟消息。",
                        signing_secret=signing,
                        timeout=5.0,
                        post=post_public_http,
                    ),
                    timeout=6.0,
                )
            )
        except WebhookConfigurationError as exc:
            raise NotificationTargetError(
                exc.code,
                str(exc),
                status_code=400,
            ) from exc
        except WebhookDeliveryError as exc:
            raise NotificationTargetError(
                exc.code,
                str(exc),
                status_code=exc.status_code,
                retryable=exc.retryable,
                outcome_unknown=exc.outcome_unknown,
            ) from exc
        except TimeoutError as exc:
            raise NotificationTargetError(
                "notification_webhook_outcome_unknown",
                "notification webhook outcome is unknown",
                status_code=502,
                outcome_unknown=True,
            ) from exc
        if not isinstance(result, WebhookSendResult):
            raise NotificationTargetError(
                "notification_webhook_outcome_unknown",
                "notification webhook outcome is unknown",
                status_code=502,
                outcome_unknown=True,
            )
        return result

    def _record_test(
        self,
        *,
        workspace_id: str,
        target_id: str,
        generation: int,
        status: str,
        error_code: str | None,
    ) -> bool:
        now = datetime.now(timezone.utc).isoformat()
        updated = self.store.connect().execute(
            """
            UPDATE notification_targets
            SET last_test_status = ?,
                last_test_config_generation = ?,
                last_tested_at = ?,
                last_test_error_code = ?,
                updated_at = ?
            WHERE workspace_id = ? AND id = ?
              AND config_generation = ? AND archived_at IS NULL
            """,
            (
                status,
                int(generation),
                now,
                error_code if status != "sent" else None,
                now,
                workspace_id,
                target_id,
                int(generation),
            ),
        )
        self.store.connect().commit()
        return updated.rowcount == 1

    def _validated_configuration(
        self,
        *,
        channel: str,
        email_address: Any,
        webhook_url: Any,
        webhook_provider: Any,
        webhook_signing_secret: Any,
        telegram_chat_id: Any,
        require_destination: bool,
    ) -> tuple[str, str | None, str | None]:
        destination: str | None = None
        provider: str | None = None
        signing: str | None = None
        if channel == "email":
            if email_address is not UNSET:
                destination = _normalize_email(email_address)
        elif channel == "telegram":
            if telegram_chat_id is not UNSET:
                try:
                    destination = normalize_telegram_chat_id(
                        telegram_chat_id
                    )
                except TelegramConfigurationError as exc:
                    raise NotificationTargetError(
                        exc.code,
                        str(exc),
                    ) from exc
        else:
            provider = (
                GENERIC_EVENT
                if webhook_provider is UNSET
                else normalize_stored_webhook_provider(webhook_provider)
            )
            if provider == "legacy_auto":
                raise NotificationTargetError(
                    "invalid_webhook_provider",
                    "legacy_auto is not selectable for a new target",
                )
            if webhook_url is not UNSET:
                try:
                    destination = validate_webhook_url(
                        webhook_url,
                        provider,
                    )
                except WebhookConfigurationError as exc:
                    raise NotificationTargetError(
                        exc.code,
                        str(exc),
                    ) from exc
            if (
                webhook_signing_secret is not UNSET
                and webhook_signing_secret is not None
                and str(webhook_signing_secret).strip()
            ):
                if provider not in {FEISHU_LARK_V2, DINGTALK}:
                    raise NotificationTargetError(
                        "webhook_signing_not_supported",
                        "selected webhook provider does not support signing",
                    )
                signing = validate_signing_secret(
                    webhook_signing_secret
                )
        if require_destination and not destination:
            raise NotificationTargetError(
                "notification_destination_required",
                "notification target destination is required",
                status_code=409,
            )
        return destination or "", provider, signing

    @staticmethod
    def _validate_configuration_fields(
        *,
        channel: str,
        email_address: Any,
        webhook_url: Any,
        webhook_provider: Any,
        webhook_signing_secret: Any,
        telegram_chat_id: Any,
    ) -> None:
        provided = {
            "email_address": email_address is not UNSET,
            "webhook_url": webhook_url is not UNSET,
            "webhook_provider": webhook_provider is not UNSET,
            "webhook_signing_secret": webhook_signing_secret is not UNSET,
            "telegram_chat_id": telegram_chat_id is not UNSET,
        }
        allowed = {
            "email": {"email_address"},
            "webhook": {
                "webhook_url",
                "webhook_provider",
                "webhook_signing_secret",
            },
            "telegram": {"telegram_chat_id"},
        }[channel]
        if any(
            is_provided and field not in allowed
            for field, is_provided in provided.items()
        ):
            raise NotificationTargetError(
                "invalid_notification_target_configuration",
                "notification target configuration does not match its channel",
            )

    def _destination(self, target: dict[str, Any]) -> str | None:
        env_name = str(target.get("destination_env_name") or "")
        digest = str(target.get("destination_secret_digest") or "")
        if not env_name and not digest:
            return self._legacy_email_destination(target)
        if not env_name or not re.fullmatch(r"[0-9a-f]{64}", digest):
            return None
        binding_kind = str(
            target.get("secret_binding_kind") or "target_v16"
        )
        if (
            binding_kind == "target_v16"
            and env_name != self.destination_env_name(str(target["id"]))
        ):
            return None
        value = self.secret_store.read().get(env_name)
        if value is None:
            value = os.environ.get(env_name)
        if value is None or not hmac_compare(self._digest(value), digest):
            return None
        try:
            channel = str(target["channel"])
            if channel == "email":
                return _normalize_email(value)
            if channel == "telegram":
                return normalize_telegram_chat_id(value)
            provider = normalize_stored_webhook_provider(
                target.get("webhook_provider")
            )
            return validate_webhook_url(
                value,
                provider,
                legacy_compat=provider == "legacy_auto",
            )
        except (
            NotificationTargetError,
            TelegramConfigurationError,
            WebhookConfigurationError,
        ):
            return None

    def _signing_secret(self, target: dict[str, Any]) -> str | None:
        env_name = str(target.get("webhook_signing_env_name") or "")
        digest = str(
            target.get("webhook_signing_secret_digest") or ""
        )
        if not env_name and not digest:
            return None
        if (
            not env_name
            or not re.fullmatch(r"[0-9a-f]{64}", digest)
            or (
                target.get("secret_binding_kind") == "target_v16"
                and env_name
                != self.signing_env_name(str(target["id"]))
            )
        ):
            return None
        value = self.secret_store.read().get(env_name)
        if value is None:
            value = os.environ.get(env_name)
        if value is None or not hmac_compare(self._digest(value), digest):
            return None
        try:
            return validate_signing_secret(value)
        except WebhookConfigurationError:
            return None

    def _legacy_email_destination(
        self,
        target: dict[str, Any],
    ) -> str | None:
        """Resolve v15 email rows without exposing or copying them in migration."""

        if target.get("channel") != "email":
            return None
        binding_kind = str(target.get("secret_binding_kind") or "")
        if binding_kind == "legacy_user_v15":
            row = self.store.connect().execute(
                """
                SELECT email_address FROM user_notification_settings
                WHERE workspace_id = ? AND user_id = ?
                """,
                (
                    target.get("workspace_id"),
                    target.get("owner_user_id"),
                ),
            ).fetchone()
        elif binding_kind == "legacy_apify_v15":
            row = self.store.connect().execute(
                """
                SELECT email_address FROM apify_actor_alert_settings
                WHERE workspace_id = ?
                """,
                (target.get("workspace_id"),),
            ).fetchone()
        else:
            return None
        try:
            return _normalize_email(row["email_address"]) if row else None
        except NotificationTargetError:
            return None

    def _transport_ready(self, target: dict[str, Any]) -> bool:
        channel = str(target.get("channel") or "")
        if channel == "email":
            return self.email_transport.is_ready(
                workspace_id=str(target.get("workspace_id") or "")
            )
        if channel == "telegram":
            return self.telegram_transport.is_ready(
                workspace_id=str(target.get("workspace_id") or "")
            )
        return channel == "webhook"

    def _transport_configured(self, target: dict[str, Any]) -> bool:
        channel = str(target.get("channel") or "")
        workspace_id = str(target.get("workspace_id") or "")
        if channel == "email":
            settings = self.email_transport.get_public_settings(
                workspace_id=workspace_id
            )
            return bool(
                settings.get("configured")
                and settings.get("credential_configured")
            )
        if channel == "telegram":
            settings = self.telegram_transport.get_public_settings(
                workspace_id=workspace_id
            )
            return bool(
                settings.get("configured")
                and settings.get("token_configured")
            )
        return channel == "webhook"

    def _editable_target(
        self,
        *,
        workspace_id: str,
        actor: dict[str, Any],
        target_id: str,
    ) -> dict[str, Any]:
        target = self.store.get_notification_target(
            workspace_id=workspace_id,
            target_id=target_id,
        )
        if target is None or target.get("archived_at") is not None:
            raise NotificationTargetError(
                "notification_target_not_found",
                "notification target was not found",
                status_code=404,
            )
        private_owner = (
            target.get("scope") == "private"
            and str(target.get("owner_user_id")) == str(actor.get("id"))
            and str(actor.get("role") or "") != "viewer"
        )
        shared_admin = (
            target.get("scope") == "shared"
            and str(actor.get("role") or "") in {"owner", "admin"}
        )
        if not private_owner and not shared_admin:
            raise NotificationTargetError(
                "forbidden",
                "notification target cannot be modified by this account",
                status_code=403,
            )
        return target

    def _actor(
        self,
        *,
        workspace_id: str,
        user_id: str,
        writable: bool,
    ) -> dict[str, Any]:
        actor = self.store.get_user(user_id)
        if (
            actor is None
            or str(actor.get("workspace_id")) != str(workspace_id)
            or not bool(actor.get("enabled"))
        ):
            raise NotificationTargetError(
                "forbidden",
                "notification targets are unavailable for this account",
                status_code=403,
            )
        if writable and str(actor.get("role") or "") == "viewer":
            raise NotificationTargetError(
                "forbidden",
                "notification targets are read-only for this account",
                status_code=403,
            )
        return actor

    def _assert_name_available(
        self,
        *,
        workspace_id: str,
        scope: str,
        owner_user_id: str | None,
        name_key: str,
        exclude_target_id: str | None = None,
    ) -> None:
        owner_clause = (
            "owner_user_id = ?" if owner_user_id is not None
            else "owner_user_id IS NULL"
        )
        parameters: list[Any] = [workspace_id, scope]
        if owner_user_id is not None:
            parameters.append(owner_user_id)
        parameters.append(name_key)
        exclude_clause = ""
        if exclude_target_id is not None:
            exclude_clause = "AND id != ?"
            parameters.append(exclude_target_id)
        row = self.store.connect().execute(
            f"""
            SELECT 1 FROM notification_targets
            WHERE workspace_id = ? AND scope = ?
              AND {owner_clause} AND name_key = ?
              AND archived_at IS NULL {exclude_clause}
            LIMIT 1
            """,
            tuple(parameters),
        ).fetchone()
        if row:
            raise NotificationTargetError(
                "notification_target_name_conflict",
                "notification target name is already in use",
                status_code=409,
            )

    def _secret_is_referenced_elsewhere(
        self,
        env_name: str,
        *,
        target_id: str,
    ) -> bool:
        """Protect shared legacy refs while clearing true target orphans."""

        references = (
            (
                "notification_targets",
                "destination_env_name",
                "id != ?",
                (target_id,),
            ),
            (
                "notification_targets",
                "webhook_signing_env_name",
                "id != ?",
                (target_id,),
            ),
            ("user_notification_settings", "webhook_env_name", "", ()),
            (
                "user_notification_settings",
                "webhook_signing_env_name",
                "",
                (),
            ),
            ("user_notification_channels", "destination_env_name", "", ()),
            ("apify_actor_alert_settings", "webhook_env_name", "", ()),
            (
                "apify_actor_alert_settings",
                "webhook_signing_env_name",
                "",
                (),
            ),
            (
                "apify_actor_alert_channels",
                "destination_env_name",
                "",
                (),
            ),
            ("workspace_email_transports", "credential_env_name", "", ()),
            ("workspace_telegram_transports", "token_env_name", "", ()),
            ("secret_refs", "env_name", "", ()),
            ("source_catalog", "secret_env", "", ()),
        )
        connection = self.store.connect()
        for table, column, extra_clause, parameters in references:
            query = f"SELECT 1 FROM {table} WHERE {column} = ?"
            if extra_clause:
                query += f" AND {extra_clause}"
            if connection.execute(
                query + " LIMIT 1",
                (env_name, *parameters),
            ).fetchone():
                return True
        return False

    @staticmethod
    def _digest(value: str) -> str:
        return hashlib.sha256(value.encode("utf-8")).hexdigest()

    @staticmethod
    def _sync_environment(updates: dict[str, str | None]) -> None:
        for name, value in updates.items():
            if value is None:
                os.environ.pop(name, None)
            else:
                os.environ[name] = value


def hmac_compare(left: str, right: str) -> bool:
    return hmac.compare_digest(left, right)
