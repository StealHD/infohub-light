"""Discovery must not revive a settled failed exact Actor revision."""

import hashlib

from src.services.apify_actor_candidate_recovery import (
    exact_revision_has_settled_route_failure,
)
from src.services.apify_actor_ops import PAID_CANARY_CONFIRMATION, ApifyActorOpsService
from src.storage.service_store import ServiceStore
from test_apify_actor_ops_v15 import _manifest, _route


def test_exact_revision_failure_stays_out_of_later_discovery(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = _route(store)
    run = ops.create_discovery_run(
        str(route["route_id"]), trigger_reason="exact-revision", expected_generation=int(route["generation"])
    )
    actor_id = "publisher/exact-failure"
    candidate_id = ops.ensure_candidate(str(route["route_id"]), actor_id=actor_id)
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id, actor_id=actor_id, publisher="publisher",
        build_id="build-1", build_number="1.0.1", manifest=_manifest(actor_id, "1.0.1"),
        input_schema_hash=hashlib.sha256(b"input").hexdigest(),
        output_schema_hash=hashlib.sha256(b"output").hexdigest(),
        discovery_run_id=str(run["run_id"]), lifecycle="static_valid",
    )
    assert revision_id is not None
    ops.update_discovery_run(str(run["run_id"]), expected_stage="queued", stage="awaiting_canary_approval")
    validation = ops.approve_revision_canary(
        str(route["route_id"]), revision_id, expected_generation=int(route["generation"]),
        approval_id="exact-revision-failure", confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02, reference_fingerprint=hashlib.sha256(b"reference").hexdigest(),
        discovery_run_id=str(run["run_id"]),
    )
    ops.record_validation(str(validation["validation_id"]), status="failed", semantic_outcome="apify_actor_contract_mismatch", cost_usd=0.01, cost_final=True)

    assert exact_revision_has_settled_route_failure(store.connect(), workspace_id=ops.workspace_id, revision_id=revision_id)
    assert ops.create_adapter_revision(
        candidate_id=candidate_id, actor_id=actor_id, publisher="publisher",
        build_id="build-1", build_number="1.0.1", manifest=_manifest(actor_id, "1.0.1"),
        input_schema_hash=hashlib.sha256(b"input").hexdigest(),
        output_schema_hash=hashlib.sha256(b"output").hexdigest(),
        discovery_run_id=str(run["run_id"]), lifecycle="static_valid",
    ) is None
