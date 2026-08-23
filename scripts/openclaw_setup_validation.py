"""Input validation shared by the local OpenClaw setup workflow."""

from __future__ import annotations

import re
from urllib.parse import urlsplit


TARGET_OPENCLAW_VERSION = (2026, 7, 1)


class SetupError(RuntimeError):
    """Safe, actionable local setup failure."""


def version_tuple(value: str) -> tuple[int, ...]:
    numbers = tuple(int(part) for part in re.findall(r"\d+", value)[:3])
    if len(numbers) < 3:
        raise SetupError(f"cannot parse OpenClaw version: {value!r}")
    return numbers


def validate_gateway_url(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"ws", "wss"} or not parsed.hostname:
        raise SetupError("Gateway URL must use ws:// or wss://.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SetupError(
            "Gateway URL must not contain credentials, query parameters, or fragments."
        )
    host = parsed.hostname.lower()
    if parsed.scheme == "ws" and host not in {"127.0.0.1", "localhost"}:
        raise SetupError("A plain ws:// Gateway must use 127.0.0.1 or localhost.")
    path = "" if parsed.path in {"", "/"} else parsed.path.rstrip("/")
    return f"{parsed.scheme}://{parsed.netloc}{path}"


def validate_origin(value: str) -> str:
    parsed = urlsplit(value.strip())
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise SetupError("Origin must be an absolute http:// or https:// URL.")
    if parsed.username or parsed.password or parsed.query or parsed.fragment:
        raise SetupError(
            "Origin must not contain credentials, query parameters, or fragments."
        )
    if parsed.path not in {"", "/"}:
        raise SetupError("Origin must not include a path.")
    if parsed.scheme == "http" and parsed.hostname.lower() not in {
        "127.0.0.1",
        "localhost",
    }:
        raise SetupError("A non-loopback Inteliscope Origin must use HTTPS.")
    return f"{parsed.scheme}://{parsed.netloc}"
