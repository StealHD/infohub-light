from __future__ import annotations

from src.services.worker_actorops_v2_jobs import actorops_v2_job_handlers
from src.services.worker_job_policy import (
    ACTOROPS_V2_JOB_TYPES,
    WORKER_CLAIMABLE_JOB_TYPES,
)


def test_every_actorops_v2_handler_is_claimable_by_the_worker() -> None:
    registered = frozenset(actorops_v2_job_handlers({}))

    assert ACTOROPS_V2_JOB_TYPES == registered
    assert ACTOROPS_V2_JOB_TYPES <= WORKER_CLAIMABLE_JOB_TYPES
