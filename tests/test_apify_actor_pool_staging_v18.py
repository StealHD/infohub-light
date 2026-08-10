from __future__ import annotations

import hashlib
from datetime import datetime, timezone

import pytest

from src.services.apify_actor_ops import (
    ActorOpsError,
    ApifyActorOpsService,
    BATCH_CANARY_CONFIRMATION,
    FIRST_ACTIVATION_CONFIRMATION,
    PAID_CANARY_CONFIRMATION,
    ROUTE_POOL_ACTIVATION_CONFIRMATION,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


FIXED_NOW = datetime(2030, 8, 9, 8, 0, tzinfo=timezone.utc)


def _manifest(actor_id: str, build_number: str, *, host: str) -> dict:
    return {
        "version": 1,
        "actor_id": actor_id,
        "build_number": build_number,
        "input": {
            "startUrls": [{"url": {"$ref": "target.canonical_url"}}],
            "maxItems": {"$ref": "runtime.max_items"},
        },
        "output": {
            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
            "published_at": {
                "pointers": ["/publishedAt"],
                "transforms": ["parse_datetime"],
            },
            "title": {"pointers": ["/title"], "transforms": ["to_string"]},
            "source_native_id": {
                "pointers": ["/sourceId"],
                "transforms": ["to_string"],
            },
        },
        "semantics": {
            "identity": {
                "output_field": "source_native_id",
                "target_ref": "target.native_id",
                "match": "exact",
            },
            "url_host_allowlist": [host],
        },
    }


def _route(store: ServiceStore, route_key: str):
    return store.connect().execute(
        """
        SELECT * FROM apify_actor_route_profiles
        WHERE workspace_id = ? AND route_key = ?
        """,
        (DEFAULT_WORKSPACE_ID, route_key),
    ).fetchone()


def _revision(
    ops: ApifyActorOpsService,
    route_id: str,
    *,
    actor_id: str,
    publisher: str,
    build_number: str,
    host: str,
    discovery_run_id: str | None = None,
    lifecycle: str = "static_valid",
) -> str:
    candidate_id = ops.ensure_candidate(route_id, actor_id=actor_id)
    return ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher=publisher,
        build_id=f"build-{build_number}",
        build_number=build_number,
        manifest=_manifest(actor_id, build_number, host=host),
        input_schema_hash=hashlib.sha256(f"in:{actor_id}".encode()).hexdigest(),
        output_schema_hash=hashlib.sha256(f"out:{actor_id}".encode()).hexdigest(),
        lifecycle=lifecycle,
        discovery_run_id=discovery_run_id,
    )


def _set_lifecycle(store: ServiceStore, revision_id: str, lifecycle: str) -> None:
    store.connect().execute(
        """
        UPDATE apify_actor_adapter_revisions
        SET lifecycle = ?, canary_passed_at = ?
        WHERE workspace_id = ? AND revision_id = ?
        """,
        (lifecycle, FIXED_NOW.isoformat(), DEFAULT_WORKSPACE_ID, revision_id),
    )
    store.connect().commit()


def _two_actor_pool(store: ServiceStore, ops: ApifyActorOpsService):
    seeded = _route(store, "youtube/channel/items")
    primary = _revision(
        ops,
        str(seeded["route_id"]),
        actor_id="publisher-a/youtube-primary",
        publisher="publisher-a",
        build_number="8.0.1",
        host="youtube.com",
    )
    backup = _revision(
        ops,
        str(seeded["route_id"]),
        actor_id="publisher-b/youtube-backup",
        publisher="publisher-b",
        build_number="8.0.2",
        host="youtube.com",
    )
    _set_lifecycle(store, primary, "certified")
    _set_lifecycle(store, backup, "certified")
    activated = ops.replace_active_pool(
        str(seeded["route_id"]),
        slots={"primary": primary, "backup_1": backup, "backup_2": None},
        expected_generation=int(seeded["generation"]),
    )
    return activated, (primary, backup)


