"""Workspace-aware due schedule selection."""

from __future__ import annotations

from typing import TYPE_CHECKING, Any

from .worker_schedule_gate import enabled_schedule_workspace_ids

if TYPE_CHECKING:
    from ..storage.service_store import ServiceStore


def _due_rows(
    store: ServiceStore,
    *,
    table: str,
    order_by: str,
    now_iso: str,
    limit: int,
) -> list[Any]:
    workspace_ids = enabled_schedule_workspace_ids(store)
    if not workspace_ids:
        return []
    placeholders = ",".join("?" for _ in workspace_ids)
    return store.connect().execute(
        f"""SELECT * FROM {table}
            WHERE enabled=1 AND workspace_id IN ({placeholders})
              AND next_run_at IS NOT NULL AND next_run_at<=?
            ORDER BY {order_by} LIMIT ?""",
        (*workspace_ids, now_iso, limit),
    ).fetchall()


def due_feed_schedule_rows(
    store: ServiceStore, *, now_iso: str, limit: int
) -> list[Any]:
    return _due_rows(
        store, table="user_feed_schedules", order_by="next_run_at, user_id",
        now_iso=now_iso, limit=limit,
    )


def due_source_schedule_rows(
    store: ServiceStore, *, now_iso: str, limit: int
) -> list[Any]:
    return _due_rows(
        store, table="user_source_schedules",
        order_by="next_run_at, subscription_id", now_iso=now_iso, limit=limit,
    )


__all__ = ["due_feed_schedule_rows", "due_source_schedule_rows"]
