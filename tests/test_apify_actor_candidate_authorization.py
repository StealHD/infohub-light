"""Recovered candidates may run once, but a failed Revision stays blocked."""

import hashlib

from test_apify_actor_ops_v15 import _manifest, _route

from src.services.apify_actor_candidate_authorization import (
    route_reference_candidate_authorized,
)
from src.services.apify_actor_ops import (
    PAID_CANARY_CONFIRMATION,
    ApifyActorOpsService,
)
from src.storage.service_store import ServiceStore


def test_open_candidate_is_authorized_only_without_current_revision_failure(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = _route(store)
    route_id = str(route["route_id"])
    run = ops.create_discovery_run(
        route_id, trigger_reason="authorization-test",
        expected_generation=int(route["generation"]),
    )
    actor_id = "publisher/authorization"
    candidate_id = ops.ensure_candidate(route_id, actor_id=actor_id)
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id, actor_id=actor_id, publisher="publisher",
        build_id="build-1", build_number="1.0.1",
        manifest=_manifest(actor_id, "1.0.1"),
        discovery_run_id=str(run["run_id"]), lifecycle="static_valid",
    )
    store.connect().execute(
        "UPDATE apify_actor_candidates SET state = 'open' WHERE id = ?",
        (candidate_id,),
    )
    store.connect().commit()
    assert route_reference_candidate_authorized(
        store.connect(), workspace_id=ops.workspace_id, revision_id=revision_id,
        lifecycle="static_valid", candidate_state="open",
    )

    ops.update_discovery_run(
        str(run["run_id"]), expected_stage="queued",
        stage="awaiting_canary_approval",
    )
    validation = ops.approve_revision_canary(
        route_id, revision_id, expected_generation=int(route["generation"]),
        approval_id="candidate-authorization-failure",
        confirmation=PAID_CANARY_CONFIRMATION, max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"authorization").hexdigest(),
        discovery_run_id=str(run["run_id"]),
    )
    ops.record_validation(
        str(validation["validation_id"]), status="failed",
        semantic_outcome="apify_actor_contract_mismatch",
        cost_usd=0.01, cost_final=True,
    )
    assert not route_reference_candidate_authorized(
        store.connect(), workspace_id=ops.workspace_id, revision_id=revision_id,
        lifecycle="static_valid", candidate_state="open",
    )
