"""Read-only recovery for known Apify Runs after an unknown start."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

import httpx

from ..scrapers.apify_client import ApifyClient
from .apify_key_pool import APIFY_RUN_TERMINAL_STATUSES


_UNKNOWN_START_REASONS = frozenset({
    "start_outcome_unknown",
    "apify_start_outcome_unknown",
    "apify_start_http_outcome_unknown",
    "apify_restart_start_outcome_unknown",
})
_MAX_REGISTERED_RUNS_PER_PASS = 20


async def reconcile_blocked_unknown_start_pool(
    coordinator: Any,
    *,
    http_transport: httpx.AsyncBaseTransport | None,
) -> dict[str, Any]:
    """Resolve only evidence-backed unknown starts; never create a new Run."""

    workspace_id = coordinator.workspace_id
    state = coordinator.public_state(workspace_id)
    if (
        state["status"] != "blocked"
        or str(state.get("blocked_reason") or "") not in _UNKNOWN_START_REASONS
    ):
        return state
    timeout = httpx.Timeout(15.0, connect=5.0)
    async with httpx.AsyncClient(
        timeout=timeout, transport=http_transport, trust_env=False,
    ) as http_client:
        client = ApifyClient(
            coordinator=coordinator,
            http_client=http_client,
            retry_base_delay=1.0,
        )
        for run in _unregistered_unknown_runs(coordinator, workspace_id):
            if not await _prove_unregistered_start_absent(client, coordinator, run):
                return coordinator.public_state(workspace_id)
        state = coordinator.public_state(workspace_id)
        if state["status"] == "blocked":
            for run in _registered_nonterminal_runs(coordinator, workspace_id):
                try:
                    lease = coordinator.lease_for_run(str(run["id"]))
                    status = await client.refresh_registered_run_status(
                        lease, str(run["remote_run_id"]),
                    )
                except Exception:
                    return coordinator.public_state(workspace_id)
                if status.casefold().replace("-", "_") not in APIFY_RUN_TERMINAL_STATUSES:
                    return coordinator.public_state(workspace_id)
    return coordinator.public_state(workspace_id)


def _unregistered_unknown_runs(coordinator: Any, workspace_id: str) -> list[dict[str, Any]]:
    return [
        run for run in coordinator.list_nonterminal_runs(workspace_id)
        if str(run.get("status") or "") == "start_outcome_unknown"
        and not run.get("remote_run_id")
    ]


def _registered_nonterminal_runs(coordinator: Any, workspace_id: str) -> list[dict[str, Any]]:
    return [
        run for run in coordinator.list_nonterminal_runs(workspace_id)
        if run.get("remote_run_id")
    ][:_MAX_REGISTERED_RUNS_PER_PASS]


async def _prove_unregistered_start_absent(
    client: ApifyClient, coordinator: Any, run: dict[str, Any],
) -> bool:
    try:
        created_at = _as_utc(str(run["created_at"]))
        unknown_at = _as_utc(str(run["updated_at"]))
        if datetime.now(timezone.utc) < unknown_at + timedelta(seconds=30):
            return False
        lease = coordinator.lease_for_run(str(run["id"]))
        proved_empty = await client.prove_no_user_run_in_window(
            lease,
            started_after=_apify_utc_query_datetime(created_at - timedelta(seconds=5)),
            started_before=_apify_utc_query_datetime(unknown_at + timedelta(seconds=30)),
        )
        if proved_empty:
            coordinator.confirm_start_not_created(lease)
        return proved_empty
    except Exception:
        return False


def _as_utc(value: str) -> datetime:
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


def _apify_utc_query_datetime(value: datetime) -> str:
    return value.astimezone(timezone.utc).isoformat(timespec="milliseconds").replace("+00:00", "Z")


__all__ = ["reconcile_blocked_unknown_start_pool"]
