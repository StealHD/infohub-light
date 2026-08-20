"""Discovery job SQL retained for the Phase 1 repository contract."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .domain import DiscoveryStatus, ensure_discovery_transition
from .repository_errors import ActorOpsConflict


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def create(repository: Any, **values: Any) -> None:
    repository._require_transaction()
    stamp = _now()
    repository.connection.execute(
        """INSERT INTO actor_discovery_jobs_v2 (
               discovery_id, workspace_id, idempotency_key, route_id,
               trigger_reason, status, stage, stage_attempt,
               input_fingerprint, generation, created_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, 'queued', 'store_search', 0, ?, 1, ?, ?)""",
        (
            values["discovery_id"], repository.workspace_id,
            values["idempotency_key"], values["route_id"],
            values["trigger_reason"], values["input_fingerprint"], stamp, stamp,
        ),
    )


def transition(repository: Any, discovery_id: str, **values: Any) -> None:
    repository._require_transaction()
    ensure_discovery_transition(
        values["current_status"], values["current_stage"],
        values["target_status"], values["target_stage"],
    )
    stamp = _now()
    terminal = stamp if values["target_status"] in {
        DiscoveryStatus.COMPLETED,
        DiscoveryStatus.FAILED,
        DiscoveryStatus.CANCELLED,
    } else None
    changed = repository.connection.execute(
        """UPDATE actor_discovery_jobs_v2
           SET status=?, stage=?,
               stage_attempt=CASE WHEN stage=? THEN stage_attempt+1 ELSE 0 END,
               terminal_at=COALESCE(?, terminal_at),
               generation=generation+1, updated_at=?
           WHERE workspace_id=? AND discovery_id=? AND status=? AND stage=?""",
        (
            values["target_status"].value, values["target_stage"].value,
            values["target_stage"].value, terminal, stamp,
            repository.workspace_id, discovery_id,
            values["current_status"].value, values["current_stage"].value,
        ),
    ).rowcount
    if changed != 1:
        raise ActorOpsConflict("discovery changed before transition")
