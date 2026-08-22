"""ASGI compatibility wrappers for the exact Remote MCP route."""

from __future__ import annotations

from dataclasses import dataclass

from mcp.server.fastmcp import FastMCP
from starlette.types import ASGIApp, Receive, Scope, Send


class ExactMCPPathApp:
    """Forward the exact parent `/mcp` route to the child app's `/` route."""

    def __init__(self, app: ASGIApp) -> None:
        self.app = app

    async def __call__(self, scope: Scope, receive: Receive, send: Send) -> None:
        child_scope = dict(scope)
        child_scope["path"] = "/"
        child_scope["raw_path"] = b"/"
        await self.app(child_scope, receive, send)


@dataclass(frozen=True, slots=True)
class RemoteMCPApplication:
    server: FastMCP
    exact_path_app: ExactMCPPathApp
