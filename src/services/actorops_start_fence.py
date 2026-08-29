"""Pre-POST fence between ActorOps Attempts and Apify reservations."""

from __future__ import annotations

import sqlite3
from collections.abc import Callable
from typing import Any


_STARTABLE = frozenset({"created", "starting"})
_RUNNING_RESERVATIONS = frozenset(
    {"reserved", "starting", "running", "aborting", "start_outcome_unknown"}
)


def assert_actorops_acquisition_startable(
    connection: sqlite3.Connection,
    workspace_id: str,
    logical_run_id: str | None,
    now_iso: str,
    reject: Callable[[], Exception],
    current_reservation_id: str | None = None,
) -> None:
    """Reject stale ActorOps work while its reservation transaction is locked."""

    if not logical_run_id:
        return
    actorops_schema = connection.execute(
        """SELECT 1 FROM sqlite_master
            WHERE type='table' AND name='actor_attempts_v2'"""
    ).fetchone()
    if actorops_schema is None:
        return
    attempt = connection.execute(
        """SELECT attempt_id, logical_job_id, kind, status, cost_final,
                  remote_run_id, result_state
             FROM actor_attempts_v2
            WHERE workspace_id=? AND attempt_id=?""",
        (workspace_id, str(logical_run_id)),
    ).fetchone()
    if attempt is None:
        return
    if (
        str(attempt["status"]) not in _STARTABLE
        or bool(attempt["cost_final"])
        or attempt["remote_run_id"] is not None
        or str(attempt["result_state"]) != "pending"
    ):
        raise reject()
    # Only fetch Attempts use fetch_jobs claims. Probe/maintenance Attempts
    # carry plan identifiers in logical_job_id and are fenced by Attempt state.
    if str(attempt["kind"]) == "fetch":
        job = connection.execute(
            """SELECT status, worker_id, claim_token, locked_until
                 FROM fetch_jobs WHERE workspace_id=? AND id=?""",
            (workspace_id, str(attempt["logical_job_id"] or "")),
        ).fetchone()
        if (
            job is None
            or str(job["status"]) != "running"
            or not job["worker_id"]
            or not job["claim_token"]
            or not job["locked_until"]
            or str(job["locked_until"]) < now_iso
        ):
            raise reject()
    placeholders = ",".join("?" for _ in _RUNNING_RESERVATIONS)
    parameters: list[object] = [
        workspace_id,
        str(logical_run_id),
        *_RUNNING_RESERVATIONS,
    ]
    current_clause = ""
    if current_reservation_id is not None:
        current_clause = " AND id<>?"
        parameters.append(str(current_reservation_id))
    conflict = connection.execute(
        f"""SELECT 1 FROM apify_actor_runs
              WHERE workspace_id=? AND purpose='acquisition'
                AND logical_run_id=? AND status IN ({placeholders})
                {current_clause} LIMIT 1""",
        parameters,
    ).fetchone()
    if conflict is not None:
        raise reject()


def assert_apify_lease_startable(
    service: Any, lease: Any, reject: Callable[[], Exception]
) -> None:
    """Recheck the pool and exact ActorOps claim immediately before POST."""

    connection = service.store.connect()
    run = service._run_for_lease(connection, lease)
    if str(run["purpose"] or "acquisition") == "validation":
        member = connection.execute(
            """SELECT role, status FROM apify_key_pool_members
                WHERE workspace_id = ? AND secret_id = ?""",
            (str(run["workspace_id"]), str(run["secret_id"])),
        ).fetchone()
        if member is None:
            raise reject()
        if str(member["role"]) == "validation":
            usable = str(member["status"]) == "standby"
        else:
            state = service._state_row(connection, str(run["workspace_id"]))
            usable = (
                str(member["role"]) == "acquisition"
                and str(member["status"]) == "active"
                and state["status"] == "ready"
                and state["active_secret_id"] == run["secret_id"]
            )
        if run["status"] != "reserved" or not usable:
            raise reject()
        return
    assert_actorops_acquisition_startable(
        connection,
        str(run["workspace_id"]),
        run["logical_run_id"],
        service._current_time().isoformat(),
        reject,
        str(run["id"]),
    )
    state = service._state_row(connection, str(run["workspace_id"]))
    if (
        run["status"] != "reserved"
        or state["status"] != "ready"
        or state["active_secret_id"] != run["secret_id"]
    ):
        raise reject()


__all__ = [
    "assert_actorops_acquisition_startable",
    "assert_apify_lease_startable",
]
