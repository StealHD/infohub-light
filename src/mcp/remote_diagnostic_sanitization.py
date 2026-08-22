"""Pure sanitization for Remote MCP diagnostic evidence."""

from __future__ import annotations

import re
from datetime import datetime, timezone
from typing import Any

from ..security import (
    classification_copies,
    is_sensitive_credential_key,
    public_data_contains_credentials,
)
from ..services.source_health import sanitize_issue_message
from .remote_read_projection import safe_job_result_summary


_CODE_RULES = (
    (
        "auth_missing",
        ("unauthorized", "forbidden", "auth", "credential", "tokenmissing"),
    ),
    ("rate_limited", ("429", "ratelimit", "rate_limit", "quotaexceeded")),
    ("network_timeout", ("timeout", "timedout", "connection", "dns", "network")),
    (
        "invalid_source_config",
        ("sourceconfig", "invalidconfig", "validationerror"),
    ),
    ("upstream_rejected", ("httperror", "fetchfailed", "upstream", "rejected")),
)
_SAFE_CODE_RE = re.compile(r"[A-Za-z][A-Za-z0-9_.:-]{0,63}\Z")
_SECRET_SHAPED_CODE_RE = re.compile(
    r"(?:sk[-_]|gh[pousr]_|xox[a-z]-|AIza|xai-|gsk_|hf_|tp-)",
    re.IGNORECASE,
)
_SAFE_RESULT_IDENTIFIER_RE = re.compile(r"[A-Za-z0-9][A-Za-z0-9_.:-]{0,127}\Z")
_COMPACT_AUTH_SCHEME_RE = re.compile(
    r"(?<![A-Za-z0-9])(?:bearer|basic)[:._~+/=-]+[A-Za-z0-9._~+/=-]+",
    re.IGNORECASE,
)


def utc(value: datetime) -> datetime:
    if value.tzinfo is None:
        return value.replace(tzinfo=timezone.utc)
    return value.astimezone(timezone.utc)


def _compact(value: str) -> str:
    return re.sub(r"[^a-z0-9]+", "", value.casefold())


def _normalized_scalar_label(value: str) -> str:
    candidate = re.sub(r"([A-Z]+)([A-Z][a-z])", r"\1_\2", value)
    candidate = re.sub(r"([a-z0-9])([A-Z])", r"\1_\2", candidate)
    return re.sub(r"[^a-z0-9]+", "_", candidate.casefold()).strip("_")


def _contains_label_parts(parts: list[str], expected: tuple[str, ...]) -> bool:
    size = len(expected)
    return any(
        tuple(parts[index : index + size]) == expected
        for index in range(len(parts))
    )


def _public_scalar_contains_credentials(value: Any) -> bool:
    copies = classification_copies(str(value))
    if copies is None:
        return True
    for copy in copies:
        if _COMPACT_AUTH_SCHEME_RE.search(copy):
            return True
        if is_sensitive_credential_key(copy):
            return True
        parts = _normalized_scalar_label(copy).split("_")
        if any(part in {"credential", "credentials"} for part in parts):
            return True
        if len(parts) > 1 and parts[-1] == "key":
            return True
        if any(
            _contains_label_parts(parts, pattern)
            for pattern in (
                ("access", "key", "id"),
                ("private", "key"),
                ("key", "env"),
                ("api", "key", "env"),
            )
        ):
            return True
        if len(parts) >= 2 and parts[-2:] == ["connection", "string"]:
            return True
    return public_data_contains_credentials(value)


def safe_code(value: Any) -> str | None:
    code = str(value or "").strip()
    if (
        not _SAFE_CODE_RE.fullmatch(code)
        or _SECRET_SHAPED_CODE_RE.search(code)
        or _public_scalar_contains_credentials(code)
    ):
        return None
    return code


def mapped_category(value: Any) -> tuple[str | None, str | None]:
    code = safe_code(value)
    if code is None:
        return None, None
    normalized = _compact(code)
    for category, markers in _CODE_RULES:
        if any(_compact(marker) in normalized for marker in markers):
            return category, code
    return None, code


def message_category(value: Any) -> str | None:
    sanitized = sanitize_issue_message(str(value or ""))
    if not sanitized:
        return None
    normalized = _compact(sanitized)
    for category, markers in _CODE_RULES:
        if any(_compact(marker) in normalized for marker in markers):
            return category
    return None


def safe_name(value: Any, *, fallback: str) -> str:
    complete = " ".join(str(value or "").split())
    candidate = complete[:120]
    if (
        not candidate
        or "://" in complete
        or "?" in complete
        or _public_scalar_contains_credentials(complete)
    ):
        return fallback
    return candidate


def safe_timestamp(value: Any) -> str | None:
    try:
        return utc(datetime.fromisoformat(str(value))).isoformat()
    except (TypeError, ValueError):
        return None


def strict_result_summary(job: dict[str, Any] | None) -> dict[str, Any]:
    if not job:
        return {}
    selected = safe_job_result_summary(job)
    safe: dict[str, Any] = {}
    for field in ("fetched_count", "item_count", "issue_count"):
        value = selected.get(field)
        if type(value) is not int or value < 0:
            continue
        safe[field] = value
    if isinstance(selected.get("partial"), bool):
        safe["partial"] = selected["partial"]
    for field in ("snapshot_id", "run_status"):
        value = str(selected.get(field) or "").strip()
        if (
            value
            and _SAFE_RESULT_IDENTIFIER_RE.fullmatch(value)
            and not _public_scalar_contains_credentials(value)
        ):
            safe[field] = value
    return safe
