"""Inject durable ActorOps bindings into ephemeral source runtime records.

Catalog source configuration deliberately remains the member-managed input.
The binding is separate ActorOps state, so this projection must be made while
building a worker configuration instead of writing a ``profile_id`` back to
``source_catalog``.  That prevents a bound source from silently falling back
to the legacy X router while keeping the catalog payload stable.
"""

from __future__ import annotations

import sqlite3
from copy import deepcopy
from typing import Any, Iterable

from ..storage.service_store import ServiceStore
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
    """Return records with a bound ActorOps route injected for execution.

    Only a legacy-shaped Apify social record with an existing, current binding
    is changed.  Explicit catalog ``profile_id`` values remain authoritative,
    and an installation without the explicit ActorOps schema continues to run
    unchanged until its migration is applied.
    """

    prepared = list(records)
    source_ids = [
        str(record.get("source_id") or "")
        for record in prepared
        if (
            (
                str(record.get("type") or "") == "apify_social"
                and not str(
                    (record.get("config") or {}).get("profile_id") or ""
                ).strip()
            )
            or is_youtube_channel_record(record)
        )
        and str(record.get("source_id") or "")
    ]
    if not source_ids:
        return prepared

    placeholders = ", ".join("?" for _ in source_ids)
    try:
        rows = store.connect().execute(
            f"""
            SELECT binding.source_id, binding.route_id, profile.platform
            FROM apify_source_route_bindings AS binding
            JOIN apify_actor_route_profiles AS profile
              ON profile.workspace_id = binding.workspace_id
             AND profile.route_id = binding.route_id
            WHERE binding.workspace_id = ?
              AND binding.source_id IN ({placeholders})
            """,
            (str(workspace_id), *source_ids),
        ).fetchall()
    except sqlite3.OperationalError as exc:
        # ActorOps schema installation is explicit; do not make older, valid
        # catalog-only installations fail merely by constructing a config.
        if "no such table" not in str(exc).lower():
            raise
        return prepared

    route_by_source = {
        str(row["source_id"]): (str(row["route_id"]), str(row["platform"]))
        for row in rows
        if row["route_id"]
    }
    if not route_by_source:
        return prepared

    projected: list[dict[str, Any]] = []
    for record in prepared:
        route = route_by_source.get(str(record.get("source_id") or ""))
        if route is None:
            projected.append(record)
            continue
        route_id, platform = route
        if is_youtube_channel_record(record):
            if platform == "youtube":
                projected.append(
                    project_youtube_actor_runtime_record(record, route_id=route_id)
                )
            else:
                projected.append(record)
            continue
        runtime_record = dict(record)
        config = deepcopy(runtime_record.get("config") or {})
        config["profile_id"] = route_id
        runtime_record["config"] = config
        projected.append(runtime_record)
    return projected


__all__ = ["with_actorops_runtime_profiles"]
