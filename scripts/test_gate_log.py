"""Private-log sanitization helpers shared by the deterministic test gate."""

from __future__ import annotations

import os
import re
from pathlib import Path
from typing import Any, TextIO

from src.logging_utils import redact_log_text


SECRET_NAME_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
_UNCLOSED_SQLITE_CONNECTION_WARNING = re.compile(
    r"ResourceWarning:\s+unclosed (?:database in )?<sqlite3\.Connection object"
)


def sensitive_values(environment: dict[str, str]) -> list[str]:
    return sorted(
        {
            value
            for name, value in environment.items()
            if value
            and len(value) >= 4
            and any(marker in name.upper() for marker in SECRET_NAME_PARTS)
        },
        key=len,
        reverse=True,
    )


def redact_gate_text(text: str, secret_values: list[str]) -> str:
    for value in secret_values:
        text = text.replace(value, "[REDACTED]")
    text = re.sub(
        r"(?i)\b([A-Z0-9_]*(?:KEY|TOKEN|SECRET|PASSWORD|CREDENTIAL)[A-Z0-9_]*)\s*[:=]\s*[^\s,;]+",
        r"\1=[REDACTED]",
        text,
    )
    return redact_log_text(text)


def sanitize_gate_log(
    source: TextIO,
    log_path: Path,
    secret_values: list[str],
) -> None:
    descriptor = os.open(log_path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(descriptor, "w", encoding="utf-8") as target:
        for line in source:
            target.write(redact_gate_text(line, secret_values))
    os.chmod(log_path, 0o600)


def unclosed_sqlite_connection_warnings(log_path: Path) -> int:
    count = 0
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for index, line in enumerate(handle):
            if index == 0 and line.startswith("$ "):
                continue
            count += len(_UNCLOSED_SQLITE_CONNECTION_WARNING.findall(line))
    return count


def sqlite_warning_gate_failure(
    command_result: dict[str, Any],
    warning_count: int,
) -> dict[str, Any]:
    return {
        "status": "failed",
        "first_failure": {
            "command": command_result["command"],
            "command_id": command_result["command_id"],
            "duration": command_result["duration"],
            "exit_code": 1,
            "id": "unclosed_sqlite_connection",
            "excerpt": (
                f"detected {warning_count} unclosed SQLite connection "
                "ResourceWarning(s)"
            ),
        },
    }
