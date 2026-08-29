"""Safe progress summaries for the ActorOps operator workflow."""

from __future__ import annotations

from typing import Any, Sequence

from .compatibility_projection import replacement_phase


_ACTIVE_DISCOVERY = frozenset({"queued", "running", "retry_wait"})
_OPEN_REPLACEMENT = frozenset({"previewed", "authorized", "running", "ready"})
_TERMINAL_ATTEMPT = frozenset({"succeeded", "failed", "cancelled"})


def replacement_workflow_additions(
    repository: Any, plan_id: str, *, binding_count: int, status: str,
) -> dict[str, object]:
    """Project bounded progress and settled cost without source identities."""

    row = repository.connection.execute(
        """SELECT * FROM actor_replacement_plans_v2
           WHERE workspace_id=? AND plan_id=?""",
        (repository.workspace_id, plan_id),
    ).fetchone()
    attempts = repository.connection.execute(
        """SELECT source_id,status,semantic_outcome,cost_final,actual_cost_usd
           FROM actor_attempts_v2
           WHERE workspace_id=? AND attempt_group_id=? AND kind='probe'
           ORDER BY created_at,attempt_id""",
        (repository.workspace_id, plan_id),
    ).fetchall()
    verified = {
        str(attempt["source_id"])
        for attempt in attempts
        if attempt["source_id"] is not None
        and str(attempt["status"]) == "succeeded"
        and str(attempt["semantic_outcome"] or "") == "valid_nonempty"
        and bool(attempt["cost_final"])
    }
    finalized = [attempt for attempt in attempts if bool(attempt["cost_final"])]
    completed = [
        attempt for attempt in finalized
        if str(attempt["status"]) in _TERMINAL_ATTEMPT
    ]
    pending = [attempt for attempt in attempts if not bool(attempt["cost_final"])]
    if status in {"ready", "applied"}:
        verified_count = binding_count
    else:
        verified_count = min(len(verified), binding_count)
    finalized_usd = sum(
        float(attempt["actual_cost_usd"] or 0.0) for attempt in finalized
    )
    return {
        "phase": replacement_phase(repository, row) if row is not None else None,
        "progress": {
            "verified_bindings": verified_count,
            "required_bindings": binding_count,
            "completed_attempts": len(completed),
            "attempt_count": len(attempts),
            "pending_attempts": len(pending),
        },
        "cost_summary": {
            "finalized_usd": round(finalized_usd, 6),
            "pending": bool(pending),
        },
    }


def route_workflow_summary(
    discoveries: Sequence[dict[str, object]],
    replacements: Sequence[dict[str, object]],
) -> dict[str, object | None]:
    """Prefer work requiring attention, then retain the latest safe result."""

    discovery = next(
        (item for item in discoveries if str(item.get("status")) in _ACTIVE_DISCOVERY),
        discoveries[0] if discoveries else None,
    )
    replacement = next(
        (item for item in replacements if str(item.get("status")) in _OPEN_REPLACEMENT),
        replacements[0] if replacements else None,
    )
    return {"discovery": discovery, "replacement": replacement}


__all__ = ["replacement_workflow_additions", "route_workflow_summary"]
