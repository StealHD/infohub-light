"""One-shot remote reads for durable Runs owned by retired auto-pool work."""

from __future__ import annotations

import asyncio
import math
import sqlite3
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path
from typing import Any
from urllib.parse import quote

import httpx

from ..scrapers.apify_client import ApifyActorRunResult
from ..storage.service_store import ServiceStore
from .apify_actor_canary import ApifyActorCanaryRunner
from .apify_actor_auto_pool_retirement import inspect_retirement
from .apify_actor_ops import ApifyActorOpsService
from .apify_actor_recovery_continuation import clear_start_unknown_barrier
from .apify_key_pool import ApifyKeyPoolService
from .secret_store import SecretStore


_RECOVERABLE_OUTCOMES = (
    "apify_run_status_unavailable",
    "apify_actor_run_status_unavailable",
    "apify_run_reconcile_required",
    "apify_worker_restart_reconcile_required",
)
_TERMINAL_REMOTE_STATUSES = frozenset(
    {"SUCCEEDED", "FAILED", "ABORTED", "TIMED-OUT"}
)
_BASE_URL = "https://api.apify.com/v2"
_MAX_RESPONSE_BYTES = 2 * 1024 * 1024


@dataclass(frozen=True, slots=True)
class _Observation:
    status: str
    actual_cost_usd: float | None
    items: list[dict[str, Any]] | None


class _ObservedRunClient:
    """Canary adapter that returns an already-read Run without network I/O."""

    def __init__(self, observation: _Observation) -> None:
        self.observation = observation

    async def resume_actor_detailed(
        self,
        _reservation_id: str,
        **_kwargs: Any,
    ) -> ApifyActorRunResult:
        return ApifyActorRunResult(
            items=list(self.observation.items or []),
            actual_charge_usd=self.observation.actual_cost_usd,
            cost_final=self.observation.actual_cost_usd is not None,
        )


def _database(data_dir: Path | str) -> Path:
    database = Path(data_dir) / "service.db"
    if not database.is_file():
        raise RuntimeError("service database does not exist")
    return database


def _candidate_rows(connection: sqlite3.Connection, *, limit: int) -> list[dict[str, Any]]:
    rows = connection.execute(
        f"""
        SELECT validation.validation_id, validation.workspace_id,
               validation.route_id, attempt.route_key,
               validation.validation_sample_items, validation.attempt_id,
               validation.status AS validation_status,
               validation.semantic_outcome AS validation_outcome,
               validation.cost_usd AS validation_cost,
               validation.cost_final AS validation_cost_final,
               attempt.status AS attempt_status,
               attempt.actual_cost_usd AS attempt_cost,
               attempt.cost_final AS attempt_cost_final,
               item.cost_final AS item_cost_final,
               run.id AS durable_run_id, run.remote_run_id, run.dataset_id,
               run.status AS durable_status, run.charge_final,
               run.charge_actual_usd, profile.status AS route_status
        FROM apify_actor_validations AS validation
        JOIN apify_actor_canary_batch_items AS item
          ON item.workspace_id = validation.workspace_id
         AND item.validation_id = validation.validation_id
        JOIN apify_actor_canary_batches AS batch
          ON batch.workspace_id = item.workspace_id
         AND batch.batch_id = item.batch_id
        JOIN apify_actor_discovery_runs AS discovery
          ON discovery.workspace_id = batch.workspace_id
         AND discovery.run_id = batch.discovery_run_id
        JOIN apify_actor_attempts AS attempt
          ON attempt.workspace_id = validation.workspace_id
         AND attempt.id = validation.attempt_id
        JOIN apify_actor_route_profiles AS profile
          ON profile.workspace_id = validation.workspace_id
         AND profile.route_id = validation.route_id
        JOIN apify_actor_runs AS run
          ON run.workspace_id = validation.workspace_id
         AND run.logical_run_id = validation.attempt_id
         AND run.purpose = 'validation'
        WHERE discovery.trigger_reason IN ('auto_pool', 'auto_pool_replenishment')
          AND run.remote_run_id IS NOT NULL
          AND (
              (
                  validation.status IN ('failed', 'cancelled')
                  AND validation.semantic_outcome IN ({','.join('?' for _ in _RECOVERABLE_OUTCOMES)})
                  AND (
                      run.status IN ('reserved', 'starting', 'running', 'aborting')
                      OR run.charge_final = 0 OR run.charge_actual_usd IS NULL
                      OR attempt.status = 'start_outcome_unknown'
                      OR profile.status = 'blocked_unknown_start'
                      OR item.cost_final = 0
                  )
              )
              OR (
                  (
                      item.cost_final = 0
                      OR item.status IN (
                          'planned', 'preflight_passed', 'queued', 'running',
                          'blocked_unknown_start'
                      )
                  )
                  AND validation.status IN ('succeeded', 'failed', 'cancelled')
                  AND validation.cost_final = 1
                  AND validation.cost_usd IS NOT NULL
                  AND attempt.status NOT IN ('reserved', 'running', 'start_outcome_unknown')
                  AND attempt.cost_final = 1
                  AND attempt.actual_cost_usd IS NOT NULL
                  AND run.charge_final = 1
                  AND run.charge_actual_usd IS NOT NULL
              )
          )
        ORDER BY run.updated_at, run.id
        LIMIT ?
        """,
        (*_RECOVERABLE_OUTCOMES, min(max(int(limit), 1), 20)),
    ).fetchall()
    return [dict(row) for row in rows]


