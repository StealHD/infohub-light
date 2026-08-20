"""Best-effort continuation hooks for automated Actor pool workflows."""

from __future__ import annotations

import logging
from typing import Any

from ..storage.service_store import ServiceStore


logger = logging.getLogger(__name__)


def _advance(
    job: dict[str, Any],
    store: ServiceStore,
    reference_id: str,
    *,
    continuation_name: str,
    stage: str,
) -> None:
    if not reference_id:
        return
    try:
        from . import apify_actor_auto_pool
        from .apify_actor_ops import ApifyActorOpsService

        ops = ApifyActorOpsService(store, workspace_id=str(job["workspace_id"]))
        continuation = getattr(apify_actor_auto_pool, continuation_name)
        continuation(
            ops,
            reference_id,
            admin_user_id=str(job.get("user_id") or ""),
        )
    except Exception:
        logger.warning(
            "auto_pool_%s_failed job_id=%s",
            stage,
            str(job.get("id") or ""),
            exc_info=True,
        )


def advance_auto_pool_after_canary(
    job: dict[str, Any],
    store: ServiceStore,
    batch_id: str,
) -> None:
    _advance(
        job,
        store,
        batch_id,
        continuation_name="advance_after_canary",
        stage="advance_after_canary",
    )


def advance_auto_pool_after_discovery(
    job: dict[str, Any],
    store: ServiceStore,
    run_id: str,
) -> None:
    _advance(
        job,
        store,
        run_id,
        continuation_name="advance_after_discovery",
        stage="advance_after_discovery",
    )
