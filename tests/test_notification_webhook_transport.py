from __future__ import annotations

import asyncio
import base64
import hashlib
import hmac
import json
import socket
from typing import Any
from urllib.parse import parse_qs, urlsplit

import httpx
import pytest

from src.services.notification_webhook_transport import (
    DINGTALK,
    DISCORD,
    FEISHU_LARK_V2,
    GENERIC_EVENT,
    GENERIC_TEXT,
    LEGACY_AUTO,
    SLACK,
    WECOM,
    WebhookConfigurationError,
    WebhookDeliveryError,
    send_notification_webhook,
    validate_webhook_url,
)


URLS = {
    GENERIC_EVENT: "https://notify.example.test/event",
    GENERIC_TEXT: "https://notify.example.test/text",
    FEISHU_LARK_V2: (
        "https://open.feishu.cn/open-apis/bot/v2/hook/"
        "00000000-0000-0000-0000-000000000000"
    ),
    WECOM: (
        "https://qyapi.weixin.qq.com/cgi-bin/webhook/send"
        "?key=00000000-0000-0000-0000-000000000000"
    ),
    DINGTALK: (
        "https://oapi.dingtalk.com/robot/send"
        "?access_token=00000000000000000000000000000000"
    ),
    SLACK: "https://hooks.slack.com/services/T00000000/B00000000/secret-token",
    DISCORD: (
        "https://discord.com/api/webhooks/"
        "123456789012345678/discord-secret-token"
    ),
}

ACKS = {
    FEISHU_LARK_V2: httpx.Response(200, json={"code": 0}),
    WECOM: httpx.Response(200, json={"errcode": 0}),
    DINGTALK: httpx.Response(200, json={"errcode": 0}),
    SLACK: httpx.Response(200, content=b"ok"),
    DISCORD: httpx.Response(
        200,
        json={"id": "123456789012345678"},
    ),
}


def _deliver(
    *,
    provider: str,
    response: httpx.Response,
    url: str | None = None,
    text: str = "Hello @all <at> & goodbye",
    signing_secret: str | None = None,
) -> tuple[Any, dict[str, Any]]:
    captured: dict[str, Any] = {}

    async def post(target: str, **kwargs: Any) -> httpx.Response:
        captured.update({"url": target, **kwargs})
        return response

    result = asyncio.run(
        send_notification_webhook(
            provider=provider,
            webhook_url=url or URLS[provider],
            event="inteliscope.test",
            data={"answer": 42},
            text=text,
            signing_secret=signing_secret,
            now=lambda: 1_700_000_000,
            post=post,
        )
    )
    captured["body"] = json.loads(
        captured["content"].decode("utf-8")
    )
    return result, captured


@pytest.mark.parametrize(
    ("provider", "expected_body"),
    (
        (
            GENERIC_EVENT,
            {
                "event": "inteliscope.test",
                "data": {"answer": 42},
            },
        ),
        (GENERIC_TEXT, {"text": "Hello @all <at> & goodbye"}),
        (
            FEISHU_LARK_V2,
            {
                "msg_type": "text",
                "content": {
                    "text": "Hello @all ＜at＞ & goodbye",
                },
            },
        ),
        (
            WECOM,
            {
                "msgtype": "text",
                "text": {
                    "content": "Hello ＠all <at> & goodbye",
                },
            },
        ),
        (
            DINGTALK,
            {
                "msgtype": "text",
                "text": {
                    "content": "Hello ＠all <at> & goodbye",
                },
                "at": {
                    "atMobiles": [],
                    "atUserIds": [],
                    "isAtAll": False,
                },
            },
        ),
        (
            SLACK,
            {"text": "Hello @all &lt;at&gt; &amp; goodbye"},
        ),
        (
            DISCORD,
            {
                "content": "Hello ＠all <at> & goodbye",
                "flags": 4,
                "allowed_mentions": {
                    "parse": [],
                    "users": [],
                    "roles": [],
                },
            },
        ),
    ),
)
def test_provider_payloads_and_verification_modes(
    provider: str,
    expected_body: dict[str, Any],
) -> None:
    response = ACKS.get(provider, httpx.Response(204))

    result, captured = _deliver(
        provider=provider,
        response=response,
    )

    assert captured["headers"] == {
        "Content-Type": "application/json; charset=utf-8"
    }
    assert captured["body"] == expected_body
    assert captured["max_response_bytes"] == 4_096
    assert captured["response_body_mode"] == (
        "bounded"
        if provider
        in {FEISHU_LARK_V2, WECOM, DINGTALK, SLACK, DISCORD}
        else "discard"
    )
    assert result.provider == provider
    assert result.verification == (
        "provider_accepted"
        if provider
        in {FEISHU_LARK_V2, WECOM, DINGTALK, SLACK, DISCORD}
        else "http_accepted"
    )
    if provider == DISCORD:
        assert parse_qs(urlsplit(captured["url"]).query) == {
            "wait": ["true"]
        }


