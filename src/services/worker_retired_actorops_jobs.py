"""Safely retire never-started ActorOps v1 Worker Jobs."""

from __future__ import annotations

import json
from datetime import datetime, timezone

from ..storage.service_store import ServiceStore
from .worker_job_policy import RETIRED_ACTOROPS_V1_JOB_TYPES


def retire_queued_actorops_v1_jobs(store: ServiceStore) -> list[str]:
    """Cancel only queued v1 Jobs that cannot have started or incurred cost.

    This intentionally reads only ``fetch_jobs``. Claimed, running, or otherwise
    ambiguous historical Jobs remain isolated for the offline retirement tool.
    """

    connection = store.connect()
    placeholders = ", ".join("?" for _ in RETIRED_ACTOROPS_V1_JOB_TYPES)
    now = datetime.now(timezone.utc).isoformat()
    try:
        connection.execute("BEGIN IMMEDIATE")
        rows = connection.execute(
            f"""SELECT id
                FROM fetch_jobs
                WHERE job_type IN ({placeholders})
                  AND status = 'queued'
                  AND attempts = 0
                  AND started_at IS NULL
                ORDER BY created_at ASC, id ASC""",
            tuple(sorted(RETIRED_ACTOROPS_V1_JOB_TYPES)),
        ).fetchall()
        if rows:
            connection.execute(
                f"""UPDATE fetch_jobs
                    SET status = 'cancelled',
                        result_json = ?,
                        error_code = 'actorops_v1_retired',
                        error_message = NULL,
                        worker_id = NULL,
                        claim_token = NULL,
                        locked_until = NULL,
                        cancelled_at = COALESCE(cancelled_at, ?),
                        finished_at = ?,
                        updated_at = ?
                    WHERE job_type IN ({placeholders})
                      AND status = 'queued'
                      AND attempts = 0
                      AND started_at IS NULL""",
                (
                    json.dumps(
                        {"invalidation_reason": "actorops_v1_retired"},
                        ensure_ascii=False,
                        sort_keys=True,
                    ),
                    now,
                    now,
                    now,
                    *tuple(sorted(RETIRED_ACTOROPS_V1_JOB_TYPES)),
                ),
            )
        connection.commit()
    except Exception:
        if connection.in_transaction:
            connection.rollback()
        raise
    return [str(row["id"]) for row in rows]


__all__ = ["retire_queued_actorops_v1_jobs"]
