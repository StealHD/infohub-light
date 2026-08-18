"""Safe continuation rules after a read-only Actor Run reconciliation."""

from __future__ import annotations

from typing import Any


def clear_start_unknown_barrier(service: Any, connection: Any, row: Any) -> bool:
    """Clear a Route barrier only when no unresolved Run remains."""

    route_id = str(row["route_id"])
    route_key = str(row["route_key"])
    unresolved = connection.execute(
        """SELECT 1 FROM apify_actor_attempts
           WHERE workspace_id = ? AND route_key = ?
             AND status = 'start_outcome_unknown' LIMIT 1""",
        (service.workspace_id, route_key),
    ).fetchone()
    if unresolved is not None:
        return False
    now = service._now_iso()
    connection.execute(
        """UPDATE apify_actor_route_profiles SET status = 'ready', updated_at = ?
           WHERE workspace_id = ? AND route_id = ?
             AND status = 'blocked_unknown_start'""",
        (now, service.workspace_id, route_id),
    )
    connection.execute(
        """UPDATE apify_actor_routes
           SET status = 'degraded', blocked_reason = NULL, updated_at = ?
           WHERE workspace_id = ? AND route_key = ?
             AND blocked_reason IN (
                 'start_outcome_unknown', 'apify_start_outcome_unknown',
                 'apify_run_reconcile_required'
             )""",
        (now, service.workspace_id, route_key),
    )
    connection.execute(
        """UPDATE apify_key_pool_state
           SET status = 'ready', blocked_reason = NULL,
               generation = generation + 1, updated_at = ?
           WHERE workspace_id = ? AND blocked_reason = 'start_outcome_unknown'
             AND NOT EXISTS (
                 SELECT 1 FROM apify_actor_attempts
                 WHERE workspace_id = ? AND status = 'start_outcome_unknown'
             )""",
        (now, service.workspace_id, service.workspace_id),
    )
    return True


def continue_terminal_route_failure(
    service: Any, connection: Any, row: Any
) -> dict[str, Any] | None:
    """Continue the same frozen batch after its recovered candidate failed.

    The failed remote Run was already paid and has been read to a terminal
    outcome.  Requeueing uses only the remaining candidate(s) disclosed in
    that exact approval; it cannot discover or approve a replacement Actor.
    """

    batch_id = str(row["batch_id"] or "")
    if (
        not batch_id
        or str(row["kind"]) != "route_reference"
        or not bool(row["cost_final"])
        or str(row["status"]) not in {"failed", "cancelled"}
    ):
        return None
    remaining = connection.execute(
        """SELECT 1 FROM apify_actor_canary_batch_items
           WHERE workspace_id = ? AND batch_id = ?
             AND status IN ('planned', 'preflight_passed') LIMIT 1""",
        (service.workspace_id, batch_id),
    ).fetchone()
    if remaining is None or not _restore_recovery_generation(
        service, connection, row
    ):
        return None
    if not clear_start_unknown_barrier(service, connection, row):
        return None
    stage_id = str(row["pool_stage_id"]) if row["pool_stage_id"] else None
    now = service._now_iso()
    if stage_id is not None:
        connection.execute(
            """UPDATE apify_actor_pool_stages
               SET status = 'queued', last_error_code = NULL,
                   updated_at = ?
               WHERE workspace_id = ? AND stage_id = ?
                 AND status IN ('blocked_unknown_start', 'validating_route')""",
            (now, service.workspace_id, stage_id),
        )
    connection.execute(
        """UPDATE apify_actor_canary_batches
           SET status = 'queued', stop_reason = NULL, completed_at = NULL,
               updated_at = ?
           WHERE workspace_id = ? AND batch_id = ?
             AND status IN (
                 'blocked_unknown_start', 'running', 'partial', 'failed'
             )""",
        (now, service.workspace_id, batch_id),
    )
    return {
        "resumed": True,
        "batch_id": batch_id,
        "stage_id": stage_id,
        "enqueue_batch": True,
    }


def _restore_recovery_generation(service: Any, connection: Any, row: Any) -> bool:
    """Undo only the one generation step written by unknown-start recovery.

    A frozen paid approval must never survive a user configuration change.  It
    may, however, survive the one synthetic generation increment that the
    restart safety barrier wrote for its own interruption.  The Stage, Route
    profile, and public Route must all prove that exact shape before the
    original generation is restored.
    """

    approved_generation = row["batch_approved_generation"]
    if approved_generation is None:
        return False
    approved = int(approved_generation)
    route = connection.execute(
        """SELECT profile.generation AS profile_generation, profile.status,
                  route.generation AS route_generation, route.blocked_reason
           FROM apify_actor_route_profiles AS profile
           JOIN apify_actor_routes AS route
             ON route.workspace_id = profile.workspace_id
            AND route.route_key = profile.route_key
           WHERE profile.workspace_id = ? AND profile.route_id = ?""",
        (service.workspace_id, str(row["route_id"])),
    ).fetchone()
    if (
        route is None
        or str(route["status"]) != "blocked_unknown_start"
        or str(route["blocked_reason"]) != "start_outcome_unknown"
        or int(route["profile_generation"]) != approved + 1
        or int(route["route_generation"]) != approved + 1
    ):
        return False
    stage_id = str(row["pool_stage_id"] or "")
    if stage_id:
        stage = connection.execute(
            """SELECT base_generation FROM apify_actor_pool_stages
               WHERE workspace_id = ? AND stage_id = ?""",
            (service.workspace_id, stage_id),
        ).fetchone()
        if stage is None or int(stage["base_generation"]) != approved:
            return False
    now = service._now_iso()
    connection.execute(
        """UPDATE apify_actor_route_profiles
           SET generation = ?, updated_at = ?
           WHERE workspace_id = ? AND route_id = ?
             AND generation = ? AND status = 'blocked_unknown_start'""",
        (approved, now, service.workspace_id, str(row["route_id"]), approved + 1),
    )
    connection.execute(
        """UPDATE apify_actor_routes
           SET generation = ?, updated_at = ?
           WHERE workspace_id = ? AND route_key = ?
             AND generation = ? AND blocked_reason = 'start_outcome_unknown'""",
        (approved, now, service.workspace_id, str(row["route_key"]), approved + 1),
    )
    return True


__all__ = ["clear_start_unknown_barrier", "continue_terminal_route_failure"]
