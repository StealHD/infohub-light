from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from src.services.network_policy import UnsafeNetworkResponse
from src.services.notification_telegram_transport import (
    TelegramConfigurationError,
    TelegramDeliveryError,
    normalize_telegram_bot_token,
    normalize_telegram_chat_id,
    send_telegram_message,
)


BOT_TOKEN = (
    "123456789:"
    "AAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAAA"
)
NUMERIC_CHAT_ID = "-1001234567890"
USERNAME_CHAT_ID = "@example_channel"


def _ack(
    *,
    chat_id: int = -1001234567890,
    username: str | None = None,
    message_id: int = 42,
) -> httpx.Response:
    chat: dict[str, Any] = {"id": chat_id}
    if username is not None:
        chat["username"] = username
    return httpx.Response(
        200,
        json={
            "ok": True,
            "result": {
                "message_id": message_id,
                "chat": chat,
            },
        },
    )


def _deliver(
    *,
    chat_id: str = NUMERIC_CHAT_ID,
    text: str = "Plain <b>text</b>",
    response: httpx.Response | None = None,
) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {"calls": 0}

    async def post(target: str, **kwargs: Any) -> httpx.Response:
        captured["calls"] += 1
        captured.update({"url": target, **kwargs})
        return response or _ack()

    result = asyncio.run(
        send_telegram_message(
            BOT_TOKEN,
            chat_id,
            text,
            post=post,
        )
    )
    captured["body"] = json.loads(
        captured["content"].decode("utf-8")
    )
    return result, captured


def test_normalizers_return_canonical_safe_values() -> None:
    assert normalize_telegram_bot_token(
        f"  {BOT_TOKEN}\n"
    ) == BOT_TOKEN
    assert normalize_telegram_chat_id(
        f" {NUMERIC_CHAT_ID} "
    ) == NUMERIC_CHAT_ID
    assert normalize_telegram_chat_id(
        "-9223372036854775808"
    ) == "-9223372036854775808"
    assert normalize_telegram_chat_id(
        "9223372036854775807"
    ) == "9223372036854775807"
    assert normalize_telegram_chat_id(
        " @Example_Channel "
    ) == USERNAME_CHAT_ID


@pytest.mark.parametrize(
    "value",
    (
        "",
        "123:short",
        "123456789:not/a/path",
        "123456789:has.dot.characters.that.are.not.allowed",
        "123456789:AAAAAAAAAAAAAAAAAAAAAAAAAAAAAA\n/path",
    ),
)
def test_invalid_bot_tokens_are_rejected_without_echo(
    value: str,
) -> None:
    with pytest.raises(TelegramConfigurationError) as exc_info:
        normalize_telegram_bot_token(value)

    assert exc_info.value.code == "invalid_telegram_bot_token"
    if value.strip():
        assert value.strip() not in str(exc_info.value)


@pytest.mark.parametrize(
    "value",
    (
        "",
        "0",
        "-0",
        "+123",
        "00123",
        "@four",
        "@bad-name",
        "https://t.me/example_channel",
        "-100123456789012345678",
        "-9223372036854775809",
        "9223372036854775808",
        "9999999999999999999",
    ),
)
def test_invalid_chat_ids_are_rejected_without_echo(
    value: str,
) -> None:
    with pytest.raises(TelegramConfigurationError) as exc_info:
        normalize_telegram_chat_id(value)

    assert exc_info.value.code == "invalid_telegram_chat_id"
    if value.strip():
        assert value.strip() not in str(exc_info.value)


def test_send_uses_fixed_endpoint_plain_text_and_bounded_ack() -> None:
    result, captured = _deliver()

    assert captured["calls"] == 1
    assert captured["url"] == (
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage"
    )
    assert captured["headers"] == {
        "Content-Type": "application/json; charset=utf-8"
    }
    assert captured["body"] == {
        "chat_id": NUMERIC_CHAT_ID,
        "text": "Plain <b>text</b>",
        "link_preview_options": {"is_disabled": True},
    }
    assert "parse_mode" not in captured["body"]
    assert captured["max_response_bytes"] == 32_768
    assert captured["response_body_mode"] == "bounded"
    assert result.message_id == 42
    assert result.verification == "provider_accepted"


