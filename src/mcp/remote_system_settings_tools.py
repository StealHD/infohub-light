"""Remote MCP tools for typed admin runtime settings."""

from __future__ import annotations

from typing import Annotated, Any

from mcp.server.fastmcp import FastMCP
from pydantic import BaseModel, ConfigDict, Field, StrictBool, StrictInt

from .remote_tool_annotations import APPLY_ANNOTATIONS, PREPARE_ANNOTATIONS, READ_ANNOTATIONS
from .remote_tool_context import RemoteMCPToolContext


class SystemSettingChangeInput(BaseModel):
    model_config = ConfigDict(extra="forbid", hide_input_in_errors=True)

    key: str = Field(min_length=1, max_length=128)
    value: StrictBool | StrictInt | None


def _changes(items: list[SystemSettingChangeInput]) -> dict[str, Any]:
    result: dict[str, Any] = {}
    for item in items:
        if item.key in result:
            raise ValueError("duplicate system setting")
        result[item.key] = item.value
    return result


def register_system_settings_tools(
    server: FastMCP,
    context: RemoteMCPToolContext,
) -> None:
    calls = context.calls
    service = context.system_settings

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def list_system_settings() -> dict[str, Any]:
        """List the admin-delegated safe runtime settings and current generation."""
        return calls.run_tool(
            "list_system_settings",
            service.list_system_settings,
            actor_operation=True,
        )

    @server.tool(annotations=PREPARE_ANNOTATIONS, structured_output=True)
    def prepare_update_system_settings(
        expected_generation: Annotated[StrictInt, Field(ge=1)],
        changes: Annotated[
            list[SystemSettingChangeInput], Field(min_length=1, max_length=20)
        ],
    ) -> dict[str, Any]:
        """Preview typed settings changes; null resets one setting to fallback."""
        return calls.run_tool(
            "prepare_update_system_settings",
            service.prepare_update_system_settings,
            actor_operation=True,
            audit_action="prepare_update",
            expected_generation=int(expected_generation),
            changes=_changes(changes),
        )

    @server.tool(annotations=APPLY_ANNOTATIONS, structured_output=True)
    def apply_system_settings_change(
        proposal_id: Annotated[str, Field(min_length=1, max_length=128)],
        confirmation_text: Annotated[str, Field(min_length=1, max_length=160)],
    ) -> dict[str, Any]:
        """Apply one exact, pending settings proposal after live revalidation."""
        return calls.run_tool(
            "apply_system_settings_change",
            service.apply_system_settings_change,
            actor_operation=True,
            audit_action="apply",
            audit_proposal_id=proposal_id,
            proposal_id=proposal_id,
            confirmation_text=confirmation_text,
        )


__all__ = ["register_system_settings_tools"]
