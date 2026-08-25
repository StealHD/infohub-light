"""Role-scoped production drain primitives for the shared Apify Key pool."""

from __future__ import annotations

import asyncio
from typing import Any

from .apify_key_pool import APIFY_RUN_TERMINAL_STATUSES, _normalize_run_status


def list_acquisition_nonterminal_runs(
    coordinator: Any,
    workspace_id: str,
    *,
    up_to_generation: int | None = None,
) -> list[dict[str, Any]]:
    """Return nonterminal Runs whose credential belongs to production acquisition.

    A validation attempt can borrow an acquisition credential and must therefore
    stay in this barrier.  A dedicated validation credential must not.
    """

    clauses = [
        "run.workspace_id = ?",
        "member.role = 'acquisition'",
        "run.status IN ('reserved', 'starting', 'running', 'aborting', "
        "'start_outcome_unknown')",
    ]
    parameters: list[Any] = [workspace_id]
    if up_to_generation is not None:
        clauses.append("run.pool_generation <= ?")
        parameters.append(int(up_to_generation))
    rows = coordinator.store.connect().execute(
        f"""
        SELECT run.*, secret.env_name
        FROM apify_actor_runs AS run
        JOIN apify_key_pool_members AS member
          ON member.workspace_id = run.workspace_id
         AND member.secret_id = run.secret_id
        LEFT JOIN secret_refs AS secret ON secret.id = run.secret_id
        WHERE {' AND '.join(clauses)}
        ORDER BY run.pool_generation, run.created_at, run.id
        """,
        parameters,
    ).fetchall()
    return [dict(row) for row in rows]


def count_acquisition_nonterminal_runs(
    coordinator: Any,
    workspace_id: str,
    *,
    up_to_generation: int,
) -> int:
    """Count the production-scoped Runs that still hold a drain barrier."""

    row = coordinator.store.connect().execute(
        """
        SELECT COUNT(*) AS count
        FROM apify_actor_runs AS run
        JOIN apify_key_pool_members AS member
          ON member.workspace_id = run.workspace_id
         AND member.secret_id = run.secret_id
        WHERE run.workspace_id = ?
          AND member.role = 'acquisition'
          AND run.pool_generation <= ?
          AND run.status IN (
              'reserved', 'starting', 'running', 'aborting',
              'start_outcome_unknown'
          )
        """,
        (workspace_id, int(up_to_generation)),
    ).fetchone()
    return int(row["count"] if row is not None else 0)


