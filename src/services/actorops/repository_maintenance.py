"""Policy, budget, and assignment SQL for bounded v2 maintenance."""

from __future__ import annotations

import json
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from .domain import AssignmentRole, CandidateLifecycle, MaintenanceBudget, MaintenancePolicyRecord
from .maintenance_selection import select_probe_target
from .policy import candidate_is_runnable
from .recovery_probe import (
    apply_settled_recovery_success,
    recovery_target_is_current,
)
from .repository_errors import ActorOpsConflict, ActorOpsNotFound
from .runtime_candidate_health import candidate_operational_states
from .youtube_capabilities import proves_combined_latest_items


MAX_MONTHLY_USD, MAX_PROBE_USD, MAX_PROBES_PER_DAY = 3.0, 0.05, 5

@dataclass(frozen=True, slots=True)
class EffectiveMaintenancePolicy:
    workspace: MaintenancePolicyRecord
    route: MaintenancePolicyRecord
    principal_user_id: str | None

    @property
    def authorized(self) -> bool:
        return bool(
            self.workspace.enabled and self.route.enabled
            and self.workspace.authorization_origin != "none"
            and self.route.authorization_origin != "none"
            and self.principal_user_id
        )

    @property
    def max_charge_usd(self) -> float:
        return min(float(self.route.max_probe_usd or 0), MAX_PROBE_USD)


