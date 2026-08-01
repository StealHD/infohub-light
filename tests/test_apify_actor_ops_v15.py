from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from src.services.apify_actor_ops import (
    ActorOpsError,
    ApifyActorOpsService,
    FIRST_ACTIVATION_CONFIRMATION,
    PAID_CANARY_CONFIRMATION,
    RouteInvocationResult,
    source_target_fingerprint,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


FIXED_NOW = datetime(2030, 1, 1, 8, 0, tzinfo=timezone.utc)


def test_discovery_measurement_recommendation_uses_two_successful_routes(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    ops = ApifyActorOpsService(store)
    runs = ops.create_discovery_measurements(
        expected_generation=1,
        max_output_tokens=32768,
        route_keys=("youtube/channel/items", "instagram/profile/items"),
    )
    for run, completion in zip(runs, (5000, 9000), strict=True):
        store.connect().execute(
            """
            UPDATE apify_actor_discovery_runs
            SET stage = 'awaiting_canary_approval'
            WHERE run_id = ?
            """,
            (run["run_id"],),
        )
        store.connect().commit()
        ops.record_discovery_ai_metrics(
            str(run["run_id"]),
            input_tokens=2000,
            completion_tokens=completion,
            reasoning_tokens=completion // 2,
            content_tokens=completion - completion // 2,
            finish_reason="stop",
            latency_ms=1000,
            response_bytes=2048,
            json_status="valid",
            manifest_status="valid",
        )
    summary = ops.discovery_measurement_summary()
    assert summary["recommended_max_output_tokens"] == 14336
    assert summary["measurements"]["youtube"]["ai_completion_tokens"] == 5000
    assert summary["measurements"]["instagram"]["ai_completion_tokens"] == 9000


def _manifest(actor_id: str, build_number: str, host: str = "youtube.com") -> dict:
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
                "pointers": ["/channelId"],
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


def _route(store: ServiceStore, route_key: str = "youtube/channel/items"):
    return store.connect().execute(
        """
        SELECT * FROM apify_actor_route_profiles
        WHERE workspace_id = ? AND route_key = ?
        """,
        (DEFAULT_WORKSPACE_ID, route_key),
    ).fetchone()


def _ready_pool(store: ServiceStore):
    ops = ApifyActorOpsService(
        store,
        now=lambda: FIXED_NOW,
    )
    route = _route(store)
    revision_ids: list[str] = []
    actors = (
        ("publisher-a/channel-one", "publisher-a"),
        ("publisher-b/channel-two", "publisher-b"),
        ("publisher-a/channel-three", "publisher-a"),
    )
    for index, (actor_id, publisher) in enumerate(actors, start=1):
        candidate_id = ops.ensure_candidate(
            str(route["route_id"]),
            actor_id=actor_id,
        )
        revision_id = ops.create_adapter_revision(
            candidate_id=candidate_id,
            actor_id=actor_id,
            publisher=publisher,
            build_id=f"build-{index}",
            build_number=f"1.0.{index}",
            manifest=_manifest(actor_id, f"1.0.{index}"),
            input_schema_hash=hashlib.sha256(f"in-{index}".encode()).hexdigest(),
            output_schema_hash=hashlib.sha256(f"out-{index}".encode()).hexdigest(),
            lifecycle="static_valid",
        )
        store.connect().execute(
            """
            UPDATE apify_actor_adapter_revisions
            SET lifecycle = ?, canary_passed_at = ?
            WHERE revision_id = ?
            """,
            (
                "certified" if index < 3 else "probationary",
                FIXED_NOW.isoformat(),
                revision_id,
            ),
        )
        store.connect().commit()
        revision_ids.append(revision_id)
    ops.replace_active_pool(
        str(route["route_id"]),
        slots={
            "primary": revision_ids[0],
            "backup_1": revision_ids[1],
            "backup_2": revision_ids[2],
        },
        expected_generation=int(route["generation"]),
    )
    return ops, ops.get_route(str(route["route_id"])), revision_ids


def test_active_pool_enforces_2_plus_1_and_generation_cas(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_pool(store)

    assert route["runtime"]["allowed"] is True
    assert route["runtime"]["runnable_count"] == 3
    assert [slot["lifecycle"] for slot in route["slots"]] == [
        "certified",
        "certified",
        "probationary",
    ]
    assert len({slot["actor_id"] for slot in route["slots"]}) == 3
    with pytest.raises(ActorOpsError) as caught:
        ops.replace_active_pool(
            route["route_id"],
            slots={
                "primary": revisions[0],
                "backup_1": revisions[1],
                "backup_2": revisions[2],
            },
            expected_generation=1,
        )
    assert caught.value.code == "apify_actor_route_generation_conflict"


def test_cap_only_update_preserves_circuit_and_route_block_state(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_pool(store)
    primary = next(
        slot for slot in route["slots"] if slot["slot_name"] == "primary"
    )
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'open'
        WHERE workspace_id = ? AND id = ?
        """,
        (DEFAULT_WORKSPACE_ID, primary["candidate_id"]),
    )
    store.connect().execute(
        """
        UPDATE apify_actor_route_profiles
        SET status = 'blocked_unknown_start'
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    )
    store.connect().execute(
        """
        UPDATE apify_actor_routes
        SET status = 'blocked', blocked_reason = 'start_outcome_unknown'
        WHERE workspace_id = ? AND route_key = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_key"]),
    )
    store.connect().commit()

    updated = ops.replace_active_pool(
        route["route_id"],
        slots=dict(zip(("primary", "backup_1", "backup_2"), revisions)),
        expected_generation=route["generation"],
        per_run_cap_usd=0.03,
    )

    assert updated["generation"] == route["generation"] + 1
    assert updated["per_run_cap_usd"] == pytest.approx(0.03)
    assert updated["status"] == "blocked_unknown_start"
    assert updated["runtime"]["allowed"] is False
    assert store.connect().execute(
        "SELECT state FROM apify_actor_candidates WHERE id = ?",
        (primary["candidate_id"],),
    ).fetchone()[0] == "open"
    compatibility = store.connect().execute(
        """
        SELECT status, blocked_reason FROM apify_actor_routes
        WHERE workspace_id = ? AND route_key = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_key"]),
    ).fetchone()
    assert tuple(compatibility) == ("blocked", "start_outcome_unknown")


def test_zero_actual_charge_is_valid_for_attempt_and_canary(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_pool(store)
    snapshot = ops.freeze_execution(route["route_id"])
    attempt_id = ops.begin_attempt(
        snapshot,
        snapshot.slots[0],
        attempt_group_id="zero-charge",
        attempt_index=1,
    )
    ops.finish_attempt(
        attempt_id,
        status="succeeded",
        semantic_outcome="valid_nonempty",
        actual_cost_usd=0.0,
    )
    attempt = store.connect().execute(
        """
        SELECT actual_cost_usd, cost_final, status
        FROM apify_actor_attempts WHERE id = ?
        """,
        (attempt_id,),
    ).fetchone()
    assert tuple(attempt) == (0.0, 1, "succeeded")

    validation = ops.approve_revision_canary(
        route["route_id"],
        revisions[2],
        expected_generation=route["generation"],
        approval_id="approval-zero-actual-charge",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"zero-charge").hexdigest(),
    )
    completed = ops.record_validation(
        validation["validation_id"],
        status="succeeded",
        semantic_outcome="valid_empty",
        cost_usd=0.0,
    )
    assert completed["cost_usd"] == 0.0


def test_unstarted_cancelled_canary_does_not_consume_route_attempt_limit(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_pool(store)
    for index in range(5):
        validation = ops.approve_revision_canary(
            route["route_id"],
            revisions[2],
            expected_generation=route["generation"],
            approval_id=f"approval-cancelled-before-start-{index}",
            confirmation=PAID_CANARY_CONFIRMATION,
            max_cost_usd=0.02,
            reference_fingerprint=hashlib.sha256(
                f"cancelled-{index}".encode()
            ).hexdigest(),
        )
        ops.record_validation(
            validation["validation_id"],
            status="cancelled",
            semantic_outcome="admin_unavailable",
            cost_usd=0.0,
        )

    replacement = ops.approve_revision_canary(
        route["route_id"],
        revisions[2],
        expected_generation=route["generation"],
        approval_id="approval-after-cancelled-before-start",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"replacement").hexdigest(),
    )
    assert replacement["status"] == "queued"


def test_pool_replacement_preserves_unchanged_slot_circuit_state(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_pool(store)
    primary = route["slots"][0]
    backup = ops.get_revision(revisions[1])
    store.connect().execute(
        "UPDATE apify_actor_candidates SET state = 'open' WHERE id = ?",
        (primary["candidate_id"],),
    )
    replacement = ops.create_adapter_revision(
        candidate_id=backup["candidate_id"],
        actor_id=backup["actor_id"],
        publisher=backup["publisher"],
        build_id="build-backup-v2",
        build_number="2.0.2",
        manifest=_manifest(backup["actor_id"], "2.0.2"),
        lifecycle="static_valid",
    )
    store.connect().execute(
        """
        UPDATE apify_actor_adapter_revisions
        SET lifecycle = 'certified'
        WHERE revision_id = ?
        """,
        (replacement,),
    )
    store.connect().commit()

    updated = ops.replace_active_pool(
        route["route_id"],
        slots={
            "primary": revisions[0],
            "backup_1": replacement,
            "backup_2": revisions[2],
        },
        expected_generation=route["generation"],
    )
    assert updated["slots"][0]["candidate_state"] == "open"
    assert updated["runtime"]["runnable_count"] == 2


def test_member_support_checks_are_workspace_bounded(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = _route(store, "x/profile")
    for index in range(10):
        store.connect().execute(
            """
            INSERT INTO apify_actor_discovery_runs (
                run_id, workspace_id, route_id, stage, trigger_reason,
                budget_usd, error_code, query_count, candidate_count,
                rejection_summary_json, created_at, updated_at
            ) VALUES (?, ?, ?, 'blocked_ai_unavailable',
                      'member_support_check', 0.10, 'test', 0, 0, '[]', ?, ?)
            """,
            (
                f"member-rate-limit-{index}",
                DEFAULT_WORKSPACE_ID,
                route["route_id"],
                FIXED_NOW.isoformat(),
                FIXED_NOW.isoformat(),
            ),
        )
    store.connect().commit()

    with pytest.raises(ActorOpsError) as caught:
        ops.request_support_check(
            platform="x",
            target_type="profile",
            capability="items",
            trigger_reason="member_support_check",
            expected_generation=ops.catalog_generation(),
            max_recent_runs=10,
            max_pending_routes=20,
        )
    assert caught.value.code == "apify_actor_support_check_rate_limited"
    assert caught.value.status_code == 429


def test_explicit_rollback_restores_superseded_revision_and_only_one_slot(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_pool(store)
    current_primary = ops.get_revision(revisions[0])
    replacement = ops.create_adapter_revision(
        candidate_id=current_primary["candidate_id"],
        actor_id=current_primary["actor_id"],
        publisher=current_primary["publisher"],
        build_id="build-primary-v2",
        build_number="2.0.1",
        manifest=_manifest(current_primary["actor_id"], "2.0.1"),
        lifecycle="static_valid",
    )
    store.connect().execute(
        """
        UPDATE apify_actor_adapter_revisions
        SET lifecycle = 'certified'
        WHERE revision_id = ?
        """,
        (replacement,),
    )
    store.connect().commit()

    replaced = ops.replace_active_pool(
        route["route_id"],
        slots={
            "primary": replacement,
            "backup_1": revisions[1],
            "backup_2": revisions[2],
        },
        expected_generation=route["generation"],
    )
    superseded = ops.get_revision(revisions[0])
    assert superseded["lifecycle"] == "superseded"
    assert superseded["superseded_from_lifecycle"] == "certified"
    with pytest.raises(ActorOpsError) as caught:
        ops.replace_active_pool(
            route["route_id"],
            slots={
                "primary": revisions[0],
                "backup_1": revisions[1],
                "backup_2": revisions[2],
            },
            expected_generation=replaced["generation"],
        )
    assert caught.value.code == "apify_actor_active_pool_uncertified"

    with pytest.raises(ActorOpsError) as caught:
        ops.replace_active_pool(
            route["route_id"],
            slots={
                "primary": revisions[0],
                "backup_1": revisions[2],
                "backup_2": revisions[1],
            },
            expected_generation=replaced["generation"],
            rollback_revision_id=revisions[0],
        )
    assert caught.value.code == "apify_actor_rollback_scope_invalid"
    unchanged = ops.get_route(route["route_id"])
    assert unchanged["generation"] == replaced["generation"]
    assert [slot["revision_id"] for slot in unchanged["slots"]] == [
        replacement,
        revisions[1],
        revisions[2],
    ]
    assert ops.get_revision(revisions[0])["lifecycle"] == "superseded"
    assert ops.get_revision(replacement)["lifecycle"] == "certified"

    rolled_back = ops.replace_active_pool(
        route["route_id"],
        slots={
            "primary": revisions[0],
            "backup_1": revisions[1],
            "backup_2": revisions[2],
        },
        expected_generation=replaced["generation"],
        rollback_revision_id=revisions[0],
    )
    assert [slot["revision_id"] for slot in rolled_back["slots"]] == revisions
    assert ops.get_revision(revisions[0])["lifecycle"] == "certified"
    assert ops.get_revision(replacement)["lifecycle"] == "superseded"


def test_legacy_builtin_history_requires_explicit_rollback(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_pool(store)
    current = ops.get_revision(revisions[0])
    legacy_revision_id = "apify-revision-legacy-history"
    store.connect().execute(
        """
        INSERT INTO apify_actor_adapter_revisions (
            revision_id, workspace_id, candidate_id, actor_id, publisher,
            build_id, build_number, manifest_json, manifest_hash,
            permission_level, security_evidence_json, lifecycle, created_at
        ) VALUES (?, ?, ?, ?, ?, NULL, NULL, NULL, NULL,
                  'unknown', '{}', 'legacy_builtin', ?)
        """,
        (
            legacy_revision_id,
            DEFAULT_WORKSPACE_ID,
            current["candidate_id"],
            current["actor_id"],
            current["publisher"],
            FIXED_NOW.isoformat(),
        ),
    )
    store.connect().commit()

    slots = {
        "primary": legacy_revision_id,
        "backup_1": revisions[1],
        "backup_2": revisions[2],
    }
    with pytest.raises(ActorOpsError) as caught:
        ops.replace_active_pool(
            route["route_id"],
            slots=slots,
            expected_generation=route["generation"],
        )
    assert caught.value.code == "apify_actor_rollback_revision_required"

    rolled_back = ops.replace_active_pool(
        route["route_id"],
        slots=slots,
        expected_generation=route["generation"],
        rollback_revision_id=legacy_revision_id,
    )
    assert rolled_back["slots"][0]["revision_id"] == legacy_revision_id


def test_revision_certification_requires_canary_and_observation(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = _route(store)
    actor_id = "publisher-a/certification"
    candidate_id = ops.ensure_candidate(str(route["route_id"]), actor_id=actor_id)
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher-a",
        build_id="build-cert",
        build_number="1.0.1",
        manifest=_manifest(actor_id, "1.0.1"),
        lifecycle="static_valid",
    )
    with pytest.raises(ActorOpsError) as caught:
        ops.transition_revision(
            revision_id,
            expected_lifecycle="static_valid",
            lifecycle="probationary",
        )
    assert caught.value.code == "apify_actor_revision_canary_incomplete"

    first = ops.approve_revision_canary(
        str(route["route_id"]),
        revision_id,
        expected_generation=int(route["generation"]),
        approval_id="approval-reference-one",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"reference-one").hexdigest(),
    )
    ops.record_validation(
        first["validation_id"],
        status="succeeded",
        semantic_outcome="valid_nonempty",
        cost_usd=0.01,
    )
    old = (FIXED_NOW - timedelta(hours=49)).isoformat()
    store.connect().execute(
        """
        UPDATE apify_actor_validations
        SET created_at = ?, completed_at = ?
        WHERE validation_id = ?
        """,
        (old, old, first["validation_id"]),
    )
    store.connect().commit()
    ops.transition_revision(
        revision_id,
        expected_lifecycle="static_valid",
        lifecycle="probationary",
    )
    second = ops.approve_revision_canary(
        str(route["route_id"]),
        revision_id,
        expected_generation=int(route["generation"]),
        approval_id="approval-reference-two",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"reference-two").hexdigest(),
    )
    ops.record_validation(
        second["validation_id"],
        status="succeeded",
        semantic_outcome="valid_empty",
        cost_usd=0.01,
    )
    ops.transition_revision(
        revision_id,
        expected_lifecycle="probationary",
        lifecycle="certified",
    )
    assert ops.get_revision(revision_id)["lifecycle"] == "certified"


def test_revision_auto_promotes_after_observation_without_third_canary(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    clock = [FIXED_NOW]
    ops = ApifyActorOpsService(store, now=lambda: clock[0])
    route = _route(store)
    actor_id = "publisher-a/auto-certification"
    candidate_id = ops.ensure_candidate(
        str(route["route_id"]),
        actor_id=actor_id,
    )
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher-a",
        build_id="build-auto",
        build_number="1.0.1",
        manifest=_manifest(actor_id, "1.0.1"),
        lifecycle="static_valid",
    )
    for reference in ("one", "two"):
        validation = ops.approve_revision_canary(
            str(route["route_id"]),
            revision_id,
            expected_generation=int(route["generation"]),
            approval_id=f"approval-auto-{reference}",
            confirmation=PAID_CANARY_CONFIRMATION,
            max_cost_usd=0.02,
            reference_fingerprint=hashlib.sha256(
                reference.encode()
            ).hexdigest(),
        )
        ops.record_validation(
            validation["validation_id"],
            status="succeeded",
            semantic_outcome="valid_nonempty",
            cost_usd=0.01,
        )
        if reference == "one":
            ops.transition_revision(
                revision_id,
                expected_lifecycle="static_valid",
                lifecycle="probationary",
            )
    with pytest.raises(ActorOpsError) as caught:
        ops.transition_revision(
            revision_id,
            expected_lifecycle="probationary",
            lifecycle="certified",
        )
    assert caught.value.code == "apify_actor_revision_observation_incomplete"
    clock[0] = FIXED_NOW + timedelta(hours=47)
    assert ops.promote_eligible_revisions()["promoted"] == 0
    clock[0] = FIXED_NOW + timedelta(hours=49)
    assert ops.promote_eligible_revisions()["promoted"] == 1
    assert ops.get_revision(revision_id)["lifecycle"] == "certified"


def test_successful_route_canary_recovers_static_valid_after_crash(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = _route(store)
    actor_id = "publisher-a/crash-recovery"
    candidate_id = ops.ensure_candidate(
        str(route["route_id"]),
        actor_id=actor_id,
    )
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher-a",
        build_id="build-crash-recovery",
        build_number="1.0.1",
        manifest=_manifest(actor_id, "1.0.1"),
        lifecycle="static_valid",
    )
    validation = ops.approve_revision_canary(
        str(route["route_id"]),
        revision_id,
        expected_generation=int(route["generation"]),
        approval_id="approval-crash-recovery",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"reference").hexdigest(),
    )
    ops.record_validation(
        validation["validation_id"],
        status="succeeded",
        semantic_outcome="valid_nonempty",
        cost_usd=0.01,
    )
    before = store.connect().execute(
        """
        SELECT
            (SELECT COUNT(*) FROM apify_actor_validations) AS validations,
            (SELECT COUNT(*) FROM apify_actor_attempts) AS attempts
        """
    ).fetchone()

    result = ops.promote_eligible_revisions(
        revision_ids=(revision_id,),
        limit=1,
    )

    assert result["recovered"] == 1
    assert result["promoted"] == 0
    assert ops.get_revision(revision_id)["lifecycle"] == "probationary"
    after = store.connect().execute(
        """
        SELECT
            (SELECT COUNT(*) FROM apify_actor_validations) AS validations,
            (SELECT COUNT(*) FROM apify_actor_attempts) AS attempts
        """
    ).fetchone()
    assert dict(after) == dict(before)


def test_route_canary_approval_rejects_duplicate_inflight_spend(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = _route(store)
    actor_id = "publisher-a/inflight"
    candidate_id = ops.ensure_candidate(
        str(route["route_id"]),
        actor_id=actor_id,
    )
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher-a",
        build_id="build-inflight",
        build_number="1.0.1",
        manifest=_manifest(actor_id, "1.0.1"),
        lifecycle="static_valid",
    )
    ops.approve_revision_canary(
        str(route["route_id"]),
        revision_id,
        expected_generation=int(route["generation"]),
        approval_id="approval-inflight-one",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"one").hexdigest(),
    )
    with pytest.raises(ActorOpsError) as caught:
        ops.approve_revision_canary(
            str(route["route_id"]),
            revision_id,
            expected_generation=int(route["generation"]),
            approval_id="approval-inflight-two",
            confirmation=PAID_CANARY_CONFIRMATION,
            max_cost_usd=0.02,
            reference_fingerprint=hashlib.sha256(b"two").hexdigest(),
        )
    assert caught.value.code == "apify_actor_revision_canary_active"


def test_reused_revision_keeps_discovery_run_canary_budgets_isolated(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = _route(store)
    route_id = str(route["route_id"])
    first_run = ops.create_discovery_run(
        route_id,
        trigger_reason="first",
        expected_generation=int(route["generation"]),
        budget_usd=0.02,
    )
    second_run = ops.create_discovery_run(
        route_id,
        trigger_reason="second",
        expected_generation=int(route["generation"]),
        budget_usd=0.02,
    )
    actor_id = "publisher-a/reused-budget"
    candidate_id = ops.ensure_candidate(route_id, actor_id=actor_id)
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher-a",
        build_id="build-reused-budget",
        build_number="1.0.1",
        manifest=_manifest(actor_id, "1.0.1"),
        lifecycle="static_valid",
        discovery_run_id=str(first_run["run_id"]),
    )
    assert ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher-a",
        build_id="build-reused-budget",
        build_number="1.0.1",
        manifest=_manifest(actor_id, "1.0.1"),
        lifecycle="static_valid",
        discovery_run_id=str(second_run["run_id"]),
    ) == revision_id
    for run in (first_run, second_run):
        ops.update_discovery_run(
            str(run["run_id"]),
            expected_stage="queued",
            stage="awaiting_canary_approval",
        )

    first = ops.approve_revision_canary(
        route_id,
        revision_id,
        expected_generation=int(route["generation"]),
        approval_id="approval-first-run",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"first-run").hexdigest(),
        discovery_run_id=str(first_run["run_id"]),
    )
    ops.record_validation(
        first["validation_id"],
        status="succeeded",
        semantic_outcome="valid_nonempty",
        cost_usd=0.02,
    )

    second = ops.approve_revision_canary(
        route_id,
        revision_id,
        expected_generation=int(route["generation"]),
        approval_id="approval-second-run",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"second-run").hexdigest(),
        discovery_run_id=str(second_run["run_id"]),
    )
    stored = store.connect().execute(
        """
        SELECT discovery_run_id
        FROM apify_actor_validations
        WHERE validation_id = ?
        """,
        (second["validation_id"],),
    ).fetchone()
    assert stored["discovery_run_id"] == second_run["run_id"]