def test_feishu_and_dingtalk_signatures_are_provider_native() -> None:
    secret = "signing-secret"
    feishu_result, feishu = _deliver(
        provider=FEISHU_LARK_V2,
        response=ACKS[FEISHU_LARK_V2],
        signing_secret=secret,
    )
    expected_feishu = base64.b64encode(
        hmac.new(
            f"1700000000\n{secret}".encode(),
            b"",
            hashlib.sha256,
        ).digest()
    ).decode()

    assert feishu_result.verification == "provider_accepted"
    assert feishu["body"]["timestamp"] == "1700000000"
    assert feishu["body"]["sign"] == expected_feishu

    _result, dingtalk = _deliver(
        provider=DINGTALK,
        response=ACKS[DINGTALK],
        signing_secret=secret,
    )
    query = parse_qs(urlsplit(dingtalk["url"]).query)
    expected_dingtalk = base64.b64encode(
        hmac.new(
            secret.encode(),
            f"1700000000000\n{secret}".encode(),
            hashlib.sha256,
        ).digest()
    ).decode()

    assert query["access_token"] == [
        "00000000000000000000000000000000"
    ]
    assert query["timestamp"] == ["1700000000000"]
    assert query["sign"] == [expected_dingtalk]


def test_legacy_auto_preserves_feishu_and_generic_wire_formats() -> None:
    feishu, captured = _deliver(
        provider=LEGACY_AUTO,
        url=URLS[FEISHU_LARK_V2],
        response=ACKS[FEISHU_LARK_V2],
    )
    assert feishu.provider == FEISHU_LARK_V2
    assert captured["body"]["msg_type"] == "text"

    generic, captured = _deliver(
        provider=LEGACY_AUTO,
        url=URLS[GENERIC_EVENT],
        response=httpx.Response(204),
    )
    assert generic.provider == GENERIC_EVENT
    assert captured["body"] == {
        "event": "inteliscope.test",
        "data": {"answer": 42},
    }


@pytest.mark.parametrize(
    ("provider", "url"),
    (
        (GENERIC_EVENT, URLS[FEISHU_LARK_V2]),
        (GENERIC_TEXT, URLS[SLACK]),
        (FEISHU_LARK_V2, URLS[WECOM]),
        (
            FEISHU_LARK_V2,
            URLS[FEISHU_LARK_V2] + "?unexpected=true",
        ),
        (WECOM, URLS[WECOM].replace("key=", "token=")),
        (DINGTALK, URLS[DINGTALK] + "&timestamp=1"),
        (SLACK, "https://hooks.slack.com/services/too/short"),
        (DISCORD, URLS[DISCORD] + "?wait=false"),
        (DISCORD, URLS[DISCORD].replace("https://", "http://")),
    ),
)
def test_provider_url_validation_is_exact(
    provider: str,
    url: str,
) -> None:
    with pytest.raises(WebhookConfigurationError):
        validate_webhook_url(url, provider)


@pytest.mark.parametrize(
    ("provider", "response"),
    (
        (FEISHU_LARK_V2, httpx.Response(200, json={"code": False})),
        (FEISHU_LARK_V2, httpx.Response(200, json={"code": 0.0})),
        (WECOM, httpx.Response(200, json={"errcode": False})),
        (DINGTALK, httpx.Response(200, content=b"not-json")),
        (DISCORD, httpx.Response(200, json={"id": 123})),
    ),
)
def test_malformed_provider_ack_is_unknown(
    provider: str,
    response: httpx.Response,
) -> None:
    with pytest.raises(WebhookDeliveryError) as exc_info:
        _deliver(provider=provider, response=response)

    assert exc_info.value.code == "notification_webhook_response_invalid"
    assert exc_info.value.outcome_unknown is True
    assert exc_info.value.retryable is False


@pytest.mark.parametrize(
    ("provider", "response"),
    (
        (FEISHU_LARK_V2, httpx.Response(200, json={"code": 1})),
        (WECOM, httpx.Response(200, json={"errcode": 40013})),
        (DINGTALK, httpx.Response(200, json={"errcode": 310000})),
        (DISCORD, httpx.Response(401, json={"message": "unauthorized"})),
    ),
)
def test_explicit_provider_rejection_is_known(
    provider: str,
    response: httpx.Response,
) -> None:
    with pytest.raises(WebhookDeliveryError) as exc_info:
        _deliver(provider=provider, response=response)

    assert exc_info.value.code == "notification_webhook_provider_rejected"
    assert exc_info.value.outcome_unknown is False
    assert exc_info.value.retryable is False


