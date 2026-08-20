"""Browser-safe verified Actor catalog and zero-cost activation helpers."""

from __future__ import annotations

import math
import re
from typing import Any, Literal

from .apify_actor_pool_management import _ensure_ops_symbols


_GOALS = {
    "initial_pool", "complete_third", "upgrade_legacy", "compatibility_single",
    "add_slot", "replace_slot",
}
_SLOTS = ("primary", "backup_1", "backup_2")
_APPLY_ID_RE = re.compile(r"^[A-Za-z0-9._:-]{16,128}$")


def list_verified_pool_candidates(
    ops: Any, route_id: str, *, goal: str, target_slot: str | None = None
) -> dict[str, Any]:
    """Return only Actors with settled Route and enabled-source proof.

    The internal discovery projection deliberately retains pending and rejected
    inventory so the server can schedule controlled Canary work.  That inventory
    is not a manual-selection catalog and must never cross the browser boundary.
    """

    result = ops.list_pool_candidates(route_id, goal=goal, target_slot=target_slot)
    raw = list(result["candidates"])
    candidates = [
        {
            key: item[key]
            for key in (
                "candidate_id", "actor_public_name", "publisher", "pricing",
                "store_quality", "max_validation_charge_usd", "already_validated",
                "selectable", "unavailable_reason",
            )
            if key in item
        }
        for item in raw
        if bool(item.get("selectable")) and bool(item.get("already_validated"))
    ]
    blockers = [item for item in result["blockers"] if item != "candidate_shortfall"]
    if len(candidates) < int(result["required_selection_count"]):
        blockers.append("candidate_shortfall")
    if any(
        bool(item.get("selectable")) and not bool(item.get("already_validated"))
        for item in raw
    ):
        blockers.append("candidate_verification_pending")
    eligible_count = len(candidates)
    return {
        **result,
        "candidate_count": eligible_count,
        "eligible_candidate_count": eligible_count,
        "candidate_shortfall": max(
            0, int(result["required_selection_count"]) - eligible_count
        ),
        "candidates": candidates,
        "blockers": blockers,
    }


def _activation_slots(plan: dict[str, Any]) -> dict[str, str | None]:
    target = {
        slot: str(plan.get("base_slots", {}).get(slot) or "") or None
        for slot in _SLOTS
    }
    items = list(plan.get("items") or ())
    revision_ids = [str(item.get("revision_id") or "") for item in items]
    if not items or any(not value for value in revision_ids):
        raise ValueError("verified Actor plan has no fixed revisions")
    operation_slot = str(plan.get("operation_slot") or "")
    goal = str(plan.get("goal") or "")
    if operation_slot:
        if operation_slot not in _SLOTS or len(revision_ids) != 1:
            raise ValueError("verified Actor slot plan is incomplete")
        target[operation_slot] = revision_ids[0]
    elif goal == "complete_third":
        if len(revision_ids) != 1:
            raise ValueError("third-slot plan must contain one Actor")
        target["backup_2"] = revision_ids[0]
    elif goal == "compatibility_single":
        if len(revision_ids) != 1:
            raise ValueError("compatibility plan must contain one Actor")
        target["primary"] = revision_ids[0]
    else:
        if len(revision_ids) != int(plan["target_slot_count"]):
            raise ValueError("verified Actor count does not match the pool target")
        target = {
            slot: revision_ids[index] if index < len(revision_ids) else None
            for index, slot in enumerate(_SLOTS)
        }
    if sum(value is not None for value in target.values()) != int(plan["target_slot_count"]):
        raise ValueError("verified Actor target slots are incomplete")
    return target


