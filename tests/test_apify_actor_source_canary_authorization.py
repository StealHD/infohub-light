from src.services.apify_actor_source_canary_authorization import (
    source_canary_candidate_authorized,
)


def test_only_stale_executable_open_slots_can_run_source_canary() -> None:
    row = {
        "lifecycle": "probationary",
        "candidate_state": "open",
        "candidate_last_error_code": "apify_actor_revision_not_executable",
    }
    assert source_canary_candidate_authorized(row)
    assert not source_canary_candidate_authorized({**row, "candidate_last_error_code": "apify_actor_contract_mismatch"})
    assert not source_canary_candidate_authorized({**row, "candidate_state": "disabled"})
    assert not source_canary_candidate_authorized({**row, "lifecycle": "rejected"})