@pytest.mark.parametrize("body", (b"", b"ok\n", b"invalid_payload"))
def test_unexpected_slack_200_body_is_unknown(body: bytes) -> None:
    with pytest.raises(WebhookDeliveryError) as exc_info:
        _deliver(
            provider=SLACK,
            response=httpx.Response(200, content=body),
        )
    assert exc_info.value.code == "notification_webhook_response_invalid"
    assert exc_info.value.outcome_unknown is True
    assert exc_info.value.retryable is False


def test_generic_uses_only_http_status_even_with_compression_header() -> None:
    result, _captured = _deliver(
        provider=GENERIC_EVENT,
        response=httpx.Response(
            200,
            headers={"content-encoding": "gzip"},
        ),
    )
    assert result.verification == "http_accepted"


def test_rate_limit_precedes_response_encoding_validation() -> None:
    with pytest.raises(WebhookDeliveryError) as exc_info:
        _deliver(
            provider=SLACK,
            response=httpx.Response(
                429,
                headers={"content-encoding": "gzip"},
            ),
        )
    assert exc_info.value.code == "notification_webhook_rate_limited"
    assert exc_info.value.retryable is True
    assert exc_info.value.outcome_unknown is False


def test_connect_is_retryable_but_lost_response_is_never_replayed() -> None:
    request = httpx.Request("POST", URLS[GENERIC_EVENT])

    async def connect_failed(
        _target: str,
        **_kwargs: Any,
    ) -> httpx.Response:
        raise httpx.ConnectError("connect failed", request=request)

    with pytest.raises(WebhookDeliveryError) as connect_error:
        asyncio.run(
            send_notification_webhook(
                provider=GENERIC_EVENT,
                webhook_url=URLS[GENERIC_EVENT],
                event="inteliscope.test",
                data={},
                text="test",
                post=connect_failed,
            )
        )
    assert connect_error.value.code == "notification_webhook_unavailable"
    assert connect_error.value.retryable is True
    assert connect_error.value.outcome_unknown is False

    async def read_failed(
        _target: str,
        **_kwargs: Any,
    ) -> httpx.Response:
        raise httpx.ReadError("response lost", request=request)

    with pytest.raises(WebhookDeliveryError) as read_error:
        asyncio.run(
            send_notification_webhook(
                provider=GENERIC_EVENT,
                webhook_url=URLS[GENERIC_EVENT],
                event="inteliscope.test",
                data={},
                text="test",
                post=read_failed,
            )
        )
    assert (
        read_error.value.code
        == "notification_webhook_outcome_unknown"
    )
    assert read_error.value.retryable is False
    assert read_error.value.outcome_unknown is True


def test_dns_failure_is_retryable_but_private_target_is_blocked(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    def failed_dns(
        _host: str,
        _port: int,
        *,
        type: int,
    ) -> list[Any]:
        assert type == socket.SOCK_STREAM
        raise OSError("resolver unavailable")

    monkeypatch.setattr(socket, "getaddrinfo", failed_dns)
    with pytest.raises(WebhookDeliveryError) as dns_error:
        asyncio.run(
            send_notification_webhook(
                provider=GENERIC_EVENT,
                webhook_url=URLS[GENERIC_EVENT],
                event="inteliscope.test",
                data={},
                text="test",
                timeout=0.05,
            )
        )
    assert dns_error.value.code == "notification_webhook_unavailable"
    assert dns_error.value.retryable is True
    assert dns_error.value.outcome_unknown is False

    with pytest.raises(WebhookDeliveryError) as blocked_error:
        asyncio.run(
            send_notification_webhook(
                provider=GENERIC_EVENT,
                webhook_url="https://127.0.0.1/hook",
                event="inteliscope.test",
                data={},
                text="test",
                timeout=0.05,
            )
        )
    assert blocked_error.value.code == "notification_webhook_target_blocked"
    assert blocked_error.value.retryable is False


def test_wecom_text_is_utf8_bounded_without_mentions() -> None:
    result, captured = _deliver(
        provider=WECOM,
        response=ACKS[WECOM],
        text="@all " + ("😀" * 1_000),
    )
    content = captured["body"]["text"]["content"]

    assert result.verification == "provider_accepted"
    assert "@all" not in content
    assert len(content.encode("utf-8")) <= 1_900
