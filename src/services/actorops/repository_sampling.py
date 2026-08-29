"""Private persistence for exact-Build sampling InputPlans."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .input_plan import input_plan_hash, parse_input_plan
from .repository_errors import ActorOpsConflict


class SamplingPlanRepository:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def get(self, candidate_id: str) -> Any | None:
        return self.repository.connection.execute(
            """SELECT * FROM actor_candidate_sampling_plans_v2
               WHERE workspace_id=? AND candidate_id=?""",
            (self.repository.workspace_id, candidate_id),
        ).fetchone()

    def get_valid(self, candidate: Any) -> Any | None:
        row = self.get(candidate.candidate_id)
        if row is None or str(row["status"]) != "ready":
            return None
        try:
            plan = parse_input_plan(str(row["input_plan_json"]))
        except Exception:
            return None
        if (
            str(row["actor_id"]) != candidate.actor_id
            or str(row["build_id"]) != candidate.build_id
            or str(row["build_number"]) != candidate.build_number
            or str(row["input_schema_hash"]) != candidate.input_schema_hash
            or str(row["input_plan_hash"]) != input_plan_hash(plan)
            or plan["actor_id"] != candidate.actor_id
            or plan["build_number"] != candidate.build_number
        ):
            return None
        return row

    def upsert_ready(self, candidate: Any, input_plan_json: str) -> Any:
        self.repository._require_transaction()
        plan = parse_input_plan(input_plan_json)
        if (
            not candidate.build_id or not candidate.build_number
            or not candidate.input_schema_hash
            or plan["actor_id"] != candidate.actor_id
            or plan["build_number"] != candidate.build_number
        ):
            raise ActorOpsConflict("sampling plan Candidate identity mismatch")
        now = datetime.now(timezone.utc).isoformat()
        digest = input_plan_hash(plan)
        existing = self.get(candidate.candidate_id)
        if existing is None:
            self.repository.connection.execute(
                """INSERT INTO actor_candidate_sampling_plans_v2(
                       workspace_id,candidate_id,actor_id,build_id,build_number,
                       input_schema_hash,input_plan_json,input_plan_hash,status,
                       generation,created_at,updated_at
                   ) VALUES(?,?,?,?,?,?,?,?, 'ready',1,?,?)""",
                (
                    self.repository.workspace_id, candidate.candidate_id,
                    candidate.actor_id, candidate.build_id, candidate.build_number,
                    candidate.input_schema_hash, input_plan_json, digest, now, now,
                ),
            )
        elif str(existing["input_plan_hash"]) != digest:
            raise ActorOpsConflict("sampling plan is immutable")
        return self.get(candidate.candidate_id)


__all__ = ["SamplingPlanRepository"]