def _source_proof_current(
    connection: Any, ops: Any, *, route_id: str, slots: dict[str, str | None]
) -> None:
    revisions = [value for value in slots.values() if value]
    bindings = connection.execute(
        """SELECT binding.source_id, binding.target_fingerprint
           FROM apify_source_route_bindings AS binding
           JOIN source_catalog AS source
             ON source.workspace_id = binding.workspace_id
            AND source.id = binding.source_id
           WHERE binding.workspace_id = ? AND binding.route_id = ?
             AND source.enabled = 1
           ORDER BY binding.source_id""",
        (ops.workspace_id, route_id),
    ).fetchall()
    for binding in bindings:
        for revision_id in revisions:
            proof = connection.execute(
                """SELECT 1 FROM apify_actor_validations
                   WHERE workspace_id = ? AND route_id = ? AND source_id = ?
                     AND revision_id = ? AND kind = 'source_canary'
                     AND status = 'succeeded' AND cost_final = 1
                     AND semantic_outcome IN ('valid_nonempty', 'valid_empty')
                     AND target_fingerprint = ? LIMIT 1""",
                (
                    ops.workspace_id, route_id, str(binding["source_id"]),
                    revision_id, str(binding["target_fingerprint"]),
                ),
            ).fetchone()
            if proof is None:
                symbols = _ensure_ops_symbols()
                raise symbols.ActorOpsError(
                    "apify_actor_verified_candidate_stale",
                    "A selected Actor no longer has current source proof",
                    status_code=409,
                )


def _apply_matching_ready_stage(
    connection: Any,
    ops: Any,
    *,
    route_id: str,
    goal: str,
    candidate_ids: list[str],
    expected_generation: int,
    target_slot_count: int,
    target_slot: str | None,
    apply_id: str,
    confirmation: str,
) -> dict[str, Any] | None:
    """Apply the exact settled stage, never a merely similar candidate set."""

    symbols = _ensure_ops_symbols()
    stage = connection.execute(
        """SELECT stage_id, plan_hash, goal, operation_slot, target_slot_count,
                  target_primary_revision_id, target_backup_1_revision_id,
                  target_backup_2_revision_id
           FROM apify_actor_pool_stages
           WHERE workspace_id = ? AND route_id = ? AND status = 'apply_ready'
           ORDER BY created_at DESC LIMIT 1""",
        (ops.workspace_id, route_id),
    ).fetchone()
    if stage is None:
        return None
    candidates = {
        str(row["candidate_id"])
        for row in connection.execute(
            """SELECT revision.candidate_id
               FROM apify_actor_canary_batches AS batch
               JOIN apify_actor_canary_batch_items AS item
                 ON item.workspace_id = batch.workspace_id AND item.batch_id = batch.batch_id
               JOIN apify_actor_adapter_revisions AS revision
                 ON revision.workspace_id = item.workspace_id AND revision.revision_id = item.revision_id
               WHERE batch.workspace_id = ? AND batch.pool_stage_id = ?""",
            (ops.workspace_id, str(stage["stage_id"])),
        ).fetchall()
    }
    slots = {
        "primary": str(stage["target_primary_revision_id"] or "") or None,
        "backup_1": str(stage["target_backup_1_revision_id"] or "") or None,
        "backup_2": str(stage["target_backup_2_revision_id"] or "") or None,
    }
    if (
        str(stage["goal"]) != goal
        or candidates != set(candidate_ids)
        or int(stage["target_slot_count"]) != int(target_slot_count)
        or (str(stage["operation_slot"] or "") or None) != target_slot
    ):
        raise symbols.ActorOpsError(
            "apify_actor_verified_candidate_stale",
            "The selected Actor does not match the settled staged pool",
            status_code=409,
        )
    _source_proof_current(connection, ops, route_id=route_id, slots=slots)
    return ops.apply_pool_stage(
        str(stage["stage_id"]),
        expected_generation=expected_generation,
        expected_plan_hash=str(stage["plan_hash"]),
        apply_id=apply_id,
        confirmation=confirmation,
    )


