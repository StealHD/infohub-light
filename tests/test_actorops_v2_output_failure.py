from __future__ import annotations

import pytest

from src.services.apify_actor_manifest import ActorManifestError
from src.services.actorops.output_failure import candidate_output_error_code


@pytest.mark.parametrize(
    "code",
    (
        "apify_actor_metadata_only",
        "apify_actor_output_outside_window",
        "apify_actor_placeholder",
        "apify_actor_target_deleted",
        "apify_actor_target_identity_mismatch",
        "apify_actor_target_not_found",
        "apify_actor_target_private",
    ),
)
def test_semantic_output_error_keeps_its_specific_code(code: str) -> None:
    error = ActorManifestError(code, "safe message", retryable=True)
    assert candidate_output_error_code(error) == code


@pytest.mark.parametrize(
    "error",
    (
        ActorManifestError("apify_actor_contract_mismatch", "safe message"),
        ValueError("unexpected adapter failure"),
    ),
)
def test_contract_or_unknown_error_stays_hard_failure(error: Exception) -> None:
    assert (
        candidate_output_error_code(error)
        == "actorops_v2_candidate_contract_invalid"
    )
