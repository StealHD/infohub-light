"""Actor-scoped source selection and the source identity migration boundary."""

from typing import Any

from .source_type_registry import catalog_source_matches_agent_type
from ..storage.source_identity_schema import SourceIdentityMigrationRequiredError, require_ready


def require_source_identity(store: Any) -> None:
    """Translate the storage migration gate to the shared REST/MCP domain error."""
    from .subscription_mutation import SubscriptionMutationError

    try:
        require_ready(store.connect())
    except SourceIdentityMigrationRequiredError as exc:
        raise SubscriptionMutationError(
            exc.code, str(exc), status_code=503,
            action="Ask an administrator to apply the source identity migration.",
        ) from None


def select_visible_source(store: Any, actor: Any, source_type: str, key: str) -> dict | None:
    """Prefer a subscribed identity, then the caller's private, then shared."""
    user = {"id": actor.user_id, "workspace_id": actor.workspace_id}
    visible = [source for source in store.get_visible_sources_by_key(user, key)
               if catalog_source_matches_agent_type(source_type, source)]
    subscribed = {str(item["source_id"]) for item in store.list_user_subscriptions(actor.user_id)
                  if item.get("enabled")}
    return min(visible, default=None, key=lambda source: (
        str(source["id"]) not in subscribed, source.get("scope") != "private", str(source["id"]),
    ))
