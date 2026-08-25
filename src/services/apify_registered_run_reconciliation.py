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


async def reconcile_dedicated_validation_unknown_starts(
    coordinator: Any,
    *,
    http_transport: httpx.AsyncBaseTransport | None,
) -> dict[str, Any]:
    """Safely settle dedicated validation unknown starts without blocking intake."""

    workspace_id = coordinator.workspace_id
    runs = _unregistered_unknown_runs(
        coordinator,
        workspace_id,
        role="validation",
    )
    if not runs:
        return coordinator.public_state(workspace_id)
    timeout = httpx.Timeout(15.0, connect=5.0)
    async with httpx.AsyncClient(
        timeout=timeout, transport=http_transport, trust_env=False,
    ) as http_client:
        client = ApifyClient(
            coordinator=coordinator,
            http_client=http_client,
            retry_base_delay=1.0,
        )
        for run in runs:
            # A non-empty or unavailable account window stays auditable but is
            # deliberately independent of production acquisition failover.
            await _prove_unregistered_start_absent(client, coordinator, run)
    return coordinator.public_state(workspace_id)


def _unregistered_unknown_runs(
    coordinator: Any,
    workspace_id: str,
    *,
    role: str = "acquisition",
) -> list[dict[str, Any]]:
    return [
        run for run in _nonterminal_runs_for_role(coordinator, workspace_id, role)
        if str(run.get("status") or "") == "start_outcome_unknown"
        and not run.get("remote_run_id")
    ]


def _registered_nonterminal_runs(
    coordinator: Any,
    workspace_id: str,
) -> list[dict[str, Any]]:
    return [
        run for run in _nonterminal_runs_for_role(
            coordinator,
            workspace_id,
            "acquisition",
        )
        if run.get("remote_run_id")
    ][:_MAX_REGISTERED_RUNS_PER_PASS]


def _nonterminal_runs_for_role(
    coordinator: Any,
    workspace_id: str,
    role: str,
) -> list[dict[str, Any]]:
    rows = coordinator.store.connect().execute(
        """
        SELECT run.*, secret.env_name
        FROM apify_actor_runs AS run
        JOIN apify_key_pool_members AS member
          ON member.workspace_id = run.workspace_id
         AND member.secret_id = run.secret_id
        LEFT JOIN secret_refs AS secret ON secret.id = run.secret_id
        WHERE run.workspace_id = ?
          AND member.role = ?
          AND run.status IN (
              'reserved', 'starting', 'running', 'aborting',
              'start_outcome_unknown'
          )
        ORDER BY run.pool_generation, run.created_at, run.id
        """,
        (workspace_id, role),
    ).fetchall()
    return [dict(row) for row in rows]


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


__all__ = [
    "reconcile_blocked_unknown_start_pool",
    "reconcile_dedicated_validation_unknown_starts",
]
