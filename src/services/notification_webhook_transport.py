"""Provider-aware Service Webhook rendering and bounded delivery verification."""

from __future__ import annotations

import base64
import hashlib
import hmac
import json
import re
import time
from dataclasses import dataclass
from typing import Any, Callable
from urllib.parse import parse_qsl, urlencode, urlsplit, urlunsplit

import httpx

from .network_policy import (
    NetworkResolutionError,
    UnsafeNetworkResponse,
    UnsafeNetworkTarget,
    post_public_http,
)


GENERIC_EVENT = "generic_event"
GENERIC_TEXT = "generic_text"
FEISHU_LARK_V2 = "feishu_lark_v2"
WECOM = "wecom"
DINGTALK = "dingtalk"
SLACK = "slack"
DISCORD = "discord"
LEGACY_AUTO = "legacy_auto"

WEBHOOK_PROVIDERS = (
    GENERIC_EVENT,
    GENERIC_TEXT,
    FEISHU_LARK_V2,
    WECOM,
    DINGTALK,
    SLACK,
    DISCORD,
)
STORED_WEBHOOK_PROVIDERS = frozenset((*WEBHOOK_PROVIDERS, LEGACY_AUTO))

_FEISHU_HOSTS = frozenset({"open.feishu.cn", "open.larksuite.com"})
_WECOM_HOSTS = frozenset({"qyapi.weixin.qq.com"})
_DINGTALK_HOSTS = frozenset({"oapi.dingtalk.com"})
_SLACK_HOSTS = frozenset({"hooks.slack.com", "hooks.slack-gov.com"})
_DISCORD_HOSTS = frozenset({"discord.com"})
_KNOWN_PROVIDER_HOSTS = frozenset(
    _FEISHU_HOSTS
    | _WECOM_HOSTS
    | _DINGTALK_HOSTS
    | _SLACK_HOSTS
    | _DISCORD_HOSTS
)
_FEISHU_PATH_RE = re.compile(
    r"^/open-apis/bot/v2/hook/[A-Za-z0-9_-]+$"
)
_SLACK_PATH_RE = re.compile(
    r"^/services/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+/[A-Za-z0-9_-]+$"
)
_DISCORD_PATH_RE = re.compile(
    r"^/api(?:/v(?:9|10))?/webhooks/[0-9]+/[A-Za-z0-9._-]+$"
)
_QUERY_SECRET_RE = re.compile(r"^[A-Za-z0-9._~-]{8,1024}$")
_ACK_LIMIT_BYTES = 4_096
_PLATFORM_PROVIDERS = frozenset(
    {FEISHU_LARK_V2, WECOM, DINGTALK, SLACK, DISCORD}
)

_PROVIDER_OPTIONS: tuple[dict[str, Any], ...] = (
    {
        "provider": GENERIC_EVENT,
        "label": "通用事件 JSON",
        "description": '发送 {"event","data"}，HTTP 2xx 仅表示接收端接受请求。',
        "url_hint": "https://example.com/webhook",
        "signing": "none",
        "verification_mode": "http_status",
    },
    {
        "provider": GENERIC_TEXT,
        "label": "通用文本 JSON",
        "description": '发送 {"text":"..."}，HTTP 2xx 仅表示接收端接受请求。',
        "url_hint": "https://example.com/webhook",
        "signing": "none",
        "verification_mode": "http_status",
    },
    {
        "provider": FEISHU_LARK_V2,
        "label": "飞书 / Lark V2",
        "description": "发送原生文本并校验平台业务响应，可选签名校验。",
        "url_hint": "https://open.feishu.cn/open-apis/bot/v2/hook/…",
        "signing": "optional",
        "verification_mode": "provider_response",
    },
    {
        "provider": WECOM,
        "label": "企业微信群机器人",
        "description": "发送原生文本并校验 errcode。",
        "url_hint": "https://qyapi.weixin.qq.com/cgi-bin/webhook/send?key=…",
        "signing": "none",
        "verification_mode": "provider_response",
    },
    {
        "provider": DINGTALK,
        "label": "钉钉自定义机器人",
        "description": "发送原生文本并校验 errcode，可选签名校验。",
        "url_hint": "https://oapi.dingtalk.com/robot/send?access_token=…",
        "signing": "optional",
        "verification_mode": "provider_response",
    },
    {
        "provider": SLACK,
        "label": "Slack / GovSlack",
        "description": "发送 Incoming Webhook 文本并校验 ok 响应。",
        "url_hint": "https://hooks.slack.com/services/…/…/…",
        "signing": "none",
        "verification_mode": "provider_response",
    },
    {
        "provider": DISCORD,
        "label": "Discord Incoming Webhook",
        "description": "发送禁用 mentions 的文本并校验返回消息 ID。",
        "url_hint": "https://discord.com/api/webhooks/…/…",
        "signing": "none",
        "verification_mode": "provider_response",
    },
)


