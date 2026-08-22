"""Safe dispatch and call lifecycle for Remote MCP tools."""

from __future__ import annotations

import time
import uuid
from collections.abc import Awaitable, Callable
from typing import Any, NoReturn, TypeVar

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.fastmcp import FastMCP
from mcp.server.fastmcp.exceptions import ToolError
from pydantic import ValidationError

from ..services.agent_change_proposal import AgentProposalError
from ..services.source_type_registry import SourceConfigError
from ..services.subscription_mutation import SubscriptionMutationError
from .remote_audit import (
    ToolCallState,
    audit_value,
    begin_tool_call,
    finish_tool_call,
    log_rejected_call,
    record_rejected_call,
    record_tool_result,
)
from .remote_rate_limit import DelegationRateLimiter
from .remote_service import RemoteMCPNotFound
from .remote_tool_context import RemoteMCPPrincipalContext


_Result = TypeVar("_Result")
_CREATE_SOURCE_SHAPE_HINT = (
    "invalid_request: source must use either "
    "{mode: existing, source_id}, "
    "{mode: resolved, resolution_ref}, or "
    "{mode: private, type, display_name, config}"
)


class SafeRemoteMCP(FastMCP):
    """Enforce delegation limits and safe validation before business dispatch."""

    def __init__(
        self,
        *args: Any,
        limiter: DelegationRateLimiter,
        principal_resolver: Callable[[str], dict[str, Any] | None],
        **kwargs: Any,
    ) -> None:
        super().__init__(*args, **kwargs)
        self._delegation_limiter = limiter
        self._principal_resolver = principal_resolver

    async def call_tool(self, name: str, arguments: dict[str, Any]) -> Any:
        request_id = f"mcp_{uuid.uuid4().hex}"
        started = time.perf_counter()
        tool = self._tool_manager.get_tool(name)
        if tool is None:
            return await super().call_tool(name, arguments)
        access = get_access_token()
        delegation_id = access.token if access is not None else None
        if not isinstance(delegation_id, str) or not delegation_id:
            return await super().call_tool(name, arguments)
        if not self._delegation_limiter.allow(delegation_id):
            self._reject_call(
                delegation_id=delegation_id,
                tool_name=name,
                request_id=request_id,
                outcome="rate_limited",
                started=started,
            )
        try:
            pre_parsed = tool.fn_metadata.pre_parse_json(arguments)
            tool.fn_metadata.arg_model.model_validate(pre_parsed)
        except (ValidationError, ValueError, RecursionError) as exc:
            self._reject_invalid_call(
                delegation_id=delegation_id,
                tool_name=name,
                request_id=request_id,
                started=started,
                exc=exc,
            )
        return await super().call_tool(name, arguments)

    def _reject_call(
        self,
        *,
        delegation_id: str,
        tool_name: str,
        request_id: str,
        outcome: str,
        started: float,
        message: str | None = None,
    ) -> NoReturn:
        elapsed_ms = int((time.perf_counter() - started) * 1000)
        log_rejected_call(
            delegation_id=delegation_id,
            tool_name=tool_name,
            request_id=request_id,
            outcome=outcome,
            elapsed_ms=elapsed_ms,
        )
        record_rejected_call(
            principal_resolver=self._principal_resolver,
            delegation_id=delegation_id,
            tool_name=tool_name,
            request_id=request_id,
            error_code=outcome,
            elapsed_ms=elapsed_ms,
        )
        raise ToolError(message or outcome) from None

    def _reject_invalid_call(
        self,
        *,
        delegation_id: str,
        tool_name: str,
        request_id: str,
        started: float,
        exc: Exception,
    ) -> NoReturn:
        message = "invalid_request"
        if tool_name == "prepare_create_subscription" and isinstance(
            exc, ValidationError
        ):
            errors = exc.errors(
                include_url=False,
                include_context=False,
                include_input=False,
            )
            if any(
                detail.get("loc") == ("source",)
                and detail.get("type")
                in {"union_tag_invalid", "union_tag_not_found"}
                for detail in errors
            ):
                message = _CREATE_SOURCE_SHAPE_HINT
        self._reject_call(
            delegation_id=delegation_id,
            tool_name=tool_name,
            request_id=request_id,
            outcome="invalid_request",
            started=started,
            message=message,
        )


class RemoteMCPCallRuntime:
    """Resolve one actor, dispatch one service call, and close its audit."""

    def __init__(self, principals: RemoteMCPPrincipalContext) -> None:
        self._principals = principals

    def run_tool(
        self,
        tool_name: str,
        operation: Callable[..., _Result],
        *,
        actor_operation: bool = False,
        audit_action: str = "-",
        audit_proposal_id: str = "-",
        **kwargs: Any,
    ) -> _Result:
        state, access = begin_tool_call(
            tool_name,
            audit_action=audit_action,
            audit_proposal_id=audit_proposal_id,
        )
        try:
            state.actor = self._principals.actor_from_access(access)
            result = operation(
                **self._operation_kwargs(state, actor_operation, kwargs)
            )
            record_tool_result(state, result)
            return result
        except Exception as exc:
            self._raise_tool_error(state, exc)
        finally:
            finish_tool_call(state)

    async def run_async_tool(
        self,
        tool_name: str,
        operation: Callable[..., Awaitable[_Result]],
        *,
        actor_operation: bool = False,
        audit_action: str = "-",
        audit_proposal_id: str = "-",
        **kwargs: Any,
    ) -> _Result:
        state, access = begin_tool_call(
            tool_name,
            audit_action=audit_action,
            audit_proposal_id=audit_proposal_id,
        )
        try:
            state.actor = self._principals.actor_from_access(access)
            result = await operation(
                **self._operation_kwargs(state, actor_operation, kwargs)
            )
            record_tool_result(state, result)
            return result
        except Exception as exc:
            self._raise_tool_error(state, exc)
        finally:
            finish_tool_call(state)

    @staticmethod
    def _operation_kwargs(
        state: ToolCallState,
        actor_operation: bool,
        kwargs: dict[str, Any],
    ) -> dict[str, Any]:
        actor = state.actor
        if actor is None:
            raise RuntimeError("tool actor was not initialized")
        if actor_operation:
            return {"actor": actor, **kwargs}
        return {
            "workspace_id": actor.workspace_id,
            "user_id": actor.user_id,
            **kwargs,
        }

    @staticmethod
    def _raise_tool_error(state: ToolCallState, exc: Exception) -> NoReturn:
        if isinstance(exc, RemoteMCPNotFound):
            state.outcome = "not_found"
            raise ToolError("not_found") from None
        if isinstance(exc, (AgentProposalError, SubscriptionMutationError)):
            state.outcome = audit_value(exc.code)
            raise ToolError(state.outcome) from None
        if isinstance(exc, SourceConfigError):
            state.outcome = "invalid_request"
            raise ToolError("invalid_request") from None
        state.outcome = "internal_error"
        raise ToolError(f"internal_error request_id={state.request_id}") from None
