"""Managed environment-file projection for local OpenClaw setup."""

from __future__ import annotations

import os
import re
import tempfile
from pathlib import Path

from scripts.openclaw_setup_validation import SetupError


MANAGED_ENV_VALUES = (
    ("HORIZON_REMOTE_MCP_ENABLED", "true"),
    ("HORIZON_REMOTE_MCP_PUBLIC_URL", "{origin}/mcp"),
    ("HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED", "false"),
    ("HORIZON_REMOTE_MCP_SYSTEM_SETTINGS_WRITES_ENABLED", "false"),
    ("HORIZON_OPENCLAW_CHAT_ENABLED", "true"),
    ("HORIZON_OPENCLAW_GATEWAY_DEFAULT_URL", "{gateway_url}"),
)
MANAGED_COMMENT = "# OpenClaw local setup (managed by scripts/setup_openclaw_local.py)"
ENV_ASSIGNMENT = re.compile(r"^\s*(?P<key>[A-Za-z_][A-Za-z0-9_]*)\s*=")


def parse_env_values(text: str) -> dict[str, str]:
    values: dict[str, str] = {}
    for line in text.splitlines():
        match = ENV_ASSIGNMENT.match(line)
        if not match:
            continue
        key = match.group("key")
        value = line[match.end() :].strip()
        if len(value) >= 2 and value[0] == value[-1] and value[0] in {'"', "'"}:
            value = value[1:-1]
        values[key] = value
    return values


def default_origin(root: Path, env_text: str) -> str:
    values = parse_env_values(env_text)
    fallback_port = "8081" if (root / "docker-compose.light.yml").exists() else "8080"
    port = values.get("HORIZON_WEB_PORT") or fallback_port
    try:
        port_number = int(port)
    except ValueError as exc:
        raise SetupError(f"HORIZON_WEB_PORT must be a port number; found {port!r}.") from exc
    if port_number < 1 or port_number > 65535:
        raise SetupError(f"HORIZON_WEB_PORT is outside 1..65535: {port_number}.")
    return f"http://127.0.0.1:{port_number}"


def update_env_text(text: str, updates: dict[str, str]) -> str:
    output: list[str] = []
    seen: set[str] = set()
    for line in text.splitlines():
        match = ENV_ASSIGNMENT.match(line)
        key = match.group("key") if match else None
        if key not in updates:
            output.append(line)
            continue
        if key in seen:
            continue
        output.append(f"{key}={updates[key]}")
        seen.add(key)
    missing = [key for key in updates if key not in seen]
    if missing:
        if output and output[-1].strip():
            output.append("")
        if MANAGED_COMMENT not in output:
            output.append(MANAGED_COMMENT)
        output.extend(f"{key}={updates[key]}" for key in missing)
    return "\n".join(output).rstrip() + "\n"


def write_env_atomic(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    mode = path.stat().st_mode & 0o777 if path.exists() else 0o600
    handle = tempfile.NamedTemporaryFile(
        mode="w",
        encoding="utf-8",
        dir=path.parent,
        prefix=f".{path.name}.",
        delete=False,
    )
    temporary = Path(handle.name)
    try:
        with handle:
            handle.write(content)
            handle.flush()
            os.fsync(handle.fileno())
        os.chmod(temporary, mode)
        os.replace(temporary, path)
    finally:
        temporary.unlink(missing_ok=True)


def managed_updates(origin: str, gateway_url: str) -> dict[str, str]:
    return {
        key: template.format(origin=origin, gateway_url=gateway_url)
        for key, template in MANAGED_ENV_VALUES
    }
