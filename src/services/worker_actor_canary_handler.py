"""Worker handler for administrator-approved, strictly serial Canary batches."""

from __future__ import annotations

import asyncio
import os
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ..storage.service_store import ServiceStore
from .job_queue import JobQueue
from .worker_handlers import (
    PaidCanaryAuthorizationError,
    PaidCanaryUnavailableError,
)


@dataclass(frozen=True, slots=True)
class WorkerActorCanaryPorts:
    apify_coordinator: Callable[..., Any]


@dataclass(frozen=True, slots=True)
class _CanaryContext:
    job: dict[str, Any]
    store: ServiceStore
    ops: Any
    runner: Any
    client: Any
    batch_id: str
    current: dict[str, Any]
    goal: str
    stage_id: str | None


def actor_canary_batch_id(job: dict[str, Any]) -> str | None:
    if str(job.get("job_type") or "") != "apify_actor_canary_batch":
        return None
    payload = job.get("payload_json")
    if not isinstance(payload, dict) or set(payload) != {"batch_id"}:
        return None
    batch_id = str(payload.get("batch_id") or "").strip()
    return batch_id or None


def _authorized_batch(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ports: WorkerActorCanaryPorts,
) -> tuple[str, Any, Any]:
    from .apify_actor_ops import ApifyActorOpsService

    batch_id = actor_canary_batch_id(job)
    if (
        not batch_id
        or int(job.get("max_attempts") or 0) != 1
        or int(job.get("priority") or 0) != 100
    ):
        raise PaidCanaryAuthorizationError(
            "Actor Canary batch authorization metadata is invalid"
        )
    actor = store.get_user(str(job["user_id"]))
    if (
        actor is None
        or not bool(actor.get("enabled"))
        or actor.get("role") not in {"owner", "admin"}
    ):
        raise PaidCanaryAuthorizationError(
            "Actor Canary batch requires an active administrator"
        )
    coordinator = ports.apify_coordinator(
        store,
        workspace_id=str(job["workspace_id"]),
        data_dir=data_dir,
        purpose="validation",
    )
    if coordinator is None:
        raise PaidCanaryUnavailableError(
            "Actor Canary batch requires the enabled Apify Key pool"
        )
    pool_state = coordinator.public_state(str(job["workspace_id"]))
    validation_secret_id = str(
        pool_state.get("validation_secret_id")
        or pool_state.get("active_secret_id")
        or ""
    )
    if not validation_secret_id:
        raise PaidCanaryUnavailableError(
            "Actor Canary batch requires an active Apify credential"
        )
    return (
        batch_id,
        coordinator,
        coordinator.quota_candidate(validation_secret_id),
    )


def _cancel_remaining(
    context: _CanaryContext,
    items: list[dict[str, Any]],
    *,
    reason: str,
) -> None:
    for item in items:
        validation = context.ops.get_validation(str(item["validation_id"]))
        if str(validation["status"]) in {"queued", "running"}:
            if str(validation["status"]) == "queued":
                context.ops.record_validation(
                    str(item["validation_id"]),
                    status="cancelled",
                    semantic_outcome=reason,
                    cost_usd=0.0,
                    cost_final=True,
                    counts_toward_canary=False,
                )
            else:
                continue
        context.ops.update_canary_batch_item(
            context.batch_id,
            int(item["ordinal"]),
            status="not_needed_no_charge",
            semantic_outcome=reason,
            actual_cost_usd=0.0,
            cost_final=True,
        )


