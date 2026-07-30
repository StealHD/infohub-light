"""Strict structured operation events and bounded user-scoped queries."""

from __future__ import annotations

import json
import logging
import os
import re
import stat
import uuid
from contextvars import Token
from datetime import datetime, timedelta, timezone
from pathlib import Path
from typing import Any, Iterator, Literal

from ..logging_utils import (
    OPERATION_LOGGER_NAME,
    new_operation_write_acknowledgement,
    operation_write_acknowledged,
)
from ..observability_context import (
    ObservabilityContext,
    begin_observability_context,
    current_observability_context,
    optional_observability_value,
    reset_observability_context,
    safe_observability_stage,
    safe_observability_value,
    update_observability_context,
)


OperationCategory = Literal[
    "request",
    "auth",
    "account",
    "source",
    "subscription",
    "schedule",
    "secret",
    "notification",
    "agent",
    "job",
    "acquisition",
    "storage",
]
OperationOutcome = Literal[
    "ok",
    "queued",
    "running",
    "succeeded",
    "partial",
    "failed",
    "denied",
    "cancelled",
    "retried",
    "skipped",
    "unavailable",
]
OperationLevel = Literal["info", "warning", "error"]

OPERATION_CATEGORIES = frozenset(
    {
        "request",
        "auth",
        "account",
        "source",
        "subscription",
        "schedule",
        "secret",
        "notification",
        "agent",
        "job",
        "acquisition",
        "storage",
    }
)
OPERATION_OUTCOMES = frozenset(
    {
        "ok",
        "queued",
        "running",
        "succeeded",
        "partial",
        "failed",
        "denied",
        "cancelled",
        "retried",
        "skipped",
        "unavailable",
    }
)
OPERATION_LEVELS = {"info": 20, "warning": 30, "error": 40}
MAX_OPERATION_SCAN_RECORDS = 20_000
_LOGGER = logging.getLogger(OPERATION_LOGGER_NAME)
_RUNTIME_LOGGER = logging.getLogger("inteliscope.operation_runtime")
_SAFE_VALUE_RE = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_SAFE_ACTION_RE = re.compile(r"^[a-z][a-z0-9_.-]{0,95}$")
_SAFE_FIELD_RE = re.compile(r"^[a-z][a-z0-9_]{0,63}$")
_SAFE_ROUTE_RE = re.compile(r"^/[A-Za-z0-9_./{}:-]{0,159}$")
_FORBIDDEN_IDENTIFIER_RE = re.compile(
    r"^(?:[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+|ih_mcp_v1_.+|sk[-_].+|"
    r"(?i:bearer|basic)[-_].+)$"
)
_OPERATION_FILE_RE = re.compile(
    r"^operations-(?:api|worker|scheduler|cli)"
    r"\.jsonl(?:\.\d{4}-\d{2}-\d{2})?$"
)


def begin_request_context(request_id: str) -> Token[ObservabilityContext]:
    return begin_observability_context(request_id=request_id)


def end_request_context(token: Token[ObservabilityContext]) -> None:
    reset_observability_context(token)


def bind_operation_actor(*, workspace_id: str, user_id: str) -> None:
    update_observability_context(
        workspace_id=workspace_id,
        actor_user_id=user_id,
    )


def current_request_id() -> str | None:
    return current_observability_context().request_id


def _safe_value(value: Any, field: str) -> str:
    return safe_observability_value(value, field)


def _optional_safe_value(value: Any, field: str) -> str | None:
    return optional_observability_value(value, field)


def _utc_iso(value: datetime | None = None) -> str:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc).isoformat(
        timespec="milliseconds"
    ).replace("+00:00", "Z")


def _parse_timestamp(value: Any) -> datetime | None:
    if not isinstance(value, str) or len(value) > 40:
        return None
    try:
        parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    except ValueError:
        return None
    if parsed.tzinfo is None:
        return None
    return parsed.astimezone(timezone.utc)


