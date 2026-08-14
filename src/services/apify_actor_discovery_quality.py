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


def persist_revision_store_quality(ops: Any, revision_id: str, actor: Mapping[str, Any]) -> None:
    """Persist an optional public Store snapshot after static validation."""

    evidence_update = store_quality_evidence(actor)
    if not evidence_update:
        return
    with ops._write() as connection:
        row = connection.execute(
            """SELECT security_evidence_json FROM apify_actor_adapter_revisions
               WHERE workspace_id = ? AND revision_id = ?""",
            (ops.workspace_id, revision_id),
        ).fetchone()
        if row is None:
            return
        evidence = ops._safe_json(row["security_evidence_json"], {})
        if evidence.get("store_quality") == evidence_update["store_quality"]:
            return
        evidence.update(evidence_update)
        connection.execute(
            """UPDATE apify_actor_adapter_revisions SET security_evidence_json = ?
               WHERE workspace_id = ? AND revision_id = ?""",
            (ops._bounded_safe_json(evidence, max_bytes=16 * 1024), ops.workspace_id, revision_id),
        )


__all__ = ["persist_revision_store_quality", "rank_discovery_candidates"]
