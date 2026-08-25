"""Worker reconciliation for role-scoped Apify Key pool state."""

from __future__ import annotations

import asyncio
from typing import Any

import httpx

from ..scrapers.apify_client import ApifyClient
from ..storage.service_store import ServiceStore
from .apify_key_pool import ApifyKeyPoolService, apify_key_pool_enabled
from .apify_pool_drain import list_acquisition_nonterminal_runs
from .apify_registered_run_reconciliation import (
    reconcile_blocked_unknown_start_pool,
    reconcile_dedicated_validation_unknown_starts,
)
from .secret_quota import ApifySecretQuotaService, SecretQuotaError
from .secret_store import SecretStore


def apify_coordinator_for_workspace(
    store: ServiceStore,
    *,
    workspace_id: str,
    data_dir: str | None = None,
    purpose: str = "acquisition",
    require_validation_key: bool = False,
) -> ApifyKeyPoolService | None:
    """Build the shared coordinator only while the Key-pool rollout is enabled."""

    if not apify_key_pool_enabled():
        return None
    return ApifyKeyPoolService(
        store,
        secret_store=SecretStore(data_dir or store.data_dir),
        workspace_id=workspace_id,
        run_purpose=purpose,
        require_validation_key=require_validation_key,
    )


async def reconcile_apify_pool(
    coordinator: ApifyKeyPoolService,
    *,
    quota_service: ApifySecretQuotaService | None = None,
    http_transport: httpx.AsyncBaseTransport | None = None,
) -> dict[str, Any]:
    """Reconcile existing Run facts without creating another Actor Run."""

    workspace_id = coordinator.workspace_id
    coordinator.block_unregistered_reservations(
        workspace_id,
        error_code="apify_restart_start_outcome_unknown",
    )
    await reconcile_dedicated_validation_unknown_starts(
        coordinator,
        http_transport=http_transport,
    )
    state = coordinator.public_state(workspace_id)
    if state["status"] == "blocked":
        state = await reconcile_blocked_unknown_start_pool(
            coordinator,
            http_transport=http_transport,
        )
        if state["status"] == "blocked":
            return state

    runs = list_acquisition_nonterminal_runs(coordinator, workspace_id)
    if any(not run.get("remote_run_id") for run in runs):
        coordinator.block_unregistered_reservations(
            workspace_id,
            error_code="apify_restart_start_outcome_unknown",
        )
        return coordinator.public_state(workspace_id)

    if state["status"] == "draining":
        timeout = httpx.Timeout(10.0, connect=3.0)
        async with httpx.AsyncClient(
            timeout=timeout,
            transport=http_transport,
            trust_env=False,
        ) as http_client:
            client = ApifyClient(
                coordinator=coordinator,
                http_client=http_client,
                poll_interval=0.1,
                timeout_seconds=30,
                drain_timeout_seconds=30,
            )
            drain_generation = int(
                state.get("drain_generation") or state["generation"]
            )
            for run in list_acquisition_nonterminal_runs(
                coordinator,
                workspace_id,
                up_to_generation=drain_generation,
            ):
                remote_run_id = str(run.get("remote_run_id") or "")
                if not remote_run_id:
                    coordinator.block_unregistered_reservations(
                        workspace_id,
                        error_code="apify_restart_start_outcome_unknown",
                    )
                    return coordinator.public_state(workspace_id)
                lease = coordinator.lease_for_run(str(run["id"]))
                await client.abort_run(lease, remote_run_id)
        state = coordinator.complete_drain_and_failover(workspace_id)

    settlement_rows = coordinator.list_terminal_runs_requiring_accounting_settlement(
        workspace_id,
        limit=20,
    )
    if settlement_rows:
        timeout = httpx.Timeout(10.0, connect=3.0)
        async with httpx.AsyncClient(
            timeout=timeout,
            transport=http_transport,
            trust_env=False,
        ) as http_client:
            client = ApifyClient(
                coordinator=coordinator,
                http_client=http_client,
                retry_base_delay=1.0,
                accounting_settle_delay_seconds=0,
            )
            for run in settlement_rows:
                try:
                    lease = coordinator.lease_for_run(str(run["id"]))
                    await client.refresh_registered_run_status(
                        lease,
                        str(run["remote_run_id"]),
                    )
                except Exception:
                    # A terminal Run cannot create duplicate spend here. Keep
                    # its prior amount and retry the bounded read next pass.
                    continue

    quota = quota_service or ApifySecretQuotaService()
    for secret_id in coordinator.quota_refresh_candidates(workspace_id):
        candidate = coordinator.quota_candidate(secret_id)
        try:
            snapshot = await quota.fetch(
                secret_id=candidate.secret_id,
                token=candidate.token,
            )
        except SecretQuotaError as exc:
            if exc.code == "apify_quota_unauthorized":
                coordinator.begin_drain(
                    candidate.secret_id,
                    target_status="invalid",
                    reason="apify_token_invalid",
                )
            continue
        coordinator.record_member_quota(
            workspace_id=workspace_id,
            secret_id=candidate.secret_id,
            remaining_included_credits_usd=float(
                snapshot["remaining_included_credits_usd"]
            ),
            checked_at=str(snapshot["checked_at"]),
            cycle_start_at=str(snapshot["cycle_start_at"]),
            cycle_end_at=str(snapshot["cycle_end_at"]),
            monthly_included_credits_usd=float(
                snapshot["monthly_included_credits_usd"]
            ),
            monthly_usage_usd=float(snapshot["monthly_usage_usd"]),
            max_monthly_usage_usd=float(snapshot["max_monthly_usage_usd"]),
            remaining_hard_limit_usd=float(snapshot["remaining_hard_limit_usd"]),
        )
    return coordinator.public_state(workspace_id)


def reconcile_apify_pool_sync(
    coordinator: ApifyKeyPoolService,
) -> dict[str, Any]:
    return asyncio.run(reconcile_apify_pool(coordinator))


async def reconcile_all_apify_pools(
    store: ServiceStore,
    *,
    data_dir: str | None = None,
) -> list[dict[str, Any]]:
    """Reconcile each workspace without blocking ordinary Worker work."""

    if not apify_key_pool_enabled():
        return []
    workspace_ids = [
        str(row["id"])
        for row in store.connect().execute(
            "SELECT id FROM workspaces ORDER BY id"
        ).fetchall()
    ]
    outcomes: list[dict[str, Any]] = []
    for workspace_id in workspace_ids:
        coordinator = apify_coordinator_for_workspace(
            store,
            workspace_id=workspace_id,
            data_dir=data_dir,
        )
        if coordinator is None:
            continue
        try:
            state = await reconcile_apify_pool(coordinator)
        except Exception as exc:
            outcomes.append(
                {
                    "workspace_id": workspace_id,
                    "ok": False,
                    "code": str(getattr(exc, "code", None) or type(exc).__name__),
                }
            )
        else:
            outcomes.append(
                {
                    "workspace_id": workspace_id,
                    "ok": True,
                    "status": str(state["status"]),
                }
            )
    return outcomes


def reconcile_all_apify_pools_sync(
    store: ServiceStore,
    *,
    data_dir: str | None = None,
) -> list[dict[str, Any]]:
    return asyncio.run(reconcile_all_apify_pools(store, data_dir=data_dir))


__all__ = [
    "apify_coordinator_for_workspace",
    "reconcile_all_apify_pools",
    "reconcile_all_apify_pools_sync",
    "reconcile_apify_pool",
    "reconcile_apify_pool_sync",
]