def emit_operation_event(
    *,
    category: OperationCategory,
    action: str,
    outcome: OperationOutcome,
    level: OperationLevel = "info",
    workspace_id: str | None = None,
    actor_user_id: str | None = None,
    subject_user_id: str | None = None,
    request_id: str | None = None,
    job_id: str | None = None,
    source_id: str | None = None,
    subscription_id: str | None = None,
    stage: str | None = None,
    error_code: str | None = None,
    error_fingerprint: str | None = None,
    duration_ms: int | None = None,
    changed_fields: list[str] | tuple[str, ...] | None = None,
    counts: dict[str, int] | None = None,
    route: str | None = None,
    method: str | None = None,
    status_code: int | None = None,
) -> dict[str, Any]:
    """Emit one value-free event after its business transition is committed."""

    if category not in OPERATION_CATEGORIES:
        raise ValueError("operation category is invalid")
    if outcome not in OPERATION_OUTCOMES:
        raise ValueError("operation outcome is invalid")
    if level not in OPERATION_LEVELS:
        raise ValueError("operation level is invalid")
    if not _SAFE_ACTION_RE.fullmatch(action):
        raise ValueError("operation action is invalid")
    context = current_observability_context()
    resolved_workspace = workspace_id or context.workspace_id
    resolved_actor = actor_user_id or context.actor_user_id
    resolved_request = request_id or context.request_id
    event: dict[str, Any] = {
        "schema_version": 1,
        "event_id": f"evt_{uuid.uuid4().hex}",
        "timestamp": _utc_iso(),
        "level": level,
        "category": category,
        "action": action,
        "outcome": outcome,
    }
    optional_ids = {
        "workspace_id": resolved_workspace,
        "actor_user_id": resolved_actor,
        "subject_user_id": subject_user_id,
        "request_id": resolved_request,
        "job_id": job_id,
        "source_id": source_id,
        "subscription_id": subscription_id,
        "error_code": error_code,
        "error_fingerprint": error_fingerprint,
    }
    for field, value in optional_ids.items():
        safe = _optional_safe_value(value, field)
        if safe is not None:
            event[field] = safe
    resolved_stage = stage or context.stage
    if resolved_stage is not None:
        event["stage"] = safe_observability_stage(resolved_stage)
    if duration_ms is not None:
        if isinstance(duration_ms, bool) or not 0 <= int(duration_ms) <= 86_400_000:
            raise ValueError("duration_ms is invalid")
        event["duration_ms"] = int(duration_ms)
    if changed_fields is not None:
        normalized = sorted(
            {
                str(field)
                for field in changed_fields
                if _SAFE_FIELD_RE.fullmatch(str(field))
            }
        )
        if len(normalized) != len(set(changed_fields)) or len(normalized) > 32:
            raise ValueError("changed_fields is invalid")
        event["changed_fields"] = normalized
    if counts is not None:
        normalized_counts: dict[str, int] = {}
        for key, value in counts.items():
            if (
                not _SAFE_FIELD_RE.fullmatch(str(key))
                or isinstance(value, bool)
                or not 0 <= int(value) <= 1_000_000_000
            ):
                raise ValueError("counts is invalid")
            normalized_counts[str(key)] = int(value)
        if len(normalized_counts) > 16:
            raise ValueError("counts is invalid")
        event["counts"] = dict(sorted(normalized_counts.items()))
    if route is not None:
        if not _SAFE_ROUTE_RE.fullmatch(route):
            raise ValueError("route template is invalid")
        event["route"] = route
    if method is not None:
        normalized_method = str(method).upper()
        if normalized_method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            raise ValueError("operation method is invalid")
        event["method"] = normalized_method
    if status_code is not None:
        if isinstance(status_code, bool) or not 100 <= int(status_code) <= 599:
            raise ValueError("status_code is invalid")
        event["status_code"] = int(status_code)
    acknowledgement = new_operation_write_acknowledgement()
    _LOGGER.log(
        OPERATION_LEVELS[level],
        "operation_event %s.%s outcome=%s event_id=%s",
        category,
        action,
        outcome,
        event["event_id"],
        extra={
            "operation_event": event,
            "_inteliscope_operation_write_ack": acknowledgement,
        },
    )
    if not operation_write_acknowledged(acknowledgement):
        raise OSError("structured operation event was not durably written")
    return event


def safe_emit_operation_event(**kwargs: Any) -> bool:
    """Best-effort wrapper: observability must not change a business outcome."""

    try:
        emit_operation_event(**kwargs)
    except Exception:
        try:
            _RUNTIME_LOGGER.error("structured operation event rejected")
        except Exception:
            pass
        return False
    return True


def _reverse_lines(path: Path) -> Iterator[str]:
    descriptor = os.open(
        path,
        os.O_RDONLY | getattr(os, "O_NOFOLLOW", 0),
    )
    try:
        if not stat.S_ISREG(os.fstat(descriptor).st_mode):
            raise OSError("operation log is not a regular file")
        stream = os.fdopen(descriptor, "rb")
    except Exception:
        os.close(descriptor)
        raise
    with stream:
        stream.seek(0, 2)
        position = stream.tell()
        buffer = b""
        while position > 0:
            size = min(64 * 1024, position)
            position -= size
            stream.seek(position)
            buffer = stream.read(size) + buffer
            parts = buffer.split(b"\n")
            buffer = parts[0]
            for line in reversed(parts[1:]):
                if line:
                    yield line.decode("utf-8", errors="replace")
        if buffer:
            yield buffer.decode("utf-8", errors="replace")


