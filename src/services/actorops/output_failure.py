"""Classify Actor output errors without over-promoting transient evidence."""

from __future__ import annotations

from ..apify_actor_manifest import ActorManifestError


_RECOVERABLE_OUTPUT_CODES = frozenset({
    "apify_actor_metadata_only",
    "apify_actor_output_outside_window",
    "apify_actor_placeholder",
    "apify_actor_target_deleted",
    "apify_actor_target_identity_mismatch",
    "apify_actor_target_not_found",
    "apify_actor_target_private",
})
_CONTRACT_INVALID = "actorops_v2_candidate_contract_invalid"


def candidate_output_error_code(error: Exception) -> str:
    """Keep bounded semantic evidence while collapsing actual contract drift."""

    if isinstance(error, ActorManifestError) and error.code in _RECOVERABLE_OUTPUT_CODES:
        return error.code
    return _CONTRACT_INVALID


__all__ = ["candidate_output_error_code"]
