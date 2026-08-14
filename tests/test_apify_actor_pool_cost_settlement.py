"""Never-started validation cost settlement is intentionally narrow."""

from src.services.apify_actor_canary import next_reference_fingerprint
from src.services.apify_actor_ops import (
    PAID_CANARY_CONFIRMATION,
    ApifyActorOpsService,
    RouteExecutionSnapshot,
    RouteSlotSnapshot,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from test_apify_actor_pool_staging_v18 import FIXED_NOW, _revision, _route


def _insert_validation(
    store: ServiceStore,
    *,
    validation_id: str,
    route_id: str,
    revision_id: str,
    outcome: str,
) -> None:
    store.connect().execute(
        """
        INSERT INTO apify_actor_validations (
            validation_id, workspace_id, route_id, revision_id, kind,
            target_fingerprint, status, semantic_outcome, cost_final,
            counts_toward_canary, created_at, completed_at
        ) VALUES (?, ?, ?, ?, 'route_reference', ?, 'failed', ?, 0, 0, ?, ?)
        """,
        (
            validation_id,
            DEFAULT_WORKSPACE_ID,
            route_id,
            revision_id,
            "a" * 64,
            outcome,
            FIXED_NOW.isoformat(),
            FIXED_NOW.isoformat(),
        ),
    )
    store.connect().commit()


def test_settlement_finalizes_only_proven_local_no_start_failures(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = _route(store, "x/profile")
    revision_id = _revision(
        ops,
        str(route["route_id"]),
        actor_id="pool-cost-settlement/x",
        publisher="pool-cost-settlement",
        build_number="1.0.0",
        host="x.com",
    )
    _insert_validation(
        store,
        validation_id="validation-prestart-revision",
        route_id=str(route["route_id"]),
        revision_id=revision_id,
        outcome="revision_not_executable",
    )
    _insert_validation(
        store,
        validation_id="validation-prestart-revoked",
        route_id=str(route["route_id"]),
        revision_id=revision_id,
        outcome="approval_revoked",
    )
    _insert_validation(
        store,
        validation_id="validation-not-proven",
        route_id=str(route["route_id"]),
        revision_id=revision_id,
        outcome="apify_run_status_unavailable",
    )

    settled = ops.reconcile_terminal_no_start_validation_costs()

    assert settled == {"validations": 2, "batch_items": 0, "batches": 0}
    rows = store.connect().execute(
        """SELECT validation_id, cost_usd, cost_final
           FROM apify_actor_validations
           ORDER BY validation_id"""
    ).fetchall()
    assert [tuple(row) for row in rows] == [
        ("validation-not-proven", None, 0),
        ("validation-prestart-revision", 0.0, 1),
        ("validation-prestart-revoked", 0.0, 1),
    ]
    assert ops.reconcile_terminal_no_start_validation_costs()["validations"] == 0


def test_settlement_repairs_running_validation_with_final_over_cap_charge(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = _route(store, "youtube/channel/items")
    revision_id = _revision(
        ops,
        str(route["route_id"]),
        actor_id="pool-cost-settlement/over-cap",
        publisher="pool-cost-settlement",
        build_number="2.0.0",
        host="youtube.com",
    )
    validation = ops.approve_revision_canary(
        str(route["route_id"]),
        revision_id,
        expected_generation=int(route["generation"]),
        approval_id="pool-cost-settlement-over-cap",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=next_reference_fingerprint(
            store,
            workspace_id=DEFAULT_WORKSPACE_ID,
            platform="youtube",
            route_id=str(route["route_id"]),
            revision_id=revision_id,
        ),
    )
    revision = ops.get_revision(revision_id)
    slot = RouteSlotSnapshot(
        slot_name="primary",
        candidate_id=str(revision["candidate_id"]),
        revision_id=revision_id,
        actor_id=str(revision["actor_id"]),
        publisher=str(revision["publisher"]),
        build_id=str(revision["build_id"]),
        build_number=str(revision["build_number"]),
        manifest_hash=str(revision["manifest_hash"]),
        lifecycle=str(revision["lifecycle"]),
        candidate_state="closed",
        manifest=None,
    )
    snapshot = RouteExecutionSnapshot(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_id=str(route["route_id"]),
        route_key=str(route["route_key"]),
        route_generation=int(route["generation"]),
        per_run_cap_usd=0.02,
        slots=(slot,),
    )
    attempt_id = ops.begin_validation_attempt(
        str(validation["validation_id"]), snapshot, slot, job_id=None
    )
    ops.finish_attempt(
        attempt_id,
        status="succeeded",
        semantic_outcome="valid_nonempty",
        actual_cost_usd=0.020001,
    )

    assert ops.reconcile_validation_charge_overages() == 1
    repaired = ops.get_validation(str(validation["validation_id"]))
    assert repaired["status"] == "failed"
    assert repaired["semantic_outcome"] == "apify_actor_charge_above_approved_cap"
    assert repaired["cost_usd"] == 0.020001
    assert repaired["cost_final"] == 1
    assert ops.reconcile_validation_charge_overages() == 0