class WebhookConfigurationError(ValueError):
    """A provider, URL, or signing value is invalid."""

    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


class WebhookDeliveryError(RuntimeError):
    """A bounded Webhook failure safe to map into Service error envelopes."""

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
class WebhookSendResult:
    provider: str
    verification: str


def webhook_provider_options() -> list[dict[str, Any]]:
    """Return safe UI metadata without endpoint credentials."""

    return [dict(option) for option in _PROVIDER_OPTIONS]


def normalize_stored_webhook_provider(value: Any) -> str:
    provider = str(value or LEGACY_AUTO).strip().lower()
    if provider not in STORED_WEBHOOK_PROVIDERS:
        raise WebhookConfigurationError(
            "invalid_webhook_provider",
            "webhook provider is not supported",
        )
    return provider


def resolve_webhook_provider(provider: Any, webhook_url: str) -> str:
    stored = normalize_stored_webhook_provider(provider)
    if stored != LEGACY_AUTO:
        return stored
    return (
        FEISHU_LARK_V2
        if is_feishu_lark_v2_url(webhook_url)
        else GENERIC_EVENT
    )


def webhook_verification_mode(provider: str) -> str:
    return (
        "provider_response"
        if provider in _PLATFORM_PROVIDERS
        else "http_status"
    )


def webhook_text_limit(provider: str) -> int:
    if provider == WECOM:
        # Keep even four-byte Unicode payloads below the provider's
        # byte-oriented text cap while leaving room for all 20 title rows.
        return 450
    if provider == DISCORD:
        # Discord echoes the created message when wait=true. Keep that
        # bounded JSON acknowledgement within our 4 KiB response cap.
        return 600
    return 3_500


def _parse_https_url(value: Any) -> tuple[str, Any, str]:
    candidate = str(value or "").strip()
    try:
        parsed = urlsplit(candidate)
        hostname = parsed.hostname
        hostname_ascii = (
            hostname.rstrip(".").encode("idna").decode("ascii").lower()
            if hostname
            else ""
        )
        parsed.port
    except (UnicodeError, ValueError):
        parsed = None
        hostname_ascii = ""
    if (
        len(candidate) > 4_096
        or any(marker in candidate for marker in ("\r", "\n", "\x00"))
        or parsed is None
        or parsed.scheme != "https"
        or not hostname_ascii
        or parsed.username is not None
        or parsed.password is not None
        or bool(parsed.fragment)
    ):
        raise WebhookConfigurationError(
            "invalid_notification_destination",
            "notification webhook must be a valid HTTPS URL",
        )
    return candidate, parsed, hostname_ascii


def _query_pairs(parsed: Any) -> list[tuple[str, str]]:
    try:
        pairs = parse_qsl(
            parsed.query,
            keep_blank_values=True,
            strict_parsing=True,
        )
    except ValueError as exc:
        raise WebhookConfigurationError(
            "invalid_webhook_url_for_provider",
            "webhook URL query is invalid for the selected provider",
        ) from exc
    names = [name for name, _value in pairs]
    if len(names) != len(set(names)):
        raise WebhookConfigurationError(
            "invalid_webhook_url_for_provider",
            "webhook URL contains duplicate query parameters",
        )
    return pairs


def _require_default_https_port(parsed: Any) -> None:
    if parsed.port not in {None, 443}:
        raise WebhookConfigurationError(
            "invalid_webhook_url_for_provider",
            "selected provider requires the default HTTPS port",
        )


