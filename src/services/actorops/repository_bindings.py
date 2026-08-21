"""CAS mutations for source bindings owned by the ActorOps v2 repository."""

from __future__ import annotations

from datetime import datetime, timezone
from typing import Any

from .repository_errors import ActorOpsConflict


def mark_ready(
    repository: Any,
    source_id: str,
    *,
    expected_binding_version: int,
    expected_target_fingerprint: str,
):
    """Promote one pending binding after an offline exact-evidence check."""

    repository._require_transaction()
    changed = repository.connection.execute(
        """UPDATE actor_source_bindings_v2
           SET status='ready', binding_version=binding_version+1, updated_at=?
           WHERE workspace_id=? AND source_id=? AND status='pending'
             AND binding_version=? AND target_fingerprint=?""",
        (
            datetime.now(timezone.utc).isoformat(),
            repository.workspace_id,
            source_id,
            int(expected_binding_version),
            expected_target_fingerprint,
        ),
    ).rowcount
    if changed != 1:
        raise ActorOpsConflict("source binding changed before readiness promotion")
    return repository.get_binding(source_id)


__all__ = ["mark_ready"]