def _ready_source(
    store: ServiceStore,
    ops: ApifyActorOpsService,
    route: dict,
    active_revisions: tuple[str, str],
    *,
    suffix: str,
) -> tuple[str, dict]:
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name=f"Staged source {suffix}",
        config={"platform": "youtube", "kind": "channel", "target": suffix},
    )
    binding = ops.bind_source(
        source_id=source_id,
        route_id=str(route["route_id"]),
        target_fingerprint=hashlib.sha256(f"target:{suffix}".encode()).hexdigest(),
        mode="fallback",
    )
    for revision_id in active_revisions:
        validation = ops.approve_source_canary(
            source_id,
            revision_id,
            expected_generation=int(binding["generation"]),
            approval_id=f"source-{suffix}-{revision_id}",
            confirmation=PAID_CANARY_CONFIRMATION,
            max_cost_usd=0.02,
        )
        ops.record_validation(
            str(validation["validation_id"]),
            status="succeeded",
            semantic_outcome="valid_nonempty",
            cost_usd=0.01,
            cost_final=True,
        )
    ready = ops.activate_binding(
        source_id,
        expected_generation=int(binding["generation"]),
        confirmation=FIRST_ACTIVATION_CONFIRMATION,
    )
    assert ready["validation_status"] == "ready_2of2"
    return source_id, ready


def _discovery_with_revisions(
    store: ServiceStore,
    ops: ApifyActorOpsService,
    route: dict,
    actors: tuple[tuple[str, str], ...],
    *,
    host: str,
) -> tuple[dict, list[str]]:
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="pool-stage-test",
        expected_generation=int(route["generation"]),
    )
    revision_ids = [
        _revision(
            ops,
            str(route["route_id"]),
            actor_id=actor_id,
            publisher=publisher,
            build_number=f"9.0.{index}",
            host=host,
            discovery_run_id=str(run["run_id"]),
        )
        for index, (actor_id, publisher) in enumerate(actors, start=1)
    ]
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="queued",
        stage="awaiting_canary_approval",
    )
    return run, revision_ids


