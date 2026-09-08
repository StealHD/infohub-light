"""Process-local correlation context shared by runtime and operation logging."""

from __future__ import annotations

import re
from contextvars import ContextVar, Token
from dataclasses import dataclass, replace
from typing import Any


_SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_STAGE_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,63}$")
_FORBIDDEN_IDENTIFIER_RE = re.compile(
    r"^(?:[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|ih_mcp_v1_.+|sk[-_].+|"
    r"(?i:bearer|basic)[-_].+)$"
)


@dataclass(frozen=True, slots=True)
class ObservabilityContext:
    request_id: str | None = None
    workspace_id: str | None = None
    actor_user_id: str | None = None
    job_id: str | None = None
    source_id: str | None = None
    subscription_id: str | None = None
    stage: str | None = None
    error_code: str | None = None


_CONTEXT: ContextVar[ObservabilityContext] = ContextVar(
    "inteliscope_observability_context",
    default=ObservabilityContext(),
)


def safe_observability_value(value: Any, field: str) -> str:
    candidate = str(value or "")
    if (
        not _SAFE_VALUE_RE.fullmatch(candidate)
        or _FORBIDDEN_IDENTIFIER_RE.fullmatch(candidate)
    ):
        raise ValueError(f"{field} must be a bounded opaque identifier")
    return candidate


def optional_observability_value(value: Any, field: str) -> str | None:
    return (
        None
        if value is None or value == ""
        else safe_observability_value(value, field)
    )


def safe_observability_stage(value: Any) -> str:
    candidate = str(value or "")
    if not _SAFE_STAGE_RE.fullmatch(candidate):
        raise ValueError("stage must be a bounded machine-readable name")
    return candidate


def current_observability_context() -> ObservabilityContext:
    return _CONTEXT.get()


def begin_observability_context(
    *,
    request_id: str | None = None,
    workspace_id: str | None = None,
    actor_user_id: str | None = None,
    job_id: str | None = None,
    source_id: str | None = None,
    subscription_id: str | None = None,
    stage: str | None = None,
    error_code: str | None = None,
) -> Token[ObservabilityContext]:
    return _CONTEXT.set(
        ObservabilityContext(
            request_id=optional_observability_value(request_id, "request_id"),
            workspace_id=optional_observability_value(
                workspace_id, "workspace_id"
            ),
            actor_user_id=optional_observability_value(
                actor_user_id, "actor_user_id"
            ),
            job_id=optional_observability_value(job_id, "job_id"),
            source_id=optional_observability_value(source_id, "source_id"),
            subscription_id=optional_observability_value(
                subscription_id, "subscription_id"
            ),
            stage=(
                None if stage in {None, ""} else safe_observability_stage(stage)
            ),
            error_code=optional_observability_value(
                error_code, "error_code"
            ),
        )
    )


def update_observability_context(
    *,
    workspace_id: str | None = None,
    actor_user_id: str | None = None,
    job_id: str | None = None,
    source_id: str | None = None,
    subscription_id: str | None = None,
    stage: str | None = None,
    error_code: str | None = None,
) -> None:
    context = _CONTEXT.get()
    updates: dict[str, str | None] = {}
    for field, value in (
        ("workspace_id", workspace_id),
        ("actor_user_id", actor_user_id),
        ("job_id", job_id),
        ("source_id", source_id),
        ("subscription_id", subscription_id),
        ("error_code", error_code),
    ):
        if value is not None:
            updates[field] = optional_observability_value(value, field)
    if stage is not None:
        updates["stage"] = (
            None if stage == "" else safe_observability_stage(stage)
        )
    _CONTEXT.set(replace(context, **updates))


def reset_observability_context(token: Token[ObservabilityContext]) -> None:
    _CONTEXT.reset(token)


def resolve_observability_field(field: str, value: Any = None) -> str | None:
    """None inherits; an empty string explicitly clears a correlation field."""
    resolved = getattr(current_observability_context(), field) if value is None else value
    if resolved is None or resolved == "":
        return None
    if not isinstance(resolved, str):
        raise ValueError("observability field must be a string")
    if field == "stage":
        return safe_observability_stage(resolved)
    return safe_observability_value(resolved, field)


def begin_child_observability_context(**fields: Any) -> Token[ObservabilityContext]:
    """Create a resettable child scope while retaining the request/Job identity."""
    values = {field: resolve_observability_field(field, value) for field, value in fields.items()}
    return _CONTEXT.set(replace(_CONTEXT.get(), **values))
