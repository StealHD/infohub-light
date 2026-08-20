"""Typed SQLite repository for ActorOps v2 facts and monotonic mutations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from datetime import datetime, timezone
from typing import Iterator

from .domain import (
    AssignmentRole,
    AttemptStatus,
    BindingRecord,
    CandidateLifecycle,
    CandidateRecord,
    DiscoveryStage,
    DiscoveryStatus,
    RouteHealth,
    RouteKey,
    RouteRecord,
    RuntimeMode,
    ensure_attempt_transition,
    ensure_candidate_transition,
    ensure_discovery_transition,
)
from .policy import candidate_is_runnable, derive_route_health


class ActorOpsRepositoryError(RuntimeError):
    pass


class ActorOpsNotFound(ActorOpsRepositoryError):
    pass


class ActorOpsConflict(ActorOpsRepositoryError):
    pass


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class ActorOpsRepository:
    def __init__(self, connection: sqlite3.Connection, workspace_id: str) -> None:
        self.connection = connection
        self.workspace_id = str(workspace_id)
        self._savepoint = 0

    def _require_transaction(self) -> None:
        if not self.connection.in_transaction:
            raise ActorOpsRepositoryError("ActorOps mutation requires a repository transaction")

    @contextmanager
    def transaction(self) -> Iterator[None]:
        nested = self.connection.in_transaction
        self._savepoint += 1
        name = f"actorops_v2_{self._savepoint}"
        self.connection.execute(f"SAVEPOINT {name}" if nested else "BEGIN IMMEDIATE")
        try:
            yield
        except Exception:
            if nested:
                self.connection.execute(f"ROLLBACK TO {name}")
                self.connection.execute(f"RELEASE {name}")
            else:
                self.connection.rollback()
            raise
        else:
            if nested:
                self.connection.execute(f"RELEASE {name}")
            else:
                self.connection.commit()

    def get_route(self, route_id: str) -> RouteRecord:
        row = self.connection.execute(
            "SELECT * FROM actor_routes_v2 WHERE workspace_id = ? AND route_id = ?",
            (self.workspace_id, route_id),
        ).fetchone()
        if row is None:
            raise ActorOpsNotFound(f"route not found: {route_id}")
        return RouteRecord(
            route_id=str(row["route_id"]),
            workspace_id=str(row["workspace_id"]),
            route_key=RouteKey(row["platform"], row["target_type"], row["capability"]),
            runtime_mode=RuntimeMode(str(row["runtime_mode"])),
            per_run_cap_usd=float(row["per_run_cap_usd"]),
            generation=int(row["generation"]),
            source_v1_generation=int(row["source_v1_generation"]),
        )

    def get_candidate(self, candidate_id: str) -> CandidateRecord:
        row = self.connection.execute(
            "SELECT * FROM actor_candidates_v2 WHERE workspace_id = ? AND candidate_id = ?",
            (self.workspace_id, candidate_id),
        ).fetchone()
        if row is None:
            raise ActorOpsNotFound(f"candidate not found: {candidate_id}")
        return CandidateRecord(
            candidate_id=str(row["candidate_id"]),
            route_id=str(row["route_id"]),
            lifecycle=CandidateLifecycle(str(row["lifecycle"])),
            assignment_role=AssignmentRole(str(row["assignment_role"])),
            priority=int(row["priority"]) if row["priority"] is not None else None,
            generation=int(row["generation"]),
            build_id=row["build_id"],
            manifest_hash=row["manifest_hash"],
        )

    def get_binding(self, source_id: str) -> BindingRecord:
        row = self.connection.execute(
            "SELECT * FROM actor_source_bindings_v2 WHERE workspace_id = ? AND source_id = ?",
            (self.workspace_id, source_id),
        ).fetchone()
        if row is None:
            raise ActorOpsNotFound(f"binding not found: {source_id}")
        return BindingRecord(
            binding_id=str(row["binding_id"]),
            source_id=str(row["source_id"]),
            route_id=str(row["route_id"]),
            target_fingerprint=str(row["target_fingerprint"]),
            binding_version=int(row["binding_version"]),
            preferred_candidate_id=row["preferred_candidate_id"],
            last_known_good_candidate_id=row["last_known_good_candidate_id"],
        )

    def route_health(self, route_id: str) -> RouteHealth:
        self.get_route(route_id)
        count = int(
            self.connection.execute(
                """SELECT COUNT(*) FROM actor_candidates_v2
                   WHERE workspace_id = ? AND route_id = ?
                     AND assignment_role IN ('active', 'standby')
                     AND lifecycle IN ('probationary', 'certified')
                     AND build_id IS NOT NULL AND manifest_hash IS NOT NULL""",
                (self.workspace_id, route_id),
            ).fetchone()[0]
        )
        return derive_route_health(count)

    def create_candidate(
        self,
        *,
        candidate_id: str,
        route_id: str,
        actor_id: str,
        publisher: str,
        build_id: str | None,
        build_number: str | None,
        manifest_json: str | None,
        manifest_hash: str | None,
        input_schema_hash: str | None,
        output_schema_hash: str | None,
        lifecycle: CandidateLifecycle,
    ) -> CandidateRecord:
        self._require_transaction()
        stamp = _now()
        self.connection.execute(
            """INSERT INTO actor_candidates_v2 (
                   candidate_id, workspace_id, route_id, actor_id, publisher,
                   build_id, build_number, manifest_json, manifest_hash,
                   input_schema_hash, output_schema_hash, lifecycle,
                   assignment_role, generation, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'inactive', 1, ?, ?)""",
            (
                candidate_id, self.workspace_id, route_id, actor_id, publisher,
                build_id, build_number, manifest_json, manifest_hash,
                input_schema_hash, output_schema_hash, lifecycle.value, stamp, stamp,
            ),
        )
        return self.get_candidate(candidate_id)

    def transition_candidate(
        self,
        candidate_id: str,
        current: CandidateLifecycle,
        target: CandidateLifecycle,
        *,
        expected_generation: int,
        error_class: str | None = None,
        error_code: str | None = None,
    ) -> CandidateRecord:
        self._require_transaction()
        ensure_candidate_transition(current, target)
        stamp = _now()
        changed = self.connection.execute(
            """UPDATE actor_candidates_v2
               SET lifecycle = ?, assignment_role = CASE
                     WHEN ? IN ('rejected','quarantined','disabled','superseded') THEN 'inactive'
                     ELSE assignment_role END,
                   priority = CASE
                     WHEN ? IN ('rejected','quarantined','disabled','superseded') THEN NULL
                     ELSE priority END,
                   last_error_class = ?, last_error_code = ?,
                   generation = generation + 1, updated_at = ?
               WHERE workspace_id = ? AND candidate_id = ?
                 AND lifecycle = ? AND generation = ?""",
            (
                target.value, target.value, target.value, error_class, error_code,
                stamp, self.workspace_id, candidate_id, current.value,
                expected_generation,
            ),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("candidate changed before transition")
        return self.get_candidate(candidate_id)

    def assign_candidate(
        self,
        route_id: str,
        candidate_id: str,
        role: AssignmentRole,
        *,
        priority: int | None,
        expected_route_generation: int,
        expected_candidate_generation: int,
    ) -> None:
        self._require_transaction()
        candidate = self.get_candidate(candidate_id)
        if candidate.route_id != route_id or not candidate_is_runnable(
            candidate.lifecycle,
            build_id=candidate.build_id,
            manifest_hash=candidate.manifest_hash,
        ):
            raise ActorOpsConflict("candidate is not runnable for this route")
        if role is AssignmentRole.ACTIVE and priority != 0:
            raise ValueError("active candidate priority must be zero")
        if role is AssignmentRole.STANDBY and (priority is None or priority < 1):
            raise ValueError("standby priority must be positive")
        if role is AssignmentRole.INACTIVE:
            priority = None
        stamp = _now()
        candidate_changed = self.connection.execute(
            """UPDATE actor_candidates_v2
               SET assignment_role = ?, priority = ?, generation = generation + 1,
                   updated_at = ?
               WHERE workspace_id = ? AND candidate_id = ? AND route_id = ?
                 AND generation = ?""",
            (
                role.value, priority, stamp, self.workspace_id, candidate_id,
                route_id, expected_candidate_generation,
            ),
        ).rowcount
        route_changed = self.connection.execute(
            """UPDATE actor_routes_v2 SET generation = generation + 1, updated_at = ?
               WHERE workspace_id = ? AND route_id = ? AND generation = ?""",
            (stamp, self.workspace_id, route_id, expected_route_generation),
        ).rowcount
        if candidate_changed != 1 or route_changed != 1:
            raise ActorOpsConflict("route or candidate changed before assignment")

    def create_attempt(
        self,
        *,
        attempt_id: str,
        idempotency_key: str,
        route_id: str,
        candidate_id: str,
        kind: str,
        attempt_group_id: str,
        attempt_index: int,
        route_generation: int,
        binding_version: int | None,
        target_fingerprint: str,
        reserved_usd: float,
    ) -> None:
        self._require_transaction()
        stamp = _now()
        self.connection.execute(
            """INSERT INTO actor_attempts_v2 (
                   attempt_id, workspace_id, idempotency_key, route_id,
                   candidate_id, kind, attempt_group_id, attempt_index,
                   route_generation, binding_version, target_fingerprint,
                   status, reserved_usd, cost_final, generation, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, 0, 1, ?, ?)""",
            (
                attempt_id, self.workspace_id, idempotency_key, route_id,
                candidate_id, kind, attempt_group_id, attempt_index,
                route_generation, binding_version, target_fingerprint,
                reserved_usd, stamp, stamp,
            ),
        )

    def transition_attempt(
        self,
        attempt_id: str,
        current: AttemptStatus,
        target: AttemptStatus,
        *,
        error_class: str | None = None,
        error_code: str | None = None,
    ) -> None:
        self._require_transaction()
        ensure_attempt_transition(current, target)
        stamp = _now()
        terminal = stamp if target in {
            AttemptStatus.SUCCEEDED, AttemptStatus.FAILED, AttemptStatus.CANCELLED
        } else None
        changed = self.connection.execute(
            """UPDATE actor_attempts_v2
               SET status = ?, failure_class = ?, error_code = ?,
                   terminal_at = COALESCE(?, terminal_at),
                   generation = generation + 1, updated_at = ?
               WHERE workspace_id = ? AND attempt_id = ? AND status = ?""",
            (
                target.value, error_class, error_code, terminal, stamp,
                self.workspace_id, attempt_id, current.value,
            ),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("attempt changed before transition")

    def create_discovery_job(
        self,
        *,
        discovery_id: str,
        idempotency_key: str,
        route_id: str,
        trigger_reason: str,
        input_fingerprint: str,
    ) -> None:
        self._require_transaction()
        stamp = _now()
        self.connection.execute(
            """INSERT INTO actor_discovery_jobs_v2 (
                   discovery_id, workspace_id, idempotency_key, route_id,
                   trigger_reason, status, stage, stage_attempt,
                   input_fingerprint, generation, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, 'queued', 'store_search', 0, ?, 1, ?, ?)""",
            (
                discovery_id, self.workspace_id, idempotency_key, route_id,
                trigger_reason, input_fingerprint, stamp, stamp,
            ),
        )

    def transition_discovery(
        self,
        discovery_id: str,
        current_status: DiscoveryStatus,
        current_stage: DiscoveryStage,
        target_status: DiscoveryStatus,
        target_stage: DiscoveryStage,
    ) -> None:
        self._require_transaction()
        ensure_discovery_transition(
            current_status, current_stage, target_status, target_stage
        )
        stamp = _now()
        terminal = stamp if target_status in {
            DiscoveryStatus.COMPLETED,
            DiscoveryStatus.FAILED,
            DiscoveryStatus.CANCELLED,
        } else None
        changed = self.connection.execute(
            """UPDATE actor_discovery_jobs_v2
               SET status = ?, stage = ?,
                   stage_attempt = CASE WHEN stage = ? THEN stage_attempt + 1 ELSE 0 END,
                   terminal_at = COALESCE(?, terminal_at),
                   generation = generation + 1, updated_at = ?
               WHERE workspace_id = ? AND discovery_id = ?
                 AND status = ? AND stage = ?""",
            (
                target_status.value, target_stage.value, target_stage.value,
                terminal, stamp, self.workspace_id, discovery_id,
                current_status.value, current_stage.value,
            ),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("discovery changed before transition")
