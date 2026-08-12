from __future__ import annotations

import asyncio

import pytest

from src.services.apify_actor_canary import ApifyActorCanaryRunner
from src.services.apify_actor_discovery import (
    ActorDiscoveryError,
    ApifyActorDiscoveryService,
)
from src.services.apify_actor_ops import (
    ActorOpsError,
    ApifyActorOpsService,
    BATCH_CANARY_CONFIRMATION,
    ROUTE_POOL_ACTIVATION_CONFIRMATION,
    RouteExecutionSnapshot,
    RouteSlotSnapshot,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _x_route(ops: ApifyActorOpsService) -> dict:
    route = next(row for row in ops.list_routes() if row["route_key"] == "x/profile")
    return ops.get_route(str(route["route_id"]))


def _candidate_id(store: ServiceStore, revision_id: str) -> str:
    return str(
        store.connect().execute(
            """
            SELECT candidate_id FROM apify_actor_adapter_revisions
            WHERE workspace_id = ? AND revision_id = ?
            """,
            (DEFAULT_WORKSPACE_ID, revision_id),
        ).fetchone()["candidate_id"]
    )


def _x_manifest(actor_id: str, build_number: str) -> dict:
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
            "text": {"pointers": ["/text"], "transforms": ["to_string"]},
            "source_native_id": {
                "pointers": ["/authorHandle"],
                "transforms": ["to_string"],
            },
        },
        "semantics": {
            "identity": {
                "output_field": "source_native_id",
                "target_ref": "target.handle",
                "match": "exact",
            },
            "url_host_allowlist": ["x.com", "twitter.com"],
        },
    }


def _compatibility_discovery(
    store: ServiceStore,
    ops: ApifyActorOpsService,
) -> tuple[dict, dict, dict[str, str]]:
    route = _x_route(ops)
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="compatibility-shortfall",
        expected_generation=int(route["generation"]),
    )
    revisions = {
        "allowed": ops.ensure_compatibility_trial_revision(
            route_id=str(route["route_id"]),
            discovery_run_id=str(run["run_id"]),
            actor_id="compatibility/allowed-x",
            publisher="compatibility",
            build_id=None,
            build_number=None,
            pricing={"minimalMaxTotalChargeUsd": 0.01},
            permission_level="limited",
            input_schema_hash=None,
            output_schema_hash=None,
            deprecated=True,
        ),
        "pinned": ops.ensure_compatibility_trial_revision(
            route_id=str(route["route_id"]),
            discovery_run_id=str(run["run_id"]),
            actor_id="compatibility/pinned-x",
            publisher="second-publisher",
            build_id="pinned-build",
            build_number="2.1.0",
            pricing={"minimalMaxTotalChargeUsd": 0.01},
            permission_level="limited",
            input_schema_hash=None,
            output_schema_hash=None,
            input_dialect="twitter_handles",
            input_count_field="maxItems",
        ),
        "expensive": ops.ensure_compatibility_trial_revision(
            route_id=str(route["route_id"]),
            discovery_run_id=str(run["run_id"]),
            actor_id="compatibility/expensive-x",
            publisher="compatibility",
            build_id="expensive-build",
            build_number="1.0.0",
            pricing={"minimalMaxTotalChargeUsd": 0.03},
            permission_level="limited",
            input_schema_hash=None,
            output_schema_hash=None,
        ),
        "full_permission": ops.ensure_compatibility_trial_revision(
            route_id=str(route["route_id"]),
            discovery_run_id=str(run["run_id"]),
            actor_id="compatibility/full-permission-x",
            publisher="compatibility",
            build_id="permission-build",
            build_number="1.0.0",
            pricing={"minimalMaxTotalChargeUsd": 0.01},
            permission_level="full",
            input_schema_hash=None,
            output_schema_hash=None,
        ),
    }
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="queued",
        stage="candidate_shortfall",
        error_code="candidate_shortfall",
    )
    return route, ops.get_discovery_run(str(run["run_id"])), revisions


