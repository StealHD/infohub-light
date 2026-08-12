"""Best-effort Worker media and source-avatar publication helpers."""

from __future__ import annotations

from collections.abc import Callable
from dataclasses import dataclass
from typing import Any

from ..storage.service_store import ServiceStore
from .media_cache import PostCommitMediaCleanup


@dataclass(frozen=True, slots=True)
class WorkerMediaPorts:
    media_cache_service: Callable[..., Any]
    source_avatar_service: Callable[..., Any]
    emit_operation_event: Callable[..., None]
    log_warning: Callable[..., None]


def cache_run_media(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    items: list[Any],
    ports: WorkerMediaPorts,
    commit: bool = True,
    publication_cleanup: PostCommitMediaCleanup | None = None,
) -> None:
    """Best-effort media caching must never change the feed job outcome."""

    conn = store.connect()
    savepoint = not commit and conn.in_transaction
    if not commit and publication_cleanup is None:
        raise RuntimeError(
            "publication_cleanup is required inside an outer transaction"
        )
    stage_cleanup = PostCommitMediaCleanup()
    if savepoint:
        conn.execute("SAVEPOINT actor_ops_media_cache")
    try:
        ports.media_cache_service(store, data_dir=data_dir).cache_items(
            workspace_id=job["workspace_id"],
            user_id=job["user_id"],
            items=items,
            commit=commit,
            media_cleanup=(stage_cleanup if not commit else None),
        )
        if savepoint:
            conn.execute("RELEASE actor_ops_media_cache")
            publication_cleanup.absorb(stage_cleanup)
    except Exception:
        if savepoint:
            conn.execute("ROLLBACK TO actor_ops_media_cache")
            conn.execute("RELEASE actor_ops_media_cache")
        elif conn.in_transaction:
            conn.rollback()
        stage_cleanup.discard()
        ports.log_warning(
            "media cache failed job_id=%s; content finalization will continue",
            job.get("id"),
        )


def _emit_avatar_refresh(
    job: dict[str, Any],
    refresh: Any,
    *,
    ports: WorkerMediaPorts,
) -> None:
    event_outcome = {
        "stored": "succeeded",
        "unchanged": "skipped",
        "candidate_missing": "skipped",
        "kept_previous": "partial",
        "failed": "failed",
        "identity_mismatch": "denied",
    }.get(refresh.status, "unavailable")
    ports.emit_operation_event(
        category="source",
        action="avatar_cache",
        outcome=event_outcome,
        level=(
            "warning"
            if refresh.status in {"kept_previous", "failed", "identity_mismatch"}
            else "info"
        ),
        workspace_id=str(job["workspace_id"]),
        subject_user_id=str(job["user_id"]),
        job_id=str(job["id"]),
        source_id=refresh.source_id,
        error_code=(
            refresh.status
            if refresh.status not in {"stored", "unchanged", "candidate_missing"}
            else None
        ),
    )


def cache_run_source_avatars(
    job: dict[str, Any],
    *,
    data_dir: str,
    store: ServiceStore,
    result: Any,
    ports: WorkerMediaPorts,
    commit: bool = True,
    publication_cleanup: PostCommitMediaCleanup | None = None,
) -> None:
    """Persist source-level avatar evidence without changing the Feed outcome."""

    conn = store.connect()
    savepoint = not commit and conn.in_transaction
    if not commit and publication_cleanup is None:
        raise RuntimeError(
            "publication_cleanup is required inside an outer transaction"
        )
    stage_cleanup = PostCommitMediaCleanup()
    if savepoint:
        conn.execute("SAVEPOINT actor_ops_avatar_cache")
    try:
        refreshes = ports.source_avatar_service(
            store,
            data_dir=data_dir,
        ).refresh_run_result(
            workspace_id=str(job["workspace_id"]),
            result=result,
            commit=commit,
            media_cleanup=(stage_cleanup if not commit else None),
        )
        if savepoint:
            conn.execute("RELEASE actor_ops_avatar_cache")
            publication_cleanup.absorb(stage_cleanup)
    except Exception:
        if savepoint:
            conn.execute("ROLLBACK TO actor_ops_avatar_cache")
            conn.execute("RELEASE actor_ops_avatar_cache")
        elif conn.in_transaction:
            conn.rollback()
        stage_cleanup.discard()
        ports.log_warning(
            "source avatar cache failed job_id=%s; feed finalization will continue",
            job.get("id"),
        )
        return
    for refresh in refreshes:
        _emit_avatar_refresh(job, refresh, ports=ports)
