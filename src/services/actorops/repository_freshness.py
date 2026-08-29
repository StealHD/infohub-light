"""Source freshness planning and per-source Actor circuit state."""

from __future__ import annotations

import re
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .domain import AssignmentRole, CandidateLifecycle
from .repository_errors import ActorOpsConflict
from .runtime_candidate_health import (
    candidate_operational_states,
    eligible_runtime_candidates,
)
from .source_candidate_circuit import SourceCandidateCircuit


_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


@dataclass(frozen=True, slots=True)
class FreshnessPlan:
    candidates: tuple[Any, ...]
    primary_candidate_id: str | None = None
    cross_check: bool = False
    blocked_code: str | None = None


class SourceFreshnessRepository:
    def __init__(self, repository: Any) -> None:
        self.repository = repository
        self.circuit = SourceCandidateCircuit(repository)

    def plan_candidates(
        self, *, binding: Any, candidates: tuple[Any, ...], natural_schedule: bool,
        logical_job_id: str = "",
    ) -> FreshnessPlan:
        candidates = eligible_runtime_candidates(self.repository, candidates)
        if not candidates:
            return FreshnessPlan(())
        if self.circuit.has_unsettled_cost(
            binding, logical_job_id=logical_job_id
        ):
            return FreshnessPlan(
                (), blocked_code="actorops_cost_settlement_required"
            )
        states = candidate_operational_states(self.repository, candidates)
        candidates = tuple(
            item for _, item in sorted(
                enumerate(candidates),
                key=lambda pair: (
                    states[str(pair[1].candidate_id)].deprioritized,
                    pair[0],
                ),
            )
        )
        available = tuple(
            item for item in candidates
            if self.circuit.available(
                binding, item.candidate_id, logical_job_id=logical_job_id
            )
        )
        if not available:
            return FreshnessPlan(())
        primary = available[0]
        fresh = self._freshness(
            binding.source_id, primary.candidate_id, binding.binding_version
        )
        alternatives = tuple(
            item for item in available if item.candidate_id != primary.candidate_id
        )
        if (
            natural_schedule and fresh
            and int(fresh["consecutive_scheduled_no_advance"]) >= 3
            and alternatives
        ):
            return FreshnessPlan(
                candidates=(alternatives[0], primary, *alternatives[1:]),
                primary_candidate_id=primary.candidate_id,
                cross_check=True,
            )
        return FreshnessPlan(available)

    def record_regular_result(
        self, *, binding: Any, candidate_id: str, outcome: str,
        logical_job_id: str, natural_schedule: bool,
    ) -> None:
        self.record_candidate_success(
            binding=binding, candidate_id=candidate_id,
            logical_job_id=logical_job_id,
        )
        if not natural_schedule:
            return
        if outcome == "no_advance":
            previous = self._freshness(
                binding.source_id, candidate_id, binding.binding_version
            )
            count = int(previous["consecutive_scheduled_no_advance"]) + 1 if previous else 1
            self._upsert_freshness(
                binding=binding, candidate_id=candidate_id, count=count,
                state="suspected_stale" if count >= 3 else "neutral",
                outcome=outcome, job_id=logical_job_id,
            )
        elif outcome == "advanced":
            self._upsert_freshness(
                binding=binding, candidate_id=candidate_id, count=0,
                state="neutral", outcome=outcome, job_id=logical_job_id,
            )

    def record_cross_check(
        self, *, binding: Any, primary_candidate_id: str, candidate_id: str,
        outcome: str, logical_job_id: str,
    ) -> str:
        if outcome in {"no_advance", "advanced"}:
            self.record_candidate_success(
                binding=binding, candidate_id=candidate_id,
                logical_job_id=logical_job_id,
            )
        if outcome == "no_advance":
            for current_id in (primary_candidate_id, candidate_id):
                self._upsert_freshness(
                    binding=binding, candidate_id=current_id, count=0,
                    state="confirmed_no_change", outcome=outcome,
                    job_id=logical_job_id, confirmed=True,
                )
            return "confirmed_no_change"
        if outcome != "advanced":
            return "unverified"
        self.circuit.record_failure(
            binding=binding, candidate_id=primary_candidate_id,
            outcome="cross_check_advanced", logical_job_id=logical_job_id,
        )
        self._upsert_freshness(
            binding=binding, candidate_id=candidate_id, count=0,
            state="neutral", outcome=outcome, job_id=logical_job_id,
        )
        with self.repository.transaction():
            changed = self.repository.connection.execute(
                """UPDATE actor_source_bindings_v2
                      SET preferred_candidate_id=?, updated_at=?
                    WHERE workspace_id=? AND source_id=? AND binding_version=?""",
                (
                    candidate_id, _stamp(), self.repository.workspace_id,
                    binding.source_id, binding.binding_version,
                ),
            ).rowcount
            if changed != 1:
                raise ActorOpsConflict("binding changed before freshness preference")
        self._maybe_globally_demote(primary_candidate_id)
        return "source_stale"

    def record_stale_regression(
        self, *, binding: Any, candidate_id: str, logical_job_id: str
    ) -> None:
        self.circuit.record_failure(
            binding=binding, candidate_id=candidate_id,
            outcome="stale_regression", logical_job_id=logical_job_id,
        )
        self._maybe_globally_demote(candidate_id)

    def record_paid_candidate_failure(
        self, *, binding: Any, candidate_id: str, logical_job_id: str
    ) -> None:
        self.circuit.record_failure(
            binding=binding, candidate_id=candidate_id,
            outcome="paid_candidate_failure", logical_job_id=logical_job_id,
        )

    def record_candidate_success(
        self, *, binding: Any, candidate_id: str, logical_job_id: str
    ) -> None:
        self.circuit.record_success(
            binding=binding, candidate_id=candidate_id,
            logical_job_id=logical_job_id,
        )

    def _freshness(
        self, source_id: str, candidate_id: str, binding_version: int
    ) -> Any | None:
        return self.repository.connection.execute(
            """SELECT * FROM actor_source_candidate_freshness_v2
                WHERE workspace_id=? AND source_id=? AND candidate_id=?
                  AND binding_version=?""",
            (
                self.repository.workspace_id, source_id, candidate_id,
                binding_version,
            ),
        ).fetchone()

    def _upsert_freshness(
        self, *, binding: Any, candidate_id: str, count: int, state: str,
        outcome: str, job_id: str, cooldown_until: str | None = None,
        confirmed: bool = False,
    ) -> None:
        stamp = _stamp()
        with self.repository.transaction():
            self.repository.connection.execute(
                """INSERT INTO actor_source_candidate_freshness_v2 (
                       workspace_id, source_id, candidate_id, binding_version,
                       consecutive_scheduled_no_advance, state, cooldown_until,
                       last_outcome, last_job_id, last_checked_at,
                       last_confirmed_at, created_at, updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(workspace_id,source_id,candidate_id,binding_version)
                   DO UPDATE SET
                       consecutive_scheduled_no_advance=excluded.consecutive_scheduled_no_advance,
                       state=excluded.state, cooldown_until=excluded.cooldown_until,
                       last_outcome=excluded.last_outcome,
                       last_job_id=excluded.last_job_id,
                       last_checked_at=excluded.last_checked_at,
                       last_confirmed_at=COALESCE(
                           excluded.last_confirmed_at,
                           actor_source_candidate_freshness_v2.last_confirmed_at
                       ), updated_at=excluded.updated_at""",
                (
                    self.repository.workspace_id, binding.source_id, candidate_id,
                    binding.binding_version, count, state, cooldown_until, outcome,
                    _safe_id(job_id), stamp, stamp if confirmed else None,
                    stamp, stamp,
                ),
            )

    def _maybe_globally_demote(self, candidate_id: str) -> None:
        count = int(self.repository.connection.execute(
            """SELECT COUNT(DISTINCT source_id)
                 FROM actor_source_candidate_freshness_v2
                WHERE workspace_id=? AND candidate_id=? AND state='source_stale'
                  AND last_outcome IN ('stale_regression','cross_check_advanced')
                  AND last_confirmed_at>=?""",
            (
                self.repository.workspace_id, candidate_id,
                _stamp(_now() - timedelta(hours=24)),
            ),
        ).fetchone()[0])
        candidate = self.repository.get_candidate(candidate_id)
        assigned = [
            item for item in self.repository.list_route_candidates(candidate.route_id)
            if item.assignment_role is not AssignmentRole.INACTIVE
        ]
        if (
            count < 2 or len(assigned) < 2
            or candidate.lifecycle not in {
                CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED,
            }
        ):
            return
        try:
            with self.repository.transaction():
                self.repository.transition_candidate(
                    candidate_id, candidate.lifecycle,
                    CandidateLifecycle.QUARANTINED,
                    expected_generation=candidate.generation,
                    error_class="candidate",
                    error_code="actorops_v2_stale_global_threshold",
                )
        except ActorOpsConflict:
            return


def _safe_id(value: str | None) -> str | None:
    return str(value) if value and _SAFE_ID.fullmatch(str(value)) else None


__all__ = ["FreshnessPlan", "SourceFreshnessRepository"]
