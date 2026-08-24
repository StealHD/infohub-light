"""Small Worker registry for bounded ActorOps v2 control jobs."""

from __future__ import annotations

from typing import Any, Callable, Mapping

from .worker_actorops_v2_discovery import run_actorops_v2_discovery
from .worker_actorops_v2_maintenance import run_actorops_v2_maintenance
from .worker_actorops_v2_metadata import run_actorops_v2_metadata_refresh
from .worker_actorops_v2_replacement import run_actorops_v2_replacement
from .worker_actorops_v2_repair import run_actorops_v2_repair

_TRACE_POLICY = {
    "actorops_v2_discovery": "job_lifecycle_only",
    "actorops_v2_maintenance": "job_lifecycle_only",
    "actorops_v2_replacement": "job_lifecycle_only",
    "actorops_v2_repair": "job_lifecycle_only",
    "actorops_v2_metadata_refresh": "job_lifecycle_only",
}


def actorops_v2_job_trace_policy() -> dict[str, str]:
    return dict(_TRACE_POLICY)


def actorops_v2_job_handlers(
    handlers: Mapping[str, Callable[..., dict[str, Any]]],
) -> dict[str, Callable[..., dict[str, Any]]]:
    """Add low-priority ActorOps v2 jobs without enlarging the Worker façade."""

    merged = dict(handlers)
    merged.update(
        {
            "actorops_v2_discovery": run_actorops_v2_discovery,
            "actorops_v2_maintenance": run_actorops_v2_maintenance,
            "actorops_v2_replacement": run_actorops_v2_replacement,
            "actorops_v2_repair": run_actorops_v2_repair,
            "actorops_v2_metadata_refresh": run_actorops_v2_metadata_refresh,
        }
    )
    return merged
