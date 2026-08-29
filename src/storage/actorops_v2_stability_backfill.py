"""Historical source-circuit evidence imported by global 33."""

from __future__ import annotations

import sqlite3
from collections import defaultdict
from datetime import datetime, timedelta, timezone
from typing import Any


_BACKOFF_HOURS = (6, 12, 24)


def backfill_source_circuits(
    connection: sqlite3.Connection, *, now: datetime | None = None
) -> int:
    """Preserve active paid-failure cooldowns across the stability upgrade."""

    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    grouped: dict[tuple[str, str, str, int], list[Any]] = defaultdict(list)
    rows = connection.execute(
        """SELECT attempt.workspace_id, attempt.source_id,
                  attempt.candidate_id, attempt.binding_version,
                  attempt.attempt_id, attempt.logical_job_id, attempt.status,
                  attempt.failure_class, attempt.actual_cost_usd,
                  attempt.cost_final, attempt.created_at, attempt.terminal_at,
                  attempt.updated_at
             FROM actor_attempts_v2 AS attempt
             JOIN actor_source_bindings_v2 AS binding
               ON binding.workspace_id=attempt.workspace_id
              AND binding.source_id=attempt.source_id
              AND binding.binding_version=attempt.binding_version
            WHERE attempt.kind='fetch' AND attempt.source_id IS NOT NULL
              AND attempt.binding_version IS NOT NULL
              AND (
                   attempt.status='succeeded'
                   OR (
                       attempt.status='failed'
                       AND attempt.failure_class='candidate'
                       AND attempt.cost_final=1
                       AND COALESCE(attempt.actual_cost_usd,0)>0
                   )
              )
            ORDER BY COALESCE(
                         attempt.terminal_at,
                         attempt.created_at,
                         attempt.updated_at
                     ), attempt.attempt_id"""
    ).fetchall()
    for row in rows:
        key = (
            str(row["workspace_id"]),
            str(row["source_id"]),
            str(row["candidate_id"]),
            int(row["binding_version"]),
        )
        grouped[key].append(row)
    changed = 0
    for key, evidence in grouped.items():
        failures = _failures_after_last_success(evidence)
        if not failures:
            continue
        latest = failures[-1]
        latest_at = _parse_time(latest["updated_at"])
        if latest_at is None:
            continue
        streak = min(len(failures), len(_BACKOFF_HOURS))
        cooldown = latest_at + timedelta(hours=_BACKOFF_HOURS[streak - 1])
        if cooldown <= current:
            continue
        changed += _upsert(
            connection,
            key=key,
            streak=streak,
            cooldown=cooldown,
            latest=latest,
        )
    return changed


def _failures_after_last_success(evidence: list[Any]) -> list[Any]:
    failures: list[Any] = []
    seen_jobs: set[str] = set()
    for row in evidence:
        if str(row["status"]) == "succeeded":
            failures.clear()
            seen_jobs.clear()
            continue
        job_id = str(row["logical_job_id"] or row["attempt_id"])
        if job_id in seen_jobs:
            continue
        seen_jobs.add(job_id)
        failures.append(row)
    return failures


def _upsert(
    connection: sqlite3.Connection,
    *,
    key: tuple[str, str, str, int],
    streak: int,
    cooldown: datetime,
    latest: Any,
) -> int:
    existing = connection.execute(
        """SELECT last_checked_at, cooldown_until
             FROM actor_source_candidate_freshness_v2
            WHERE workspace_id=? AND source_id=? AND candidate_id=?
              AND binding_version=?""",
        key,
    ).fetchone()
    latest_stamp = str(latest["updated_at"])
    if existing is not None and (
        str(existing["last_checked_at"] or "") > latest_stamp
        or str(existing["cooldown_until"] or "") > cooldown.isoformat()
    ):
        return 0
    job_id = str(latest["logical_job_id"] or latest["attempt_id"])
    if len(job_id) > 128:
        job_id = str(latest["attempt_id"])
    connection.execute(
        """INSERT INTO actor_source_candidate_freshness_v2 (
               workspace_id, source_id, candidate_id, binding_version,
               consecutive_scheduled_no_advance, state, cooldown_until,
               last_outcome, last_job_id, last_checked_at, last_confirmed_at,
               failure_streak, cooldown_reason, half_open_lease_until,
               half_open_lease_token, created_at, updated_at
           ) VALUES (?,?,?,?,0,'source_stale',?,'paid_candidate_failure',?,?,?,
                     ?,'paid_candidate_failure',NULL,NULL,?,?)
           ON CONFLICT(workspace_id,source_id,candidate_id,binding_version)
           DO UPDATE SET consecutive_scheduled_no_advance=0,
               state='source_stale', cooldown_until=excluded.cooldown_until,
               last_outcome=excluded.last_outcome,
               last_job_id=excluded.last_job_id,
               last_checked_at=excluded.last_checked_at,
               last_confirmed_at=excluded.last_confirmed_at,
               failure_streak=excluded.failure_streak,
               cooldown_reason=excluded.cooldown_reason,
               half_open_lease_until=NULL, half_open_lease_token=NULL,
               updated_at=excluded.updated_at""",
        (
            *key,
            cooldown.isoformat(),
            job_id,
            latest_stamp,
            latest_stamp,
            streak,
            latest_stamp,
            latest_stamp,
        ),
    )
    return 1


def _parse_time(value: Any) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = ["backfill_source_circuits"]
