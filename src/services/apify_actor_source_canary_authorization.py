"""Authorization boundary for source Canary retries of active Actor slots."""

from __future__ import annotations

from typing import Any


def source_canary_candidate_authorized(row: Any) -> bool:
    """Permit only the stale executable-state recovery to probe an open slot."""

    lifecycle, state = map(str, (row["lifecycle"], row["candidate_state"]))
    return lifecycle in {"certified", "probationary", "legacy_builtin"} and (
        state in {"closed", "half_open", "probationary"}
        or state == "open"
        and str(row["candidate_last_error_code"] or "")
        == "apify_actor_revision_not_executable"
    )
