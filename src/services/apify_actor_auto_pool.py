"""Bounded, self-advancing Actor slot replacement/add orchestration.

An ``auto pool`` run turns a single admin action (replace or add one slot
Actor) into a loop that keeps driving ``discovery -> paid canary ->
activation`` until exactly one Actor passes paid Canary (then it atomically
activates that slot) or a hard spend budget is exhausted.

The loop is not a polling loop: each Worker job (discovery, canary batch)
calls :func:`advance_after_discovery` / :func:`advance_after_canary` when it
settles, and ``advance`` inspects the durable run state to decide the next
step.  Because the Worker executes jobs serially and each job settles exactly
once, the state machine is naturally idempotent.
"""

from __future__ import annotations

import os
import uuid
from typing import Any

from .apify_actor_ops import (
    ActorOpsError,
    BATCH_CANARY_CONFIRMATION,
    ROUTE_POOL_ACTIVATION_CONFIRMATION,
)

AUTO_POOL_BUDGET_CAP_USD = 0.50
AUTO_POOL_TRIGGER_REASON = "auto_pool"
AUTO_POOL_REPLENISH_REASON = "auto_pool_replenishment"

_ACTIVE_DISCOVERY_STAGES = frozenset(
    {"queued", "searching", "metadata", "ranking", "static_validation", "input_validation"}
)
_ACTIVE_BATCH_STATUSES = frozenset({"queued", "preflighting", "running"})
_TERMINAL_BATCH_STATUSES = frozenset(
    {"succeeded", "partial", "failed", "blocked_unknown_start"}
)
_TERMINAL_AUTO_POOL_STATUSES = frozenset(
    {"succeeded", "budget_exhausted", "failed", "cancelled"}
)

_AUTO_POOL_COLUMNS = (
    "run_id", "workspace_id", "route_id", "slot_name", "goal", "status",
    "budget_cap_usd", "total_spent_usd", "last_discovery_run_id",
    "last_canary_batch_id", "error_code", "created_by_user_id",
    "created_at", "updated_at",
)


def _now_iso() -> str:
    from datetime import datetime, timezone

    return datetime.now(timezone.utc).isoformat()


def _job_retention_days() -> int:
    return int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14"))


def _load_auto_pool_run(ops: Any, run_id: str) -> dict[str, Any] | None:
    row = ops.store.connect().execute(
        f"""SELECT {", ".join(_AUTO_POOL_COLUMNS)}
            FROM apify_actor_auto_pool_runs
            WHERE workspace_id = ? AND run_id = ?""",
        (ops.workspace_id, str(run_id)),
    ).fetchone()
    return dict(row) if row is not None else None


def _update_auto_pool_run(ops: Any, run_id: str, **fields: Any) -> None:
    assignments = ", ".join(f"{key} = ?" for key in fields)
    values = [*fields.values(), _now_iso(), ops.workspace_id, str(run_id)]
    with ops._write() as connection:
        connection.execute(
            f"""UPDATE apify_actor_auto_pool_runs
                SET {assignments}, updated_at = ?
                WHERE workspace_id = ? AND run_id = ?""",
            values,
        )


def _route_slot_count(ops: Any, route_id: str) -> int:
    route = ops.get_route(str(route_id))
    return sum(1 for slot in route.get("slots", []) if slot.get("revision_id"))


def _enqueue_discovery(ops: Any, run_id: str, user_id: str) -> None:
    from .job_queue import JobQueue

    JobQueue(ops.store).create_job(
        workspace_id=ops.workspace_id,
        user_id=str(user_id),
        job_type="apify_actor_discovery",
        payload={"run_id": str(run_id)},
        priority=50,
        max_attempts=1,
        retention_days=_job_retention_days(),
    )


def _enqueue_canary_batch(ops: Any, batch_id: str, user_id: str) -> None:
    from .job_queue import JobQueue

    JobQueue(ops.store).create_job(
        workspace_id=ops.workspace_id,
        user_id=str(user_id),
        job_type="apify_actor_canary_batch",
        payload={"batch_id": str(batch_id)},
        priority=100,
        max_attempts=1,
        retention_days=_job_retention_days(),
    )


