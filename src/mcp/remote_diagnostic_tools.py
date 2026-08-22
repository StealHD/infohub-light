"""Registration for Remote MCP diagnostic tools."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .remote_tool_annotations import READ_ANNOTATIONS
from .remote_tool_context import RemoteMCPToolContext


def register_diagnostic_tools(
    server: FastMCP,
    context: RemoteMCPToolContext,
) -> None:
    """Register deterministic read-only diagnostic tools."""

    calls = context.calls

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def diagnose_source(
        subscription_id: Annotated[str, Field(min_length=1, max_length=128)],
    ) -> dict[str, Any]:
        """Explain one caller-owned source using bounded persisted evidence."""
        return calls.run_tool(
            "diagnose_source",
            context.diagnostics.diagnose_source,
            actor_operation=True,
            subscription_id=subscription_id,
        )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def diagnose_job(
        job_id: Annotated[str, Field(min_length=1, max_length=128)],
    ) -> dict[str, Any]:
        """Explain one caller-owned job using sanitized persisted evidence."""
        return calls.run_tool(
            "diagnose_job",
            context.diagnostics.diagnose_job,
            actor_operation=True,
            job_id=job_id,
        )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def query_operation_logs(
        scope: Literal["self", "workspace"] = "self",
        lookback_hours: Annotated[int, Field(ge=1, le=720)] = 24,
        category: Literal[
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
        | None = None,
        outcome: Literal[
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
        | None = None,
        minimum_level: Literal["info", "warning", "error"] = "info",
        job_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
        source_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
        subscription_id: Annotated[
            str | None, Field(min_length=1, max_length=128)
        ] = None,
        request_id: Annotated[str | None, Field(min_length=1, max_length=128)] = None,
        limit: Annotated[int, Field(ge=1, le=100)] = 50,
    ) -> dict[str, Any]:
        """Query safe structured events; workspace scope needs an explicit grant."""
        return calls.run_tool(
            "query_operation_logs",
            context.principals.query_operation_logs_for_actor,
            actor_operation=True,
            audit_action=(
                "diagnostics_workspace"
                if scope == "workspace"
                else "diagnostics_self"
            ),
            scope=scope,
            lookback_hours=lookback_hours,
            category=category,
            outcome=outcome,
            minimum_level=minimum_level,
            job_id=job_id,
            source_id=source_id,
            subscription_id=subscription_id,
            request_id=request_id,
            limit=limit,
        )
