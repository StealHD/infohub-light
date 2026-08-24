"""Single-use preview/confirmation workflow for system setting changes."""

from __future__ import annotations

import hashlib
import hmac
import json
import sqlite3
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Literal, Mapping

from .system_settings import (
    SystemSettingsGenerationConflict,
    SystemSettingsService,
)


SYSTEM_SETTINGS_WRITE_SCOPE = "inteliscope:system-settings:write"
PROPOSAL_TTL_MINUTES = 10
MAX_PENDING_PROPOSALS = 10


class SystemSettingProposalError(ValueError):
    def __init__(self, code: str, message: str) -> None:
        super().__init__(message)
        self.code = code


@dataclass(frozen=True, slots=True)
class SystemSettingsActor:
    workspace_id: str
    user_id: str
    channel: Literal["web", "mcp"]
    delegation_id: str | None = None


def _now(value: datetime | None = None) -> datetime:
    current = value or datetime.now(timezone.utc)
    if current.tzinfo is None:
        return current.replace(tzinfo=timezone.utc)
    return current.astimezone(timezone.utc)


def _parse_time(value: Any) -> datetime:
    return _now(datetime.fromisoformat(str(value).replace("Z", "+00:00")))


def _confirmation_phrase(proposal_id: str) -> str:
    return f"确认执行 {proposal_id[-8:]}"


def _confirmation_hash(phrase: str) -> str:
    return hashlib.sha256(phrase.encode("utf-8")).hexdigest()


def _json(value: Any) -> str:
    return json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":"))


