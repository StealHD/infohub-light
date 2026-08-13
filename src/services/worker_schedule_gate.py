"""Runtime gate for local maintenance windows that must not enqueue schedules."""

from __future__ import annotations

import os


def worker_schedule_polling_enabled() -> bool:
    """Return whether the resident Worker may enqueue user schedules.

    The default keeps normal production behavior. Local ActorOps acceptance can
    set the variable to ``false`` so the Worker keeps its health/reconcile
    duties but does not create unrelated scheduled source jobs.
    """

    value = os.getenv("HORIZON_SCHEDULE_POLL_ENABLED", "true").strip().casefold()
    return value not in {"0", "false", "no", "off"}
