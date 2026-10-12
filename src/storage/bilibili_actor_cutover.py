"""Explicit data-only provisioning for Bilibili ActorOps routes and bindings."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from .actorops_v2_single_track_schema import seed_default_catalog
from ..services.bilibili_source_identity import is_bilibili_source
from ..services.actorops.binding_service import ActorOpsBindingService, _binding_id
from ..services.actorops.domain import RouteKey


def source_candidates(connection):
    candidates = []
    for row in connection.execute(
        "SELECT id, workspace_id, config_json, enabled FROM source_catalog WHERE type='rss' ORDER BY id"
    ):
        try:
            config = json.loads(str(row["config_json"]))
        except (TypeError, json.JSONDecodeError):
            continue
        if is_bilibili_source("rss", config):
            candidates.append(dict(row))
    return candidates


def cutover_counts(connection):
    sources = source_candidates(connection)
    missing = sum(connection.execute(
        "SELECT 1 FROM actor_source_bindings_v2 WHERE workspace_id=? AND source_id=?",
        (row["workspace_id"], row["id"]),
    ).fetchone() is None for row in sources)
    routes = connection.execute(
        """SELECT COUNT(*) FROM workspaces AS workspace WHERE NOT EXISTS (
             SELECT 1 FROM actor_routes_v2 AS route WHERE route.workspace_id=workspace.id
             AND route.platform='bilibili' AND route.target_type='profile' AND route.capability='items')"""
    ).fetchone()[0]
    return {"sources": len(sources), "bindings_required": missing, "routes_required": int(routes)}


def apply_cutover(store):
    connection = store.connect()
    if not connection.in_transaction:
        raise RuntimeError("Bilibili cutover requires a caller transaction")
    before = cutover_counts(connection)
    seed_default_catalog(connection, route_keys={RouteKey("bilibili", "profile", "items")})
    for row in source_candidates(connection):
        exists = connection.execute(
            "SELECT 1 FROM actor_source_bindings_v2 WHERE workspace_id=? AND source_id=?",
            (row["workspace_id"], row["id"]),
        ).fetchone()
        if exists:
            continue
        service = ActorOpsBindingService(store, workspace_id=row["workspace_id"])
        target = service.evidence.target(store.get_source(row["id"]), existing=None)
        stamp = datetime.now(timezone.utc).isoformat()
        # Administrative disable also clears user notifications/schedules and
        # rewrites Feed visibility. A transport cutover must preserve that state.
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                 binding_id, workspace_id, source_id, route_id, target_fingerprint,
                 status, binding_version, created_at, updated_at)
               VALUES (?, ?, ?, ?, ?, ?, 1, ?, ?)""",
            (_binding_id(row["workspace_id"], row["id"]), row["workspace_id"], row["id"],
             target.route_id, target.target_fingerprint,
             "pending" if row["enabled"] else "disabled", stamp, stamp),
        )
        connection.execute(
            "UPDATE source_catalog SET enabled=0, updated_at=? WHERE workspace_id=? AND id=?",
            (stamp, row["workspace_id"], row["id"]),
        )
    return before