def _safe_public_event(
    event: dict[str, Any],
    *,
    timestamp: datetime,
) -> dict[str, Any] | None:
    event_id = str(event.get("event_id") or "")
    if (
        not _SAFE_VALUE_RE.fullmatch(event_id)
        or _FORBIDDEN_IDENTIFIER_RE.fullmatch(event_id)
        or event.get("level") not in OPERATION_LEVELS
        or event.get("service") not in {"api", "worker", "scheduler", "cli"}
        or event.get("category") not in OPERATION_CATEGORIES
        or not _SAFE_ACTION_RE.fullmatch(str(event.get("action") or ""))
        or event.get("outcome") not in OPERATION_OUTCOMES
    ):
        return None
    public: dict[str, Any] = {
        "timestamp": _utc_iso(timestamp),
        **{
            field: event[field]
            for field in (
                "event_id",
                "level",
                "service",
                "category",
                "action",
                "outcome",
            )
        },
    }
    for field in (
        "request_id",
        "job_id",
        "source_id",
        "subscription_id",
        "error_code",
        "error_fingerprint",
    ):
        value = event.get(field)
        if value is not None:
            candidate = str(value)
            if (
                not _SAFE_VALUE_RE.fullmatch(candidate)
                or _FORBIDDEN_IDENTIFIER_RE.fullmatch(candidate)
            ):
                return None
            public[field] = candidate
    stage = event.get("stage")
    if stage is not None:
        if not isinstance(stage, str):
            return None
        try:
            public["stage"] = safe_observability_stage(stage)
        except ValueError:
            return None
    duration_ms = event.get("duration_ms")
    if duration_ms is not None:
        if (
            isinstance(duration_ms, bool)
            or not isinstance(duration_ms, int)
            or not 0 <= duration_ms <= 86_400_000
        ):
            return None
        public["duration_ms"] = duration_ms
    changed_fields = event.get("changed_fields")
    if changed_fields is not None:
        if (
            not isinstance(changed_fields, list)
            or len(changed_fields) > 32
            or any(
                not isinstance(field, str) or not _SAFE_FIELD_RE.fullmatch(field)
                for field in changed_fields
            )
        ):
            return None
        public["changed_fields"] = sorted(set(changed_fields))
    counts = event.get("counts")
    if counts is not None:
        if not isinstance(counts, dict) or len(counts) > 16:
            return None
        normalized_counts: dict[str, int] = {}
        for key, value in counts.items():
            if (
                not isinstance(key, str)
                or not _SAFE_FIELD_RE.fullmatch(key)
                or isinstance(value, bool)
                or not isinstance(value, int)
                or not 0 <= value <= 1_000_000_000
            ):
                return None
            normalized_counts[key] = value
        public["counts"] = dict(sorted(normalized_counts.items()))
    route = event.get("route")
    if route is not None:
        if not isinstance(route, str) or not _SAFE_ROUTE_RE.fullmatch(route):
            return None
        public["route"] = route
    method = event.get("method")
    if method is not None:
        if method not in {"GET", "POST", "PUT", "PATCH", "DELETE"}:
            return None
        public["method"] = method
    status_code = event.get("status_code")
    if status_code is not None:
        if (
            isinstance(status_code, bool)
            or not isinstance(status_code, int)
            or not 100 <= status_code <= 599
        ):
            return None
        public["status_code"] = status_code
    return public


