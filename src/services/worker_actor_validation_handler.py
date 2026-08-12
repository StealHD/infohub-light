"""Worker handlers for administrator-approved Actor validation work."""

from __future__ import annotations

import asyncio
from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

import httpx

from ..storage.service_store import ServiceStore
from .worker_handlers import (
    PaidCanaryAuthorizationError,
    PaidCanaryUnavailableError,
)


@dataclass(frozen=True, slots=True)
class WorkerActorValidationPorts:
    apify_coordinator: Callable[..., Any]
    exception_code: Callable[[Exception], str]
    safe_machine_code: Callable[[Any, str], str]


def actor_validation_id(job: dict[str, Any]) -> str | None:
    if str(job.get("job_type") or "") != "apify_actor_validation":
        return None
    payload = job.get("payload_json")
    if not isinstance(payload, dict) or set(payload) != {"validation_id"}:
        return None
    validation_id = str(payload.get("validation_id") or "").strip()
    return validation_id or None


def actor_freshness_check_id(job: dict[str, Any]) -> str | None:
    if str(job.get("job_type") or "") != "apify_actor_freshness_check":
        return None
    payload = job.get("payload_json")
    if not isinstance(payload, dict) or set(payload) != {"check_id"}:
        return None
    check_id = str(payload.get("check_id") or "").strip()
    return check_id or None


def run_actor_validation(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ports: WorkerActorValidationPorts,
) -> dict[str, Any]:
    from ..scrapers.apify_client import ApifyClient
    from .apify_actor_canary import (
        ApifyActorCanaryRunner,
        actor_canary_timeout_seconds,
    )
    from .apify_actor_ops import ApifyActorOpsService

    validation_id = actor_validation_id(job)
    if (
        not validation_id
        or int(job.get("max_attempts") or 0) != 1
        or int(job.get("priority") or 0) != 100
    ):
        raise PaidCanaryAuthorizationError(
            "Actor validation job authorization metadata is invalid"
        )
    actor = store.get_user(str(job["user_id"]))
    if (
        actor is None
        or not bool(actor.get("enabled"))
        or actor.get("role") not in {"owner", "admin"}
    ):
        raise PaidCanaryAuthorizationError(
            "Actor validation requires an active administrator"
        )
    coordinator = ports.apify_coordinator(
        store,
        workspace_id=str(job["workspace_id"]),
        data_dir=data_dir,
        purpose="validation",
    )
    if coordinator is None:
        raise PaidCanaryUnavailableError(
            "Actor validation requires the enabled Apify Key pool"
        )
    pool_state = coordinator.public_state(str(job["workspace_id"]))
    validation_secret_id = str(
        pool_state.get("validation_secret_id")
        or pool_state.get("active_secret_id")
        or ""
    )
    if not validation_secret_id:
        raise PaidCanaryUnavailableError(
            "Actor validation requires an active Apify credential"
        )
    credential = coordinator.quota_candidate(validation_secret_id)

    async def execute() -> dict[str, Any]:
        timeout = httpx.Timeout(30.0, connect=10.0)
        async with httpx.AsyncClient(timeout=timeout, trust_env=False) as client:
            apify_client = ApifyClient(
                tokens=[(credential.env_name, credential.token)],
                coordinator=coordinator,
                http_client=client,
                timeout_seconds=actor_canary_timeout_seconds(),
            )
            result = await ApifyActorCanaryRunner(
                store,
                ApifyActorOpsService(
                    store,
                    workspace_id=str(job["workspace_id"]),
                ),
                apify_client,
            ).run(validation_id, job_id=str(job["id"]))
            return {
                "ok": True,
                "job_type": "apify_actor_validation",
                **result.public_dict(),
            }

    return asyncio.run(execute())


def _freshness_context(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ports: WorkerActorValidationPorts,
) -> tuple[str, Any, Any]:
    from .apify_actor_resilience import ApifyActorResilienceService

    check_id = actor_freshness_check_id(job)
    resilience = ApifyActorResilienceService(
        store,
        workspace_id=str(job["workspace_id"]),
    )
    if (
        not check_id
        or int(job.get("max_attempts") or 0) != 1
        or int(job.get("priority") or 0) != 100
    ):
        if check_id:
            resilience.fail_freshness_check(
                check_id,
                reason_code="freshness_job_authorization_invalid",
            )
        raise PaidCanaryAuthorizationError(
            "Actor freshness Job authorization metadata is invalid"
        )
    actor = store.get_user(str(job["user_id"]))
    if (
        actor is None
        or not bool(actor.get("enabled"))
        or actor.get("role") not in {"owner", "admin"}
    ):
        resilience.fail_freshness_check(
            check_id,
            reason_code="freshness_actor_unauthorized",
        )
        raise PaidCanaryAuthorizationError(
            "Actor freshness check requires an active administrator"
        )
    coordinator = ports.apify_coordinator(
        store,
        workspace_id=str(job["workspace_id"]),
        data_dir=data_dir,
        purpose="validation",
        require_validation_key=True,
    )
    if coordinator is None:
        resilience.fail_freshness_check(
            check_id,
            reason_code="validation_key_unavailable",
        )
        raise PaidCanaryUnavailableError(
            "Actor freshness check requires the dedicated validation Key"
        )
    pool_state = coordinator.public_state(str(job["workspace_id"]))
    validation_secret_id = str(pool_state.get("validation_secret_id") or "")
    if not validation_secret_id:
        resilience.fail_freshness_check(
            check_id,
            reason_code="validation_key_unavailable",
        )
        raise PaidCanaryUnavailableError(
            "Actor freshness check requires the dedicated validation Key"
        )
    try:
        credential = coordinator.quota_candidate(validation_secret_id)
    except Exception:
        resilience.fail_freshness_check(
            check_id,
            reason_code="validation_key_unavailable",
        )
        raise
    return check_id, coordinator, credential


def run_actor_freshness_check(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    ports: WorkerActorValidationPorts,
) -> dict[str, Any]:
    """Execute one manual or standing-authorized freshness round."""

    from ..scrapers.apify_client import ApifyClient
    from .apify_actor_canary import actor_canary_timeout_seconds
    from .apify_actor_freshness import ApifyActorFreshnessRunner
    from .apify_actor_ops import ApifyActorOpsService

    check_id, coordinator, credential = _freshness_context(
        job,
        data_dir=data_dir,
        store=store,
        ports=ports,
    )

    async def execute() -> dict[str, Any]:
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
            runner = ApifyActorFreshnessRunner(
                store,
                ApifyActorOpsService(
                    store,
                    workspace_id=str(job["workspace_id"]),
                ),
                client,
            )
            try:
                result = await runner.run(check_id, job_id=str(job["id"]))
            except Exception as exc:
                runner.resilience.fail_freshness_check(
                    check_id,
                    reason_code=ports.safe_machine_code(
                        ports.exception_code(exc),
                        "freshness_job_failed",
                    ).casefold(),
                )
                raise
            return {
                "ok": str(result["status"]) in {"succeeded", "partial"},
                "job_type": "apify_actor_freshness_check",
                "check_id": check_id,
                "status": str(result["status"]),
                "actual_cost_usd": result.get("actual_cost_usd"),
                "cost_final": bool(result.get("cost_final")),
            }

    return asyncio.run(execute())
