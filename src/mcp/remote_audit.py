"""Redacted audit lifecycle for Remote MCP calls."""

from __future__ import annotations

import logging
import re
import time
import uuid
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from mcp.server.auth.middleware.auth_context import get_access_token
from mcp.server.auth.provider import AccessToken

from ..services.agent_change_proposal import DelegatedActor
from ..services.operation_log import safe_emit_operation_event


_LOGGER = logging.getLogger("src.mcp.remote_server")
_AUDIT_VALUE_RE = re.compile(r"[A-Za-z0-9_.:-]{1,128}\Z")
_DENIED_OUTCOMES = {
    "unauthorized",
    "forbidden",
    "invalid_request",
    "write_scope_required",
    "diagnostics_scope_required",
    "diagnostics_filter_required",
    "system_settings_scope_required",
    "system_settings_writes_disabled",
    "rate_limited",
}


def audit_value(value: Any) -> str:
    candidate = str(value or "")
    return candidate if _AUDIT_VALUE_RE.fullmatch(candidate) else "-"


@dataclass(slots=True)
class ToolCallState:
    tool_name: str
    delegation_id: str
    request_id: str
    started: float
    outcome: str
    logged_proposal_id: str
    logged_action: str
    actor: DelegatedActor | None = None


def begin_tool_call(
    tool_name: str,
    *,
    audit_action: str,
    audit_proposal_id: str,
) -> tuple[ToolCallState, AccessToken | None]:
    access = get_access_token()
    return (
        ToolCallState(
            tool_name=tool_name,
            delegation_id=str(access.token if access is not None else ""),
            request_id=f"mcp_{uuid.uuid4().hex}",
            started=time.perf_counter(),
            outcome="ok",
            logged_proposal_id=audit_value(audit_proposal_id),
            logged_action=audit_value(audit_action),
        ),
        access,
    )


def record_tool_result(state: ToolCallState, result: Any) -> None:
    if not isinstance(result, dict):
        return
    state.logged_proposal_id = audit_value(
        result.get("proposal_id") or state.logged_proposal_id
    )
    preview = result.get("preview")
    result_summary = result.get("result")
    result_action = (
        preview.get("action") if isinstance(preview, dict) else None
    ) or (
        result_summary.get("action") if isinstance(result_summary, dict) else None
    )
    if result_action:
        state.logged_action = audit_value(result_action)
    if (
        state.actor is not None
        and state.tool_name == "apply_subscription_change"
        and isinstance(result_summary, dict)
        and result_action in {"created", "updated", "deleted"}
    ):
        safe_emit_operation_event(
            category="subscription",
            action=f"mcp_{result_action}",
            outcome="succeeded",
            workspace_id=state.actor.workspace_id,
            actor_user_id=state.actor.user_id,
            request_id=state.request_id,
            source_id=result_summary.get("source_id"),
            subscription_id=result_summary.get("subscription_id"),
        )


def finish_tool_call(state: ToolCallState) -> None:
    elapsed_ms = int((time.perf_counter() - state.started) * 1000)
    _LOGGER.info(
        "remote_mcp_call delegation_id=%s tool=%s proposal_id=%s "
        "action=%s outcome=%s elapsed_ms=%s request_id=%s",
        state.delegation_id,
        state.tool_name,
        state.logged_proposal_id,
        state.logged_action,
        state.outcome,
        elapsed_ms,
        state.request_id,
    )
    if state.actor is None:
        return
    operation_outcome = (
        "succeeded"
        if state.outcome == "ok"
        else "denied" if state.outcome in _DENIED_OUTCOMES else "failed"
    )
    safe_emit_operation_event(
        category="agent",
        action=f"mcp.{state.tool_name}",
        outcome=operation_outcome,
        level=(
            "info"
            if operation_outcome == "succeeded"
            else "warning" if operation_outcome == "denied" else "error"
        ),
        workspace_id=state.actor.workspace_id,
        actor_user_id=state.actor.user_id,
        request_id=state.request_id,
        stage=(
            "workspace_diagnostics"
            if state.tool_name == "query_operation_logs"
            and state.logged_action == "diagnostics_workspace"
            else None
        ),
        error_code=None if state.outcome == "ok" else state.outcome,
        duration_ms=elapsed_ms,
    )


def record_rejected_call(
    *,
    principal_resolver: Callable[[str], dict[str, Any] | None],
    delegation_id: str,
    tool_name: str,
    request_id: str,
    error_code: str,
    elapsed_ms: int,
) -> None:
    try:
        principal = principal_resolver(delegation_id)
    except Exception:
        return
    if principal is None:
        return
    safe_emit_operation_event(
        category="agent",
        action=f"mcp.{tool_name}",
        outcome="denied",
        level="warning",
        workspace_id=principal.get("workspace_id"),
        actor_user_id=principal.get("user_id"),
        request_id=request_id,
        error_code=error_code,
        duration_ms=elapsed_ms,
    )


def log_rejected_call(
    *,
    delegation_id: str,
    tool_name: str,
    request_id: str,
    outcome: str,
    elapsed_ms: int,
) -> None:
    _LOGGER.log(
        logging.WARNING if outcome == "rate_limited" else logging.INFO,
        "remote_mcp_call delegation_id=%s tool=%s proposal_id=%s "
        "action=%s outcome=%s elapsed_ms=%s request_id=%s",
        delegation_id,
        tool_name,
        "-",
        "-",
        outcome,
        elapsed_ms,
        request_id,
    )