class OperationLogQueryService:
    """Read managed event files without exposing file or tenant internals."""

    def __init__(
        self,
        log_dir: str | Path = "logs",
        *,
        max_scan_records: int = MAX_OPERATION_SCAN_RECORDS,
    ) -> None:
        self.log_dir = Path(log_dir)
        self.max_scan_records = int(max_scan_records)

    def query(
        self,
        *,
        workspace_id: str,
        user_id: str,
        scope: Literal["self", "workspace"] = "self",
        lookback_hours: int = 24,
        category: OperationCategory | None = None,
        outcome: OperationOutcome | None = None,
        minimum_level: OperationLevel = "info",
        job_id: str | None = None,
        source_id: str | None = None,
        subscription_id: str | None = None,
        request_id: str | None = None,
        limit: int = 50,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        workspace_id = _safe_value(workspace_id, "workspace_id")
        user_id = _safe_value(user_id, "user_id")
        if scope not in {"self", "workspace"}:
            raise ValueError("operation log scope is invalid")
        if isinstance(lookback_hours, bool) or not 1 <= int(lookback_hours) <= 720:
            raise ValueError("lookback_hours must be between 1 and 720")
        if isinstance(limit, bool) or not 1 <= int(limit) <= 100:
            raise ValueError("limit must be between 1 and 100")
        if category is not None and category not in OPERATION_CATEGORIES:
            raise ValueError("operation category is invalid")
        if outcome is not None and outcome not in OPERATION_OUTCOMES:
            raise ValueError("operation outcome is invalid")
        if minimum_level not in OPERATION_LEVELS:
            raise ValueError("minimum_level is invalid")
        id_filters = {
            "job_id": _optional_safe_value(job_id, "job_id"),
            "source_id": _optional_safe_value(source_id, "source_id"),
            "subscription_id": _optional_safe_value(
                subscription_id, "subscription_id"
            ),
            "request_id": _optional_safe_value(request_id, "request_id"),
        }
        current = now or datetime.now(timezone.utc)
        if current.tzinfo is None:
            current = current.replace(tzinfo=timezone.utc)
        current = current.astimezone(timezone.utc)
        cutoff = current - timedelta(hours=int(lookback_hours))
        window = {
            "from": _utc_iso(cutoff),
            "to": _utc_iso(current),
            "lookback_hours": int(lookback_hours),
        }
        if not self.log_dir.exists():
            return {
                "scope": scope,
                "availability": "empty",
                "events": [],
                "window": window,
                "returned": 0,
                "truncated": False,
            }
        try:
            if self.log_dir.is_symlink() or not self.log_dir.is_dir():
                raise OSError("unsafe log directory")
            files = [
                candidate
                for candidate in self.log_dir.iterdir()
                if _OPERATION_FILE_RE.fullmatch(candidate.name)
                and candidate.is_file()
                and not candidate.is_symlink()
            ]
            files.sort(key=lambda candidate: candidate.stat().st_mtime, reverse=True)
        except OSError:
            return {
                "scope": scope,
                "availability": "unavailable",
                "events": [],
                "window": window,
                "returned": 0,
                "truncated": False,
            }

        scanned = 0
        truncated = False
        matches: list[tuple[datetime, dict[str, Any]]] = []
        try:
            for path in files:
                for line in _reverse_lines(path):
                    if scanned >= self.max_scan_records:
                        truncated = True
                        break
                    scanned += 1
                    try:
                        event = json.loads(line)
                    except (json.JSONDecodeError, UnicodeError):
                        continue
                    if not isinstance(event, dict) or event.get("schema_version") != 1:
                        continue
                    timestamp = _parse_timestamp(event.get("timestamp"))
                    if timestamp is None or not cutoff <= timestamp <= current:
                        continue
                    if event.get("workspace_id") != workspace_id:
                        continue
                    if (
                        scope == "self"
                        and user_id
                        not in {
                            event.get("actor_user_id"),
                            event.get("subject_user_id"),
                        }
                    ):
                        continue
                    if event.get("category") not in OPERATION_CATEGORIES:
                        continue
                    if event.get("outcome") not in OPERATION_OUTCOMES:
                        continue
                    if event.get("level") not in OPERATION_LEVELS:
                        continue
                    if (
                        OPERATION_LEVELS[str(event["level"])]
                        < OPERATION_LEVELS[minimum_level]
                    ):
                        continue
                    if category is not None and event.get("category") != category:
                        continue
                    if outcome is not None and event.get("outcome") != outcome:
                        continue
                    if any(
                        expected is not None and event.get(field) != expected
                        for field, expected in id_filters.items()
                    ):
                        continue
                    if not isinstance(event.get("service"), str):
                        continue
                    if not isinstance(event.get("event_id"), str):
                        continue
                    if not isinstance(event.get("action"), str):
                        continue
                    public_event = _safe_public_event(event, timestamp=timestamp)
                    if public_event is None:
                        continue
                    matches.append((timestamp, public_event))
                if truncated:
                    break
        except OSError:
            return {
                "scope": scope,
                "availability": "unavailable",
                "events": [],
                "window": window,
                "returned": 0,
                "truncated": truncated,
            }
        matches.sort(key=lambda item: item[0], reverse=True)
        selected = [event for _timestamp, event in matches[: int(limit)]]
        if len(matches) > int(limit):
            truncated = True
        return {
            "scope": scope,
            "availability": "available" if selected else "empty",
            "events": selected,
            "window": window,
            "returned": len(selected),
            "truncated": truncated,
        }
