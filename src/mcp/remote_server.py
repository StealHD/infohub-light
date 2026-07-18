"""Remote, stateless Streamable HTTP MCP server for local OpenClaw clients."""

from __future__ import annotations

import logging
import re
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
from pydantic import AnyHttpUrl, ConfigDict, Field
from starlette.types import ASGIApp, Receive, Scope, Send

from ..services.agent_change_proposal import (
    AgentChangeProposalService,
    AgentProposalError,
    DelegatedActor,
)
from ..services.runtime_status import RuntimeStatusService
from ..services.source_type_registry import SourceConfigError
from ..services.subscription_mutation import (
    SubscriptionMutationError,
    SubscriptionMutationService,
)
from ..storage.service_store import AGENT_DELEGATION_READ_SCOPE, ServiceStore
from .remote_config import RemoteMCPSettings
from .remote_diagnostics import RemoteMCPDiagnostics
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
from .remote_service import RemoteMCPNotFound, RemoteMCPReadService
from .remote_subscription_service import RemoteMCPSubscriptionService


_LOGGER = logging.getLogger(__name__)
_Result = TypeVar("_Result")
_AUDIT_VALUE_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")

READ_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=True,
    destructiveHint=False,
    idempotentHint=True,
    openWorldHint=False,
)
PREPARE_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=False,
    idempotentHint=False,
    openWorldHint=False,
)
APPLY_ANNOTATIONS = ToolAnnotations(
    readOnlyHint=False,
    destructiveHint=True,
    idempotentHint=False,
    openWorldHint=False,
)


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
    *,
    mutation_service: SubscriptionMutationService,
    runtime_status: RuntimeStatusService,
    secret_is_set: Callable[[str], bool],
) -> RemoteMCPApplication:
    """Create a fresh MCP server/session manager for one FastAPI application."""

    if not settings.enabled:
        raise ValueError("Remote MCP must be enabled before creating its server")
    read_service = RemoteMCPReadService(store)
    proposal_service = AgentChangeProposalService(
        store,
        writes_enabled=settings.subscription_writes_enabled,
        mutations=mutation_service,
    )
    subscription_service = RemoteMCPSubscriptionService(
        store=store,
        mutations=mutation_service,
        proposals=proposal_service,
        secret_is_set=secret_is_set,
    )
    diagnostics = RemoteMCPDiagnostics(
        store,
        runtime_status=runtime_status,
        secret_is_set=secret_is_set,
    )
    limiter = DelegationRateLimiter()
    server = FastMCP(
        "Inteliscope",
        instructions="User-scoped Inteliscope information and controlled subscription tools.",
        token_verifier=AgentDelegationTokenVerifier(store),
        auth=AuthSettings(
            issuer_url=AnyHttpUrl(settings.origin),
            resource_server_url=None,
            required_scopes=[AGENT_DELEGATION_READ_SCOPE],
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

    def actor_from_access(access: AccessToken | None) -> DelegatedActor:
        claims = access.claims if access and isinstance(access.claims, dict) else {}
        scopes = access.scopes if access is not None else []
        if not all(
            isinstance(value, str) and value
            for value in (
                claims.get("workspace_id"),
                claims.get("user_id"),
                claims.get("role"),
                claims.get("delegation_id"),
            )
        ) or not isinstance(scopes, list):
            raise AgentProposalError(
                "unauthorized", "delegation is not authorized", status_code=401
            )
        return DelegatedActor(
            workspace_id=str(claims["workspace_id"]),
            user_id=str(claims["user_id"]),
            role=str(claims["role"]),
            delegation_id=str(claims["delegation_id"]),
            scopes=tuple(str(scope) for scope in scopes),
        )

    def audit_value(value: Any) -> str:
        candidate = str(value or "")
        return candidate if _AUDIT_VALUE_RE.fullmatch(candidate) else "-"

    def run_tool(
        tool_name: str,
        operation: Callable[..., _Result],
        *,
        actor_operation: bool = False,
        audit_action: str = "-",
        audit_proposal_id: str = "-",
        **kwargs: Any,
    ) -> _Result:
        access = get_access_token()
        claims = access.claims if access and isinstance(access.claims, dict) else {}
        delegation_id = str(claims.get("delegation_id") or "")
        request_id = f"mcp_{uuid.uuid4().hex}"
        started = time.perf_counter()
        outcome = "ok"
        logged_proposal_id = audit_value(audit_proposal_id)
        logged_action = audit_value(audit_action)
        if not delegation_id or not limiter.allow(delegation_id):
            outcome = "rate_limited"
            _LOGGER.warning(
                "remote_mcp_call delegation_id=%s tool=%s proposal_id=%s "
                "action=%s outcome=%s elapsed_ms=%s request_id=%s",
                delegation_id or "-",
                tool_name,
                logged_proposal_id,
                logged_action,
                outcome,
                0,
                request_id,
            )
            raise ToolError("rate_limited")
        try:
            actor = actor_from_access(access)
            result = (
                operation(actor=actor, **kwargs)
                if actor_operation
                else operation(
                    workspace_id=actor.workspace_id,
                    user_id=actor.user_id,
                    **kwargs,
                )
            )
            if isinstance(result, dict):
                logged_proposal_id = audit_value(
                    result.get("proposal_id") or logged_proposal_id
                )
                preview = result.get("preview")
                result_summary = result.get("result")
                result_action = (
                    preview.get("action") if isinstance(preview, dict) else None
                ) or (
                    result_summary.get("action")
                    if isinstance(result_summary, dict)
                    else None
                )
                if result_action:
                    logged_action = audit_value(result_action)
            return result
        except RemoteMCPNotFound:
            outcome = "not_found"
            raise ToolError("not_found") from None
        except AgentProposalError as exc:
            outcome = audit_value(exc.code)
            raise ToolError(outcome) from None
        except SubscriptionMutationError as exc:
            outcome = audit_value(exc.code)
            raise ToolError(outcome) from None
        except SourceConfigError:
            outcome = "invalid_request"
            raise ToolError("invalid_request") from None
        except Exception:
            outcome = "internal_error"
            raise ToolError(f"internal_error request_id={request_id}") from None
        finally:
            elapsed_ms = int((time.perf_counter() - started) * 1000)
            _LOGGER.info(
                "remote_mcp_call delegation_id=%s tool=%s proposal_id=%s "
                "action=%s outcome=%s elapsed_ms=%s request_id=%s",
                delegation_id,
                tool_name,
                logged_proposal_id,
                logged_action,
                outcome,
                elapsed_ms,
                request_id,
            )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
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

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
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

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def list_subscriptions(include_disabled: bool = True) -> dict[str, Any]:
        """List the caller's safe subscription summaries."""
        return run_tool(
            "list_subscriptions",
            read_service.list_subscriptions,
            include_disabled=include_disabled,
        )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def source_health() -> dict[str, Any]:
        """Return the caller's existing sanitized Source Health projection."""
        return run_tool("source_health", read_service.source_health)

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
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

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def get_job(job_id: str) -> dict[str, Any]:
        """Get one caller-owned sanitized job summary."""
        return run_tool("get_job", read_service.get_job, job_id=job_id)

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def get_source_setup_guide(
        source_type: Literal[
            "rss",
            "telegram",
            "github",
            "reddit",
            "twitter",
            "website",
            "youtube",
            "apify",
        ]
        | None = None,
        locale: Literal["zh-CN", "en"] = "zh-CN",
    ) -> dict[str, Any]:
        """Return registry-owned setup guidance without secret fields."""
        return run_tool(
            "get_source_setup_guide",
            subscription_service.get_source_setup_guide,
            actor_operation=True,
            source_type=source_type,
            locale=locale,
        )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def list_available_sources(
        source_type: Literal[
            "rss",
            "telegram",
            "github",
            "reddit",
            "twitter",
            "website",
            "youtube",
            "apify",
        ]
        | None = None,
        unsubscribed_only: bool = False,
    ) -> dict[str, Any]:
        """List visible source summaries without raw config or secret names."""
        return run_tool(
            "list_available_sources",
            subscription_service.list_available_sources,
            actor_operation=True,
            source_type=source_type,
            unsubscribed_only=unsubscribed_only,
        )

    @server.tool(annotations=PREPARE_ANNOTATIONS, structured_output=True)
    def prepare_create_subscription(
        source: SourceInput,
        subscription: SubscriptionInput | None = None,
        schedule: ScheduleInput | None = None,
    ) -> dict[str, Any]:
        """Prepare, but do not apply, a subscription creation proposal."""
        request = PrepareCreateSubscriptionInput(
            source=source,
            subscription=subscription,
            schedule=schedule,
        )
        payload = request.model_dump(exclude_unset=True)
        return run_tool(
            "prepare_create_subscription",
            subscription_service.prepare_create_subscription,
            actor_operation=True,
            audit_action="prepare_create",
            **payload,
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
        return run_tool(
            "prepare_update_subscription",
            subscription_service.prepare_update_subscription,
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
        return run_tool(
            "prepare_delete_subscription",
            subscription_service.prepare_delete_subscription,
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
        return run_tool(
            "apply_subscription_change",
            subscription_service.apply_subscription_change,
            actor_operation=True,
            audit_action="apply",
            audit_proposal_id=payload["proposal_id"],
            **payload,
        )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def diagnose_source(
        subscription_id: Annotated[str, Field(min_length=1, max_length=128)],
    ) -> dict[str, Any]:
        """Explain one caller-owned source using bounded persisted evidence."""
        return run_tool(
            "diagnose_source",
            diagnostics.diagnose_source,
            actor_operation=True,
            subscription_id=subscription_id,
        )

    @server.tool(annotations=READ_ANNOTATIONS, structured_output=True)
    def diagnose_job(
        job_id: Annotated[str, Field(min_length=1, max_length=128)],
    ) -> dict[str, Any]:
        """Explain one caller-owned job using sanitized persisted evidence."""
        return run_tool(
            "diagnose_job",
            diagnostics.diagnose_job,
            actor_operation=True,
            job_id=job_id,
        )

    for tool in server._tool_manager.list_tools():
        argument_model = tool.fn_metadata.arg_model
        argument_model.model_config = ConfigDict(
            **argument_model.model_config,
            extra="forbid",
            hide_input_in_errors=True,
        )
        argument_model.model_rebuild(force=True)
        tool.parameters = argument_model.model_json_schema(by_alias=True)

    child_app = server.streamable_http_app()
    return RemoteMCPApplication(server=server, exact_path_app=ExactMCPPathApp(child_app))
