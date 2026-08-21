"""CAS persistence for safe Store snapshots and explicit replacement plans."""

from __future__ import annotations

import hashlib
import json
from datetime import datetime, timezone
from typing import Any

from .domain import (
    AssignmentRole, CandidateLifecycle, ReplacementPlanRecord, ReplacementStatus,
    StoreMetadataRecord, TERMINAL_REPLACEMENT_STATUSES,
)
from .repository_errors import ActorOpsConflict, ActorOpsNotFound
from .store_metadata import StoreMetadata, pricing_json


_OPEN = ("previewed", "authorized", "running", "ready")


class OperatorRepository:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def metadata(self, candidate_id: str) -> StoreMetadataRecord | None:
        row = self.repository.connection.execute(
            "SELECT * FROM actor_candidate_store_metadata_v2 WHERE workspace_id=? AND candidate_id=?",
            (self.repository.workspace_id, candidate_id),
        ).fetchone()
        return _metadata(row) if row else None

    def list_metadata(self, route_id: str) -> dict[str, StoreMetadataRecord]:
        rows = self.repository.connection.execute(
            """SELECT metadata.* FROM actor_candidate_store_metadata_v2 AS metadata
               JOIN actor_candidates_v2 AS candidate
                 ON candidate.workspace_id=metadata.workspace_id AND candidate.candidate_id=metadata.candidate_id
               WHERE metadata.workspace_id=? AND candidate.route_id=?""",
            (self.repository.workspace_id, route_id),
        ).fetchall()
        return {str(row["candidate_id"]): _metadata(row) for row in rows}

    def upsert_metadata(self, candidate_id: str, value: StoreMetadata, *, expected_generation: int | None = None) -> StoreMetadataRecord:
        self.repository._require_transaction()
        candidate = self.repository.get_candidate(candidate_id)
        if value.actor_slug != candidate.actor_id:
            raise ActorOpsConflict("store metadata actor does not match Candidate")
        stamp = _stamp()
        current = self.metadata(candidate_id)
        if current is None:
            self.repository.connection.execute(
                """INSERT INTO actor_candidate_store_metadata_v2 (
                       candidate_id, workspace_id, actor_slug, display_name, short_description,
                       developer_name, maintained_by_apify, rating, review_count, bookmark_count,
                       total_users, monthly_active_users, pricing_json, last_modified_at,
                       observed_at, generation, created_at, updated_at
                   ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
                (candidate.candidate_id, self.repository.workspace_id, value.actor_slug, value.display_name,
                 value.short_description, value.developer_name, int(value.maintained_by_apify), value.rating,
                 value.review_count, value.bookmark_count, value.total_users, value.monthly_active_users,
                 pricing_json(value), value.last_modified_at, stamp, 1, stamp, stamp),
            )
        else:
            expected = current.generation if expected_generation is None else expected_generation
            changed = self.repository.connection.execute(
                """UPDATE actor_candidate_store_metadata_v2 SET actor_slug=?, display_name=?,
                       short_description=?, developer_name=?, maintained_by_apify=?, rating=?, review_count=?,
                       bookmark_count=?, total_users=?, monthly_active_users=?, pricing_json=?, last_modified_at=?,
                       observed_at=?, generation=generation+1, updated_at=?
                   WHERE workspace_id=? AND candidate_id=? AND generation=?""",
                (value.actor_slug, value.display_name, value.short_description, value.developer_name,
                 int(value.maintained_by_apify), value.rating, value.review_count, value.bookmark_count,
                 value.total_users, value.monthly_active_users, pricing_json(value), value.last_modified_at,
                 stamp, stamp, self.repository.workspace_id, candidate_id, expected),
            ).rowcount
            if changed != 1:
                raise ActorOpsConflict("store metadata changed before refresh")
        stored = self.metadata(candidate_id)
        assert stored is not None
        return stored

    def set_route_cap(self, route_id: str, *, cap_usd: float, expected_generation: int) -> Any:
        self.repository._require_transaction()
        value = round(float(cap_usd), 6)
        if not 0 < value <= 0.20:
            raise ValueError("actorops_v2_price_cap_invalid")
        stamp = _stamp()
        changed = self.repository.connection.execute(
            """UPDATE actor_routes_v2 SET per_run_cap_usd=?, generation=generation+1, updated_at=?
               WHERE workspace_id=? AND route_id=? AND generation=?""",
            (value, stamp, self.repository.workspace_id, route_id, expected_generation),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("route changed before price cap update")
        return self.repository.get_route(route_id)

    def binding_set(self, route_id: str) -> tuple[tuple[str, int, str], ...]:
        rows = self.repository.connection.execute(
            """SELECT source_id, binding_version, target_fingerprint FROM actor_source_bindings_v2
               WHERE workspace_id=? AND route_id=? AND status='ready'
               ORDER BY source_id""",
            (self.repository.workspace_id, route_id),
        ).fetchall()
        return tuple((str(row["source_id"]), int(row["binding_version"]), str(row["target_fingerprint"])) for row in rows)

    def create_plan(self, *, plan_id: str, route_id: str, target_assignment: AssignmentRole, target_priority: int, proposed_candidate_id: str, idempotency_key: str, created_by_user_id: str, per_probe_cap_usd: float, total_cap_usd: float) -> ReplacementPlanRecord:
        self.repository._require_transaction()
        existing = self.repository.connection.execute(
            "SELECT * FROM actor_replacement_plans_v2 WHERE workspace_id=? AND idempotency_key=?",
            (self.repository.workspace_id, idempotency_key),
        ).fetchone()
        if existing is not None:
            return _plan(existing)
        route = self.repository.get_route(route_id)
        candidate = self.repository.get_candidate(proposed_candidate_id)
        metadata = self.metadata(proposed_candidate_id)
        assigned = next((item for item in self.repository.list_route_candidates(route_id) if item.assignment_role is target_assignment and item.priority == target_priority), None)
        bindings = self.binding_set(route_id)
        per_probe = round(float(per_probe_cap_usd), 6)
        total = round(float(total_cap_usd), 6)
        if (
            candidate.route_id != route_id
            or candidate.assignment_role is not AssignmentRole.INACTIVE
            or metadata is None
        ):
            raise ActorOpsConflict("actorops_replacement_candidate_invalid")
        if assigned is None or not bindings:
            raise ActorOpsConflict("actorops_replacement_route_not_ready")
        if not 0 < per_probe <= min(route.per_run_cap_usd, 0.20) or not 0 < total <= 0.60 or per_probe * len(bindings) > total:
            raise ActorOpsConflict("actorops_replacement_budget_invalid")
        stamp = _stamp()
        digest = _bindings_hash(bindings)
        self.repository.connection.execute(
            """INSERT INTO actor_replacement_plans_v2 (
                   plan_id, workspace_id, route_id, target_assignment, target_priority,
                   current_candidate_id, current_candidate_generation, proposed_candidate_id,
                   proposed_candidate_generation, pricing_hash, route_generation, binding_set_hash, binding_count,
                   per_probe_cap_usd, total_cap_usd, status, idempotency_key, created_by_user_id,
                   generation, created_at, updated_at
               ) VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,?)""",
            (plan_id, self.repository.workspace_id, route_id, target_assignment.value, target_priority,
             assigned.candidate_id, assigned.generation, candidate.candidate_id, candidate.generation,
             _pricing_hash(metadata.pricing_json), route.generation, digest, len(bindings), per_probe, total,
             ReplacementStatus.PREVIEWED.value,
             idempotency_key, created_by_user_id, 1, stamp, stamp),
        )
        return self.get_plan(plan_id)

    def get_plan(self, plan_id: str) -> ReplacementPlanRecord:
        row = self.repository.connection.execute(
            "SELECT * FROM actor_replacement_plans_v2 WHERE workspace_id=? AND plan_id=?",
            (self.repository.workspace_id, plan_id),
        ).fetchone()
        if row is None:
            raise ActorOpsNotFound("replacement plan not found")
        return _plan(row)

    def list_due_plans(self, *, limit: int = 5) -> tuple[ReplacementPlanRecord, ...]:
        rows = self.repository.connection.execute(
            """SELECT * FROM actor_replacement_plans_v2 WHERE workspace_id=? AND status IN ('authorized','running')
               ORDER BY updated_at, plan_id LIMIT ?""",
            (self.repository.workspace_id, min(max(int(limit), 1), 20)),
        ).fetchall()
        return tuple(_plan(row) for row in rows)

    def proofs_complete(self, plan: ReplacementPlanRecord) -> bool:
        bindings = self.binding_set(plan.route_id)
        if len(bindings) != plan.binding_count or _bindings_hash(bindings) != plan.binding_set_hash:
            return False
        for source_id, binding_version, fingerprint in bindings:
            row = self.repository.connection.execute(
                """SELECT 1 FROM actor_attempts_v2 WHERE workspace_id=? AND candidate_id=?
                   AND source_id=? AND binding_version=? AND target_fingerprint=?
                   AND kind='probe' AND status='succeeded' AND semantic_outcome='valid_nonempty'
                   AND cost_final=1 LIMIT 1""",
                (self.repository.workspace_id, plan.proposed_candidate_id,
                 source_id, binding_version, fingerprint),
            ).fetchone()
            if row is None:
                return False
        return True

    def transition_plan(self, plan_id: str, *, current: ReplacementStatus, target: ReplacementStatus, expected_generation: int, error_code: str | None = None, proposed_candidate_generation: int | None = None) -> ReplacementPlanRecord:
        self.repository._require_transaction()
        allowed = {
            ReplacementStatus.PREVIEWED: {ReplacementStatus.AUTHORIZED, ReplacementStatus.CANCELLED, ReplacementStatus.READY},
            ReplacementStatus.AUTHORIZED: {ReplacementStatus.RUNNING, ReplacementStatus.FAILED, ReplacementStatus.CANCELLED, ReplacementStatus.READY},
            ReplacementStatus.RUNNING: {ReplacementStatus.READY, ReplacementStatus.FAILED, ReplacementStatus.CANCELLED},
            ReplacementStatus.READY: {ReplacementStatus.APPLIED, ReplacementStatus.CANCELLED},
        }
        if target not in allowed.get(current, set()):
            raise ActorOpsConflict("actorops_replacement_transition_invalid")
        stamp = _stamp()
        changed = self.repository.connection.execute(
            """UPDATE actor_replacement_plans_v2 SET status=?, error_code=?,
                   proposed_candidate_generation=COALESCE(?, proposed_candidate_generation),
                   authorized_at=CASE WHEN ?='authorized' THEN ? ELSE authorized_at END,
                   terminal_at=CASE WHEN ? IN ('applied','failed','cancelled') THEN ? ELSE terminal_at END,
                   generation=generation+1, updated_at=?
               WHERE workspace_id=? AND plan_id=? AND status=? AND generation=?""",
            (target.value, error_code, proposed_candidate_generation, target.value, stamp, target.value,
             stamp, stamp, self.repository.workspace_id, plan_id, current.value, expected_generation),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("replacement plan changed before transition")
        return self.get_plan(plan_id)

    def cancel_plan(self, plan_id: str, *, expected_generation: int) -> ReplacementPlanRecord:
        plan = self.get_plan(plan_id)
        if plan.status in TERMINAL_REPLACEMENT_STATUSES:
            raise ActorOpsConflict("replacement plan is already terminal")
        return self.transition_plan(plan_id, current=plan.status, target=ReplacementStatus.CANCELLED, expected_generation=expected_generation)

    def refresh_proposed_generation(
        self, plan_id: str, *, status: ReplacementStatus, expected_generation: int,
        proposed_candidate_generation: int,
    ) -> ReplacementPlanRecord:
        """Keep a running plan pinned to its own evidence-induced Candidate revision."""

        self.repository._require_transaction()
        changed = self.repository.connection.execute(
            """UPDATE actor_replacement_plans_v2 SET proposed_candidate_generation=?,
                   generation=generation+1, updated_at=?
               WHERE workspace_id=? AND plan_id=? AND status=? AND generation=?""",
            (proposed_candidate_generation, _stamp(), self.repository.workspace_id,
             plan_id, status.value, expected_generation),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("replacement plan changed before evidence update")
        return self.get_plan(plan_id)

    def note_plan(
        self, plan_id: str, *, status: ReplacementStatus, expected_generation: int,
        error_code: str | None,
    ) -> ReplacementPlanRecord:
        self.repository._require_transaction()
        changed = self.repository.connection.execute(
            """UPDATE actor_replacement_plans_v2 SET error_code=?, generation=generation+1, updated_at=?
               WHERE workspace_id=? AND plan_id=? AND status=? AND generation=?""",
            (error_code, _stamp(), self.repository.workspace_id, plan_id, status.value, expected_generation),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("replacement plan changed before note")
        return self.get_plan(plan_id)

    def assert_plan_current(self, plan: ReplacementPlanRecord) -> tuple[tuple[str, int, str], ...]:
        route = self.repository.get_route(plan.route_id)
        current = self.repository.get_candidate(plan.current_candidate_id)
        proposed = self.repository.get_candidate(plan.proposed_candidate_id)
        metadata = self.metadata(plan.proposed_candidate_id)
        bindings = self.binding_set(plan.route_id)
        if (
            route.generation != plan.route_generation or current.generation != plan.current_candidate_generation
            or proposed.generation != plan.proposed_candidate_generation or _bindings_hash(bindings) != plan.binding_set_hash
            or len(bindings) != plan.binding_count
            or metadata is None
            or _pricing_hash(metadata.pricing_json) != plan.pricing_hash
        ):
            raise ActorOpsConflict("actorops_replacement_plan_stale")
        return bindings

    def apply_plan(self, plan_id: str, *, expected_generation: int) -> ReplacementPlanRecord:
        self.repository._require_transaction()
        plan = self.get_plan(plan_id)
        if plan.generation != expected_generation or plan.status is not ReplacementStatus.READY:
            raise ActorOpsConflict("replacement plan changed before apply")
        self.assert_plan_current(plan)
        proposed = self.repository.get_candidate(plan.proposed_candidate_id)
        if proposed.lifecycle not in {CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED}:
            raise ActorOpsConflict("actorops_replacement_candidate_not_runnable")
        stamp = _stamp()
        old_changed = self.repository.connection.execute(
            """UPDATE actor_candidates_v2 SET assignment_role='inactive', priority=NULL,
                   generation=generation+1, updated_at=? WHERE workspace_id=? AND candidate_id=?
                   AND generation=?""",
            (stamp, self.repository.workspace_id, plan.current_candidate_id, plan.current_candidate_generation),
        ).rowcount
        new_changed = self.repository.connection.execute(
            """UPDATE actor_candidates_v2 SET assignment_role=?, priority=?, generation=generation+1, updated_at=?
               WHERE workspace_id=? AND candidate_id=? AND assignment_role='inactive' AND generation=?""",
            (plan.target_assignment.value, plan.target_priority, stamp, self.repository.workspace_id,
             plan.proposed_candidate_id, plan.proposed_candidate_generation),
        ).rowcount
        route_changed = self.repository.connection.execute(
            """UPDATE actor_routes_v2 SET generation=generation+1, updated_at=?
               WHERE workspace_id=? AND route_id=? AND generation=?""",
            (stamp, self.repository.workspace_id, plan.route_id, plan.route_generation),
        ).rowcount
        if old_changed != 1 or new_changed != 1 or route_changed != 1:
            raise ActorOpsConflict("actorops_replacement_assignment_conflict")
        return self.transition_plan(plan_id, current=ReplacementStatus.READY, target=ReplacementStatus.APPLIED, expected_generation=plan.generation)


def _bindings_hash(bindings: tuple[tuple[str, int, str], ...]) -> str:
    return hashlib.sha256(json.dumps(bindings, separators=(",", ":")).encode()).hexdigest()


def _pricing_hash(value: str) -> str:
    return hashlib.sha256(value.encode()).hexdigest()


def _stamp() -> str:
    return datetime.now(timezone.utc).isoformat()


def _metadata(row: Any) -> StoreMetadataRecord:
    return StoreMetadataRecord(
        candidate_id=str(row["candidate_id"]), actor_slug=str(row["actor_slug"]), display_name=str(row["display_name"]),
        short_description=row["short_description"], developer_name=row["developer_name"],
        maintained_by_apify=bool(row["maintained_by_apify"]), rating=float(row["rating"]) if row["rating"] is not None else None,
        review_count=int(row["review_count"]) if row["review_count"] is not None else None,
        bookmark_count=int(row["bookmark_count"]) if row["bookmark_count"] is not None else None,
        total_users=int(row["total_users"]) if row["total_users"] is not None else None,
        monthly_active_users=int(row["monthly_active_users"]) if row["monthly_active_users"] is not None else None,
        pricing_json=str(row["pricing_json"]), last_modified_at=row["last_modified_at"],
        observed_at=str(row["observed_at"]), generation=int(row["generation"]),
    )


def _plan(row: Any) -> ReplacementPlanRecord:
    return ReplacementPlanRecord(
        plan_id=str(row["plan_id"]), route_id=str(row["route_id"]),
        target_assignment=AssignmentRole(str(row["target_assignment"])), target_priority=int(row["target_priority"]),
        current_candidate_id=str(row["current_candidate_id"]), current_candidate_generation=int(row["current_candidate_generation"]),
        proposed_candidate_id=str(row["proposed_candidate_id"]), proposed_candidate_generation=int(row["proposed_candidate_generation"]),
        pricing_hash=str(row["pricing_hash"]),
        route_generation=int(row["route_generation"]), binding_set_hash=str(row["binding_set_hash"]),
        binding_count=int(row["binding_count"]), per_probe_cap_usd=float(row["per_probe_cap_usd"]),
        total_cap_usd=float(row["total_cap_usd"]), status=ReplacementStatus(str(row["status"])),
        idempotency_key=str(row["idempotency_key"]), error_code=row["error_code"], generation=int(row["generation"]),
    )


__all__ = ["OperatorRepository"]
