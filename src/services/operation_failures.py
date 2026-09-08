"""Terminal best-effort failure boundary for independent Worker side effects."""

from __future__ import annotations

import logging
from typing import Any

from ..logging_diagnostics import log_exception
from ..logging_utils import error_fingerprint
from .operation_log import safe_emit_operation_event


def record_operation_failure(
    logger: logging.Logger, *, category: str, action: str, stage: str,
    error_code: str, **identifiers: Any,
) -> None:
    log_exception(logger, stage=stage, error_code=error_code, level=logging.ERROR)
    safe_emit_operation_event(
        category=category, action=action, stage=stage, outcome="failed", level="error",
        error_code=error_code, error_fingerprint=error_fingerprint(), **identifiers,
    )
