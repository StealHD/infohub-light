"""Automatic, read-only reconciliation of durable interrupted Actor Runs."""

from __future__ import annotations

import asyncio
import os
from typing import Any

import httpx

from ..scrapers.apify_client import ApifyClient
from ..storage.service_store import ServiceStore
from .apify_pool_runtime import apify_coordinator_for_workspace
from .job_queue import JobQueue

_RECOVERABLE_OUTCOMES = (
    "apify_run_status_unavailable",
    "apify_actor_run_status_unavailable",
    "apify_run_reconcile_required",
    "apify_worker_restart_reconcile_required",
)


async def _reconcile_workspace(
    store: ServiceStore,
    *,
    workspace_id: str,
    data_dir: str,
) -> dict[str, int]:
    from .apify_actor_canary import ApifyActorCanaryRunner, actor_canary_timeout_seconds
    from .apify_actor_ops import ActorOpsError, ApifyActorOpsService

    ops = ApifyActorOpsService(store, workspace_id=workspace_id)
    rows = store.connect().execute(
        """
        SELECT validation.validation_id,
               CASE WHEN validation.semantic_outcome IN (?, ?, ?, ?)
                    THEN 1 ELSE 0 END AS requires_remote_read
        FROM apify_actor_validations AS validation
        JOIN apify_actor_route_profiles AS profile
          ON profile.workspace_id = validation.workspace_id
         AND profile.route_id = validation.route_id
        WHERE validation.workspace_id = ?
          AND validation.status IN ('failed', 'cancelled')
          AND validation.attempt_id IS NOT NULL
          AND EXISTS (
              SELECT 1 FROM apify_actor_runs AS run
              WHERE run.workspace_id = validation.workspace_id
                AND run.logical_run_id = validation.attempt_id
                AND run.remote_run_id IS NOT NULL
          )
          AND (
              validation.semantic_outcome IN (?, ?, ?, ?)
              OR (
                  profile.status = 'blocked_unknown_start'
                  AND validation.kind = 'route_reference'
                  AND validation.cost_final = 1
                  AND EXISTS (
                      SELECT 1
                      FROM apify_actor_canary_batch_items AS item
                      JOIN apify_actor_canary_batches AS batch
                        ON batch.workspace_id = item.workspace_id
                       AND batch.batch_id = item.batch_id
                      WHERE item.workspace_id = validation.workspace_id
                        AND item.validation_id = validation.validation_id
                        AND item.status = 'failed'
                        AND batch.status IN ('blocked_unknown_start', 'running')
                  )
              )
          )
        ORDER BY validation.completed_at, validation.validation_id
        LIMIT 20
        """,
        (*_RECOVERABLE_OUTCOMES, workspace_id, *_RECOVERABLE_OUTCOMES),
    ).fetchall()
    if not rows:
        return {"checked": 0, "reconciled": 0, "continued": 0}
    reconciled = 0
    continuation_batches: set[str] = set()
    remote_rows = [row for row in rows if bool(row["requires_remote_read"])]
    for row in rows:
        if not bool(row["requires_remote_read"]):
            recovery = ops.resume_reconciled_validation(str(row["validation_id"]))
            if recovery["enqueue_batch"] and recovery["batch_id"]:
                continuation_batches.add(str(recovery["batch_id"]))
    if remote_rows:
        coordinator = apify_coordinator_for_workspace(
            store, workspace_id=workspace_id, data_dir=data_dir, purpose="validation"
        )
        if coordinator is None:
            return _reconciliation_result(
                store,
                workspace_id=workspace_id,
                checked=len(rows),
                reconciled=0,
                continuation_batches=continuation_batches,
            )
        state = coordinator.public_state(workspace_id)
        secret_id = str(state.get("validation_secret_id") or state.get("active_secret_id") or "")
        if not secret_id:
            return _reconciliation_result(
                store,
                workspace_id=workspace_id,
                checked=len(rows),
                reconciled=0,
                continuation_batches=continuation_batches,
            )
        credential = coordinator.quota_candidate(secret_id)
        async with httpx.AsyncClient(timeout=httpx.Timeout(30.0, connect=10.0), trust_env=False) as http_client:
            runner = ApifyActorCanaryRunner(
                store, ops,
                ApifyClient(tokens=[(credential.env_name, credential.token)], coordinator=coordinator, http_client=http_client, timeout_seconds=actor_canary_timeout_seconds()),
            )
            for row in remote_rows:
                validation_id = str(row["validation_id"])
                try:
                    await runner.reconcile(validation_id)
                except ActorOpsError:
                    # The remote Run may still be active or unavailable.  It stays
                    # blocked and no Actor POST is attempted.
                    continue
                ops.reconcile_terminal_validation_costs()
                recovery = ops.resume_reconciled_validation(validation_id)
                reconciled += 1
                if recovery["enqueue_batch"] and recovery["batch_id"]:
                    continuation_batches.add(str(recovery["batch_id"]))
    return _reconciliation_result(
        store,
        workspace_id=workspace_id,
        checked=len(rows),
        reconciled=reconciled,
        continuation_batches=continuation_batches,
    )


def _reconciliation_result(
    store: ServiceStore,
    *,
    workspace_id: str,
    checked: int,
    reconciled: int,
    continuation_batches: set[str],
) -> dict[str, int]:
    return {
        "checked": checked,
        "reconciled": reconciled,
        "continued": _enqueue_originally_approved_batches(
            store,
            workspace_id=workspace_id,
            batch_ids=continuation_batches,
        ),
    }


def _enqueue_originally_approved_batches(
    store: ServiceStore,
    *,
    workspace_id: str,
    batch_ids: set[str],
) -> int:
    """Continue only the original approval's frozen batch, once per batch."""

    if not batch_ids:
        return 0
    queue = JobQueue(store)
    connection = store.connect()
    admin = connection.execute(
        """
        SELECT id FROM users
        WHERE workspace_id = ? AND enabled = 1 AND role IN ('owner', 'admin')
        ORDER BY CASE role WHEN 'owner' THEN 0 ELSE 1 END, created_at, id
        LIMIT 1
        """,
        (workspace_id,),
    ).fetchone()
    if admin is None:
        return 0
    queued = 0
    for batch_id in sorted(batch_ids):
        active = connection.execute(
            """
            SELECT 1 FROM fetch_jobs
            WHERE workspace_id = ? AND job_type = 'apify_actor_canary_batch'
              AND status IN ('queued', 'running')
              AND json_extract(payload_json, '$.batch_id') = ?
            LIMIT 1
            """,
            (workspace_id, batch_id),
        ).fetchone()
        if active is not None:
            continue
        queue.create_job(
            workspace_id=workspace_id,
            user_id=str(admin["id"]),
            job_type="apify_actor_canary_batch",
            payload={"batch_id": batch_id},
            priority=100,
            max_attempts=1,
            retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
        )
        queued += 1
    return queued


def reconcile_interrupted_canary_runs(
    store: ServiceStore,
    *,
    workspace_id: str,
    data_dir: str,
) -> dict[str, int]:
    """Re-read known remote Runs; this path cannot issue a new Actor POST."""

    return asyncio.run(
        _reconcile_workspace(store, workspace_id=workspace_id, data_dir=data_dir)
    )


__all__ = ["reconcile_interrupted_canary_runs"]
