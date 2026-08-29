"""Durable intent and evidence rules for an assigned Candidate recovery Probe."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any, Mapping

from .domain import AssignmentRole, CandidateLifecycle
from .runtime_candidate_health import candidate_operational_states


RECOVERY_CONFIRMATION = "确认实测恢复 Actor"
RECOVERY_INTENT = "operator_recovery"
RECOVERY_SLOT_PREFIX = "operator-recovery:"
RECOVERY_ATTEMPT_GROUP_PREFIX = f"maintenance:{RECOVERY_SLOT_PREFIX}"
RECOVERY_PAYLOAD_KEYS = frozenset({
    "intent", "route_id", "candidate_id", "source_id", "binding_version",
    "slot", "expected_route_generation", "expected_candidate_generation",
    "expected_last_failure_at", "idempotency_key",
})


def recovery_slot(idempotency_key: str) -> str:
    digest = hashlib.sha256(str(idempotency_key).encode()).hexdigest()[:32]
    return f"{RECOVERY_SLOT_PREFIX}{digest}"


def recovery_job_payload(
    *,
    route_id: str,
    candidate_id: str,
    source_id: str,
    binding_version: int,
    expected_route_generation: int,
    expected_candidate_generation: int,
    expected_last_failure_at: str,
    idempotency_key: str,
) -> dict[str, object]:
    return {
        "intent": RECOVERY_INTENT,
        "route_id": route_id,
        "candidate_id": candidate_id,
        "source_id": source_id,
        "binding_version": int(binding_version),
        "slot": recovery_slot(idempotency_key),
        "expected_route_generation": int(expected_route_generation),
        "expected_candidate_generation": int(expected_candidate_generation),
        "expected_last_failure_at": expected_last_failure_at,
        "idempotency_key": idempotency_key,
    }


def valid_recovery_job_payload(payload: Mapping[str, object]) -> bool:
    return bool(
        set(payload) == RECOVERY_PAYLOAD_KEYS
        and payload.get("intent") == RECOVERY_INTENT
        and str(payload.get("slot") or "")
        == recovery_slot(str(payload.get("idempotency_key") or ""))
        and all(
            str(payload.get(key) or "").strip()
            for key in (
                "route_id", "candidate_id", "source_id",
                "expected_last_failure_at", "idempotency_key",
            )
        )
        and _positive_int(payload.get("binding_version"))
        and _positive_int(payload.get("expected_route_generation"))
        and _positive_int(payload.get("expected_candidate_generation"))
    )


def recovery_target_is_current(
    repository: Any,
    candidate: Any,
    *,
    expected_last_failure_at: str,
    now: datetime | None = None,
) -> bool:
    current = (now or datetime.now(timezone.utc)).astimezone(timezone.utc)
    state = candidate_operational_states(repository, (candidate,), now=current)[
        candidate.candidate_id
    ]
    failure = str(state.last_failure_at or "")
    failure_at = _time(failure)
    if (
        candidate.assignment_role is AssignmentRole.INACTIVE
        or candidate.lifecycle
        not in {CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED}
        or failure != str(expected_last_failure_at)
        or failure_at is None
        or failure_at >= current
    ):
        return False
    return state.confirmed_failure


def commit_recovery_success(
    repository: Any,
    *,
    attempt_id: str,
    candidate_id: str,
    expected_route_generation: int,
    expected_candidate_generation: int,
    expected_source_id: str,
    expected_binding_version: int,
    expected_last_failure_at: str,
) -> tuple[Any, Any] | None:
    """Atomically accept one exact post-failure, settled Probe observation."""

    repository._require_transaction()
    candidate = repository.get_candidate(candidate_id)
    route = repository.get_route(candidate.route_id)
    summary = repository.connection.execute(
        """SELECT last_failure_at FROM actor_candidates_v2
             WHERE workspace_id=? AND candidate_id=?""",
        (repository.workspace_id, candidate_id),
    ).fetchone()
    if (
        route.generation != int(expected_route_generation)
        or candidate.generation != int(expected_candidate_generation)
        or candidate.assignment_role is AssignmentRole.INACTIVE
        or candidate.lifecycle
        not in {CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED}
        or summary is None
        or str(summary["last_failure_at"] or "") != expected_last_failure_at
    ):
        return None
    evidence = repository.connection.execute(
        """SELECT attempt.source_id, attempt.binding_version
             FROM actor_attempts_v2 AS attempt
             JOIN actor_source_bindings_v2 AS binding
               ON binding.workspace_id=attempt.workspace_id
              AND binding.source_id=attempt.source_id
              AND binding.route_id=attempt.route_id
              AND binding.binding_version=attempt.binding_version
              AND binding.target_fingerprint=attempt.target_fingerprint
            WHERE attempt.workspace_id=? AND attempt.attempt_id=?
              AND attempt.route_id=? AND attempt.candidate_id=?
              AND attempt.route_generation=? AND attempt.kind='probe'
              AND attempt.source_id=? AND attempt.binding_version=?
              AND attempt.attempt_group_id LIKE ?
              AND attempt.status='succeeded'
              AND attempt.semantic_outcome='valid_nonempty'
              AND attempt.cost_final=1 AND attempt.created_at>?
              AND binding.status='ready'""",
        (
            repository.workspace_id,
            attempt_id,
            candidate.route_id,
            candidate_id,
            int(expected_route_generation),
            expected_source_id,
            int(expected_binding_version),
            f"{RECOVERY_ATTEMPT_GROUP_PREFIX}%",
            expected_last_failure_at,
        ),
    ).fetchone()
    if evidence is None:
        return None
    current = repository.record_candidate_outcome(
        candidate_id,
        expected_generation=candidate.generation,
        succeeded=True,
    )
    return current, evidence


def apply_recovery_success(
    repository: Any,
    *,
    attempt_id: str,
    candidate_id: str,
    binding: Any,
    expected_route_generation: int,
    expected_candidate_generation: int,
    expected_last_failure_at: str,
) -> bool:
    with repository.transaction():
        committed = commit_recovery_success(
            repository,
            attempt_id=attempt_id,
            candidate_id=candidate_id,
            expected_route_generation=expected_route_generation,
            expected_candidate_generation=expected_candidate_generation,
            expected_source_id=str(binding.source_id),
            expected_binding_version=int(binding.binding_version),
            expected_last_failure_at=expected_last_failure_at,
        )
        if committed is None:
            return False
        current, _evidence = committed
        repository.resilience.record_candidate_success(
            binding=binding,
            candidate_id=current.candidate_id,
            logical_job_id=f"recovery:{attempt_id}",
        )
    return True


def apply_settled_recovery_success(
    repository: Any, candidate_id: str
) -> Any | None:
    """Atomically project a reconciled recovery Attempt into both health stores."""

    with repository.transaction():
        candidate = repository.get_candidate(candidate_id)
        evidence = settled_recovery_evidence(repository, candidate)
        if evidence is None:
            return None
        current = repository.record_candidate_outcome(
            candidate.candidate_id,
            expected_generation=candidate.generation,
            succeeded=True,
        )
        binding = repository.get_binding(str(evidence["source_id"]))
        if binding.binding_version != int(evidence["binding_version"]):
            raise RuntimeError("recovery Probe binding changed before projection")
        repository.resilience.record_candidate_success(
            binding=binding,
            candidate_id=current.candidate_id,
            logical_job_id=str(evidence["attempt_id"]),
        )
    return current


def settled_recovery_evidence(repository: Any, candidate: Any) -> Any | None:
    """Return one current-Binding proof not already reflected in Candidate success."""

    state = candidate_operational_states(repository, (candidate,))[
        candidate.candidate_id
    ]
    failure = str(state.last_failure_at or "")
    if (
        not failure
        or candidate.assignment_role is AssignmentRole.INACTIVE
        or candidate.lifecycle
        not in {CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED}
    ):
        return None
    return repository.connection.execute(
        """SELECT attempt.attempt_id, attempt.source_id,
                  attempt.binding_version, attempt.updated_at
             FROM actor_attempts_v2 AS attempt
             JOIN actor_source_bindings_v2 AS binding
               ON binding.workspace_id=attempt.workspace_id
              AND binding.source_id=attempt.source_id
              AND binding.route_id=attempt.route_id
              AND binding.binding_version=attempt.binding_version
              AND binding.target_fingerprint=attempt.target_fingerprint
             JOIN actor_routes_v2 AS route
               ON route.workspace_id=attempt.workspace_id
              AND route.route_id=attempt.route_id
              AND route.generation=attempt.route_generation
            WHERE attempt.workspace_id=? AND attempt.route_id=?
              AND attempt.candidate_id=? AND attempt.kind='probe'
              AND attempt.attempt_group_id LIKE ?
              AND attempt.status='succeeded'
              AND attempt.semantic_outcome='valid_nonempty'
              AND attempt.cost_final=1 AND binding.status='ready'
              AND attempt.created_at>?
              AND attempt.updated_at>?
            ORDER BY attempt.updated_at DESC, attempt.attempt_id DESC LIMIT 1""",
        (
            repository.workspace_id,
            candidate.route_id,
            candidate.candidate_id,
            f"{RECOVERY_ATTEMPT_GROUP_PREFIX}%",
            failure,
            str(state.last_success_at or ""),
        ),
    ).fetchone()


def settled_recovery_candidate_ids(
    repository: Any, *, limit: int = 20
) -> tuple[str, ...]:
    """Find bounded existing recovery facts that still need health projection."""

    rows = repository.connection.execute(
        """SELECT attempt.candidate_id, MAX(attempt.updated_at) AS evidence_at
             FROM actor_attempts_v2 AS attempt
             JOIN actor_candidates_v2 AS candidate
               ON candidate.workspace_id=attempt.workspace_id
              AND candidate.candidate_id=attempt.candidate_id
             JOIN actor_source_bindings_v2 AS binding
               ON binding.workspace_id=attempt.workspace_id
              AND binding.source_id=attempt.source_id
              AND binding.route_id=attempt.route_id
              AND binding.binding_version=attempt.binding_version
              AND binding.target_fingerprint=attempt.target_fingerprint
             JOIN actor_routes_v2 AS route
               ON route.workspace_id=attempt.workspace_id
              AND route.route_id=attempt.route_id
              AND route.generation=attempt.route_generation
            WHERE attempt.workspace_id=? AND attempt.kind='probe'
              AND attempt.attempt_group_id LIKE ?
              AND attempt.status='succeeded'
              AND attempt.semantic_outcome='valid_nonempty'
              AND attempt.cost_final=1 AND binding.status='ready'
              AND candidate.assignment_role IN ('active','standby')
              AND candidate.lifecycle IN ('probationary','certified')
              AND attempt.created_at>COALESCE(candidate.last_failure_at, '')
              AND attempt.updated_at>COALESCE(candidate.last_success_at, '')
            GROUP BY attempt.candidate_id
            ORDER BY evidence_at, attempt.candidate_id LIMIT ?""",
        (
            repository.workspace_id,
            f"{RECOVERY_ATTEMPT_GROUP_PREFIX}%",
            min(max(int(limit), 1), 100),
        ),
    ).fetchall()
    return tuple(str(row["candidate_id"]) for row in rows)


def _positive_int(value: object) -> bool:
    return isinstance(value, int) and not isinstance(value, bool) and value >= 1


def _time(value: object) -> datetime | None:
    try:
        parsed = datetime.fromisoformat(str(value).replace("Z", "+00:00"))
    except (TypeError, ValueError):
        return None
    if parsed.tzinfo is None:
        parsed = parsed.replace(tzinfo=timezone.utc)
    return parsed.astimezone(timezone.utc)


__all__ = [
    "RECOVERY_CONFIRMATION", "RECOVERY_INTENT", "RECOVERY_PAYLOAD_KEYS",
    "apply_recovery_success", "apply_settled_recovery_success",
    "commit_recovery_success", "recovery_job_payload", "recovery_slot",
    "recovery_target_is_current",
    "settled_recovery_candidate_ids", "settled_recovery_evidence",
    "valid_recovery_job_payload",
]
