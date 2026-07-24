"""Private runtime and structured-operation logging."""

from __future__ import annotations

import copy
import json
import logging
import os
import re
import sys
import traceback
from datetime import datetime, timedelta, timezone
from logging.handlers import TimedRotatingFileHandler
from pathlib import Path
from typing import Any


OPERATION_LOGGER_NAME = "inteliscope.operations"
_SERVICES = {"api", "worker", "scheduler", "cli"}
_MANAGED_FILE_RE = re.compile(
    r"^(?:runtime|operations)-(?:api|worker|scheduler|cli)"
    r"\.jsonl(?:\.(\d{4}-\d{2}-\d{2}))?$"
)
_SENSITIVE_ASSIGNMENT_RE = re.compile(
    r"(?i)\b("
    r"authorization|password|passwd|token|api[_-]?key|secret|credential|"
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
    "error_code",
    "duration_ms",
    "changed_fields",
    "counts",
    "route",
    "method",
    "status_code",
}


def _utc_iso(timestamp: float | None = None) -> str:
    value = (
        datetime.fromtimestamp(timestamp, tz=timezone.utc)
        if timestamp is not None
        else datetime.now(timezone.utc)
    )
    return value.isoformat(timespec="milliseconds").replace("+00:00", "Z")


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
    ) -> None:
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
        payload: dict[str, Any] = {
            "schema_version": 1,
            "timestamp": _utc_iso(record.created),
            "level": record.levelname.lower(),
            "service": self.service,
            "logger": record.name,
            "message": message,
        }
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
    )
    operation_handler.setLevel(logging.INFO)
    operation_handler.setFormatter(_OperationJsonFormatter(service=service))
    operation_logger.addHandler(operation_handler)

    return {
        "directory": directory,
        "runtime": runtime_path,
        "operations": operation_path,
    }
