"""Shared Service API response envelopes and structured errors."""

from __future__ import annotations

from typing import Any

from fastapi.responses import JSONResponse


class ApiError(Exception):
    """Structured API error converted to the public error envelope."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
        retryable: bool = False,
        action: str = "",
    ) -> None:
        self.code = code
        self.message = message
        self.status_code = status_code
        self.retryable = retryable
        self.action = action


def ok(data: Any) -> dict[str, Any]:
    """Wrap successful response data in the stable public envelope."""

    return {"ok": True, "data": data}


def error_response(exc: ApiError) -> JSONResponse:
    """Render a structured error in the stable public envelope."""

    return JSONResponse(
        status_code=exc.status_code,
        content={
            "ok": False,
            "error": {
                "code": exc.code,
                "message": exc.message,
                "retryable": exc.retryable,
                "action": exc.action,
            },
        },
    )
