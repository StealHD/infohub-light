"""Safe three-stage compatibility projections derived from durable facts."""

from __future__ import annotations

from typing import Any

from ..apify_actor_manifest import ActorManifestError, parse_actor_manifest
from .domain import CandidateLifecycle
from .policy import candidate_has_exact_execution_contract
from .runtime_candidate_health import candidate_operational_states


def candidate_compatibility(repository: Any, candidate: Any) -> dict[str, object]:
    proof_count = _proof_count(repository, candidate.candidate_id)
    required_count = len(repository.operator.binding_set(candidate.route_id))
    operational = candidate_operational_states(repository, (candidate,))[
        candidate.candidate_id
    ]
    exact_contract = candidate_has_exact_execution_contract(candidate)
    sampled = repository.sampling.get_valid(candidate) is not None
    healthy = not operational.confirmed_failure and operational.retry_at is None
    usable = bool(
        exact_contract
        and healthy
        and candidate.lifecycle in {
            CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED,
        }
        and required_count > 0
        and proof_count >= required_count
    )
    probe_eligible = bool(
        healthy
        and (
            (
                exact_contract
                and candidate.lifecycle in {
                    CandidateLifecycle.STATIC_VALID,
                    CandidateLifecycle.PROBATIONARY,
                    CandidateLifecycle.CERTIFIED,
                }
            )
            or (
                sampled
                and candidate.lifecycle is CandidateLifecycle.MAPPING_PENDING
            )
        )
    )
    plan = repository.connection.execute(
        """SELECT status,error_code FROM actor_replacement_plans_v2
           WHERE workspace_id=? AND proposed_candidate_id=?
             AND status IN ('previewed','authorized','running','ready')
           ORDER BY updated_at DESC LIMIT 1""",
        (repository.workspace_id, candidate.candidate_id),
    ).fetchone()
    if plan is not None and str(plan["status"]) == "running" and str(
        plan["error_code"] or ""
    ) in {
        "actorops_replacement_dataset_revalidating",
        "actorops_replacement_adaptation_pending",
    }:
        stage = "adapting"
    elif usable:
        stage = "system_usable"
    elif not healthy:
        stage = "blocked"
    elif candidate.lifecycle in {
        CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED,
    }:
        # A previously runnable Candidate is not system-usable for a Route
        # until the current Binding set has settled Dataset proof.
        stage = "sample_required"
    elif candidate.lifecycle is CandidateLifecycle.STATIC_VALID:
        stage = "static_ready"
    elif candidate.lifecycle is CandidateLifecycle.DISCOVERED:
        stage = "candidate"
    elif sampled and candidate.lifecycle is CandidateLifecycle.MAPPING_PENDING:
        stage = "sample_required"
    elif candidate.lifecycle is CandidateLifecycle.MAPPING_PENDING:
        stage = "blocked"
    else:
        stage = "blocked"
    return {
        "compatibility_stage": stage,
        "mapping_evidence": "dataset" if proof_count else "schema",
        "dataset_shape": _dataset_shape(candidate),
        "system_usable": usable,
        "probe_eligible": probe_eligible,
        "binding_proof_count": proof_count,
        "binding_required_count": required_count,
        "compatibility_issue_code": _compatibility_issue(
            exact_contract=exact_contract,
            healthy=healthy,
            issue_code=operational.issue_code,
            proof_count=proof_count,
            required_count=required_count,
            sampled=sampled,
        ),
    }


def _compatibility_issue(
    *, exact_contract: bool, healthy: bool, issue_code: str | None,
    proof_count: int, required_count: int, sampled: bool,
) -> str | None:
    if not healthy:
        return str(issue_code or "candidate_unavailable")
    if not exact_contract and not sampled:
        return "output_sample_required"
    if required_count > 0 and proof_count < required_count and proof_count > 0:
        return "binding_proof_incomplete"
    if required_count <= 0:
        return "route_binding_missing"
    return None


def replacement_phase(repository: Any, row: Any) -> str:
    status = str(row["status"])
    error = str(row["error_code"] or "")
    if status in {"ready", "applied"}:
        return "proof_complete"
    if error == "actorops_replacement_cost_pending":
        return "cost_reconciliation"
    if error == "actorops_replacement_dataset_revalidating":
        return "dataset_revalidating"
    if error == "actorops_replacement_adaptation_pending":
        return "dataset_adapting"
    attempt = repository.connection.execute(
        """SELECT status,dataset_id,cost_final FROM actor_attempts_v2
           WHERE workspace_id=? AND attempt_group_id=?
           ORDER BY created_at DESC,attempt_id DESC LIMIT 1""",
        (repository.workspace_id, str(row["plan_id"])),
    ).fetchone()
    if status == "previewed":
        return "schema_analysis"
    if attempt is None:
        return "sample_required"
    if not bool(attempt["cost_final"]) and str(attempt["status"]) in {
        "start_unknown", "succeeded", "failed",
    }:
        return "cost_reconciliation"
    if attempt["dataset_id"]:
        return "dataset_read"
    return "sample_required"


def _proof_count(repository: Any, candidate_id: str) -> int:
    candidate = repository.get_candidate(candidate_id)
    bindings = repository.operator.binding_set(candidate.route_id)
    return sum(
        bool(repository.connection.execute(
            """SELECT 1 FROM actor_attempts_v2
               WHERE workspace_id=? AND candidate_id=? AND source_id=?
                 AND binding_version=? AND target_fingerprint=? AND kind='probe'
                 AND status='succeeded' AND semantic_outcome='valid_nonempty'
                 AND cost_final=1
               LIMIT 1""",
            (
                repository.workspace_id, candidate_id, source_id,
                binding_version, fingerprint,
            ),
        ).fetchone())
        for source_id, binding_version, fingerprint in bindings
    )


def _dataset_shape(candidate: Any) -> str:
    if not candidate.manifest_json:
        return "unknown"
    try:
        plan = parse_actor_manifest(str(candidate.manifest_json)).row_extraction
    except (ActorManifestError, TypeError, ValueError):
        return "unknown"
    if plan is None or plan.mode == "top_level":
        return "flat"
    return "mixed" if plan.filters else "nested"


__all__ = ["candidate_compatibility", "replacement_phase"]