def _start_batch(
    *,
    job: dict[str, Any],
    store: ServiceStore,
    ops: Any,
    runner: Any,
    client: Any,
    batch_id: str,
) -> _CanaryContext:
    current = ops.get_canary_batch(batch_id)
    if str(current["status"]) != "queued":
        raise PaidCanaryAuthorizationError("Actor Canary batch is not queued")
    ops.set_canary_batch_status(
        batch_id,
        expected_statuses=("queued",),
        status="preflighting",
    )
    goal = str(current.get("goal") or "initial_pool")
    stage_id = str(current["pool_stage_id"]) if current.get("pool_stage_id") else None
    if goal != "initial_pool" and stage_id is None:
        raise PaidCanaryAuthorizationError(
            "Staged Actor Canary batch is missing its pool stage"
        )
    if stage_id is not None:
        ops.set_pool_stage_status(
            stage_id,
            expected_statuses=("queued",),
            status="validating_route",
        )
    return _CanaryContext(
        job=job,
        store=store,
        ops=ops,
        runner=runner,
        client=client,
        batch_id=batch_id,
        current=current,
        goal=goal,
        stage_id=stage_id,
    )


def _route_ready_reason(context: _CanaryContext) -> str | None:
    ready = (
        context.ops.pool_stage_route_ready(context.stage_id)
        if context.stage_id is not None
        else bool(
            context.ops.recommend_active_pool(
                str(context.current["route_id"])
            ).get("ready")
        )
    )
    if not ready:
        return None
    return "staged_route_ready" if context.stage_id is not None else "two_providers_ready"


async def _preflight_item(
    context: _CanaryContext,
    item: dict[str, Any],
) -> tuple[bool, str | None]:
    from ..scrapers.apify_client import ApifyClientError

    validation_id = str(item["validation_id"])
    revision_id = str(item["revision_id"])
    try:
        if context.goal != "compatibility_single":
            await context.client.preflight_actor_revision(
                str(item["actor_id"]),
                build_id=str(item["build_id"]),
                build_number=str(item["build_number"]),
            )
    except ApifyClientError as exc:
        context.ops.record_validation(
            validation_id,
            status="failed",
            semantic_outcome=str(exc.code),
            cost_usd=0.0,
            cost_final=True,
            counts_toward_canary=False,
        )
        if str(exc.code) == "apify_actor_revision_unavailable":
            context.ops.stop_unavailable_revision(revision_id, reason=str(exc.code))
        context.ops.update_canary_batch_item(
            context.batch_id,
            int(item["ordinal"]),
            status="preflight_failed",
            semantic_outcome=str(exc.code),
            actual_cost_usd=0.0,
            cost_final=True,
        )
        stop = (
            str(exc.code)
            if str(exc.code)
            in {"apify_key_rejected", "apify_actor_revision_preflight_unavailable"}
            else None
        )
        return False, stop
    context.ops.update_canary_batch_item(
        context.batch_id,
        int(item["ordinal"]),
        status="preflight_passed",
        semantic_outcome=(
            "compatibility_preflight_deferred"
            if context.goal == "compatibility_single"
            else "preflight_available"
        ),
    )
    return True, None


def _mark_batch_running(context: _CanaryContext, item: dict[str, Any]) -> None:
    batch_state = context.ops.get_canary_batch(context.batch_id)
    if str(batch_state["status"]) == "preflighting":
        context.ops.set_canary_batch_status(
            context.batch_id,
            expected_statuses=("preflighting",),
            status="running",
        )
    context.ops.update_canary_batch_item(
        context.batch_id,
        int(item["ordinal"]),
        status="running",
    )


def _unknown_start_result(context: _CanaryContext) -> dict[str, Any]:
    return {
        "ok": False,
        "job_type": "apify_actor_canary_batch",
        "batch_id": context.batch_id,
        "status": "blocked_unknown_start",
        "error_code": "apify_start_outcome_unknown",
        "_job_status": "failed",
    }