def test_source_target_fingerprint_preserves_youtube_channel_id_case() -> None:
    upper = (
        "https://www.youtube.com/feeds/videos.xml?"
        "channel_id=UCabcdefghijklmnopqrstuv"
    )
    lower = upper.replace("UCa", "UCA")
    assert source_target_fingerprint(
        "workspace",
        "route",
        upper,
        platform="youtube",
    ) != source_target_fingerprint(
        "workspace",
        "route",
        lower,
        platform="youtube",
    )
    assert source_target_fingerprint(
        "workspace",
        "route",
        "@OpenAI",
        platform="x",
    ) == source_target_fingerprint(
        "workspace",
        "route",
        "@openai",
        platform="x",
    )
    assert source_target_fingerprint(
        "workspace",
        "route",
        "https://x.com/OpenAI/",
        platform="x",
    ) == source_target_fingerprint(
        "workspace",
        "route",
        "@openai",
        platform="x",
    )


def test_certification_freezes_and_deduplicates_natural_target_identity(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_pool(store)
    revision_id = revisions[2]
    revision = ops.get_revision(revision_id)
    target_a = source_target_fingerprint(
        DEFAULT_WORKSPACE_ID,
        route["route_id"],
        "https://www.youtube.com/@YouTube",
        platform="youtube",
    )
    reference = ops.approve_revision_canary(
        route["route_id"],
        revision_id,
        expected_generation=route["generation"],
        approval_id="approval-deduplicated-reference",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=target_a,
    )
    ops.record_validation(
        reference["validation_id"],
        status="succeeded",
        semantic_outcome="valid_nonempty",
        cost_usd=0.01,
    )
    old = (FIXED_NOW - timedelta(hours=49)).isoformat()
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="rss",
        display_name="Same public reference",
        config={"url": "https://www.youtube.com/@YouTube"},
    )
    store.connect().execute(
        """
        UPDATE apify_actor_validations
        SET created_at = ?, completed_at = ?
        WHERE validation_id = ?
        """,
        (old, old, reference["validation_id"]),
    )
    store.connect().execute(
        """
        INSERT INTO apify_actor_attempts (
            id, workspace_id, route_key, route_generation, candidate_id,
            source_id, attempt_group_id, attempt_index, status,
            semantic_outcome, reserved_usd, actual_cost_usd, cost_final,
            adapter_revision_id, build_id, build_number, manifest_hash,
            target_fingerprint, created_at, started_at, terminal_at, updated_at
        ) VALUES (
            'attempt-deduplicated-target', ?, ?, ?, ?, ?, 'natural:one', 1,
            'succeeded', 'valid_nonempty', 0.02, 0.01, 1,
            ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            route["route_key"],
            route["generation"],
            revision["candidate_id"],
            source_id,
            revision_id,
            revision["build_id"],
            revision["build_number"],
            revision["manifest_hash"],
            target_a,
            old,
            old,
            FIXED_NOW.isoformat(),
            FIXED_NOW.isoformat(),
        ),
    )
    store.connect().commit()

    with pytest.raises(ActorOpsError) as caught:
        ops.transition_revision(
            revision_id,
            expected_lifecycle="probationary",
            lifecycle="certified",
        )
    assert caught.value.code == "apify_actor_revision_canary_incomplete"

    # Rebinding the source cannot rewrite historical attempt identity.
    store.connect().execute(
        """
        UPDATE source_catalog
        SET config_json = ?
        WHERE id = ?
        """,
        ('{"url":"https://www.youtube.com/@GoogleDevelopers"}', source_id),
    )
    store.connect().commit()
    frozen = store.connect().execute(
        """
        SELECT target_fingerprint FROM apify_actor_attempts
        WHERE id = 'attempt-deduplicated-target'
        """
    ).fetchone()
    assert frozen["target_fingerprint"] == target_a


def test_supported_profile_check_creates_safe_discovery_run_without_source(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)

    result = ops.request_support_check(
        platform="instagram",
        target_type="profile",
        capability="items",
        trigger_reason="member_support_check",
        expected_generation=ops.catalog_generation(),
    )

    assert result["kind"] == "discovery"
    assert result["route_id"]
    assert result["discovery_run_id"]
    assert result["support_status"] in {"candidate_shortfall", "discovery_required"}
    assert ops.get_discovery_run(result["discovery_run_id"])["stage"] == "queued"
    assert (
        store.connect().execute(
            """
            SELECT COUNT(*) FROM source_catalog
            WHERE workspace_id = ?
            """,
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()[0]
        == 0
    )


def test_unsupported_profile_is_rejected_before_catalog_cas(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    stale_generation = ops.catalog_generation()
    route = _route(store, "x/profile")
    store.connect().execute(
        """
        UPDATE apify_actor_route_profiles
        SET generation = generation + 1
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    )
    store.connect().commit()

    with pytest.raises(ActorOpsError) as caught:
        ops.request_support_check(
            platform="youtube",
            target_type="profile",
            capability="items",
            trigger_reason="member_support_check",
            expected_generation=stale_generation,
        )

    assert caught.value.code == "apify_actor_route_profile_unsupported"
    assert caught.value.status_code == 422
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM apify_actor_route_profiles
        WHERE workspace_id = ? AND platform = 'youtube'
          AND target_type = 'profile'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()[0] == 0


