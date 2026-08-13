"""Full ActorOps route-detail projection kept out of the API composition root."""

from __future__ import annotations

from datetime import datetime, timedelta, timezone
from typing import Any

from .actor_ops_projection import public_actor_ops_revision, public_actor_ops_route
from ..services.apify_actor_resilience import ApifyActorResilienceService
from ..services.apify_actor_ops import ApifyActorOpsService
from ..storage.service_store import ServiceStore


def public_actor_ops_detail(
    store: ServiceStore, ops: ApifyActorOpsService, route_id: str
) -> dict[str, Any]:
    """Project slots, evidence, recommendation, and source status safely."""

    route = ops.get_route(route_id)
    slot_operations = ops.slot_operations(route_id)
    result = public_actor_ops_route(ops, route)
    revisions: dict[str, dict[str, Any]] = {}
    slots: list[dict[str, Any]] = []
    for slot in route.get("slots", []):
        revision_id = slot.get("revision_id")
        revision = ops.get_revision(str(revision_id)) if revision_id else None
        if revision is not None:
            if str(revision.get("lifecycle")) in {"probationary", "certified"}:
                revision["certification_progress"] = ops.certification_progress(str(revision_id))
            revisions[str(revision_id)] = public_actor_ops_revision(revision)
        state, lifecycle = str(slot.get("candidate_state") or ""), str(slot.get("lifecycle") or "")
        slots.append({
            "slot": str(slot["slot_name"]), "revision_id": revision_id,
            "runnable": state in {"closed", "half_open", "probationary"}
            and lifecycle in {"certified", "probationary", "legacy_builtin"},
            "validation_status": lifecycle or "unconfigured",
            "actions": slot_operations.get(str(slot["slot_name"]), {}),
            "revision": revisions.get(str(revision_id)) if revision_id else None,
        })
    connection = store.connect()
    cutoff = (datetime.now(timezone.utc) - timedelta(hours=24)).isoformat()
    revision_rows = connection.execute(
        """
        SELECT revision.revision_id, revision.created_at AS revision_created_at,
               candidate.display_name,
               (SELECT attempt.actual_cost_usd FROM apify_actor_attempts AS attempt
                WHERE attempt.workspace_id = revision.workspace_id
                  AND attempt.adapter_revision_id = revision.revision_id
                  AND attempt.actual_cost_usd IS NOT NULL
                ORDER BY COALESCE(attempt.terminal_at, attempt.updated_at) DESC LIMIT 1) AS last_charge_usd,
               (SELECT AVG(attempt.actual_cost_usd) FROM apify_actor_attempts AS attempt
                WHERE attempt.workspace_id = revision.workspace_id
                  AND attempt.adapter_revision_id = revision.revision_id
                  AND attempt.actual_cost_usd IS NOT NULL
                  AND COALESCE(attempt.terminal_at, attempt.updated_at) >= ?) AS avg_charge_24h_usd,
               (SELECT COALESCE(validation.semantic_outcome, validation.status)
                FROM apify_actor_validations AS validation
                WHERE validation.workspace_id = revision.workspace_id
                  AND validation.revision_id = revision.revision_id
                ORDER BY COALESCE(validation.completed_at, validation.created_at) DESC LIMIT 1) AS last_canary_status,
               (SELECT COALESCE(validation.completed_at, validation.created_at)
                FROM apify_actor_validations AS validation
                WHERE validation.workspace_id = revision.workspace_id
                  AND validation.revision_id = revision.revision_id
                ORDER BY COALESCE(validation.completed_at, validation.created_at) DESC LIMIT 1) AS last_canary_at
        FROM apify_actor_adapter_revisions AS revision
        JOIN apify_actor_candidates AS candidate
          ON candidate.workspace_id = revision.workspace_id AND candidate.id = revision.candidate_id
        JOIN apify_actor_route_profiles AS profile
          ON profile.workspace_id = candidate.workspace_id AND profile.route_key = candidate.route_key
        WHERE revision.workspace_id = ? AND profile.route_id = ?
        ORDER BY revision.created_at DESC, revision.revision_id DESC LIMIT 200
        """,
        (cutoff, ops.workspace_id, route_id),
    ).fetchall()
    for row in revision_rows:
        revision = ops.get_revision(str(row["revision_id"]))
        revision["actor_public_name"] = str(row["display_name"] or "")
        if str(revision.get("lifecycle")) in {"probationary", "certified"}:
            revision["certification_progress"] = ops.certification_progress(str(row["revision_id"]))
        projected = public_actor_ops_revision(revision)
        projected.update({
            "last_charge_usd": row["last_charge_usd"],
            "avg_charge_24h_usd": row["avg_charge_24h_usd"],
            "last_canary_at": row["last_canary_at"],
            "last_canary_status": row["last_canary_status"],
        })
        revisions[str(row["revision_id"])] = projected
    for slot in slots:
        if slot["revision_id"] is not None:
            slot["revision"] = revisions.get(str(slot["revision_id"]))
    result["slots"], result["revisions"] = slots, list(revisions.values())
    recommendation = ops.recommend_active_pool(route_id)
    result["activation_recommendation"] = {
        "ready": bool(recommendation["ready"]), "already_active": bool(recommendation["already_active"]),
        "confirmation": "确认启用 Actor 主备", "problems": list(recommendation["problems"]),
        "certified_actor_count": int(recommendation["certified_actor_count"]),
        "backup_2_actor_count": int(recommendation["backup_2_actor_count"]),
        "runnable_actor_count": int(recommendation["runnable_actor_count"]),
        "publisher_count": int(recommendation["publisher_count"]), "activation_mode": recommendation["activation_mode"],
        "slots": [
            {"slot": name, "revision_id": revision_id, "revision": revisions.get(str(revision_id)) if revision_id else None}
            for name, revision_id in recommendation["slots"].items()
        ],
    }
    _add_revision_diffs(result, revisions, revision_rows, slots)
    _add_source_validations(connection, ops, route_id, slots, result)
    result["workflow"] = ops.workflow_state(route_id)
    discovery = connection.execute(
        """SELECT run_id, stage, error_code FROM apify_actor_discovery_runs
           WHERE workspace_id = ? AND route_id = ?
           ORDER BY created_at DESC, run_id DESC LIMIT 1""",
        (ops.workspace_id, route_id),
    ).fetchone()
    result["discovery_run_id"] = str(discovery["run_id"]) if discovery else None
    result["discovery_status"] = str(discovery["stage"]) if discovery else None
    result["discovery_error_code"] = discovery["error_code"] if discovery else None
    result.update(ApifyActorResilienceService(store, workspace_id=ops.workspace_id).route_resilience(route_id))
    return result