def start_auto_pool(
    ops: Any,
    *,
    route_id: str,
    slot_name: str,
    goal: str,
    expected_generation: int,
    admin_user_id: str,
    budget_cap_usd: float = AUTO_POOL_BUDGET_CAP_USD,
) -> dict[str, Any]:
    """Create an auto-pool run and its first free discovery run."""

    if goal not in {"add_slot", "replace_slot"}:
        raise ActorOpsError(
            "apify_actor_auto_pool_goal_invalid",
            "Automated slot replacement supports add_slot or replace_slot only",
            status_code=422,
        )
    if slot_name not in {"primary", "backup_1", "backup_2"}:
        raise ActorOpsError(
            "apify_actor_auto_pool_slot_invalid",
            "Automated slot replacement requires a valid slot",
            status_code=422,
        )
    route = ops.get_route(str(route_id))
    if int(route["generation"]) != int(expected_generation):
        raise ActorOpsError(
            "apify_actor_route_generation_conflict",
            "Actor route changed; reload before retrying",
        )
    action = ops.slot_operations(str(route_id)).get(slot_name, {})
    if not bool(action.get("add" if goal == "add_slot" else "replace")):
        raise ActorOpsError(
            "apify_actor_pool_slot_operation_blocked",
            "The requested Actor slot operation is currently blocked",
            status_code=409,
        )
    # A fresh run always opens with a free discovery; the first paid step is
    # only reached through advance once eligible candidates exist.
    run_id = f"apify-auto-pool-{uuid.uuid4().hex}"
    now = _now_iso()
    with ops._write() as connection:
        connection.execute(
            f"""INSERT INTO apify_actor_auto_pool_runs
                ({", ".join(_AUTO_POOL_COLUMNS)})
                VALUES ({", ".join("?" for _ in _AUTO_POOL_COLUMNS)})""",
            (
                run_id,
                ops.workspace_id,
                str(route_id),
                slot_name,
                goal,
                "running",
                float(budget_cap_usd),
                0.0,
                None,
                None,
                None,
                str(admin_user_id),
                now,
                now,
            ),
        )
    discovery = ops.create_discovery_run(
        str(route_id),
        trigger_reason=AUTO_POOL_TRIGGER_REASON,
        expected_generation=int(expected_generation),
    )
    _update_auto_pool_run(
        ops, run_id, last_discovery_run_id=str(discovery["run_id"])
    )
    _enqueue_discovery(ops, str(discovery["run_id"]), str(admin_user_id))
    return _load_auto_pool_run(ops, run_id) or {}


def get_auto_pool_run(ops: Any, run_id: str) -> dict[str, Any]:
    ap = _load_auto_pool_run(ops, run_id)
    if ap is None:
        raise ActorOpsError(
            "apify_actor_auto_pool_not_found",
            "Automated slot run was not found",
            status_code=404,
        )
    return ap


def list_running_auto_pool_runs(ops: Any, route_id: str) -> list[dict[str, Any]]:
    rows = ops.store.connect().execute(
        """SELECT run_id FROM apify_actor_auto_pool_runs
           WHERE workspace_id = ? AND route_id = ? AND status = 'running'
           ORDER BY updated_at DESC""",
        (ops.workspace_id, str(route_id)),
    ).fetchall()
    result = []
    for row in rows:
        ap = _load_auto_pool_run(ops, str(row["run_id"]))
        if ap is not None:
            result.append(ap)
    return result


def advance_auto_pool(
    ops: Any,
    run_id: str,
    *,
    admin_user_id: str | None = None,
) -> dict[str, Any]:
    """Idempotently advance one auto-pool run to its next durable step."""

    ap = _load_auto_pool_run(ops, run_id)
    if ap is None:
        raise ActorOpsError(
            "apify_actor_auto_pool_not_found",
            "Automated slot run was not found",
            status_code=404,
        )
    if ap["status"] in _TERMINAL_AUTO_POOL_STATUSES:
        return ap
    user_id = str(admin_user_id or ap["created_by_user_id"] or "")

    # Settle the spend ledger before deciding the next step, then reload so
    # the budget checks below see the accumulated total.
    _settle_spend(ops, ap)
    ap = _load_auto_pool_run(ops, run_id) or ap

    discovery_run_id = ap.get("last_discovery_run_id")
    discovery = (
        ops.get_discovery_run(str(discovery_run_id))
        if discovery_run_id
        else None
    )

    if discovery is None:
        return _begin_discovery(ops, ap, user_id)

    stage = str(discovery["stage"])
    if stage in _ACTIVE_DISCOVERY_STAGES:
        return ap  # discovery still in flight

    if stage == "activation_ready":
        return _activate(ops, ap, user_id)

    if stage == "awaiting_canary_approval":
        return _begin_canary(ops, ap, user_id, discovery)

    # candidate_shortfall, canary_exhausted, failed, blocked_*, ...
    return _replenish_or_exhaust(ops, ap, user_id, error_code=str(discovery.get("error_code") or "candidate_shortfall"))


