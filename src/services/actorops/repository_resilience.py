"""Durable source freshness, automatic repair, and safe execution tracing."""

from __future__ import annotations

import hashlib
import json
import re
import uuid
from datetime import datetime, timedelta, timezone
from typing import Any

from ..operation_log import safe_emit_operation_event
from .repository_freshness import FreshnessPlan, SourceFreshnessRepository
from .repair_lifecycle import RepairLifecycle


_SAFE = re.compile(r"^[a-z][a-z0-9_]{1,95}$")
_SAFE_ID = re.compile(r"^[A-Za-z0-9_.:-]{1,128}$")
def _now() -> datetime:
    return datetime.now(timezone.utc)


def _stamp(value: datetime | None = None) -> str:
    return (value or _now()).astimezone(timezone.utc).isoformat()


class ResilienceRepository:
    def __init__(self, repository: Any) -> None:
        self.repository = repository
        self.freshness = SourceFreshnessRepository(repository)
        self.repairs = RepairLifecycle(repository)

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
        self, *, binding: Any, candidates: tuple[Any, ...], natural_schedule: bool,
        logical_job_id: str = "",
    ) -> FreshnessPlan:
        return self.freshness.plan_candidates(
            binding=binding, candidates=candidates,
            natural_schedule=natural_schedule, logical_job_id=logical_job_id,
        )

    def record_regular_result(
        self, *, binding: Any, candidate_id: str, outcome: str,
        logical_job_id: str, natural_schedule: bool,
    ) -> None:
        self.freshness.record_regular_result(
            binding=binding, candidate_id=candidate_id, outcome=outcome,
            logical_job_id=logical_job_id, natural_schedule=natural_schedule,
        )

    def record_cross_check(
        self, *, binding: Any, primary_candidate_id: str, candidate_id: str,
        outcome: str, logical_job_id: str,
    ) -> str:
        return self.freshness.record_cross_check(
            binding=binding, primary_candidate_id=primary_candidate_id,
            candidate_id=candidate_id, outcome=outcome,
            logical_job_id=logical_job_id,
        )

    def record_stale_regression(
        self, *, binding: Any, candidate_id: str, logical_job_id: str
    ) -> None:
        self.freshness.record_stale_regression(
            binding=binding, candidate_id=candidate_id,
            logical_job_id=logical_job_id,
        )

    def record_paid_candidate_failure(
        self, *, binding: Any, candidate_id: str, logical_job_id: str
    ) -> None:
        self.freshness.record_paid_candidate_failure(
            binding=binding, candidate_id=candidate_id,
            logical_job_id=logical_job_id,
        )

    def record_candidate_success(
        self, *, binding: Any, candidate_id: str, logical_job_id: str
    ) -> None:
        self.freshness.record_candidate_success(
            binding=binding, candidate_id=candidate_id,
            logical_job_id=logical_job_id,
        )

    def ensure_repair(
        self, *, route_id: str, source_id: str, origin_job_id: str,
        trigger_code: str, blocked_code: str | None = None,
    ) -> dict[str, Any]:
        return self.repairs.ensure(
            route_id=route_id, source_id=source_id,
            origin_job_id=origin_job_id, trigger_code=trigger_code,
            blocked_code=blocked_code,
        )

    def get_repair(self, repair_id: str) -> Any:
        return self.repairs.get(repair_id)

    def due_repairs(self, *, limit: int = 20) -> tuple[Any, ...]:
        return self.repairs.due(limit=limit)

    def advance_repair(self, repair_id: str) -> dict[str, Any]:
        return self.repairs.advance(repair_id)

    def allows_repair_headroom(self, route_id: str, candidate_id: str) -> bool:
        return self.repairs.allows_headroom(route_id, candidate_id)

    def route_repairs(self, route_id: str, *, limit: int = 20) -> list[dict[str, Any]]:
        return self.repairs.route_repairs(route_id, limit=limit)

    def wake_repairs_after_cost_settlement(
        self, route_id: str, source_id: str
    ) -> int:
        return self.repairs.wake_repairs_after_cost_settlement(route_id, source_id)

    def wake_repairs_after_discovery(self, discovery_id: str) -> int:
        return self.repairs.wake_repairs_after_discovery(discovery_id)

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
