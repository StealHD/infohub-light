"""Durable source freshness, automatic repair, and safe execution tracing."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from dataclasses import dataclass
from datetime import datetime, timedelta, timezone
from typing import Any

from ..operation_log import safe_emit_operation_event
from .domain import AssignmentRole, CandidateLifecycle
from .repository_errors import ActorOpsConflict
from .repository_maintenance import MAX_MONTHLY_USD, MAX_PROBES_PER_DAY


_SAFE = re.compile(r"^[a-z][a-z0-9_]{1,95}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
_OPEN_REPAIRS = ("queued", "discovering", "awaiting_probe", "blocked")
_HARD_FAILURES = {
    "apify_actor_deleted",
    "apify_actor_build_unavailable",
    "actorops_v2_candidate_contract_invalid",
}


@dataclass(frozen=True, slots=True)
class FreshnessPlan:
    candidates: tuple[Any, ...]
    primary_candidate_id: str | None = None
    cross_check: bool = False


def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


class ResilienceRepository:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def is_natural_schedule(self, logical_job_id: str) -> bool:
        row = self.repository.connection.execute(
            "SELECT payload_json FROM fetch_jobs WHERE workspace_id=? AND id=?",
            (self.repository.workspace_id, str(logical_job_id)),
        ).fetchone()
        if row is None:
            return False
        try:
            payload = json.loads(str(row["payload_json"] or "{}"))
        except (TypeError, ValueError):
            return False
        return isinstance(payload, dict) and payload.get("reason") == "scheduled_source_fetch"

    def plan_candidates(
        self, *, binding: Any, candidates: tuple[Any, ...], natural_schedule: bool
    ) -> FreshnessPlan:
        if not candidates:
            return FreshnessPlan(())
        primary = candidates[0]
        fresh = self._freshness(binding.source_id, primary.candidate_id, binding.binding_version)
        alternatives = tuple(item for item in candidates if item.candidate_id != primary.candidate_id)
        if natural_schedule and fresh and int(fresh["consecutive_scheduled_no_advance"]) >= 3 and alternatives:
            return FreshnessPlan(
                candidates=(alternatives[0], primary, *alternatives[1:]),
                primary_candidate_id=primary.candidate_id,
                cross_check=True,
            )
        available = tuple(
            item for item in candidates
            if not self._source_cooldown(binding, item.candidate_id)
        )
        return FreshnessPlan(available or candidates)

    def record_regular_result(
        self, *, binding: Any, candidate_id: str, outcome: str,
        logical_job_id: str, natural_schedule: bool,
    ) -> None:
        if not natural_schedule:
            return
        if outcome == "no_advance":
            previous = self._freshness(binding.source_id, candidate_id, binding.binding_version)
            count = int(previous["consecutive_scheduled_no_advance"]) + 1 if previous else 1
            state = "suspected_stale" if count >= 3 else "neutral"
            self._upsert_freshness(
                binding=binding, candidate_id=candidate_id, count=count, state=state,
                outcome=outcome, job_id=logical_job_id,
            )
        elif outcome == "advanced":
            self._upsert_freshness(
                binding=binding, candidate_id=candidate_id, count=0, state="neutral",
                outcome=outcome, job_id=logical_job_id,
            )

    def record_cross_check(
        self, *, binding: Any, primary_candidate_id: str, candidate_id: str,
        outcome: str, logical_job_id: str,
    ) -> str:
        if outcome == "no_advance":
            self._upsert_freshness(
                binding=binding, candidate_id=primary_candidate_id, count=0,
                state="confirmed_no_change", outcome=outcome, job_id=logical_job_id,
                confirmed=True,
            )
            self._upsert_freshness(
                binding=binding, candidate_id=candidate_id, count=0,
                state="confirmed_no_change", outcome=outcome, job_id=logical_job_id,
                confirmed=True,
            )
            return "confirmed_no_change"
        if outcome == "advanced":
            cooldown = _now() + timedelta(hours=6)
            self._upsert_freshness(
                binding=binding, candidate_id=primary_candidate_id, count=0,
                state="source_stale", outcome=outcome, job_id=logical_job_id,
                cooldown_until=_stamp(cooldown), confirmed=True,
            )
            self._upsert_freshness(
                binding=binding, candidate_id=candidate_id, count=0,
                state="neutral", outcome=outcome, job_id=logical_job_id,
            )
            with self.repository.transaction():
                changed = self.repository.connection.execute(
                    """UPDATE actor_source_bindings_v2 SET preferred_candidate_id=?, updated_at=?
                       WHERE workspace_id=? AND source_id=? AND binding_version=?""",
                    (candidate_id, _stamp(), self.repository.workspace_id,
                     binding.source_id, binding.binding_version),
                ).rowcount
                if changed != 1:
                    raise ActorOpsConflict("binding changed before freshness preference")
            self._maybe_globally_demote(primary_candidate_id)
            return "source_stale"
        return "unverified"

    def ensure_repair(
        self, *, route_id: str, source_id: str, origin_job_id: str,
        trigger_code: str, blocked_code: str | None = None,
    ) -> dict[str, Any]:
        existing = self.repository.connection.execute(
            f"""SELECT * FROM actor_route_repairs_v2 WHERE workspace_id=? AND route_id=?
                AND source_id=? AND status IN ({','.join('?' for _ in _OPEN_REPAIRS)})
                ORDER BY created_at DESC LIMIT 1""",
            (self.repository.workspace_id, route_id, source_id, *_OPEN_REPAIRS),
        ).fetchone()
        if existing is not None:
            return dict(existing)
        status, error = self._repair_admission(route_id, blocked_code)
        stamp = _stamp()
        repair_id = f"repair-{uuid.uuid4().hex}"
        with self.repository.transaction():
            self.repository.connection.execute(
                """INSERT INTO actor_route_repairs_v2 (
                       repair_id, workspace_id, route_id, source_id, origin_job_id,
                       trigger_code, status, error_code, next_attempt_at, created_at, updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?)""",
                (repair_id, self.repository.workspace_id, route_id, source_id,
                 origin_job_id or None, trigger_code, status, error,
                 _stamp(_now() + timedelta(minutes=10)) if status == "blocked" else stamp,
                 stamp, stamp),
            )
        return dict(self.get_repair(repair_id))

    def get_repair(self, repair_id: str) -> Any:
        row = self.repository.connection.execute(
            "SELECT * FROM actor_route_repairs_v2 WHERE workspace_id=? AND repair_id=?",
            (self.repository.workspace_id, repair_id),
        ).fetchone()
        if row is None:
            raise ActorOpsConflict("ActorOps repair is missing")
        return row

    def due_repairs(self, *, limit: int = 20) -> tuple[Any, ...]:
        now = _stamp()
        return tuple(self.repository.connection.execute(
            """SELECT * FROM actor_route_repairs_v2 WHERE workspace_id=?
                 AND status IN ('queued','discovering','awaiting_probe','blocked')
                 AND (next_attempt_at IS NULL OR next_attempt_at<=?)
                 ORDER BY updated_at, repair_id LIMIT ?""",
            (self.repository.workspace_id, now, min(max(int(limit), 1), 50)),
        ).fetchall())

    def advance_repair(self, repair_id: str) -> dict[str, Any]:
        repair = self.get_repair(repair_id)
        admission, error = self._repair_admission(str(repair["route_id"]), None)
        if admission == "blocked":
            return self._update_repair(repair, status="blocked", error_code=error, delay_minutes=30)
        source_id, route_id = str(repair["source_id"]), str(repair["route_id"])
        candidate = self._usable_repair_candidate(repair)
        if candidate is not None and candidate.assignment_role is not AssignmentRole.INACTIVE:
            self._set_binding_preference(source_id, candidate.candidate_id)
            return self._update_repair(repair, status="recovered", candidate_id=candidate.candidate_id, terminal=True)
        if candidate is not None:
            return self._update_repair(repair, status="awaiting_probe", candidate_id=candidate.candidate_id, delay_minutes=5)
        discovery_id = repair["discovery_id"]
        if discovery_id:
            discovery = self.repository.discovery.get(str(discovery_id))
            if str(discovery["status"]) == "completed":
                accepted = self.repository.discovery.list_accepted_candidate_ids(str(discovery_id))
                if accepted:
                    return self._update_repair(repair, status="awaiting_probe", candidate_id=accepted[0], delay_minutes=5)
                return self._update_repair(repair, status="blocked", error_code="actorops_repair_no_candidate", delay_minutes=360)
            if str(discovery["status"]) in {"failed", "cancelled"}:
                return self._update_repair(repair, status="blocked", error_code="actorops_repair_discovery_failed", delay_minutes=60)
            return self._update_repair(repair, status="discovering", delay_minutes=5)
        discovery_id = self._create_repair_discovery(route_id, repair_id)
        return self._update_repair(repair, status="discovering", discovery_id=discovery_id, delay_minutes=5)

    def allows_repair_headroom(self, route_id: str, candidate_id: str) -> bool:
        return self.repository.connection.execute(
            """SELECT 1 FROM actor_route_repairs_v2 WHERE workspace_id=? AND route_id=?
                 AND candidate_id=? AND status='awaiting_probe' LIMIT 1""",
            (self.repository.workspace_id, route_id, candidate_id),
        ).fetchone() is not None

    def route_repairs(self, route_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        rows = self.repository.connection.execute(
            """SELECT repair_id, source_id, origin_job_id, trigger_code, status, discovery_id,
                      candidate_id, error_code, attempt_count, created_at, updated_at, terminal_at
                 FROM actor_route_repairs_v2 WHERE workspace_id=? AND route_id=?
                 ORDER BY updated_at DESC, repair_id DESC LIMIT ?""",
            (self.repository.workspace_id, route_id, min(max(int(limit), 1), 50)),
        ).fetchall()
        return [dict(row) for row in rows]

    def emit(
        self, *, root_job_id: str | None, job_id: str | None = None,
        route_id: str | None = None, source_id: str | None = None,
        candidate_id: str | None = None, repair_id: str | None = None,
        phase: str, outcome: str, reason_code: str | None = None,
        counts: dict[str, int] | None = None, final_cost_usd: float | None = None,
    ) -> None:
        if not _SAFE.fullmatch(phase) or not _SAFE.fullmatch(outcome):
            return
        reason = reason_code if reason_code and _SAFE.fullmatch(reason_code) else None
        safe_counts = {
            str(key): int(value) for key, value in (counts or {}).items()
            if _SAFE.fullmatch(str(key)) and not isinstance(value, bool) and 0 <= int(value) <= 1_000_000_000
        }
        occurrence = hashlib.sha256("\x1f".join(map(str, (
            root_job_id or "", job_id or "", route_id or "", source_id or "",
            candidate_id or "", repair_id or "", phase, outcome, reason or "",
        ))).encode()).hexdigest()
        event_id = f"trace-{uuid.uuid4().hex}"
        try:
            with self.repository.transaction():
                self.repository.connection.execute(
                    """INSERT OR IGNORE INTO actor_execution_events_v2 (
                           event_id, occurrence_key, workspace_id, root_job_id, job_id, route_id,
                           source_id, candidate_id, repair_id, phase, outcome, reason_code,
                           counts_json, final_cost_usd, created_at
                       ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                    (event_id, occurrence, self.repository.workspace_id,
                     _safe_id(root_job_id), _safe_id(job_id), _safe_id(route_id),
                     _safe_id(source_id), _safe_id(candidate_id), _safe_id(repair_id),
                     phase, outcome, reason, json.dumps(safe_counts, sort_keys=True),
                     float(final_cost_usd) if final_cost_usd is not None else None, _stamp()),
                )
        except Exception:
            return
        mirrored = safe_emit_operation_event(
            category="source", action="actorops_v2_execution_trace",
            outcome=_operation_outcome(outcome), workspace_id=self.repository.workspace_id,
            job_id=_safe_id(root_job_id), source_id=_safe_id(source_id),
            error_code=reason, changed_fields=(phase, outcome), counts=safe_counts,
        )
        if not mirrored:
            try:
                with self.repository.transaction():
                    self.repository.connection.execute(
                        "UPDATE actor_execution_events_v2 SET mirror_state='partial' WHERE workspace_id=? AND occurrence_key=?",
                        (self.repository.workspace_id, occurrence),
                    )
            except Exception:
                return

    def execution_events(
        self, *, root_job_id: str | None = None, route_id: str | None = None,
        source_id: str | None = None, repair_id: str | None = None,
        phase: str | None = None, outcome: str | None = None,
        since: str | None = None, until: str | None = None, before: str | None = None,
        limit: int = 50,
    ) -> tuple[list[dict[str, Any]], str | None, str]:
        clauses, params = ["workspace_id=?"], [self.repository.workspace_id]
        for column, value in (("root_job_id", root_job_id), ("route_id", route_id),
                              ("source_id", source_id), ("repair_id", repair_id),
                              ("phase", phase), ("outcome", outcome)):
            if value:
                clauses.append(f"{column}=?")
                params.append(str(value))
        if since:
            clauses.append("created_at>=?")
            params.append(str(since))
        if until:
            clauses.append("created_at<=?")
            params.append(str(until))
        if before:
            cursor = self.repository.connection.execute(
                "SELECT created_at FROM actor_execution_events_v2 WHERE workspace_id=? AND event_id=?",
                (self.repository.workspace_id, str(before)),
            ).fetchone()
            if cursor is not None:
                clauses.append("(created_at<? OR (created_at=? AND event_id<?))")
                params.extend((str(cursor["created_at"]), str(cursor["created_at"]), str(before)))
        rows = self.repository.connection.execute(
            f"""SELECT event_id, root_job_id, job_id, route_id, source_id, candidate_id,
                       repair_id, phase, outcome, reason_code, counts_json, final_cost_usd,
                       mirror_state, created_at FROM actor_execution_events_v2
                 WHERE {' AND '.join(clauses)} ORDER BY created_at DESC, event_id DESC LIMIT ?""",
            (*params, min(max(int(limit), 1), 100) + 1),
        ).fetchall()
        next_cursor = str(rows[-1]["event_id"]) if len(rows) > limit else None
        selected = rows[:limit]
        result = []
        for row in reversed(selected):
            try:
                counts = json.loads(str(row["counts_json"]))
            except ValueError:
                counts = {}
            result.append({**dict(row), "counts": counts})
        if not selected:
            completeness = "not_recorded"
        elif any(str(row["mirror_state"]) == "partial" for row in selected):
            completeness = "partial"
        else:
            completeness = "complete"
        return result, next_cursor, completeness

    def prune_execution_events(self) -> int:
        with self.repository.transaction():
            return int(self.repository.connection.execute(
                "DELETE FROM actor_execution_events_v2 WHERE created_at < ?",
                (_stamp(_now() - timedelta(days=30)),),
            ).rowcount)

    def _freshness(self, source_id: str, candidate_id: str, binding_version: int) -> Any | None:
        return self.repository.connection.execute(
            """SELECT * FROM actor_source_candidate_freshness_v2 WHERE workspace_id=?
                 AND source_id=? AND candidate_id=? AND binding_version=?""",
            (self.repository.workspace_id, source_id, candidate_id, binding_version),
        ).fetchone()

    def _source_cooldown(self, binding: Any, candidate_id: str) -> bool:
        row = self._freshness(binding.source_id, candidate_id, binding.binding_version)
        return bool(row and row["state"] == "source_stale" and row["cooldown_until"] and str(row["cooldown_until"]) > _stamp())

    def _upsert_freshness(self, *, binding: Any, candidate_id: str, count: int,
                          state: str, outcome: str, job_id: str,
                          cooldown_until: str | None = None, confirmed: bool = False) -> None:
        stamp = _stamp()
        with self.repository.transaction():
            self.repository.connection.execute(
                """INSERT INTO actor_source_candidate_freshness_v2 (
                       workspace_id, source_id, candidate_id, binding_version,
                       consecutive_scheduled_no_advance, state, cooldown_until, last_outcome,
                       last_job_id, last_checked_at, last_confirmed_at, created_at, updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?)
                   ON CONFLICT(workspace_id,source_id,candidate_id,binding_version) DO UPDATE SET
                       consecutive_scheduled_no_advance=excluded.consecutive_scheduled_no_advance,
                       state=excluded.state, cooldown_until=excluded.cooldown_until,
                       last_outcome=excluded.last_outcome, last_job_id=excluded.last_job_id,
                       last_checked_at=excluded.last_checked_at,
                       last_confirmed_at=COALESCE(excluded.last_confirmed_at,actor_source_candidate_freshness_v2.last_confirmed_at),
                       updated_at=excluded.updated_at""",
                (self.repository.workspace_id, binding.source_id, candidate_id,
                 binding.binding_version, count, state, cooldown_until, outcome,
                 _safe_id(job_id), stamp, stamp if confirmed else None, stamp, stamp),
            )

    def _repair_admission(self, route_id: str, blocked_code: str | None) -> tuple[str, str | None]:
        if blocked_code:
            return "blocked", blocked_code
        policy = self.repository.maintenance.effective_policy(route_id)
        if not policy.authorized:
            return "blocked", "actorops_repair_not_authorized"
        budget = self.repository.maintenance.probe_budget(route_id, _now())
        daily_cap = min(
            int(policy.route.max_probes_per_utc_day or 0), MAX_PROBES_PER_DAY
        )
        if daily_cap <= 0 or budget.probe_count >= daily_cap:
            return "blocked", "actorops_repair_daily_probe_limit"
        monthly_cap = min(
            float(policy.workspace.monthly_budget_usd or 0), MAX_MONTHLY_USD
        )
        if (
            policy.max_charge_usd <= 0
            or budget.spent_usd + budget.reserved_usd + policy.max_charge_usd > monthly_cap
        ):
            return "blocked", "actorops_repair_monthly_budget_exhausted"
        unknown = self.repository.connection.execute(
            """SELECT 1 FROM actor_attempts_v2 WHERE workspace_id=? AND route_id=?
                 AND kind='fetch' AND (status NOT IN ('succeeded','failed','cancelled') OR cost_final=0)
                 LIMIT 1""",
            (self.repository.workspace_id, route_id),
        ).fetchone()
        return ("blocked", "actorops_repair_cost_settlement_required") if unknown else ("queued", None)

    def _create_repair_discovery(self, route_id: str, repair_id: str) -> str:
        route = self.repository.get_route(route_id)
        bucket = _now().strftime("%Y%m%d%H")
        digest = hashlib.sha256(f"repair\x1f{route_id}\x1f{repair_id}\x1f{bucket}".encode()).hexdigest()
        discovery_id = f"repair-discovery-{uuid.uuid4().hex}"
        with self.repository.transaction():
            row, _created = self.repository.discovery.ensure(
                discovery_id=discovery_id, idempotency_key=digest, route_id=route_id,
                trigger_reason="production_exhausted",
                input_fingerprint=hashlib.sha256(str(route.route_key).encode()).hexdigest(),
            )
        return str(row["discovery_id"])

    def _usable_repair_candidate(self, repair: Any) -> Any | None:
        candidate_id = repair["candidate_id"]
        if candidate_id:
            try:
                return self.repository.get_candidate(str(candidate_id))
            except Exception:
                return None
        return None

    def _set_binding_preference(self, source_id: str, candidate_id: str) -> None:
        binding = self.repository.get_binding(source_id)
        with self.repository.transaction():
            self.repository.connection.execute(
                """UPDATE actor_source_bindings_v2 SET preferred_candidate_id=?, updated_at=?
                   WHERE workspace_id=? AND source_id=? AND binding_version=?""",
                (candidate_id, _stamp(), self.repository.workspace_id, source_id, binding.binding_version),
            )

    def _update_repair(self, repair: Any, *, status: str, error_code: str | None = None,
                       discovery_id: str | None = None, candidate_id: str | None = None,
                       delay_minutes: int | None = None, terminal: bool = False) -> dict[str, Any]:
        stamp = _stamp()
        with self.repository.transaction():
            self.repository.connection.execute(
                """UPDATE actor_route_repairs_v2 SET status=?, error_code=?,
                       discovery_id=COALESCE(?,discovery_id), candidate_id=COALESCE(?,candidate_id),
                       attempt_count=attempt_count+1, next_attempt_at=?, terminal_at=?, updated_at=?
                   WHERE workspace_id=? AND repair_id=?""",
                (status, error_code, discovery_id, candidate_id,
                 _stamp(_now() + timedelta(minutes=delay_minutes)) if delay_minutes else None,
                 stamp if terminal else None, stamp, self.repository.workspace_id, repair["repair_id"]),
            )
        return dict(self.get_repair(str(repair["repair_id"])))

    def _maybe_globally_demote(self, candidate_id: str) -> None:
        count = int(self.repository.connection.execute(
            """SELECT COUNT(DISTINCT source_id) FROM actor_source_candidate_freshness_v2
                 WHERE workspace_id=? AND candidate_id=? AND state='source_stale'
                   AND last_confirmed_at>=?""",
            (self.repository.workspace_id, candidate_id, _stamp(_now() - timedelta(hours=24))),
        ).fetchone()[0])
        candidate = self.repository.get_candidate(candidate_id)
        assigned = [item for item in self.repository.list_route_candidates(candidate.route_id)
                    if item.assignment_role is not AssignmentRole.INACTIVE]
        if count < 2 or len(assigned) < 2 or candidate.lifecycle not in {CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED}:
            return
        try:
            with self.repository.transaction():
                self.repository.transition_candidate(
                    candidate_id, candidate.lifecycle, CandidateLifecycle.QUARANTINED,
                    expected_generation=candidate.generation, error_class="candidate",
                    error_code="actorops_v2_stale_global_threshold",
                )
        except ActorOpsConflict:
            return


def _safe_id(value: str | None) -> str | None:
    return str(value) if value and _SAFE_ID.fullmatch(str(value)) else None


def _operation_outcome(outcome: str) -> str:
    return {
        "selected": "running", "started": "running", "settled": "succeeded",
        "advanced": "succeeded", "no_advance": "succeeded", "fallback": "partial",
        "failed": "failed", "blocked": "blocked", "queued": "queued",
        "recovered": "succeeded", "skipped": "skipped",
    }.get(outcome, "ok")


__all__ = ["FreshnessPlan", "ResilienceRepository"]
