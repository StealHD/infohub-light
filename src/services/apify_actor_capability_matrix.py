"""Declared platform capabilities and safe policy convergence for ActorOps.

Only the neutral pool orchestration is shared by platforms.  This matrix is
the durable registration point for each platform's execution contract and its
minimum reliable pool shape; an unregistered tuple is intentionally absent.
"""

from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Any


@dataclass(frozen=True, slots=True)
class ActorRouteCapability:
    route_id: str
    route_key: str
    platform: str
    target_type: str
    capability: str
    mode: str
    label: str
    min_runtime_healthy: int = 2
    min_publishers: int = 2

    def public_profile(self) -> dict[str, str]:
        return {
            "id": self.route_id,
            "route_key": self.route_key,
            "platform": self.platform,
            "target_type": self.target_type,
            "capability": self.capability,
            "mode": self.mode,
            "label": self.label,
        }


CAPABILITY_MATRIX = (
    ActorRouteCapability(
        route_id="x/profile/items",
        route_key="x/profile",
        platform="x",
        target_type="profile",
        capability="items",
        mode="primary",
        label="X Profile",
    ),
    ActorRouteCapability(
        route_id="youtube/channel/items",
        route_key="youtube/channel/items",
        platform="youtube",
        target_type="channel",
        capability="items",
        mode="primary",
        label="YouTube Channel",
    ),
    ActorRouteCapability(
        route_id="instagram/profile/items",
        route_key="instagram/profile/items",
        platform="instagram",
        target_type="profile",
        capability="items",
        mode="primary",
        label="Instagram Profile",
    ),
)

_BY_ID = {entry.route_id: entry for entry in CAPABILITY_MATRIX}
_BY_IDENTITY = {
    (entry.platform, entry.target_type, entry.capability): entry
    for entry in CAPABILITY_MATRIX
}
_ACTIVE_STAGE_STATUSES = frozenset(
    {"queued", "validating_route", "validating_sources", "apply_ready", "blocked_unknown_start"}
)


def registered_route_capability(
    platform: str,
    target_type: str,
    capability: str,
) -> ActorRouteCapability | None:
    """Return the explicit platform binding; unknown combinations fail closed."""

    return _BY_IDENTITY.get((platform, target_type, capability))


def route_profiles() -> tuple[dict[str, str], ...]:
    return tuple(entry.public_profile() for entry in CAPABILITY_MATRIX)


