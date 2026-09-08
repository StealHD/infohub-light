"""Safe diagnostics for caught exceptions, including asyncio gathered failures."""

from __future__ import annotations

import logging
import sys
from functools import wraps

from .logging_health import mark_failure
from .observability_context import (
    begin_child_observability_context, reset_observability_context,
    safe_observability_stage, safe_observability_value,
)


def log_exception(
    logger: logging.Logger,
    *,
    stage: str,
    error_code: str,
    exception: BaseException | None = None,
    level: int = logging.WARNING,
) -> None:
    """Retain code locations without interpolating exception text or values."""
    try:
        exc_info = (
            (type(exception), exception, exception.__traceback__)
            if exception is not None else sys.exc_info()
        )
        logger.log(
            level, "caught operation exception",
            exc_info=exc_info if exc_info[0] is not None else None,
            extra={
                "stage": safe_observability_stage(stage),
                "error_code": safe_observability_value(error_code, "error_code"),
            },
        )
    except Exception as exc:
        mark_failure("runtime", "write" if isinstance(exc, OSError) else "validation")


def source_diagnostics(call):
    """Bind each concurrent source fetch before any adapter or coordinator log."""
    @wraps(call)
    async def wrapped(self, label, scraper, source, since):
        fields = {"stage": "acquisition", "error_code": ""}
        for field in ("source_id", "subscription_id"):
            raw = getattr(source, field, None)
            try:
                fields[field] = safe_observability_value(raw, field) if raw else ""
            except (ValueError, TypeError):
                fields[field] = ""
                mark_failure("runtime", "validation")
        token = begin_child_observability_context(**fields)
        try:
            return await call(self, label, scraper, source, since)
        except Exception as exception:
            log_exception(logging.getLogger(call.__module__), stage="acquisition",
                          error_code="source_fetch_failed", exception=exception)
            raise
        finally:
            reset_observability_context(token)
    return wrapped