def _settle_spend(ops: Any, ap: dict[str, Any]) -> None:
    """Accumulate a settled canary batch cost exactly once per batch."""

    batch_id = ap.get("last_canary_batch_id")
    if not batch_id:
        return
    try:
        batch = ops.get_canary_batch(str(batch_id))
    except ActorOpsError:
        return
    if str(batch.get("status") or "") not in _TERMINAL_BATCH_STATUSES:
        return
    try:
        spent = float(batch.get("actual_cost_usd") or 0.0)
    except (TypeError, ValueError):
        spent = 0.0
    # The ledger is advanced by the next step; guard against a duplicate
    # accumulation only by the batch's terminal state having been consumed.
    current = _load_auto_pool_run(ops, str(ap["run_id"]))
    if current is None or str(current.get("last_canary_batch_id") or "") != str(batch_id):
        return
    _update_auto_pool_run(
        ops,
        str(ap["run_id"]),
        total_spent_usd=round(float(ap["total_spent_usd"] or 0.0) + spent, 6),
    )


def _begin_discovery(ops: Any, ap: dict[str, Any], user_id: str) -> dict[str, Any]:
    route = ops.get_route(str(ap["route_id"]))
    discovery = ops.create_discovery_run(
        str(ap["route_id"]),
        trigger_reason=(
            AUTO_POOL_TRIGGER_REASON
            if not ap.get("last_discovery_run_id")
            else AUTO_POOL_REPLENISH_REASON
        ),
        expected_generation=int(route["generation"]),
    )
    _update_auto_pool_run(
        ops,
        str(ap["run_id"]),
        last_discovery_run_id=str(discovery["run_id"]),
        last_canary_batch_id=None,
    )
    _enqueue_discovery(ops, str(discovery["run_id"]), user_id)
    return _load_auto_pool_run(ops, str(ap["run_id"])) or ap


