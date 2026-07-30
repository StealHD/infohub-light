"""Private runtime and structured-operation logging."""

from __future__ import annotations

import copy
import hashlib
import json
import logging
import os
import re
import sys
import threading
import time
import traceback
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any

from .observability_context import current_observability_context


OPERATION_LOGGER_NAME = "inteliscope.operations"
_SERVICES = {"api", "worker", "scheduler", "cli"}
_MANAGED_FILE_RE = re.compile(
    r"^(?:runtime|operations)-(?:api|worker|scheduler|cli)"
    r"\.jsonl(?:\.(\d{4}-\d{2}-\d{2}))?$"
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b("
    r"authorization|password|passwd|token|api[_-]?key|secret|credential|"
    r"chat(?:_id)?|bot_token|"
    r"webhook(?:_url)?|email(?:_address|_destination)?|recipient|destination|"
    r"confirmation(?:_text|_phrase)?|confirm(?:_text|_phrase)?|"
    r"article_id|display_name|personal_tags?|label|env(?:ironment)?(?:_name|_var)?"
    r"|body|request_body|response_body|headers?"
    r")\b([\"']?\s*[:=]\s*)([^\r\n,;]+)"
)
_SENSITIVE_TAIL_RE = re.compile(
    r"(?i)\b(?:payload|config|upstream[_\s-]*response|"
    r"(?:request|response|article)[_\s-]*(?:body|content)|"
    r"article[_\s-]*id|display[_\s-]*name|"
    r"personal[_\s-]*(?:tags?|labels?))\b.*"
)
_AUTH_SCHEME_RE = re.compile(
    r"(?i)\b(?:Bearer|Basic|Digest|ApiKey)\s+[^\s,;]+"
)
_MCP_TOKEN_RE = re.compile(r"\bih_mcp_v1_[A-Za-z0-9_-]+\b")
_COMMON_SECRET_RE = re.compile(
    r"\b(?:sk-|sk_|AIza|xai-|gsk_|hf_|tp-)[A-Za-z0-9._~-]{6,}\b"
)
_EMAIL_RE = re.compile(
    r"(?<![A-Za-z0-9.!#$%&'*+/=?^_`{|}~-])"
    r"[A-Za-z0-9.!#$%&'*+/=?^_`{|}~-]+@"
    r"[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?"
    r"(?:\.[A-Za-z0-9](?:[A-Za-z0-9-]{0,61}[A-Za-z0-9])?)+"
)
_URL_RE = re.compile(r"(?i)\b(?:https?|wss?)://[^\s<>'\"]+")
_ENV_NAME_RE = re.compile(r"\b[A-Z][A-Z0-9]*(?:_[A-Z0-9]+)+\b")
_OPERATION_REQUIRED_FIELDS = {
    "schema_version",
    "event_id",
    "timestamp",
    "level",
    "category",
    "action",
    "outcome",
}
_OPERATION_ALLOWED_FIELDS = _OPERATION_REQUIRED_FIELDS | {
    "workspace_id",
    "actor_user_id",
    "subject_user_id",
    "request_id",
    "job_id",
    "source_id",
    "subscription_id",
    "stage",
    "error_code",
    "error_fingerprint",
    "duration_ms",
    "changed_fields",
    "counts",
    "route",
    "method",
    "status_code",
}
_LOG_WRITE_LOCK = threading.Lock()
_LOG_WRITE_STATE: dict[str, dict[str, Any]] = {
    "runtime": {
        "configured": False,
        "healthy": False,
        "last_success": None,
        "last_failure": None,
    },
    "operations": {
        "configured": False,
        "healthy": False,
        "last_success": None,
        "last_failure": None,
    },
}
_LAST_FALLBACK_AT = 0.0


@dataclass(slots=True)
class _WriteAcknowledgement:
    channel: str
    attempted: bool = False
    succeeded: bool = False


def _utc_iso(timestamp: float | None = None) -> str:
    value = (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        if timestamp is not None
        else datetime.now(timezone.utc)
    )
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


def error_fingerprint(
    exc_info: tuple[type[BaseException], BaseException, Any] | None = None,
) -> str:
    """Build a stable, value-free fingerprint for one exception location."""

    resolved = exc_info or sys.exc_info()
    exception_type, _exception, tb = resolved
    type_name = getattr(exception_type, "__name__", "Exception")
    frames = traceback.extract_tb(tb)[-8:] if tb is not None else []
    revision = os.getenv("INTELISCOPE_BUILD_REVISION", "unknown")
    material = "|".join(
        [
            revision,
            type_name,
            *(
                f"{Path(frame.filename).name}:{frame.name}:{int(frame.lineno)}"
                for frame in frames
            ),
        ]
    )
    return f"err_{hashlib.sha256(material.encode('utf-8')).hexdigest()[:20]}"


def _mark_log_write(channel: str, *, healthy: bool) -> None:
    timestamp = _utc_iso()
    with _LOG_WRITE_LOCK:
        state = _LOG_WRITE_STATE[channel]
        state["configured"] = True
        state["healthy"] = healthy
        state["last_success" if healthy else "last_failure"] = timestamp


def _reset_log_write_health() -> None:
    with _LOG_WRITE_LOCK:
        for state in _LOG_WRITE_STATE.values():
            state.update(
                {
                    "configured": False,
                    "healthy": False,
                    "last_success": None,
                    "last_failure": None,
                }
            )


def logging_health_status() -> dict[str, Any]:
    """Return bounded logging sink health without exposing paths or errors."""

    with _LOG_WRITE_LOCK:
        channels = {
            channel: {
                "status": (
                    "ready"
                    if state["configured"] and state["healthy"]
                    else "degraded"
                ),
                "last_success": state["last_success"],
                "last_failure": state["last_failure"],
            }
            for channel, state in _LOG_WRITE_STATE.items()
        }
    return {
        "status": (
            "ready"
            if all(channel["status"] == "ready" for channel in channels.values())
            else "degraded"
        ),
        "channels": channels,
    }


def operation_write_acknowledged(acknowledgement: Any) -> bool:
    return bool(
        isinstance(acknowledgement, _WriteAcknowledgement)
        and acknowledgement.attempted
        and acknowledgement.succeeded
    )


def new_operation_write_acknowledgement() -> _WriteAcknowledgement:
    return _WriteAcknowledgement(channel="operations")


def _emit_safe_fallback(channel: str) -> None:
    global _LAST_FALLBACK_AT
    current = time.monotonic()
    if current - _LAST_FALLBACK_AT < 60:
        return
    _LAST_FALLBACK_AT = current
    try:
        os.write(
            2,
            (
                "inteliscope managed log write failed "
                f"channel={channel}\n"
            ).encode("ascii"),
        )
    except OSError:
        pass


def redact_log_text(value: Any) -> str:
    """Remove credential-like and destination-like values from rendered logs."""

    text = str(value)
    text = _AUTH_SCHEME_RE.sub("<redacted-authorization>", text)
    text = _SENSITIVE_ASSIGNMENT_RE.sub(
        lambda match: f"{match.group(1)}{match.group(2)}<redacted>",
        text,
    )
    text = _SENSITIVE_TAIL_RE.sub("<redacted-sensitive-data>", text)
    text = _MCP_TOKEN_RE.sub("<redacted-token>", text)
    text = _COMMON_SECRET_RE.sub("<redacted-secret>", text)
    text = _EMAIL_RE.sub("<redacted-email>", text)
    text = _URL_RE.sub("<redacted-url>", text)
    text = _ENV_NAME_RE.sub("<redacted-env>", text)
    return text


def log_retention_days(value: str | int | None = None) -> int:
    """Resolve the strict managed-log retention window."""

    candidate: Any = (
        os.getenv("HORIZON_LOG_RETENTION_DAYS", "30") if value is None else value
    )
    if isinstance(candidate, bool):
        raise ValueError("HORIZON_LOG_RETENTION_DAYS must be an integer from 1 to 365")
    try:
        days = int(candidate)
    except (TypeError, ValueError) as exc:
        raise ValueError(
            "HORIZON_LOG_RETENTION_DAYS must be an integer from 1 to 365"
        ) from exc
    if str(candidate).strip() != str(days) or not 1 <= days <= 365:
        raise ValueError("HORIZON_LOG_RETENTION_DAYS must be an integer from 1 to 365")
    return days


def _log_level(value: str | int | None = None) -> int:
    candidate: Any = os.getenv("HORIZON_LOG_LEVEL", "INFO") if value is None else value
    if isinstance(candidate, int) and not isinstance(candidate, bool):
        if candidate in {
            logging.DEBUG,
            logging.INFO,
            logging.WARNING,
            logging.ERROR,
            logging.CRITICAL,
        }:
            return candidate
        raise ValueError("HORIZON_LOG_LEVEL is invalid")
    name = str(candidate).strip().upper()
    level = logging.getLevelNamesMapping().get(name)
    if not isinstance(level, int):
        raise ValueError("HORIZON_LOG_LEVEL is invalid")
    return level


def _prepare_log_directory(log_dir: str | Path) -> Path:
    path = Path(log_dir)
    if path.is_symlink():
        raise ValueError("log directory must not be a symbolic link")
    path.mkdir(parents=True, exist_ok=True, mode=0o700)
    os.chmod(path, 0o700)
    return path


def _validate_managed_log_path(path: Path) -> None:
    if path.is_symlink() or (path.exists() and not path.is_file()):
        raise ValueError("managed log path must be a regular file")


def prune_managed_logs(
    log_dir: str | Path,
    retention_days: int,
    *,
    now: datetime | None = None,
) -> list[Path]:
    """Delete only dated files owned by this logging system and older than policy."""

    retention_days = log_retention_days(retention_days)
    directory = Path(log_dir)
    if not directory.exists():
        return []
    if directory.is_symlink():
        raise ValueError("log directory must not be a symbolic link")
    current = now or datetime.now(timezone.utc)
    if current.tzinfo is None:
        current = current.replace(tzinfo=timezone.utc)
    cutoff = current.astimezone(timezone.utc).date() - timedelta(
        days=retention_days - 1
    )
    removed: list[Path] = []
    for candidate in directory.iterdir():
        match = _MANAGED_FILE_RE.fullmatch(candidate.name)
        dated_suffix = match.group(1) if match else None
        if not dated_suffix or candidate.is_symlink() or not candidate.is_file():
            continue
        try:
            file_date = datetime.strptime(dated_suffix, "%Y-%m-%d").date()
        except ValueError:
            continue
        if file_date < cutoff:
            try:
                candidate.unlink()
            except FileNotFoundError:
                continue
            removed.append(candidate)
    return removed


class _PrivateTimedRotatingFileHandler(TimedRotatingFileHandler):
    """UTC daily rotation with private files and age-based cleanup."""

    def __init__(
        self,
        filename: str | Path,
        *,
        retention_days: int,
        channel: str,
    ) -> None:
        if channel not in _LOG_WRITE_STATE:
            raise ValueError("managed log channel is invalid")
        self.channel = channel
        self.retention_days = log_retention_days(retention_days)
        super().__init__(
            str(filename),
            when="midnight",
            interval=1,
            backupCount=0,
            encoding="utf-8",
            delay=False,
            utc=True,
            errors="backslashreplace",
        )
        self._inteliscope_managed_handler = True

    def _open(self):  # type: ignore[no-untyped-def]
        descriptor = os.open(
            self.baseFilename,
            os.O_APPEND
            | os.O_CREAT
            | os.O_WRONLY
            | getattr(os, "O_NOFOLLOW", 0),
            0o600,
        )
        os.fchmod(descriptor, 0o600)
        return os.fdopen(
            descriptor,
            self.mode,
            encoding=self.encoding,
            errors=self.errors,
        )

    def doRollover(self) -> None:
        super().doRollover()
        base = Path(self.baseFilename)
        for candidate in base.parent.glob(f"{base.name}*"):
            if candidate.is_file() and not candidate.is_symlink():
                os.chmod(candidate, 0o600)
        prune_managed_logs(base.parent, self.retention_days)

    def emit(self, record: logging.LogRecord) -> None:
        acknowledgement = getattr(
            record, "_inteliscope_operation_write_ack", None
        )
        if (
            isinstance(acknowledgement, _WriteAcknowledgement)
            and acknowledgement.channel == self.channel
        ):
            acknowledgement.attempted = True
        try:
            if self.shouldRollover(record):
                self.doRollover()
            message = self.format(record)
            stream = self.stream
            if stream is None:
                stream = self.stream = self._open()
            stream.write(message + self.terminator)
            self.flush()
        except Exception:
            _mark_log_write(self.channel, healthy=False)
            if (
                isinstance(acknowledgement, _WriteAcknowledgement)
                and acknowledgement.channel == self.channel
            ):
                acknowledgement.succeeded = False
            _emit_safe_fallback(self.channel)
        else:
            _mark_log_write(self.channel, healthy=True)
            if (
                isinstance(acknowledgement, _WriteAcknowledgement)
                and acknowledgement.channel == self.channel
            ):
                acknowledgement.succeeded = True


class _RedactingTextFormatter(logging.Formatter):
    def format(self, record: logging.LogRecord) -> str:
        safe_record = copy.copy(record)
        exception_type: str | None = None
        if record.exc_info:
            exception_type = getattr(record.exc_info[0], "__name__", "Exception")
            safe_record.exc_info = None
            safe_record.exc_text = None
        safe_record.stack_info = None
        rendered = super().format(safe_record)
        if exception_type is not None:
            rendered = f"{rendered} exception_type={exception_type}"
        return redact_log_text(rendered)


class _RuntimeJsonFormatter(logging.Formatter):
    def __init__(self, *, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        message = redact_log_text(record.getMessage())
        context = current_observability_context()
        payload: dict[str, Any] = {
            "schema_version": 1,
            "timestamp": _utc_iso(record.created),
            "level": record.levelname.lower(),
            "service": self.service,
            "logger": record.name,
            "message": message,
        }
        for field in (
            "request_id",
            "job_id",
            "source_id",
            "subscription_id",
            "stage",
            "error_code",
        ):
            value = getattr(record, field, None) or getattr(context, field)
            if value is not None:
                payload[field] = value
        if record.exc_info:
            exception_type, _exception, tb = record.exc_info
            frames = traceback.extract_tb(tb)[-32:]
            payload["exception"] = {
                "type": redact_log_text(
                    getattr(exception_type, "__name__", "Exception")
                ),
                "frames": [
                    {
                        "file": redact_log_text(Path(frame.filename).name),
                        "function": redact_log_text(frame.name),
                        "line": int(frame.lineno),
                    }
                    for frame in frames
                ],
            }
            payload["error_fingerprint"] = error_fingerprint(record.exc_info)
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


class _OperationJsonFormatter(logging.Formatter):
    def __init__(self, *, service: str) -> None:
        super().__init__()
        self.service = service

    def format(self, record: logging.LogRecord) -> str:
        raw = getattr(record, "operation_event", None)
        if not isinstance(raw, dict):
            raise ValueError("operation log record is missing its structured event")
        if (
            not _OPERATION_REQUIRED_FIELDS.issubset(raw)
            or not set(raw).issubset(_OPERATION_ALLOWED_FIELDS)
        ):
            raise ValueError("operation log record violates the event schema")
        payload = {
            **{
                field: raw[field]
                for field in _OPERATION_ALLOWED_FIELDS
                if field in raw
            },
            "service": self.service,
        }
        return json.dumps(
            payload,
            ensure_ascii=False,
            separators=(",", ":"),
            sort_keys=True,
        )


def _remove_managed_handlers(logger: logging.Logger) -> None:
    for handler in tuple(logger.handlers):
        if getattr(handler, "_inteliscope_managed_handler", False):
            logger.removeHandler(handler)
            handler.close()


def configure_logging(
    log_dir: str | Path = "logs",
    *,
    service: str = "cli",
    retention_days: str | int | None = None,
    level: str | int | None = None,
) -> dict[str, Path]:
    """Configure private files and human-readable stdout for one process."""

    if service not in _SERVICES:
        raise ValueError("logging service is invalid")
    _reset_log_write_health()
    resolved_retention = log_retention_days(retention_days)
    resolved_level = _log_level(level)
    directory = _prepare_log_directory(log_dir)
    prune_managed_logs(directory, resolved_retention)

    runtime_path = directory / f"runtime-{service}.jsonl"
    operation_path = directory / f"operations-{service}.jsonl"
    _validate_managed_log_path(runtime_path)
    _validate_managed_log_path(operation_path)

    root = logging.getLogger()
    _remove_managed_handlers(root)
    root.setLevel(resolved_level)

    runtime_handler = _PrivateTimedRotatingFileHandler(
        runtime_path,
        retention_days=resolved_retention,
        channel="runtime",
    )
    runtime_handler.setLevel(resolved_level)
    runtime_handler.setFormatter(_RuntimeJsonFormatter(service=service))
    root.addHandler(runtime_handler)

    stream_handler = logging.StreamHandler(sys.stdout)
    stream_handler._inteliscope_managed_handler = True  # type: ignore[attr-defined]
    stream_handler.setLevel(resolved_level)
    stream_handler.setFormatter(
        _RedactingTextFormatter(
            "%(asctime)s %(levelname)s %(name)s %(message)s"
        )
    )
    root.addHandler(stream_handler)

    operation_logger = logging.getLogger(OPERATION_LOGGER_NAME)
    _remove_managed_handlers(operation_logger)
    # Operation events are the durable state-change trail. Runtime verbosity
    # must not silently suppress successful critical operations.
    operation_logger.setLevel(logging.INFO)
    operation_logger.propagate = True
    operation_handler = _PrivateTimedRotatingFileHandler(
        operation_path,
        retention_days=resolved_retention,
        channel="operations",
    )
    operation_handler.setLevel(logging.INFO)
    operation_handler.setFormatter(_OperationJsonFormatter(service=service))
    operation_logger.addHandler(operation_handler)
    _mark_log_write("runtime", healthy=True)
    _mark_log_write("operations", healthy=True)

    return {
        "directory": directory,
        "runtime": runtime_path,
        "operations": operation_path,
    }
