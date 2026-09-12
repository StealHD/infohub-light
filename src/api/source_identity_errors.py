"""Safe HTTP projection of catalog identity storage failures."""

from fastapi import FastAPI, Request

from ..storage.service_store import SourceKeyConflictError
from ..storage.source_identity_schema import SourceIdentityMigrationRequiredError
from .responses import ApiError, error_response


def default_source_scope(user: dict) -> str:
    if user.get("role") == "viewer":
        raise ApiError("forbidden", "viewer cannot create sources", status_code=403)
    return "public" if user.get("role") in {"owner", "admin"} else "private"


def register_source_identity_errors(app: FastAPI) -> None:
    async def migration_error(request: Request, exc: SourceIdentityMigrationRequiredError):
        request.state.operation_error_code = exc.code
        return error_response(ApiError(
            exc.code, str(exc), status_code=503,
            action="Ask an administrator to apply the source identity migration.",
        ))

    async def conflict_error(request: Request, exc: SourceKeyConflictError):
        request.state.operation_error_code = "source_key_conflict"
        return error_response(ApiError(
            "source_key_conflict", str(exc), status_code=409,
            action="Use an existing visible source or keep the current source unchanged.",
        ))

    app.add_exception_handler(SourceIdentityMigrationRequiredError, migration_error)
    app.add_exception_handler(SourceKeyConflictError, conflict_error)
