"""Safe source discovery and prepare-only subscription proposal facade."""

from __future__ import annotations

from typing import Any, Callable

from ..services.agent_change_proposal import (
    AgentChangeProposalService,
    AgentProposalError,
    DelegatedActor,
)
from ..services.bilibili_user_search import BilibiliUserSearchService
from ..services.source_type_registry import (
    catalog_source_matches_agent_type,
    get_source_setup_guide,
    project_catalog_source_public_summary,
    validate_agent_source_type,
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
        bilibili_user_search: BilibiliUserSearchService | None = None,
    ) -> None:
        self.store = store
        self.mutations = mutations
        self.proposals = proposals
        self.proposals.bind_mutations(mutations)
        self.secret_is_set = secret_is_set
        self.bilibili_user_search = (
            bilibili_user_search or BilibiliUserSearchService()
        )

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
        validated_source_type = (
            validate_agent_source_type(source_type)
            if source_type is not None
            else None
        )
        user = {"workspace_id": live_actor.workspace_id, "id": live_actor.user_id}
        visible = self.store.list_visible_sources(user, include_disabled=False)
        if validated_source_type is not None:
            visible = [
                source
                for source in visible
                if catalog_source_matches_agent_type(validated_source_type, source)
            ]
        subscribed_source_ids = {
            str(subscription["source_id"])
            for subscription in self.store.list_user_subscriptions(
                live_actor.user_id
            )
        }
        items: list[dict[str, Any]] = []
        seen_source_ids: set[str] = set()
        for source in visible:
            source_id = str(source["id"])
            if source_id in seen_source_ids:
                continue
            seen_source_ids.add(source_id)
            subscribed = source_id in subscribed_source_ids
            if unsubscribed_only and subscribed:
                continue
            secret_env = source.get("secret_env")
            secret_configured = False
            secret_error: AgentProposalError | None = None
            if secret_env:
                try:
                    secret_configured = bool(
                        self.secret_is_set(str(secret_env))
                    )
                except Exception:
                    secret_error = AgentProposalError(
                        "source_discovery_unavailable",
                        "source discovery is unavailable",
                        status_code=503,
                    )
            # Raise outside the callback exception context so neither chaining
            # nor common exception serializers can retain the environment name.
            if secret_error is not None:
                raise secret_error
            public_summary = project_catalog_source_public_summary(source)
            public_target = public_summary["public_target"]
            public_type = (
                "bilibili"
                if source.get("type") == "rss"
                and isinstance(public_target, dict)
                and public_target.get("site") == "bilibili"
                else source["type"]
            )
            items.append(
                {
                    "id": source_id,
                    "name": source["display_name"],
                    "type": public_type,
                    "scope": source["scope"],
                    "enabled": bool(source["enabled"]),
                    "default_channel": source.get("default_channel"),
                    "default_topics": list(source.get("default_topics") or []),
                    "public_target": public_target,
                    "secret_configured": secret_configured,
                    "subscribed": subscribed,
                }
            )
        items.sort(
            key=lambda item: (
                str(item["scope"]),
                str(item["name"]).casefold(),
                str(item["id"]),
            )
        )
        return {"items": items}

    def search_bilibili_users(
        self,
        *,
        actor: DelegatedActor,
        query: str,
        limit: int = 5,
    ) -> dict[str, Any]:
        self.proposals.require_read_actor(actor)
        invalid_error: AgentProposalError | None = None
        try:
            result = self.bilibili_user_search.search(query=query, limit=limit)
        except ValueError:
            invalid_error = AgentProposalError(
                "invalid_request",
                "Bilibili account query is invalid",
                status_code=400,
            )
        if invalid_error is not None:
            raise invalid_error
        return result

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

    def apply_subscription_change(
        self,
        *,
        actor: DelegatedActor,
        proposal_id: str,
        confirmation_text: str,
    ) -> dict[str, Any]:
        return self.proposals.apply(
            actor,
            proposal_id=proposal_id,
            confirmation_text=confirmation_text,
        )
