"""Stable Worker Job type boundaries during ActorOps v1 retirement."""

from __future__ import annotations


_LEGACY_ACTOROPS_JOB_PREFIX = "apify_actor_"

RETIRED_ACTOROPS_V1_JOB_TYPES = frozenset(
    _LEGACY_ACTOROPS_JOB_PREFIX + suffix
    for suffix in ("discovery", "validation", "canary_batch", "freshness_check")
)

ACTOROPS_V2_JOB_TYPES = frozenset(
    {
        "actorops_v2_discovery",
        "actorops_v2_maintenance",
        "actorops_v2_replacement",
        "actorops_v2_repair",
        "actorops_v2_metadata_refresh",
    }
)

WORKER_CLAIMABLE_JOB_TYPES = frozenset(
    {
        "source_test",
        "source_fetch",
        "user_feed_refresh",
        "content_repair",
        *ACTOROPS_V2_JOB_TYPES,
    }
)


__all__ = [
    "ACTOROPS_V2_JOB_TYPES",
    "RETIRED_ACTOROPS_V1_JOB_TYPES",
    "WORKER_CLAIMABLE_JOB_TYPES",
]
