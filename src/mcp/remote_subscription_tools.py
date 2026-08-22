"""Registration for controlled Remote MCP subscription mutations."""

from __future__ import annotations

from typing import Annotated, Any, Literal

from mcp.server.fastmcp import FastMCP
from pydantic import Field

from .remote_models import (
    ApplySubscriptionChangeInput,
    PrepareCreateSubscriptionInput,
    PrepareDeleteSubscriptionInput,
    PrepareUpdateSubscriptionInput,
    ScheduleInput,
    ScheduleUpdatesInput,
    SourceInput,
    SourceUpdatesInput,
    SubscriptionInput,
    SubscriptionUpdatesInput,
)
from .remote_tool_annotations import APPLY_ANNOTATIONS, PREPARE_ANNOTATIONS
from .remote_tool_context import RemoteMCPToolContext


def register_subscription_tools(
    server: FastMCP,
    context: RemoteMCPToolContext,
) -> None:
    """Register prepare/apply tools without owning mutation semantics."""

    calls = context.calls
    service = context.subscription_service

    @server.tool(annotations=PREPARE_ANNOTATIONS, structured_output=True)
    def prepare_create_subscription(
        source: SourceInput,
        subscription: SubscriptionInput | None = None,
        schedule: ScheduleInput | None = None,
    ) -> dict[str, Any]:
        """Prepare, but do not apply, one subscription creation proposal.

        Source must be either ``{mode: existing, source_id}`` using an ID from
        ``list_available_sources``, ``{mode: resolved, resolution_ref}`` using
        a reference from ``resolve_source``, or
        ``{mode: private, type, display_name, config}``. Never use
        ``mode: create``, ``source_type``, or ``fields``.
        """
        request = PrepareCreateSubscriptionInput(
            source=source,
            subscription=subscription,
            schedule=schedule,
        )
        return calls.run_tool(
            "prepare_create_subscription",
            service.prepare_create_subscription,
            actor_operation=True,
            audit_action="prepare_create",
            **request.model_dump(exclude_unset=True),
        )

    @server.tool(annotations=PREPARE_ANNOTATIONS, structured_output=True)
    def prepare_update_subscription(
        subscription_id: Annotated[str, Field(min_length=1, max_length=128)],
        source_updates: SourceUpdatesInput | None = None,
        subscription_updates: SubscriptionUpdatesInput | None = None,
        schedule_updates: ScheduleUpdatesInput | None = None,
    ) -> dict[str, Any]:
        """Prepare, but do not apply, a subscription update proposal."""
        request = PrepareUpdateSubscriptionInput(
            subscription_id=subscription_id,
            source_updates=source_updates,
            subscription_updates=subscription_updates,
            schedule_updates=schedule_updates,
        )
        return calls.run_tool(
            "prepare_update_subscription",
            service.prepare_update_subscription,
            actor_operation=True,
            audit_action="prepare_update",
            **request.model_dump(exclude_unset=True),
        )

    @server.tool(annotations=PREPARE_ANNOTATIONS, structured_output=True)
    def prepare_delete_subscription(
        subscription_id: Annotated[str, Field(min_length=1, max_length=128)],
        source_disposition: Literal["keep", "disable_private"],
    ) -> dict[str, Any]:
        """Prepare a deletion with an explicit private-source disposition."""
        request = PrepareDeleteSubscriptionInput(
            subscription_id=subscription_id,
            source_disposition=source_disposition,
        )
        return calls.run_tool(
            "prepare_delete_subscription",
            service.prepare_delete_subscription,
            actor_operation=True,
            audit_action="prepare_delete",
            **request.model_dump(),
        )

    @server.tool(annotations=APPLY_ANNOTATIONS, structured_output=True)
    def apply_subscription_change(
        proposal_id: Annotated[str, Field(min_length=1, max_length=128)],
        confirmation_text: Annotated[str, Field(min_length=1, max_length=160)],
    ) -> dict[str, Any]:
        """Apply one exact, pending proposal after server-side revalidation."""
        request = ApplySubscriptionChangeInput(
            proposal_id=proposal_id,
            confirmation_text=confirmation_text,
        )
        payload = request.model_dump()
        return calls.run_tool(
            "apply_subscription_change",
            service.apply_subscription_change,
            actor_operation=True,
            audit_action="apply",
            audit_proposal_id=payload["proposal_id"],
            **payload,
        )
