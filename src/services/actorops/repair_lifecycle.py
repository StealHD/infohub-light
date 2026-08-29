"""Durable, progress-guaranteed ActorOps route repair lifecycle."""

from __future__ import annotations

import hashlib
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from .domain import AssignmentRole, CandidateLifecycle, RouteHealth
from .policy import candidate_has_exact_execution_contract, candidate_is_runnable
from .repository_errors import ActorOpsConflict, ActorOpsNotFound
from .repository_maintenance import MAX_MONTHLY_USD, MAX_PROBES_PER_DAY
from .runtime_candidate_health import (
    candidate_operational_states,
    operational_route_summary,
)


_OPEN = ("queued", "discovering", "awaiting_probe", "blocked")
_BACKOFF_MINUTES = (30, 120, 360, 1440)
_ADMISSION_BLOCKERS = frozenset({
    "actorops_repair_not_authorized",
    "actorops_repair_daily_probe_limit",
    "actorops_repair_monthly_budget_exhausted",
    "actorops_repair_cost_settlement_required",
})
_PROBE_LIFECYCLES = {
    CandidateLifecycle.STATIC_VALID,
    CandidateLifecycle.PROBATIONARY,
    CandidateLifecycle.CERTIFIED,
}
_UNSET = object()


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


class RepairLifecycle:
    """Own Repair admission, recovery, discovery rotation, and event wakeups."""

    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def ensure(
        self,
        *,
        route_id: str,
        source_id: str,
        origin_job_id: str,
        trigger_code: str,
        blocked_code: str | None = None,
    ) -> dict[str, Any]:
        with self.repository.transaction():
            existing = self._open_repair(route_id, source_id)
            status, error = self._admission(route_id, blocked_code)
            if existing is not None:
                self._sync_admission(existing, status=status, error_code=error)
                repair_id = str(existing["repair_id"])
            else:
                repair_id = self._insert(
                    route_id=route_id,
                    source_id=source_id,
                    origin_job_id=origin_job_id,
                    trigger_code=trigger_code,
                    status=status,
                    error_code=error,
                )
        return dict(self.get(repair_id))

    def get(self, repair_id: str) -> Any:
        row = self.repository.connection.execute(
            "SELECT * FROM actor_route_repairs_v2 WHERE workspace_id=? AND repair_id=?",
            (self.repository.workspace_id, repair_id),
        ).fetchone()
        if row is None:
            raise ActorOpsConflict("ActorOps repair is missing")
        return row

    def due(self, *, limit: int = 20) -> tuple[Any, ...]:
        return tuple(self.repository.connection.execute(
            """SELECT * FROM actor_route_repairs_v2 WHERE workspace_id=?
                 AND status IN ('queued','discovering','awaiting_probe','blocked')
                 AND (next_attempt_at IS NULL OR next_attempt_at<=?)
                 ORDER BY updated_at, repair_id LIMIT ?""",
            (self.repository.workspace_id, _stamp(), min(max(int(limit), 1), 50)),
        ).fetchall())

    def advance(self, repair_id: str) -> dict[str, Any]:
        repair = self.get(repair_id)
        if str(repair["status"]) not in _OPEN:
            return dict(repair)
        admission, error = self._admission(str(repair["route_id"]), None)
        if admission == "blocked":
            return self._block(repair, str(error))
        if (
            str(repair["status"]) == "blocked"
            and str(repair["error_code"] or "") in _ADMISSION_BLOCKERS
        ):
            repair = self._update(
                repair,
                status="queued",
                attempt_count=0,
            )
        recovered = self._recover_if_stable(repair)
        if recovered is not None:
            return recovered
        repair = self.get(repair_id)
        candidate = self._probe_candidate(repair["candidate_id"], str(repair["route_id"]))
        if candidate is not None:
            return self._update(
                repair,
                status="awaiting_probe",
                candidate_id=candidate.candidate_id,
                delay_minutes=5,
            )
        if repair["discovery_id"]:
            return self._advance_discovery(repair)
        return self._start_discovery(repair)

    def allows_headroom(self, route_id: str, candidate_id: str) -> bool:
        return self.repository.connection.execute(
            """SELECT 1 FROM actor_route_repairs_v2 WHERE workspace_id=? AND route_id=?
                 AND candidate_id=? AND status='awaiting_probe' LIMIT 1""",
            (self.repository.workspace_id, route_id, candidate_id),
        ).fetchone() is not None

    def route_repairs(self, route_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.repository.connection.execute(
            """SELECT repair_id, source_id, origin_job_id, trigger_code, status,
                      discovery_id, candidate_id, error_code, attempt_count,
                      created_at, updated_at, terminal_at
                 FROM actor_route_repairs_v2 WHERE workspace_id=? AND route_id=?
                 ORDER BY updated_at DESC, repair_id DESC LIMIT ?""",
            (self.repository.workspace_id, route_id, min(max(int(limit), 1), 50)),
        ).fetchall()
        return [dict(row) for row in rows]

    def wake_repairs_after_cost_settlement(self, route_id: str, source_id: str) -> int:
        del source_id
        return self._wake(
            """route_id=?
               AND error_code='actorops_repair_cost_settlement_required'""",
            (route_id,),
        )

    def wake_repairs_after_discovery(self, discovery_id: str) -> int:
        return self._wake("discovery_id=?", (discovery_id,))

    def _advance_discovery(self, repair: Any) -> dict[str, Any]:
        try:
            discovery = self.repository.discovery.get(str(repair["discovery_id"]))
        except ActorOpsNotFound:
            return self._block(
                repair,
                "actorops_repair_discovery_missing",
                clear_discovery=True,
                clear_candidate=True,
            )
        status = str(discovery["status"])
        if status == "completed":
            candidate = self._accepted_probe_candidate(
                str(discovery["discovery_id"]), str(repair["route_id"])
            )
            if candidate is not None:
                return self._update(
                    repair,
                    status="awaiting_probe",
                    candidate_id=candidate.candidate_id,
                    delay_minutes=5,
                )
            return self._block(
                repair,
                "actorops_repair_no_candidate",
                clear_discovery=True,
                clear_candidate=True,
            )
        if status in {"failed", "cancelled"}:
            return self._block(
                repair,
                "actorops_repair_discovery_failed",
                clear_discovery=True,
                clear_candidate=True,
            )
        return self._update(
            repair,
            status="discovering",
            candidate_id=None,
            delay_minutes=5,
        )

    def _start_discovery(self, repair: Any) -> dict[str, Any]:
        route = self.repository.get_route(str(repair["route_id"]))
        discovery_id = f"repair-discovery-{uuid.uuid4().hex}"
        digest = hashlib.sha256(
            f"repair\x1f{repair['repair_id']}\x1f{discovery_id}".encode()
        ).hexdigest()
        with self.repository.transaction():
            current = self.get(str(repair["repair_id"]))
            if (
                str(current["status"]) not in _OPEN
                or str(current["updated_at"]) != str(repair["updated_at"])
            ):
                raise ActorOpsConflict("ActorOps repair changed before discovery")
            row, _created = self.repository.discovery.ensure(
                discovery_id=discovery_id,
                idempotency_key=digest,
                route_id=str(repair["route_id"]),
                trigger_reason="production_exhausted",
                input_fingerprint=hashlib.sha256(str(route.route_key).encode()).hexdigest(),
            )
            self._write_update(
                current,
                status="discovering",
                discovery_id=str(row["discovery_id"]),
                candidate_id=None,
                delay_minutes=5,
                attempt_count=int(current["attempt_count"] or 0),
            )
        return dict(self.get(str(repair["repair_id"])))

    def _accepted_probe_candidate(self, discovery_id: str, route_id: str) -> Any | None:
        for candidate_id in self.repository.discovery.list_accepted_candidate_ids(discovery_id):
            candidate = self._probe_candidate(candidate_id, route_id)
            if candidate is not None:
                return candidate
        return None

    def _probe_candidate(self, candidate_id: Any, route_id: str) -> Any | None:
        if not candidate_id:
            return None
        try:
            candidate = self.repository.get_candidate(str(candidate_id))
        except Exception:
            return None
        if (
            candidate.route_id != route_id
            or candidate.assignment_role is not AssignmentRole.INACTIVE
            or candidate.lifecycle not in _PROBE_LIFECYCLES
            or not candidate_has_exact_execution_contract(candidate)
        ):
            return None
        state = candidate_operational_states(self.repository, (candidate,))[candidate.candidate_id]
        return None if state.confirmed_failure else candidate

    def _stable_recovery_candidate(self, repair: Any) -> Any | None:
        route_id = str(repair["route_id"])
        candidates = tuple(self.repository.list_route_candidates(route_id))
        summary = operational_route_summary(
            self.repository,
            candidates,
            route_id=route_id,
            source_id=str(repair["source_id"]),
        )
        if summary.health is not RouteHealth.HEALTHY:
            return None
        binding = self.repository.get_binding(str(repair["source_id"]))
        states = candidate_operational_states(self.repository, candidates)
        eligible = [
            item
            for item in candidates
            if candidate_is_runnable(item)
            and states[item.candidate_id].status == "normal"
            and states[item.candidate_id].stable
            and (
                item.assignment_role is not AssignmentRole.INACTIVE
                or item.candidate_id == binding.last_known_good_candidate_id
            )
        ]
        eligible.sort(key=lambda item: (
            item.candidate_id != binding.preferred_candidate_id,
            item.assignment_role is not AssignmentRole.ACTIVE,
            int(item.priority or 0),
            item.candidate_id,
        ))
        return eligible[0] if eligible else None

    def _recover_if_stable(self, repair: Any) -> dict[str, Any] | None:
        with self.repository.transaction():
            current = self.get(str(repair["repair_id"]))
            if (
                str(current["status"]) not in _OPEN
                or str(current["updated_at"]) != str(repair["updated_at"])
            ):
                raise ActorOpsConflict("ActorOps repair changed before recovery")
            candidate = self._stable_recovery_candidate(current)
            if candidate is None:
                return None
            binding = self.repository.get_binding(str(current["source_id"]))
            changed = self.repository.connection.execute(
                """UPDATE actor_source_bindings_v2
                      SET preferred_candidate_id=?, updated_at=?
                    WHERE workspace_id=? AND source_id=? AND binding_version=?""",
                (
                    candidate.candidate_id,
                    _stamp(),
                    self.repository.workspace_id,
                    binding.source_id,
                    binding.binding_version,
                ),
            ).rowcount
            if changed != 1:
                raise ActorOpsConflict("binding changed before repair recovery")
            self._write_update(
                current,
                status="recovered",
                candidate_id=candidate.candidate_id,
                attempt_count=0,
                terminal=True,
            )
        return dict(self.get(str(repair["repair_id"])))

    def _admission(
        self, route_id: str, blocked_code: str | None
    ) -> tuple[str, str | None]:
        if blocked_code:
            return "blocked", blocked_code
        policy = self.repository.maintenance.effective_policy(route_id)
        if not policy.authorized:
            return "blocked", "actorops_repair_not_authorized"
        budget = self.repository.maintenance.probe_budget(route_id, _now())
        daily_cap = min(int(policy.route.max_probes_per_utc_day or 0), MAX_PROBES_PER_DAY)
        if daily_cap <= 0 or budget.probe_count >= daily_cap:
            return "blocked", "actorops_repair_daily_probe_limit"
        monthly_cap = min(float(policy.workspace.monthly_budget_usd or 0), MAX_MONTHLY_USD)
        if (
            policy.max_charge_usd <= 0
            or budget.spent_usd + budget.reserved_usd + policy.max_charge_usd > monthly_cap
        ):
            return "blocked", "actorops_repair_monthly_budget_exhausted"
        pending = self.repository.connection.execute(
            """SELECT 1 FROM actor_attempts_v2 WHERE workspace_id=? AND route_id=?
                 AND kind='fetch'
                 AND (status NOT IN ('succeeded','failed','cancelled') OR cost_final=0)
                 LIMIT 1""",
            (self.repository.workspace_id, route_id),
        ).fetchone()
        if pending is not None:
            return "blocked", "actorops_repair_cost_settlement_required"
        return "queued", None

    def _open_repair(self, route_id: str, source_id: str) -> Any | None:
        placeholders = ",".join("?" for _ in _OPEN)
        return self.repository.connection.execute(
            f"""SELECT * FROM actor_route_repairs_v2 WHERE workspace_id=?
                  AND route_id=? AND source_id=? AND status IN ({placeholders})
                  ORDER BY created_at DESC LIMIT 1""",
            (self.repository.workspace_id, route_id, source_id, *_OPEN),
        ).fetchone()

    def _insert(self, **values: Any) -> str:
        stamp = _stamp()
        repair_id = f"repair-{uuid.uuid4().hex}"
        blocked = values["status"] == "blocked"
        self.repository.connection.execute(
            """INSERT INTO actor_route_repairs_v2 (
                   repair_id, workspace_id, route_id, source_id, origin_job_id,
                   trigger_code, status, error_code, attempt_count,
                   next_attempt_at, created_at, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?)""",
            (
                repair_id,
                self.repository.workspace_id,
                values["route_id"],
                values["source_id"],
                values["origin_job_id"] or None,
                values["trigger_code"],
                values["status"],
                values["error_code"],
                1 if blocked else 0,
                _stamp(_now() + timedelta(minutes=30)) if blocked else stamp,
                stamp,
                stamp,
            ),
        )
        return repair_id

    def _sync_admission(
        self, repair: Any, *, status: str, error_code: str | None
    ) -> None:
        current = str(repair["status"])
        if (
            status == "queued"
            and current == "blocked"
            and str(repair["error_code"] or "") in _ADMISSION_BLOCKERS
        ):
            self._write_update(
                repair,
                status="queued",
                error_code=None,
                next_attempt_at=_stamp(),
                attempt_count=0,
            )
        elif status == "blocked" and (
            current != "blocked" or str(repair["error_code"] or "") != str(error_code or "")
        ):
            self._write_update(
                repair,
                status="blocked",
                error_code=error_code,
                next_attempt_at=_stamp(_now() + timedelta(minutes=30)),
                attempt_count=1,
            )

    def _block(
        self,
        repair: Any,
        error_code: str,
        *,
        clear_discovery: bool = False,
        clear_candidate: bool = False,
    ) -> dict[str, Any]:
        count = int(repair["attempt_count"] or 0) + 1
        delay = _BACKOFF_MINUTES[min(count - 1, len(_BACKOFF_MINUTES) - 1)]
        return self._update(
            repair,
            status="blocked",
            error_code=error_code,
            discovery_id=None if clear_discovery else _UNSET,
            candidate_id=None if clear_candidate else _UNSET,
            delay_minutes=delay,
            attempt_count=count,
        )

    def _update(
        self,
        repair: Any,
        *,
        status: str,
        error_code: str | None = None,
        discovery_id: str | None | object = _UNSET,
        candidate_id: str | None | object = _UNSET,
        delay_minutes: int | None = None,
        attempt_count: int | object = _UNSET,
        terminal: bool = False,
    ) -> dict[str, Any]:
        with self.repository.transaction():
            self._write_update(
                repair,
                status=status,
                error_code=error_code,
                discovery_id=discovery_id,
                candidate_id=candidate_id,
                delay_minutes=delay_minutes,
                attempt_count=attempt_count,
                terminal=terminal,
            )
        return dict(self.get(str(repair["repair_id"])))

    def _write_update(
        self,
        repair: Any,
        *,
        status: str,
        error_code: str | None = None,
        discovery_id: str | None | object = _UNSET,
        candidate_id: str | None | object = _UNSET,
        delay_minutes: int | None = None,
        next_attempt_at: str | None = None,
        attempt_count: int | object = _UNSET,
        terminal: bool = False,
    ) -> None:
        stamp = _stamp()
        discovery = repair["discovery_id"] if discovery_id is _UNSET else discovery_id
        candidate = repair["candidate_id"] if candidate_id is _UNSET else candidate_id
        attempts = (
            int(repair["attempt_count"] or 0)
            if attempt_count is _UNSET
            else int(attempt_count)
        )
        next_at = next_attempt_at
        if next_at is None and delay_minutes is not None:
            next_at = _stamp(_now() + timedelta(minutes=delay_minutes))
        changed = self.repository.connection.execute(
            """UPDATE actor_route_repairs_v2
                  SET status=?, error_code=?, discovery_id=?, candidate_id=?,
                      attempt_count=?, next_attempt_at=?, terminal_at=?, updated_at=?
                WHERE workspace_id=? AND repair_id=? AND status=? AND updated_at=?""",
            (
                status,
                error_code,
                discovery,
                candidate,
                attempts,
                next_at,
                stamp if terminal else None,
                stamp,
                self.repository.workspace_id,
                repair["repair_id"],
                repair["status"],
                repair["updated_at"],
            ),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("ActorOps repair changed before update")

    def _wake(self, clause: str, params: tuple[str, ...]) -> int:
        stamp = _stamp()
        with self.repository.transaction():
            changed = self.repository.connection.execute(
                f"""UPDATE actor_route_repairs_v2 SET next_attempt_at=?, updated_at=?
                      WHERE workspace_id=? AND status IN ('queued','discovering','awaiting_probe','blocked')
                        AND {clause}""",
                (stamp, stamp, self.repository.workspace_id, *params),
            ).rowcount
        return int(changed)


__all__ = ["RepairLifecycle"]
