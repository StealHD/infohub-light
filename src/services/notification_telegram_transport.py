"""Bounded Telegram Bot API delivery for Service notifications."""

from __future__ import annotations

import json
import re
from dataclasses import dataclass
from typing import Any, Callable

import httpx

from .network_policy import (
    NetworkResolutionError,
    UnsafeNetworkResponse,
    UnsafeNetworkTarget,
    post_public_http,
)


_TELEGRAM_API_HOST = "api.telegram.org"
_BOT_TOKEN_RE = re.compile(
    r"^[0-9]{5,20}:[A-Za-z0-9_-]{30,100}$"
)
_CHAT_USERNAME_RE = re.compile(
    r"^@[A-Za-z][A-Za-z0-9_]{4,31}$"
)
_NUMERIC_CHAT_ID_RE = re.compile(r"^-?[1-9][0-9]{0,18}$")
_ACK_LIMIT_BYTES = 32_768
_MESSAGE_LIMIT_CHARACTERS = 4_096
_MIN_SIGNED_64 = -(2**63)
_MAX_SIGNED_64 = (2**63) - 1


class TelegramConfigurationError(ValueError):
    """A Telegram token, chat destination, or message is invalid."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class TelegramDeliveryError(RuntimeError):
    """A safe Telegram failure suitable for a Service error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 502,
        retryable: bool = False,
        outcome_unknown: bool = False,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = int(status_code)
        self.retryable = bool(retryable)
        self.outcome_unknown = bool(outcome_unknown)


@dataclass(frozen=True, slots=True)
class TelegramSendResult:
    """Verified Telegram acknowledgement metadata."""

    message_id: int
    verification: str


def normalize_telegram_bot_token(value: Any) -> str:
    """Validate a Bot API token without ever echoing it in an error."""

    candidate = str(value or "").strip()
    if not _BOT_TOKEN_RE.fullmatch(candidate):
        raise TelegramConfigurationError(
            "invalid_telegram_bot_token",
            "telegram bot token is invalid",
        )
    return candidate


def normalize_telegram_chat_id(value: Any) -> str:
    """Return a canonical numeric chat ID or public ``@username``."""

    candidate = str(value or "").strip()
    if _NUMERIC_CHAT_ID_RE.fullmatch(candidate):
        numeric_id = int(candidate)
        if _MIN_SIGNED_64 <= numeric_id <= _MAX_SIGNED_64:
            return candidate
    if _CHAT_USERNAME_RE.fullmatch(candidate):
        return candidate.lower()
    raise TelegramConfigurationError(
        "invalid_telegram_chat_id",
        "telegram chat destination is invalid",
    )


def _normalize_message_text(value: Any) -> str:
    if not isinstance(value, str) or not value.strip():
        raise TelegramConfigurationError(
            "invalid_telegram_message",
            "telegram message text is required",
        )
    if len(value) > _MESSAGE_LIMIT_CHARACTERS:
        raise TelegramConfigurationError(
            "telegram_message_too_long",
            "telegram message text exceeds 4096 characters",
        )
    return value


def _delivery_error_for_status(status: int) -> TelegramDeliveryError:
    if status == 401:
        return TelegramDeliveryError(
            "notification_telegram_authentication_failed",
            "telegram bot authentication failed",
            status_code=400,
        )
    if status in {400, 403}:
        return TelegramDeliveryError(
            "notification_telegram_destination_rejected",
            "telegram rejected the notification destination",
            status_code=400,
        )
    if status == 429:
        return TelegramDeliveryError(
            "notification_telegram_rate_limited",
            "telegram rate limited the notification",
            status_code=429,
            retryable=True,
        )
    if status in {408, 425} or status >= 500:
        return TelegramDeliveryError(
            "notification_telegram_outcome_unknown",
            "telegram notification outcome is unknown",
            outcome_unknown=True,
        )
    return TelegramDeliveryError(
        "notification_telegram_provider_rejected",
        "telegram rejected the notification",
        status_code=400,
    )


