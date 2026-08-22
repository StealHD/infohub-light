"""Gateway status, preference, and readiness helpers for local setup."""

from __future__ import annotations

import json
import time
import urllib.error
import urllib.request
from dataclasses import dataclass
from typing import Any

from scripts.openclaw_setup_validation import (
    TARGET_OPENCLAW_VERSION,
    SetupError,
    validate_gateway_url,
    version_tuple,
)


@dataclass(frozen=True)
class GatewayInfo:
    cli_version: str
    gateway_url: str
    running: bool


def parse_gateway_status(payload: dict[str, Any]) -> GatewayInfo:
    cli = payload.get("cli")
    gateway = payload.get("gateway")
    service = payload.get("service")
    if not isinstance(cli, dict) or not isinstance(gateway, dict):
        raise SetupError("OpenClaw gateway status JSON is missing cli/gateway data.")
    version = str(cli.get("version") or "")
    if version_tuple(version) < TARGET_OPENCLAW_VERSION:
        required = ".".join(str(part) for part in TARGET_OPENCLAW_VERSION)
        raise SetupError(
            f"OpenClaw {required} or newer is required; found {version or 'unknown'}."
        )
    links = gateway.get("controlUiLinks")
    gateway_url = links.get("wsUrl") if isinstance(links, dict) else None
    if not gateway_url:
        gateway_url = gateway.get("probeUrl")
    if not isinstance(gateway_url, str):
        raise SetupError("OpenClaw did not report a Gateway WebSocket URL.")
    runtime = service.get("runtime") if isinstance(service, dict) else None
    running = isinstance(runtime, dict) and runtime.get("status") == "running"
    return GatewayInfo(
        cli_version=version,
        gateway_url=validate_gateway_url(gateway_url),
        running=running,
    )


def merge_allowed_origins(current: Any, origin: str) -> list[str]:
    if current is None:
        entries: list[str] = []
    elif isinstance(current, list) and all(isinstance(item, str) for item in current):
        entries = list(current)
    else:
        raise SetupError(
            "gateway.controlUi.allowedOrigins must be a JSON array of strings."
        )
    if origin not in entries:
        entries.append(origin)
    return entries


def wait_for_ready(url: str, timeout_seconds: int) -> None:
    deadline = time.monotonic() + timeout_seconds
    last_error = "no response"
    while time.monotonic() < deadline:
        try:
            with urllib.request.urlopen(url, timeout=3) as response:
                payload = json.loads(response.read().decode("utf-8"))
                if response.status == 200 and payload.get("ok") is True:
                    return
                last_error = f"unexpected readiness payload: {payload!r}"
        except (OSError, ValueError, urllib.error.HTTPError) as exc:
            last_error = str(exc)
        time.sleep(2)
    raise SetupError(
        f"Inteliscope readiness did not pass within {timeout_seconds}s: {last_error}"
    )