def complete_acquisition_drain_and_failover(
    coordinator: Any,
    workspace_id: str,
) -> dict[str, Any]:
    """Promote a standby once all production-scoped old Runs are terminal."""

    from .apify_key_pool import ApifyKeyDrainPendingError, ApifyKeyPoolBlockedError

    connection = coordinator.store.connect()
    owns_transaction = not connection.in_transaction
    now_iso = coordinator._current_time().isoformat()
    try:
        if owns_transaction:
            connection.execute("BEGIN IMMEDIATE")
        state = coordinator._state_row(connection, workspace_id)
        if state["status"] == "blocked":
            raise ApifyKeyPoolBlockedError()
        if state["status"] != "draining":
            if owns_transaction:
                connection.commit()
            return coordinator.public_state(workspace_id)
        drain_generation = int(state["drain_generation"] or state["generation"])
        active_run_count = count_acquisition_nonterminal_runs(
            coordinator,
            workspace_id,
            up_to_generation=drain_generation,
        )
        if active_run_count:
            raise ApifyKeyDrainPendingError(active_run_count=active_run_count)
        draining_secret_id = str(state["draining_secret_id"])
        target_status = str(state["drain_target_status"] or "standby")
        connection.execute(
            """
            UPDATE apify_key_pool_members
            SET status = ?,
                blocked_until = CASE
                    WHEN ? = 'depleted' THEN COALESCE(cycle_end_at, blocked_until)
                    ELSE blocked_until
                END,
                updated_at = ?
            WHERE workspace_id = ? AND secret_id = ?
            """,
            (
                target_status,
                target_status,
                now_iso,
                workspace_id,
                draining_secret_id,
            ),
        )
        candidate = connection.execute(
            """
            SELECT secret_id
            FROM apify_key_pool_members
            WHERE workspace_id = ?
              AND status = 'standby'
              AND role = 'acquisition'
              AND secret_id != ?
            ORDER BY position, secret_id
            LIMIT 1
            """,
            (workspace_id, draining_secret_id),
        ).fetchone()
        candidate_id = str(candidate["secret_id"]) if candidate is not None else None
        rows = coordinator._member_rows(connection, workspace_id)
        ordered_ids = [
            *([candidate_id] if candidate_id else []),
            *[
                str(row["secret_id"])
                for row in rows
                if row["secret_id"] not in {candidate_id, draining_secret_id}
                and row["status"] == "standby"
            ],
            *[
                str(row["secret_id"])
                for row in rows
                if row["secret_id"] not in {candidate_id, draining_secret_id}
                and row["status"] != "standby"
            ],
            draining_secret_id,
        ]
        coordinator._compact_positions(
            connection,
            workspace_id=workspace_id,
            ordered_secret_ids=ordered_ids,
            now_iso=now_iso,
        )
        if candidate_id:
            connection.execute(
                """
                UPDATE apify_key_pool_members
                SET status = 'active', blocked_until = NULL, updated_at = ?
                WHERE workspace_id = ? AND secret_id = ?
                """,
                (now_iso, workspace_id, candidate_id),
            )
        connection.execute(
            """
            UPDATE apify_key_pool_state
            SET generation = generation + 1,
                status = ?,
                active_secret_id = ?,
                draining_secret_id = NULL,
                drain_generation = NULL,
                drain_target_status = NULL,
                drain_reason = NULL,
                drain_started_at = NULL,
                blocked_reason = NULL,
                updated_at = ?
            WHERE workspace_id = ?
            """,
            (
                "ready" if candidate_id else "exhausted",
                candidate_id,
                now_iso,
                workspace_id,
            ),
        )
        if owns_transaction:
            connection.commit()
    except Exception:
        if owns_transaction and connection.in_transaction:
            connection.rollback()
        raise
    return coordinator.public_state(workspace_id)


async def report_acquisition_credential_failure(
    coordinator: Any,
    lease: Any,
    *,
    failure_kind: Any,
    status_code: int,
    error_type: str | None,
    abort_run: Any,
) -> None:
    """Drain only production credentials after a production credential failure."""

    from .apify_key_pool import ApifyKeyDrainPendingError

    workspace_id, draining = coordinator._record_credential_failure(
        lease,
        failure_kind,
        status_code=status_code,
        error_type=error_type,
    )
    if not draining:
        return
    state = coordinator._state_row(coordinator.store.connect(), workspace_id)
    drain_generation = int(state["drain_generation"] or state["generation"])
    try:
        async with asyncio.timeout(30):
            for run in list_acquisition_nonterminal_runs(
                coordinator,
                workspace_id,
                up_to_generation=drain_generation,
            ):
                remote_run_id = str(run["remote_run_id"] or "")
                if not remote_run_id:
                    raise ApifyKeyDrainPendingError(active_run_count=1)
                run_lease = coordinator.lease_for_run(str(run["id"]))
                coordinator.mark_run_aborting(run_lease, remote_run_id)
                terminal_status = await abort_run(run_lease, remote_run_id)
                normalized = _normalize_run_status(terminal_status)
                if normalized not in APIFY_RUN_TERMINAL_STATUSES:
                    raise ApifyKeyDrainPendingError(active_run_count=1)
                coordinator.mark_run_terminal(run_lease, remote_run_id, normalized)
    except TimeoutError:
        remaining = count_acquisition_nonterminal_runs(
            coordinator,
            workspace_id,
            up_to_generation=drain_generation,
        )
        raise ApifyKeyDrainPendingError(active_run_count=remaining) from None
    complete_acquisition_drain_and_failover(coordinator, workspace_id)


__all__ = [
    "complete_acquisition_drain_and_failover",
    "count_acquisition_nonterminal_runs",
    "list_acquisition_nonterminal_runs",
    "report_acquisition_credential_failure",
]