def _add_revision_diffs(
    result: dict[str, Any], revisions: dict[str, dict[str, Any]], revision_rows: list[Any], slots: list[dict[str, Any]]
) -> None:
    order = {str(row["revision_id"]): index for index, row in enumerate(revision_rows)}
    active = {str(slot["revision_id"]) for slot in slots if slot.get("revision_id") is not None}
    diffs: list[dict[str, Any]] = []
    for slot in slots:
        current_id = slot.get("revision_id")
        current, position = revisions.get(str(current_id)), order.get(str(current_id))
        if current is None or position is None:
            continue
        proposed = next((revisions[str(row["revision_id"])] for index, row in enumerate(revision_rows)
                         if index < position and str(row["revision_id"]) not in active
                         and str(revisions[str(row["revision_id"])]["actor_id"]) == str(current["actor_id"])
                         and str(revisions[str(row["revision_id"])]["lifecycle"]) in {"proposed", "static_valid", "probationary", "certified"}), None)
        changes = [field for field in ("build_id", "build_number", "manifest_hash") if proposed and proposed.get(field) != current.get(field)]
        if proposed and changes:
            diffs.append({"slot": str(slot["slot"]), "current_revision_id": str(current_id), "proposed_revision_id": str(proposed["revision_id"]), "changes": changes})
    result["revision_diffs"] = diffs
    result["replacement_needed"] = int(result["runnable_slots"]) < int(result["min_runtime_healthy"])