def _number(value: Any) -> float | None:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        return None
    number = float(value)
    return number if math.isfinite(number) and number >= 0 else None


def _needs_validation_recovery(row: dict[str, Any]) -> bool:
    return (
        str(row.get("validation_status") or "") in {"failed", "cancelled"}
        and str(row.get("validation_outcome") or "") in _RECOVERABLE_OUTCOMES
    )


def _settle_terminal_failure(
    ops: ApifyActorOpsService,
    row: dict[str, Any],
    observation: _Observation,
) -> None:
    if observation.actual_cost_usd is None:
        raise RuntimeError("terminal Actor Run cost is not final")
    now = datetime.now(timezone.utc).isoformat()
    outcome = "apify_worker_restart_result_lost"
    with ops._write() as connection:
        connection.execute(
            """UPDATE apify_actor_attempts
               SET status = 'cancelled', semantic_outcome = ?, actual_cost_usd = ?,
                   cost_final = 1, last_error_code = ?,
                   terminal_at = COALESCE(terminal_at, ?), updated_at = ?
               WHERE workspace_id = ? AND id = ?
                 AND status = 'start_outcome_unknown'""",
            (outcome, observation.actual_cost_usd, outcome, now, now,
             ops.workspace_id, str(row["attempt_id"])),
        )
        connection.execute(
            """UPDATE apify_actor_validations
               SET status = 'failed', semantic_outcome = ?, cost_usd = ?,
                   cost_final = 1, completed_at = COALESCE(completed_at, ?)
               WHERE workspace_id = ? AND validation_id = ?""",
            (outcome, observation.actual_cost_usd, now, ops.workspace_id,
             str(row["validation_id"])),
        )
        connection.execute(
            """UPDATE apify_actor_canary_batch_items
               SET status = 'failed', semantic_outcome = ?, actual_cost_usd = ?,
                   cost_final = 1, completed_at = COALESCE(completed_at, ?),
                   updated_at = ?
               WHERE workspace_id = ? AND validation_id = ?""",
            (outcome, observation.actual_cost_usd, now, now, ops.workspace_id,
             str(row["validation_id"])),
        )
        clear_start_unknown_barrier(ops, connection, row)


def _clear_reconciled_barrier(
    ops: ApifyActorOpsService, row: dict[str, Any]
) -> None:
    with ops._write() as connection:
        clear_start_unknown_barrier(ops, connection, row)


