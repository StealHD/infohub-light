"""Immutable Dataset-revalidation facts for failed replacement probes."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone
from typing import Any

from .repository_errors import ActorOpsConflict


class ReplacementRevalidationRepository:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def plan_by_idempotency(self, key: str):
        row = self.repository.connection.execute(
            """SELECT plan_id FROM actor_replacement_plans_v2
               WHERE workspace_id=? AND idempotency_key=?""",
            (self.repository.workspace_id, key),
        ).fetchone()
        return self.repository.operator.get_plan(str(row["plan_id"])) if row else None

    def failed_dataset_attempts(self, plan: Any) -> tuple[Any, ...]:
        return tuple(self.repository.connection.execute(
            """SELECT attempt.* FROM actor_attempts_v2 AS attempt
               WHERE attempt.workspace_id=? AND attempt.candidate_id=?
                 AND attempt.attempt_group_id=? AND attempt.kind='probe'
                 AND attempt.status='failed' AND attempt.cost_final=1
                 AND attempt.dataset_id IS NOT NULL
                 AND attempt.error_code IN (
                     'actorops_replacement_contract_mismatch',
                     'actorops_replacement_published_at_invalid',
                     'actorops_replacement_target_identity_mismatch',
                     'actorops_replacement_output_url_invalid',
                     'actorops_replacement_output_outside_window'
                 )
               ORDER BY attempt.created_at, attempt.attempt_id""",
            (self.repository.workspace_id, plan.proposed_candidate_id, plan.plan_id),
        ).fetchall())

    def recover_candidate(self, origin: Any, *, proved: bool):
        self.repository._require_transaction()
        stamp = _now()
        lifecycle = "probationary" if proved else "static_valid"
        row = self.repository.connection.execute(
            """SELECT last_success_at FROM actor_candidates_v2
               WHERE workspace_id=? AND candidate_id=?""",
            (self.repository.workspace_id, origin.candidate_id),
        ).fetchone()
        success_at = stamp if proved else row["last_success_at"]
        changed = self.repository.connection.execute(
            """UPDATE actor_candidates_v2
               SET lifecycle=?, assignment_role='inactive', priority=NULL,
                   last_success_at=?, last_error_class=NULL, last_error_code=NULL,
                   generation=generation+1, updated_at=?
               WHERE workspace_id=? AND candidate_id=? AND generation=?
                 AND lifecycle='rejected'
                 AND last_error_code IN (
                     'actorops_replacement_contract_mismatch',
                     'actorops_replacement_published_at_invalid',
                     'actorops_replacement_target_identity_mismatch',
                     'actorops_replacement_output_url_invalid',
                     'actorops_replacement_output_outside_window'
                 )""",
            (
                lifecycle, success_at, stamp, self.repository.workspace_id,
                origin.candidate_id, origin.generation,
            ),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("revalidation Candidate changed before recovery")
        return self.repository.get_candidate(origin.candidate_id)

    def create_evidence(
        self, *, origin_attempt: Any, candidate_id: str, ruleset: str,
        semantic_outcome: str,
    ) -> str:
        self.repository._require_transaction()
        digest = hashlib.sha256(
            f"{origin_attempt['attempt_id']}\x1f{candidate_id}\x1f{ruleset}\x1f{semantic_outcome}".encode()
        ).hexdigest()
        attempt_id = f"revalidation-{digest[:24]}"
        existing = self.repository.connection.execute(
            """SELECT attempt_id FROM actor_attempts_v2
               WHERE workspace_id=? AND idempotency_key=?""",
            (self.repository.workspace_id, digest),
        ).fetchone()
        if existing:
            return str(existing["attempt_id"])
        stamp = _now()
        self.repository.connection.execute(
            """INSERT INTO actor_attempts_v2 (
                   attempt_id,workspace_id,idempotency_key,route_id,source_id,
                   candidate_id,kind,attempt_group_id,attempt_index,
                   route_generation,binding_version,target_fingerprint,status,
                   semantic_outcome,reserved_usd,actual_cost_usd,cost_final,
                   generation,created_at,terminal_at,updated_at,logical_job_id,
                   request_schema_version,request_fingerprint,window_since,
                   window_until,max_items,result_state,result_observed_at,dataset_id
               ) VALUES (?,?,?,?,?,?,'probe',?,?,?, ?,?,'succeeded',
                         ?,0,0,1,1,?,?,?,?,2,?,?,?, ?,
                         'validated',?,?)""",
            (
                attempt_id, self.repository.workspace_id, digest,
                str(origin_attempt["route_id"]), str(origin_attempt["source_id"]),
                candidate_id, str(origin_attempt["attempt_group_id"]),
                int(origin_attempt["attempt_index"]), int(origin_attempt["route_generation"]),
                int(origin_attempt["binding_version"]), str(origin_attempt["target_fingerprint"]),
                semantic_outcome, stamp, stamp, stamp,
                f"revalidate:{origin_attempt['attempt_id']}",
                digest, str(origin_attempt["window_since"]), origin_attempt["window_until"],
                int(origin_attempt["max_items"]), stamp, str(origin_attempt["dataset_id"]),
            ),
        )
        return attempt_id


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["ReplacementRevalidationRepository"]
