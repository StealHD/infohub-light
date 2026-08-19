"""Batch-level Canary state must not inherit unrelated route history."""

import hashlib

from test_apify_actor_pool_staging_v18 import (
    FIXED_NOW,
    _approve_stage,
    _discovery_with_revisions,
    _revision,
    _route,
    _set_lifecycle,
)

from src.services.apify_actor_ops import (
    BATCH_CANARY_CONFIRMATION,
    PAID_CANARY_CONFIRMATION,
    ApifyActorOpsService,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _record_prior_route_success(
    ops: ApifyActorOpsService,
    route: dict,
    revision_id: str,
    *,
    suffix: str,
) -> None:
    validation = ops.approve_revision_canary(
        str(route["route_id"]),
        revision_id,
        expected_generation=int(route["generation"]),
        approval_id=f"prior-proof-{suffix}-route-evidence",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(
            f"prior-reference-{suffix}".encode()
        ).hexdigest(),
    )
    ops.record_validation(
        str(validation["validation_id"]),
        status="succeeded",
        semantic_outcome="valid_nonempty",
        cost_usd=0.01,
        cost_final=True,
        counts_toward_canary=True,
    )


def test_failed_stage_batch_does_not_count_historical_route_successes(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="batch-local-counter-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = _route(store, "youtube/channel/items")
    primary = _revision(
        ops,
        str(route["route_id"]),
        actor_id="prior-a/youtube-primary",
        publisher="prior-a",
        build_number="61.0.1",
        host="youtube.com",
    )
    backup = _revision(
        ops,
        str(route["route_id"]),
        actor_id="prior-b/youtube-backup",
        publisher="prior-b",
        build_number="61.0.2",
        host="youtube.com",
    )
    for suffix, revision_id in (("a", primary), ("b", backup)):
        _record_prior_route_success(ops, route, revision_id, suffix=suffix)
        _set_lifecycle(store, revision_id, "certified")
    active = ops.replace_active_pool(
        str(route["route_id"]),
        slots={"primary": primary, "backup_1": backup, "backup_2": None},
        expected_generation=int(route["generation"]),
    )
    run, _revisions = _discovery_with_revisions(
        store,
        ops,
        active,
        (("new/youtube-third", "new"),),
        host="youtube.com",
    )
    _plan, batch = _approve_stage(
        ops,
        str(owner["id"]),
        str(run["run_id"]),
        goal="complete_third",
        approval_id="failed-batch-counts-only-itself",
    )
    item = batch["items"][0]
    ops.record_validation(
        str(item["validation_id"]),
        status="failed",
        semantic_outcome="apify_actor_contract_mismatch",
        cost_usd=0.01,
        cost_final=True,
    )
    ops.update_canary_batch_item(
        str(batch["batch_id"]),
        int(item["ordinal"]),
        status="failed",
        semantic_outcome="apify_actor_contract_mismatch",
        actual_cost_usd=0.01,
        cost_final=True,
    )

    finalized = ops.finalize_canary_batch(str(batch["batch_id"]))

    assert finalized["status"] == "partial"
    assert finalized["success_count"] == 0
    assert finalized["publisher_count"] == 0
