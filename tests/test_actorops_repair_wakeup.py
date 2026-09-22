"""Regression coverage for settled attempts leaving legacy repair blockers."""
import json
import logging

import pytest

from src.logging_utils import configure_logging
from src.storage.service_store import DEFAULT_WORKSPACE_ID
from test_actorops_v2_resilience import _repository


BLOCKERS = (
    "actorops_cost_settlement_required",
    "actorops_repair_cost_settlement_required",
    "actorops_result_recovery_required",
    "apify_start_outcome_unknown",
)


def authorize(store):
    store.create_user(workspace_id=DEFAULT_WORKSPACE_ID, username="repair-owner",
                      password="safe-test-password", role="owner")
    conn = store.connect()
    owner = conn.execute("SELECT id FROM users WHERE username='repair-owner'").fetchone()
    conn.execute("""UPDATE actor_maintenance_policies_v2 SET enabled=1,
        authorized_by_user_id=?, authorized_at='2026-08-24T00:00:00+00:00'
        WHERE workspace_id=?""", (owner["id"], DEFAULT_WORKSPACE_ID))
    conn.commit()


def repair(repository, route_id, source_id, code):
    return repository.resilience.ensure_repair(
        route_id=route_id, source_id=source_id, origin_job_id="job-original",
        trigger_code="actorops_route_exhausted", blocked_code=code,
    )


@pytest.mark.parametrize("code", BLOCKERS)
def test_settlement_wakes_old_codes_and_next_fetch_clears_stale_reason(tmp_path, code):
    store, repo, route_id, source_id = _repository(tmp_path)
    try:
        authorize(store)
        original = repair(repo, route_id, source_id, code)
        assert original["status"] == "blocked"
        assert repo.resilience.wake_repairs_after_cost_settlement(route_id, source_id) == 1
        woken = repo.resilience.get_repair(original["repair_id"])
        assert woken["status"] == "blocked"  # A wakeup grants no execution permission.
        assert woken["next_attempt_at"] < original["next_attempt_at"]
        current = repair(repo, route_id, source_id, None)
        assert current["repair_id"] == original["repair_id"]
        assert (current["status"], current["error_code"]) == ("queued", None)
        assert repo.resilience.advance_repair(current["repair_id"])["status"] == "recovered"
    finally:
        store.close()


@pytest.mark.parametrize("code", BLOCKERS)
def test_woken_repair_still_requires_current_authorization(tmp_path, code):
    store, repo, route_id, source_id = _repository(tmp_path)
    try:
        original = repair(repo, route_id, source_id, code)
        repo.resilience.wake_repairs_after_cost_settlement(route_id, source_id)
        current = repo.resilience.advance_repair(original["repair_id"])
        assert (current["status"], current["error_code"]) == (
            "blocked", "actorops_repair_not_authorized")
        assert current["discovery_id"] is None
        assert repo.resilience.wake_repairs_after_cost_settlement(route_id, source_id) == 0
    finally:
        store.close()


@pytest.mark.parametrize("cost_final", (False, True))
def test_wakeup_keeps_unfinished_attempt_barrier_and_distinguishes_cost(tmp_path, cost_final):
    store, repo, route_id, source_id = _repository(tmp_path)
    try:
        authorize(store)
        original = repair(repo, route_id, source_id, BLOCKERS[0])
        with repo.transaction():
            repo.create_attempt(attempt_id="pending", idempotency_key="a" * 64,
                route_id=route_id, source_id=source_id, candidate_id="candidate-0",
                kind="fetch", attempt_group_id="group", attempt_index=0,
                route_generation=1, binding_version=1, target_fingerprint="b" * 64,
                reserved_usd=0.01)
            if cost_final:
                repo.observe_attempt_result("pending", remote_run_id="run", dataset_id="dataset",
                    actual_cost_usd=0.001, cost_final=True)
        repo.resilience.wake_repairs_after_cost_settlement(route_id, source_id)
        current = repo.resilience.advance_repair(original["repair_id"])
        expected = "actorops_result_recovery_required" if cost_final else BLOCKERS[1]
        assert (current["status"], current["error_code"]) == ("blocked", expected)
        assert current["discovery_id"] is None
    finally:
        store.close()


def test_blocked_trace_is_written_to_both_diagnostic_sinks(tmp_path):
    store, repo, route_id, source_id = _repository(tmp_path)
    paths = configure_logging(tmp_path / "logs", service="worker")
    try:
        repo.resilience.emit(root_job_id="job-blocked", route_id=route_id,
            source_id=source_id, phase="route_repair", outcome="blocked",
            reason_code="actorops_cost_settlement_required")
        events, _, completeness = repo.resilience.execution_events(root_job_id="job-blocked")
        assert completeness == "complete"
        assert events[0]["outcome"] == "blocked"
        lines = paths["operations"].read_text().splitlines()
        event = next(json.loads(line) for line in lines if "job-blocked" in line)
        assert event["outcome"] == "unavailable"
        assert event["error_code"] == "actorops_cost_settlement_required"
    finally:
        store.close()
        for logger in (logging.getLogger(), logging.getLogger("inteliscope.operations")):
            for handler in list(logger.handlers):
                if getattr(handler, "_inteliscope_managed_handler", False):
                    logger.removeHandler(handler)
                    handler.close()
