"""Worker handler for bounded Actor discovery orchestration."""

from __future__ import annotations

import asyncio
import inspect
import os
from collections.abc import Callable
from dataclasses import dataclass
from functools import partial
from typing import Any

import httpx

from ..storage.service_store import ServiceStore
from .worker_actor_discovery_ai import generate_manifest


@dataclass(frozen=True, slots=True)
class WorkerActorDiscoveryPorts:
    safe_machine_code: Callable[[Any, str], str]
    log_close_failure: Callable[[], None]


@dataclass(frozen=True, slots=True)
class _DiscoveryContext:
    ops: Any
    run_id: str
    run: dict[str, Any]
    prefer_existing: bool
    expanded_compatibility: bool
    global_ai: Any
    apify_env: str
    output_limit: int
    ai_client: Any
    route: dict[str, Any]


def actor_discovery_queries(route: dict[str, Any]) -> tuple[str, str, str]:
    """Return route-specific Store queries that target content-item Actors."""

    profile = (
        str(route.get("platform") or ""),
        str(route.get("target_type") or ""),
        str(route.get("capability") or ""),
    )
    presets = {
        ("x", "profile", "items"): (
            "x profile posts scraper",
            "twitter user tweets scraper",
            "x profile feed actor",
        ),
        ("youtube", "channel", "items"): (
            "youtube channel videos scraper",
            "youtube public channel videos",
            "youtube channel feed actor",
        ),
        ("instagram", "profile", "items"): (
            "instagram profile posts scraper",
            "instagram user posts scraper",
            "instagram profile feed actor",
        ),
    }
    selected = presets.get(profile)
    if selected is None:
        raise ValueError("Actor discovery route profile is unsupported")
    return selected


def _job_metadata(
    job: dict[str, Any],
    store: ServiceStore,
) -> tuple[str, bool]:
    payload = (
        job.get("payload_json")
        if isinstance(job.get("payload_json"), dict)
        else {}
    )
    run_id = str(payload.get("run_id") or "").strip()
    prefer_existing = payload.get("prefer_existing_legacy_actors", False)
    if (
        not run_id
        or set(payload) not in (
            {"run_id"},
            {"run_id", "prefer_existing_legacy_actors"},
        )
        or not isinstance(prefer_existing, bool)
        or int(job.get("max_attempts") or 0) != 1
    ):
        raise ValueError("Actor discovery job metadata is invalid")
    actor = store.get_user(str(job["user_id"]))
    if actor is None or not bool(actor.get("enabled")) or actor.get("role") == "viewer":
        raise PermissionError("Actor discovery requires an active member")
    return run_id, prefer_existing


def _result(
    run_id: str,
    stage: str,
    *,
    ok: bool = True,
    **extra: Any,
) -> dict[str, Any]:
    return {
        "ok": ok,
        "job_type": "apify_actor_discovery",
        "run_id": run_id,
        "stage": stage,
        "revision_count": 0,
        **extra,
    }


def _queued_replay_or_duplicate(
    job: dict[str, Any],
    *,
    ops: Any,
    run_id: str,
    run: dict[str, Any],
    prefer_existing: bool,
) -> dict[str, Any] | None:
    if str(run["stage"]) != "queued":
        return _result(
            run_id,
            str(run["stage"]),
            idempotent_replay=True,
        )
    if not prefer_existing:
        return None
    earlier_active = ops.store.connect().execute(
        """
        SELECT 1
        FROM apify_actor_discovery_runs AS earlier
        WHERE earlier.workspace_id = ?
          AND earlier.route_id = ?
          AND earlier.trigger_reason = 'manual_legacy_upgrade_refresh'
          AND earlier.stage IN (
              'queued', 'searching', 'metadata', 'ranking',
              'static_validation', 'input_validation'
          )
          AND earlier.rowid < (
              SELECT current.rowid
              FROM apify_actor_discovery_runs AS current
              WHERE current.workspace_id = ? AND current.run_id = ?
          )
        LIMIT 1
        """,
        (
            str(job["workspace_id"]),
            str(run["route_id"]),
            str(job["workspace_id"]),
            run_id,
        ),
    ).fetchone()
    if earlier_active is None:
        return None
    superseded = ops.update_discovery_run(
        run_id,
        expected_stage="queued",
        stage="failed",
        error_code="superseded_duplicate_refresh",
    )
    return _result(
        run_id,
        str(superseded["stage"]),
        superseded_duplicate=True,
    )


def _transition_from_queued(
    ops: Any,
    run_id: str,
    *,
    stage: str,
    error_code: str,
    ok: bool = True,
) -> dict[str, Any]:
    updated = ops.update_discovery_run(
        run_id,
        expected_stage="queued",
        stage=stage,
        error_code=error_code,
    )
    return _result(run_id, str(updated["stage"]), ok=ok)


def _metadata_token_env(
    store: ServiceStore,
    *,
    workspace_id: str,
) -> str:
    pool_secret = store.connect().execute(
        """
        SELECT secret.env_name
        FROM apify_key_pool_state AS state
        JOIN secret_refs AS secret ON secret.id = state.active_secret_id
        WHERE state.workspace_id = ?
        """,
        (workspace_id,),
    ).fetchone()
    return str(pool_secret["env_name"]) if pool_secret else ""


