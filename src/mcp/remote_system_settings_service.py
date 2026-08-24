"""Admin-only Remote MCP adapter for workspace system settings."""

from __future__ import annotations

from typing import Any

from ..services.agent_change_proposal import AgentProposalError, DelegatedActor
from ..services.operation_log import safe_emit_operation_event
from ..services.system_settings import (
    SystemSettingsGenerationConflict,
    SystemSettingsService,
    SystemSettingsUnavailable,
)
from ..services.system_settings_proposals import (
    SystemSettingProposalError,
    SystemSettingProposalService,
    SystemSettingsActor,
)
from ..services.system_settings_registry import InvalidSystemSetting
from ..storage.service_store import AGENT_DELEGATION_SYSTEM_SETTINGS_WRITE_SCOPE


class RemoteMCPSystemSettingsService:
    def __init__(self, store: Any, *, writes_enabled: bool) -> None:
        self.store = store
        self.settings = SystemSettingsService(store)
        self.proposals = SystemSettingProposalService(store)
        self.writes_enabled = bool(writes_enabled)

    @staticmethod
    def _system_actor(actor: DelegatedActor) -> SystemSettingsActor:
        return SystemSettingsActor(
            workspace_id=actor.workspace_id,
            user_id=actor.user_id,
            channel="mcp",
            delegation_id=actor.delegation_id,
        )

    def _require_actor(self, actor: DelegatedActor, *, write: bool) -> None:
        if (
            actor.role not in {"owner", "admin"}
            or AGENT_DELEGATION_SYSTEM_SETTINGS_WRITE_SCOPE not in actor.scopes
        ):
            raise AgentProposalError(
                "system_settings_scope_required",
                "system settings scope is required",
                status_code=403,
            )
        if write and not self.writes_enabled:
            raise AgentProposalError(
                "system_settings_writes_disabled",
                "system settings writes are disabled",
                status_code=409,
            )

    @staticmethod
    def _translate(error: Exception) -> AgentProposalError:
        if isinstance(error, InvalidSystemSetting):
            return AgentProposalError(error.code, str(error), status_code=400)
        if isinstance(error, SystemSettingsUnavailable):
            return AgentProposalError(error.code, str(error), status_code=503)
        if isinstance(error, SystemSettingsGenerationConflict):
            return AgentProposalError(error.code, str(error), status_code=409)
        if isinstance(error, SystemSettingProposalError):
            return AgentProposalError(error.code, str(error), status_code=409)
        return AgentProposalError(
            "system_settings_unavailable", "system settings are unavailable",
            status_code=503,
        )

    def list_system_settings(self, *, actor: DelegatedActor) -> dict[str, Any]:
        self._require_actor(actor, write=False)
        try:
            return self.settings.list_settings(actor.workspace_id)
        except (InvalidSystemSetting, SystemSettingsUnavailable) as error:
            raise self._translate(error) from None

    def prepare_update_system_settings(
        self,
        *,
        actor: DelegatedActor,
        expected_generation: int,
        changes: dict[str, Any],
    ) -> dict[str, Any]:
        self._require_actor(actor, write=True)
        try:
            return self.proposals.prepare(
                self._system_actor(actor),
                expected_generation=expected_generation,
                changes=changes,
            )
        except (
            InvalidSystemSetting,
            SystemSettingsUnavailable,
            SystemSettingsGenerationConflict,
            SystemSettingProposalError,
        ) as error:
            raise self._translate(error) from None

    def apply_system_settings_change(
        self,
        *,
        actor: DelegatedActor,
        proposal_id: str,
        confirmation_text: str,
    ) -> dict[str, Any]:
        self._require_actor(actor, write=True)
        try:
            result = self.proposals.apply(
                self._system_actor(actor),
                proposal_id=proposal_id,
                confirmation=confirmation_text,
            )
        except (
            InvalidSystemSetting,
            SystemSettingsUnavailable,
            SystemSettingsGenerationConflict,
            SystemSettingProposalError,
        ) as error:
            raise self._translate(error) from None
        safe_emit_operation_event(
            category="system_settings",
            action="mcp_apply",
            outcome="succeeded",
            workspace_id=actor.workspace_id,
            actor_user_id=actor.user_id,
            changed_fields=result["changed_keys"],
            counts={"settings": len(result["changed_keys"])},
        )
        return result


__all__ = ["RemoteMCPSystemSettingsService"]
