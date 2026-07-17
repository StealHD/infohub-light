"""Safe source discovery and prepare-only subscription proposal facade."""

from __future__ import annotations

from typing import Any, Callable

from ..services.agent_change_proposal import (
    AgentChangeProposalService,
    AgentProposalError,
    DelegatedActor,
)
from ..services.source_type_registry import (
    catalog_source_matches_agent_type,
    get_source_setup_guide,
)
from ..services.subscription_mutation import (
    SubscriptionMutationError,
    SubscriptionMutationService,
)
from ..storage.service_store import ServiceStore


_MISSING = object()


class RemoteMCPSubscriptionService:
    """Expose read discovery and proposal preparation without business writes."""

    def __init__(
        self,
        *,
        store: ServiceStore,
        mutations: SubscriptionMutationService,
        proposals: AgentChangeProposalService,
        secret_is_set: Callable[[str], bool],
    ) -> None:
        self.store = store
        self.mutations = mutations
        self.proposals = proposals
        self.secret_is_set = secret_is_set

    @staticmethod
    def _proposal_error(exc: SubscriptionMutationError) -> AgentProposalError:
        return AgentProposalError(
            exc.code,
            str(exc),
            status_code=exc.status_code,
        )

    def get_source_setup_guide(
        self,
        *,
        actor: DelegatedActor,
        source_type: str | None = None,
        locale: str = "zh-CN",
    ) -> dict[str, Any]:
        self.proposals.require_read_actor(actor)
        return get_source_setup_guide(source_type, locale)

    def list_available_sources(
        self,
        *,
        actor: DelegatedActor,
        source_type: str | None = None,
        unsubscribed_only: bool = False,
    ) -> dict[str, Any]:
        live_actor = self.proposals.require_read_actor(actor)
        user = {"workspace_id": live_actor.workspace_id, "id": live_actor.user_id}
        visible = self.store.list_visible_sources(user, include_disabled=False)
        if source_type is not None:
            visible = [
                source
                for source in visible
                if catalog_source_matches_agent_type(source_type, source)
            ]
        subscribed_source_ids = {
            str(subscription["source_id"])
            for subscription in self.store.list_user_subscriptions(
                live_actor.user_id
            )
        }
        items: list[dict[str, Any]] = []
        for source in visible:
            subscribed = str(source["id"]) in subscribed_source_ids
            if unsubscribed_only and subscribed:
                continue
            secret_env = source.get("secret_env")
            items.append(
                {
                    "id": source["id"],
                    "name": source["display_name"],
                    "type": source["type"],
                    "scope": source["scope"],
                    "enabled": bool(source["enabled"]),
                    "default_channel": source.get("default_channel"),
                    "default_topics": list(source.get("default_topics") or []),
                    "secret_configured": bool(
                        secret_env and self.secret_is_set(str(secret_env))
                    ),
                    "subscribed": subscribed,
                }
            )
        return {"items": items}

    @staticmethod
    def _source_visible_to_actor(
        source: dict[str, Any], actor: DelegatedActor
    ) -> bool:
        return bool(
            source.get("enabled")
            and source.get("workspace_id") == actor.workspace_id
            and (
                source.get("scope") in {"public", "workspace"}
                or (
                    source.get("scope") == "private"
                    and source.get("owner_user_id") == actor.user_id
                )
            )
        )

    def _require_existing_visible_source(
        self,
        actor: DelegatedActor,
        source: Any,
    ) -> None:
        if not isinstance(source, dict) or source.get("mode") != "existing":
            return
        source_id = source.get("source_id")
        row = self.store.get_source(str(source_id or ""))
        if row is None or not self._source_visible_to_actor(row, actor):
            raise AgentProposalError("not_found", "source not found", status_code=404)

    def prepare_create_subscription(
        self,
        *,
        actor: DelegatedActor,
        source: dict[str, Any],
        subscription: dict[str, Any] | None = None,
        schedule: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        live_actor = self.proposals.require_write_actor(actor)
        self._require_existing_visible_source(live_actor, source)
        try:
            plan = self.mutations.plan_create(
                live_actor,
                source=source,
                subscription=subscription,
                schedule=schedule,
            )
        except SubscriptionMutationError as exc:
            raise self._proposal_error(exc) from exc
        return self.proposals.prepare(live_actor, plan)

    def prepare_update_subscription(
        self,
        *,
        actor: DelegatedActor,
        subscription_id: str,
        source_updates: dict[str, Any] | None = None,
        subscription_updates: dict[str, Any] | None = None,
        schedule_updates: dict[str, Any] | None = None,
    ) -> dict[str, Any]:
        live_actor = self.proposals.require_write_actor(actor)
        try:
            plan = self.mutations.plan_update(
                live_actor,
                subscription_id=subscription_id,
                source_updates=source_updates,
                subscription_updates=subscription_updates,
                schedule_updates=schedule_updates,
            )
        except SubscriptionMutationError as exc:
            raise self._proposal_error(exc) from exc
        return self.proposals.prepare(live_actor, plan)

    def prepare_delete_subscription(
        self,
        *,
        actor: DelegatedActor,
        subscription_id: str,
        source_disposition: Any = _MISSING,
    ) -> dict[str, Any]:
        live_actor = self.proposals.require_write_actor(actor)
        try:
            plan = (
                self.mutations.plan_delete(
                    live_actor,
                    subscription_id=subscription_id,
                )
                if source_disposition is _MISSING
                else self.mutations.plan_delete(
                    live_actor,
                    subscription_id=subscription_id,
                    source_disposition=source_disposition,
                )
            )
        except SubscriptionMutationError as exc:
            raise self._proposal_error(exc) from exc
        return self.proposals.prepare(live_actor, plan)