def test_runtime_ready_legacy_route_still_requests_source_discovery(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = _route(store, "x/profile")
    store.connect().execute(
        """
        UPDATE apify_actor_route_profiles
        SET status = 'ready'
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    )
    store.connect().commit()

    result = ops.request_support_check(
        platform="x",
        target_type="profile",
        capability="items",
        trigger_reason="member_support_check",
        expected_generation=ops.catalog_generation(),
    )

    assert ops.source_capability_ready(str(route["route_id"])) is False
    assert result["kind"] == "discovery"
    assert result["discovery_run_id"]


def test_existing_route_rejects_stale_catalog_token_collision(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    stale_catalog_generation = ops.catalog_generation()
    route = _route(store, "x/profile")
    store.connect().execute(
        """
        UPDATE apify_actor_route_profiles
        SET generation = generation + 3, status = 'ready'
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    )
    store.connect().commit()
    assert int(ops.get_route(str(route["route_id"]))["generation"]) == (
        stale_catalog_generation
    )
    assert ops.catalog_generation() != stale_catalog_generation

    with pytest.raises(ActorOpsError) as caught:
        ops.request_support_check(
            platform="x",
            target_type="profile",
            capability="items",
            trigger_reason="member_support_check",
            expected_generation=stale_catalog_generation,
        )

    assert caught.value.code == "apify_actor_route_generation_conflict"
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM apify_actor_discovery_runs
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    ).fetchone()[0] == 0