def validate_webhook_url(
    value: Any,
    provider: Any,
    *,
    legacy_compat: bool = False,
) -> str:
    candidate, parsed, hostname = _parse_https_url(value)
    stored = normalize_stored_webhook_provider(provider)
    effective = resolve_webhook_provider(stored, candidate)

    if effective in {GENERIC_EVENT, GENERIC_TEXT}:
        if not legacy_compat and hostname in _KNOWN_PROVIDER_HOSTS:
            raise WebhookConfigurationError(
                "invalid_webhook_url_for_provider",
                "select the matching provider preset for this webhook URL",
            )
        return candidate

    _require_default_https_port(parsed)
    if "%" in parsed.path:
        raise WebhookConfigurationError(
            "invalid_webhook_url_for_provider",
            "provider webhook paths must not contain percent encoding",
        )
    pairs = _query_pairs(parsed)

    valid = False
    if effective == FEISHU_LARK_V2:
        valid = bool(
            hostname in _FEISHU_HOSTS
            and not pairs
            and _FEISHU_PATH_RE.fullmatch(parsed.path)
        )
    elif effective == WECOM:
        valid = bool(
            hostname in _WECOM_HOSTS
            and parsed.path == "/cgi-bin/webhook/send"
            and len(pairs) == 1
            and pairs[0][0] == "key"
            and _QUERY_SECRET_RE.fullmatch(pairs[0][1])
        )
    elif effective == DINGTALK:
        valid = bool(
            hostname in _DINGTALK_HOSTS
            and parsed.path == "/robot/send"
            and len(pairs) == 1
            and pairs[0][0] == "access_token"
            and _QUERY_SECRET_RE.fullmatch(pairs[0][1])
        )
    elif effective == SLACK:
        valid = bool(
            hostname in _SLACK_HOSTS
            and not pairs
            and _SLACK_PATH_RE.fullmatch(parsed.path)
        )
    elif effective == DISCORD:
        query = dict(pairs)
        valid = bool(
            hostname in _DISCORD_HOSTS
            and _DISCORD_PATH_RE.fullmatch(parsed.path)
            and set(query) <= {"wait", "thread_id"}
            and query.get("wait", "true").lower() == "true"
            and (
                "thread_id" not in query
                or re.fullmatch(r"[0-9]+", query["thread_id"])
            )
        )
    if not valid:
        raise WebhookConfigurationError(
            "invalid_webhook_url_for_provider",
            "webhook URL does not match the selected provider",
        )
    return candidate


def is_feishu_lark_v2_url(value: str) -> bool:
    try:
        candidate, parsed, hostname = _parse_https_url(value)
        del candidate
        return bool(
            hostname in _FEISHU_HOSTS
            and parsed.port in {None, 443}
            and not parsed.query
            and _FEISHU_PATH_RE.fullmatch(parsed.path)
        )
    except WebhookConfigurationError:
        return False


def validate_signing_secret(value: Any) -> str:
    secret = str(value or "")
    if (
        not secret
        or len(secret) > 4_096
        or any(marker in secret for marker in ("\r", "\n", "\x00"))
    ):
        raise WebhookConfigurationError(
            "invalid_webhook_signing_secret",
            "webhook signing secret is invalid",
        )
    return secret


def _bounded_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    if len(text) <= limit:
        return text
    return text[: max(0, limit - 1)].rstrip() + "…"


def _bounded_utf8_text(value: Any, limit: int) -> str:
    text = str(value or "").strip()
    encoded = text.encode("utf-8")
    if len(encoded) <= limit:
        return text
    suffix = "…"
    budget = max(0, limit - len(suffix.encode("utf-8")))
    truncated = encoded[:budget]
    while truncated:
        try:
            return truncated.decode("utf-8").rstrip() + suffix
        except UnicodeDecodeError:
            truncated = truncated[:-1]
    return suffix if limit >= len(suffix.encode("utf-8")) else ""


def _provider_text(value: Any, provider: str) -> str:
    text = _bounded_text(value, webhook_text_limit(provider))
    if provider == FEISHU_LARK_V2:
        return text.translate(str.maketrans({"<": "＜", ">": "＞"}))
    if provider == SLACK:
        return (
            text.replace("&", "&amp;")
            .replace("<", "&lt;")
            .replace(">", "&gt;")
        )
    if provider in {WECOM, DINGTALK, DISCORD}:
        text = text.replace("@", "＠")
        if provider == WECOM:
            return _bounded_utf8_text(text, 1_900)
        return text
    return text


def _feishu_signature(secret: str, timestamp: int) -> str:
    key = f"{timestamp}\n{secret}".encode("utf-8")
    digest = hmac.new(key, b"", hashlib.sha256).digest()
    return base64.b64encode(digest).decode("ascii")


def _dingtalk_signature(secret: str, timestamp_ms: int) -> str:
    message = f"{timestamp_ms}\n{secret}".encode("utf-8")
    digest = hmac.new(
        secret.encode("utf-8"),
        message,
        hashlib.sha256,
    ).digest()
    return base64.b64encode(digest).decode("ascii")