def reconcile_registered_route_policies(
    connection: sqlite3.Connection,
    *,
    workspace_id: str,
    now: str,
) -> dict[str, int]:
    """Converge persisted legacy routes without changing an in-flight Stage.

    The legacy YouTube 1/3 fallback rule was a product-policy bug, not a
    schema difference.  Existing in-flight stages retain their generation and
    source bindings, but immediately expose the common 2/3 minimum.  Idle
    routes converge in one transaction and never create a discovery or paid
    Actor Run.
    """

    updated_routes = 0
    updated_bindings = 0
    deferred_routes = 0
    for entry in CAPABILITY_MATRIX:
        route = connection.execute(
            """
            SELECT route_id, route_key, mode, status, admission_mode,
                   min_runtime_healthy, min_publishers, policy_version
            FROM apify_actor_route_profiles
            WHERE workspace_id = ? AND platform = ? AND target_type = ?
              AND capability = ?
            """,
            (workspace_id, entry.platform, entry.target_type, entry.capability),
        ).fetchone()
        if route is None:
            continue
        route_id = str(route["route_id"])
        active_stage = connection.execute(
            """
            SELECT 1 FROM apify_actor_pool_stages
            WHERE workspace_id = ? AND route_id = ?
              AND status IN (?, ?, ?, ?, ?)
            LIMIT 1
            """,
            (workspace_id, route_id, *_ACTIVE_STAGE_STATUSES),
        ).fetchone() is not None
        needs_mode = str(route["mode"]) != entry.mode
        needs_policy = str(route["policy_version"]) != "actor_ops_v3"
        is_compatibility = str(route["admission_mode"] or "") == "compatibility"
        needs_minimum = (
            not is_compatibility
            and (
                int(route["min_runtime_healthy"]) != entry.min_runtime_healthy
                or int(route["min_publishers"]) != entry.min_publishers
            )
        )
        if active_stage:
            if needs_mode or needs_policy or needs_minimum:
                _converge_active_profile(
                    connection,
                    workspace_id=workspace_id,
                    route_id=route_id,
                    entry=entry,
                    is_compatibility=is_compatibility,
                    now=now,
                )
                updated_routes += 1
            continue
        binding_cursor = connection.execute(
            """
            UPDATE apify_source_route_bindings
            SET mode = 'primary', generation = generation + 1, updated_at = ?
            WHERE workspace_id = ? AND route_id = ? AND mode != 'primary'
            """,
            (now, workspace_id, route_id),
        )
        updated_bindings += int(binding_cursor.rowcount)
        if not (needs_mode or needs_policy or needs_minimum):
            continue
        configured, publishers = (
            int(value)
            for value in connection.execute(
                """
                SELECT COUNT(DISTINCT revision.actor_id),
                       COUNT(DISTINCT NULLIF(
                           LOWER(TRIM(COALESCE(revision.publisher, ''))), ''
                       ))
                FROM apify_route_active_slots AS slot
                JOIN apify_actor_adapter_revisions AS revision
                  ON revision.workspace_id = slot.workspace_id
                 AND revision.revision_id = slot.revision_id
                WHERE slot.workspace_id = ? AND slot.route_id = ?
                  AND slot.revision_id IS NOT NULL
                """,
                (workspace_id, route_id),
            ).fetchone()
        )
        next_status = (
            str(route["status"])
            if str(route["status"]) == "blocked_unknown_start"
            else "ready"
            if (
                configured >= entry.min_runtime_healthy
                and publishers >= entry.min_publishers
            )
            else "discovery_required"
        )
        connection.execute(
            """
            UPDATE apify_actor_route_profiles
            SET mode = ?, min_runtime_healthy = ?, min_publishers = ?,
                policy_version = ?, status = ?, generation = generation + 1,
                updated_at = ?
            WHERE workspace_id = ? AND route_id = ?
            """,
            (
                entry.mode,
                1 if is_compatibility else entry.min_runtime_healthy,
                1 if is_compatibility else entry.min_publishers,
                "actor_ops_v3",
                next_status,
                now,
                workspace_id,
                route_id,
            ),
        )
        if next_status != "blocked_unknown_start":
            connection.execute(
                """
                UPDATE apify_actor_routes
                SET status = ?, blocked_reason = ?, generation = generation + 1,
                    updated_at = ?
                WHERE workspace_id = ? AND route_key = ?
                  AND COALESCE(blocked_reason, '') NOT IN (
                      'start_outcome_unknown', 'apify_start_outcome_unknown',
                      'apify_run_reconcile_required'
                  )
                """,
                (
                    "ready" if next_status == "ready" else "blocked",
                    None if next_status == "ready" else "discovery_required",
                    now,
                    workspace_id,
                    str(route["route_key"]),
                ),
            )
        updated_routes += 1
    return {
        "routes": updated_routes,
        "bindings": updated_bindings,
        "deferred": deferred_routes,
    }


def _converge_active_profile(
    connection: sqlite3.Connection,
    *,
    workspace_id: str,
    route_id: str,
    entry: ActorRouteCapability,
    is_compatibility: bool,
    now: str,
) -> None:
    """Update display policy without invalidating an approved frozen Stage."""

    connection.execute(
        """UPDATE apify_actor_route_profiles
           SET mode = ?, min_runtime_healthy = ?, min_publishers = ?,
               policy_version = ?, updated_at = ?
           WHERE workspace_id = ? AND route_id = ?""",
        (
            entry.mode,
            1 if is_compatibility else entry.min_runtime_healthy,
            1 if is_compatibility else entry.min_publishers,
            "actor_ops_v3",
            now,
            workspace_id,
            route_id,
        ),
    )


__all__ = [
    "ActorRouteCapability",
    "CAPABILITY_MATRIX",
    "reconcile_registered_route_policies",
    "registered_route_capability",
    "route_profiles",
]
