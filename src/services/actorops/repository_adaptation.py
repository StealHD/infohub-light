"""Atomic persistence for immutable observed mappings and plan retargeting."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .candidate_identity import candidate_id
from .domain import CandidateLifecycle, ReplacementStatus
from .repository_errors import ActorOpsConflict, ActorOpsNotFound


class DatasetAdaptationRepository:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def plan_attempts(self, plan: Any, candidate_id: str) -> tuple[Any, ...]:
        rows = self.repository.connection.execute(
            """SELECT * FROM actor_attempts_v2
               WHERE workspace_id=? AND attempt_group_id=? AND candidate_id=?
                 AND kind='probe' AND status IN ('succeeded','failed')
               ORDER BY created_at DESC, attempt_id DESC""",
            (self.repository.workspace_id, plan.plan_id, candidate_id),
        ).fetchall()
        latest: dict[tuple[str, int, str], Any] = {}
        for row in rows:
            key = (
                str(row["source_id"]), int(row["binding_version"]),
                str(row["target_fingerprint"]),
            )
            latest.setdefault(key, row)
        return tuple(latest[key] for key in sorted(latest))

    def persist_successor(
        self, origin: Any, *, manifest_json: str, manifest_hash: str,
    ) -> Any:
        """Create or reuse one immutable successor and copy public metadata."""

        self.repository._require_transaction()
        successor_id = candidate_id(
            route_id=origin.route_id, actor_id=origin.actor_id,
            build_id=str(origin.build_id), build_number=str(origin.build_number),
            manifest_identity=manifest_hash,
        )
        try:
            successor = self.repository.get_candidate(successor_id)
        except ActorOpsNotFound:
            created = self.repository.create_candidate(
                candidate_id=successor_id, route_id=origin.route_id,
                actor_id=origin.actor_id, publisher=origin.publisher,
                build_id=origin.build_id, build_number=origin.build_number,
                manifest_json=manifest_json, manifest_hash=manifest_hash,
                input_schema_hash=origin.input_schema_hash,
                output_schema_hash=origin.output_schema_hash,
                lifecycle=CandidateLifecycle.DISCOVERED,
            )
            successor = self.repository.transition_candidate(
                created.candidate_id, CandidateLifecycle.DISCOVERED,
                CandidateLifecycle.STATIC_VALID,
                expected_generation=created.generation,
            )
        if not _same_revision(origin, successor, manifest_hash):
            raise ActorOpsConflict("observed mapping successor identity collision")
        self._copy_metadata(origin.candidate_id, successor.candidate_id)
        return successor

    def mark_origin_superseded(self, origin: Any) -> Any:
        self.repository._require_transaction()
        if origin.lifecycle is CandidateLifecycle.MAPPING_PENDING:
            return self.repository.transition_candidate(
                origin.candidate_id, origin.lifecycle,
                CandidateLifecycle.REJECTED,
                expected_generation=origin.generation,
                error_class=None,
                error_code="actorops_discovery_mapping_superseded",
            )
        if origin.lifecycle is CandidateLifecycle.STATIC_VALID:
            return self.repository.transition_candidate(
                origin.candidate_id, origin.lifecycle,
                CandidateLifecycle.REJECTED,
                expected_generation=origin.generation,
                error_class=None,
                error_code="actorops_discovery_mapping_superseded",
            )
        if origin.lifecycle in {
            CandidateLifecycle.PROBATIONARY, CandidateLifecycle.CERTIFIED,
        }:
            return self.repository.transition_candidate(
                origin.candidate_id, origin.lifecycle,
                CandidateLifecycle.SUPERSEDED,
                expected_generation=origin.generation,
                error_class=None,
                error_code="actorops_discovery_mapping_superseded",
            )
        raise ActorOpsConflict("origin Candidate cannot be superseded")

    def retarget_plan(self, plan: Any, origin: Any, successor: Any) -> Any:
        self.repository._require_transaction()
        current = self.repository.operator.get_plan(plan.plan_id)
        if (
            current.status is not ReplacementStatus.RUNNING
            or current.generation != plan.generation
            or current.proposed_candidate_id != origin.candidate_id
        ):
            raise ActorOpsConflict("replacement plan changed before adaptation")
        fills_empty = current.current_candidate_id == origin.candidate_id
        changed = self.repository.connection.execute(
            """UPDATE actor_replacement_plans_v2
               SET current_candidate_id=CASE WHEN ? THEN ? ELSE current_candidate_id END,
                   current_candidate_generation=CASE WHEN ? THEN ? ELSE current_candidate_generation END,
                   proposed_candidate_id=?, proposed_candidate_generation=?,
                   error_code='actorops_replacement_dataset_revalidating',
                   generation=generation+1, updated_at=?
               WHERE workspace_id=? AND plan_id=? AND status='running'
                 AND generation=? AND proposed_candidate_id=?""",
            (
                int(fills_empty), successor.candidate_id, int(fills_empty),
                successor.generation, successor.candidate_id,
                successor.generation, _now(), self.repository.workspace_id,
                plan.plan_id, plan.generation, origin.candidate_id,
            ),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("replacement plan changed before retarget")
        return self.repository.operator.get_plan(plan.plan_id)

    def _copy_metadata(self, origin_id: str, successor_id: str) -> None:
        if self.repository.operator.metadata(successor_id) is not None:
            return
        self.repository.connection.execute(
            """INSERT INTO actor_candidate_store_metadata_v2 (
                   candidate_id, workspace_id, actor_slug, display_name,
                   short_description, developer_name, maintained_by_apify,
                   rating, review_count, bookmark_count, total_users,
                   monthly_active_users, pricing_json, last_modified_at,
                   observed_at, generation, created_at, updated_at
               ) SELECT ?, workspace_id, actor_slug, display_name,
                   short_description, developer_name, maintained_by_apify,
                   rating, review_count, bookmark_count, total_users,
                   monthly_active_users, pricing_json, last_modified_at,
                   observed_at, 1, ?, ?
               FROM actor_candidate_store_metadata_v2
               WHERE workspace_id=? AND candidate_id=?""",
            (
                successor_id, _now(), _now(), self.repository.workspace_id,
                origin_id,
            ),
        )
        if self.repository.operator.metadata(successor_id) is None:
            raise ActorOpsConflict("observed mapping metadata unavailable")


def _same_revision(origin: Any, successor: Any, manifest_hash: str) -> bool:
    return (
        successor.route_id == origin.route_id
        and successor.actor_id == origin.actor_id
        and successor.publisher == origin.publisher
        and successor.build_id == origin.build_id
        and successor.build_number == origin.build_number
        and successor.input_schema_hash == origin.input_schema_hash
        and successor.output_schema_hash == origin.output_schema_hash
        and successor.manifest_hash == manifest_hash
    )


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


__all__ = ["DatasetAdaptationRepository"]
