"""Candidate lifecycle accounting for settled maintenance and replacement Probes."""

from __future__ import annotations

from typing import Any

from .domain import CandidateLifecycle, FailureClass


def record_settled_probe_candidate_failure(
    repository: Any, *, attempt_id: str
) -> Any | None:
    """Reject or quarantine a Candidate only after its Probe cost is final."""

    repository._require_transaction()
    attempt = repository.get_attempt(attempt_id)
    if (
        str(attempt["kind"]) != "probe"
        or str(attempt["status"]) != "failed"
        or str(attempt["failure_class"] or "") != FailureClass.CANDIDATE.value
        or not bool(attempt["cost_final"])
    ):
        return None
    candidate = repository.get_candidate(str(attempt["candidate_id"]))
    if candidate.lifecycle in {
        CandidateLifecycle.REJECTED,
        CandidateLifecycle.QUARANTINED,
        CandidateLifecycle.DISABLED,
        CandidateLifecycle.SUPERSEDED,
    }:
        return candidate
    if candidate.lifecycle not in {
        CandidateLifecycle.STATIC_VALID,
        CandidateLifecycle.PROBATIONARY,
        CandidateLifecycle.CERTIFIED,
    }:
        return None
    error_code = str(attempt["error_code"] or attempt["semantic_outcome"])
    current = repository.record_candidate_outcome(
        candidate.candidate_id,
        expected_generation=candidate.generation,
        succeeded=False,
        error_class=FailureClass.CANDIDATE.value,
        error_code=error_code,
    )
    target = (
        CandidateLifecycle.REJECTED
        if current.lifecycle is CandidateLifecycle.STATIC_VALID
        else CandidateLifecycle.QUARANTINED
    )
    return repository.transition_candidate(
        current.candidate_id,
        current.lifecycle,
        target,
        expected_generation=current.generation,
        error_class=FailureClass.CANDIDATE.value,
        error_code=error_code,
    )


__all__ = ["record_settled_probe_candidate_failure"]
