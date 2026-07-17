"""Authorization and persistence for prepared Agent subscription changes."""

from __future__ import annotations

import hashlib
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any, Callable

from ..storage.service_store import (
    AGENT_DELEGATION_READ_SCOPE,
    AGENT_DELEGATION_WRITE_SCOPE,
    AgentProposalLimitError,
    ServiceStore,
)
from .subscription_mutation import SubscriptionActor, SubscriptionChangePlan


_WRITABLE_ROLES = {"owner", "admin", "member"}
_PLAN_SNAPSHOT_KEYS = {
    "version",
    "kind",
    "normalized",
    "preview",
    "targets",
    "fingerprints",
}


@dataclass(frozen=True, slots=True)
class DelegatedActor(SubscriptionActor):
    delegation_id: str
    scopes: tuple[str, ...]


class AgentProposalError(ValueError):
    """Stable, non-sensitive error returned by proposal-facing adapters."""

    def __init__(
        self,
        code: str,
        message: str,
        *,
        status_code: int = 400,
    ) -> None:
        super().__init__(message)
        self.code = code
        self.status_code = status_code


class AgentChangeProposalService:
    """Prepare sealed mutation plans after re-reading live delegation state."""

    def __init__(
        self,
        store: ServiceStore,
        *,
        writes_enabled: Callable[[], Any] | Any,
        now: Callable[[], datetime] | None = None,
    ) -> None:
        self.store = store
        self._writes_enabled_provider = writes_enabled
        self.now = now or (lambda: datetime.now(timezone.utc))

    def _writes_enabled(self) -> bool:
        value = (
            self._writes_enabled_provider()
            if callable(self._writes_enabled_provider)
            else self._writes_enabled_provider
        )
        if hasattr(value, "subscription_writes_enabled"):
            value = value.subscription_writes_enabled
        return value is True

    @staticmethod
    def _unauthorized() -> AgentProposalError:
        return AgentProposalError(
            "unauthorized", "delegation is not authorized", status_code=401
        )

    def _live_actor(self, actor: DelegatedActor) -> DelegatedActor:
        if not isinstance(actor, DelegatedActor):
            raise self._unauthorized()
        principal = self.store.get_active_agent_delegation_principal(
            actor.delegation_id
        )
        if principal is None:
            raise self._unauthorized()
        if (
            str(principal.get("workspace_id")) != actor.workspace_id
            or str(principal.get("user_id")) != actor.user_id
            or str(principal.get("delegation_id")) != actor.delegation_id
        ):
            raise self._unauthorized()
        live_scopes = tuple(principal.get("scopes") or ())
        if len(actor.scopes) != len(set(actor.scopes)) or set(actor.scopes) != set(
            live_scopes
        ):
            raise self._unauthorized()
        live_role = str(principal.get("role") or "")
        if live_role not in _WRITABLE_ROLES:
            raise AgentProposalError(
                "forbidden",
                "viewer cannot modify subscriptions",
                status_code=403,
            )
        if actor.role != live_role:
            raise self._unauthorized()
        return DelegatedActor(
            workspace_id=str(principal["workspace_id"]),
            user_id=str(principal["user_id"]),
            role=live_role,
            delegation_id=str(principal["delegation_id"]),
            scopes=live_scopes,
        )

    def require_read_actor(self, actor: DelegatedActor) -> DelegatedActor:
        """Revalidate a read caller while allowing the viewer role."""

        if (
            not isinstance(actor, DelegatedActor)
            or AGENT_DELEGATION_READ_SCOPE not in actor.scopes
        ):
            raise self._unauthorized()
        principal = self.store.get_active_agent_delegation_principal(
            actor.delegation_id
        )
        if principal is None:
            raise self._unauthorized()
        live_scopes = tuple(principal.get("scopes") or ())
        if (
            str(principal.get("workspace_id")) != actor.workspace_id
            or str(principal.get("user_id")) != actor.user_id
            or str(principal.get("delegation_id")) != actor.delegation_id
            or str(principal.get("role")) != actor.role
            or len(actor.scopes) != len(set(actor.scopes))
            or set(actor.scopes) != set(live_scopes)
            or AGENT_DELEGATION_READ_SCOPE not in live_scopes
        ):
            raise self._unauthorized()
        return DelegatedActor(
            workspace_id=str(principal["workspace_id"]),
            user_id=str(principal["user_id"]),
            role=str(principal["role"]),
            delegation_id=str(principal["delegation_id"]),
            scopes=live_scopes,
        )

    def require_write_actor(self, actor: DelegatedActor) -> DelegatedActor:
        """Apply the fixed flag -> scope -> live-role authorization order."""

        if not self._writes_enabled():
            raise AgentProposalError(
                "subscription_writes_disabled",
                "subscription writes are disabled",
                status_code=409,
            )
        if (
            not isinstance(actor, DelegatedActor)
            or AGENT_DELEGATION_WRITE_SCOPE not in actor.scopes
        ):
            raise AgentProposalError(
                "write_scope_required",
                "subscription write scope is required",
                status_code=403,
            )
        return self._live_actor(actor)

    @staticmethod
    def _validated_snapshot(plan: SubscriptionChangePlan) -> dict[str, Any]:
        if not isinstance(plan, SubscriptionChangePlan):
            raise AgentProposalError(
                "invalid_plan_snapshot", "invalid subscription change plan"
            )
        try:
            snapshot = plan.to_snapshot()
        except Exception as exc:
            raise AgentProposalError(
                "invalid_plan_snapshot", "invalid subscription change plan"
            ) from exc
        if (
            not isinstance(snapshot, dict)
            or set(snapshot) != _PLAN_SNAPSHOT_KEYS
            or snapshot.get("version") != 2
            or snapshot.get("kind") not in {"create", "update", "delete"}
            or not isinstance(snapshot.get("normalized"), dict)
            or not isinstance(snapshot.get("preview"), dict)
            or not isinstance(snapshot.get("targets"), dict)
            or not isinstance(snapshot.get("fingerprints"), dict)
        ):
            raise AgentProposalError(
                "invalid_plan_snapshot", "invalid subscription change plan"
            )
        return snapshot

    @staticmethod
    def _utc(value: datetime) -> datetime:
        if not isinstance(value, datetime) or value.tzinfo is None:
            raise AgentProposalError(
                "invalid_plan_snapshot", "proposal clock is invalid"
            )
        return value.astimezone(timezone.utc)

    @staticmethod
    def _verify_stored_row(
        row: dict[str, Any],
        *,
        proposal_id: str,
        actor: DelegatedActor,
        snapshot: dict[str, Any],
        confirmation_hash: str,
    ) -> None:
        targets = snapshot["targets"]
        duplicate_targets = {
            key: value
            for key, value in {
                "source_id": row.get("source_id"),
                "subscription_id": row.get("subscription_id"),
            }.items()
            if value is not None
        }
        try:
            created_at = datetime.fromisoformat(str(row["created_at"]))
            expires_at = datetime.fromisoformat(str(row["expires_at"]))
        except (KeyError, TypeError, ValueError) as exc:
            raise AgentProposalError(
                "invalid_plan_snapshot", "stored proposal is invalid"
            ) from exc
        if (
            row.get("id") != proposal_id
            or row.get("workspace_id") != actor.workspace_id
            or row.get("user_id") != actor.user_id
            or row.get("delegation_id") != actor.delegation_id
            or row.get("status") != "pending"
            or row.get("kind") != snapshot["kind"]
            or row.get("payload") != {"plan_snapshot": snapshot}
            or row.get("preview") != snapshot["preview"]
            or row.get("fingerprints") != snapshot["fingerprints"]
            or duplicate_targets != targets
            or row.get("confirmation_hash") != confirmation_hash
            or created_at.tzinfo is None
            or expires_at.tzinfo is None
            or expires_at.astimezone(timezone.utc)
            - created_at.astimezone(timezone.utc)
            != timedelta(minutes=10)
        ):
            raise AgentProposalError(
                "invalid_plan_snapshot", "stored proposal is invalid"
            )

    def prepare(
        self,
        actor: DelegatedActor,
        plan: SubscriptionChangePlan,
    ) -> dict[str, Any]:
        """Persist one complete v2 plan; return its plaintext phrase once."""

        live_actor = self.require_write_actor(actor)
        snapshot = self._validated_snapshot(plan)
        proposal_id = f"agp_{uuid.uuid4().hex}"
        confirmation_text = f"确认执行 {proposal_id[-8:]}"
        confirmation_hash = hashlib.sha256(
            confirmation_text.encode("utf-8")
        ).hexdigest()
        requested_created_at = self._utc(self.now())
        conn = self.store.connect()
        if conn.in_transaction:
            raise AgentProposalError(
                "invalid_plan_snapshot", "proposal prepare requires its own transaction"
            )
        try:
            conn.execute("BEGIN IMMEDIATE")
            row = self.store.create_agent_change_proposal(
                proposal_id=proposal_id,
                workspace_id=live_actor.workspace_id,
                user_id=live_actor.user_id,
                delegation_id=live_actor.delegation_id,
                kind=str(snapshot["kind"]),
                source_id=snapshot["targets"].get("source_id"),
                subscription_id=snapshot["targets"].get("subscription_id"),
                payload={"plan_snapshot": snapshot},
                preview=snapshot["preview"],
                fingerprints=snapshot["fingerprints"],
                confirmation_hash=confirmation_hash,
                created_at=requested_created_at.isoformat(),
                expires_at=(requested_created_at + timedelta(minutes=10)).isoformat(),
                commit=False,
            )
            self._verify_stored_row(
                row,
                proposal_id=proposal_id,
                actor=live_actor,
                snapshot=snapshot,
                confirmation_hash=confirmation_hash,
            )
            conn.commit()
        except AgentProposalLimitError as exc:
            if conn.in_transaction:
                conn.rollback()
            raise AgentProposalError(
                "proposal_limit",
                "pending proposal limit reached",
                status_code=429,
            ) from exc
        except AgentProposalError:
            if conn.in_transaction:
                conn.rollback()
            raise
        except (KeyError, LookupError, TypeError, ValueError) as exc:
            if conn.in_transaction:
                conn.rollback()
            raise AgentProposalError(
                "invalid_plan_snapshot", "invalid subscription change plan"
            ) from exc
        except Exception:
            if conn.in_transaction:
                conn.rollback()
            raise
        return {
            "proposal_id": row["id"],
            "kind": row["kind"],
            "preview": row["preview"],
            "created_at": row["created_at"],
            "expires_at": row["expires_at"],
            "confirmation_text": confirmation_text,
        }