def _prepare_runtime(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ops: Any,
    run_id: str,
    run: dict[str, Any],
    prefer_existing: bool,
    expanded_compatibility: bool,
) -> _DiscoveryContext | dict[str, Any]:
    from ..ai.client import create_ai_client
    from .apify_discovery_ai import resolve_global_discovery_ai

    settings = ops.get_discovery_settings()
    if not bool(settings["enabled"]):
        return _transition_from_queued(
            ops,
            run_id,
            stage="blocked_ai_unavailable",
            error_code="discovery_ai_disabled",
        )
    global_ai = resolve_global_discovery_ai(
        store,
        data_dir=data_dir,
        workspace_id=str(job["workspace_id"]),
        secret_ref_id=(
            str(settings["secret_ref_id"])
            if settings.get("secret_ref_id")
            else None
        ),
    )
    if not global_ai.ready or global_ai.config is None:
        return _transition_from_queued(
            ops,
            run_id,
            stage="blocked_ai_unavailable",
            error_code="discovery_global_ai_unavailable",
        )
    apify_env = _metadata_token_env(store, workspace_id=str(job["workspace_id"]))
    if not apify_env or not os.getenv(apify_env):
        return _transition_from_queued(
            ops,
            run_id,
            stage="failed",
            error_code="metadata_token_unavailable",
            ok=False,
        )
    from .quota import QuotaService

    QuotaService(store).admit_ai_attempt(
        workspace_id=str(job["workspace_id"]),
        user_id=str(job["user_id"]),
        provider=global_ai.provider,
    )
    route = ops.get_route(str(run["route_id"]))
    output_limit = int(run.get("ai_max_output_tokens") or settings["max_output_tokens"])
    ai_config = global_ai.config.model_copy(
        update={"enabled": True, "temperature": 0.0, "max_tokens": output_limit}
    )
    return _DiscoveryContext(
        ops=ops,
        run_id=run_id,
        run=run,
        prefer_existing=prefer_existing,
        expanded_compatibility=expanded_compatibility,
        global_ai=global_ai,
        apify_env=apify_env,
        output_limit=output_limit,
        ai_client=create_ai_client(
            ai_config,
            single_attempt=True,
            timeout_seconds=180,
        ),
        route=route,
    )


async def _close_ai_client(
    context: _DiscoveryContext,
    ports: WorkerActorDiscoveryPorts,
) -> None:
    close = getattr(context.ai_client, "aclose", None)
    if not callable(close):
        return
    try:
        close_result = close()
        if inspect.isawaitable(close_result):
            await close_result
    except Exception:
        ports.log_close_failure()


async def _execute_discovery(
    context: _DiscoveryContext,
    ports: WorkerActorDiscoveryPorts,
) -> dict[str, Any]:
    from .apify_actor_discovery import (
        ApifyActorDiscoveryService,
        ApifyStoreRestClient,
        LEGACY_UPGRADE_DISCOVERY_CANDIDATE_LIMIT,
    )

    try:
        async with httpx.AsyncClient(
            timeout=httpx.Timeout(30.0, connect=10.0),
            trust_env=False,
        ) as http_client:
            service = ApifyActorDiscoveryService(
                context.ops,
                ApifyStoreRestClient(
                    os.environ[context.apify_env],
                    client=http_client,
                ),
                partial(generate_manifest, context),
                ai_provider=context.global_ai.provider,
                ai_model=context.global_ai.model,
            )
            outcome = await service.run_discovery(
                context.run_id,
                queries=actor_discovery_queries(context.route),
                preferred_actor_ids=(
                    context.ops.legacy_actor_ids(str(context.run["route_id"]))
                    if context.prefer_existing
                    else ()
                ),
                candidate_limit=(
                    LEGACY_UPGRADE_DISCOVERY_CANDIDATE_LIMIT
                    if context.prefer_existing or context.expanded_compatibility
                    else None
                ),
            )
            return {
                "ok": True,
                "job_type": "apify_actor_discovery",
                "run_id": outcome.run_id,
                "route_id": outcome.route_id,
                "stage": outcome.stage,
                "revision_count": len(outcome.revision_ids),
                "rejected_count": len(outcome.rejected),
            }
    finally:
        await _close_ai_client(context, ports)


def _mark_failed(
    context: _DiscoveryContext,
    exc: Exception,
    ports: WorkerActorDiscoveryPorts,
) -> None:
    current = context.ops.get_discovery_run(context.run_id)
    if str(current["stage"]) in {
        "awaiting_canary_approval",
        "candidate_shortfall",
        "blocked_ai_unavailable",
        "failed",
    }:
        return
    context.ops.update_discovery_run(
        context.run_id,
        expected_stage=str(current["stage"]),
        stage="failed",
        error_code=ports.safe_machine_code(
            getattr(exc, "code", None),
            "apify_actor_discovery_failed",
        ),
        failure_phase={
            "searching": "store",
            "metadata": "metadata",
            "ranking": "ai_generation",
            "static_validation": "static_validation",
            "input_validation": "input_validation",
        }.get(str(current["stage"])),
    )


def run_actor_discovery(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ports: WorkerActorDiscoveryPorts,
) -> dict[str, Any]:
    from .apify_actor_ops import ApifyActorOpsService

    run_id, prefer_existing = _job_metadata(job, store)
    ops = ApifyActorOpsService(store, workspace_id=str(job["workspace_id"]))
    run = ops.get_discovery_run(run_id)
    replay = _queued_replay_or_duplicate(
        job,
        ops=ops,
        run_id=run_id,
        run=run,
        prefer_existing=prefer_existing,
    )
    if replay is not None:
        return replay
    prepared = _prepare_runtime(
        job,
        data_dir=data_dir,
        store=store,
        ops=ops,
        run_id=run_id,
        run=run,
        prefer_existing=prefer_existing,
        expanded_compatibility=(
            str(run.get("trigger_reason") or "")
            == "manual_compatibility_candidate_refresh"
        ),
    )
    if isinstance(prepared, dict):
        return prepared
    try:
        return asyncio.run(_execute_discovery(prepared, ports))
    except Exception as exc:
        _mark_failed(prepared, exc, ports)
        raise
