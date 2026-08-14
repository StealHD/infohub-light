"""Narrow unknown-start reconciliation primitives for the Apify boundaries."""

from __future__ import annotations

from collections.abc import Awaitable, Callable
from typing import Any


RequestJson = Callable[..., Awaitable[dict[str, Any]]]


async def prove_no_user_run_in_window(
    request_json: RequestJson,
    lease: Any,
    *,
    started_after: str,
    started_before: str,
) -> bool:
    """Accept recovery only when the authenticated account proves no Run."""

    payload = await request_json(
        lease,
        "GET",
        "/actor-runs",
        params={
            "startedAfter": str(started_after),
            "startedBefore": str(started_before),
            "limit": "1000",
            "offset": "0",
        },
        timeout=15.0,
        classify_credential=False,
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    items = data.get("items") if isinstance(data, dict) else None
    total = data.get("total") if isinstance(data, dict) else None
    if (
        isinstance(total, bool)
        or not isinstance(total, int)
        or total < 0
        or not isinstance(items, list)
    ):
        raise ValueError("Apify user Run list was not authoritative")
    return total == 0 and not items


async def known_zero_cost_aborted_run(
    request_json: RequestJson,
    lease: Any,
    *,
    remote_run_path: str,
) -> bool:
    """Verify the exact Run returned by POST ended aborted with no charge."""

    payload = await request_json(
        lease,
        "GET",
        remote_run_path,
        timeout=10.0,
        classify_credential=False,
    )
    data = payload.get("data") if isinstance(payload, dict) else None
    if not isinstance(data, dict):
        return False
    charge = data.get("usageTotalUsd")
    return (
        str(data.get("status") or "").upper() == "ABORTED"
        and not isinstance(charge, bool)
        and isinstance(charge, (int, float))
        and float(charge) == 0.0
    )


__all__ = ["known_zero_cost_aborted_run", "prove_no_user_run_in_window"]