async def _run_item(
    context: _CanaryContext,
    item: dict[str, Any],
) -> dict[str, Any] | None:
    from .apify_actor_ops import ActorOpsError

    validation_id = str(item["validation_id"])
    try:
        result = await context.runner.run(
            validation_id,
            job_id=str(context.job["id"]),
            skip_preflight=True,
        )
    except ActorOpsError as exc:
        validation = context.ops.get_validation(validation_id)
        cost = validation.get("cost_usd")
        final = bool(validation.get("cost_final"))
        unknown = str(exc.code) in {
            "apify_start_outcome_unknown",
            "apify_run_reconcile_required",
        }
        context.ops.update_canary_batch_item(
            context.batch_id,
            int(item["ordinal"]),
            status="blocked_unknown_start" if unknown else "failed",
            semantic_outcome=str(validation.get("semantic_outcome") or exc.code),
            actual_cost_usd=(float(cost) if cost is not None else None),
            cost_final=final,
        )
        return _unknown_start_result(context) if unknown else None
    validation = context.ops.get_validation(validation_id)
    context.ops.update_canary_batch_item(
        context.batch_id,
        int(item["ordinal"]),
        status="succeeded",
        semantic_outcome=result.semantic_outcome,
        actual_cost_usd=result.cost_usd,
        cost_final=bool(validation.get("cost_final")),
    )
    return None


async def _run_route_items(
    context: _CanaryContext,
) -> tuple[str | None, dict[str, Any] | None]:
    items = list(context.ops.get_canary_batch(context.batch_id)["items"])
    for index, item in enumerate(items):
        ready_reason = _route_ready_reason(context)
        if ready_reason:
            _cancel_remaining(
                context,
                [
                    remaining
                    for remaining in items[index:]
                    if str(remaining.get("status"))
                    not in {"succeeded", "not_needed_no_charge"}
                ],
                reason=ready_reason,
            )
            return ready_reason, None
        if str(item.get("status")) in {"succeeded", "not_needed_no_charge"}:
            continue
        passed, stop_reason = await _preflight_item(context, item)
        if stop_reason:
            _cancel_remaining(context, items[index + 1 :], reason=stop_reason)
            return stop_reason, None
        if not passed:
            continue
        _mark_batch_running(context, item)
        blocked = await _run_item(context, item)
        if blocked is not None:
            _cancel_remaining(
                context,
                items[index + 1 :],
                reason="apify_start_outcome_unknown",
            )
            if context.stage_id is not None:
                context.ops.block_pool_stage_unknown_start(context.stage_id)
            context.ops.set_canary_batch_status(
                context.batch_id,
                expected_statuses=("running",),
                status="blocked_unknown_start",
                stop_reason="apify_start_outcome_unknown",
            )
            return "apify_start_outcome_unknown", blocked
    return None, None


def _mark_stage_batch_running(context: _CanaryContext) -> None:
    batch_state = context.ops.get_canary_batch(context.batch_id)
    if str(batch_state["status"]) == "preflighting":
        context.ops.set_canary_batch_status(
            context.batch_id,
            expected_statuses=("preflighting",),
            status="running",
        )


def _stage_unknown_start(context: _CanaryContext) -> dict[str, Any]:
    assert context.stage_id is not None
    context.ops.block_pool_stage_unknown_start(context.stage_id)
    batch_state = context.ops.get_canary_batch(context.batch_id)
    context.ops.set_canary_batch_status(
        context.batch_id,
        expected_statuses=(str(batch_state["status"]),),
        status="blocked_unknown_start",
        stop_reason="apify_start_outcome_unknown",
    )
    return {
        **_unknown_start_result(context),
        "pool_stage_id": context.stage_id,
    }


async def _run_stage_sources(
    context: _CanaryContext,
) -> dict[str, Any] | None:
    from .apify_actor_ops import ActorOpsError

    if context.stage_id is None:
        return None
    if context.goal == "compatibility_single":
        context.ops.prepare_compatibility_stage_activation(context.stage_id)
        return None
    source_validation_ids = context.ops.prepare_pool_stage_source_validations(
        context.stage_id
    )
    if source_validation_ids:
        _mark_stage_batch_running(context)
    for validation_id in source_validation_ids:
        try:
            await context.runner.run(
                validation_id,
                job_id=str(context.job["id"]),
                skip_preflight=False,
            )
        except ActorOpsError as exc:
            unknown = str(exc.code) in {
                "apify_start_outcome_unknown",
                "apify_run_reconcile_required",
            }
            context.ops.refresh_pool_stage_sources(context.stage_id)
            if unknown:
                return _stage_unknown_start(context)
        else:
            context.ops.refresh_pool_stage_sources(context.stage_id)
    context.ops.refresh_pool_stage_sources(context.stage_id)
    return None


