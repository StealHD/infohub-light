"""Register the complete, access-filtered Remote MCP tool surface."""

from __future__ import annotations

from .remote_diagnostic_tools import register_diagnostic_tools
from .remote_read_tools import register_read_tools
from .remote_subscription_tools import register_subscription_tools
from .remote_system_settings_tools import register_system_settings_tools


def register_remote_tools(server: object, context: object) -> None:
    register_read_tools(server, context)
    register_subscription_tools(server, context)
    register_diagnostic_tools(server, context)
    register_system_settings_tools(server, context)


__all__ = ["register_remote_tools"]