def _settle_final_item_from_evidence(
    ops: ApifyActorOpsService,
    row: dict[str, Any],
    observation: _Observation,
) -> None:
    """Terminalize one item only after its durable charge is fully corroborated."""

    if observation.actual_cost_usd is None:
        raise RuntimeError("terminal Actor Run cost is not final")
    with ops._write() as connection:
        evidence = connection.execute(
            """SELECT validation.status AS validation_status,
                      validation.semantic_outcome AS validation_outcome,
                      validation.cost_usd AS validation_cost,
                      validation.cost_final AS validation_cost_final,
                      attempt.status AS attempt_status,
                      attempt.actual_cost_usd AS attempt_cost,
                      attempt.cost_final AS attempt_cost_final,
                      run.remote_run_id, run.status AS run_status,
                      run.charge_actual_usd AS run_cost,
                      run.charge_final,
                      item.cost_final AS item_cost_final
               FROM apify_actor_validations AS validation
               JOIN apify_actor_attempts AS attempt
                 ON attempt.workspace_id = validation.workspace_id
                AND attempt.id = validation.attempt_id
               JOIN apify_actor_runs AS run
                 ON run.workspace_id = validation.workspace_id
                AND run.logical_run_id = validation.attempt_id
               JOIN apify_actor_canary_batch_items AS item
                 ON item.workspace_id = validation.workspace_id
                AND item.validation_id = validation.validation_id
               WHERE validation.workspace_id = ?
                 AND validation.validation_id = ? AND run.id = ?""",
            (
                ops.workspace_id,
                str(row["validation_id"]),
                str(row["durable_run_id"]),
            ),
        ).fetchone()
        if evidence is None or str(evidence["remote_run_id"] or "") != str(
            row["remote_run_id"]
        ):
            raise RuntimeError("durable Actor Run evidence changed during reconciliation")
        if str(evidence["run_status"]) != observation.status.lower().replace("-", "_"):
            raise RuntimeError("durable Actor Run status does not match remote evidence")
        if (
            str(evidence["validation_status"]) not in {"succeeded", "failed", "cancelled"}
            or str(evidence["attempt_status"]) in {
                "reserved", "running", "start_outcome_unknown"
            }
            or not bool(evidence["validation_cost_final"])
            or not bool(evidence["attempt_cost_final"])
            or not bool(evidence["charge_final"])
        ):
            raise RuntimeError("local Actor validation evidence is not terminal")
        ledger_cost = round(observation.actual_cost_usd, 6)
        ledger_costs = (evidence["validation_cost"], evidence["attempt_cost"])
        if (
            evidence["run_cost"] is None
            or not math.isclose(
                float(evidence["run_cost"]), observation.actual_cost_usd,
                rel_tol=0.0, abs_tol=1e-9,
            )
            or any(cost is None for cost in ledger_costs)
            or any(
            not math.isclose(
                float(cost), ledger_cost, rel_tol=0.0, abs_tol=1e-9
            )
            for cost in ledger_costs
            )
        ):
            raise RuntimeError("local Actor validation costs do not match durable Run")
        terminal_status = (
            "succeeded" if str(evidence["validation_status"]) == "succeeded" else "failed"
        )
        now = ops._now_iso()
        cursor = connection.execute(
            """UPDATE apify_actor_canary_batch_items
               SET status = ?, semantic_outcome = ?, actual_cost_usd = ?,
                   cost_final = 1, completed_at = COALESCE(completed_at, ?),
                   updated_at = ?
               WHERE workspace_id = ? AND validation_id = ?
                 AND (cost_final = 0 OR status IN (
                     'planned', 'preflight_passed', 'queued', 'running',
                     'blocked_unknown_start'
                 ))""",
            (
                terminal_status,
                evidence["validation_outcome"],
                ledger_cost,
                now,
                now,
                ops.workspace_id,
                str(row["validation_id"]),
            ),
        )
        if cursor.rowcount != 1:
            raise RuntimeError("Actor batch item changed during reconciliation")


