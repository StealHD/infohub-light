"""Registration for Remote MCP read and source-discovery tools."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .remote_models import ResolveSourceInput
from .remote_tool_annotations import (
    OPEN_WORLD_READ_ANNOTATIONS,
    READ_ANNOTATIONS,
)
from .remote_tool_context import RemoteMCPToolContext


def register_read_tools(server: FastMCP, context: RemoteMCPToolContext) -> None:
    """Register the ten non-diagnostic read tools."""

    calls = context.calls
    read_service = context.read_service
    subscription_service = context.subscription_service

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def get_my_feed(
        collection: Literal["latest", "history", "saved", "later"] = "latest",
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        offset: Annotated[int, Field(ge=0, le=10_000)] = 0,
        hide_ignored: bool = True,
        unread_first: bool = True,
    ) -> dict[str, Any]:
        """List the caller's bounded Feed collection without full article bodies."""
        return calls.run_tool(
            "get_my_feed",
            read_service.get_my_feed,
            collection=collection,
            limit=limit,
            offset=offset,
            hide_ignored=hide_ignored,
            unread_first=unread_first,
        )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def get_item(
        article_id: str,
        body_offset: Annotated[int, Field(ge=0, le=20_000)] = 0,
        max_body_chars: Annotated[int, Field(ge=1, le=8000)] = 4000,
    ) -> dict[str, Any]:
        """Get one caller-visible item with a bounded plain-text body chunk."""
        return calls.run_tool(
            "get_item",
            read_service.get_item,
            article_id=article_id,
            body_offset=body_offset,
            max_body_chars=max_body_chars,
        )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def list_subscriptions(include_disabled: bool = True) -> dict[str, Any]:
        """List the caller's safe subscription summaries."""
        return calls.run_tool(
            "list_subscriptions",
            read_service.list_subscriptions,
            include_disabled=include_disabled,
        )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def source_health() -> dict[str, Any]:
        """Return the caller's existing sanitized Source Health projection."""
        return calls.run_tool("source_health", read_service.source_health)

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def list_jobs(
        status: Literal[
            "queued", "running", "succeeded", "failed", "partial", "cancelled"
        ]
        | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> dict[str, Any]:
        """List the caller's bounded, sanitized job summaries."""
        return calls.run_tool(
            "list_jobs", read_service.list_jobs, status=status, limit=limit
        )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def get_job(job_id: str) -> dict[str, Any]:
        """Get one caller-owned sanitized job summary."""
        return calls.run_tool("get_job", read_service.get_job, job_id=job_id)

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def get_source_setup_guide(
        source_type: Annotated[str, Field(min_length=1, max_length=64)]
        | None = None,
        locale: Literal["zh-CN", "en"] = "zh-CN",
    ) -> dict[str, Any]:
        """Return registry-owned setup guidance without secret fields."""
        return calls.run_tool(
            "get_source_setup_guide",
            subscription_service.get_source_setup_guide,
            actor_operation=True,
            source_type=source_type,
            locale=locale,
        )

    @server.tool(annotations=OPEN_WORLD_READ_ANNOTATIONS, structured_output=True)
    def search_bilibili_users(
        query: Annotated[str, Field(min_length=1, max_length=50)],
        limit: Annotated[int, Field(ge=1, le=5)] = 5,
    ) -> dict[str, Any]:
        """Resolve a public Bilibili account name through fixed official endpoints."""
        return calls.run_tool(
            "search_bilibili_users",
            subscription_service.search_bilibili_users,
            actor_operation=True,
            query=query,
            limit=limit,
        )

    @server.tool(
        annotations=OPEN_WORLD_READ_ANNOTATIONS,
        structured_output=True,
    )
    async def resolve_source(
        source_type: Annotated[str, Field(min_length=1, max_length=64)],
        input: Annotated[str, Field(min_length=1, max_length=2048)],
        candidate_urls: Annotated[
            list[Annotated[str, Field(min_length=1, max_length=2048)]],
            Field(max_length=5),
        ]
        | None = None,
        limit: Annotated[int, Field(ge=1, le=5)] = 5,
    ) -> dict[str, Any]:
        """Verify public source candidates and mint bounded preparation refs."""
        request = ResolveSourceInput(
            source_type=source_type,
            input=input,
            candidate_urls=candidate_urls or [],
            limit=limit,
        )
        payload = request.model_dump()
        payload["input_value"] = payload.pop("input")
        return await calls.run_async_tool(
            "resolve_source",
            subscription_service.resolve_source,
            actor_operation=True,
            **payload,
        )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def list_available_sources(
        source_type: Annotated[str, Field(min_length=1, max_length=64)]
        | None = None,
        unsubscribed_only: bool = False,
    ) -> dict[str, Any]:
        """List visible source summaries without raw config or secret names."""
        return calls.run_tool(
            "list_available_sources",
            subscription_service.list_available_sources,
            actor_operation=True,
            source_type=source_type,
            unsubscribed_only=unsubscribed_only,
        )