def test_source_requires_three_successful_canaries_and_activation_confirmation(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_pool(store)
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Canary source",
        config={"platform": "youtube", "kind": "channel", "target": "safe"},
    )
    binding = ops.bind_source(
        source_id=source_id,
        route_id=route["route_id"],
        target_fingerprint=hashlib.sha256(b"safe-target").hexdigest(),
        mode="fallback",
    )

    for revision_id in revisions:
        validation = ops.approve_source_canary(
            source_id,
            revision_id,
            expected_generation=binding["generation"],
            approval_id=f"approval-source-{revision_id}",
            confirmation=PAID_CANARY_CONFIRMATION,
            max_cost_usd=0.02,
        )
        ops.record_validation(
            validation["validation_id"],
            status="succeeded",
            semantic_outcome="valid_nonempty",
            cost_usd=0.01,
        )
    with pytest.raises(ActorOpsError) as caught:
        ops.activate_binding(
            source_id,
            expected_generation=binding["generation"],
            confirmation="yes",
        )
    assert caught.value.code == "apify_actor_activation_confirmation_required"

    ready = ops.activate_binding(
        source_id,
        expected_generation=binding["generation"],
        confirmation=FIRST_ACTIVATION_CONFIRMATION,
    )
    assert ready["validation_status"] == "ready_3of3"
    assert ready["verified_revision_set_hash"]
    replayed = ops.activate_binding(
        source_id,
        expected_generation=binding["generation"],
        confirmation=FIRST_ACTIVATION_CONFIRMATION,
    )
    assert replayed["_activation_replayed"] is True
    assert replayed["generation"] == ready["generation"]


