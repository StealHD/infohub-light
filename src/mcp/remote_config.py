"""Configuration for the opt-in Remote MCP endpoint."""

from __future__ import annotations

import ipaddress
import os
from dataclasses import dataclass
from urllib.parse import urlsplit


def _is_loopback(hostname: str) -> bool:
    if hostname.lower() == "localhost":
        return True
    try:
        return ipaddress.ip_address(hostname).is_loopback
    except ValueError:
        return False


def _boolean_env(name: str) -> bool:
    value = os.getenv(name, "false")
    if value not in {"true", "false"}:
        raise ValueError(f"{name} must be true or false")
    return value == "true"


@dataclass(frozen=True, slots=True)
class RemoteMCPSettings:
    enabled: bool
    public_url: str
    subscription_writes_enabled: bool = False

    @classmethod
    def from_env(cls) -> "RemoteMCPSettings":
        enabled = _boolean_env("HORIZON_REMOTE_MCP_ENABLED")
        subscription_writes_enabled = _boolean_env(
            "HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED"
        )
        public_url = os.getenv("HORIZON_REMOTE_MCP_PUBLIC_URL", "").strip()
        settings = cls(
            enabled=enabled,
            public_url=public_url,
            subscription_writes_enabled=subscription_writes_enabled,
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        if self.subscription_writes_enabled and not self.enabled:
            raise ValueError("subscription writes require Remote MCP to be enabled")
        if not self.enabled:
            return
        if not self.public_url:
            raise ValueError(
                "HORIZON_REMOTE_MCP_PUBLIC_URL is required when Remote MCP is enabled"
            )
        parsed = urlsplit(self.public_url)
        if (
            parsed.scheme not in {"http", "https"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.path != "/mcp"
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "HORIZON_REMOTE_MCP_PUBLIC_URL must be an absolute URL ending at /mcp"
            )
        if not _is_loopback(parsed.hostname) and parsed.scheme != "https":
            raise ValueError("non-loopback Remote MCP URLs must use HTTPS")

    @property
    def host(self) -> str:
        return urlsplit(self.public_url).netloc

    @property
    def origin(self) -> str:
        parsed = urlsplit(self.public_url)
        return f"{parsed.scheme}://{parsed.netloc}"


@dataclass(frozen=True, slots=True)
class OpenClawChatSettings:
    enabled: bool
    default_gateway_url: str
    protocol_version: int = 4
    target_version: str = "2026.7.1"

    @classmethod
    def from_env(cls) -> "OpenClawChatSettings":
        settings = cls(
            enabled=_boolean_env("HORIZON_OPENCLAW_CHAT_ENABLED"),
            default_gateway_url=os.getenv(
                "HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL",
                "ws://127.0.0.1:18789",
            ).strip(),
        )
        settings.validate()
        return settings

    def validate(self) -> None:
        parsed = urlsplit(self.default_gateway_url)
        if (
            parsed.scheme not in {"ws", "wss"}
            or not parsed.hostname
            or parsed.username is not None
            or parsed.password is not None
            or parsed.query
            or parsed.fragment
        ):
            raise ValueError(
                "HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL must be a credential-free WS URL"
            )
        if parsed.scheme == "ws" and parsed.hostname.lower() not in {
            "127.0.0.1",
            "localhost",
        }:
            raise ValueError(
                "OpenClaw Gateway WS URLs must use 127.0.0.1 or localhost"
            )

    def public_config(self) -> dict[str, bool | int | str]:
        return {
            "enabled": self.enabled,
            "default_gateway_url": self.default_gateway_url,
            "protocol_version": self.protocol_version,
            "target_version": self.target_version,
        }
