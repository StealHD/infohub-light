"""Focused SQL facet for recoverable ActorOps v2 Discovery jobs."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .domain import DiscoveryStage, DiscoveryStatus, ensure_discovery_transition
from .repository_errors import ActorOpsConflict, ActorOpsNotFound


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


class DiscoveryRepository:
    def __init__(self, repository: Any) -> None:
        self.repository = repository

    def create(self, **values: Any) -> None:
        self.repository._require_transaction()
        stamp = _now()
        self.repository.connection.execute(
            """INSERT INTO actor_discovery_jobs_v2 (
                   discovery_id, workspace_id, idempotency_key, route_id,
                   trigger_reason, status, stage, stage_attempt,
                   input_fingerprint, generation, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, 'queued', 'store_search', 0, ?, 1, ?, ?)""",
            (
                values["discovery_id"], self.repository.workspace_id,
                values["idempotency_key"], values["route_id"],
                values["trigger_reason"], values["input_fingerprint"], stamp, stamp,
            ),
        )

    def ensure(self, **values: Any):
        self.repository._require_transaction()
        existing = self.repository.connection.execute(
            """SELECT * FROM actor_discovery_jobs_v2
               WHERE workspace_id=? AND idempotency_key=?""",
            (self.repository.workspace_id, values["idempotency_key"]),
        ).fetchone()
        if existing is not None:
            if (
                str(existing["route_id"]) != str(values["route_id"])
                or str(existing["trigger_reason"]) != str(values["trigger_reason"])
                or str(existing["input_fingerprint"]) != str(values["input_fingerprint"])
            ):
                raise ActorOpsConflict("discovery idempotency key conflicts")
            return existing, False
        self.create(**values)
        return self.get(str(values["discovery_id"])), True

    def get(self, discovery_id: str):
        row = self.repository.connection.execute(
            """SELECT * FROM actor_discovery_jobs_v2
               WHERE workspace_id=? AND discovery_id=?""",
            (self.repository.workspace_id, discovery_id),
        ).fetchone()
        if row is None:
            raise ActorOpsNotFound(f"discovery not found: {discovery_id}")
        return row

    def list_due(self, *, now: str, limit: int = 20):
        return tuple(self.repository.connection.execute(
            """SELECT * FROM actor_discovery_jobs_v2
               WHERE workspace_id=? AND (
                   status='queued' OR status='running' OR
                   (status='retry_wait' AND (retry_after IS NULL OR retry_after<=?))
               )
               ORDER BY created_at, discovery_id LIMIT ?""",
            (self.repository.workspace_id, now, min(max(int(limit), 1), 100)),
        ).fetchall())

    def checkpoint(
        self,
        discovery_id: str,
        *,
        expected_status: DiscoveryStatus,
        expected_stage: DiscoveryStage,
        expected_generation: int,
        status: DiscoveryStatus,
        stage: DiscoveryStage,
        checkpoint_hash: str | None,
        search_cursor: str | None,
        query_count: int,
        candidate_count: int,
        rejection_count: int,
        retry_after: str | None = None,
        failure_class: str | None = None,
        error_code: str | None = None,
        ai_metrics: dict[str, object] | None = None,
    ) -> None:
        self.repository._require_transaction()
        ensure_discovery_transition(expected_status, expected_stage, status, stage)
        stamp = _now()
        terminal = stamp if status in {
            DiscoveryStatus.COMPLETED,
            DiscoveryStatus.FAILED,
            DiscoveryStatus.CANCELLED,
        } else None
        metrics = ai_metrics or {}
        changed = self.repository.connection.execute(
            """UPDATE actor_discovery_jobs_v2
               SET status=?, stage=?,
                   stage_attempt=CASE
                     WHEN ?='retry_wait' AND ?=stage THEN stage_attempt+1
                     WHEN ?!=stage THEN 0 ELSE stage_attempt END,
                   retry_after=?, checkpoint_hash=COALESCE(?, checkpoint_hash),
                   search_cursor=COALESCE(?, search_cursor),
                   query_count=?, candidate_count=?, rejection_count=?,
                   failure_class=CASE WHEN ? IS NULL THEN failure_class ELSE ? END,
                   error_code=CASE WHEN ? IS NULL THEN error_code ELSE ? END,
                   ai_config_id=COALESCE(?, ai_config_id),
                   ai_input_tokens=COALESCE(?, ai_input_tokens),
                   ai_completion_tokens=COALESCE(?, ai_completion_tokens),
                   ai_reasoning_tokens=COALESCE(?, ai_reasoning_tokens),
                   ai_finish_reason=COALESCE(?, ai_finish_reason),
                   ai_latency_ms=COALESCE(?, ai_latency_ms),
                   ai_response_bytes=COALESCE(?, ai_response_bytes),
                   terminal_at=COALESCE(?, terminal_at),
                   generation=generation+1, updated_at=?
               WHERE workspace_id=? AND discovery_id=? AND status=? AND stage=?
                 AND generation=?""",
            (
                status.value, stage.value, status.value, stage.value, stage.value,
                retry_after, checkpoint_hash, search_cursor, query_count,
                candidate_count, rejection_count, failure_class, failure_class,
                error_code, error_code, metrics.get("config_id"),
                metrics.get("input_tokens"), metrics.get("completion_tokens"),
                metrics.get("reasoning_tokens"), metrics.get("finish_reason"),
                metrics.get("latency_ms"), metrics.get("response_bytes"), terminal,
                stamp, self.repository.workspace_id, discovery_id,
                expected_status.value, expected_stage.value, expected_generation,
            ),
        ).rowcount
        if changed != 1:
            raise ActorOpsConflict("discovery changed before checkpoint")

    def link_candidate(
        self,
        discovery_id: str,
        *,
        candidate_id: str,
        rank: int,
        status: str,
        rejection_code: str | None,
    ) -> None:
        self.repository._require_transaction()
        existing = self.repository.connection.execute(
            """SELECT rank, status, rejection_code
               FROM actor_discovery_job_candidates_v2
               WHERE workspace_id=? AND discovery_id=? AND candidate_id=?""",
            (self.repository.workspace_id, discovery_id, candidate_id),
        ).fetchone()
        if existing is not None:
            if (
                int(existing["rank"]) != rank or str(existing["status"]) != status
                or existing["rejection_code"] != rejection_code
            ):
                raise ActorOpsConflict("discovery candidate changed before persist")
            return
        stamp = _now()
        self.repository.connection.execute(
            """INSERT INTO actor_discovery_job_candidates_v2 (
                   workspace_id, discovery_id, candidate_id, rank, status,
                   rejection_code, created_at, updated_at
               ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                self.repository.workspace_id, discovery_id, candidate_id, rank,
                status, rejection_code, stamp, stamp,
            ),
        )

    def list_candidates(self, discovery_id: str):
        return tuple(self.repository.connection.execute(
            """SELECT * FROM actor_discovery_job_candidates_v2
               WHERE workspace_id=? AND discovery_id=? ORDER BY rank, candidate_id""",
            (self.repository.workspace_id, discovery_id),
        ).fetchall())


def create(repository: Any, **values: Any) -> None:
    DiscoveryRepository(repository).create(**values)


def transition(repository: Any, discovery_id: str, **values: Any) -> None:
    facet = DiscoveryRepository(repository)
    row = facet.get(discovery_id)
    facet.checkpoint(
        discovery_id,
        expected_status=values["current_status"],
        expected_stage=values["current_stage"],
        expected_generation=int(row["generation"]),
        status=values["target_status"],
        stage=values["target_stage"],
        checkpoint_hash=None,
        search_cursor=None,
        query_count=int(row["query_count"]),
        candidate_count=int(row["candidate_count"]),
        rejection_count=int(row["rejection_count"]),
    )
