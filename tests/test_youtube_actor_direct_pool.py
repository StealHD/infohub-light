"""Direct-YouTube Actor pool regressions kept outside frozen ActorOps suites."""

import hashlib

import pytest

from src.services.apify_actor_ops import ActorOpsError, ApifyActorOpsService
from src.storage.service_store import ServiceStore
from test_apify_actor_pool_staging_v18 import FIXED_NOW, _manifest, _revision, _route, _two_actor_pool


def _candidate_id(store: ServiceStore, revision_id: str) -> str:
    row = store.connect().execute(
        "SELECT candidate_id FROM apify_actor_adapter_revisions WHERE revision_id = ?",
        (revision_id,),
    ).fetchone()
    assert row is not None
    return str(row["candidate_id"])


def test_youtube_never_projects_or_plans_x_compatibility_trials(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = _route(store, "youtube/channel/items")
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="youtube-compatibility-guard",
        expected_generation=int(route["generation"]),
    )
    ops.update_discovery_run(
        str(run["run_id"]), expected_stage="queued", stage="candidate_shortfall"
    )

    projected = ops.list_pool_candidates(
        str(route["route_id"]), goal="compatibility_single"
    )

    assert projected["candidates"] == []
    assert projected["blockers"] == ["compatibility_route_unsupported"]
    with pytest.raises(ActorOpsError, match="Compatibility single-Actor") as caught:
        ops.get_canary_plan(
            str(run["run_id"]),
            goal="compatibility_single",
            candidate_ids=["candidate-not-used"],
        )
    assert caught.value.code == "compatibility_route_unsupported"


def test_youtube_keeps_prior_static_candidate_pending_for_server_canary(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route, _active = _two_actor_pool(store, ops)
    route_id = str(route["route_id"])
    prior = ops.create_discovery_run(
        route_id,
        trigger_reason="youtube-prior-safe-candidate",
        expected_generation=int(route["generation"]),
    )
    revision_id = _revision(
        ops,
        route_id,
        actor_id="publisher-new/youtube-direct-candidate",
        publisher="publisher-new",
        build_number="51.0.1",
        host="youtube.com",
        discovery_run_id=str(prior["run_id"]),
    )
    ops.update_discovery_run(
        str(prior["run_id"]), expected_stage="queued", stage="awaiting_canary_approval"
    )
    latest = ops.create_discovery_run(
        route_id,
        trigger_reason="youtube-empty-refresh",
        expected_generation=int(route["generation"]),
    )
    ops.update_discovery_run(
        str(latest["run_id"]), expected_stage="queued", stage="candidate_shortfall"
    )

    projected = ops.list_pool_candidates(
        route_id, goal="add_slot", target_slot="backup_2"
    )
    candidate = next(
        item for item in projected["candidates"]
        if item["candidate_id"] == _candidate_id(store, revision_id)
    )

    assert projected["run_id"] == str(prior["run_id"])
    assert candidate["selectable"] is True
    assert candidate["already_validated"] is False
    plan = ops.get_canary_plan(
        str(latest["run_id"]), goal="add_slot", target_slot="backup_2"
    )
    assert plan["ready"] is True
    assert plan["selection_mode"] == "server"
    assert plan["items"][0]["revision_id"] == revision_id


def test_youtube_server_plan_uses_current_run_and_public_quality_order(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route, _active = _two_actor_pool(store, ops)
    route_id = str(route["route_id"])
    old_run = ops.create_discovery_run(
        route_id, trigger_reason="old-high-quality", expected_generation=int(route["generation"]),
    )
    def create_quality_revision(
        *, actor_id: str, publisher: str, build_number: str, run_id: str, users: int
    ) -> str:
        candidate_id = ops.ensure_candidate(route_id, actor_id=actor_id)
        return ops.create_adapter_revision(
            candidate_id=candidate_id, actor_id=actor_id, publisher=publisher,
            build_id=f"build-{build_number}", build_number=build_number,
            manifest=_manifest(actor_id, build_number, host="youtube.com"),
            input_schema_hash=hashlib.sha256(f"input:{actor_id}".encode()).hexdigest(),
            output_schema_hash=hashlib.sha256(f"output:{actor_id}".encode()).hexdigest(),
            security_evidence={"store_quality": {"user_count": users}},
            discovery_run_id=run_id,
        )

    create_quality_revision(
        actor_id="a-old/very-popular", publisher="a-old", build_number="61.0.1",
        run_id=str(old_run["run_id"]), users=99999,
    )
    current_run = ops.create_discovery_run(
        route_id, trigger_reason="current-candidates", expected_generation=int(route["generation"]),
    )
    current_revision = create_quality_revision(
        actor_id="z-current/available", publisher="z-current", build_number="61.0.2",
        run_id=str(current_run["run_id"]), users=1,
    )
    ops.update_discovery_run(
        str(current_run["run_id"]), expected_stage="queued", stage="awaiting_canary_approval",
    )

    plan = ops.get_canary_plan(
        str(current_run["run_id"]), goal="add_slot", target_slot="backup_2", max_candidates=1,
    )

    assert plan["ready"] is True
    assert plan["selection_mode"] == "server"
    assert plan["items"][0]["revision_id"] == current_revision
