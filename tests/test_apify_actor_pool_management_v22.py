"""Pool-management regressions stay isolated from the legacy staging suite."""

from test_apify_actor_ops_api import _client, _login, _ready_route
from test_apify_actor_pool_staging_v18 import (
    FIXED_NOW,
    _revision,
    _route,
    _set_lifecycle,
    _ready_source,
    _two_actor_pool,
)

from src.services.apify_actor_ops import ApifyActorOpsService
from src.services.apify_actor_pool_management import (
    ROUTE_POOL_REMOVE_CONFIRMATION,
)
from src.storage.service_store import ServiceStore


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