class MaintenanceRepository:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def get_policy(self, route_id: str | None) -> MaintenancePolicyRecord:
        row = self.repository.connection.execute(
            """SELECT * FROM actor_maintenance_policies_v2
               WHERE workspace_id=? AND route_id IS ?""",
            (self.repository.workspace_id, route_id),
        ).fetchone()
        if row is None:
            raise ActorOpsNotFound("maintenance policy not found: " + ("workspace" if route_id is None else f"route {route_id}"))
        return _policy(row)

    def effective_policy(self, route_id: str) -> EffectiveMaintenancePolicy:
        principal = self.repository.connection.execute(
            """SELECT id FROM users WHERE workspace_id=? AND enabled=1
               AND role IN ('owner','admin') ORDER BY created_at, id LIMIT 1""",
            (self.repository.workspace_id,),
        ).fetchone()
        return EffectiveMaintenancePolicy(
            self.get_policy(None), self.get_policy(route_id),
            str(principal["id"]) if principal is not None else None,
        )

    def set_enabled(
        self,
        route_id: str | None,
        enabled: bool,
        *,
        authorized_by_user_id: str | None,
        expected_generation: int,
        now: datetime | None = None,
    ) -> MaintenancePolicyRecord:
        self.repository._require_transaction()
        if enabled and not str(authorized_by_user_id or "").strip():
            raise ValueError("maintenance authorization requires an operator")
        if enabled and self.repository.connection.execute(
            """SELECT 1 FROM users WHERE id=? AND workspace_id=? AND enabled=1
               AND role IN ('owner','admin')""",
            (authorized_by_user_id, self.repository.workspace_id),
        ).fetchone() is None:
            raise ActorOpsConflict("actorops_maintenance_authorizer_invalid")
        stamp = _stamp(now)
        changed = self.repository.connection.execute(
            """UPDATE actor_maintenance_policies_v2
               SET enabled=?, authorized_by_user_id=?, authorized_at=?,
                   authorization_origin=?,
                   generation=generation+1, updated_at=?
               WHERE workspace_id=? AND route_id IS ? AND generation=?""",
            (
                int(enabled), str(authorized_by_user_id) if enabled else None,
                stamp if enabled else None, "operator" if enabled else "none",
                stamp, self.repository.workspace_id,
                route_id, expected_generation,
            ),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("maintenance policy changed before authorization")
        if enabled:
            if route_id is None:
                self.repository.connection.execute(
                    """UPDATE actor_route_repairs_v2
                          SET next_attempt_at=?, updated_at=?
                        WHERE workspace_id=? AND status='blocked'""",
                    (stamp, stamp, self.repository.workspace_id),
                )
            else:
                self.repository.connection.execute(
                    """UPDATE actor_route_repairs_v2
                          SET next_attempt_at=?, updated_at=?
                        WHERE workspace_id=? AND route_id=? AND status='blocked'""",
                    (stamp, stamp, self.repository.workspace_id, route_id),
                )
        return self.get_policy(route_id)

    def probe_budget(self, route_id: str, now: datetime) -> MaintenanceBudget:
        current = _utc(now)
        month_start = current.replace(day=1, hour=0, minute=0, second=0, microsecond=0)
        day_start = current.replace(hour=0, minute=0, second=0, microsecond=0)
        day_end = day_start + timedelta(days=1)
        row = self.repository.connection.execute(
            """SELECT
                 COALESCE((SELECT SUM(CASE WHEN cost_final=1 THEN COALESCE(actual_cost_usd, 0) ELSE 0 END)
                           FROM actor_attempts_v2 WHERE workspace_id=? AND kind='probe' AND created_at>=?), 0),
                 COALESCE((SELECT SUM(CASE WHEN cost_final=0 THEN reserved_usd ELSE 0 END)
                           FROM actor_attempts_v2 WHERE workspace_id=? AND kind='probe' AND created_at>=?), 0),
                 (SELECT COUNT(*) FROM actor_attempts_v2
                  WHERE workspace_id=? AND route_id=? AND kind='probe'
                    AND created_at>=? AND created_at<?)""",
            (
                self.repository.workspace_id, month_start.isoformat(),
                self.repository.workspace_id, month_start.isoformat(),
                self.repository.workspace_id, route_id, day_start.isoformat(), day_end.isoformat(),
            ),
        ).fetchone()
        return MaintenanceBudget(float(row[0]), float(row[1]), int(row[2]))

    def reserve_probe(self, **values: Any) -> None:
        """Atomically admit exactly one paid Probe under both policy limits."""

        self.repository._require_transaction()
        route_id = str(values["route_id"])
        policy = self.effective_policy(route_id)
        if not policy.authorized:
            raise ActorOpsConflict("actorops_maintenance_not_authorized")
        if (
            policy.workspace.generation != int(values["expected_workspace_policy_generation"])
            or policy.route.generation != int(values["expected_route_policy_generation"])
        ):
            raise ActorOpsConflict("maintenance policy changed before probe")
        now = _utc(values["now"])
        reserved = float(values["reserved_usd"])
        route = self.repository.get_route(route_id)
        if reserved <= 0 or reserved > policy.max_charge_usd:
            raise ActorOpsConflict("actorops_maintenance_probe_cap_exceeded")
        candidate = self.repository.get_candidate(str(values["candidate_id"]))
        binding = self.repository.get_binding(str(values["source_id"]))
        operator_recovery = bool(values.get("operator_recovery"))
        standard_candidate = (
            not operator_recovery
            and candidate.lifecycle
            in (CandidateLifecycle.STATIC_VALID, CandidateLifecycle.PROBATIONARY)
        )
        recovery_candidate = (
            operator_recovery
            and recovery_target_is_current(
                self.repository,
                candidate,
                expected_last_failure_at=str(values.get("expected_last_failure_at") or ""),
                now=now,
            )
        )
        if (
            route.generation != int(values["expected_route_generation"])
            or candidate.generation != int(values["expected_candidate_generation"])
            or candidate.route_id != route_id
            or not (standard_candidate or recovery_candidate)
            or binding.route_id != route_id
            or binding.status != "ready"
            or binding.binding_version != int(values["binding_version"])
            or binding.target_fingerprint != str(values["target_fingerprint"])
        ):
            raise ActorOpsConflict("maintenance target changed before probe")
        budget = self.probe_budget(route_id, now)
        if budget.probe_count >= min(int(policy.route.max_probes_per_utc_day or 0), MAX_PROBES_PER_DAY):
            raise ActorOpsConflict("actorops_maintenance_daily_probe_limit")
        if budget.spent_usd + budget.reserved_usd + reserved > min(float(policy.workspace.monthly_budget_usd or 0), MAX_MONTHLY_USD):
            raise ActorOpsConflict("actorops_maintenance_monthly_budget_exhausted")
        pending = self.repository.connection.execute(
            """SELECT 1 FROM actor_attempts_v2
               WHERE workspace_id=? AND route_id=? AND kind='probe'
                 AND (status NOT IN ('succeeded','failed','cancelled') OR cost_final=0)
               LIMIT 1""",
            (self.repository.workspace_id, route_id),
        ).fetchone()
        if pending is not None:
            raise ActorOpsConflict("actorops_maintenance_probe_reconciliation_required")
        self.repository.create_attempt(
            attempt_id=str(values["attempt_id"]), idempotency_key=str(values["idempotency_key"]),
            route_id=route_id, source_id=str(values["source_id"]),
            candidate_id=str(values["candidate_id"]), kind="probe",
            attempt_group_id=str(values["attempt_group_id"]), attempt_index=0,
            route_generation=route.generation, binding_version=binding.binding_version,
            target_fingerprint=binding.target_fingerprint, reserved_usd=reserved,
            created_at=now.isoformat(),
            logical_job_id=str(
                values.get("logical_job_id") or values["attempt_group_id"]
            ),
            request_fingerprint=str(
                values.get("request_fingerprint") or values["idempotency_key"]
            ),
            window_since=str(values.get("window_since") or now.isoformat()),
            window_until=values.get("window_until"),
            max_items=int(values.get("max_items") or 1),
        )

    def successful_probe_targets(self, candidate_id: str) -> int:
        return int(self.repository.connection.execute(
            """SELECT COUNT(*) FROM actor_source_bindings_v2 AS binding
               JOIN actor_candidates_v2 AS candidate
                 ON candidate.workspace_id=binding.workspace_id
                AND candidate.route_id=binding.route_id
              WHERE binding.workspace_id=? AND candidate.candidate_id=?
                AND binding.status='ready' AND EXISTS (
                    SELECT 1 FROM actor_attempts_v2 AS attempt
                     WHERE attempt.workspace_id=binding.workspace_id
                       AND attempt.candidate_id=candidate.candidate_id
                       AND attempt.source_id=binding.source_id
                       AND attempt.binding_version=binding.binding_version
                       AND attempt.target_fingerprint=binding.target_fingerprint
                       AND attempt.kind='probe' AND attempt.status='succeeded'
                       AND attempt.semantic_outcome='valid_nonempty'
                       AND attempt.cost_final=1
                )""",
            (self.repository.workspace_id, candidate_id),
        ).fetchone()[0])

    def reconcile_settled_candidates(self, route_id: str) -> int:
        """Apply already-settled Probe evidence without another remote call."""

        policy = self.effective_policy(route_id)
        if not policy.authorized:
            return 0
        changed = 0
        for candidate in self.repository.list_route_candidates(route_id):
            try:
                current = apply_settled_recovery_success(
                    self.repository, candidate.candidate_id
                )
            except ActorOpsConflict:
                current = None
            if current is not None:
                changed += 1
                candidate = current
            proofs = self.successful_probe_targets(candidate.candidate_id)
            target: CandidateLifecycle | None = None
            if candidate.lifecycle is CandidateLifecycle.STATIC_VALID and proofs >= 1:
                target = CandidateLifecycle.PROBATIONARY
            elif candidate.lifecycle is CandidateLifecycle.PROBATIONARY and proofs >= 2:
                target = CandidateLifecycle.CERTIFIED
            if target is None:
                continue
            try:
                with self.repository.transaction():
                    current = self.repository.get_candidate(candidate.candidate_id)
                    if current.lifecycle is not candidate.lifecycle:
                        continue
                    if current.lifecycle is CandidateLifecycle.STATIC_VALID:
                        current = self.repository.record_candidate_outcome(
                            current.candidate_id,
                            expected_generation=current.generation,
                            succeeded=True,
                        )
                    current = self.repository.transition_candidate(
                        current.candidate_id,
                        current.lifecycle,
                        target,
                        expected_generation=current.generation,
                    )
                changed += 1
            except ActorOpsConflict:
                continue
            if (
                current.assignment_role is AssignmentRole.INACTIVE
                and policy.route.auto_add_standby
            ):
                try:
                    with self.repository.transaction():
                        route = self.repository.get_route(route_id)
                        current = self.repository.get_candidate(current.candidate_id)
                        self.add_standby(
                            route_id,
                            current.candidate_id,
                            expected_route_generation=route.generation,
                            expected_candidate_generation=current.generation,
                        )
                except ActorOpsConflict:
                    continue
        return changed

    def due_routes(self, *, limit: int = 20) -> tuple[str, ...]:
        rows = self.repository.connection.execute(
            """SELECT route.route_id FROM actor_routes_v2 AS route
               JOIN actor_maintenance_policies_v2 AS workspace_policy
                 ON workspace_policy.workspace_id=route.workspace_id
                AND workspace_policy.route_id IS NULL
               JOIN actor_maintenance_policies_v2 AS route_policy
                 ON route_policy.workspace_id=route.workspace_id
                AND route_policy.route_id=route.route_id
               WHERE route.workspace_id=? AND workspace_policy.enabled=1
                 AND route_policy.enabled=1
                 AND workspace_policy.authorization_origin!='none'
                 AND route_policy.authorization_origin!='none'
               ORDER BY route.route_id LIMIT ?""",
            (self.repository.workspace_id, min(max(int(limit), 1), 100)),
        ).fetchall()
        return tuple(str(row[0]) for row in rows)

    def probe_target(self, route_id: str):
        """Choose one Candidate and one still-unproved Binding atomically.

        Candidate-first selection can permanently starve later Candidates on a
        single-Binding Route: after the first proof the chosen Candidate has no
        Binding left, but remains the first candidate forever.  Selecting the
        pair together guarantees every returned target can make progress.
        """

        return select_probe_target(
            self.repository, route_id,
            successful_probe_targets=self.successful_probe_targets,
        )

    def unhealthy_assigned(self, route_id: str) -> tuple[str, ...]:
        assigned = tuple(
            item
            for item in self.repository.list_route_candidates(route_id)
            if item.assignment_role in {AssignmentRole.ACTIVE, AssignmentRole.STANDBY}
        )
        states = candidate_operational_states(self.repository, assigned)
        ordered = sorted(
            assigned,
            key=lambda item: (
                item.assignment_role is AssignmentRole.STANDBY,
                item.priority or 0,
                item.candidate_id,
            ),
        )
        return tuple(
            item.candidate_id
            for item in ordered
            if states[item.candidate_id].confirmed_failure
        )

    def protect_last_unhealthy(self, route_id: str) -> str | None:
        assigned = [
            item for item in self.repository.list_route_candidates(route_id)
            if item.assignment_role is not AssignmentRole.INACTIVE
            and candidate_is_runnable(item)
        ]
        if len(assigned) != 1 or not self.unhealthy_assigned(route_id):
            return None
        candidate = assigned[0]
        with self.repository.transaction():
            self.repository.record_candidate_outcome(
                candidate.candidate_id, expected_generation=candidate.generation,
                succeeded=False, error_class="candidate",
                error_code="actorops_maintenance_last_candidate_protected",
            )
        return "actorops_maintenance_last_candidate_protected"

    def add_standby(self, route_id: str, candidate_id: str, *, expected_route_generation: int, expected_candidate_generation: int) -> bool:
        assigned = [item for item in self.repository.list_route_candidates(route_id)
                    if item.assignment_role is not AssignmentRole.INACTIVE]
        active = next((item for item in assigned if item.assignment_role is AssignmentRole.ACTIVE), None)
        if active is None or (
            len(assigned) >= 2
            and not self.repository.resilience.allows_repair_headroom(
                route_id, candidate_id
            )
        ) or len(assigned) >= 3:
            return False
        self.repository.assign_candidate(
            route_id, candidate_id, AssignmentRole.STANDBY,
            priority=max((int(item.priority or 0) for item in assigned), default=0) + 1,
            expected_route_generation=expected_route_generation,
            expected_candidate_generation=expected_candidate_generation,
        )
        return True

    def replace_unhealthy_non_last(
        self,
        route_id: str,
        candidate_id: str,
        *,
        expected_route_generation: int,
        expected_candidate_generation: int,
    ) -> bool:
        """Quarantine one unhealthy assigned Candidate without losing the last path."""

        self.repository._require_transaction()
        policy = self.effective_policy(route_id)
        route = self.repository.get_route(route_id)
        replacement = self.repository.get_candidate(candidate_id)
        binding_count = int(self.repository.connection.execute(
            """SELECT COUNT(*) FROM actor_source_bindings_v2
               WHERE workspace_id=? AND route_id=? AND status='ready'""",
            (self.repository.workspace_id, route_id),
        ).fetchone()[0])
        required_proofs = min(2, binding_count)
        if (
            not policy.authorized or not policy.route.auto_replace_non_last
            or route.generation != expected_route_generation
            or replacement.generation != expected_candidate_generation
            or replacement.route_id != route_id
            or replacement.assignment_role is not AssignmentRole.INACTIVE
            or not candidate_is_runnable(replacement)
        ):
            raise ActorOpsConflict("actorops_maintenance_replacement_changed")
        if (
            required_proofs == 0
            or self.successful_probe_targets(candidate_id) < required_proofs
            or not _route_capabilities_proven(route, replacement)
        ):
            return False
        assigned = [
            item for item in self.repository.list_route_candidates(route_id)
            if item.assignment_role is not AssignmentRole.INACTIVE
            and candidate_is_runnable(item)
        ]
        unhealthy = self.unhealthy_assigned(route_id)
        victims = [item for item in assigned if item.candidate_id in unhealthy]
        if not victims:
            return False
        if len(assigned) == 1:
            self.protect_last_unhealthy(route_id)
            return False
        victim = victims[0]
        self.repository.transition_candidate(
            victim.candidate_id, victim.lifecycle, CandidateLifecycle.QUARANTINED,
            expected_generation=victim.generation, error_class="candidate",
            error_code="actorops_maintenance_replaced_unhealthy",
        )
        remaining = [item for item in assigned if item.candidate_id != victim.candidate_id]
        active = next(
            (item for item in remaining if item.assignment_role is AssignmentRole.ACTIVE),
            None,
        )
        if active is None:
            active = min(remaining, key=lambda item: (int(item.priority or 0), item.candidate_id))
        standby = [item for item in remaining if item.candidate_id != active.candidate_id]
        standby.append(replacement)
        self._reassign(route_id, route.generation, active, standby)
        return True

    def _reassign(self, route_id: str, route_generation: int, active: Any, standby: list[Any]) -> None:
        """Temporarily clear roles, then install a unique active/standby ordering."""

        stamp = _stamp(None)
        current = [
            item for item in self.repository.list_route_candidates(route_id)
            if item.assignment_role is not AssignmentRole.INACTIVE
        ]
        for item in current:
            changed = self.repository.connection.execute(
                """UPDATE actor_candidates_v2 SET assignment_role='inactive', priority=NULL,
                   generation=generation+1, updated_at=?
                   WHERE workspace_id=? AND candidate_id=? AND generation=?""",
                (stamp, self.repository.workspace_id, item.candidate_id, item.generation),
            ).rowcount
            if changed != 1:
                raise ActorOpsConflict("candidate changed before maintenance reassignment")
        for role, priority, item in [
            (AssignmentRole.ACTIVE, 0, active),
            *[(AssignmentRole.STANDBY, index, item) for index, item in enumerate(standby, 1)],
        ]:
            current = self.repository.get_candidate(item.candidate_id)
            changed = self.repository.connection.execute(
                """UPDATE actor_candidates_v2 SET assignment_role=?, priority=?,
                   generation=generation+1, updated_at=?
                   WHERE workspace_id=? AND candidate_id=? AND generation=?""",
                (role.value, priority, stamp, self.repository.workspace_id,
                 current.candidate_id, current.generation),
            ).rowcount
            if changed != 1:
                raise ActorOpsConflict("candidate changed before maintenance reassignment")
        changed = self.repository.connection.execute(
            """UPDATE actor_routes_v2 SET generation=generation+1, updated_at=?
               WHERE workspace_id=? AND route_id=? AND generation=?""",
            (stamp, self.repository.workspace_id, route_id, route_generation),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("route changed before maintenance reassignment")


def _policy(row: Any) -> MaintenancePolicyRecord:
    return MaintenancePolicyRecord(
        policy_id=str(row["policy_id"]), workspace_id=str(row["workspace_id"]),
        route_id=str(row["route_id"]) if row["route_id"] is not None else None,
        enabled=bool(row["enabled"]), monthly_budget_usd=row["monthly_budget_usd"],
        max_probe_usd=row["max_probe_usd"], max_probes_per_utc_day=row["max_probes_per_utc_day"],
        auto_add_standby=bool(row["auto_add_standby"]) if row["auto_add_standby"] is not None else None,
        auto_replace_non_last=bool(row["auto_replace_non_last"]) if row["auto_replace_non_last"] is not None else None,
        generation=int(row["generation"]), authorized_by_user_id=row["authorized_by_user_id"],
        authorized_at=row["authorized_at"],
        authorization_origin=str(row["authorization_origin"]),
    )


def _route_capabilities_proven(route: Any, candidate: Any) -> bool:
    if route.route_key.platform != "youtube":
        return True
    try:
        value = json.loads(str(candidate.manifest_json or ""))
    except (TypeError, ValueError, json.JSONDecodeError):
        return False
    inputs = value.get("input") if isinstance(value, dict) else None
    return bool(
        isinstance(inputs, dict) and proves_combined_latest_items(inputs)
    )


def _utc(value: datetime) -> datetime:
    return value.replace(tzinfo=timezone.utc) if value.tzinfo is None else value.astimezone(timezone.utc)


def _stamp(value: datetime | None) -> str:
    return _utc(value or datetime.now(timezone.utc)).isoformat()


__all__ = ["EffectiveMaintenancePolicy", "MaintenanceRepository"]
