"""Focused subscription-existence queries kept outside the ServiceStore facade."""

from __future__ import annotations

from typing import Any


def has_enabled_user_subscriptions(
    store: Any,
    *,
    workspace_id: str,
    user_id: str,
    global_schedule_only: bool = False,
    source_scope: str = "all",
) -> bool:
    """Check whether a user has an enabled subscription in the permitted scope."""

    if source_scope not in {"all", "private"}:
        raise ValueError("source_scope must be 'all' or 'private'")
    schedule_filter = "AND COALESCE(uss.enabled, 0) = 0" if global_schedule_only else ""
    source_filter = (
        "AND sc.scope = 'private' AND sc.owner_user_id = ?"
        if source_scope == "private"
        else ""
    )
    params = [user_id, workspace_id, *([user_id] if source_scope == "private" else [])]
    return bool(
        store.connect()
        .execute(
            f"""
            SELECT 1
            FROM user_subscriptions us
            JOIN source_catalog sc ON sc.id = us.source_id
            LEFT JOIN user_source_schedules uss ON uss.subscription_id = us.id
            WHERE us.user_id = ?
              AND sc.workspace_id = ?
              AND us.enabled = 1
              AND sc.enabled = 1
              {schedule_filter}
              {source_filter}
            LIMIT 1
            """,
            params,
        )
        .fetchone()
    )
