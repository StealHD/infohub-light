"""Store-runnable evidence remains attached to X compatibility revisions."""

import pytest

from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import ServiceStore
from test_apify_actor_compatibility_v21 import (
    _candidate_id,
    _compatibility_discovery,
)


def test_compatibility_revision_retains_store_runnable_provenance(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route, run, _revisions = _compatibility_discovery(store, ops)
    values = {
        "route_id": str(route["route_id"]),
        "discovery_run_id": str(run["run_id"]),
        "actor_id": "compatibility/store-proven-x",
        "publisher": "compatibility",
        "build_id": "store-proven-build",
        "build_number": "3.0.0",
        "pricing": {"minimalMaxTotalChargeUsd": 0.01},
        "permission_level": "limited",
        "input_schema_hash": None,
        "output_schema_hash": None,
    }
    revision_id = ops.ensure_compatibility_trial_revision(
        **values, store_runnable_provenance=True
    )
    # Later discovery without the proof must not erase the stored fact.
    assert ops.ensure_compatibility_trial_revision(**values) == revision_id
    assert ops.get_revision(revision_id)["security_evidence"]["store_runnable_provenance"] is True


@pytest.mark.parametrize(
    "failure_code",
    ["apify_actor_start_rejected", "apify_actor_identity_mismatch"],
)
def test_terminal_compatibility_build_is_not_selectable_again(
    tmp_path, failure_code: str
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route, _run, revisions = _compatibility_discovery(store, ops)
    store.connect().execute(
        """
        INSERT INTO apify_actor_validations (
            validation_id, workspace_id, route_id, revision_id, kind,
            target_fingerprint, status, semantic_outcome, cost_usd,
            cost_final, counts_toward_canary, created_at, completed_at
        ) VALUES (?, ?, ?, ?, 'route_reference', ?, 'failed',
                  ?, 0, 1, 0, ?, ?)
        """,
        (
            "store-proven-start-rejected",
            "default",
            str(route["route_id"]),
            revisions["pinned"],
            "a" * 64,
            failure_code,
            "2026-08-14T00:00:00+00:00",
            "2026-08-14T00:00:00+00:00",
        ),
    )
    store.connect().commit()

    rejected = next(
        item
        for item in ops.list_pool_candidates(
            str(route["route_id"]), goal="compatibility_single"
        )["candidates"]
        if item["candidate_id"] == _candidate_id(store, revisions["pinned"])
    )

    assert rejected["selectable"] is False
    assert rejected["unavailable_reason"] == failure_code
