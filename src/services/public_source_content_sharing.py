"""Project public source content into each active subscriber Feed."""

from __future__ import annotations

from ..storage.service_store import ServiceStore
from .source_content_reuse import reuse_source_content
from .user_feed_store import UserFeedStore


PUBLIC_SOURCE_SCOPES = frozenset({"public", "workspace"})
MAX_PUBLIC_SOURCE_REUSE_ITEMS = 200


def _active_subscribers(
    store: ServiceStore,
    *,
    workspace_id: str,
    source_id: str,
) -> list[dict[str, str]]:
    rows = store.connect().execute(
        """
        SELECT subscriptions.id AS subscription_id, subscriptions.user_id
        FROM user_subscriptions AS subscriptions
        JOIN users
          ON users.id = subscriptions.user_id
         AND users.workspace_id = ?
        WHERE subscriptions.source_id = ?
          AND subscriptions.enabled = 1
          AND users.enabled = 1
          AND users.role != 'viewer'
        ORDER BY subscriptions.created_at, subscriptions.id
        """,
        (workspace_id, source_id),
    ).fetchall()
    return [
        {
            "subscription_id": str(row["subscription_id"]),
            "user_id": str(row["user_id"]),
        }
        for row in rows
    ]


def fan_out_public_source_content(
    store: ServiceStore,
    *,
    workspace_id: str,
    source_id: str,
    commit: bool = True,
) -> dict[str, int]:
    """Reuse neutral public-source content for every eligible subscriber.

    The reused content is rebuilt through the target subscription, so no
    producer AI output, personal tags, or item state crosses user boundaries.
    """

    source = store.get_source(source_id)
    if (
        source is None
        or source.get("workspace_id") != workspace_id
        or not bool(source.get("enabled"))
        or source.get("scope") not in PUBLIC_SOURCE_SCOPES
    ):
        return {"projected_user_count": 0, "reused_item_count": 0}

    connection = store.connect()
    owns_transaction = bool(commit and not connection.in_transaction)
    try:
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        feed_store = UserFeedStore(store)
        projected_user_count = 0
        reused_item_count = 0
        for subscriber in _active_subscribers(
            store,
            workspace_id=workspace_id,
            source_id=source_id,
        ):
            result = reuse_source_content(
                feed_store,
                workspace_id=workspace_id,
                user_id=subscriber["user_id"],
                source_id=source_id,
                subscription_id=subscriber["subscription_id"],
                limit=MAX_PUBLIC_SOURCE_REUSE_ITEMS,
                commit=False,
            )
            reused_count = int(result["reused_count"])
            reused_item_count += reused_count
            projected_user_count += int(reused_count > 0)
        if owns_transaction:
            connection.commit()
        return {
            "projected_user_count": projected_user_count,
            "reused_item_count": reused_item_count,
        }
    except Exception:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        raise