def _begin_canary(
    ops: Any,
    ap: dict[str, Any],
    user_id: str,
    discovery: dict[str, Any],
) -> dict[str, Any]:
    from .apify_actor_canary import next_reference_fingerprint

    target_slot_count = _route_slot_count(ops, str(ap["route_id"]))
    if ap["goal"] == "add_slot":
        target_slot_count = target_slot_count + 1
    plan = ops.get_canary_plan(
        str(discovery["run_id"]),
        goal=ap["goal"],
        max_candidates=3,
        target_slot_count=target_slot_count,
        target_slot=ap["slot_name"],
    )
    if not bool(plan.get("ready")):
        return _replenish_or_exhaust(ops, ap, user_id, error_code="candidate_shortfall")

    budget_cap = float(ap["budget_cap_usd"] or 0.0)
    total_spent = float(ap["total_spent_usd"] or 0.0)
    charge = float(plan.get("max_total_charge_usd") or 0.0)
    if total_spent + charge > budget_cap + 1e-9:
        _update_auto_pool_run(
            ops, str(ap["run_id"]), status="budget_exhausted",
            error_code="apify_actor_auto_pool_budget_exhausted",
        )
        return _load_auto_pool_run(ops, str(ap["run_id"])) or ap

    reference_fingerprints = (
        dict(plan["_reference_fingerprints"])
        if plan.get("_reference_fingerprints")
        else {
            str(item["revision_id"]): next_reference_fingerprint(
                ops.store,
                workspace_id=ops.workspace_id,
                platform=str(plan.get("platform") or ""),
                route_id=str(plan.get("route_id") or ""),
                revision_id=str(item["revision_id"]),
            )
            for item in plan.get("items", [])
            if item.get("revision_id")
        }
    )
    batch = ops.create_canary_batch(
        str(discovery["run_id"]),
        expected_generation=int(plan["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        approval_id=str(uuid.uuid4()),
        confirmation=BATCH_CANARY_CONFIRMATION,
        max_candidates=int(plan["max_candidates"]),
        max_total_charge_usd=charge,
        created_by_user_id=user_id,
        reference_fingerprints=reference_fingerprints,
        goal=ap["goal"],
        target_slot_count=target_slot_count,
        target_slot=ap["slot_name"],
    )
    _update_auto_pool_run(
        ops, str(ap["run_id"]), last_canary_batch_id=str(batch["batch_id"])
    )
    _enqueue_canary_batch(ops, str(batch["batch_id"]), user_id)
    return _load_auto_pool_run(ops, str(ap["run_id"])) or ap


def _activate(ops: Any, ap: dict[str, Any], user_id: str) -> dict[str, Any]:
    batch_id = ap.get("last_canary_batch_id")
    stage_id = None
    if batch_id:
        try:
            batch = ops.get_canary_batch(str(batch_id))
            stage_id = batch.get("pool_stage_id")
        except ActorOpsError:
            stage_id = None
    route = ops.get_route(str(ap["route_id"]))
    generation = int(route["generation"])
    if stage_id:
        stage = ops.get_pool_stage(str(stage_id))
        if str(stage.get("status") or "") == "apply_ready":
            ops.apply_pool_stage(
                str(stage_id),
                expected_generation=generation,
                expected_plan_hash=str(stage["plan_hash"]),
                apply_id=str(uuid.uuid4()),
                confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
            )
        else:
            # The stage is not yet apply-ready; treat as still in flight.
            return ap
    else:
        ops.activate_recommended_pool(
            str(ap["route_id"]),
            expected_generation=generation,
            confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
        )
    _update_auto_pool_run(ops, str(ap["run_id"]), status="succeeded", error_code=None)
    return _load_auto_pool_run(ops, str(ap["run_id"])) or ap


def _replenish_or_exhaust(
    ops: Any,
    ap: dict[str, Any],
    user_id: str,
    *,
    error_code: str,
) -> dict[str, Any]:
    budget_cap = float(ap["budget_cap_usd"] or 0.0)
    total_spent = float(ap["total_spent_usd"] or 0.0)
    if total_spent >= budget_cap - 1e-9:
        _update_auto_pool_run(
            ops, str(ap["run_id"]), status="budget_exhausted",
            error_code="apify_actor_auto_pool_budget_exhausted",
        )
        return _load_auto_pool_run(ops, str(ap["run_id"])) or ap
    # A free discovery costs nothing, so keep cycling until spend runs out or
    # an Actor passes paid Canary.
    _update_auto_pool_run(ops, str(ap["run_id"]), error_code=error_code)
    return _begin_discovery(ops, ap, user_id)


def find_auto_pool_by_discovery(ops: Any, discovery_run_id: str) -> dict[str, Any] | None:
    row = ops.store.connect().execute(
        """SELECT run_id FROM apify_actor_auto_pool_runs
           WHERE workspace_id = ? AND last_discovery_run_id = ? AND status = 'running'
           LIMIT 1""",
        (ops.workspace_id, str(discovery_run_id)),
    ).fetchone()
    return _load_auto_pool_run(ops, str(row["run_id"])) if row is not None else None


def find_auto_pool_by_canary(ops: Any, batch_id: str) -> dict[str, Any] | None:
    row = ops.store.connect().execute(
        """SELECT run_id FROM apify_actor_auto_pool_runs
           WHERE workspace_id = ? AND last_canary_batch_id = ? AND status = 'running'
           LIMIT 1""",
        (ops.workspace_id, str(batch_id)),
    ).fetchone()
    return _load_auto_pool_run(ops, str(row["run_id"])) if row is not None else None


def advance_after_discovery(
    ops: Any,
    discovery_run_id: str,
    *,
    admin_user_id: str | None = None,
) -> dict[str, Any] | None:
    ap = find_auto_pool_by_discovery(ops, discovery_run_id)
    if ap is None:
        return None
    return advance_auto_pool(ops, str(ap["run_id"]), admin_user_id=admin_user_id)


def advance_after_canary(
    ops: Any,
    batch_id: str,
    *,
    admin_user_id: str | None = None,
) -> dict[str, Any] | None:
    ap = find_auto_pool_by_canary(ops, batch_id)
    if ap is None:
        return None
    return advance_auto_pool(ops, str(ap["run_id"]), admin_user_id=admin_user_id)


__all__ = [
    "AUTO_POOL_BUDGET_CAP_USD",
    "advance_after_canary",
    "advance_after_discovery",
    "advance_auto_pool",
    "find_auto_pool_by_canary",
    "find_auto_pool_by_discovery",
    "get_auto_pool_run",
    "list_running_auto_pool_runs",
    "start_auto_pool",
]
