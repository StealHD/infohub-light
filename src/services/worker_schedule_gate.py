"""Runtime gate for local maintenance windows that must not enqueue schedules."""

from __future__ import annotations

from typing import TYPE_CHECKING

from .system_settings import resolve_system_setting
from .system_settings_registry import (
    SYSTEM_SETTING_DEFINITIONS,
    parse_environment_value,
)

if TYPE_CHECKING:
    from ..storage.service_store import ServiceStore


def worker_schedule_polling_enabled(
    store: ServiceStore | None = None,
    *,
    workspace_id: str = "default",
) -> bool:
    """Return whether the resident Worker may enqueue user schedules.

    The default keeps normal production behavior. Local ActorOps acceptance can
    set the variable to ``false`` so the Worker keeps its health/reconcile
    duties but does not create unrelated scheduled source jobs.
    """

    if store is None:
        return bool(parse_environment_value(
            SYSTEM_SETTING_DEFINITIONS["scheduling.automatic_enqueue_enabled"]
        ))
    return bool(resolve_system_setting(
        store, workspace_id, "scheduling.automatic_enqueue_enabled"
    ))


def enabled_schedule_workspace_ids(store: ServiceStore) -> tuple[str, ...]:
    """Return workspaces whose current settings permit scheduled enqueues."""

    workspace_ids = (
        str(row[0]) for row in store.connect().execute("SELECT id FROM workspaces")
    )
    return tuple(
        workspace_id
        for workspace_id in workspace_ids
        if worker_schedule_polling_enabled(store, workspace_id=workspace_id)
    )


__all__ = ["enabled_schedule_workspace_ids", "worker_schedule_polling_enabled"]
