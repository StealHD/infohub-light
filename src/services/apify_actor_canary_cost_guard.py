"""Fail closed when a completed paid Actor Run reports an over-cap charge."""

from __future__ import annotations

from collections.abc import Callable
from typing import Any


OVER_CAP_CHARGE_CODE = "apify_actor_charge_above_approved_cap"


async def run_actor_with_charge_guard(
    runner: Any,
    *,
    validation_id: str,
    attempt_id: str,
    snapshot: Any,
    slot: Any,
    actor_input: dict[str, Any],
    max_paid_dataset_items: int,
    dataset_item_limit: int,
    timeout_seconds: int,
    duration_seconds: Callable[[], int],
) -> Any:
    """Run one bounded Actor call and terminally reject an over-cap charge."""

    run = await runner.client.run_actor_detailed(
        slot.actor_id,
        actor_input,
        max_total_charge_usd=min(float(snapshot.per_run_cap_usd), 0.20),
        logical_run_id=attempt_id,
        build_number=slot.build_number,
        max_paid_dataset_items=max_paid_dataset_items,
        dataset_item_limit=dataset_item_limit,
        expected_pool_generation=snapshot.key_pool_generation,
        max_remote_starts=1,
        timeout_seconds=timeout_seconds,
    )
    enforce_validation_charge_cap(
        runner.ops,
        validation_id=validation_id,
        attempt_id=attempt_id,
        actual_cost_usd=run.actual_charge_usd,
        duration_seconds=duration_seconds(),
    )
    return run


def enforce_validation_charge_cap(
    ops: Any,
    *,
    validation_id: str,
    attempt_id: str,
    actual_cost_usd: float | None,
    duration_seconds: int,
) -> None:
    """Persist a terminal safety failure before output mapping can continue.

    An upstream Actor can report a finalized charge slightly above the request
    cap.  It must never leave the validation in ``running`` just because the
    normal success writer correctly refuses that unapproved amount.
    """

    if actual_cost_usd is None:
        return
    settled = ops.settle_validation_charge_above_approved_cap(
        validation_id,
        attempt_id=attempt_id,
        actual_cost_usd=float(actual_cost_usd),
        duration_seconds=int(duration_seconds),
    )
    if not settled:
        return

    from .apify_actor_ops import ActorOpsError

    raise ActorOpsError(
        OVER_CAP_CHARGE_CODE,
        "Actor reported a charge above the approved validation limit",
        status_code=422,
    )