def _dingtalk_signed_url(
    webhook_url: str,
    *,
    signing_secret: str,
    timestamp_ms: int,
) -> str:
    parsed = urlsplit(webhook_url)
    pairs = parse_qsl(parsed.query, keep_blank_values=True)
    pairs.extend(
        (
            ("timestamp", str(timestamp_ms)),
            (
                "sign",
                _dingtalk_signature(signing_secret, timestamp_ms),
            ),
        )
    )
    return urlunsplit(
        (
            parsed.scheme,
            parsed.netloc,
            parsed.path,
            urlencode(pairs),
            "",
        )
    )


def _request_payload(
    *,
    provider: str,
    event: str,
    data: dict[str, Any],
    text: str,
    signing_secret: str | None,
    webhook_url: str,
    now_seconds: int,
) -> tuple[str, bytes]:
    rendered_text = _provider_text(text, provider)
    target_url = webhook_url
    if provider == GENERIC_EVENT:
        body: dict[str, Any] = {"event": event, "data": data}
    elif provider in {GENERIC_TEXT, SLACK}:
        body = {"text": rendered_text}
    elif provider == FEISHU_LARK_V2:
        body = {
            "msg_type": "text",
            "content": {"text": rendered_text},
        }
        if signing_secret:
            body["timestamp"] = str(now_seconds)
            body["sign"] = _feishu_signature(
                signing_secret,
                now_seconds,
            )
    elif provider == WECOM:
        body = {
            "msgtype": "text",
            "text": {"content": rendered_text},
        }
    elif provider == DINGTALK:
        body = {
            "msgtype": "text",
            "text": {"content": rendered_text},
            "at": {
                "atMobiles": [],
                "atUserIds": [],
                "isAtAll": False,
            },
        }
        if signing_secret:
            target_url = _dingtalk_signed_url(
                webhook_url,
                signing_secret=signing_secret,
                timestamp_ms=now_seconds * 1_000,
            )
    elif provider == DISCORD:
        parsed = urlsplit(webhook_url)
        query = dict(parse_qsl(parsed.query, keep_blank_values=True))
        query["wait"] = "true"
        target_url = urlunsplit(
            (
                parsed.scheme,
                parsed.netloc,
                parsed.path,
                urlencode(query),
                "",
            )
        )
        body = {
            "content": rendered_text,
            "flags": 4,
            "allowed_mentions": {
                "parse": [],
                "users": [],
                "roles": [],
            },
        }
    else:  # guarded by normalize_stored_webhook_provider
        raise WebhookConfigurationError(
            "invalid_webhook_provider",
            "webhook provider is not supported",
        )
    encoded = json.dumps(
        body,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
        default=str,
    ).encode("utf-8")
    return target_url, encoded


def _json_ack(response: httpx.Response) -> dict[str, Any] | None:
    try:
        decoded = response.content.decode("utf-8")
        parsed = json.loads(decoded)
    except (UnicodeDecodeError, TypeError, ValueError):
        return None
    return parsed if isinstance(parsed, dict) else None


def _zero(value: Any) -> bool:
    return (type(value) is int and value == 0) or value == "0"


def _verify_provider_ack(
    provider: str,
    response: httpx.Response,
) -> None:
    if int(response.status_code) != 200:
        raise WebhookDeliveryError(
            "notification_webhook_response_invalid",
            "notification webhook returned an unexpected success status",
            outcome_unknown=True,
        )
    if provider == SLACK:
        try:
            ack = response.content.decode("utf-8")
        except UnicodeDecodeError as exc:
            raise WebhookDeliveryError(
                "notification_webhook_response_invalid",
                "notification webhook response could not be verified",
                outcome_unknown=True,
            ) from exc
        if ack == "ok":
            return
        if ack:
            raise WebhookDeliveryError(
                "notification_webhook_response_invalid",
                "notification webhook response could not be verified",
                outcome_unknown=True,
            )
        raise WebhookDeliveryError(
            "notification_webhook_response_invalid",
            "notification webhook response could not be verified",
            outcome_unknown=True,
        )

    ack = _json_ack(response)
    if ack is None:
        raise WebhookDeliveryError(
            "notification_webhook_response_invalid",
            "notification webhook response could not be verified",
            outcome_unknown=True,
        )
    if provider == FEISHU_LARK_V2:
        code = ack.get("code", ack.get("StatusCode"))
        if _zero(code):
            return
        if type(code) is int or isinstance(code, str):
            raise WebhookDeliveryError(
                "notification_webhook_provider_rejected",
                "notification provider rejected the request",
            )
    elif provider in {WECOM, DINGTALK}:
        code = ack.get("errcode")
        if _zero(code):
            return
        if type(code) is int or isinstance(code, str):
            raise WebhookDeliveryError(
                "notification_webhook_provider_rejected",
                "notification provider rejected the request",
            )
    elif provider == DISCORD:
        message_id = ack.get("id")
        if (
            isinstance(message_id, str)
            and re.fullmatch(r"[0-9]+", message_id)
        ):
            return
    raise WebhookDeliveryError(
        "notification_webhook_response_invalid",
        "notification webhook response could not be verified",
        outcome_unknown=True,
    )


