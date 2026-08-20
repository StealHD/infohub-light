"""Attempt ledger SQL for ActorOpsRepository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .domain import AttemptStatus, ensure_attempt_transition
from .repository_errors import ActorOpsConflict, ActorOpsNotFound


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create_attempt(repository: Any, **values: Any) -> None:
    repository._require_transaction()
    stamp = _now()
    repository.connection.execute(
        """INSERT INTO actor_attempts_v2 (
               attempt_id, workspace_id, idempotency_key, route_id, source_id,
               candidate_id, kind, attempt_group_id, attempt_index,
               route_generation, binding_version, target_fingerprint,
               status, reserved_usd, cost_final, generation, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, 'created', ?, 0, 1, ?, ?)""",
        (
            values["attempt_id"], repository.workspace_id,
            values["idempotency_key"], values["route_id"], values["source_id"],
            values["candidate_id"], values["kind"], values["attempt_group_id"],
            values["attempt_index"], values["route_generation"],
            values["binding_version"], values["target_fingerprint"],
            values["reserved_usd"], stamp, stamp,
        ),
    )


def get_by_idempotency(repository: Any, key: str):
    return repository.connection.execute(
        "SELECT * FROM actor_attempts_v2 WHERE workspace_id=? AND idempotency_key=?",
        (repository.workspace_id, key),
    ).fetchone()


def get_attempt(repository: Any, attempt_id: str):
    row = repository.connection.execute(
        "SELECT * FROM actor_attempts_v2 WHERE workspace_id=? AND attempt_id=?",
        (repository.workspace_id, attempt_id),
    ).fetchone()
    if row is None:
        raise ActorOpsNotFound(f"attempt not found: {attempt_id}")
    return row


def update_start(repository: Any, attempt_id: str, **values: Any) -> None:
    repository._require_transaction()
    stamp = _now()
    changed = repository.connection.execute(
        """UPDATE actor_attempts_v2
           SET status='starting', secret_ref_id=?, secret_version=?, pool_generation=?,
               started_at=?, generation=generation+1, updated_at=?
           WHERE workspace_id=? AND attempt_id=? AND status='created' AND generation=?""",
        (
            values["secret_ref_id"], values["secret_version"],
            values["pool_generation"], stamp, stamp, repository.workspace_id,
            attempt_id, values["expected_generation"],
        ),
    ).rowcount
    _changed(changed, "attempt changed before start")


def register_run(repository: Any, attempt_id: str, **values: Any) -> None:
    repository._require_transaction()
    changed = repository.connection.execute(
        """UPDATE actor_attempts_v2
           SET status='registered', remote_run_id=?, dataset_id=?,
               generation=generation+1, updated_at=?
           WHERE workspace_id=? AND attempt_id=? AND status IN ('starting','start_unknown')
             AND generation=?""",
        (
            values["remote_run_id"], values["dataset_id"], _now(),
            repository.workspace_id, attempt_id, values["expected_generation"],
        ),
    ).rowcount
    _changed(changed, "attempt changed before Run registration")


def replace_credential(repository: Any, attempt_id: str, **values: Any) -> None:
    repository._require_transaction()
    changed = repository.connection.execute(
        """UPDATE actor_attempts_v2
           SET secret_ref_id=?, secret_version=?, pool_generation=?,
               generation=generation+1, updated_at=?
           WHERE workspace_id=? AND attempt_id=? AND status='starting'
             AND remote_run_id IS NULL AND generation=?""",
        (
            values["secret_ref_id"], values["secret_version"],
            values["pool_generation"], _now(), repository.workspace_id,
            attempt_id, values["expected_generation"],
        ),
    ).rowcount
    _changed(changed, "attempt changed before credential replacement")


def annotate(repository: Any, attempt_id: str, **values: Any) -> None:
    repository._require_transaction()
    row = get_attempt(repository, attempt_id)
    changed = repository.connection.execute(
        """UPDATE actor_attempts_v2 SET failure_class=?, error_code=?,
               generation=generation+1, updated_at=?
           WHERE workspace_id=? AND attempt_id=? AND generation=?""",
        (
            values["failure_class"], values["error_code"], _now(),
            repository.workspace_id, attempt_id, int(row["generation"]),
        ),
    ).rowcount
    _changed(changed, "attempt changed before annotation")


def complete(repository: Any, attempt_id: str, **values: Any) -> None:
    repository._require_transaction()
    row = get_attempt(repository, attempt_id)
    current, target = AttemptStatus(str(row["status"])), values["status"]
    ensure_attempt_transition(current, target)
    stamp = _now()
    changed = repository.connection.execute(
        """UPDATE actor_attempts_v2
           SET status=?, semantic_outcome=?, failure_class=?, error_code=?,
               actual_cost_usd=?, cost_final=?, terminal_at=?,
               generation=generation+1, updated_at=?
           WHERE workspace_id=? AND attempt_id=? AND status=? AND generation=?""",
        (
            target.value, values["semantic_outcome"], values["failure_class"],
            values["error_code"], values["actual_cost_usd"],
            int(values["cost_final"]), stamp, stamp, repository.workspace_id,
            attempt_id, current.value, int(row["generation"]),
        ),
    ).rowcount
    _changed(changed, "attempt changed before completion")


def transition(
    repository: Any,
    attempt_id: str,
    current: AttemptStatus,
    target: AttemptStatus,
    *,
    error_class: str | None,
    error_code: str | None,
    expected_generation: int | None,
) -> None:
    repository._require_transaction()
    ensure_attempt_transition(current, target)
    stamp = _now()
    terminal = stamp if target in {
        AttemptStatus.SUCCEEDED, AttemptStatus.FAILED, AttemptStatus.CANCELLED
    } else None
    changed = repository.connection.execute(
        """UPDATE actor_attempts_v2 SET status=?, failure_class=?, error_code=?,
               terminal_at=COALESCE(?, terminal_at), generation=generation+1, updated_at=?
           WHERE workspace_id=? AND attempt_id=? AND status=?
             AND (? IS NULL OR generation=?)""",
        (
            target.value, error_class, error_code, terminal, stamp,
            repository.workspace_id, attempt_id, current.value,
            expected_generation, expected_generation,
        ),
    ).rowcount
    _changed(changed, "attempt changed before transition")


def _changed(count: int, message: str) -> None:
    if count != 1:
        raise ActorOpsConflict(message)