async def _single_json_get(
    client: httpx.AsyncClient,
    url: str,
    *,
    token: str,
    params: dict[str, str] | None = None,
) -> Any:
    content = bytearray()
    async with client.stream(
        "GET",
        url,
        headers={
            "Authorization": f"Bearer {token}",
            "Accept": "application/json",
            "Accept-Encoding": "identity",
        },
        params=params,
    ) as response:
        response.raise_for_status()
        async for chunk in response.aiter_bytes():
            if len(content) + len(chunk) > _MAX_RESPONSE_BYTES:
                raise RuntimeError("Apify reconciliation response exceeded its byte limit")
            content.extend(chunk)
    try:
        return httpx.Response(200, content=bytes(content)).json()
    except ValueError as exc:
        raise RuntimeError("Apify reconciliation response was not JSON") from exc


async def _read_once(
    client: httpx.AsyncClient,
    *,
    token: str,
    remote_run_id: str,
    dataset_id: str | None,
    item_limit: int,
    base_url: str,
    read_items: bool = True,
) -> _Observation:
    encoded_run = quote(remote_run_id, safe="")
    payload = await _single_json_get(
        client, f"{base_url.rstrip('/')}/actor-runs/{encoded_run}", token=token
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        raise RuntimeError("Apify Run response omitted data")
    returned_id = str(data.get("id") or "")
    if returned_id and returned_id != remote_run_id:
        raise RuntimeError("Apify Run response did not match the durable Run")
    status = str(data.get("status") or "").upper()
    if status not in _TERMINAL_REMOTE_STATUSES:
        return _Observation(status=status, actual_cost_usd=None, items=None)
    cost = _number(data.get("usageTotalUsd"))
    if cost is None:
        return _Observation(status=status, actual_cost_usd=None, items=None)
    if status != "SUCCEEDED" or not read_items:
        return _Observation(status=status, actual_cost_usd=cost, items=None)
    if not dataset_id:
        raise RuntimeError("durable succeeded Run omitted its dataset identifier")
    encoded_dataset = quote(dataset_id, safe="")
    raw_items = await _single_json_get(
        client,
        f"{base_url.rstrip('/')}/datasets/{encoded_dataset}/items",
        token=token,
        params={"clean": "true", "limit": str(item_limit)},
    )
    if not isinstance(raw_items, list) or len(raw_items) > item_limit:
        raise RuntimeError("Apify Dataset response exceeded its row limit")
    return _Observation(
        status=status,
        actual_cost_usd=cost,
        items=[item for item in raw_items if isinstance(item, dict)],
    )


def _finalize_settled_batches(
    store: ServiceStore,
    ops_by_workspace: dict[str, ApifyActorOpsService],
) -> int:
    rows = store.connect().execute(
        """SELECT batch.workspace_id, batch.batch_id
           FROM apify_actor_canary_batches AS batch
           JOIN apify_actor_discovery_runs AS discovery
             ON discovery.workspace_id = batch.workspace_id
            AND discovery.run_id = batch.discovery_run_id
           WHERE discovery.trigger_reason IN ('auto_pool', 'auto_pool_replenishment')
             AND (batch.status IN ('queued', 'preflighting', 'running')
                  OR batch.cost_final = 0)
             AND EXISTS (
                 SELECT 1 FROM apify_actor_canary_batch_items AS item
                 WHERE item.workspace_id = batch.workspace_id
                   AND item.batch_id = batch.batch_id
             )
             AND NOT EXISTS (
                 SELECT 1 FROM apify_actor_canary_batch_items AS item
                 WHERE item.workspace_id = batch.workspace_id
                   AND item.batch_id = batch.batch_id
                   AND (item.cost_final = 0 OR item.status IN (
                       'planned', 'preflight_passed', 'queued', 'running',
                       'blocked_unknown_start'
                   ))
             )
           ORDER BY batch.created_at, batch.batch_id"""
    ).fetchall()
    finalized = 0
    for row in rows:
        workspace_id = str(row["workspace_id"])
        ops = ops_by_workspace.setdefault(
            workspace_id,
            ApifyActorOpsService(store, workspace_id=workspace_id),
        )
        ops.finalize_canary_batch(
            str(row["batch_id"]), stop_reason="apify_actor_auto_pool_retired"
        )
        finalized += 1
    return finalized


async def _reconcile(
    data_dir: Path,
    *,
    limit: int,
    http_transport: httpx.AsyncBaseTransport | None,
    base_url: str,
) -> dict[str, int]:
    store = ServiceStore(data_dir)
    connection = store.connect()
    rows = _candidate_rows(connection, limit=limit)
    if not rows:
        finalized = _finalize_settled_batches(store, {})
        store.close()
        return {
            "checked": 0, "reconciled": 0, "unresolved": 0,
            "finalized_batches": finalized,
        }
    coordinators: dict[str, ApifyKeyPoolService] = {}
    ops_by_workspace: dict[str, ApifyActorOpsService] = {}
    reconciled = 0
    unresolved = 0
    timeout = httpx.Timeout(15.0, connect=5.0)
    try:
        async with httpx.AsyncClient(
            timeout=timeout, transport=http_transport, trust_env=False
        ) as client:
            for row in rows:
                workspace_id = str(row["workspace_id"])
                coordinator = coordinators.setdefault(
                    workspace_id,
                    ApifyKeyPoolService(
                        store,
                        secret_store=SecretStore(data_dir),
                        workspace_id=workspace_id,
                        run_purpose="validation",
                    ),
                )
                ops = ops_by_workspace.setdefault(
                    workspace_id,
                    ApifyActorOpsService(store, workspace_id=workspace_id),
                )
                try:
                    needs_recovery = _needs_validation_recovery(row)
                    lease = coordinator.lease_for_run(str(row["durable_run_id"]))
                    observation = await _read_once(
                        client,
                        token=lease.token,
                        remote_run_id=str(row["remote_run_id"]),
                        dataset_id=(str(row["dataset_id"]) if row["dataset_id"] else None),
                        item_limit=min(max(int(row["validation_sample_items"] or 1) + 1, 2), 6),
                        base_url=base_url,
                        read_items=needs_recovery,
                    )
                    if observation.status not in _TERMINAL_REMOTE_STATUSES:
                        unresolved += 1
                        continue
                    if observation.actual_cost_usd is None:
                        unresolved += 1
                        continue
                    coordinator.mark_run_terminal(
                        lease, str(row["remote_run_id"]), observation.status
                    )
                    coordinator.record_run_accounting(
                        lease,
                        actual_cost_usd=observation.actual_cost_usd,
                        cost_final=True,
                    )
                    if needs_recovery:
                        if observation.status == "SUCCEEDED" and observation.items is not None:
                            runner = ApifyActorCanaryRunner(
                                store, ops, _ObservedRunClient(observation)  # type: ignore[arg-type]
                            )
                            await runner.reconcile(str(row["validation_id"]))
                        else:
                            _settle_terminal_failure(ops, row, observation)
                    ops.reconcile_terminal_validation_costs()
                    if not needs_recovery:
                        _settle_final_item_from_evidence(ops, row, observation)
                    _clear_reconciled_barrier(ops, row)
                    reconciled += 1
                except Exception:
                    unresolved += 1
        finalized = _finalize_settled_batches(store, ops_by_workspace)
    finally:
        store.close()
    return {
        "checked": len(rows), "reconciled": reconciled,
        "unresolved": unresolved, "finalized_batches": finalized,
    }


def reconcile_retirement(
    data_dir: Path | str,
    *,
    confirm_worker_stopped: bool,
    limit: int = 20,
    http_transport: httpx.AsyncBaseTransport | None = None,
    base_url: str = _BASE_URL,
    now: datetime | None = None,
    heartbeat_stale_seconds: float = 35.0,
) -> dict[str, int]:
    """GET each exact durable Run at most once and never issue an Actor POST."""

    resolved = Path(data_dir)
    _database(resolved)
    if not confirm_worker_stopped:
        raise RuntimeError("explicit Worker stopped confirmation is required")
    safety = inspect_retirement(
        resolved,
        now=now,
        heartbeat_stale_seconds=heartbeat_stale_seconds,
    )
    if int(safety["active_worker_count"]):
        raise RuntimeError("worker heartbeat safety window has not elapsed")
    return asyncio.run(
        _reconcile(
            resolved,
            limit=limit,
            http_transport=http_transport,
            base_url=base_url,
        )
    )


__all__ = ["reconcile_retirement"]
