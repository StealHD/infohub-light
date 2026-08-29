"""Read-only SQL evidence used by ActorOps operational health."""

from __future__ import annotations

from datetime import datetime, timedelta
from typing import Any


def candidate_rows(repository: Any, candidate_ids: tuple[str, ...]) -> list[Any]:
    placeholders = ",".join("?" for _ in candidate_ids)
    return repository.connection.execute(
        f"""SELECT candidate_id, last_success_at, last_failure_at,
                   last_error_class, last_error_code
              FROM actor_candidates_v2
             WHERE workspace_id=? AND candidate_id IN ({placeholders})""",
        (repository.workspace_id, *candidate_ids),
    ).fetchall()


def attempt_evidence(
    repository: Any, candidate_ids: tuple[str, ...], now: datetime
) -> dict[str, tuple[Any, ...]]:
    placeholders = ",".join("?" for _ in candidate_ids)
    cutoff = (now - timedelta(hours=48)).isoformat()
    rows = repository.connection.execute(
        f"""SELECT attempt.candidate_id, attempt.source_id,
                   attempt.binding_version, attempt.status,
                   attempt.failure_class, attempt.error_code,
                   attempt.actual_cost_usd, attempt.cost_final,
                   attempt.updated_at
              FROM actor_attempts_v2 AS attempt
             WHERE attempt.workspace_id=?
               AND attempt.candidate_id IN ({placeholders})
               AND attempt.kind='fetch' AND attempt.updated_at>=?
             ORDER BY attempt.updated_at""",
        (repository.workspace_id, *candidate_ids, cutoff),
    ).fetchall()
    grouped: dict[str, list[Any]] = {}
    for row in rows:
        grouped.setdefault(str(row["candidate_id"]), []).append(row)
    return {candidate_id: tuple(items) for candidate_id, items in grouped.items()}


def stale_evidence(
    repository: Any, candidate_ids: tuple[str, ...], now: datetime
) -> dict[str, frozenset[str]]:
    placeholders = ",".join("?" for _ in candidate_ids)
    cutoff = (now - timedelta(hours=24)).isoformat()
    rows = repository.connection.execute(
        f"""SELECT candidate_id, source_id, last_confirmed_at
             FROM actor_source_candidate_freshness_v2
             WHERE workspace_id=? AND candidate_id IN ({placeholders})
               AND state='source_stale'
               AND last_outcome IN ('stale_regression','cross_check_advanced')
               AND last_confirmed_at>=?""",
        (repository.workspace_id, *candidate_ids, cutoff),
    ).fetchall()
    grouped: dict[str, set[str]] = {}
    for row in rows:
        grouped.setdefault(str(row["candidate_id"]), set()).add(str(row["source_id"]))
    return {candidate_id: frozenset(items) for candidate_id, items in grouped.items()}


def candidate_retry_at(
    repository: Any, candidate_ids: tuple[str, ...], now: datetime
) -> dict[str, str]:
    placeholders = ",".join("?" for _ in candidate_ids)
    rows = repository.connection.execute(
        f"""SELECT candidate_id, MIN(cooldown_until) AS retry_at
              FROM actor_source_candidate_freshness_v2
             WHERE workspace_id=? AND candidate_id IN ({placeholders})
               AND cooldown_until>?
             GROUP BY candidate_id""",
        (repository.workspace_id, *candidate_ids, now.isoformat()),
    ).fetchall()
    return {
        str(row["candidate_id"]): str(row["retry_at"])
        for row in rows
        if row["retry_at"]
    }


def ready_bindings(
    repository: Any, route_id: str, *, source_id: str | None = None
) -> tuple[Any, ...]:
    if not route_id:
        return ()
    source_clause = " AND source_id=?" if source_id else ""
    params = (
        (repository.workspace_id, route_id, source_id)
        if source_id
        else (repository.workspace_id, route_id)
    )
    return tuple(repository.connection.execute(
        f"""SELECT source_id, binding_version, last_known_good_candidate_id
              FROM actor_source_bindings_v2
             WHERE workspace_id=? AND route_id=? AND status='ready'{source_clause}""",
        params,
    ).fetchall())


def active_cooldowns(
    repository: Any,
    route_id: str,
    now: datetime,
    *,
    source_id: str | None = None,
) -> frozenset[tuple[str, str, int]]:
    if not route_id:
        return frozenset()
    source_clause = " AND fresh.source_id=?" if source_id else ""
    params = (
        (repository.workspace_id, route_id, now.isoformat(), source_id)
        if source_id
        else (repository.workspace_id, route_id, now.isoformat())
    )
    rows = repository.connection.execute(
        f"""SELECT fresh.source_id, fresh.candidate_id, fresh.binding_version
             FROM actor_source_candidate_freshness_v2 AS fresh
             JOIN actor_candidates_v2 AS candidate
               ON candidate.workspace_id=fresh.workspace_id
              AND candidate.candidate_id=fresh.candidate_id
            WHERE fresh.workspace_id=? AND candidate.route_id=?
              AND fresh.cooldown_until>?
              {source_clause}""",
        params,
    ).fetchall()
    return frozenset(
        (str(row["source_id"]), str(row["candidate_id"]), int(row["binding_version"]))
        for row in rows
    )


def recent_fallback_sources(
    repository: Any,
    route_id: str,
    now: datetime,
    *,
    source_id: str | None = None,
) -> frozenset[str]:
    if not route_id:
        return frozenset()
    source_clause = " AND source_id=?" if source_id else ""
    cutoff = (now - timedelta(hours=24)).isoformat()
    params = (
        (repository.workspace_id, route_id, cutoff, source_id)
        if source_id
        else (repository.workspace_id, route_id, cutoff)
    )
    rows = repository.connection.execute(
        f"""SELECT DISTINCT source_id FROM actor_execution_events_v2
           WHERE workspace_id=? AND route_id=? AND phase='native_fallback'
             AND outcome='fallback' AND created_at>=? AND source_id IS NOT NULL
             {source_clause}""",
        params,
    ).fetchall()
    return frozenset(str(row["source_id"]) for row in rows)


def next_repair_at(
    repository: Any, route_id: str, *, source_id: str | None = None
) -> str | None:
    if not route_id:
        return None
    source_clause = " AND source_id=?" if source_id else ""
    params = (
        (repository.workspace_id, route_id, source_id)
        if source_id
        else (repository.workspace_id, route_id)
    )
    row = repository.connection.execute(
        f"""SELECT MIN(next_attempt_at) FROM actor_route_repairs_v2
           WHERE workspace_id=? AND route_id=?
             AND status IN ('queued','discovering','awaiting_probe','blocked')
             {source_clause}""",
        params,
    ).fetchone()
    return str(row[0]) if row and row[0] else None


__all__ = [
    "active_cooldowns",
    "attempt_evidence",
    "candidate_retry_at",
    "candidate_rows",
    "next_repair_at",
    "ready_bindings",
    "recent_fallback_sources",
    "stale_evidence",
]
