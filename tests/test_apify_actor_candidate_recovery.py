"""A failed Revision must not permanently disable a changed static revision."""

import hashlib

from test_apify_actor_ops_v15 import _manifest, _route

from src.services.apify_actor_ops import (
    PAID_CANARY_CONFIRMATION,
    ApifyActorOpsService,
)
from src.storage.service_store import ServiceStore


def test_changed_manifest_reopens_candidate_but_duplicate_does_not(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = _route(store)
    route_id = str(route["route_id"])
    run = ops.create_discovery_run(
        route_id, trigger_reason="manifest-recovery",
        expected_generation=int(route["generation"]),
    )
    actor_id = "publisher/revision-recovery"
    candidate_id = ops.ensure_candidate(route_id, actor_id=actor_id)
    original = _manifest(actor_id, "1.0.1")
    original_id = ops.create_adapter_revision(
        candidate_id=candidate_id, actor_id=actor_id, publisher="publisher",
        build_id="build-1", build_number="1.0.1", manifest=original,
        input_schema_hash=hashlib.sha256(b"input").hexdigest(),
        output_schema_hash=hashlib.sha256(b"output").hexdigest(),
        discovery_run_id=str(run["run_id"]), lifecycle="static_valid",
    )
    ops.update_discovery_run(
        str(run["run_id"]), expected_stage="queued",
        stage="awaiting_canary_approval",
    )
    validation = ops.approve_revision_canary(
        route_id, original_id, expected_generation=int(route["generation"]),
        approval_id="candidate-recovery-original-failure",
        confirmation=PAID_CANARY_CONFIRMATION, max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"original").hexdigest(),
        discovery_run_id=str(run["run_id"]),
    )
    ops.record_validation(
        str(validation["validation_id"]), status="failed",
        semantic_outcome="apify_actor_contract_mismatch",
        cost_usd=0.01, cost_final=True,
    )

    assert ops.create_adapter_revision(
        candidate_id=candidate_id, actor_id=actor_id, publisher="publisher",
        build_id="build-1", build_number="1.0.1", manifest=original,
        input_schema_hash=hashlib.sha256(b"input").hexdigest(),
        output_schema_hash=hashlib.sha256(b"output").hexdigest(),
        discovery_run_id=str(run["run_id"]), lifecycle="static_valid",
    ) is None
    assert store.connect().execute(
        "SELECT state FROM apify_actor_candidates WHERE id = ?", (candidate_id,)
    ).fetchone()[0] == "disabled"

    changed = _manifest(actor_id, "1.0.1")
    changed["output"]["source_native_id"]["pointers"] = ["/channel/id"]
    assert ops.create_adapter_revision(
        candidate_id=candidate_id, actor_id=actor_id, publisher="publisher",
        build_id="build-1", build_number="1.0.1", manifest=changed,
        input_schema_hash=hashlib.sha256(b"input").hexdigest(),
        output_schema_hash=hashlib.sha256(b"output").hexdigest(),
        discovery_run_id=str(run["run_id"]), lifecycle="static_valid",
    ) != original_id
    recovered = store.connect().execute(
        "SELECT state, last_error_code FROM apify_actor_candidates WHERE id = ?",
        (candidate_id,),
    ).fetchone()
    assert tuple(recovered) == ("open", None)
