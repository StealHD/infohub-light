"""Atomic source-circuit evidence for settled paid Candidate failures."""

from __future__ import annotations

from typing import Any

from .repository_errors import ActorOpsNotFound
from .source_candidate_circuit import SourceCandidateCircuit


_OUTCOMES = frozenset({"paid_candidate_failure", "stale_regression"})


def record_settled_candidate_failure(
    repository: Any, *, attempt_id: str, outcome: str
) -> bool:
    """Write the exact Attempt's source circuit in its settlement transaction."""

    repository._require_transaction()
    if outcome not in _OUTCOMES:
        raise ValueError("unsupported candidate failure circuit outcome")
    row = repository.get_attempt(attempt_id)
    if (
        str(row["kind"]) != "fetch"
        or str(row["status"]) != "failed"
        or str(row["failure_class"] or "") != "candidate"
        or not bool(row["cost_final"])
        or float(row["actual_cost_usd"] or 0) <= 0
        or not row["source_id"]
        or row["binding_version"] is None
    ):
        return False
    try:
        binding = repository.get_binding(str(row["source_id"]))
    except ActorOpsNotFound:
        return False
    if (
        binding.binding_version != int(row["binding_version"])
        or binding.route_id != str(row["route_id"])
    ):
        return False
    SourceCandidateCircuit(repository).record_failure_in_transaction(
        binding=binding,
        candidate_id=str(row["candidate_id"]),
        outcome=outcome,
        logical_job_id=str(row["logical_job_id"] or ""),
    )
    return True


__all__ = ["record_settled_candidate_failure"]