async def send_notification_webhook(
    *,
    provider: Any,
    webhook_url: str,
    event: str,
    data: dict[str, Any],
    text: str,
    signing_secret: str | None = None,
    timeout: float = 5.0,
    now: Callable[[], float] = time.time,
    transport_factory: Callable[[], httpx.AsyncBaseTransport] | None = None,
    post: Callable[..., Any] = post_public_http,
) -> WebhookSendResult:
    stored = normalize_stored_webhook_provider(provider)
    effective = resolve_webhook_provider(stored, webhook_url)
    validated_url = validate_webhook_url(
        webhook_url,
        stored,
        legacy_compat=stored == LEGACY_AUTO,
    )
    if signing_secret is not None:
        signing_secret = validate_signing_secret(signing_secret)
        if effective not in {FEISHU_LARK_V2, DINGTALK}:
            raise WebhookConfigurationError(
                "webhook_signing_not_supported",
                "selected webhook provider does not support signing",
            )
    target_url, content = _request_payload(
        provider=effective,
        event=str(event),
        data=dict(data),
        text=text,
        signing_secret=signing_secret,
        webhook_url=validated_url,
        now_seconds=int(now()),
    )
    try:
        response = await post(
            target_url,
            content=content,
            headers={"Content-Type": "application/json; charset=utf-8"},
            timeout=timeout,
            max_response_bytes=_ACK_LIMIT_BYTES,
            transport_factory=transport_factory,
            response_body_mode=(
                "bounded"
                if effective in _PLATFORM_PROVIDERS
                else "discard"
            ),
        )
    except NetworkResolutionError as exc:
        raise WebhookDeliveryError(
            "notification_webhook_unavailable",
            "notification webhook is unavailable",
            retryable=True,
        ) from exc
    except UnsafeNetworkTarget as exc:
        raise WebhookDeliveryError(
            "notification_webhook_target_blocked",
            "notification webhook must resolve only to the public network",
            status_code=400,
        ) from exc
    except UnsafeNetworkResponse as exc:
        raise WebhookDeliveryError(
            "notification_webhook_response_invalid",
            "notification webhook response could not be verified",
            outcome_unknown=True,
        ) from exc
    except (
        httpx.ConnectError,
        httpx.ConnectTimeout,
        httpx.PoolTimeout,
    ) as exc:
        raise WebhookDeliveryError(
            "notification_webhook_unavailable",
            "notification webhook is unavailable",
            retryable=True,
        ) from exc
    except httpx.TransportError as exc:
        raise WebhookDeliveryError(
            "notification_webhook_outcome_unknown",
            "notification webhook outcome is unknown",
            outcome_unknown=True,
        ) from exc

    status = int(response.status_code)
    if status == 429:
        raise WebhookDeliveryError(
            "notification_webhook_rate_limited",
            "notification webhook rate limited the request",
            retryable=True,
        )
    if status in {408, 425} or status >= 500:
        raise WebhookDeliveryError(
            "notification_webhook_outcome_unknown",
            "notification webhook outcome is unknown",
            outcome_unknown=True,
        )
    if not 200 <= status < 300:
        raise WebhookDeliveryError(
            "notification_webhook_provider_rejected",
            "notification provider rejected the request",
        )
    if effective in _PLATFORM_PROVIDERS:
        content_encoding = response.headers.get(
            "content-encoding",
            "",
        ).strip().lower()
        if content_encoding not in {"", "identity"}:
            raise WebhookDeliveryError(
                "notification_webhook_response_invalid",
                "notification webhook response could not be verified",
                outcome_unknown=True,
            )
        _verify_provider_ack(effective, response)
        verification = "provider_accepted"
    else:
        verification = "http_accepted"
    return WebhookSendResult(
        provider=effective,
        verification=verification,
    )
