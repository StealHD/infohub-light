"""Typed service and delegated-principal context for Remote MCP tools."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from dataclasses import dataclass
from typing import Any, Literal, Protocol, TypeVar

from mcp.server.auth.provider import AccessToken

from ..services.agent_change_proposal import AgentProposalError, DelegatedActor
from ..services.operation_log import OperationLogQueryService
from ..storage.service_store import (
    AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE,
    ServiceStore,
)
from .remote_diagnostics import RemoteMCPDiagnostics
from .remote_service import RemoteMCPReadService
from .remote_subscription_service import RemoteMCPSubscriptionService


_Result = TypeVar("_Result")


class RemoteMCPCallPort(Protocol):
    def run_tool(
        self,
        tool_name: str,
        operation: Callable[..., _Result],
        *,
        actor_operation: bool = False,
        audit_action: str = "-",
        audit_proposal_id: str = "-",
        **kwargs: Any,
    ) -> _Result: ...

    async def run_async_tool(
        self,
        tool_name: str,
        operation: Callable[..., Awaitable[_Result]],
        *,
        actor_operation: bool = False,
        audit_action: str = "-",
        audit_proposal_id: str = "-",
        **kwargs: Any,
    ) -> _Result: ...


class RemoteMCPPrincipalContext:
    """Resolve the authenticated delegation and enforce diagnostics scope."""

    def __init__(
        self,
        store: ServiceStore,
        operation_logs: OperationLogQueryService,
    ) -> None:
        self._store = store
        self._operation_logs = operation_logs

    def principal_from_access(self, access: AccessToken | None) -> dict[str, Any]:
        delegation_id = access.token if access is not None else ""
        principal = (
            self._store.get_active_agent_delegation_principal(delegation_id)
            if isinstance(delegation_id, str) and delegation_id
            else None
        )
        if principal is None:
            raise AgentProposalError(
                "unauthorized", "delegation is not authorized", status_code=401
            )
        return principal

    def actor_from_access(self, access: AccessToken | None) -> DelegatedActor:
        principal = self.principal_from_access(access)
        scopes = principal.get("scopes")
        required_values = (
            principal.get("workspace_id"),
            principal.get("user_id"),
            principal.get("role"),
            principal.get("delegation_id"),
        )
        if (
            not all(isinstance(value, str) and value for value in required_values)
            or not isinstance(scopes, list)
        ):
            raise AgentProposalError(
                "unauthorized", "delegation is not authorized", status_code=401
            )
        return DelegatedActor(
            workspace_id=str(principal["workspace_id"]),
            user_id=str(principal["user_id"]),
            role=str(principal["role"]),
            delegation_id=str(principal["delegation_id"]),
            scopes=tuple(str(scope) for scope in scopes),
        )

    def query_operation_logs_for_actor(
        self,
        *,
        actor: DelegatedActor,
        scope: Literal["self", "workspace"],
        **kwargs: Any,
    ) -> dict[str, Any]:
        if scope == "workspace":
            self._require_workspace_diagnostics(actor, kwargs)
        return self._operation_logs.query(
            workspace_id=actor.workspace_id,
            user_id=actor.user_id,
            scope=scope,
            **kwargs,
        )

    @staticmethod
    def _require_workspace_diagnostics(
        actor: DelegatedActor,
        filters: dict[str, Any],
    ) -> None:
        if actor.role not in {"owner", "admin"} or (
            AGENT_DELEGATION_DIAGNOSTICS_READ_SCOPE not in actor.scopes
        ):
            raise AgentProposalError(
                "diagnostics_scope_required",
                "workspace diagnostics require an explicitly delegated "
                "owner or admin connection",
                status_code=403,
            )
        identity_fields = ("job_id", "source_id", "subscription_id", "request_id")
        if filters.get("minimum_level") == "info" and not any(
            filters.get(field) for field in identity_fields
        ):
            raise AgentProposalError(
                "diagnostics_filter_required",
                "workspace diagnostics require an identifier filter "
                "or warning/error minimum level",
                status_code=400,
            )


@dataclass(frozen=True, slots=True)
class RemoteMCPToolContext:
    read_service: RemoteMCPReadService
    subscription_service: RemoteMCPSubscriptionService
    diagnostics: RemoteMCPDiagnostics
    principals: RemoteMCPPrincipalContext
    calls: RemoteMCPCallPort
