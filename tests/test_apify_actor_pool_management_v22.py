"""Pool-management regressions stay isolated from the legacy staging suite."""

import hashlib

from test_apify_actor_ops_api import _client, _login, _ready_route
from test_apify_actor_pool_staging_v18 import (
    BATCH_CANARY_CONFIRMATION,
    _discovery_with_revisions,
    FIXED_NOW,
    _revision,
    _route,
    _set_lifecycle,
    _ready_source,
    _two_actor_pool,
)

from src.services.apify_actor_ops import ApifyActorOpsService
from src.api.actor_ops_projection import public_canary_plan
from src.services.apify_actor_pool_management import (
    ROUTE_POOL_REMOVE_CONFIRMATION,
    ROUTE_POOL_PROMOTE_CONFIRMATION,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def test_route_price_cap_does_not_require_a_prior_pool_activation(tmp_path, monkeypatch) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    route = _route(store, "youtube/channel/items")
    response = client.patch(
        f"/api/admin/apify-routes/{route['route_id']}/price-cap",
        json={"expected_generation": route["generation"], "per_run_cap_usd": 0.10},
    )
    assert response.status_code == 200, response.text
    assert response.json()["data"]["per_run_cap_usd"] == 0.10


def test_slot_operations_freeze_target_and_compact_pool(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    seeded = _route(store, "x/profile")
    revisions = [
        _revision(
            ops, str(seeded["route_id"]), actor_id=f"publisher-{name}/x-{name}",
            publisher=f"publisher-{name}", build_number=f"31.0.{index}", host="x.com",
        )
        for index, name in enumerate(("a", "b", "c"), start=1)
    ]
    for revision_id in revisions:
        _set_lifecycle(store, revision_id, "certified")
    active = ops.replace_active_pool(
        str(seeded["route_id"]),
        slots=dict(zip(("primary", "backup_1", "backup_2"), revisions, strict=True)),
        expected_generation=int(seeded["generation"]),
    )
    assert ops.slot_operations(str(active["route_id"]))["backup_2"]["remove"]
    removed = ops.remove_active_pool_slot(
        str(active["route_id"]), target_slot="backup_1",
        expected_generation=int(active["generation"]),
        confirmation=ROUTE_POOL_REMOVE_CONFIRMATION,
    )
    assert [slot["revision_id"] for slot in removed["slots"]] == [
        revisions[0], revisions[2], None,
    ]


def test_add_plan_binds_requested_slot_to_hash(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    active, _ = _two_actor_pool(store, ops)
    route_id = str(active["route_id"])
    run = ops.create_discovery_run(
        route_id, trigger_reason="slot-operation-plan",
        expected_generation=int(active["generation"]),
    )
    revision_id = _revision(
        ops, route_id, actor_id="publisher-c/youtube-slot-operation",
        publisher="publisher-c", build_number="32.0.1", host="youtube.com",
        discovery_run_id=str(run["run_id"]),
    )
    candidate_id = str(store.connect().execute(
        "SELECT candidate_id FROM apify_actor_adapter_revisions WHERE revision_id = ?",
        (revision_id,),
    ).fetchone()["candidate_id"])
    ops.update_discovery_run(str(run["run_id"]), expected_stage="queued", stage="awaiting_canary_approval")
    plan = ops.get_canary_plan(
        str(run["run_id"]), goal="add_slot", target_slot="backup_2",
        candidate_ids=[candidate_id], target_slot_count=3,
    )
    assert (plan["operation_slot"], plan["target_slot_count"], plan["items"][0]["revision_id"]) == (
        "backup_2", 3, revision_id,
    )
    assert public_canary_plan(plan)["operation_slot"] == "backup_2"


def test_api_remove_is_cas_guarded_and_projects_slot_actions(tmp_path, monkeypatch) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, revisions = _ready_route(store, route_key="x/profile")
    url = f"/api/admin/apify-routes/{route['route_id']}"
    slots = client.get(url).json()["data"]["slots"]
    assert slots[0]["actions"]["replace"] and slots[2]["actions"]["remove"]
    assert client.post(f"{url}/active-pool/remove", json={
        "target_slot": "backup_2", "expected_generation": route["generation"], "confirmation": "移出",
    }).status_code == 400
    removed = client.post(f"{url}/active-pool/remove", json={
        "target_slot": "backup_2", "expected_generation": route["generation"],
        "confirmation": "确认移出 Actor 主备池",
    })
    assert removed.status_code == 200, removed.text
    assert [slot["revision_id"] for slot in removed.json()["data"]["slots"]] == [
        revisions[0], revisions[1], None,
    ]
    stale = client.post(f"{url}/active-pool/remove", json={
        "target_slot": "backup_1", "expected_generation": route["generation"],
        "confirmation": "确认移出 Actor 主备池",
    })
    assert stale.status_code == 409


def test_backup_can_be_selected_as_primary_without_spending(tmp_path, monkeypatch) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops, route, revisions = _ready_route(store, route_key="x/profile")
    url = f"/api/admin/apify-routes/{route['route_id']}"
    assert ops.slot_operations(str(route["route_id"]))["backup_1"]["promote"]
    assert ops.slot_operations(str(route["route_id"]))["primary"]["promote_reason"] == "primary_slot"
    denied = client.post(f"{url}/active-pool/promote", json={
        "target_slot": "backup_1", "expected_generation": route["generation"],
        "confirmation": "确认",
    })
    assert denied.status_code == 400
    promoted = client.post(f"{url}/active-pool/promote", json={
        "target_slot": "backup_1", "expected_generation": route["generation"],
        "confirmation": ROUTE_POOL_PROMOTE_CONFIRMATION,
    })
    assert promoted.status_code == 200, promoted.text
    assert [slot["revision_id"] for slot in promoted.json()["data"]["slots"]] == [
        revisions[1], revisions[0], revisions[2],
    ]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0] == 0


def test_route_price_cap_is_cas_guarded_and_does_not_replace_pool(tmp_path, monkeypatch) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, revisions = _ready_route(store, route_key="instagram/profile/items")
    url = f"/api/admin/apify-routes/{route['route_id']}"
    updated = client.patch(f"{url}/price-cap", json={
        "expected_generation": route["generation"], "per_run_cap_usd": 0.10,
    })
    assert updated.status_code == 200, updated.text
    data = updated.json()["data"]
    assert data["per_run_cap_usd"] == 0.10
    assert [slot["revision_id"] for slot in data["slots"]] == revisions
    stale = client.patch(f"{url}/price-cap", json={
        "expected_generation": route["generation"], "per_run_cap_usd": 0.05,
    })
    assert stale.status_code == 409


def test_remove_reuses_only_retained_source_evidence(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route, revisions = _two_actor_pool(store, ops)
    source_id, ready = _ready_source(
        store, ops, route, revisions, suffix="pool-remove-evidence"
    )
    removed = ops.remove_active_pool_slot(
        str(route["route_id"]),
        target_slot="backup_1",
        expected_generation=int(route["generation"]),
        confirmation=ROUTE_POOL_REMOVE_CONFIRMATION,
    )
    assert [slot["revision_id"] for slot in removed["slots"]] == [
        revisions[0], None, None,
    ]
    binding = ops.get_source_binding(source_id)
    assert ready["validation_status"] == "ready_2of2"
    assert binding["validation_status"] == "ready_1of1"


def test_failed_replan_stage_does_not_lock_pool_removal(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="failed-replan-removal-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route, revisions = _two_actor_pool(store, ops)
    run, staged = _discovery_with_revisions(
        store,
        ops,
        route,
        (("publisher-c/youtube-failed-replan", "publisher-c"),),
        host="youtube.com",
    )
    candidate_id = str(store.connect().execute(
        """SELECT candidate_id FROM apify_actor_adapter_revisions
           WHERE workspace_id = ? AND revision_id = ?""",
        (DEFAULT_WORKSPACE_ID, staged[0]),
    ).fetchone()["candidate_id"])
    candidate = next(
        item for item in ops.list_pool_candidates(
            str(route["route_id"]), goal="replace_slot", target_slot="backup_1"
        )["candidates"]
        if item["candidate_id"] == candidate_id
    )
    profile = {
        "candidate_id": candidate_id,
        **candidate["validation_options"],
    }
    plan = ops.get_canary_plan(
        str(run["run_id"]),
        goal="replace_slot",
        target_slot="backup_1",
        candidate_ids=[candidate_id],
        candidate_validation_profiles=[profile],
        target_slot_count=2,
    )
    batch = ops.create_canary_batch(
        str(run["run_id"]),
        goal="replace_slot",
        target_slot="backup_1",
        candidate_ids=[candidate_id],
        candidate_validation_profiles=[profile],
        target_slot_count=2,
        expected_generation=int(plan["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        approval_id="failed-replan-removal-approval",
        confirmation=BATCH_CANARY_CONFIRMATION,
        max_candidates=1,
        max_total_charge_usd=float(plan["max_total_charge_usd"]),
        created_by_user_id=str(owner["id"]),
        reference_fingerprints={
            staged[0]: hashlib.sha256(
                f"reference:{staged[0]}".encode()
            ).hexdigest(),
        },
    )
    stage_id = str(batch["pool_stage_id"])
    store.connect().execute(
        """UPDATE apify_actor_pool_stages
           SET status = 'replan_required', last_error_code = 'candidate_shortfall'
           WHERE workspace_id = ? AND stage_id = ?""",
        (DEFAULT_WORKSPACE_ID, stage_id),
    )
    store.connect().commit()

    finalized = ops.finalize_canary_batch(str(batch["batch_id"]))
    assert finalized["status"] == "partial"
    assert finalized["stop_reason"] == "candidate_replenishment_required"
    workflow = ops.workflow_state(str(route["route_id"]))
    assert workflow["kind"] == "replace_slot_discovery_required"
    assert workflow["goal"] == "replace_slot"
    assert workflow["operation_slot"] == "backup_1"
    assert ops.slot_operations(str(route["route_id"]))["backup_1"]["remove"]
    removed = ops.remove_active_pool_slot(
        str(route["route_id"]),
        target_slot="backup_1",
        expected_generation=int(route["generation"]),
        confirmation=ROUTE_POOL_REMOVE_CONFIRMATION,
    )

    assert [slot["revision_id"] for slot in removed["slots"]] == [
        revisions[0], None, None,
    ]
    assert ops.get_pool_stage(stage_id)["status"] == "stale"


def test_remove_invalidates_ready_binding_when_retained_evidence_is_missing(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route, revisions = _two_actor_pool(store, ops)
    source_id, _ = _ready_source(
        store, ops, route, revisions, suffix="pool-remove-pending"
    )
    store.connect().execute(
        """DELETE FROM apify_actor_validations
           WHERE workspace_id = ? AND source_id = ? AND revision_id = ?""",
        (ops.workspace_id, source_id, revisions[0]),
    )
    store.connect().commit()
    ops.remove_active_pool_slot(
        str(route["route_id"]),
        target_slot="backup_1",
        expected_generation=int(route["generation"]),
        confirmation=ROUTE_POOL_REMOVE_CONFIRMATION,
    )
    binding = ops.get_source_binding(source_id)
    assert binding["validation_status"] == "pending"
    assert binding["verified_revision_set_hash"] is None
