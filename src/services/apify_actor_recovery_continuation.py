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
    recovery_mode = _restore_recovery_generation(service, connection, row)
    if recovery_mode is None:
        return None
    if remaining is None and recovery_mode == "stale":
        _restore_zero_cost_stale_items(service, connection, batch_id)
        remaining = connection.execute(
            """SELECT 1 FROM apify_actor_canary_batch_items
               WHERE workspace_id = ? AND batch_id = ?
                 AND status IN ('planned', 'preflight_passed') LIMIT 1""",
            (service.workspace_id, batch_id),
        ).fetchone()
    if remaining is None:
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
                 AND status IN (
                     'blocked_unknown_start', 'validating_route', 'replan_required'
                 )""",
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


def _restore_recovery_generation(
    service: Any, connection: Any, row: Any
) -> str | None:
    """Undo only the one generation step written by unknown-start recovery.

    A frozen paid approval must never survive a user configuration change.  It
    may, however, survive the one synthetic generation increment that the
    restart safety barrier wrote for its own interruption.  The Stage, Route
    profile, and public Route must all prove that exact shape before the
    original generation is restored.
    """

    approved_generation = row["batch_approved_generation"]
    if approved_generation is None:
        return None
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
    if route is None:
        return None
    stage_id = str(row["pool_stage_id"] or "")
    stage = None
    if stage_id:
        stage = connection.execute(
            """SELECT base_generation, status, last_error_code
               FROM apify_actor_pool_stages
               WHERE workspace_id = ? AND stage_id = ?""",
            (service.workspace_id, stage_id),
        ).fetchone()
        if stage is None or int(stage["base_generation"]) != approved:
            return None
    blocked = (
        str(route["status"]) == "blocked_unknown_start"
        and str(route["blocked_reason"]) == "start_outcome_unknown"
    )
    stale = (
        stage is not None
        and str(route["status"]) == "ready"
        and str(route["blocked_reason"] or "") == ""
        and str(stage["status"]) == "replan_required"
        and str(stage["last_error_code"]) == "candidate_shortfall"
    )
    profile_generation = int(route["profile_generation"])
    route_generation = int(route["route_generation"])
    # Older recovery code could restore the synthetic generation increment
    # before noticing that it had written zero-cost approval_stale items with
    # cost_final=0.  This exact staged shape is safe to finish, because a real
    # Route change cannot decrement back to the original approval generation.
    if (
        profile_generation == approved
        and route_generation == approved
        and stale
    ):
        return "stale"
    if (
        profile_generation != approved + 1
        or route_generation != approved + 1
    ):
        return None
    if not blocked and not stale:
        return None
    now = service._now_iso()
    connection.execute(
        """UPDATE apify_actor_route_profiles
           SET generation = ?, updated_at = ?
           WHERE workspace_id = ? AND route_id = ?
             AND generation = ?
             AND status IN ('blocked_unknown_start', 'ready')""",
        (approved, now, service.workspace_id, str(row["route_id"]), approved + 1),
    )
    connection.execute(
        """UPDATE apify_actor_routes
           SET generation = ?, updated_at = ?
           WHERE workspace_id = ? AND route_key = ?
             AND generation = ?
             AND (
                 blocked_reason = 'start_outcome_unknown' OR blocked_reason IS NULL
             )""",
        (approved, now, service.workspace_id, str(row["route_key"]), approved + 1),
    )
    return "stale" if stale else "blocked"


def _restore_zero_cost_stale_items(
    service: Any, connection: Any, batch_id: str
) -> None:
    """Reopen only entries cancelled by the old recovery-generation defect."""

    connection.execute(
        """UPDATE apify_actor_validations
           SET status = 'queued', semantic_outcome = NULL, cost_usd = NULL,
               cost_final = 0, completed_at = NULL
           WHERE workspace_id = ?
             AND validation_id IN (
                 SELECT item.validation_id
                 FROM apify_actor_canary_batch_items AS item
                 WHERE item.workspace_id = ? AND item.batch_id = ?
                   AND item.status = 'failed'
                   AND item.semantic_outcome = 'approval_stale'
                   AND COALESCE(item.actual_cost_usd, 0) = 0
                   AND item.cost_final IN (0, 1)
             )
             AND status = 'cancelled'
             AND semantic_outcome = 'approval_stale'
             AND COALESCE(cost_usd, 0) = 0
             AND cost_final IN (0, 1)""",
        (service.workspace_id, service.workspace_id, batch_id),
    )
    now = service._now_iso()
    connection.execute(
        """UPDATE apify_actor_canary_batch_items
           SET status = 'planned', semantic_outcome = NULL,
               actual_cost_usd = NULL, cost_final = 0,
               preflight_checked_at = NULL, started_at = NULL,
               completed_at = NULL, updated_at = ?
           WHERE workspace_id = ? AND batch_id = ?
             AND status = 'failed' AND semantic_outcome = 'approval_stale'
             AND COALESCE(actual_cost_usd, 0) = 0
             AND cost_final IN (0, 1)""",
        (now, service.workspace_id, batch_id),
    )


__all__ = ["clear_start_unknown_barrier", "continue_terminal_route_failure"]
