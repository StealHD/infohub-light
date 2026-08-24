"""Remote MCP composition root and explicit compatibility facade."""

from __future__ import annotations

from collections.abc import Callable

from mcp.server.auth.settings import AuthSettings
from mcp.server.transport_security import TransportSecuritySettings
from pydantic import AnyHttpUrl

from ..services.agent_change_proposal import AgentChangeProposalService
from ..services.operation_log import OperationLogQueryService
from ..services.runtime_status import RuntimeStatusService
from ..services.subscription_mutation import SubscriptionMutationService
from ..storage.service_store import AGENT_DELEGATION_READ_SCOPE, ServiceStore
from .remote_auth import AgentDelegationTokenVerifier
from .remote_call_runtime import RemoteMCPCallRuntime, SafeRemoteMCP
from .remote_config import RemoteMCPSettings
from .remote_diagnostics import RemoteMCPDiagnostics
from .remote_http import ExactMCPPathApp, RemoteMCPApplication
from .remote_rate_limit import DelegationRateLimiter
from .remote_service import RemoteMCPReadService
from .remote_subscription_service import RemoteMCPSubscriptionService
from .remote_system_settings_service import RemoteMCPSystemSettingsService
from .remote_tool_registration import register_remote_tools
from .remote_tool_annotations import (
    APPLY_ANNOTATIONS,
    OPEN_WORLD_READ_ANNOTATIONS,
    PREPARE_ANNOTATIONS,
    READ_ANNOTATIONS,
    finalize_tool_schemas,
)
from .remote_tool_context import RemoteMCPPrincipalContext, RemoteMCPToolContext


__all__ = [
    "APPLY_ANNOTATIONS",
    "AgentDelegationTokenVerifier",
    "DelegationRateLimiter",
    "ExactMCPPathApp",
    "OPEN_WORLD_READ_ANNOTATIONS",
    "PREPARE_ANNOTATIONS",
    "READ_ANNOTATIONS",
    "RemoteMCPApplication",
    "SafeRemoteMCP",
    "create_remote_mcp",
]


def _create_server(
    store: ServiceStore,
    settings: RemoteMCPSettings,
) -> SafeRemoteMCP:
    return SafeRemoteMCP(
        "Inteliscope",
        limiter=DelegationRateLimiter(),
        principal_resolver=store.get_active_agent_delegation_principal,
        instructions=(
            "User-scoped Inteliscope information and controlled subscription tools."
        ),
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


def _create_tool_context(
    store: ServiceStore,
    settings: RemoteMCPSettings,
    *,
    mutation_service: SubscriptionMutationService,
    runtime_status: RuntimeStatusService,
    operation_logs: OperationLogQueryService,
    secret_is_set: Callable[[str], bool],
) -> RemoteMCPToolContext:
    proposals = AgentChangeProposalService(
        store,
        writes_enabled=settings.subscription_writes_enabled,
        mutations=mutation_service,
    )
    subscriptions = RemoteMCPSubscriptionService(
        store=store,
        mutations=mutation_service,
        proposals=proposals,
        secret_is_set=secret_is_set,
    )
    principals = RemoteMCPPrincipalContext(store, operation_logs)
    return RemoteMCPToolContext(
        read_service=RemoteMCPReadService(store),
        subscription_service=subscriptions,
        system_settings=RemoteMCPSystemSettingsService(store, writes_enabled=settings.system_settings_writes_enabled),
        diagnostics=RemoteMCPDiagnostics(
            store,
            runtime_status=runtime_status,
            secret_is_set=secret_is_set,
        ),
        principals=principals,
        calls=RemoteMCPCallRuntime(principals),
    )


def create_remote_mcp(
    store: ServiceStore,
    settings: RemoteMCPSettings,
    *,
    mutation_service: SubscriptionMutationService,
    runtime_status: RuntimeStatusService,
    operation_logs: OperationLogQueryService,
    secret_is_set: Callable[[str], bool],
) -> RemoteMCPApplication:
    """Create a fresh MCP server/session manager for one FastAPI application."""

    if not settings.enabled:
        raise ValueError("Remote MCP must be enabled before creating its server")
    server = _create_server(store, settings)
    context = _create_tool_context(
        store,
        settings,
        mutation_service=mutation_service,
        runtime_status=runtime_status,
        operation_logs=operation_logs,
        secret_is_set=secret_is_set,
    )
    register_remote_tools(server, context)
    finalize_tool_schemas(server)
    return RemoteMCPApplication(
        server=server,
        exact_path_app=ExactMCPPathApp(server.streamable_http_app()),
    )