def _approve_stage(
    ops: ApifyActorOpsService,
    owner_id: str,
    run_id: str,
    *,
    goal: str,
    approval_id: str,
) -> tuple[dict, dict]:
    plan = ops.get_canary_plan(run_id, goal=goal)
    assert plan["ready"] is True
    references = {
        str(item["revision_id"]): hashlib.sha256(
            f"reference:{item['revision_id']}".encode()
        ).hexdigest()
        for item in plan["items"]
    }
    batch = ops.create_canary_batch(
        run_id,
        goal=goal,
        expected_generation=int(plan["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        approval_id=approval_id,
        confirmation=BATCH_CANARY_CONFIRMATION,
        max_candidates=int(plan["max_candidates"]),
        max_total_charge_usd=float(plan["max_total_charge_usd"]),
        created_by_user_id=owner_id,
        reference_fingerprints=references,
    )
    return plan, batch


def _approve_manual_stage(
    store: ServiceStore,
    ops: ApifyActorOpsService,
    owner_id: str,
    run_id: str,
    revision_ids: list[str],
    *,
    goal: str,
    approval_id: str,
) -> tuple[dict, dict]:
    candidate_ids = [
        str(
            store.connect().execute(
                """
                SELECT candidate_id FROM apify_actor_adapter_revisions
                WHERE workspace_id = ? AND revision_id = ?
                """,
                (DEFAULT_WORKSPACE_ID, revision_id),
            ).fetchone()["candidate_id"]
        )
        for revision_id in revision_ids
    ]
    plan = ops.get_canary_plan(
        run_id,
        goal=goal,
        candidate_ids=candidate_ids,
        target_slot_count=3,
    )
    assert plan["ready"] is True
    references = {
        str(item["revision_id"]): hashlib.sha256(
            f"reference:{item['revision_id']}".encode()
        ).hexdigest()
        for item in plan["items"]
    }
    batch = ops.create_canary_batch(
        run_id,
        goal=goal,
        candidate_ids=candidate_ids,
        target_slot_count=3,
        expected_generation=int(plan["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        approval_id=approval_id,
        confirmation=BATCH_CANARY_CONFIRMATION,
        max_candidates=len(candidate_ids),
        max_total_charge_usd=float(plan["max_total_charge_usd"]),
        created_by_user_id=owner_id,
        reference_fingerprints=references,
    )
    return plan, batch


def _succeed_route_items(
    store: ServiceStore,
    ops: ApifyActorOpsService,
    batch: dict,
) -> None:
    for item in batch["items"]:
        ops.record_validation(
            str(item["validation_id"]),
            status="succeeded",
            semantic_outcome="valid_nonempty",
            cost_usd=0.01,
            cost_final=True,
        )
        ops.update_canary_batch_item(
            str(batch["batch_id"]),
            int(item["ordinal"]),
            status="succeeded",
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.01,
            cost_final=True,
        )
        ops.transition_revision(
            str(item["revision_id"]),
            expected_lifecycle="static_valid",
            lifecycle="probationary",
        )
    store.connect().commit()


def _reuse_route_items(ops: ApifyActorOpsService, batch: dict) -> None:
    for item in batch["items"]:
        if item["status"] == "succeeded":
            assert item["semantic_outcome"] == "evidence_reused"
            assert item["actual_cost_usd"] == 0.0
            assert item["cost_final"] is True
            continue
        ops.record_validation(
            str(item["validation_id"]),
            status="cancelled",
            semantic_outcome="not_needed_no_charge",
            cost_usd=0.0,
            cost_final=True,
            counts_toward_canary=False,
        )
        ops.update_canary_batch_item(
            str(batch["batch_id"]),
            int(item["ordinal"]),
            status="not_needed_no_charge",
            semantic_outcome="not_needed_no_charge",
            actual_cost_usd=0.0,
            cost_final=True,
        )


def _succeed_stage_sources(ops: ApifyActorOpsService, stage_id: str) -> list[str]:
    validation_ids = ops.prepare_pool_stage_source_validations(stage_id)
    for validation_id in validation_ids:
        ops.record_validation(
            validation_id,
            status="succeeded",
            semantic_outcome="valid_nonempty",
            cost_usd=0.01,
            cost_final=True,
        )
    ops.refresh_pool_stage_sources(stage_id)
    return validation_ids


def test_complete_third_preserves_two_actor_pool_until_atomic_apply(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="third-stage-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    active, base_revisions = _two_actor_pool(store, ops)
    source_id, binding = _ready_source(
        store, ops, active, base_revisions, suffix="existing"
    )
    run, _candidate_revisions = _discovery_with_revisions(
        store,
        ops,
        active,
        (("publisher-c/youtube-third", "publisher-c"),),
        host="youtube.com",
    )
    plan, batch = _approve_stage(
        ops,
        str(owner["id"]),
        str(run["run_id"]),
        goal="complete_third",
        approval_id="complete-third-approval",
    )

    assert plan["source_count"] == 1
    assert plan["source_validation_count"] == 1
    stage_id = str(batch["pool_stage_id"])
    assert [slot["revision_id"] for slot in ops.get_route(active["route_id"])["slots"]] == [
        *base_revisions,
        None,
    ]
    assert ops.get_source_binding(source_id)["validation_status"] == "ready_2of2"

    _succeed_route_items(store, ops, batch)
    source_validations = _succeed_stage_sources(ops, stage_id)
    assert len(source_validations) == 1
    assert ops.get_pool_stage(stage_id)["status"] == "apply_ready"
    assert ops.get_source_binding(source_id)["validation_status"] == "ready_2of2"
    with pytest.raises(ActorOpsError) as unsettled:
        ops.apply_pool_stage(
            stage_id,
            expected_generation=int(active["generation"]),
            expected_plan_hash=str(plan["plan_hash"]),
            apply_id="third-apply-request-0001",
            confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
        )
    assert unsettled.value.code == "apify_actor_pool_stage_precondition_incomplete"

    finalized = ops.finalize_canary_batch(str(batch["batch_id"]))
    assert finalized["status"] == "activation_ready"
    snapshot = ops.freeze_execution(str(active["route_id"]))
    inflight_attempt = ops.begin_attempt(
        snapshot,
        snapshot.slots[0],
        attempt_group_id="pool-stage-apply-inflight",
        attempt_index=1,
    )
    with pytest.raises(ActorOpsError) as inflight:
        ops.apply_pool_stage(
            stage_id,
            expected_generation=int(active["generation"]),
            expected_plan_hash=str(plan["plan_hash"]),
            apply_id="third-apply-request-0001",
            confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
        )
    assert inflight.value.code == "apify_actor_pool_stage_apply_inflight"
    assert [
        slot["revision_id"]
        for slot in ops.get_route(str(active["route_id"]))["slots"]
    ] == [*base_revisions, None]
    ops.finish_attempt(
        inflight_attempt,
        status="cancelled",
        semantic_outcome="cancelled_before_stage_apply",
        actual_cost_usd=0.0,
    )
    store.connect().execute(
        """
        UPDATE apify_actor_validations SET cost_final = 0
        WHERE workspace_id = ? AND validation_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, source_validations[0]),
    )
    store.connect().commit()
    with pytest.raises(ActorOpsError) as unsettled_source:
        ops.apply_pool_stage(
            stage_id,
            expected_generation=int(active["generation"]),
            expected_plan_hash=str(plan["plan_hash"]),
            apply_id="third-apply-request-0001",
            confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
        )
    assert unsettled_source.value.code == (
        "apify_actor_pool_stage_precondition_incomplete"
    )
    store.connect().execute(
        """
        UPDATE apify_actor_validations SET cost_final = 1
        WHERE workspace_id = ? AND validation_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, source_validations[0]),
    )
    store.connect().commit()
    staged_revision_id = str(
        ops.get_pool_stage(stage_id)["target_slots"]["backup_2"]
    )
    ops.transition_revision(
        staged_revision_id,
        expected_lifecycle="probationary",
        lifecycle="quarantined",
    )
    with pytest.raises(ActorOpsError) as quarantined:
        ops.apply_pool_stage(
            stage_id,
            expected_generation=int(active["generation"]),
            expected_plan_hash=str(plan["plan_hash"]),
            apply_id="third-apply-request-0001",
            confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
        )
    assert quarantined.value.code == "apify_actor_active_pool_uncertified"
    assert [
        slot["revision_id"]
        for slot in ops.get_route(str(active["route_id"]))["slots"]
    ] == [*base_revisions, None]
    ops.transition_revision(
        staged_revision_id,
        expected_lifecycle="quarantined",
        lifecycle="static_valid",
    )
    ops.transition_revision(
        staged_revision_id,
        expected_lifecycle="static_valid",
        lifecycle="probationary",
    )
    applied = ops.apply_pool_stage(
        stage_id,
        expected_generation=int(active["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        apply_id="third-apply-request-0001",
        confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
    )

    assert [slot["revision_id"] for slot in applied["slots"][:2]] == list(base_revisions)
    assert applied["slots"][2]["revision_id"] is not None
    ready_binding = ops.get_source_binding(source_id)
    assert ready_binding["validation_status"] == "ready_3of3"
    assert int(ready_binding["generation"]) == int(binding["generation"]) + 1
    replay = ops.apply_pool_stage(
        stage_id,
        expected_generation=int(active["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        apply_id="third-apply-request-0001",
        confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
    )
    assert replay["generation"] == applied["generation"]
    with pytest.raises(ActorOpsError) as conflict:
        ops.apply_pool_stage(
            stage_id,
            expected_generation=int(active["generation"]),
            expected_plan_hash=str(plan["plan_hash"]),
            apply_id="different-apply-request-0002",
            confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
        )
    assert conflict.value.code == "apify_actor_pool_stage_apply_id_conflict"


def test_complete_third_uses_approved_fallback_after_first_candidate_fails(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="third-fallback-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    active, base_revisions = _two_actor_pool(store, ops)
    source_id, _binding = _ready_source(
        store, ops, active, base_revisions, suffix="fallback"
    )
    active = ops.replace_active_pool(
        str(active["route_id"]),
        slots={
            "primary": base_revisions[0],
            "backup_1": base_revisions[1],
            "backup_2": None,
        },
        expected_generation=int(active["generation"]),
        per_run_cap_usd=0.005,
    )
    run, candidate_revisions = _discovery_with_revisions(
        store,
        ops,
        active,
        (
            ("publisher-c/youtube-third-first", "publisher-c"),
            ("publisher-d/youtube-third-second", "publisher-d"),
            ("publisher-e/youtube-third-last", "publisher-e"),
        ),
        host="youtube.com",
    )
    plan, batch = _approve_stage(
        ops,
        str(owner["id"]),
        str(run["run_id"]),
        goal="complete_third",
        approval_id="complete-third-fallback-approval",
    )

    assert [str(item["revision_id"]) for item in plan["items"]] == candidate_revisions
    assert plan["route_validation_cap_usd"] == pytest.approx(0.015)
    assert plan["source_validation_count"] == 1
    assert plan["source_validation_cap_usd"] == pytest.approx(0.005)
    assert plan["max_total_charge_usd"] == pytest.approx(0.02)
    assert batch["route_validation_cap_usd"] == pytest.approx(0.015)
    assert batch["max_total_charge_usd"] == pytest.approx(0.02)

    first, second, last = batch["items"]
    ops.record_validation(
        str(first["validation_id"]),
        status="failed",
        semantic_outcome="actor_failed",
        cost_usd=0.0,
        cost_final=True,
        counts_toward_canary=False,
    )
    ops.update_canary_batch_item(
        str(batch["batch_id"]),
        int(first["ordinal"]),
        status="failed",
        semantic_outcome="actor_failed",
        actual_cost_usd=0.0,
        cost_final=True,
    )
    with pytest.raises(ActorOpsError) as over_cap:
        ops.record_validation(
            str(second["validation_id"]),
            status="succeeded",
            semantic_outcome="valid_nonempty",
            cost_usd=0.006,
            cost_final=True,
        )
    assert over_cap.value.code == "apify_actor_cost_invalid"
    ops.record_validation(
        str(second["validation_id"]),
        status="succeeded",
        semantic_outcome="valid_nonempty",
        cost_usd=0.004,
        cost_final=True,
    )
    ops.update_canary_batch_item(
        str(batch["batch_id"]),
        int(second["ordinal"]),
        status="succeeded",
        semantic_outcome="valid_nonempty",
        actual_cost_usd=0.004,
        cost_final=True,
    )
    ops.transition_revision(
        str(second["revision_id"]),
        expected_lifecycle="static_valid",
        lifecycle="probationary",
    )
    ops.record_validation(
        str(last["validation_id"]),
        status="cancelled",
        semantic_outcome="staged_route_ready",
        cost_usd=0.0,
        cost_final=True,
        counts_toward_canary=False,
    )
    ops.update_canary_batch_item(
        str(batch["batch_id"]),
        int(last["ordinal"]),
        status="not_needed_no_charge",
        semantic_outcome="staged_route_ready",
        actual_cost_usd=0.0,
        cost_final=True,
    )

    stage_id = str(batch["pool_stage_id"])
    assert ops.pool_stage_route_ready(stage_id) is True
    validation_ids = ops.prepare_pool_stage_source_validations(stage_id)
    assert len(validation_ids) == 1
    source_validation = ops.get_validation(validation_ids[0])
    assert source_validation["source_id"] == source_id
    assert source_validation["revision_id"] == candidate_revisions[1]
    approved_source_cap = store.connect().execute(
        """
        SELECT approved_max_cost_usd FROM apify_actor_validations
        WHERE workspace_id = ? AND validation_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, validation_ids[0]),
    ).fetchone()[0]
    assert approved_source_cap == pytest.approx(0.005)
    stage = ops.get_pool_stage(stage_id)
    assert stage["target_slots"] == {
        "primary": base_revisions[0],
        "backup_1": base_revisions[1],
        "backup_2": candidate_revisions[1],
    }


def test_empty_staged_target_replans_instead_of_becoming_apply_ready(
    tmp_path,
) -> None:
    """A failed third candidate must not turn an empty source set into apply-ready."""

    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="empty-stage-target-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    active, base_revisions = _two_actor_pool(store, ops)
    run, _candidate_revisions = _discovery_with_revisions(
        store,
        ops,
        active,
        (("publisher-c/youtube-third-timeout", "publisher-c"),),
        host="youtube.com",
    )
    plan, batch = _approve_stage(
        ops,
        str(owner["id"]),
        str(run["run_id"]),
        goal="complete_third",
        approval_id="empty-stage-target-approval",
    )
    item = batch["items"][0]
    ops.record_validation(
        str(item["validation_id"]),
        status="failed",
        semantic_outcome="apify_actor_run_timed_out",
        cost_usd=0.019,
        cost_final=True,
        counts_toward_canary=False,
    )
    ops.update_canary_batch_item(
        str(batch["batch_id"]),
        int(item["ordinal"]),
        status="failed",
        semantic_outcome="apify_actor_run_timed_out",
        actual_cost_usd=0.019,
        cost_final=True,
    )

    stage_id = str(batch["pool_stage_id"])
    assert ops.prepare_pool_stage_source_validations(stage_id) == []
    assert ops.get_pool_stage(stage_id)["status"] == "replan_required"
    # The Worker calls refresh unconditionally after preparation. An empty
    # source snapshot used to make all([]) mark this failed stage apply-ready.
    ops.refresh_pool_stage_sources(stage_id)
    stage = ops.get_pool_stage(stage_id)
    assert stage["status"] == "replan_required"
    assert stage["target_slots"] == {
        "primary": None,
        "backup_1": None,
        "backup_2": None,
    }
    assert ops.finalize_canary_batch(str(batch["batch_id"]))["status"] == "partial"

    # Repair the corrupt persisted state left by the prior Worker revision.
    store.connect().execute(
        """
        UPDATE apify_actor_pool_stages
        SET status = 'apply_ready'
        WHERE workspace_id = ? AND stage_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, stage_id),
    )
    store.connect().commit()
    recovered = ops.workflow_state(str(active["route_id"]))
    assert ops.get_pool_stage(stage_id)["status"] == "replan_required"
    assert recovered["kind"] in {
        "backup_2_candidate_selection_required",
        "backup_2_discovery_required",
    }

    with pytest.raises(ActorOpsError) as incomplete:
        ops.apply_pool_stage(
            stage_id,
            expected_generation=int(active["generation"]),
            expected_plan_hash=str(plan["plan_hash"]),
            apply_id="empty-stage-target-apply-0001",
            confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
        )
    assert incomplete.value.code == "apify_actor_pool_stage_precondition_incomplete"
    assert [
        slot["revision_id"]
        for slot in ops.get_route(str(active["route_id"]))["slots"]
    ] == [*base_revisions, None]


def test_new_source_replans_only_missing_proofs_before_third_slot_apply(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="third-replan-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    active, base_revisions = _two_actor_pool(store, ops)
    existing_source, _binding = _ready_source(
        store, ops, active, base_revisions, suffix="already-ready"
    )
    run, _candidate_revisions = _discovery_with_revisions(
        store,
        ops,
        active,
        (("publisher-c/youtube-third-replan", "publisher-c"),),
        host="youtube.com",
    )
    first_plan, first_batch = _approve_stage(
        ops,
        str(owner["id"]),
        str(run["run_id"]),
        goal="complete_third",
        approval_id="complete-third-first-approval",
    )
    _succeed_route_items(store, ops, first_batch)
    assert len(_succeed_stage_sources(ops, str(first_batch["pool_stage_id"]))) == 1
    assert ops.finalize_canary_batch(str(first_batch["batch_id"]))["status"] == "activation_ready"

    new_source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="New source during stage",
        config={"platform": "youtube", "kind": "channel", "target": "new"},
    )
    ops.bind_source(
        source_id=new_source_id,
        route_id=str(active["route_id"]),
        target_fingerprint=hashlib.sha256(b"target:new").hexdigest(),
        mode="fallback",
    )
    ops.refresh_pool_stage_sources(str(first_batch["pool_stage_id"]))
    assert ops.get_pool_stage(str(first_batch["pool_stage_id"]))["status"] == "replan_required"
    with pytest.raises(ActorOpsError) as changed_source:
        ops.apply_pool_stage(
            str(first_batch["pool_stage_id"]),
            expected_generation=int(active["generation"]),
            expected_plan_hash=str(first_plan["plan_hash"]),
            apply_id="stale-source-apply-request-0001",
            confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
        )
    assert changed_source.value.code == "apify_actor_pool_stage_precondition_incomplete"
    assert [
        slot["revision_id"] for slot in ops.get_route(str(active["route_id"]))["slots"]
    ] == [*base_revisions, None]

    retry_plan, retry_batch = _approve_stage(
        ops,
        str(owner["id"]),
        str(run["run_id"]),
        goal="complete_third",
        approval_id="complete-third-incremental-approval",
    )
    assert retry_plan["source_count"] == 2
    assert retry_plan["source_validation_count"] == 3
    assert ops.get_pool_stage(str(first_batch["pool_stage_id"]))["status"] == "stale"
    _reuse_route_items(ops, retry_batch)
    missing = _succeed_stage_sources(ops, str(retry_batch["pool_stage_id"]))
    assert len(missing) == 3
    missing_sources = {
        str(row["source_id"])
        for row in store.connect().execute(
            """
            SELECT source_id FROM apify_actor_validations
            WHERE validation_id IN ({})
            """.format(",".join("?" for _ in missing)),
            tuple(missing),
        ).fetchall()
    }
    assert missing_sources == {new_source_id}
    ops.finalize_canary_batch(str(retry_batch["batch_id"]))
    applied = ops.apply_pool_stage(
        str(retry_batch["pool_stage_id"]),
        expected_generation=int(active["generation"]),
        expected_plan_hash=str(retry_plan["plan_hash"]),
        apply_id="incremental-apply-request-0001",
        confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
    )
    assert applied["runtime"]["runnable_count"] == 3
    assert ops.get_source_binding(existing_source)["validation_status"] == "ready_3of3"
    assert ops.get_source_binding(new_source_id)["validation_status"] == "ready_3of3"


@pytest.mark.parametrize(
    ("route_key", "goal", "host"),
    (
        ("instagram/profile/items", "initial_pool", "instagram.com"),
        ("x/profile", "upgrade_legacy", "x.com"),
    ),
)
def test_manual_initial_and_legacy_apply_three_selected_actors_atomically(
    tmp_path,
    route_key: str,
    goal: str,
    host: str,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username=f"manual-three-{goal}",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = ops.get_route(str(_route(store, route_key)["route_id"]))
    original_slots = [slot["revision_id"] for slot in route["slots"]]
    run, revisions = _discovery_with_revisions(
        store,
        ops,
        route,
        (
            (f"publisher-a/{goal}-primary", "publisher-a"),
            (f"publisher-b/{goal}-backup", "publisher-b"),
            (f"publisher-c/{goal}-backup-2", "publisher-c"),
        ),
        host=host,
    )
    plan, batch = _approve_manual_stage(
        store,
        ops,
        str(owner["id"]),
        str(run["run_id"]),
        revisions,
        goal=goal,
        approval_id=f"manual-three-{goal}-approval",
    )

    assert plan["schema_version"] == 3
    assert plan["selection_mode"] == "manual"
    assert plan["target_slot_count"] == 3
    assert plan["required_success_count"] == 3
    assert [slot["revision_id"] for slot in ops.get_route(route["route_id"])["slots"]] == original_slots

    _succeed_route_items(store, ops, batch)
    assert _succeed_stage_sources(ops, str(batch["pool_stage_id"])) == []
    ops.finalize_canary_batch(str(batch["batch_id"]))
    applied = ops.apply_pool_stage(
        str(batch["pool_stage_id"]),
        expected_generation=int(route["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        apply_id=f"manual-three-{goal}-apply",
        confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
    )

    assert [slot["revision_id"] for slot in applied["slots"]] == revisions
    assert {slot["lifecycle"] for slot in applied["slots"]} == {"probationary"}
    assert ops.workflow_state(str(route["route_id"]))["kind"] == "probation_observing"
    pending_source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name=f"Pending source {goal}",
        config={
            "platform": route_key.split("/", 1)[0],
            "kind": "profile",
            "target": f"pending-{goal}",
        },
    )
    ops.bind_source(
        source_id=pending_source_id,
        route_id=str(route["route_id"]),
        target_fingerprint=hashlib.sha256(
            f"pending:{goal}".encode()
        ).hexdigest(),
        mode="fallback",
    )
    source_action = ops.workflow_state(str(route["route_id"]))
    assert source_action["kind"] == "source_validation_required"
    assert source_action["progress"] == {"pending_sources": 1}
    store.connect().execute(
        "UPDATE source_catalog SET enabled = 0 WHERE id = ?",
        (pending_source_id,),
    )
    store.connect().commit()
    assert ops.workflow_state(str(route["route_id"]))["kind"] == (
        "probation_observing"
    )
    if goal == "upgrade_legacy":
        persisted = {
            str(row["lifecycle"])
            for row in store.connect().execute(
                """
                SELECT lifecycle FROM apify_actor_adapter_revisions
                WHERE workspace_id = ? AND revision_id IN (?, ?, ?)
                """,
                (DEFAULT_WORKSPACE_ID, *original_slots),
            ).fetchall()
        }
        assert persisted == {"legacy_builtin"}


def test_legacy_workflow_requires_three_explicit_candidates_before_paid_confirmation(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    seeded = ops.get_route(str(_route(store, "x/profile")["route_id"]))
    first_run, _first_revision = _discovery_with_revisions(
        store,
        ops,
        seeded,
        (("publisher-new-a/x-primary", "publisher-new-a"),),
        host="x.com",
    )

    shortfall = ops.workflow_state(str(seeded["route_id"]))

    assert shortfall["kind"] == "legacy_discovery_required"
    assert shortfall["run_id"] == first_run["run_id"]
    assert shortfall["progress"] == {
        "eligible_candidate_count": 1,
        "required_selection_count": 3,
    }
    assert shortfall["blockers"] == ["candidate_shortfall"]

    second_run, second_revisions = _discovery_with_revisions(
        store,
        ops,
        seeded,
        (
            ("publisher-new-a/x-primary-v2", "publisher-new-a"),
            ("publisher-new-b/x-backup", "publisher-new-b"),
            ("publisher-new-c/x-backup-2", "publisher-new-c"),
        ),
        host="x.com",
    )

    ready = ops.workflow_state(str(seeded["route_id"]))
    assert ready["kind"] == "legacy_candidate_selection_required"
    assert ready["run_id"] == second_run["run_id"]
    assert ready["progress"] == {
        "eligible_candidate_count": 3,
        "required_selection_count": 3,
    }
    assert ready["blockers"] == []
    candidate_ids = [
        str(
            store.connect().execute(
                """
                SELECT candidate_id FROM apify_actor_adapter_revisions
                WHERE workspace_id = ? AND revision_id = ?
                """,
                (DEFAULT_WORKSPACE_ID, revision_id),
            ).fetchone()["candidate_id"]
        )
        for revision_id in second_revisions
    ]
    plan = ops.get_canary_plan(
        str(ready["run_id"]),
        goal="upgrade_legacy",
        candidate_ids=candidate_ids,
        target_slot_count=3,
    )
    assert plan["ready"] is True
    assert plan["selection_mode"] == "manual"
    assert plan["target_slot_count"] == 3
    assert plan["required_success_count"] == 3


def test_initial_route_does_not_offer_legacy_two_actor_activation(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = ops.get_route(str(_route(store, "youtube/channel/items")["route_id"]))
    run, _revisions = _discovery_with_revisions(
        store,
        ops,
        route,
        (
            ("publisher-a/initial-primary", "publisher-a"),
            ("publisher-b/initial-backup", "publisher-b"),
        ),
        host="youtube.com",
    )
    store.connect().execute(
        """
        UPDATE apify_actor_discovery_runs SET stage = 'activation_ready'
        WHERE workspace_id = ? AND run_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, run["run_id"]),
    )
    store.connect().commit()

    workflow = ops.workflow_state(str(route["route_id"]))

    assert workflow["kind"] == "setup_discovery_required"
    assert workflow["progress"] == {
        "eligible_candidate_count": 2,
        "required_selection_count": 3,
    }
    assert workflow["blockers"] == ["candidate_shortfall"]


def test_legacy_sidecar_keeps_old_pool_live_then_atomically_switches_exact_pair(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="legacy-stage-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    seeded = ops.get_route(str(_route(store, "x/profile")["route_id"]))
    legacy_revision_ids = [
        str(slot["revision_id"])
        for slot in seeded["slots"]
        if slot["revision_id"]
    ]
    assert {slot["lifecycle"] for slot in seeded["slots"]} == {"legacy_builtin"}
    run, exact_revisions = _discovery_with_revisions(
        store,
        ops,
        seeded,
        (
            ("publisher-new-a/x-primary", "publisher-new-a"),
            ("publisher-new-b/x-backup", "publisher-new-b"),
        ),
        host="x.com",
    )
    plan, batch = _approve_stage(
        ops,
        str(owner["id"]),
        str(run["run_id"]),
        goal="upgrade_legacy",
        approval_id="legacy-sidecar-approval",
    )
    assert plan["required_success_count"] == 2
    assert plan["source_count"] == 0
    assert [slot["revision_id"] for slot in ops.get_route(seeded["route_id"])["slots"]] == legacy_revision_ids

    _succeed_route_items(store, ops, batch)
    recommendation = ops.recommend_active_pool(str(seeded["route_id"]))
    assert recommendation["ready"] is True
    assert set(
        value for value in recommendation["slots"].values() if value
    ) == set(exact_revisions)
    assert recommendation["already_active"] is False
    assert _succeed_stage_sources(ops, str(batch["pool_stage_id"])) == []
    ops.finalize_canary_batch(str(batch["batch_id"]))
    applied = ops.apply_pool_stage(
        str(batch["pool_stage_id"]),
        expected_generation=int(seeded["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        apply_id="legacy-sidecar-apply-request-0001",
        confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
    )

    assert [slot["revision_id"] for slot in applied["slots"]] == [
        exact_revisions[0],
        exact_revisions[1],
        None,
    ]
    assert {slot["lifecycle"] for slot in applied["slots"] if slot["revision_id"]} == {"probationary"}
    persisted_legacy = {
        str(row["lifecycle"])
        for row in store.connect().execute(
            """
            SELECT lifecycle FROM apify_actor_adapter_revisions
            WHERE workspace_id = ? AND revision_id IN ({})
            """.format(",".join("?" for _ in legacy_revision_ids)),
            (DEFAULT_WORKSPACE_ID, *legacy_revision_ids),
        ).fetchall()
    }
    assert persisted_legacy == {"legacy_builtin"}
    follow_up = ops.workflow_state(str(seeded["route_id"]))
    assert follow_up["kind"] == "backup_2_discovery_required"
    assert follow_up["goal"] == "complete_third"
