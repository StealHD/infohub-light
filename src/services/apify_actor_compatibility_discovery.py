"""Compatibility-specific discovery orchestration outside the legacy runner."""

from __future__ import annotations

from collections.abc import Callable, Mapping, MutableSequence
from typing import Any

from .apify_actor_pool_compatibility import persist_compatibility_candidates


async def collect_x_compatibility_candidate(
    *,
    platform: str,
    service: Any,
    actor_id: str,
    per_run_cap_usd: float,
    allow_store_runnable_omission: bool,
    candidates: MutableSequence[Any],
    rejected: MutableSequence[dict[str, str]],
) -> None:
    """Append only a fully free-preflighted X Candidate.

    This keeps compatibility-only evidence out of the generic Discovery loop.
    The caller's typed error remains the authority; this module only forwards
    its stable public code into Discovery's existing rejection projection.
    """

    if platform != "x":
        return
    try:
        candidate = await service.load_compatibility_candidate(
            actor_id,
            per_run_cap_usd=per_run_cap_usd,
            allow_store_runnable_omission=allow_store_runnable_omission,
        )
    except Exception as error:
        code = str(getattr(error, "code", ""))
        if code == "apify_actor_metadata_authentication_failed":
            raise
        if not code:
            raise
        rejected.append({"actor_id": actor_id, "reason": code})
        return
    candidates.append(candidate)


def persist_x_compatibility_candidates(
    *,
    platform: str,
    ops: Any,
    route_id: str,
    discovery_run_id: str,
    candidates: list[Any],
    candidate_limit: int,
    preferred_actor_ids: set[str],
    store_search_actor_ids: set[str],
    pricing_summary: Callable[[Any], Mapping[str, Any]],
    schema_hash: Callable[[Mapping[str, Any]], str],
    input_dialect: Callable[[Any], str | None],
    input_count_field: Callable[[Any], str | None],
) -> None:
    """Persist only the Candidate list produced by the free X preflight."""

    if platform != "x":
        return
    persist_compatibility_candidates(
        ops=ops,
        route_id=route_id,
        discovery_run_id=discovery_run_id,
        candidates=candidates,
        candidate_limit=candidate_limit,
        preferred_actor_ids=preferred_actor_ids,
        store_search_actor_ids=store_search_actor_ids,
        pricing_summary=pricing_summary,
        schema_hash=schema_hash,
        input_dialect=input_dialect,
        input_count_field=input_count_field,
    )


__all__ = [
    "collect_x_compatibility_candidate",
    "persist_x_compatibility_candidates",
]