def test_username_destination_requires_matching_ack_username() -> None:
    result, _captured = _deliver(
        chat_id="@Example_Channel",
        response=_ack(
            username="example_channel",
        ),
    )
    assert result.message_id == 42

    with pytest.raises(TelegramDeliveryError) as exc_info:
        _deliver(
            chat_id=USERNAME_CHAT_ID,
            response=_ack(username="another_channel"),
        )
    assert exc_info.value.code == (
        "notification_telegram_response_invalid"
    )
    assert exc_info.value.outcome_unknown is True


@pytest.mark.parametrize(
    "response",
    (
        httpx.Response(200, content=b"not-json"),
        httpx.Response(200, json=[]),
        httpx.Response(200, json={"ok": "true"}),
        httpx.Response(
            200,
            json={"ok": True, "result": {"message_id": 42}},
        ),
        httpx.Response(
            200,
            json={
                "ok": True,
                "result": {
                    "message_id": True,
                    "chat": {"id": -1001234567890},
                },
            },
        ),
        _ack(chat_id=-1009999999999),
    ),
)
def test_malformed_or_mismatched_ack_is_outcome_unknown(
    response: httpx.Response,
) -> None:
    with pytest.raises(TelegramDeliveryError) as exc_info:
        _deliver(response=response)

    assert exc_info.value.code == (
        "notification_telegram_response_invalid"
    )
    assert exc_info.value.retryable is False
    assert exc_info.value.outcome_unknown is True


def test_unexpected_success_status_is_outcome_unknown() -> None:
    response = _ack()
    response.status_code = 201

    with pytest.raises(TelegramDeliveryError) as exc_info:
        _deliver(response=response)

    assert exc_info.value.code == (
        "notification_telegram_response_invalid"
    )
    assert exc_info.value.outcome_unknown is True


@pytest.mark.parametrize(
    ("status", "code", "status_code", "retryable"),
    (
        (
            401,
            "notification_telegram_authentication_failed",
            400,
            False,
        ),
        (
            400,
            "notification_telegram_destination_rejected",
            400,
            False,
        ),
        (
            403,
            "notification_telegram_destination_rejected",
            400,
            False,
        ),
        (
            429,
            "notification_telegram_rate_limited",
            429,
            True,
        ),
    ),
)
def test_known_http_errors_have_stable_safe_semantics(
    status: int,
    code: str,
    status_code: int,
    retryable: bool,
) -> None:
    secret_remote_body = (
        f"token={BOT_TOKEN}; chat={NUMERIC_CHAT_ID}"
    )
    with pytest.raises(TelegramDeliveryError) as exc_info:
        _deliver(
            response=httpx.Response(
                status,
                content=secret_remote_body.encode(),
            )
        )

    assert exc_info.value.code == code
    assert exc_info.value.status_code == status_code
    assert exc_info.value.retryable is retryable
    assert exc_info.value.outcome_unknown is False
    assert BOT_TOKEN not in str(exc_info.value)
    assert NUMERIC_CHAT_ID not in str(exc_info.value)
    assert secret_remote_body not in str(exc_info.value)


def test_explicit_error_ack_uses_safe_status_mapping() -> None:
    with pytest.raises(TelegramDeliveryError) as exc_info:
        _deliver(
            response=httpx.Response(
                200,
                json={
                    "ok": False,
                    "error_code": 403,
                    "description": (
                        f"{BOT_TOKEN} {NUMERIC_CHAT_ID}"
                    ),
                },
            )
        )

    assert exc_info.value.code == (
        "notification_telegram_destination_rejected"
    )
    assert BOT_TOKEN not in str(exc_info.value)
    assert NUMERIC_CHAT_ID not in str(exc_info.value)


