"""Safe v1/v2 compatibility summary for offline ActorOps cutover controls."""

from __future__ import annotations

import sqlite3
from typing import Any

from src.services.actorops.catalog_binding_bridge import catalog_binding_is_current
from src.services.actorops.legacy_readiness import (
    runnable_legacy_slot_revisions,
    runnable_v2_candidate_revisions,
)


def legacy_summary(
    connection: sqlite3.Connection, workspace_id: str, route: sqlite3.Row
) -> dict[str, Any]:
    route_id = str(route["route_id"])
    profile = connection.execute(
        """SELECT generation FROM apify_actor_route_profiles
           WHERE workspace_id=? AND route_id=?""",
        (workspace_id, route_id),
    ).fetchone()
    expected = runnable_legacy_slot_revisions(
        connection, workspace_id=workspace_id, route_id=route_id
    )
    actual = runnable_v2_candidate_revisions(
        connection, workspace_id=workspace_id, route_id=route_id
    )
    legacy_bindings = connection.execute(
        """SELECT binding_id, target_fingerprint, generation
           FROM apify_source_route_bindings
           WHERE workspace_id=? AND route_id=? ORDER BY binding_id""",
        (workspace_id, route_id),
    ).fetchall()
    v2_bindings = {
        str(row["binding_id"]): row
        for row in connection.execute(
            """SELECT binding_id, workspace_id, source_id, route_id,
                      target_fingerprint, source_v1_generation
               FROM actor_source_bindings_v2
               WHERE workspace_id=? AND route_id=?""",
            (workspace_id, route_id),
        ).fetchall()
    }
    legacy_ids = {str(row["binding_id"]) for row in legacy_bindings}
    catalog_ids = {
        binding_id
        for binding_id, binding in v2_bindings.items()
        if binding_id not in legacy_ids
        and catalog_binding_is_current(connection, binding)
    }
    slot_mismatches = sum(
        left != right for left, right in zip(expected, actual, strict=False)
    ) + abs(len(expected) - len(actual))
    binding_mismatches = sum(
        binding_id not in v2_bindings
        or str(v2_bindings[binding_id]["target_fingerprint"])
        != str(row["target_fingerprint"])
        or int(v2_bindings[binding_id]["source_v1_generation"])
        != int(row["generation"])
        for row in legacy_bindings
        for binding_id in (str(row["binding_id"]),)
    )
    binding_mismatches += sum(
        binding_id not in legacy_ids and binding_id not in catalog_ids
        for binding_id in v2_bindings
    )
    route_matches = bool(profile) and int(route["source_v1_generation"]) == int(
        profile["generation"]
    )
    return {
        "route_generation_matches": route_matches,
        "slot_count": len(expected),
        "slot_mismatches": slot_mismatches,
        "binding_count": len(legacy_bindings),
        "catalog_binding_count": len(catalog_ids),
        "binding_mismatches": binding_mismatches,
        "compatible": route_matches and not slot_mismatches and not binding_mismatches,
    }


__all__ = ["legacy_summary"]
