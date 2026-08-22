"""Project ready ActorOps v2 bindings into ephemeral source records."""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from typing import Any, Iterable

from ..storage.service_store import ServiceStore
from .actorops.binding_service import ActorOpsBindingError
from .youtube_actor_source import (
    is_youtube_channel_record,
    project_youtube_actor_runtime_record,
)


def with_actorops_runtime_profiles(
    store: ServiceStore,
    *,
    workspace_id: str,
    records: Iterable[dict[str, Any]],
) -> list[dict[str, Any]]:
    """Inject only current ready v2 bindings; catalog Route ids are ignored."""

    original = list(records)
    prepared = [_without_catalog_profile(record) for record in original]
    source_ids = [
        str(record.get("source_id") or "")
        for record in original
        if (
            str(record.get("type") or "") == "apify_social"
            or is_youtube_channel_record(record)
        )
        and str(record.get("source_id") or "")
    ]
    if not source_ids:
        return prepared
    placeholders = ", ".join("?" for _ in source_ids)
    try:
        rows = store.connect().execute(
            f"""SELECT binding.source_id, binding.route_id, route.platform
                FROM actor_source_bindings_v2 AS binding
                JOIN actor_routes_v2 AS route
                  ON route.workspace_id=binding.workspace_id
                 AND route.route_id=binding.route_id
                WHERE binding.workspace_id=? AND binding.status='ready'
                  AND binding.source_id IN ({placeholders})""",
            (str(workspace_id), *source_ids),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        if "no such table" not in str(exc).casefold():
            raise
        raise ActorOpsBindingError("actorops_v2_migration_required") from exc
    route_by_source = {
        str(row["source_id"]): (str(row["route_id"]), str(row["platform"]))
        for row in rows
    }
    projected: list[dict[str, Any]] = []
    for record in prepared:
        route = route_by_source.get(str(record.get("source_id") or ""))
        if route is None:
            projected.append(record)
            continue
        route_id, platform = route
        if is_youtube_channel_record(record):
            projected.append(
                project_youtube_actor_runtime_record(record, route_id=route_id)
                if platform == "youtube"
                else record
            )
            continue
        runtime_record = dict(record)
        config = deepcopy(runtime_record.get("config") or {})
        config["profile_id"] = route_id
        config["enabled"] = True
        runtime_record["config"] = config
        projected.append(runtime_record)
    return projected


def _without_catalog_profile(record: dict[str, Any]) -> dict[str, Any]:
    managed_youtube = is_youtube_channel_record(record)
    if (
        str(record.get("type") or "") != "apify_social"
        and not managed_youtube
    ):
        return record
    projected = dict(record)
    config = deepcopy(projected.get("config") or {})
    config.pop("profile_id", None)
    # A stale catalog enable bit must not make a pending/missing Binding fall
    # through to the fixed legacy Actor path.
    config["enabled"] = False
    projected["config"] = config
    return projected


__all__ = ["with_actorops_runtime_profiles"]