def test_execute_route_is_serial_and_publish_fence_rejects_hot_swap(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, _revisions = _ready_pool(store)
    called: list[str] = []

    async def invoke(slot, snapshot):
        called.append(slot.slot_name)
        if slot.slot_name == "primary":
            return RouteInvocationResult(
                semantic_outcome="suspicious_empty",
                cost_usd=0.01,
            )
        return RouteInvocationResult(
            value=["safe"],
            semantic_outcome="valid_empty",
            cost_usd=0.01,
        )

    result = asyncio.run(ops.execute_route(route["route_id"], None, invoke))
    assert called == ["primary", "backup_1"]
    assert result.semantic_outcome == "valid_empty"
    assert len(result.attempt_ids) == 2


def test_actor_failure_can_fall_back_without_invalidating_its_own_snapshot(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, _revisions = _ready_pool(store)
    called: list[str] = []

    async def invoke(slot, snapshot):
        called.append(slot.slot_name)
        if slot.slot_name == "primary":
            return RouteInvocationResult(
                semantic_outcome="actor_system_failure",
                failure_scope="actor",
                error_code="apify_actor_system_failure",
                cost_usd=0.01,
            )
        return RouteInvocationResult(
            value=["safe"],
            semantic_outcome="valid_nonempty",
            cost_usd=0.01,
        )

    result = asyncio.run(ops.execute_route(route["route_id"], None, invoke))
    assert called == ["primary", "backup_1"]
    assert result.value == ["safe"]
    assert result.slot_name == "backup_1"
    assert ops.get_route(route["route_id"])["slots"][0]["candidate_state"] == "open"

    snapshot = ops.freeze_execution(route["route_id"])
    store.connect().execute(
        """
        UPDATE apify_actor_route_profiles
        SET generation = generation + 1
        WHERE route_id = ?
        """,
        (route["route_id"],),
    )
    store.connect().commit()
    with pytest.raises(ActorOpsError) as caught:
        ops.assert_publishable(snapshot)
    assert caught.value.code == "apify_actor_publication_stale"


def test_unknown_start_blocks_route_and_key_without_fallback(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, _revisions = _ready_pool(store)
    called: list[str] = []

    async def invoke(slot, snapshot):
        called.append(slot.slot_name)
        return RouteInvocationResult(
            semantic_outcome="start_unknown",
            failure_scope="start_outcome_unknown",
        )

    with pytest.raises(ActorOpsError) as caught:
        asyncio.run(ops.execute_route(route["route_id"], None, invoke))
    assert caught.value.code == "apify_start_outcome_unknown"
    assert called == ["primary"]
    profile = _route(store)
    assert profile["status"] == "blocked_unknown_start"
    key = store.connect().execute(
        """
        SELECT status, blocked_reason FROM apify_key_pool_state
        WHERE workspace_id = ?
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    assert tuple(key) == ("blocked", "start_outcome_unknown")


def test_unknown_start_attempt_and_barriers_commit_atomically(
    tmp_path,
    monkeypatch,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, _revisions = _ready_pool(store)

    async def invoke(_slot, _snapshot):
        return RouteInvocationResult(
            semantic_outcome="start_unknown",
            failure_scope="start_outcome_unknown",
        )

    def fail_barrier(_snapshot):
        raise RuntimeError("injected barrier failure")

    monkeypatch.setattr(ops, "_block_unknown_start", fail_barrier)
    with pytest.raises(RuntimeError, match="injected barrier failure"):
        asyncio.run(ops.execute_route(route["route_id"], None, invoke))

    attempt = store.connect().execute(
        """
        SELECT status FROM apify_actor_attempts
        WHERE attempt_group_id LIKE 'apify-group-%'
        ORDER BY created_at DESC LIMIT 1
        """
    ).fetchone()
    assert attempt["status"] == "running"
    assert _route(store)["status"] == "ready"
    key = store.connect().execute(
        """
        SELECT status FROM apify_key_pool_state
        WHERE workspace_id = ?
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    assert key["status"] != "blocked"