class SystemSettingProposalService:
    def __init__(self, store: Any) -> None:
        self.store = store
        self.settings = SystemSettingsService(store)

    def _require_live_actor(
        self,
        connection: sqlite3.Connection,
        actor: SystemSettingsActor,
    ) -> None:
        user = connection.execute(
            """SELECT workspace_id, role, enabled FROM users WHERE id=?""",
            (actor.user_id,),
        ).fetchone()
        if (
            user is None
            or str(user["workspace_id"]) != actor.workspace_id
            or not bool(user["enabled"])
            or str(user["role"]) not in {"owner", "admin"}
        ):
            raise SystemSettingProposalError(
                "system_settings_admin_required", "live owner or admin is required"
            )
        if actor.channel != "mcp":
            return
        delegation = connection.execute(
            """SELECT workspace_id, user_id, scopes_json, expires_at, revoked_at
               FROM agent_delegations WHERE id=?""",
            (actor.delegation_id,),
        ).fetchone()
        if (
            delegation is None
            or str(delegation["workspace_id"]) != actor.workspace_id
            or str(delegation["user_id"]) != actor.user_id
            or delegation["revoked_at"] is not None
            or _parse_time(delegation["expires_at"]) <= _now()
        ):
            raise SystemSettingProposalError(
                "system_settings_delegation_invalid", "live delegation is required"
            )
        try:
            scopes = json.loads(str(delegation["scopes_json"]))
        except (TypeError, json.JSONDecodeError) as error:
            raise SystemSettingProposalError(
                "system_settings_scope_required", "system settings scope is required"
            ) from error
        if (
            not isinstance(scopes, list)
            or not all(isinstance(scope, str) for scope in scopes)
            or SYSTEM_SETTINGS_WRITE_SCOPE not in scopes
        ):
            raise SystemSettingProposalError(
                "system_settings_scope_required", "system settings scope is required"
            )

    def prepare(
        self,
        actor: SystemSettingsActor,
        *,
        expected_generation: int,
        changes: Mapping[str, Any],
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _now(now)
        expires = current + timedelta(minutes=PROPOSAL_TTL_MINUTES)
        preview = self.settings.preview(
            actor.workspace_id,
            expected_generation=expected_generation,
            changes=changes,
        )
        connection = self.store.connect()
        if connection.in_transaction:
            connection.rollback()
        try:
            connection.execute("BEGIN IMMEDIATE")
            self._require_live_actor(connection, actor)
            connection.execute(
                """UPDATE system_setting_change_proposals
                   SET status='expired', updated_at=?
                   WHERE workspace_id=? AND actor_user_id=? AND actor_channel=?
                     AND status='pending' AND expires_at<=?""",
                (current.isoformat(), actor.workspace_id, actor.user_id,
                 actor.channel, current.isoformat()),
            )
            pending = int(connection.execute(
                """SELECT COUNT(*) FROM system_setting_change_proposals
                   WHERE workspace_id=? AND actor_user_id=? AND actor_channel=?
                     AND status='pending'""",
                (actor.workspace_id, actor.user_id, actor.channel),
            ).fetchone()[0])
            if pending >= MAX_PENDING_PROPOSALS:
                raise SystemSettingProposalError(
                    "system_settings_too_many_pending", "too many pending proposals"
                )
            proposal_id = f"ssp_{uuid.uuid4().hex}"
            confirmation = _confirmation_phrase(proposal_id)
            stamp = current.isoformat()
            connection.execute(
                """INSERT INTO system_setting_change_proposals (
                       id, workspace_id, actor_user_id, delegation_id, actor_channel,
                       base_generation, changes_json, preview_json, confirmation_hash,
                       status, created_at, expires_at, updated_at
                   ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, 'pending', ?, ?, ?)""",
                (
                    proposal_id, actor.workspace_id, actor.user_id,
                    actor.delegation_id, actor.channel, preview["base_generation"],
                    _json(preview["changes"]), _json({
                        "changes": preview["preview_changes"],
                        "warnings": preview["warnings"],
                    }), _confirmation_hash(confirmation), stamp,
                    expires.isoformat(), stamp,
                ),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        return {
            "proposal_id": proposal_id,
            "base_generation": preview["base_generation"],
            "changes": preview["preview_changes"],
            "warnings": preview["warnings"],
            "confirmation": confirmation,
            "expires_at": expires.isoformat(),
        }

    def apply(
        self,
        actor: SystemSettingsActor,
        *,
        proposal_id: str,
        confirmation: str,
        now: datetime | None = None,
    ) -> dict[str, Any]:
        current = _now(now)
        connection = self.store.connect()
        if connection.in_transaction:
            connection.rollback()
        try:
            connection.execute("BEGIN IMMEDIATE")
            row = connection.execute(
                "SELECT * FROM system_setting_change_proposals WHERE id=?",
                (proposal_id,),
            ).fetchone()
            if row is None or any((
                str(row["workspace_id"]) != actor.workspace_id,
                str(row["actor_user_id"]) != actor.user_id,
                str(row["actor_channel"]) != actor.channel,
                (row["delegation_id"] or None) != actor.delegation_id,
            )):
                raise SystemSettingProposalError(
                    "system_settings_proposal_not_found", "proposal not found"
                )
            if str(row["status"]) != "pending":
                raise SystemSettingProposalError(
                    "system_settings_proposal_not_pending", "proposal is not pending"
                )
            if _parse_time(row["expires_at"]) <= current:
                connection.execute(
                    """UPDATE system_setting_change_proposals
                       SET status='expired', updated_at=? WHERE id=?""",
                    (current.isoformat(), proposal_id),
                )
                connection.commit()
                raise SystemSettingProposalError(
                    "system_settings_proposal_expired", "proposal expired"
                )
            if not hmac.compare_digest(
                str(row["confirmation_hash"]), _confirmation_hash(confirmation)
            ):
                raise SystemSettingProposalError(
                    "system_settings_confirmation_mismatch", "confirmation mismatch"
                )
            self._require_live_actor(connection, actor)
            overrides, generation = self.settings.state(
                actor.workspace_id, connection=connection
            )
            if generation != int(row["base_generation"]):
                raise SystemSettingsGenerationConflict(
                    "system settings generation changed"
                )
            changes = json.loads(str(row["changes_json"]))
            validated = self.settings.preview(
                actor.workspace_id,
                expected_generation=generation,
                changes=changes,
                connection=connection,
            )
            next_overrides = validated["next_overrides"]
            next_generation = generation + 1
            stamp = current.isoformat()
            cursor = connection.execute(
                """UPDATE workspace_system_settings
                   SET overrides_json=?, generation=?, updated_by_user_id=?, updated_at=?
                   WHERE workspace_id=? AND generation=?""",
                (_json(next_overrides), next_generation, actor.user_id, stamp,
                 actor.workspace_id, generation),
            )
            if cursor.rowcount != 1:
                raise SystemSettingsGenerationConflict(
                    "system settings generation changed"
                )
            result = {
                "proposal_id": proposal_id,
                "generation": next_generation,
                "changed_keys": sorted(changes),
            }
            connection.execute(
                """UPDATE system_setting_change_proposals
                   SET status='applied', applied_at=?, result_summary_json=?, updated_at=?
                   WHERE id=? AND status='pending'""",
                (stamp, _json(result), stamp, proposal_id),
            )
            connection.commit()
        except Exception:
            if connection.in_transaction:
                connection.rollback()
            raise
        return result


__all__ = [
    "SYSTEM_SETTINGS_WRITE_SCOPE", "SystemSettingProposalError",
    "SystemSettingProposalService", "SystemSettingsActor",
]
