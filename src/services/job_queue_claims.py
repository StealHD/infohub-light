"""Claim and lease-recovery transactions for the Worker queue."""

from __future__ import annotations

import uuid
from collections.abc import Collection
from datetime import datetime, timedelta, timezone
from typing import Any

from ..storage.service_store import ServiceStore
from .worker_job_policy import RETIRED_ACTOROPS_V1_JOB_TYPES


def _claimable_job_type_clause(
    allowed_job_types: Collection[str] | None,
) -> tuple[str, tuple[str, ...]]:
    """Return a filter that excludes all retired ActorOps v1 Job types."""

    retired = tuple(sorted(RETIRED_ACTOROPS_V1_JOB_TYPES))
    clauses = ["job_type NOT IN (" + ", ".join("?" for _ in retired) + ")"]
    params: list[str] = list(retired)
    if allowed_job_types is not None:
        allowed = tuple(sorted({str(item) for item in allowed_job_types}))
        if not allowed:
            return "0 = 1", ()
        clauses.append("job_type IN (" + ", ".join("?" for _ in allowed) + ")")
        params.extend(allowed)
    return " AND ".join(clauses), tuple(params)


def claim_next_job(
    store: ServiceStore,
    *,
    worker_id: str,
    lease_seconds: float,
    allowed_job_types: Collection[str] | None,
) -> dict[str, Any] | None:
    """Atomically claim one allowed queued Job."""

    connection = store.connect()
    now_dt = datetime.now(timezone.utc)
    now = now_dt.isoformat()
    locked_until = (
        now_dt + timedelta(seconds=max(float(lease_seconds), 1))
    ).isoformat()
    claim_token = uuid.uuid4().hex
    clause, parameters = _claimable_job_type_clause(allowed_job_types)
    try:
        connection.execute("BEGIN IMMEDIATE")
        row = connection.execute(
            f"""SELECT id FROM fetch_jobs
                WHERE status='queued'
                  AND (next_run_at IS NULL OR next_run_at <= ?)
                  AND {clause}
                ORDER BY priority DESC, created_at LIMIT 1""",
            (now, *parameters),
        ).fetchone()
        if row is None:
            connection.commit()
            return None
        job_id = str(row["id"])
        updated = connection.execute(
            f"""UPDATE fetch_jobs
                SET status='running', attempts=attempts+1, worker_id=?,
                    claim_token=?, started_at=COALESCE(started_at, ?),
                    locked_until=?, updated_at=?
                WHERE id=? AND status='queued'
                  AND (next_run_at IS NULL OR next_run_at <= ?)
                  AND {clause}""",
            (
                worker_id,
                claim_token,
                now,
                locked_until,
                now,
                job_id,
                now,
                *parameters,
            ),
        )
        if updated.rowcount != 1:
            connection.rollback()
            return None
        claimed = connection.execute(
            "SELECT * FROM fetch_jobs WHERE id=?", (job_id,)
        ).fetchone()
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return store._job(claimed)


def recover_stale_running_jobs(
    store: ServiceStore,
    *,
    now: datetime | None,
    allowed_job_types: Collection[str] | None,
) -> list[dict[str, Any]]:
    """Recover expired allowed leases without touching retired v1 Jobs."""

    now_iso = (now or datetime.now(timezone.utc)).isoformat()
    connection = store.connect()
    clause, parameters = _claimable_job_type_clause(allowed_job_types)
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            f"""SELECT id, workspace_id, user_id, source_id, subscription_id,
                       attempts, max_attempts
                FROM fetch_jobs
                WHERE status='running' AND locked_until IS NOT NULL
                  AND locked_until < ? AND {clause}
                ORDER BY created_at ASC, id ASC""",
            (now_iso, *parameters),
        ).fetchall()
        connection.execute(
            f"""UPDATE fetch_jobs
                SET status=CASE WHEN attempts >= max_attempts THEN 'failed'
                                ELSE 'queued' END,
                    worker_id=NULL, claim_token=NULL, locked_until=NULL,
                    error_code='lease_expired',
                    error_message='Worker lease expired before completion',
                    finished_at=CASE WHEN attempts >= max_attempts THEN ?
                                     ELSE finished_at END,
                    updated_at=?
                WHERE status='running' AND locked_until IS NOT NULL
                  AND locked_until < ? AND {clause}""",
            (now_iso, now_iso, now_iso, *parameters),
        )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return [
        {
            "job_id": str(row["id"]),
            "workspace_id": str(row["workspace_id"]),
            "user_id": str(row["user_id"]),
            "source_id": row["source_id"],
            "subscription_id": row["subscription_id"],
            "attempts": int(row["attempts"]),
            "status": "failed"
            if int(row["attempts"]) >= int(row["max_attempts"])
            else "queued",
        }
        for row in rows
    ]


__all__ = ["claim_next_job", "recover_stale_running_jobs"]
