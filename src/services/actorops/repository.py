"""Typed SQLite repository for ActorOps v2 facts and monotonic mutations."""

from __future__ import annotations

import sqlite3
from contextlib import contextmanager
from typing import Iterator

from .domain import (
    AssignmentRole,
    AttemptStatus,
    BindingRecord,
    CandidateLifecycle,
    CandidateRecord,
    DiscoveryStage,
    DiscoveryStatus,
    ExecutionSnapshot,
    RouteHealth,
    RouteRecord,
)
from . import repository_candidates as _candidates
from . import repository_discovery as _discovery
from .ports import PublicationProof
from . import repository_attempts as _attempts
from . import repository_execution as _execution
from . import repository_reads as _reads
from .repository_errors import (
    ActorOpsConflict,
    ActorOpsNotFound,
    ActorOpsRepositoryError,
)

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
        return _reads.get_route(self, route_id)

    def get_candidate(self, candidate_id: str) -> CandidateRecord:
        return _reads.get_candidate(self, candidate_id)

    def get_binding(self, source_id: str) -> BindingRecord:
        return _reads.get_binding(self, source_id)

    def list_route_candidates(self, route_id: str) -> tuple[CandidateRecord, ...]:
        return _execution.list_route_candidates(self, route_id)

    def freeze_execution(
        self, route_id: str, source_id: str, target_fingerprint: str
    ) -> ExecutionSnapshot:
        return _execution.freeze_execution(
            self, route_id, source_id, target_fingerprint
        )

    def publication_proof(
        self, snapshot: ExecutionSnapshot, candidate_id: str | None
    ) -> PublicationProof:
        return _execution.publication_proof(self, snapshot, candidate_id)

    def assert_publishable(self, proof: PublicationProof) -> None:
        _execution.assert_publishable(self, proof)

    def publish_success(
        self,
        proof: PublicationProof,
        *,
        latest_published_at: str,
        latest_item_id_hash: str,
    ) -> None:
        _execution.publish_success(
            self,
            proof,
            latest_published_at=latest_published_at,
            latest_item_id_hash=latest_item_id_hash,
        )

    def record_candidate_outcome(
        self,
        candidate_id: str,
        *,
        expected_generation: int,
        succeeded: bool,
        error_class: str | None = None,
        error_code: str | None = None,
    ) -> CandidateRecord:
        return _execution.record_candidate_outcome(
            self,
            candidate_id,
            expected_generation=expected_generation,
            succeeded=succeeded,
            error_class=error_class,
            error_code=error_code,
        )

    def route_health(self, route_id: str) -> RouteHealth:
        return _candidates.route_health(self, route_id)

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
        return _candidates.create(
            self,
            candidate_id=candidate_id,
            route_id=route_id,
            actor_id=actor_id,
            publisher=publisher,
            build_id=build_id,
            build_number=build_number,
            manifest_json=manifest_json,
            manifest_hash=manifest_hash,
            input_schema_hash=input_schema_hash,
            output_schema_hash=output_schema_hash,
            lifecycle=lifecycle,
        )

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
        return _candidates.transition(
            self,
            candidate_id,
            current,
            target,
            expected_generation=expected_generation,
            error_class=error_class,
            error_code=error_code,
        )

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
        _candidates.assign(
            self,
            route_id,
            candidate_id,
            role,
            priority=priority,
            expected_route_generation=expected_route_generation,
            expected_candidate_generation=expected_candidate_generation,
        )

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
        source_id: str | None = None,
    ) -> None:
        _attempts.create_attempt(
            self,
            attempt_id=attempt_id,
            idempotency_key=idempotency_key,
            route_id=route_id,
            source_id=source_id,
            candidate_id=candidate_id,
            kind=kind,
            attempt_group_id=attempt_group_id,
            attempt_index=attempt_index,
            route_generation=route_generation,
            binding_version=binding_version,
            target_fingerprint=target_fingerprint,
            reserved_usd=reserved_usd,
        )

    def get_attempt_by_idempotency(self, idempotency_key: str) -> sqlite3.Row | None:
        return _attempts.get_by_idempotency(self, idempotency_key)

    def update_attempt_start(
        self,
        attempt_id: str,
        *,
        expected_generation: int,
        secret_ref_id: str | None,
        secret_version: int | None,
        pool_generation: int | None,
    ) -> None:
        _attempts.update_start(
            self,
            attempt_id,
            expected_generation=expected_generation,
            secret_ref_id=secret_ref_id,
            secret_version=secret_version,
            pool_generation=pool_generation,
        )

    def register_attempt_run(
        self,
        attempt_id: str,
        *,
        expected_generation: int,
        remote_run_id: str,
        dataset_id: str | None,
    ) -> None:
        _attempts.register_run(
            self,
            attempt_id,
            expected_generation=expected_generation,
            remote_run_id=remote_run_id,
            dataset_id=dataset_id,
        )

    def replace_attempt_credential(
        self,
        attempt_id: str,
        *,
        expected_generation: int,
        secret_ref_id: str | None,
        secret_version: int | None,
        pool_generation: int | None,
    ) -> None:
        _attempts.replace_credential(
            self,
            attempt_id,
            expected_generation=expected_generation,
            secret_ref_id=secret_ref_id,
            secret_version=secret_version,
            pool_generation=pool_generation,
        )

    def get_attempt(self, attempt_id: str) -> sqlite3.Row:
        return _attempts.get_attempt(self, attempt_id)

    def annotate_attempt(
        self,
        attempt_id: str,
        *,
        failure_class: str,
        error_code: str,
    ) -> None:
        _attempts.annotate(
            self,
            attempt_id,
            failure_class=failure_class,
            error_code=error_code,
        )

    def complete_attempt(
        self,
        attempt_id: str,
        *,
        status: AttemptStatus,
        semantic_outcome: str | None,
        actual_cost_usd: float | None,
        cost_final: bool,
        failure_class: str | None = None,
        error_code: str | None = None,
    ) -> None:
        _attempts.complete(
            self,
            attempt_id,
            status=status,
            semantic_outcome=semantic_outcome,
            actual_cost_usd=actual_cost_usd,
            cost_final=cost_final,
            failure_class=failure_class,
            error_code=error_code,
        )

    def transition_attempt(
        self,
        attempt_id: str,
        current: AttemptStatus,
        target: AttemptStatus,
        *,
        error_class: str | None = None,
        error_code: str | None = None,
        expected_generation: int | None = None,
    ) -> None:
        _attempts.transition(
            self,
            attempt_id,
            current,
            target,
            error_class=error_class,
            error_code=error_code,
            expected_generation=expected_generation,
        )

    def list_reconcilable_attempts(self, *, limit: int = 20) -> tuple[sqlite3.Row, ...]:
        return _attempts.list_reconcilable(self, limit=limit)

    def reconcile_attempt(self, attempt_id: str, **values: object) -> None:
        _attempts.reconcile(self, attempt_id, **values)

    def mark_reconciliation_error(self, attempt_id: str, **values: object) -> None:
        _attempts.mark_reconciliation_error(self, attempt_id, **values)

    @property
    def discovery(self) -> _discovery.DiscoveryRepository:
        return _discovery.DiscoveryRepository(self)

    def create_discovery_job(
        self,
        *,
        discovery_id: str,
        idempotency_key: str,
        route_id: str,
        trigger_reason: str,
        input_fingerprint: str,
    ) -> None:
        self.discovery.create(
            discovery_id=discovery_id,
            idempotency_key=idempotency_key,
            route_id=route_id,
            trigger_reason=trigger_reason,
            input_fingerprint=input_fingerprint,
        )

    def transition_discovery(
        self,
        discovery_id: str,
        current_status: DiscoveryStatus,
        current_stage: DiscoveryStage,
        target_status: DiscoveryStatus,
        target_stage: DiscoveryStage,
    ) -> None:
        _discovery.transition(
            self,
            discovery_id,
            current_status=current_status,
            current_stage=current_stage,
            target_status=target_status,
            target_stage=target_stage,
        )
