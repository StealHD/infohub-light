"""The browser catalog contains only settled, directly activatable Actors."""

from test_apify_actor_pool_staging_v18 import (
    FIXED_NOW,
    _approve_stage,
    _discovery_with_revisions,
    _ready_source,
    _succeed_route_items,
    _succeed_stage_sources,
    _two_actor_pool,
)

from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def test_verified_catalog_hides_pending_inventory_and_activates_without_a_new_run(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route, active_revisions = _two_actor_pool(store, ops)
    route_id = str(route["route_id"])
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="verified-catalog-owner",
        password="safe-test-password",
        role="owner",
    )
    source_id, _binding = _ready_source(
        store, ops, route, active_revisions, suffix="verified-catalog"
    )
    run, revisions = _discovery_with_revisions(
        store,
        ops,
        route,
        (("publisher-c/youtube-verified", "publisher-c"),),
        host="youtube.com",
    )
    revision_id = revisions[0]
    candidate_id = str(
        store.connect().execute(
            "SELECT candidate_id FROM apify_actor_adapter_revisions WHERE revision_id = ?",
            (revision_id,),
        ).fetchone()["candidate_id"]
    )
    plan, batch = _approve_stage(
        ops,
        str(owner["id"]),
        str(run["run_id"]),
        goal="complete_third",
        approval_id="verified-catalog-proof",
    )
    pending = ops.list_verified_pool_candidates(
        route_id, goal="complete_third"
    )
    assert pending["candidates"] == []
    assert pending["candidate_count"] == 0
    assert pending["candidate_shortfall"] == 1

    _succeed_route_items(store, ops, batch)
    _succeed_stage_sources(ops, str(batch["pool_stage_id"]))
    ops.finalize_canary_batch(str(batch["batch_id"]))
    catalog = ops.list_verified_pool_candidates(
        route_id, goal="complete_third"
    )
    assert [item["candidate_id"] for item in catalog["candidates"]] == [candidate_id]
    assert catalog["candidates"][0]["already_validated"] is True
    assert catalog["candidate_count"] == 1
    assert catalog["candidate_shortfall"] == 0
    runs_before = store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0]

    activated = ops.activate_verified_pool_candidates(
        route_id,
        run_id=str(run["run_id"]),
        goal="complete_third",
        candidate_ids=[candidate_id],
        expected_generation=int(route["generation"]),
        target_slot_count=3,
        apply_id="verified-catalog-apply-0001",
        confirmation="确认启用 Actor 主备",
    )

    assert [slot["revision_id"] for slot in activated["slots"]] == [
        active_revisions[0], active_revisions[1], revision_id,
    ]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0] == runs_before
    assert ops.get_source_binding(source_id)["validation_status"] == "ready_3of3"


def test_stage_activation_reopens_a_verified_unchanged_slot(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route, active_revisions = _two_actor_pool(store, ops)
    route_id = str(route["route_id"])
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="verified-reopen-owner",
        password="safe-test-password",
        role="owner",
    )
    _source_id, _binding = _ready_source(
        store, ops, route, active_revisions, suffix="verified-reopen"
    )
    run, revisions = _discovery_with_revisions(
        store,
        ops,
        route,
        (("publisher-c/youtube-reopen", "publisher-c"),),
        host="youtube.com",
    )
    plan, batch = _approve_stage(
        ops,
        str(owner["id"]),
        str(run["run_id"]),
        goal="complete_third",
        approval_id="verified-reopen-proof",
    )
    _succeed_route_items(store, ops, batch)
    _succeed_stage_sources(ops, str(batch["pool_stage_id"]))
    ops.finalize_canary_batch(str(batch["batch_id"]))
    primary_candidate = store.connect().execute(
        "SELECT candidate_id FROM apify_route_active_slots WHERE route_id = ? AND slot_name = 'primary'",
        (route_id,),
    ).fetchone()["candidate_id"]
    store.connect().execute(
        "UPDATE apify_actor_candidates SET state = 'open' WHERE id = ?",
        (primary_candidate,),
    )
    store.connect().commit()

    ops.activate_verified_pool_candidates(
        route_id,
        run_id=str(run["run_id"]),
        goal="complete_third",
        candidate_ids=[str(store.connect().execute(
            "SELECT candidate_id FROM apify_actor_adapter_revisions WHERE revision_id = ?",
            (revisions[0],),
        ).fetchone()["candidate_id"])],
        expected_generation=int(route["generation"]),
        target_slot_count=3,
        apply_id="verified-catalog-apply-0002",
        confirmation="确认启用 Actor 主备",
    )

    assert store.connect().execute(
        "SELECT state FROM apify_actor_candidates WHERE id = ?",
        (primary_candidate,),
    ).fetchone()["state"] == "closed"