def _enqueue_replenishment(
    context: _CanaryContext,
    finalized: dict[str, Any],
) -> str | None:
    if not (
        context.goal == "initial_pool"
        and context.stage_id is None
        and str(finalized["status"]) == "partial"
    ):
        return None
    continuation = context.ops.get_canary_plan(str(finalized["discovery_run_id"]))
    if bool(continuation["ready"]):
        return None
    route = context.ops.get_route(str(finalized["route_id"]))
    discovery = context.ops.create_discovery_run(
        str(finalized["route_id"]),
        trigger_reason="canary_batch_replenishment",
        expected_generation=int(route["generation"]),
    )
    replenishment = JobQueue(context.store).create_job(
        workspace_id=str(context.job["workspace_id"]),
        user_id=str(context.job["user_id"]),
        job_type="apify_actor_discovery",
        payload={"run_id": str(discovery["run_id"])},
        priority=50,
        max_attempts=1,
        retention_days=int(os.getenv("HORIZON_JOB_RETENTION_DAYS", "14")),
    )
    return str(replenishment["id"])


def _final_result(
    context: _CanaryContext,
    *,
    stop_reason: str | None,
) -> dict[str, Any]:
    finalized = context.ops.finalize_canary_batch(
        context.batch_id,
        stop_reason=stop_reason,
    )
    result = {
        "ok": True,
        "job_type": "apify_actor_canary_batch",
        "batch_id": context.batch_id,
        "status": str(finalized["status"]),
        "success_count": int(finalized["success_count"]),
        "publisher_count": int(finalized["publisher_count"]),
        "actual_cost_usd": finalized.get("actual_cost_usd"),
        "cost_final": bool(finalized.get("cost_final")),
        "replenishment_job_id": _enqueue_replenishment(context, finalized),
    }
    if context.stage_id is not None:
        result["pool_stage"] = context.ops.get_pool_stage(context.stage_id)
    return result


async def _execute_batch(
    job: dict[str, Any],
    *,
    store: ServiceStore,
    batch_id: str,
    coordinator: Any,
    credential: Any,
) -> dict[str, Any]:
    from ..scrapers.apify_client import ApifyClient
    from .apify_actor_canary import (
        ApifyActorCanaryRunner,
        actor_canary_timeout_seconds,
    )
    from .apify_actor_ops import ApifyActorOpsService

    ops = ApifyActorOpsService(store, workspace_id=str(job["workspace_id"]))
    async with httpx.AsyncClient(
        timeout=httpx.Timeout(30.0, connect=10.0),
        trust_env=False,
    ) as http_client:
        client = ApifyClient(
            tokens=[(credential.env_name, credential.token)],
            coordinator=coordinator,
            http_client=http_client,
            timeout_seconds=actor_canary_timeout_seconds(),
        )
        context = _start_batch(
            job=job,
            store=store,
            ops=ops,
            runner=ApifyActorCanaryRunner(store, ops, client),
            client=client,
            batch_id=batch_id,
        )
        stop_reason, blocked = await _run_route_items(context)
        if blocked is not None:
            return blocked
        stage_blocked = await _run_stage_sources(context)
        if stage_blocked is not None:
            return stage_blocked
    return _final_result(context, stop_reason=stop_reason)


def run_actor_canary_batch(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ports: WorkerActorCanaryPorts,
) -> dict[str, Any]:
    batch_id, coordinator, credential = _authorized_batch(
        job,
        data_dir=data_dir,
        store=store,
        ports=ports,
    )
    return asyncio.run(
        _execute_batch(
            job,
            store=store,
            batch_id=batch_id,
            coordinator=coordinator,
            credential=credential,
        )
    )
