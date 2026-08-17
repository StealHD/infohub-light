from __future__ import annotations

from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import ServiceStore


def _trial(ops: ApifyActorOpsService, route_id: str, run_id: str, actor_id: str, publisher: str) -> str:
    return ops.ensure_compatibility_trial_revision(
        route_id=route_id,
        discovery_run_id=run_id,
        actor_id=actor_id,
        publisher=publisher,
        build_id=f"build-{publisher}",
        build_number="1.0.0",
        pricing={"minimalMaxTotalChargeUsd": 0.01},
        permission_level="limited",
        input_schema_hash=None,
        output_schema_hash=None,
        compatibility_preflight_version=2,
        free_input_validated=True,
        output_schema_proves_items=True,
        x_profile_semantics_proven=True,
    )


def test_x_slot_server_plan_skips_active_members_and_selects_the_trial(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = next(item for item in ops.list_routes() if item["route_key"] == "x/profile")
    route_id = str(route["route_id"])
    run = ops.create_discovery_run(
        route_id, trigger_reason="slot-selection-test", expected_generation=int(route["generation"])
    )
    active_revisions = [
        _trial(ops, route_id, str(run["run_id"]), f"active/{name}", f"active-{name}")
        for name in ("one", "two", "three")
    ]
    trial_revision = _trial(ops, route_id, str(run["run_id"]), "trial/selected", "trial")
    active = ops.replace_active_pool(
        route_id,
        slots=dict(zip(("primary", "backup_1", "backup_2"), active_revisions, strict=True)),
        expected_generation=int(route["generation"]),
        allow_compatibility_single=True,
    )
    ops.update_discovery_run(
        str(run["run_id"]), expected_stage="queued", stage="candidate_shortfall", error_code="candidate_shortfall"
    )

    plan = ops.get_canary_plan(str(run["run_id"]), goal="replace_slot", target_slot="backup_1")
    trial_candidate = store.connect().execute(
        "SELECT candidate_id FROM apify_actor_adapter_revisions WHERE revision_id = ?", (trial_revision,)
    ).fetchone()["candidate_id"]
    assert plan["selection_mode"] == "server"
    assert plan["items"][0]["candidate_id"] == trial_candidate
    listed = ops.list_pool_candidates(route_id, goal="replace_slot", target_slot="backup_1")
    active_ids = {slot["candidate_id"] for slot in active["slots"]}
    assert all(
        item["unavailable_reason"] == "actor_already_active"
        for item in listed["candidates"] if item["candidate_id"] in active_ids
    )
