"""Narrow recovery for a known Run whose local registration failed."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any
from urllib.parse import quote

from .apify_actor_run_reconciliation import known_zero_cost_aborted_run


CoordinatorCall = Callable[..., Awaitable[Any]]
AbortRun = Callable[[Any, str], Awaitable[None]]
RequestJson = Callable[..., Awaitable[dict[str, Any]]]


async def reconcile_failed_run_registration(
    *,
    coordinator_call: CoordinatorCall,
    abort_registered_run: AbortRun,
    abort_unregistered_run: AbortRun,
    request_json: RequestJson,
    lease: Any,
    remote_run_id: str,
    dataset_id: str | None,
) -> bool:
    """Return true only when the original POST is safely terminalized.

    A local row that already has the exact Run is sufficient to abort through
    its normal ledger path.  Without that row, the only recovery is a GET of
    the exact POST-returned ID after an abort request proves `ABORTED/$0`.
    """

    persisted_run = await coordinator_call(
        "get_run",
        lease.reservation_id,
        optional=True,
    )
    if (
        isinstance(persisted_run, dict)
        and str(persisted_run.get("remote_run_id") or "") == remote_run_id
    ):
        await abort_registered_run(lease, remote_run_id)
        return True

    try:
        await abort_unregistered_run(lease, remote_run_id)
        recovered = await known_zero_cost_aborted_run(
            request_json,
            lease,
            remote_run_path=f"/actor-runs/{quote(remote_run_id, safe='')}",
        )
        if not recovered:
            return False
        return bool(
            await coordinator_call(
                "confirm_zero_cost_aborted_start",
                lease,
                remote_run_id,
                dataset_id,
                optional=True,
            )
        )
    except Exception:
        return False


__all__ = ["reconcile_failed_run_registration"]