def _add_source_validations(
    connection: Any, ops: ApifyActorOpsService, route_id: str, slots: list[dict[str, Any]], result: dict[str, Any]
) -> None:
    bindings = connection.execute(
        """SELECT binding.source_id, binding.validation_status, binding.generation, binding.target_fingerprint,
                  binding.preferred_candidate_id, binding.active_candidate_id, binding.preference_suspended_at,
                  preferred.display_name AS preferred_actor_name, active.display_name AS active_actor_name
           FROM apify_source_route_bindings AS binding
           LEFT JOIN apify_actor_candidates AS preferred ON preferred.workspace_id = binding.workspace_id AND preferred.id = binding.preferred_candidate_id
           LEFT JOIN apify_actor_candidates AS active ON active.workspace_id = binding.workspace_id AND active.id = binding.active_candidate_id
           WHERE binding.workspace_id = ? AND binding.route_id = ?
           ORDER BY binding.updated_at DESC, binding.source_id LIMIT 100""",
        (ops.workspace_id, route_id),
    ).fetchall()
    source_validations, summary = [], {"ready": 0, "pending": 0, "failed": 0}
    for binding in bindings:
        latest, passed = _source_validation_evidence(connection, ops, route_id, binding)
        pending = next((str(slot["revision_id"]) for slot in slots if slot.get("revision_id") is not None and str(slot["revision_id"]) not in passed), None)
        validation_slots = [_source_validation_slot(slot, latest, passed, pending) for slot in slots]
        status = str(binding["validation_status"])
        bucket = "ready" if status in {"ready_1of1", "ready_2of2", "ready_3of3"} else "failed" if status in {"failed", "blocked"} else "pending"
        summary[bucket] += 1
        source_validations.append({
            "source_id": str(binding["source_id"]), "binding_status": status, "generation": int(binding["generation"]),
            "actor_preference": {
                "mode": "manual" if binding["preferred_candidate_id"] else "automatic",
                "preferred_candidate_id": binding["preferred_candidate_id"], "preferred_actor_name": binding["preferred_actor_name"],
                "active_candidate_id": binding["active_candidate_id"], "active_actor_name": binding["active_actor_name"],
                "preference_suspended": bool(binding["preference_suspended_at"]),
            }, "slots": validation_slots,
        })
    result["source_validations"], result["source_validation_summary"] = source_validations, summary
    _add_staged_source_validations(connection, ops, route_id, source_validations)


def _source_validation_evidence(connection: Any, ops: ApifyActorOpsService, route_id: str, binding: Any) -> tuple[dict[str, Any], set[str]]:
    rows = connection.execute(
        """SELECT revision_id, status, semantic_outcome, created_at, completed_at FROM apify_actor_validations
           WHERE workspace_id = ? AND route_id = ? AND source_id = ? AND kind = 'source_canary' AND target_fingerprint = ?
           ORDER BY COALESCE(completed_at, created_at) DESC""",
        (ops.workspace_id, route_id, binding["source_id"], binding["target_fingerprint"]),
    ).fetchall()
    latest: dict[str, Any] = {}
    passed: set[str] = set()
    for row in rows:
        revision_id = str(row["revision_id"])
        latest.setdefault(revision_id, row)
        if str(row["status"]) == "succeeded" and str(row["semantic_outcome"]) in {"valid_nonempty", "valid_empty"}:
            passed.add(revision_id)
    return latest, passed


def _source_validation_slot(slot: dict[str, Any], latest: dict[str, Any], passed: set[str], pending: str | None) -> dict[str, Any]:
    revision_id = str(slot["revision_id"]) if slot.get("revision_id") is not None else None
    evidence, passed_slot = latest.get(revision_id) if revision_id else None, revision_id in passed if revision_id else False
    return {
        "slot": str(slot["slot"]), "revision_id": revision_id,
        "status": "passed" if passed_slot else str(evidence["status"]) if evidence is not None else "pending",
        "last_canary_at": (evidence["completed_at"] or evidence["created_at"]) if evidence is not None else None,
        "last_canary_status": (evidence["semantic_outcome"] or evidence["status"]) if evidence is not None else None,
        "can_canary": revision_id is not None and revision_id == pending and (evidence is None or str(evidence["status"]) not in {"queued", "running"}),
    }


def _add_staged_source_validations(connection: Any, ops: ApifyActorOpsService, route_id: str, source_validations: list[dict[str, Any]]) -> None:
    stage = ops.active_pool_stage(route_id)
    if stage is None:
        return
    rows = connection.execute(
        """SELECT source_id, required_count, passed_count, status, last_error_code FROM apify_actor_pool_stage_sources
           WHERE workspace_id = ? AND stage_id = ?""", (ops.workspace_id, str(stage["stage_id"])),
    ).fetchall()
    staged = {str(row["source_id"]): dict(row) for row in rows}
    for source_validation in source_validations:
        if (value := staged.get(str(source_validation["source_id"]))) is not None:
            source_validation["staged_validation"] = {"stage_id": str(stage["stage_id"]), **value}
