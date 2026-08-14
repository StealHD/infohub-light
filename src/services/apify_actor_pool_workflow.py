"""Public workflow projection for a persisted Actor pool stage.

Keeping the per-stage UI state here prevents a slot replan from being
mislabelled as a legacy-upgrade flow, while the service remains the sole
authority for candidate eligibility and stage transitions.
"""

from __future__ import annotations

from collections.abc import Callable, Mapping
from typing import Any


_SLOT_GOALS = frozenset({"add_slot", "replace_slot"})
_SLOT_NAMES = frozenset({"primary", "backup_1", "backup_2"})
_WORKFLOW_PREFIXES = {
    "initial_pool": "setup",
    "complete_third": "backup_2",
    "upgrade_legacy": "legacy",
    "compatibility_single": "compatibility",
    "add_slot": "add_slot",
    "replace_slot": "replace_slot",
}


def project_active_pool_stage_workflow(
    service: Any,
    stage: Mapping[str, Any],
    *,
    candidate_selection_progress: Callable[
        [str, str | None], tuple[dict[str, int], list[str]]
    ],
) -> dict[str, Any]:
    """Return the safe guided action for one non-terminal pool stage."""

    goal = str(stage["goal"])
    prefix = _WORKFLOW_PREFIXES.get(goal, "setup")
    operation_slot = str(stage.get("operation_slot") or "")
    target_slot = operation_slot if goal in _SLOT_GOALS and operation_slot in _SLOT_NAMES else None
    status = str(stage["status"])
    progress = dict(stage["source_summary"])
    blockers = [str(stage["last_error_code"])] if stage.get("last_error_code") else []
    if status in {"queued", "validating_route", "validating_sources"}:
        kind = f"{prefix}_canary_running"
    elif status == "apply_ready":
        kind = f"{prefix}_activation_approval_required"
    elif status == "blocked_unknown_start":
        kind = "blocked_unknown_start"
    elif status == "replan_required":
        plan_progress, plan_blockers = candidate_selection_progress(goal, target_slot)
        if goal == "upgrade_legacy" and "candidate_shortfall" in plan_blockers:
            compatibility_progress, compatibility_blockers = candidate_selection_progress(
                "compatibility_single", None
            )
            if not compatibility_blockers:
                failure = service._pool_stage_last_failure(str(stage["stage_id"]))
                return {
                    "kind": "compatibility_candidate_selection_available",
                    "goal": "compatibility_single",
                    "stage_id": str(stage["stage_id"]),
                    "run_id": str(stage["discovery_run_id"]),
                    "plan_hash": str(stage["plan_hash"]),
                    "progress": {
                        **compatibility_progress,
                        "strict_blockers": plan_blockers,
                        **({"last_failure": failure} if failure is not None else {}),
                    },
                    "blockers": [],
                }
        kind = (
            f"{prefix}_discovery_required"
            if "candidate_shortfall" in plan_blockers
            else f"{prefix}_candidate_selection_required"
        )
        failure = service._pool_stage_last_failure(str(stage["stage_id"]))
        progress = {
            **plan_progress,
            **({"last_failure": failure} if failure is not None else {}),
        }
        blockers = plan_blockers
    else:
        kind = f"{prefix}_canary_approval_required"
    return {
        "kind": kind,
        "goal": goal,
        "stage_id": str(stage["stage_id"]),
        "run_id": str(stage["discovery_run_id"]),
        "plan_hash": str(stage["plan_hash"]),
        "progress": progress,
        "blockers": blockers,
        **({"operation_slot": target_slot} if target_slot is not None else {}),
    }
