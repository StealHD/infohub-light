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

from ..storage.service_store import ServiceStore
from .network_policy import UnsafeNetworkTarget, post_public_http
from .notification_email_transport import (
    EmailTransportError,
    WorkspaceEmailTransportService,
)
from .secret_store import SecretStore


logger = logging.getLogger(__name__)
UNSET = object()
_EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
_SAFE_ERROR_CODE_RE = re.compile(r"^[a-z][a-z0-9_.:-]{0,63}$")
_MAX_DELIVERIES_PER_TICK = 20
_TEST_COOLDOWN_SECONDS = 60


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


def _validate_webhook_url(value: Any) -> str:
    candidate = str(value or "").strip()
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        hostname_ascii = (
            hostname.rstrip(".").encode("idna").decode("ascii")
            if hostname
            else ""
        )
        parsed.port
    except (UnicodeError, ValueError):
        parsed = None
        hostname = None
        hostname_ascii = ""
    if (
        len(candidate) > 4096
        or "\r" in candidate
        or "\n" in candidate
        or "\x00" in candidate
        or parsed is None
        or parsed.scheme != "https"
        or not hostname
        or not hostname_ascii
        or parsed.username is not None
        or parsed.password is not None
        or parsed.fragment
    ):
        raise NotificationServiceError(
            "invalid_notification_destination",
            "notification webhook must be a credential-free HTTPS URL",
        )
    return candidate


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

    @staticmethod
    def webhook_env_name(*, workspace_id: str, user_id: str) -> str:
        digest = hashlib.sha256(
            f"{workspace_id}:{user_id}".encode("utf-8")
        ).hexdigest()[:24].upper()
        return f"HORIZON_USER_WEBHOOK_{digest}"

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
        if settings is None:
            return {
                "schema_version": 1,
                "enabled": False,
                "channel": "webhook",
                "email_configured": False,
                "email_transport_ready": self.email_transport.is_ready(
                    workspace_id=workspace_id
                ),
                "webhook_configured": False,
                "last_test_status": None,
                "last_tested_at": None,
                "last_test_error_code": None,
                "updated_at": None,
            }
        return {
            "schema_version": 1,
            "enabled": bool(settings.get("enabled")),
            "channel": str(settings.get("channel") or "webhook"),
            "email_configured": bool(settings.get("email_address")),
            "email_transport_ready": self.email_transport.is_ready(
                workspace_id=workspace_id
            ),
            "webhook_configured": bool(self._bound_webhook_secret(settings)),
            "last_test_status": settings.get("last_test_status"),
            "last_tested_at": settings.get("last_tested_at"),
            "last_test_error_code": settings.get("last_test_error_code"),
            "updated_at": settings.get("updated_at"),
        }

    def upsert_settings(
        self,
        *,
        workspace_id: str,
        user_id: str,
        enabled: Any = UNSET,
        channel: Any = UNSET,
        email_address: Any = UNSET,
        webhook_url: Any = UNSET,
    ) -> dict[str, Any]:
        conn = self.store.connect()
        if conn.in_transaction:
            raise RuntimeError(
                "notification settings update requires no active transaction"
            )
        previous_secret: str | None = None
        current_env_name = ""
        target_env_name: str | None = None
        target_webhook_digest: str | None = None
        secret_changed = False
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
            target_enabled = bool(
                (current or {}).get("enabled", False)
                if enabled is UNSET or enabled is None
                else enabled
            )
            target_channel = str(
                (current or {}).get("channel") or "webhook"
                if channel is UNSET or channel is None
                else channel
            ).strip().lower()
            if target_channel not in {"email", "webhook"}:
                raise NotificationServiceError(
                    "invalid_notification_channel",
                    "notification channel must be email or webhook",
                )
            target_email = (
                (current or {}).get("email_address")
                if email_address is UNSET
                else _normalize_email(email_address)
            )
            expected_env_name = self.webhook_env_name(
                workspace_id=workspace_id,
                user_id=user_id,
            )
            stored_env_name = str(
                (current or {}).get("webhook_env_name") or ""
            )
            current_env_name = (
                stored_env_name
                if stored_env_name == expected_env_name
                else ""
            )
            target_env_name = current_env_name or None
            target_webhook_digest = (
                str((current or {}).get("webhook_secret_digest") or "")
                if current_env_name
                else None
            ) or None
            secret_changed = webhook_url is not UNSET
            validated_webhook_url: str | None = None
            if secret_changed:
                previous_secret = self.secret_store.read().get(
                    expected_env_name
                )
                if webhook_url is None or not str(webhook_url).strip():
                    target_env_name = None
                    target_webhook_digest = None
                else:
                    target_env_name = expected_env_name
                    validated_webhook_url = _validate_webhook_url(webhook_url)
                    target_webhook_digest = hashlib.sha256(
                        validated_webhook_url.encode("utf-8")
                    ).hexdigest()

            webhook_configured = False
            if secret_changed:
                webhook_configured = bool(
                    target_env_name
                    and target_webhook_digest
                    and webhook_url is not None
                    and str(webhook_url).strip()
                )
            elif current is not None:
                webhook_configured = bool(
                    self._bound_webhook_secret(current)
                )
            if target_enabled and target_channel == "email" and not target_email:
                raise NotificationServiceError(
                    "notification_destination_required",
                    "configure a notification email address before enabling email delivery",
                    status_code=409,
                )
            if (
                target_enabled
                and target_channel == "email"
                and not self.email_transport.is_ready(
                    workspace_id=workspace_id
                )
            ):
                raise NotificationServiceError(
                    "notification_channel_unavailable",
                    "workspace email transport is not ready",
                    status_code=409,
                )
            if (
                target_enabled
                and target_channel == "webhook"
                and not webhook_configured
            ):
                raise NotificationServiceError(
                    "notification_destination_required",
                    "configure a webhook before enabling webhook delivery",
                    status_code=409,
                )

            if secret_changed:
                if target_env_name is None:
                    self.secret_store.delete(expected_env_name)
                    os.environ.pop(expected_env_name, None)
                else:
                    self.secret_store.set(
                        target_env_name,
                        str(validated_webhook_url),
                    )
            store_updates: dict[str, Any] = {}
            if enabled is not UNSET:
                store_updates["enabled"] = enabled
            if channel is not UNSET:
                store_updates["channel"] = target_channel
            if email_address is not UNSET:
                store_updates["email_address"] = target_email
            if secret_changed:
                store_updates["webhook_env_name"] = target_env_name
                store_updates["webhook_secret_digest"] = (
                    target_webhook_digest
                )
            elif (
                stored_env_name
                and (
                    not current_env_name
                    or not target_webhook_digest
                )
            ):
                store_updates["webhook_env_name"] = None
                store_updates["webhook_secret_digest"] = None
            self.store.upsert_user_notification_settings(
                workspace_id=workspace_id,
                user_id=user_id,
                commit=False,
                **store_updates,
            )
            conn.commit()
        except Exception as exc:
            if conn.in_transaction:
                conn.rollback()
            if secret_changed:
                if previous_secret is not None:
                    self.secret_store.set(
                        expected_env_name,
                        previous_secret,
                    )
                else:
                    self.secret_store.delete(expected_env_name)
                    os.environ.pop(expected_env_name, None)
            if isinstance(exc, (LookupError, PermissionError)):
                raise NotificationServiceError(
                    "notification_channel_unavailable",
                    "notification settings are unavailable for this account",
                    status_code=409,
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
        if str(settings.get("channel") or "") == "email":
            if (
                not settings.get("email_address")
                or not self.email_transport.is_ready(
                    workspace_id=workspace_id
                )
            ):
                return 0
        elif str(settings.get("channel") or "") == "webhook":
            if not self._bound_webhook_secret(settings):
                return 0
        else:
            return 0

        snapshot = conn.execute(
            """
            SELECT *
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
            WHERE workspace_id = ? AND user_id = ? AND id != ?
            ORDER BY generated_at DESC, created_at DESC, id DESC
            LIMIT 1
            """,
            (workspace_id, user_id, snapshot_id),
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
            item_subscription_ids = item.get("subscription_ids")
            subscription_ids = list(
                dict.fromkeys(
                    str(value)
                    for value in [
                        *(
                            item_subscription_ids
                            if isinstance(item_subscription_ids, list)
                            else []
                        ),
                        item.get("subscription_id"),
                        row["subscription_id"],
                    ]
                    if value
                )
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
                enabled_at = max(account_enabled_at, subscription_enabled_at)
                if published_at <= enabled_at:
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
                inserted = conn.execute(
                    """
                    INSERT OR IGNORE INTO preferred_source_notification_deliveries (
                        id, workspace_id, user_id, subscription_id, source_id,
                        snapshot_id, job_id, article_id, channel, payload_json,
                        status, attempts, account_notification_generation,
                        subscription_notification_generation,
                        created_at, updated_at
                    ) VALUES (
                        ?, ?, ?, ?, ?, ?, ?, ?, ?, ?,
                        'pending', 0, ?, ?, ?, ?
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
                        str(settings["channel"]),
                        _json_dumps(payload),
                        account_generation,
                        subscription_generation,
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
                if (
                    settings is None
                    or not bool(settings.get("enabled"))
                    or str(settings.get("channel")) != str(first["channel"])
                ):
                    raise NotificationServiceError(
                        "notification_settings_changed",
                        "notification settings changed before delivery",
                        status_code=409,
                    )
                account_enabled_at = _parse_time(
                    settings.get("notification_enabled_at")
                )
                account_generation = int(
                    settings.get("notification_generation") or 0
                )
                if account_enabled_at is None:
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
                    current_watermark = max(
                        account_enabled_at,
                        subscription_enabled_at,
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
                    break
                send_started = True
                self._send_payload(
                    settings,
                    self._batch_delivery_payload(active_deliveries),
                )
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
            break
        return summary

    def send_test(
        self,
        *,
        workspace_id: str,
        user_id: str,
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
        attempt = self.store.claim_user_notification_test_attempt(
            workspace_id=workspace_id,
            user_id=user_id,
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
        try:
            self._send_payload(settings, payload)
        except NotificationServiceError as exc:
            self.store.record_user_notification_test(
                workspace_id=workspace_id,
                user_id=user_id,
                status="failed",
                error_code=exc.code,
            )
            raise NotificationServiceError(
                "notification_test_failed",
                "notification test could not be delivered",
                status_code=exc.status_code,
                retryable=exc.retryable,
            ) from exc
        except Exception as exc:
            error = NotificationServiceError(
                "notification_test_failed",
                "notification test could not be delivered",
                status_code=502,
                retryable=True,
            )
            self.store.record_user_notification_test(
                workspace_id=workspace_id,
                user_id=user_id,
                status="failed",
                error_code="notification_delivery_failed",
            )
            raise error from exc
        self.store.record_user_notification_test(
            workspace_id=workspace_id,
            user_id=user_id,
            status="sent",
        )
        return {"sent": True, "channel": str(settings["channel"])}

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
                SELECT workspace_id, user_id, channel, job_id
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
                  AND job_id IS ?
                GROUP BY article_id
                ORDER BY first_created_at, article_id
                LIMIT ?
                """,
                (
                    row["workspace_id"],
                    row["user_id"],
                    row["channel"],
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
                  AND job_id IS ?
                  AND article_id IN ({article_placeholders})
                ORDER BY created_at, id
                """,
                (
                    row["workspace_id"],
                    row["user_id"],
                    row["channel"],
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
    ) -> None:
        channel = str(settings.get("channel") or "")
        if channel == "webhook":
            self._send_webhook(settings, payload)
            return
        if channel == "email":
            self._send_email(settings, payload)
            return
        raise NotificationServiceError(
            "invalid_notification_channel",
            "notification channel must be email or webhook",
        )

    def _send_webhook(
        self,
        settings: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        webhook_url = self._bound_webhook_secret(settings)
        if not webhook_url:
            raise NotificationServiceError(
                "notification_destination_required",
                "notification webhook is not configured",
                status_code=409,
            )
        webhook_url = _validate_webhook_url(webhook_url)
        body = _json_dumps(
            {
                "event": (
                    "inteliscope.preferred_source.test"
                    if payload.get("kind") == "test"
                    else "inteliscope.preferred_source.new_items"
                ),
                "data": (
                    {**payload, "test": True}
                    if payload.get("kind") == "test"
                    else {
                        "schema_version": 1,
                        "items": list(payload.get("items") or [])[
                            :_MAX_DELIVERIES_PER_TICK
                        ],
                    }
                ),
            }
        ).encode("utf-8")
        try:
            response = _run_coroutine(
                asyncio.wait_for(
                    post_public_http(
                        webhook_url,
                        content=body,
                        headers={
                            "Content-Type": "application/json; charset=utf-8"
                        },
                        timeout=5.0,
                        max_response_bytes=64_000,
                    ),
                    timeout=6.0,
                )
            )
        except UnsafeNetworkTarget as exc:
            raise NotificationServiceError(
                "notification_webhook_target_blocked",
                "notification webhook must resolve only to the public network",
                status_code=400,
            ) from exc
        except Exception as exc:
            raise NotificationServiceError(
                "notification_webhook_unavailable",
                "notification webhook is unavailable",
                status_code=502,
                retryable=True,
                outcome_unknown=True,
            ) from exc
        content_encoding = (
            response.headers.get("content-encoding", "").strip().lower()
        )
        if content_encoding not in {"", "identity"}:
            raise NotificationServiceError(
                "notification_webhook_response_encoding_unsupported",
                "notification webhook returned an unsupported content encoding",
                status_code=502,
                outcome_unknown=True,
            )
        if not 200 <= int(response.status_code) < 300:
            raise NotificationServiceError(
                "notification_webhook_rejected",
                "notification webhook rejected the request",
                status_code=502,
            )

    def _send_email(
        self,
        settings: dict[str, Any],
        payload: dict[str, Any],
    ) -> None:
        recipient = _normalize_email(settings.get("email_address"))
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