@pytest.mark.parametrize("status", (500, 502, 503, 504))
def test_server_errors_are_unknown_and_never_replayed(
    status: int,
) -> None:
    captured = {"calls": 0}

    async def post(
        _target: str,
        **_kwargs: Any,
    ) -> httpx.Response:
        captured["calls"] += 1
        return httpx.Response(status)

    with pytest.raises(TelegramDeliveryError) as exc_info:
        asyncio.run(
            send_telegram_message(
                BOT_TOKEN,
                NUMERIC_CHAT_ID,
                "test",
                post=post,
            )
        )

    assert captured["calls"] == 1
    assert exc_info.value.code == (
        "notification_telegram_outcome_unknown"
    )
    assert exc_info.value.retryable is False
    assert exc_info.value.outcome_unknown is True


def test_connect_failure_is_retryable_but_lost_response_is_unknown() -> None:
    request = httpx.Request(
        "POST",
        f"https://api.telegram.org/bot{BOT_TOKEN}/sendMessage",
    )

    async def connect_failed(
        _target: str,
        **_kwargs: Any,
    ) -> httpx.Response:
        raise httpx.ConnectError(
            f"failed {BOT_TOKEN}",
            request=request,
        )

    with pytest.raises(TelegramDeliveryError) as connect_error:
        asyncio.run(
            send_telegram_message(
                BOT_TOKEN,
                NUMERIC_CHAT_ID,
                "test",
                post=connect_failed,
            )
        )
    assert connect_error.value.code == (
        "notification_telegram_unavailable"
    )
    assert connect_error.value.status_code == 503
    assert connect_error.value.retryable is True
    assert connect_error.value.outcome_unknown is False
    assert BOT_TOKEN not in str(connect_error.value)

    async def read_failed(
        _target: str,
        **_kwargs: Any,
    ) -> httpx.Response:
        raise httpx.ReadTimeout(
            f"lost {NUMERIC_CHAT_ID}",
            request=request,
        )

    with pytest.raises(TelegramDeliveryError) as read_error:
        asyncio.run(
            send_telegram_message(
                BOT_TOKEN,
                NUMERIC_CHAT_ID,
                "test",
                post=read_failed,
            )
        )
    assert read_error.value.code == (
        "notification_telegram_outcome_unknown"
    )
    assert read_error.value.retryable is False
    assert read_error.value.outcome_unknown is True
    assert NUMERIC_CHAT_ID not in str(read_error.value)


def test_oversized_ack_is_unknown_and_not_replayed() -> None:
    captured = {"calls": 0}

    async def post(
        _target: str,
        **_kwargs: Any,
    ) -> httpx.Response:
        captured["calls"] += 1
        raise UnsafeNetworkResponse("response too large")

    with pytest.raises(TelegramDeliveryError) as exc_info:
        asyncio.run(
            send_telegram_message(
                BOT_TOKEN,
                NUMERIC_CHAT_ID,
                "test",
                post=post,
            )
        )

    assert captured["calls"] == 1
    assert exc_info.value.code == (
        "notification_telegram_response_invalid"
    )
    assert exc_info.value.outcome_unknown is True


def test_message_length_is_checked_before_any_post() -> None:
    captured = {"calls": 0}

    async def post(
        _target: str,
        **_kwargs: Any,
    ) -> httpx.Response:
        captured["calls"] += 1
        return _ack()

    result = asyncio.run(
        send_telegram_message(
            BOT_TOKEN,
            NUMERIC_CHAT_ID,
            "x" * 4_096,
            post=post,
        )
    )
    assert result.message_id == 42
    assert captured["calls"] == 1

    with pytest.raises(TelegramConfigurationError) as exc_info:
        asyncio.run(
            send_telegram_message(
                BOT_TOKEN,
                NUMERIC_CHAT_ID,
                "x" * 4_097,
                post=post,
            )
        )
    assert exc_info.value.code == "telegram_message_too_long"
    assert captured["calls"] == 1
