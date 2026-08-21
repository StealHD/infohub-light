"""Pool planning must use the same exact-revision guard as execution."""

import hashlib

import pytest

from test_apify_actor_pool_staging_v18 import (
    FIXED_NOW,
    _revision,
    _route,
    _two_actor_pool,
)

from src.services.apify_actor_ops import (
    ActorOpsError,
    PAID_CANARY_CONFIRMATION,
    ApifyActorOpsService,
)
from src.storage.service_store import ServiceStore


def test_pool_plan_rejects_open_revision_with_settled_route_failure(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    active, _ = _two_actor_pool(store, ops)
    route_id = str(active["route_id"])
    run = ops.create_discovery_run(
        route_id,
        trigger_reason="exact-revision-plan-authorization",
        expected_generation=int(active["generation"]),
    )
    revision_id = _revision(
        ops,
        route_id,
        actor_id="publisher-c/youtube-failed-exact-revision",
        publisher="publisher-c",
        build_number="32.0.1",
        host="youtube.com",
        discovery_run_id=str(run["run_id"]),
    )
    candidate_id = str(store.connect().execute(
        "SELECT candidate_id FROM apify_actor_adapter_revisions WHERE revision_id = ?",
        (revision_id,),
    ).fetchone()["candidate_id"])
    store.connect().execute(
        "UPDATE apify_actor_candidates SET state = 'open' WHERE id = ?",
        (candidate_id,),
    )
    store.connect().commit()
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="queued",
        stage="awaiting_canary_approval",
    )
    validation = ops.approve_revision_canary(
        route_id,
        revision_id,
        expected_generation=int(active["generation"]),
        approval_id="failed-exact-revision",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"failed-exact-revision").hexdigest(),
        discovery_run_id=str(run["run_id"]),
    )
    ops.record_validation(
        str(validation["validation_id"]),
        status="failed",
        semantic_outcome="apify_actor_run_failed",
        cost_usd=0.01,
        cost_final=True,
    )

    with pytest.raises(ActorOpsError) as excinfo:
        ops.get_canary_plan(
            str(run["run_id"]),
            goal="replace_slot",
            target_slot="primary",
            candidate_ids=[candidate_id],
            target_slot_count=3,
        )
    assert excinfo.value.code == "apify_actor_manual_candidate_stale"
