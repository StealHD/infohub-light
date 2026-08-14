"""Store-quality enrichment kept outside the legacy discovery runner."""

from __future__ import annotations

from collections.abc import Callable, Mapping, Sequence
from typing import Any, TypeVar

from .apify_actor_candidate_quality import (
    actor_store_quality,
    discovery_candidate_sort_key,
    store_quality_evidence,
    with_store_quality,
)


T = TypeVar("T")


def rank_discovery_candidates(
    candidates: Sequence[T],
    store_hits: Mapping[str, Mapping[str, Any]],
    preferred_actor_ids: set[str],
    output_schema_proves_items: Callable[[Mapping[str, Any]], bool],
) -> list[T]:
    """Attach public Store evidence, then prefer usable, established Actors."""

    enriched = [
        with_store_quality(candidate, store_hits.get(candidate.actor_id))
        for candidate in candidates
    ]
    return sorted(
        enriched,
        key=lambda candidate: discovery_candidate_sort_key(
            candidate.actor_id,
            actor_store_quality(candidate.actor),
            preferred=candidate.actor_id in preferred_actor_ids,
            output_schema_proves_items=output_schema_proves_items(
                candidate.output_schema
            ),
        ),
    )


def discovery_revision_security_evidence(
    actor: Mapping[str, Any],
    *,
    output_schema_proves_items: bool,
) -> dict[str, Any]:
    """Freeze Store quality with the immutable Revision's static evidence."""

    return {
        "public": actor.get("isPublic") is True,
        "store_unrunnable_actors_excluded": True,
        "not_deprecated": actor.get("isDeprecated") is False,
        "limited_permissions": True,
        "exact_successful_build": True,
        "input_validation": True,
        "output_schema_proves_items": output_schema_proves_items,
        **store_quality_evidence(actor),
    }


__all__ = ["discovery_revision_security_evidence", "rank_discovery_candidates"]
