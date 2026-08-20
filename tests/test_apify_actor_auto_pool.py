"""Automated Actor slot replacement orchestration regressions."""

import pytest

from test_apify_actor_pool_staging_v18 import FIXED_NOW, _route, _two_actor_pool

from src.services.apify_actor_auto_pool import (
    AUTO_POOL_BUDGET_CAP_USD,
    AUTO_POOL_REPLENISH_REASON,
    AUTO_POOL_TRIGGER_REASON,
    advance_auto_pool,
    get_auto_pool_run,
    start_auto_pool,
)
from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _admin_user(store: ServiceStore) -> str:
    existing = store.get_user_by_username("owner", workspace_id=DEFAULT_WORKSPACE_ID)
    if existing is not None:
        return str(existing["id"])
    return str(
        store.create_user(
            workspace_id=DEFAULT_WORKSPACE_ID,
            username="owner",
            password="secret-password",
            role="owner",
        )["id"]
    )


def _start(store: ServiceStore, ops: ApifyActorOpsService):
    _two_actor_pool(store, ops)
    route = _route(store, "youtube/channel/items")
    admin_user_id = _admin_user(store)
    run = start_auto_pool(
        ops,
        route_id=str(route["route_id"]),
        slot_name="backup_2",
        goal="add_slot",
        expected_generation=int(route["generation"]),
        admin_user_id=admin_user_id,
    )
    return route, run, admin_user_id


def test_start_auto_pool_creates_run_and_queues_discovery(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route, run, _admin = _start(store, ops)
    assert run["status"] == "running"
    assert run["goal"] == "add_slot"
    assert run["slot_name"] == "backup_2"
    assert run["budget_cap_usd"] == AUTO_POOL_BUDGET_CAP_USD
    discovery = ops.get_discovery_run(str(run["last_discovery_run_id"]))
    assert discovery["stage"] == "queued"
    assert discovery["trigger_reason"] == AUTO_POOL_TRIGGER_REASON
    # A discovery job was enqueued for the worker to claim.
    job = store.connect().execute(
        """SELECT id FROM fetch_jobs
           WHERE job_type = 'apify_actor_discovery'
             AND json_extract(payload_json, '$.run_id') = ?""",
        (str(run["last_discovery_run_id"]),),
    ).fetchone()
    assert job is not None


def test_advance_waits_while_discovery_in_flight(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    _route_, run, _admin = _start(store, ops)
    # Discovery is still queued: advance must not change the run or create work.
    advanced = advance_auto_pool(ops, str(run["run_id"]), admin_user_id=_admin)
    assert advanced["last_discovery_run_id"] == run["last_discovery_run_id"]
    assert advanced["last_canary_batch_id"] is None
    assert advanced["status"] == "running"


def test_advance_replenishes_discovery_on_shortfall(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    _route_, run, _admin = _start(store, ops)
    first_discovery = str(run["last_discovery_run_id"])
    ops.update_discovery_run(
        first_discovery,
        expected_stage="queued",
        stage="candidate_shortfall",
        error_code="canary_batch_candidates_exhausted",
    )
    advanced = advance_auto_pool(ops, str(run["run_id"]), admin_user_id=_admin)
    assert advanced["status"] == "running"
    assert advanced["last_discovery_run_id"] != first_discovery
    second = ops.get_discovery_run(str(advanced["last_discovery_run_id"]))
    assert second["trigger_reason"] == AUTO_POOL_REPLENISH_REASON
    assert second["stage"] == "queued"


def test_advance_marks_budget_exhausted_after_spend(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    _route_, run, _admin = _start(store, ops)
    run_id = str(run["run_id"])
    store.connect().execute(
        """UPDATE apify_actor_auto_pool_runs
           SET total_spent_usd = ? WHERE workspace_id = ? AND run_id = ?""",
        (AUTO_POOL_BUDGET_CAP_USD, DEFAULT_WORKSPACE_ID, run_id),
    )
    store.connect().commit()
    ops.update_discovery_run(
        str(run["last_discovery_run_id"]),
        expected_stage="queued",
        stage="candidate_shortfall",
        error_code="canary_batch_candidates_exhausted",
    )
    advanced = advance_auto_pool(ops, run_id, admin_user_id=_admin)
    assert advanced["status"] == "budget_exhausted"
    assert advanced["error_code"] == "apify_actor_auto_pool_budget_exhausted"
    # A settled run stays terminal across repeated advances.
    again = advance_auto_pool(ops, run_id, admin_user_id=_admin)
    assert again["status"] == "budget_exhausted"


def test_get_auto_pool_run_missing_raises(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    with pytest.raises(Exception):
        get_auto_pool_run(ops, "apify-auto-pool-does-not-exist")
