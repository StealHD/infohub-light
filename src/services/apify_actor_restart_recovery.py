"""Fail-closed recovery for an Actor attempt interrupted by Worker restart."""

from __future__ import annotations

from typing import Any

from .apify_key_pool import APIFY_RUN_TERMINAL_STATUSES


def reconcile_unfinished_actor_attempts(service: Any) -> dict[str, int]:
    """Block and accurately project every unknown paid start exactly once.

    A previous implementation updated only the validation and Route.  Its
    Canary batch item and Job stayed ``running``, so the UI reported a live
    validation that no Worker could safely continue.  This operation does not
    contact Apify or start a replacement Actor: it records the durable
    unknown-start barrier and leaves the known remote Run for free status
    reconciliation.
    """

    now = service._now_iso()
    cancelled = blocked = 0
    blocked_routes: set[tuple[str, str]] = set()
    blocked_batches: set[str] = set()
    with service._write() as connection:
        for row in _unfinished_attempt_rows(connection, service.workspace_id):
            unknown, batch_ids = _project_attempt_outcome(service, connection, row, now)
            if unknown:
                blocked += 1
                blocked_routes.add((str(row["route_id"]), str(row["route_key"])))
                blocked_batches.update(batch_ids)
            else:
                cancelled += 1
        _block_batches(service, connection, blocked_batches, now)
        _block_routes(service, connection, blocked_routes, now)
    return {
        "cancelled": cancelled,
        "blocked": blocked,
        "routes_blocked": len(blocked_routes),
        "batches_blocked": len(blocked_batches),
    }


def _unfinished_attempt_rows(connection: Any, workspace_id: str) -> list[Any]:
    return connection.execute(
        """
        SELECT attempt.id, attempt.job_id, attempt.route_key, profile.route_id,
               GROUP_CONCAT(run.status) AS run_statuses
        FROM apify_actor_attempts AS attempt
        JOIN apify_actor_route_profiles AS profile
          ON profile.workspace_id = attempt.workspace_id
         AND profile.route_key = attempt.route_key
        LEFT JOIN apify_actor_runs AS run
          ON run.workspace_id = attempt.workspace_id
         AND run.logical_run_id = attempt.id
        WHERE attempt.workspace_id = ? AND attempt.status = 'running'
          AND attempt.adapter_revision_id IS NOT NULL
        GROUP BY attempt.id, attempt.job_id, attempt.route_key, profile.route_id
        """,
        (workspace_id,),
    ).fetchall()


def _project_attempt_outcome(
    service: Any, connection: Any, row: Any, now: str
) -> tuple[bool, set[str]]:
    statuses = {value for value in str(row["run_statuses"] or "").split(",") if value}
    unknown = any(status not in APIFY_RUN_TERMINAL_STATUSES for status in statuses)
    outcome = (
        "apify_worker_restart_reconcile_required"
        if unknown else "apify_worker_restart_result_lost"
    )
    attempt_id = str(row["id"])
    connection.execute(
        """UPDATE apify_actor_attempts
           SET status = ?, semantic_outcome = ?, last_error_code = ?,
               terminal_at = ?, updated_at = ?
           WHERE workspace_id = ? AND id = ? AND status = 'running'""",
        (
            "start_outcome_unknown" if unknown else "cancelled", outcome, outcome,
            now, now, service.workspace_id, attempt_id,
        ),
    )
    validations = connection.execute(
        """SELECT validation_id FROM apify_actor_validations
           WHERE workspace_id = ? AND attempt_id = ? AND status = 'running'""",
        (service.workspace_id, attempt_id),
    ).fetchall()
    connection.execute(
        """UPDATE apify_actor_validations
           SET status = 'failed', semantic_outcome = ?, completed_at = ?
           WHERE workspace_id = ? AND attempt_id = ? AND status = 'running'""",
        (outcome, now, service.workspace_id, attempt_id),
    )
    _finish_interrupted_job(service, connection, row["job_id"], now)
    return unknown, _block_validation_items(
        service, connection, validations, now
    ) if unknown else set()


def _finish_interrupted_job(service: Any, connection: Any, job_id: Any, now: str) -> None:
    if not job_id:
        return
    connection.execute(
        """UPDATE fetch_jobs
           SET status = 'failed', worker_id = NULL, claim_token = NULL,
               locked_until = NULL, error_code = 'apify_start_outcome_unknown',
               error_message = 'Actor Run needs status reconciliation',
               finished_at = ?, updated_at = ?
           WHERE workspace_id = ? AND id = ? AND status = 'running'""",
        (now, now, service.workspace_id, str(job_id)),
    )


def _block_validation_items(
    service: Any, connection: Any, validations: list[Any], now: str
) -> set[str]:
    batch_ids: set[str] = set()
    for validation in validations:
        validation_id = str(validation["validation_id"])
        rows = connection.execute(
            """SELECT batch_id FROM apify_actor_canary_batch_items
               WHERE workspace_id = ? AND validation_id = ?""",
            (service.workspace_id, validation_id),
        ).fetchall()
        connection.execute(
            """UPDATE apify_actor_canary_batch_items
               SET status = 'blocked_unknown_start',
                   semantic_outcome = 'apify_start_outcome_unknown',
                   completed_at = ?, updated_at = ?
               WHERE workspace_id = ? AND validation_id = ?
                 AND status IN ('planned', 'preflight_passed', 'running')""",
            (now, now, service.workspace_id, validation_id),
        )
        batch_ids.update(str(row["batch_id"]) for row in rows)
    return batch_ids


def _block_batches(service: Any, connection: Any, batch_ids: set[str], now: str) -> None:
    for batch_id in batch_ids:
        connection.execute(
            """UPDATE apify_actor_canary_batches
               SET status = 'blocked_unknown_start',
                   stop_reason = 'apify_start_outcome_unknown',
                   completed_at = ?, updated_at = ?
               WHERE workspace_id = ? AND batch_id = ?
                 AND status IN ('queued', 'preflighting', 'running')""",
            (now, now, service.workspace_id, batch_id),
        )
        connection.execute(
            """UPDATE apify_actor_pool_stages
               SET status = 'blocked_unknown_start',
                   last_error_code = 'apify_start_outcome_unknown', updated_at = ?
               WHERE workspace_id = ? AND stage_id = (
                   SELECT pool_stage_id FROM apify_actor_canary_batches
                   WHERE workspace_id = ? AND batch_id = ?
               ) AND status NOT IN ('applied', 'stale', 'cancelled')""",
            (now, service.workspace_id, service.workspace_id, batch_id),
        )


def _block_routes(
    service: Any, connection: Any, routes: set[tuple[str, str]], now: str
) -> None:
    for route_id, route_key in routes:
        connection.execute(
            """UPDATE apify_actor_route_profiles
               SET status = 'blocked_unknown_start', generation = generation + 1,
                   updated_at = ? WHERE workspace_id = ? AND route_id = ?""",
            (now, service.workspace_id, route_id),
        )
        connection.execute(
            """UPDATE apify_actor_routes
               SET status = 'blocked', blocked_reason = 'start_outcome_unknown',
                   generation = generation + 1, updated_at = ?
               WHERE workspace_id = ? AND route_key = ?""",
            (now, service.workspace_id, route_key),
        )
    if routes:
        connection.execute(
            """UPDATE apify_key_pool_state
               SET status = 'blocked', blocked_reason = 'start_outcome_unknown',
                   generation = generation + 1, updated_at = ?
               WHERE workspace_id = ?""",
            (now, service.workspace_id),
        )


__all__ = ["reconcile_unfinished_actor_attempts"]