def _decode_ack(response: httpx.Response) -> dict[str, Any]:
    try:
        decoded = response.content.decode("utf-8")
        ack = json.loads(decoded)
    except (UnicodeDecodeError, TypeError, ValueError):
        ack = None
    if not isinstance(ack, dict):
        raise TelegramDeliveryError(
            "notification_telegram_response_invalid",
            "telegram notification response could not be verified",
            outcome_unknown=True,
        )
    return ack


def _ack_matches_chat(ack_chat: Any, chat_id: str) -> bool:
    if not isinstance(ack_chat, dict):
        return False
    if chat_id.startswith("@"):
        username = ack_chat.get("username")
        return bool(
            isinstance(username, str)
            and f"@{username}".lower() == chat_id
        )
    remote_id = ack_chat.get("id")
    return bool(
        type(remote_id) is int
        and remote_id == int(chat_id)
    )


def _verify_ack(
    response: httpx.Response,
    *,
    chat_id: str,
) -> TelegramSendResult:
    ack = _decode_ack(response)
    if ack.get("ok") is not True:
        error_code = ack.get("error_code")
        if type(error_code) is int and error_code in {
            400,
            401,
            403,
            429,
        }:
            raise _delivery_error_for_status(error_code)
        raise TelegramDeliveryError(
            "notification_telegram_response_invalid",
            "telegram notification response could not be verified",
            outcome_unknown=True,
        )

    result = ack.get("result")
    if not isinstance(result, dict):
        result = {}
    message_id = result.get("message_id")
    if (
        type(message_id) is not int
        or message_id <= 0
        or not _ack_matches_chat(result.get("chat"), chat_id)
    ):
        raise TelegramDeliveryError(
            "notification_telegram_response_invalid",
            "telegram notification response could not be verified",
            outcome_unknown=True,
        )
    return TelegramSendResult(
        message_id=message_id,
        verification="provider_accepted",
    )


async def send_telegram_message(
    bot_token: Any,
    chat_id: Any,
    text: Any,
    *,
    timeout: float = 5.0,
    transport_factory: Callable[
        [], httpx.AsyncBaseTransport
    ]
    | None = None,
    post: Callable[..., Any] = post_public_http,
) -> TelegramSendResult:
    """POST one plain-text message and require a matching Telegram ACK."""

    token = normalize_telegram_bot_token(bot_token)
    destination = normalize_telegram_chat_id(chat_id)
    message = _normalize_message_text(text)
    target_url = (
        f"https://{_TELEGRAM_API_HOST}/bot{token}/sendMessage"
    )
    content = json.dumps(
        {
            "chat_id": destination,
            "text": message,
            "link_preview_options": {"is_disabled": True},
        },
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")

    try:
        response = await post(
            target_url,
            content=content,
            headers={
                "Content-Type": "application/json; charset=utf-8"
            },
            timeout=timeout,
            max_response_bytes=_ACK_LIMIT_BYTES,
            transport_factory=transport_factory,
            response_body_mode="bounded",
            synthetic_dns_hosts=(_TELEGRAM_API_HOST,),
        )
    except NetworkResolutionError:
        raise TelegramDeliveryError(
            "notification_telegram_unavailable",
            "telegram notification service is unavailable",
            status_code=503,
            retryable=True,
        ) from None
    except UnsafeNetworkTarget:
        raise TelegramDeliveryError(
            "notification_telegram_unavailable",
            "telegram notification service is unavailable",
            status_code=503,
        ) from None
    except UnsafeNetworkResponse:
        raise TelegramDeliveryError(
            "notification_telegram_response_invalid",
            "telegram notification response could not be verified",
            outcome_unknown=True,
        ) from None
    except (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.PoolTimeout,
    ):
        raise TelegramDeliveryError(
            "notification_telegram_unavailable",
            "telegram notification service is unavailable",
            status_code=503,
            retryable=True,
        ) from None
    except httpx.TransportError:
        raise TelegramDeliveryError(
            "notification_telegram_outcome_unknown",
            "telegram notification outcome is unknown",
            outcome_unknown=True,
        ) from None

    status = int(response.status_code)
    if not 200 <= status < 300:
        raise _delivery_error_for_status(status)
    if status != 200:
        raise TelegramDeliveryError(
            "notification_telegram_response_invalid",
            "telegram notification response could not be verified",
            outcome_unknown=True,
        )
    return _verify_ack(response, chat_id=destination)
