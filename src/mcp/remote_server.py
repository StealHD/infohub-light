"""Remote, stateless Streamable HTTP MCP server for local OpenClaw clients."""

from __future__ import annotations

import logging
import threading
import time
import uuid
from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Any, Callable, Literal, TypeVar

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken, TokenVerifier
from mcp.server.auth.settings import AuthSettings
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from mcp.server.transport_security import TransportSecuritySettings
from mcp.types import ToolAnnotations
from pydantic import AnyHttpUrl, Field
from starlette.types import ASGIApp, Receive, Scope, Send

from ..storage.service_store import AGENT_DELEGATION_SCOPE, ServiceStore
from .remote_config import RemoteMCPSettings
from .remote_service import RemoteMCPNotFound, RemoteMCPReadService


_LOGGER = logging.getLogger(__name__)
_Result = TypeVar("_Result")


class AgentDelegationTokenVerifier(TokenVerifier):
    """Resolve one opaque bearer token to its own user and workspace."""

    def __init__(self, store: ServiceStore) -> None:
        self.store = store

    async def verify_token(self, token: str) -> AccessToken | None:
        principal = self.store.authenticate_agent_delegation(token)
        if principal is None:
            return None
        return AccessToken(
            token=principal["delegation_id"],
            client_id=f"openclaw:{principal['delegation_id']}",
            scopes=principal["scopes"],
            expires_at=int(datetime.fromisoformat(principal["expires_at"]).timestamp()),
            subject=principal["user_id"],
            claims={
                "delegation_id": principal["delegation_id"],
                "workspace_id": principal["workspace_id"],
                "user_id": principal["user_id"],
                "role": principal["role"],
            },
        )


class DelegationRateLimiter:
    """In-process token bucket: 60 calls/minute with a burst of 10."""

    def __init__(self, *, rate_per_minute: int = 60, burst: int = 10) -> None:
        self.refill_per_second = float(rate_per_minute) / 60.0
        self.burst = float(burst)
        self._buckets: dict[str, tuple[float, float]] = {}
        self._lock = threading.Lock()

    def allow(self, key: str) -> bool:
        now = time.monotonic()
        with self._lock:
            tokens, previous = self._buckets.get(key, (self.burst, now))
            tokens = min(self.burst, tokens + (now - previous) * self.refill_per_second)
            if tokens < 1.0:
                self._buckets[key] = (tokens, now)
                return False
            self._buckets[key] = (tokens - 1.0, now)
            return True


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


def create_remote_mcp(
    store: ServiceStore,
    settings: RemoteMCPSettings,
) -> RemoteMCPApplication:
    """Create a fresh MCP server/session manager for one FastAPI application."""

    if not settings.enabled:
        raise ValueError("Remote MCP must be enabled before creating its server")
    read_service = RemoteMCPReadService(store)
    limiter = DelegationRateLimiter()
    annotations = ToolAnnotations(
        readOnlyHint=True,
        destructiveHint=False,
        idempotentHint=True,
        openWorldHint=False,
    )
    server = FastMCP(
        "Inteliscope",
        instructions="Read-only, user-scoped Inteliscope information tools.",
        token_verifier=AgentDelegationTokenVerifier(store),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.origin),
            resource_server_url=None,
            required_scopes=[AGENT_DELEGATION_SCOPE],
        ),
        streamable_http_path="/",
        stateless_http=True,
        json_response=True,
        transport_security=TransportSecuritySettings(
            enable_dns_rebinding_protection=True,
            allowed_hosts=[settings.host],
            allowed_origins=[settings.origin],
        ),
    )

    def run_tool(tool_name: str, operation: Callable[..., _Result], **kwargs: Any) -> _Result:
        access = get_access_token()
        claims = access.claims if access and isinstance(access.claims, dict) else {}
        delegation_id = str(claims.get("delegation_id") or "")
        request_id = f"mcp_{uuid.uuid4().hex}"
        started = time.perf_counter()
        outcome = "ok"
        if not delegation_id or not limiter.allow(delegation_id):
            outcome = "rate_limited"
            _LOGGER.warning(
                "remote_mcp_call delegation_id=%s tool=%s outcome=%s elapsed_ms=0 request_id=%s",
                delegation_id or "unknown",
                tool_name,
                outcome,
                request_id,
            )
            raise ToolError("rate_limited")
        try:
            return operation(
                workspace_id=str(claims["workspace_id"]),
                user_id=str(claims["user_id"]),
                **kwargs,
            )
        except RemoteMCPNotFound as exc:
            outcome = "not_found"
            raise ToolError("not_found") from exc
        except ValueError as exc:
            outcome = "invalid_request"
            raise ToolError(f"invalid_request: {exc}") from exc
        except Exception as exc:
            outcome = "internal_error"
            _LOGGER.error(
                "remote_mcp_internal_error delegation_id=%s tool=%s request_id=%s",
                delegation_id,
                tool_name,
                request_id,
            )
            raise ToolError(f"internal_error request_id={request_id}") from exc
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            _LOGGER.info(
                "remote_mcp_call delegation_id=%s tool=%s outcome=%s elapsed_ms=%s request_id=%s",
                delegation_id,
                tool_name,
                outcome,
                elapsed_ms,
                request_id,
            )

    @server.tool(annotations=annotations, structured_output=True)
    def get_my_feed(
        collection: Literal["latest", "history", "saved", "later"] = "latest",
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
        offset: Annotated[int, Field(ge=0, le=10_000)] = 0,
        hide_ignored: bool = True,
        unread_first: bool = True,
    ) -> dict[str, Any]:
        """List the caller's bounded Feed collection without full article bodies."""
        return run_tool(
            "get_my_feed",
            read_service.get_my_feed,
            collection=collection,
            limit=limit,
            offset=offset,
            hide_ignored=hide_ignored,
            unread_first=unread_first,
        )

    @server.tool(annotations=annotations, structured_output=True)
    def get_item(
        article_id: str,
        max_body_chars: Annotated[int, Field(ge=1, le=8000)] = 4000,
    ) -> dict[str, Any]:
        """Get one caller-visible item with a bounded plain-text body."""
        return run_tool(
            "get_item",
            read_service.get_item,
            article_id=article_id,
            max_body_chars=max_body_chars,
        )

    @server.tool(annotations=annotations, structured_output=True)
    def list_subscriptions(include_disabled: bool = True) -> dict[str, Any]:
        """List the caller's safe subscription summaries."""
        return run_tool(
            "list_subscriptions",
            read_service.list_subscriptions,
            include_disabled=include_disabled,
        )

    @server.tool(annotations=annotations, structured_output=True)
    def source_health() -> dict[str, Any]:
        """Return the caller's existing sanitized Source Health projection."""
        return run_tool("source_health", read_service.source_health)

    @server.tool(annotations=annotations, structured_output=True)
    def list_jobs(
        status: Literal[
            "queued", "running", "succeeded", "failed", "partial", "cancelled"
        ]
        | None = None,
        limit: Annotated[int, Field(ge=1, le=50)] = 20,
    ) -> dict[str, Any]:
        """List the caller's bounded, sanitized job summaries."""
        return run_tool(
            "list_jobs", read_service.list_jobs, status=status, limit=limit
        )

    @server.tool(annotations=annotations, structured_output=True)
    def get_job(job_id: str) -> dict[str, Any]:
        """Get one caller-owned sanitized job summary."""
        return run_tool("get_job", read_service.get_job, job_id=job_id)

    child_app = server.streamable_http_app()
    return RemoteMCPApplication(server=server, exact_path_app=ExactMCPPathApp(child_app))