def activate_verified_pool_candidates(
    ops: Any,
    route_id: str,
    *,
    run_id: str,
    goal: Literal[
        "initial_pool", "complete_third", "upgrade_legacy", "compatibility_single",
        "add_slot", "replace_slot",
    ],
    candidate_ids: list[str],
    expected_generation: int,
    target_slot_count: int,
    apply_id: str,
    confirmation: str,
    target_slot: str | None = None,
) -> dict[str, Any]:
    """Atomically activate a catalog item after rechecking its proof.

    This deliberately does not create a Canary batch.  A browser-visible item
    already has exact Build, real Route target, every enabled source, and final
    cost proof; running it again would be both redundant and billable.
    """

    symbols = _ensure_ops_symbols()
    if confirmation != symbols.ROUTE_POOL_ACTIVATION_CONFIRMATION:
        raise symbols.ActorOpsError(
            "apify_actor_pool_activation_confirmation_required",
            "Verified Actor activation requires the exact confirmation phrase",
            status_code=422,
        )
    if not _APPLY_ID_RE.fullmatch(str(apply_id)):
        raise symbols.ActorOpsError(
            "apify_actor_pool_apply_id_invalid",
            "Verified Actor activation apply id is invalid",
            status_code=422,
        )
    if goal not in _GOALS:
        raise symbols.ActorOpsError("apify_actor_pool_stage_goal_invalid", "Actor pool workflow goal is invalid", status_code=422)
    with ops._write() as connection:
        staged = _apply_matching_ready_stage(
            connection, ops, route_id=route_id, goal=goal,
            candidate_ids=candidate_ids, expected_generation=expected_generation,
            target_slot_count=target_slot_count, target_slot=target_slot,
            apply_id=apply_id, confirmation=confirmation,
        )
        if staged is not None:
            return staged
        plan = ops.get_canary_plan(
            run_id,
            goal=goal,
            max_candidates=len(candidate_ids),
            candidate_ids=tuple(candidate_ids),
            candidate_validation_profiles=None,
            target_slot_count=target_slot_count,
            target_slot=target_slot,
        )
        if str(plan["route_id"]) != route_id:
            raise symbols.ActorOpsError(
                "apify_actor_verified_candidate_stale",
                "The selected Actor belongs to a different Route",
                status_code=409,
            )
        if int(plan["generation"]) != int(expected_generation):
            raise symbols.ActorOpsError("apify_actor_route_generation_conflict", "Actor route changed; reload before enabling the selected Actor", status_code=409)
        if (
            not bool(plan["ready"])
            or not math.isclose(float(plan["max_total_charge_usd"]), 0.0, abs_tol=1e-9)
            or int(plan.get("source_validation_count") or 0) != 0
            or not all(bool(item.get("already_validated")) for item in plan["items"])
        ):
            raise symbols.ActorOpsError(
                "apify_actor_verified_candidate_stale",
                "Selected Actor proof is incomplete or changed; refresh the verified catalog",
                status_code=409,
            )
        try:
            slots = _activation_slots(plan)
        except ValueError as exc:
            raise symbols.ActorOpsError(
                "apify_actor_verified_candidate_stale", str(exc), status_code=409
            ) from exc
        _source_proof_current(connection, ops, route_id=route_id, slots=slots)
        rows = connection.execute(
            """SELECT lifecycle FROM apify_actor_adapter_revisions
               WHERE workspace_id = ? AND revision_id IN (?, ?, ?)""",
            (ops.workspace_id, *(slots[name] or "" for name in _SLOTS)),
        ).fetchall()
        compatibility_slot = (
            str(plan["platform"]) == "x"
            and goal in {"add_slot", "replace_slot"}
            and any(str(row["lifecycle"]) == "legacy_builtin" for row in rows)
        )
        result = ops.replace_active_pool(
            route_id,
            slots=slots,
            expected_generation=expected_generation,
            allow_probationary_primary=True,
            allow_compatibility_single=(str(plan["platform"]) == "x" and goal == "compatibility_single"),
            allow_compatibility_slot=compatibility_slot,
            reactivate_verified_slots=True,
        )
        target_hash = symbols.revision_set_hash(
            {name: slots[name] or "" for name in _SLOTS}
        )
        populated = sum(value is not None for value in slots.values())
        connection.execute(
            """UPDATE apify_source_route_bindings
               SET validation_status = ?, verified_revision_set_hash = ?, updated_at = ?
               WHERE workspace_id = ? AND route_id = ?""",
            (
                f"ready_{populated}of{populated}", target_hash, ops._now_iso(),
                ops.workspace_id, route_id,
            ),
        )
    return result