def test_compatibility_candidates_relax_evidence_but_keep_hard_fences(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route, run, revisions = _compatibility_discovery(store, ops)

    listed = ops.list_pool_candidates(
        str(route["route_id"]),
        goal="compatibility_single",
    )
    by_candidate = {
        str(row["candidate_id"]): row for row in listed["candidates"]
    }
    allowed = by_candidate[_candidate_id(store, revisions["allowed"])]
    expensive = by_candidate[_candidate_id(store, revisions["expensive"])]
    pinned = by_candidate[_candidate_id(store, revisions["pinned"])]
    full_permission = by_candidate[
        _candidate_id(store, revisions["full_permission"])
    ]

    assert listed["goal"] == "compatibility_single"
    assert listed["required_selection_count"] == 1
    assert "pre_canary_exact_build" in allowed["relaxed_requirements"]
    assert allowed["selectable"] is True
    assert "observed_manifest_after_canary" in allowed["compatibility_warnings"]
    assert "follows_current_build_if_unpinnable" in allowed[
        "compatibility_warnings"
    ]
    assert "deprecated_actor" in allowed["compatibility_warnings"]
    assert pinned["selectable"] is True
    assert "follows_current_build_if_unpinnable" not in pinned[
        "compatibility_warnings"
    ]
    assert expensive["selectable"] is False
    assert expensive["unavailable_reason"] == "actor_price_above_route_cap"
    assert full_permission["selectable"] is False
    assert full_permission["unavailable_reason"] == (
        "actor_requires_full_permissions"
    )
    workflow = ops.workflow_state(str(route["route_id"]))
    assert workflow["kind"] == "compatibility_candidate_selection_available"
    assert workflow["run_id"] == run["run_id"]


def test_compatibility_candidates_reuse_prior_evidence_after_empty_inspection(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route, _run, revisions = _compatibility_discovery(store, ops)
    newer = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="newer-compatibility-inspection",
        expected_generation=int(route["generation"]),
    )
    ops.update_discovery_run(
        str(newer["run_id"]),
        expected_stage="queued",
        stage="candidate_shortfall",
        error_code="candidate_shortfall",
    )

    listed = ops.list_pool_candidates(
        str(route["route_id"]),
        goal="compatibility_single",
    )

    assert listed["run_id"] == newer["run_id"]
    assert listed["blockers"] == []
    assert any(
        row["candidate_id"] == _candidate_id(store, revisions["allowed"])
        and row["selectable"] is True
        for row in listed["candidates"]
    )
    workflow = ops.workflow_state(str(route["route_id"]))
    assert workflow["kind"] == "compatibility_candidate_selection_available"
    assert workflow["goal"] == "compatibility_single"
    assert workflow["run_id"] == newer["run_id"]
    assert workflow["progress"]["eligible_candidate_count"] >= 1


def test_x_discovery_preserves_metadata_safe_compatibility_candidate(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    ops.patch_discovery_settings(
        expected_generation=1,
        enabled=True,
        call_limit=3,
    )
    route = _x_route(ops)
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="compatibility-discovery-test",
        expected_generation=int(route["generation"]),
    )

    class Metadata:
        async def search_store(self, _query: str):
            return [
                {"actorId": "compatibility/store-x"},
                {"actorId": "compatibility/full-x"},
                {"actorId": "compatibility/expensive-x"},
            ]

        async def get_actor(self, actor_id: str):
            permission = (
                "FULL_PERMISSIONS"
                if actor_id.endswith("full-x")
                else "LIMITED_PERMISSIONS"
            )
            charge = 0.03 if actor_id.endswith("expensive-x") else 0.01
            publisher, name = actor_id.split("/", 1)
            return {
                "actorId": actor_id,
                "username": publisher,
                "name": name,
                "isPublic": True,
                "isRunnable": True,
                "isDeprecated": True,
                "actorPermissionLevel": permission,
                "pricingInfos": [
                    {
                        "startedAt": "2020-01-01T00:00:00Z",
                        "pricingModel": "PAY_PER_EVENT",
                        "minimalMaxTotalChargeUsd": charge,
                        "pricingPerEvent": {
                            "actorChargeEvents": {
                                "item": {"eventPriceUsd": charge}
                            }
                        },
                    }
                ],
            }

        async def get_build(self, _build_id: str):
            raise AssertionError("Missing tagged Builds must not be fetched")

        async def validate_input(self, *_args):
            raise AssertionError("Compatibility placeholders skip static input validation")

    async def unexpected_ai(_prompt):
        raise AssertionError("Strict shortfall must stop before AI")

    outcome = asyncio.run(
        ApifyActorDiscoveryService(ops, Metadata(), unexpected_ai).run_discovery(
            str(run["run_id"]),
            queries=["x profile posts"],
            candidate_limit=30,
        )
    )

    assert outcome.stage == "candidate_shortfall"
    listed = ops.list_pool_candidates(
        str(route["route_id"]),
        goal="compatibility_single",
    )
    stored = store.connect().execute(
        """
        SELECT id FROM apify_actor_candidates
        WHERE workspace_id = ? AND actor_id = 'compatibility/store-x'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    assert stored is not None
    remembered_failures = store.connect().execute(
        """
        SELECT candidate.actor_id, evaluation.reason_code
        FROM apify_actor_candidates AS candidate
        JOIN apify_actor_evaluation_history AS evaluation
          ON evaluation.workspace_id = candidate.workspace_id
         AND evaluation.candidate_id = candidate.id
        WHERE candidate.workspace_id = ?
          AND candidate.actor_id IN (
              'compatibility/full-x', 'compatibility/expensive-x'
          )
          AND evaluation.stage = 'metadata'
          AND evaluation.policy_mode = 'compatibility'
        ORDER BY candidate.actor_id
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchall()
    assert [tuple(row) for row in remembered_failures] == [
        ("compatibility/expensive-x", "actor_price_above_route_cap"),
        ("compatibility/full-x", "actor_full_permission"),
    ]
    candidate = next(
        item
        for item in listed["candidates"]
        if item["candidate_id"] == str(stored["id"])
    )
    assert candidate["selectable"] is True
    assert "pre_canary_exact_build" in candidate["relaxed_requirements"]
    assert "deprecated_actor" in candidate["compatibility_warnings"]
    assert {
        item["unavailable_reason"]
        for item in listed["candidates"]
        if not item["selectable"]
    } >= {
        "actor_price_above_route_cap",
        "actor_requires_full_permissions",
    }


def test_compatibility_candidate_requires_explicit_runnable_evidence(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    ops.patch_discovery_settings(
        expected_generation=1,
        enabled=True,
        call_limit=3,
    )
    route = _x_route(ops)
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="compatibility-runnable-proof",
        expected_generation=int(route["generation"]),
    )

    class Metadata:
        async def search_store(self, _query: str):
            return [{"actorId": "compatibility/unknown-runnable"}]

        async def get_actor(self, _actor_id: str):
            return {
                "actorId": "compatibility/unknown-runnable",
                "username": "compatibility",
                "name": "unknown-runnable",
                "isPublic": True,
                "actorPermissionLevel": "LIMITED_PERMISSIONS",
                "pricingInfos": [
                    {
                        "startedAt": "2020-01-01T00:00:00Z",
                        "pricingModel": "PAY_PER_EVENT",
                        "minimalMaxTotalChargeUsd": 0.01,
                        "pricingPerEvent": {
                            "actorChargeEvents": {
                                "item": {"eventPriceUsd": 0.01}
                            }
                        },
                    }
                ],
            }

        async def get_build(self, _build_id: str):
            raise AssertionError("Unproven runnable Actor must stop first")

        async def validate_input(self, *_args):
            raise AssertionError("Unproven runnable Actor must not validate")

    outcome = asyncio.run(
        ApifyActorDiscoveryService(ops, Metadata(), lambda _prompt: {}).run_discovery(
            str(run["run_id"]),
            queries=["x profile"],
            candidate_limit=30,
        )
    )

    assert outcome.stage == "candidate_shortfall"
    remembered = store.connect().execute(
        """
        SELECT id FROM apify_actor_candidates
        WHERE workspace_id = ? AND actor_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, "compatibility/unknown-runnable"),
    ).fetchone()
    assert remembered is not None
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM apify_actor_adapter_revisions
        WHERE workspace_id = ? AND candidate_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, str(remembered["id"])),
    ).fetchone()[0] == 0
    listed = ops.list_pool_candidates(
        str(route["route_id"]),
        goal="compatibility_single",
    )
    failed = next(
        item
        for item in listed["candidates"]
        if item["candidate_id"] == str(remembered["id"])
    )
    assert failed["selectable"] is False
    assert failed["unavailable_reason"] == "actor_not_runnable"


def test_single_nonempty_compatibility_proof_can_activate_x_without_redundancy(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="compatibility-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store)
    route, run, revisions = _compatibility_discovery(store, ops)
    candidate_id = _candidate_id(store, revisions["pinned"])
    plan = ops.get_canary_plan(
        str(run["run_id"]),
        goal="compatibility_single",
        candidate_ids=[candidate_id],
        target_slot_count=1,
    )
    assert plan["ready"] is True
    assert plan["required_success_count"] == 1
    assert plan["max_total_charge_usd"] == 0.02
    batch = ops.create_canary_batch(
        str(run["run_id"]),
        goal="compatibility_single",
        candidate_ids=[candidate_id],
        target_slot_count=1,
        expected_generation=int(plan["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        approval_id="compatibility-paid-confirmation",
        confirmation=BATCH_CANARY_CONFIRMATION,
        max_candidates=1,
        max_total_charge_usd=float(plan["max_total_charge_usd"]),
        created_by_user_id=str(owner["id"]),
        reference_fingerprints=dict(plan["_reference_fingerprints"]),
    )
    item = batch["items"][0]
    ops.record_validation(
        str(item["validation_id"]),
        status="succeeded",
        semantic_outcome="valid_nonempty",
        cost_usd=0.005,
        cost_final=True,
        dataset_row_count=1,
        mapped_item_count=1,
    )
    observed_revision = ops.promote_compatibility_observation(
        str(item["validation_id"]),
        observed_fields=("identity", "url", "published_at", "content"),
    )
    promoted = ops.get_revision(observed_revision)
    assert promoted["execution_mode"] == "pinned"
    assert promoted["build_id"] == "pinned-build"
    assert promoted["build_number"] == "2.1.0"
    assert promoted["security_evidence"]["follows_current_build"] is False
    ops.update_canary_batch_item(
        str(batch["batch_id"]),
        int(item["ordinal"]),
        status="succeeded",
        semantic_outcome="valid_nonempty",
        actual_cost_usd=0.005,
        cost_final=True,
    )
    prepared = ops.prepare_compatibility_stage_activation(
        str(batch["pool_stage_id"])
    )
    assert prepared["status"] == "apply_ready"
    assert prepared["target_slot_count"] == 1
    finalized = ops.finalize_canary_batch(str(batch["batch_id"]))
    assert finalized["status"] == "activation_ready"
    assert finalized["cost_final"] is True

    activated = ops.apply_pool_stage(
        str(batch["pool_stage_id"]),
        expected_generation=int(plan["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        apply_id="compatibility-final-activation",
        confirmation=ROUTE_POOL_ACTIVATION_CONFIRMATION,
    )
    active_slots = [slot for slot in activated["slots"] if slot["revision_id"]]
    assert [slot["revision_id"] for slot in active_slots] == [observed_revision]
    assert activated["admission_mode"] == "compatibility"
    assert activated["min_runtime_healthy"] == 1
    assert activated["min_publishers"] == 1
    assert ops.source_capability_ready(str(route["route_id"])) is True
    workflow = ops.workflow_state(str(route["route_id"]))
    assert workflow["kind"] == "compatibility_operational"
    assert workflow["goal"] == "initial_pool"


def test_compatibility_cost_reconciliation_promotes_without_second_run(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="compatibility-reconcile-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store)
    route, run, revisions = _compatibility_discovery(store, ops)
    original_revision_id = revisions["allowed"]
    candidate_id = _candidate_id(store, original_revision_id)
    plan = ops.get_canary_plan(
        str(run["run_id"]),
        goal="compatibility_single",
        candidate_ids=[candidate_id],
        target_slot_count=1,
    )
    batch = ops.create_canary_batch(
        str(run["run_id"]),
        goal="compatibility_single",
        candidate_ids=[candidate_id],
        target_slot_count=1,
        expected_generation=int(plan["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        approval_id="compatibility-delayed-cost",
        confirmation=BATCH_CANARY_CONFIRMATION,
        max_candidates=1,
        max_total_charge_usd=float(plan["max_total_charge_usd"]),
        created_by_user_id=str(owner["id"]),
        reference_fingerprints=dict(plan["_reference_fingerprints"]),
    )
    item = batch["items"][0]
    revision = ops.get_revision(original_revision_id)
    candidate = store.connect().execute(
        """
        SELECT state FROM apify_actor_candidates
        WHERE workspace_id = ? AND id = ?
        """,
        (DEFAULT_WORKSPACE_ID, candidate_id),
    ).fetchone()
    slot = RouteSlotSnapshot(
        slot_name="primary",
        candidate_id=candidate_id,
        revision_id=original_revision_id,
        actor_id=str(revision["actor_id"]),
        publisher=str(revision["publisher"]),
        # The free paid-start preflight resolved this current-only trial to an
        # actual Build; delayed cost settlement must retain that snapshot.
        build_id="observed-build",
        build_number="2026.08.12",
        manifest_hash=None,
        lifecycle=str(revision["lifecycle"]),
        candidate_state=str(candidate["state"]),
        manifest=None,
    )
    snapshot = RouteExecutionSnapshot(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_id=str(route["route_id"]),
        route_key=str(route["route_key"]),
        route_generation=int(plan["generation"]),
        per_run_cap_usd=0.02,
        slots=(slot,),
    )
    attempt_id = ops.begin_validation_attempt(
        str(item["validation_id"]), snapshot, slot, job_id=None
    )
    ops.finish_attempt(
        attempt_id,
        status="succeeded",
        semantic_outcome="valid_nonempty",
        actual_cost_usd=None,
    )
    ops.record_validation(
        str(item["validation_id"]),
        status="succeeded",
        semantic_outcome="valid_nonempty",
        attempt_id=attempt_id,
        cost_usd=None,
        cost_final=False,
        dataset_row_count=1,
        mapped_item_count=1,
    )
    ops.update_canary_batch_item(
        str(batch["batch_id"]),
        int(item["ordinal"]),
        status="succeeded",
        semantic_outcome="valid_nonempty",
        actual_cost_usd=None,
        cost_final=False,
    )
    pending = ops.prepare_compatibility_stage_activation(
        str(batch["pool_stage_id"])
    )
    assert pending["status"] == "validating_route"
    assert pending["last_error_code"] == (
        "apify_actor_cost_reconciliation_required"
    )
    ops.finalize_canary_batch(str(batch["batch_id"]))
    now = "2026-08-12T00:00:00+00:00"
    store.connect().execute(
        """
        INSERT INTO apify_actor_runs (
            id, workspace_id, logical_run_id, purpose, secret_id,
            secret_version, pool_generation, remote_run_id, dataset_id,
            status, charge_reserved_usd, charge_actual_usd, charge_final,
            created_at, started_at, terminal_at, updated_at
        ) VALUES (
            'compatibility-final-cost-run', ?, ?, 'validation',
            'validation-secret', 1, 1, 'remote-compatibility-run',
            'compatibility-dataset', 'succeeded', 0.02, 0.005, 1,
            ?, ?, ?, ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            attempt_id,
            now,
            now,
            now,
            now,
        ),
    )
    store.connect().commit()

    reconciled = ops.reconcile_terminal_validation_costs()

    assert reconciled["validations"] == 1
    assert reconciled["cycles"] >= 1
    stage = ops.get_pool_stage(str(batch["pool_stage_id"]))
    assert stage["status"] == "apply_ready"
    assert stage["target_primary_revision_id"] != original_revision_id
    promoted = ops.get_revision(str(stage["target_primary_revision_id"]))
    assert promoted["execution_mode"] == "pinned"
    assert promoted["build_id"] == "observed-build"
    assert promoted["build_number"] == "2026.08.12"
    finalized = ops.get_canary_batch(str(batch["batch_id"]))
    assert finalized["status"] == "activation_ready"
    assert finalized["actual_cost_usd"] == 0.005
    assert finalized["cost_final"] is True
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM apify_actor_runs
        WHERE logical_run_id = ?
        """,
        (attempt_id,),
    ).fetchone()[0] == 1


def test_compatibility_canary_promotes_existing_exact_revision(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="compatibility-exact-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store)
    route, run, revisions = _compatibility_discovery(store, ops)
    candidate_id = _candidate_id(store, revisions["pinned"])
    exact_revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id="compatibility/pinned-x",
        publisher="second-publisher",
        build_id="pinned-build",
        build_number="2.1.0",
        manifest=_x_manifest("compatibility/pinned-x", "2.1.0"),
        input_schema_hash="a" * 64,
        output_schema_hash="b" * 64,
        pricing={"minimalMaxTotalChargeUsd": 0.01},
        permission_level="limited",
        lifecycle="static_valid",
        discovery_run_id=str(run["run_id"]),
    )
    plan = ops.get_canary_plan(
        str(run["run_id"]),
        goal="compatibility_single",
        candidate_ids=[candidate_id],
        target_slot_count=1,
    )
    assert plan["items"][0]["revision_id"] == exact_revision_id
    batch = ops.create_canary_batch(
        str(run["run_id"]),
        goal="compatibility_single",
        candidate_ids=[candidate_id],
        target_slot_count=1,
        expected_generation=int(plan["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        approval_id="compatibility-exact-proof",
        confirmation=BATCH_CANARY_CONFIRMATION,
        max_candidates=1,
        max_total_charge_usd=float(plan["max_total_charge_usd"]),
        created_by_user_id=str(owner["id"]),
        reference_fingerprints=dict(plan["_reference_fingerprints"]),
    )
    validation_id = str(batch["items"][0]["validation_id"])
    ops.record_validation(
        validation_id,
        status="succeeded",
        semantic_outcome="valid_nonempty",
        cost_usd=0.004,
        cost_final=True,
        dataset_row_count=1,
        mapped_item_count=1,
    )

    promoted_id = ops.promote_compatibility_observation(
        validation_id,
        observed_fields=("identity", "url", "published_at", "content"),
    )

    assert promoted_id == exact_revision_id
    promoted = ops.get_revision(exact_revision_id)
    assert promoted["lifecycle"] == "probationary"
    assert promoted["execution_mode"] == "pinned"
    assert bool(promoted["observed_manifest"]) is False


def test_compatibility_canary_rechecks_hard_fences_before_paid_start(
    tmp_path,
    monkeypatch,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="compatibility-preflight-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store)
    route, run, revisions = _compatibility_discovery(store, ops)
    candidate_id = _candidate_id(store, revisions["pinned"])
    plan = ops.get_canary_plan(
        str(run["run_id"]),
        goal="compatibility_single",
        candidate_ids=[candidate_id],
        target_slot_count=1,
    )
    batch = ops.create_canary_batch(
        str(run["run_id"]),
        goal="compatibility_single",
        candidate_ids=[candidate_id],
        target_slot_count=1,
        expected_generation=int(plan["generation"]),
        expected_plan_hash=str(plan["plan_hash"]),
        approval_id="compatibility-preflight-paid-confirmation",
        confirmation=BATCH_CANARY_CONFIRMATION,
        max_candidates=1,
        max_total_charge_usd=float(plan["max_total_charge_usd"]),
        created_by_user_id=str(owner["id"]),
        reference_fingerprints=dict(plan["_reference_fingerprints"]),
    )

    async def reject_changed_actor(*_args, **_kwargs):
        raise ActorDiscoveryError(
            "actor_price_exceeds_route_cap",
            "Actor price changed after approval",
            status_code=412,
        )

    monkeypatch.setattr(
        ApifyActorDiscoveryService,
        "load_compatibility_candidate",
        reject_changed_actor,
    )

    class NoPaidStartClient:
        token = "test-only-token"
        base_url = "https://api.apify.test/v2"
        http_client = object()

        async def run_actor_detailed(self, *_args, **_kwargs):
            raise AssertionError("paid Actor POST must not run after failed preflight")

    validation_id = str(batch["items"][0]["validation_id"])
    with pytest.raises(ActorOpsError) as caught:
        asyncio.run(
            ApifyActorCanaryRunner(store, ops, NoPaidStartClient()).run(
                validation_id,
                job_id="compatibility-preflight-job",
            )
        )
    assert caught.value.code == "actor_price_exceeds_route_cap"
    persisted = store.connect().execute(
        """
        SELECT status, semantic_outcome, attempt_id, cost_usd,
               cost_final, counts_toward_canary
        FROM apify_actor_validations
        WHERE workspace_id = ? AND validation_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, validation_id),
    ).fetchone()
    assert tuple(persisted) == (
        "failed",
        "actor_price_exceeds_route_cap",
        None,
        0.0,
        1,
        0,
    )
