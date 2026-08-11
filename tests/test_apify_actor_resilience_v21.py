from __future__ import annotations

import asyncio
import hashlib
from datetime import datetime, timedelta, timezone

import pytest

from src.services.apify_actor_ops import (
    ActorOpsError,
    ApifyActorOpsService,
    RouteInvocationResult,
)
from src.services.apify_actor_resilience import (
    ActorResilienceError,
    ApifyActorResilienceService,
)
from src.services.apify_key_pool import (
    ApifyKeyBusyError,
    ApifyKeyPoolService,
)
from src.services.job_queue import JobQueue
from src.services.secret_store import SecretStore
from src.services.worker import _enqueue_due_actor_freshness_checks
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _store(tmp_path) -> ServiceStore:
    store = ServiceStore(tmp_path)
    store.initialize()
    return store


def _route(ops: ApifyActorOpsService, route_key: str = "x/profile") -> dict:
    return next(row for row in ops.list_routes() if row["route_key"] == route_key)


def _validation_pool(
    store: ServiceStore,
) -> tuple[ApifyKeyPoolService, dict, dict]:
    secrets = SecretStore(store.data_dir)
    refs = []
    for suffix in ("ACQUISITION", "VALIDATION"):
        env_name = f"APIFY_RESILIENCE_{suffix}"
        refs.append(
            store.create_secret_ref(
                workspace_id=DEFAULT_WORKSPACE_ID,
                owner_user_id=None,
                name=suffix.title(),
                env_name=env_name,
                kind="provider",
                provider="apify",
            )
        )
        secrets.set(env_name, f"test-{suffix.casefold()}-token")
    store.initialize()
    service = ApifyKeyPoolService(store, secret_store=secrets)
    state = service.public_state(DEFAULT_WORKSPACE_ID)
    updated = service.set_validation_key(
        DEFAULT_WORKSPACE_ID,
        secret_id=refs[1]["id"],
        expected_generation=int(state["generation"]),
    )
    return service, refs[0], {
        **refs[1],
        "generation": int(updated["generation"]),
    }


def _source_binding(
    store: ServiceStore,
    ops: ApifyActorOpsService,
    route_id: str,
) -> tuple[str, dict]:
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Watermark account",
        config={"platform": "x", "kind": "profile", "target": "example"},
    )
    binding = ops.bind_source(
        source_id=source_id,
        route_id=route_id,
        target_fingerprint="a" * 64,
        mode="primary",
    )
    return source_id, binding


def test_validation_key_is_exclusive_and_never_used_for_acquisition(tmp_path) -> None:
    store = _store(tmp_path)
    pool, acquisition_ref, validation_ref = _validation_pool(store)

    public = pool.public_state(DEFAULT_WORKSPACE_ID)
    assert public["schema_version"] == 2
    assert public["active_secret_id"] == acquisition_ref["id"]
    assert public["validation_secret_id"] == validation_ref["id"]
    assert {
        member["secret_id"]: member["role"] for member in public["members"]
    } == {
        acquisition_ref["id"]: "acquisition",
        validation_ref["id"]: "validation",
    }

    acquisition = pool.acquire_credential(logical_run_id="production")
    validation_pool = ApifyKeyPoolService(
        store,
        secret_store=pool.secret_store,
        run_purpose="validation",
        require_validation_key=True,
    )
    validation = validation_pool.acquire_credential(logical_run_id="canary")

    assert acquisition.secret_id == acquisition_ref["id"]
    assert validation.secret_id == validation_ref["id"]
    assert pool.get_run(acquisition.reservation_id)["purpose"] == "acquisition"
    assert pool.get_run(validation.reservation_id)["purpose"] == "validation"
    with pytest.raises(ApifyKeyBusyError):
        validation_pool.acquire_credential(logical_run_id="duplicate-canary")

    validation_pool.report_start_outcome_unknown(validation)
    assert pool.public_state(DEFAULT_WORKSPACE_ID)["status"] == "ready"
    with pytest.raises(ApifyKeyBusyError):
        validation_pool.acquire_credential(logical_run_id="before-reconcile")


def test_manual_validation_fallback_keeps_validation_purpose(tmp_path) -> None:
    store = _store(tmp_path)
    pool, acquisition_ref, validation_ref = _validation_pool(store)
    pool.set_validation_key(
        DEFAULT_WORKSPACE_ID,
        secret_id=None,
        expected_generation=int(validation_ref["generation"]),
    )
    manual_validation = ApifyKeyPoolService(
        store,
        secret_store=pool.secret_store,
        run_purpose="validation",
        require_validation_key=False,
    )

    lease = manual_validation.acquire_credential(logical_run_id="manual-canary")

    assert lease.secret_id == acquisition_ref["id"]
    assert manual_validation.get_run(lease.reservation_id)["purpose"] == (
        "validation"
    )
    manual_validation.assert_lease_startable(lease)
    manual_validation.register_run(
        lease,
        "manual-validation-run",
        "manual-validation-dataset",
    )


def test_freshness_frequency_requires_key_confirmation_and_bounds(tmp_path) -> None:
    store = _store(tmp_path)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    resilience = ApifyActorResilienceService(store)
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="freshness-owner",
        password="safe-test-password",
        role="owner",
    )

    with pytest.raises(ActorResilienceError) as missing_key:
        resilience.update_freshness_settings(
            str(route["route_id"]),
            enabled=True,
            interval_hours=24,
            expected_generation=int(route["generation"]),
            actor_user_id=str(owner["id"]),
            standing_authorization_confirmed=True,
        )
    assert missing_key.value.code == "apify_validation_key_required"

    _validation_pool(store)
    route = ops.get_route(str(route["route_id"]))
    with pytest.raises(ActorResilienceError) as missing_confirmation:
        resilience.update_freshness_settings(
            str(route["route_id"]),
            enabled=True,
            interval_hours=24,
            expected_generation=int(route["generation"]),
            actor_user_id=str(owner["id"]),
            standing_authorization_confirmed=False,
        )
    assert missing_confirmation.value.code == "freshness_authorization_required"

    for invalid in (5, 169):
        with pytest.raises(ActorResilienceError) as out_of_range:
            resilience.update_freshness_settings(
                str(route["route_id"]),
                enabled=True,
                interval_hours=invalid,
                expected_generation=int(route["generation"]),
                actor_user_id=str(owner["id"]),
                standing_authorization_confirmed=True,
            )
        assert out_of_range.value.code == "invalid_freshness_interval"

    enabled = resilience.update_freshness_settings(
        str(route["route_id"]),
        enabled=True,
        interval_hours=6,
        expected_generation=int(route["generation"]),
        actor_user_id=str(owner["id"]),
        standing_authorization_confirmed=True,
    )
    assert enabled["freshness"]["enabled"] is True
    assert enabled["freshness"]["interval_hours"] == 6
    assert enabled["freshness"]["theoretical_monthly_max_usd"] > 0

    disabled = resilience.update_freshness_settings(
        str(route["route_id"]),
        enabled=False,
        interval_hours=168,
        expected_generation=int(ops.get_route(str(route["route_id"]))["generation"]),
        actor_user_id=str(owner["id"]),
        standing_authorization_confirmed=False,
    )
    assert disabled["freshness"]["enabled"] is False
    assert disabled["freshness"]["next_check_at"] is None


def test_freshness_cannot_be_authorized_for_an_empty_actor_route(tmp_path) -> None:
    store = _store(tmp_path)
    _validation_pool(store)
    ops = ApifyActorOpsService(store)
    route = _route(ops, "youtube/channel/items")
    resilience = ApifyActorResilienceService(store)
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="empty-freshness-owner",
        password="safe-test-password",
        role="owner",
    )

    assert resilience.freshness_plan(str(route["route_id"]))[
        "max_total_charge_usd"
    ] == 0
    with pytest.raises(ActorResilienceError) as empty_route:
        resilience.update_freshness_settings(
            str(route["route_id"]),
            enabled=True,
            interval_hours=24,
            expected_generation=int(route["generation"]),
            actor_user_id=str(owner["id"]),
            standing_authorization_confirmed=True,
        )
    assert empty_route.value.code == "apify_actor_route_empty"


def test_freshness_job_rejects_a_changed_actor_route(tmp_path) -> None:
    store = _store(tmp_path)
    _validation_pool(store)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    route_id = str(route["route_id"])
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="freshness-route-fence-owner",
        password="safe-test-password",
        role="owner",
    )
    resilience = ApifyActorResilienceService(store)
    check = resilience.create_freshness_check(
        route_id,
        trigger_kind="manual",
        actor_user_id=str(owner["id"]),
        cost_confirmed=True,
        expected_generation=int(route["generation"]),
        approved_max_total_charge_usd=float(
            resilience.freshness_plan(route_id)["max_total_charge_usd"]
        ),
    )
    current = ops.get_route(route_id)
    with pytest.raises(ActorOpsError) as active_check:
        ops.replace_active_pool(
            route_id,
            slots={
                str(slot["slot_name"]): slot["revision_id"]
                for slot in current["slots"]
            },
            expected_generation=int(current["generation"]),
            per_run_cap_usd=0.019,
        )
    assert active_check.value.code == "apify_actor_freshness_active"
    store.connect().execute(
        """
        UPDATE apify_actor_route_profiles
        SET generation = generation + 1
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route_id),
    )
    store.connect().commit()

    with pytest.raises(ActorResilienceError) as changed:
        resilience.begin_freshness_check(str(check["check_id"]))

    assert changed.value.code == "freshness_plan_changed"
    assert resilience.get_freshness_check(str(check["check_id"]))["status"] == (
        "queued"
    )


def test_automatic_freshness_enqueue_is_due_only_and_deduplicated(tmp_path) -> None:
    store = _store(tmp_path)
    _validation_pool(store)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="freshness-scheduler-owner",
        password="safe-test-password",
        role="owner",
    )
    resilience = ApifyActorResilienceService(store)
    resilience.update_freshness_settings(
        str(route["route_id"]),
        enabled=True,
        interval_hours=24,
        expected_generation=int(route["generation"]),
        actor_user_id=str(owner["id"]),
        standing_authorization_confirmed=True,
    )
    store.connect().execute(
        """
        UPDATE apify_actor_route_profiles
        SET freshness_next_check_at = '2000-01-01T00:00:00+00:00'
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, str(route["route_id"])),
    )
    store.connect().commit()
    queue = JobQueue(store)

    first = _enqueue_due_actor_freshness_checks(store, queue)
    second = _enqueue_due_actor_freshness_checks(store, queue)

    assert first == {"enqueued": 1, "blocked": 0}
    assert second == {"enqueued": 0, "blocked": 0}
    jobs = queue.list_jobs(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=str(owner["id"]),
        limit=20,
    )
    freshness_jobs = [
        job
        for job in jobs
        if job["job_type"] == "apify_actor_freshness_check"
    ]
    assert len(freshness_jobs) == 1
    assert freshness_jobs[0]["priority"] == 100
    assert freshness_jobs[0]["max_attempts"] == 1


def test_due_freshness_blocks_without_borrowing_a_production_key(tmp_path) -> None:
    store = _store(tmp_path)
    pool, _acquisition, validation = _validation_pool(store)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="freshness-no-key-owner",
        password="safe-test-password",
        role="owner",
    )
    resilience = ApifyActorResilienceService(store)
    resilience.update_freshness_settings(
        str(route["route_id"]),
        enabled=True,
        interval_hours=24,
        expected_generation=int(route["generation"]),
        actor_user_id=str(owner["id"]),
        standing_authorization_confirmed=True,
    )
    pool.set_validation_key(
        DEFAULT_WORKSPACE_ID,
        secret_id=None,
        expected_generation=int(validation["generation"]),
    )
    store.connect().execute(
        """
        UPDATE apify_actor_route_profiles
        SET freshness_next_check_at = '2000-01-01T00:00:00+00:00'
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, str(route["route_id"])),
    )
    store.connect().commit()

    result = _enqueue_due_actor_freshness_checks(store, JobQueue(store))

    assert result == {"enqueued": 0, "blocked": 0}
    assert resilience.route_resilience(str(route["route_id"]))["freshness"][
        "status"
    ] == "blocked_no_validation_key"
    assert pool.public_state(DEFAULT_WORKSPACE_ID)["active_secret_id"] is not None


def test_source_watermark_classifies_advance_repeat_and_regression(tmp_path) -> None:
    store = _store(tmp_path)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    route_detail = ops.get_route(str(route["route_id"]))
    selected = next(
        slot for slot in route_detail["slots"] if slot["candidate_state"] == "closed"
    )
    source_id, binding = _source_binding(store, ops, str(route["route_id"]))
    resilience = ApifyActorResilienceService(store)
    preference = resilience.set_source_preference(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        expected_generation=int(binding["generation"]),
    )
    t1 = "2026-08-11T10:00:00+00:00"

    assert resilience.classify_source_result(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        latest_published_at=t1,
        latest_item_id="item-a",
        semantic_outcome="valid_nonempty",
    ) == "advanced"
    watermark_before_empty = store.connect().execute(
        """
        SELECT watermark_item_id_hash FROM apify_source_route_bindings
        WHERE workspace_id = ? AND source_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, source_id),
    ).fetchone()["watermark_item_id_hash"]
    assert resilience.classify_source_result(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        latest_published_at=None,
        latest_item_id=None,
        semantic_outcome="valid_empty",
    ) == "valid_empty"
    assert resilience.classify_source_result(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        latest_published_at=t1,
        latest_item_id="item-a",
        semantic_outcome="valid_empty",
    ) == "no_advance"
    assert store.connect().execute(
        """
        SELECT watermark_item_id_hash FROM apify_source_route_bindings
        WHERE workspace_id = ? AND source_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, source_id),
    ).fetchone()["watermark_item_id_hash"] == watermark_before_empty
    assert resilience.classify_source_result(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        latest_published_at="2026-08-10T10:00:00+00:00",
        latest_item_id="window-old-item",
        semantic_outcome="valid_empty",
    ) == "stale_regression"
    assert resilience.classify_source_result(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        latest_published_at=t1,
        latest_item_id="item-a",
        semantic_outcome="valid_nonempty",
    ) == "no_advance"
    assert resilience.classify_source_result(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        latest_published_at=t1,
        latest_item_id="item-b",
        semantic_outcome="valid_nonempty",
    ) == "advanced"
    assert resilience.classify_source_result(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        latest_published_at="2026-08-10T10:00:00+00:00",
        latest_item_id="old-item",
        semantic_outcome="valid_nonempty",
    ) == "stale_regression"
    assert resilience.source_preference(source_id)["preference_suspended"] is True

    for published_at, item_id in (
        ("2026-08-11T11:00:00+00:00", "item-c"),
        ("2026-08-11T12:00:00+00:00", "item-d"),
    ):
        assert resilience.classify_source_result(
            source_id,
            candidate_id=str(selected["candidate_id"]),
            latest_published_at=published_at,
            latest_item_id=item_id,
            semantic_outcome="valid_nonempty",
        ) == "advanced"
    recovered = resilience.source_preference(source_id)
    assert recovered["preferred_candidate_id"] == preference["preferred_candidate_id"]
    assert recovered["preference_suspended"] is False
    assert recovered["preference_recovery_successes"] == 2
    row = store.connect().execute(
        """
        SELECT watermark_item_id_hash FROM apify_source_route_bindings
        WHERE workspace_id = ? AND source_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, source_id),
    ).fetchone()
    assert row["watermark_item_id_hash"] == hashlib.sha256(b"item-d").hexdigest()


def test_deferred_watermark_advances_only_with_publication_transaction(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    selected = next(
        slot
        for slot in ops.get_route(str(route["route_id"]))["slots"]
        if slot["candidate_state"] == "closed"
    )
    source_id, _binding = _source_binding(
        store,
        ops,
        str(route["route_id"]),
    )
    resilience = ApifyActorResilienceService(store)
    published_at = "2026-08-11T10:00:00+00:00"
    item_hash = hashlib.sha256(b"deferred-item").hexdigest()

    assert resilience.classify_source_result(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        latest_published_at=published_at,
        latest_item_id="deferred-item",
        semantic_outcome="valid_nonempty",
        defer_publication=True,
    ) == "advanced"
    assert store.connect().execute(
        """
        SELECT watermark_latest_published_at
        FROM apify_source_route_bindings
        WHERE workspace_id = ? AND source_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, source_id),
    ).fetchone()["watermark_latest_published_at"] is None

    connection = store.connect()
    connection.execute("BEGIN IMMEDIATE")
    resilience.publish_source_advance(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        latest_published_at=published_at,
        latest_item_id_hash=item_hash,
        connection=connection,
    )
    connection.rollback()
    assert connection.execute(
        """
        SELECT watermark_latest_published_at
        FROM apify_source_route_bindings
        WHERE workspace_id = ? AND source_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, source_id),
    ).fetchone()["watermark_latest_published_at"] is None

    connection.execute("BEGIN IMMEDIATE")
    resilience.publish_source_advance(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        latest_published_at=published_at,
        latest_item_id_hash=item_hash,
        connection=connection,
    )
    connection.commit()
    row = connection.execute(
        """
        SELECT watermark_latest_published_at, watermark_item_id_hash
        FROM apify_source_route_bindings
        WHERE workspace_id = ? AND source_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, source_id),
    ).fetchone()
    assert row["watermark_latest_published_at"] == published_at
    assert row["watermark_item_id_hash"] == item_hash


def test_source_preference_can_select_a_probationary_active_actor(tmp_path) -> None:
    store = _store(tmp_path)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    route_id = str(route["route_id"])
    active = [
        slot
        for slot in ops.get_route(route_id)["slots"]
        if slot["candidate_state"] != "disabled"
    ]
    selected = active[1]
    store.connect().execute(
        """
        UPDATE apify_actor_candidates SET state = 'probationary'
        WHERE workspace_id = ? AND id = ?
        """,
        (DEFAULT_WORKSPACE_ID, str(selected["candidate_id"])),
    )
    store.connect().commit()
    source_id, binding = _source_binding(store, ops, route_id)
    resilience = ApifyActorResilienceService(store)

    preference = resilience.set_source_preference(
        source_id,
        candidate_id=str(selected["candidate_id"]),
        expected_generation=int(binding["generation"]),
    )
    store.connect().execute(
        """
        UPDATE apify_source_route_bindings
        SET validation_status = 'legacy_validation_pending'
        WHERE workspace_id = ? AND source_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, source_id),
    )
    store.connect().commit()
    snapshot = ops.freeze_execution(route_id, source_id=source_id)

    assert preference["preference_suspended"] is False
    assert snapshot.slots[0].candidate_id == str(selected["candidate_id"])


def test_ops_runtime_failure_suspends_preference_and_soft_falls_back(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    ops = ApifyActorOpsService(store)
    route_id = str(_route(ops)["route_id"])
    active = [
        slot
        for slot in ops.get_route(route_id)["slots"]
        if slot["candidate_state"] != "disabled"
    ]
    preferred = active[1]
    source_id, binding = _source_binding(store, ops, route_id)
    resilience = ApifyActorResilienceService(store)
    resilience.set_source_preference(
        source_id,
        candidate_id=str(preferred["candidate_id"]),
        expected_generation=int(binding["generation"]),
    )
    store.connect().execute(
        """
        UPDATE apify_source_route_bindings
        SET validation_status = 'legacy_validation_pending'
        WHERE workspace_id = ? AND source_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, source_id),
    )
    store.connect().commit()

    async def invoke(slot, _snapshot):
        if slot.candidate_id == str(preferred["candidate_id"]):
            return RouteInvocationResult(
                semantic_outcome="apify_actor_contract_mismatch",
                failure_scope="actor",
                error_code="apify_actor_contract_mismatch",
            )
        return RouteInvocationResult(value=[], semantic_outcome="valid_empty")

    snapshot = ops.freeze_execution(
        route_id,
        source_id=source_id,
        enforce_gate=False,
    )
    result = asyncio.run(
        ops.execute_route(
            route_id,
            source_id,
            invoke,
            frozen_snapshot=snapshot,
        )
    )

    assert result.slot_name != str(preferred["slot_name"])
    preference = resilience.source_preference(source_id)
    assert preference["preferred_candidate_id"] == preferred["candidate_id"]
    assert preference["preference_suspended"] is True
    assert preference["preference_recovery_successes"] == 0


def test_two_actor_freshness_requires_repeat_before_stale(tmp_path) -> None:
    store = _store(tmp_path)
    _validation_pool(store)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    route_id = str(route["route_id"])
    resilience = ApifyActorResilienceService(store)
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="freshness-check-owner",
        password="safe-test-password",
        role="owner",
    )
    active = [
        slot
        for slot in ops.get_route(route_id)["slots"]
        if slot["candidate_state"] != "disabled"
    ]
    assert len(active) == 2
    source_id, binding = _source_binding(store, ops, route_id)
    resilience.set_source_preference(
        source_id,
        candidate_id=str(active[1]["candidate_id"]),
        expected_generation=int(binding["generation"]),
    )
    store.connect().execute(
        """
        UPDATE apify_source_route_bindings
        SET preference_suspended_at = '2026-08-01T00:00:00+00:00'
        WHERE workspace_id = ? AND source_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, source_id),
    )
    store.connect().commit()

    def run_round(index: int) -> dict:
        check = resilience.create_freshness_check(
            route_id,
            trigger_kind="manual",
            actor_user_id=str(owner["id"]),
            cost_confirmed=True,
            expected_generation=int(ops.get_route(route_id)["generation"]),
            approved_max_total_charge_usd=float(
                resilience.freshness_plan(route_id)["max_total_charge_usd"]
            ),
        )
        resilience.begin_freshness_check(str(check["check_id"]))
        return resilience.complete_freshness_check(
            str(check["check_id"]),
            samples=[
                {
                    "candidate_id": str(active[0]["candidate_id"]),
                    "revision_id": str(active[0]["revision_id"]),
                    "successful": True,
                    "timely": True,
                    "semantic_outcome": "valid_nonempty",
                    "reason_code": "freshness_sample_valid",
                    "latest_published_at": "2026-08-10T00:00:00+00:00",
                    "latest_item_id": "older",
                    "actual_cost_usd": 0.001 + index / 10000,
                    "cost_final": True,
                },
                {
                    "candidate_id": str(active[1]["candidate_id"]),
                    "revision_id": str(active[1]["revision_id"]),
                    "successful": True,
                    "timely": True,
                    "semantic_outcome": "valid_nonempty",
                    "reason_code": "freshness_sample_valid",
                    "latest_published_at": "2026-08-11T00:00:00+00:00",
                    "latest_item_id": "newer",
                    "actual_cost_usd": 0.001,
                    "cost_final": True,
                },
            ],
        )

    first = run_round(1)
    assert [row["status"] for row in first["results"]] == [
        "suspected_stale",
        "fresh",
    ]
    assert resilience.source_preference(source_id)["preference_suspended"] is True
    second = run_round(2)
    assert [row["status"] for row in second["results"]] == ["stale", "fresh"]
    assert resilience.source_preference(source_id)["preference_suspended"] is False
    assert resilience.source_preference(source_id)[
        "preference_recovery_successes"
    ] == 2
    stale_candidate = store.connect().execute(
        "SELECT state, last_error_code FROM apify_actor_candidates WHERE id = ?",
        (str(active[0]["candidate_id"]),),
    ).fetchone()
    assert dict(stale_candidate) == {
        "state": "open",
        "last_error_code": "apify_actor_stale_content",
    }


def test_three_actor_freshness_uses_majority_fingerprint(tmp_path) -> None:
    store = _store(tmp_path)
    _validation_pool(store)
    ops = ApifyActorOpsService(store)
    route_id = str(_route(ops)["route_id"])
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'open', last_error_code = NULL
        WHERE workspace_id = ? AND id IN (
            SELECT revision.candidate_id
            FROM apify_route_active_slots AS slot
            JOIN apify_actor_adapter_revisions AS revision
              ON revision.workspace_id = slot.workspace_id
             AND revision.revision_id = slot.revision_id
            WHERE slot.workspace_id = ? AND slot.route_id = ?
        )
        """,
        (DEFAULT_WORKSPACE_ID, DEFAULT_WORKSPACE_ID, route_id),
    )
    store.connect().commit()
    active = [
        slot
        for slot in ops.get_route(route_id)["slots"]
        if slot["candidate_state"] != "disabled"
    ]
    assert len(active) == 3
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="majority-freshness-owner",
        password="safe-test-password",
        role="owner",
    )
    resilience = ApifyActorResilienceService(store)
    check = resilience.create_freshness_check(
        route_id,
        trigger_kind="manual",
        actor_user_id=str(owner["id"]),
        cost_confirmed=True,
        expected_generation=int(ops.get_route(route_id)["generation"]),
        approved_max_total_charge_usd=float(
            resilience.freshness_plan(route_id)["max_total_charge_usd"]
        ),
    )
    resilience.begin_freshness_check(str(check["check_id"]))
    completed = resilience.complete_freshness_check(
        str(check["check_id"]),
        samples=[
            {
                "candidate_id": str(slot["candidate_id"]),
                "revision_id": str(slot["revision_id"]),
                "successful": True,
                "timely": True,
                "semantic_outcome": "valid_nonempty",
                "reason_code": "freshness_sample_valid",
                "latest_published_at": (
                    "2026-08-11T00:00:00+00:00"
                    if index < 2
                    else "2026-08-10T00:00:00+00:00"
                ),
                "latest_item_id": "majority" if index < 2 else "older",
                "actual_cost_usd": 0.001,
                "cost_final": True,
            }
            for index, slot in enumerate(active)
        ],
    )
    assert [row["status"] for row in completed["results"]] == [
        "fresh",
        "fresh",
        "stale",
    ]
    assert completed["results"][2]["reason_code"] == "behind_majority_latest"


def test_single_actor_freshness_is_explicitly_not_cross_validated(tmp_path) -> None:
    store = _store(tmp_path)
    _validation_pool(store)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    route_id = str(route["route_id"])
    active = [
        slot
        for slot in ops.get_route(route_id)["slots"]
        if slot["candidate_state"] != "disabled"
    ]
    store.connect().execute(
        "UPDATE apify_actor_candidates SET state = 'disabled' WHERE id = ?",
        (str(active[1]["candidate_id"]),),
    )
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'open', last_error_code = 'apify_actor_stale_content'
        WHERE id = ?
        """,
        (str(active[0]["candidate_id"]),),
    )
    store.connect().commit()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="single-freshness-owner",
        password="safe-test-password",
        role="owner",
    )
    resilience = ApifyActorResilienceService(store)
    check = resilience.create_freshness_check(
        route_id,
        trigger_kind="manual",
        actor_user_id=str(owner["id"]),
        cost_confirmed=True,
        expected_generation=int(ops.get_route(route_id)["generation"]),
        approved_max_total_charge_usd=float(
            resilience.freshness_plan(route_id)["max_total_charge_usd"]
        ),
    )
    resilience.begin_freshness_check(str(check["check_id"]))
    completed = resilience.complete_freshness_check(
        str(check["check_id"]),
        samples=[
            {
                "candidate_id": str(active[0]["candidate_id"]),
                "revision_id": str(active[0]["revision_id"]),
                "successful": True,
                "timely": True,
                "semantic_outcome": "valid_nonempty",
                "reason_code": "freshness_sample_valid",
                "latest_published_at": "2026-08-11T00:00:00+00:00",
                "latest_item_id": "single",
                "actual_cost_usd": 0.001,
                "cost_final": True,
            }
        ],
    )
    assert completed["status"] == "succeeded"
    assert completed["results"][0]["status"] == "unverified_single"
    assert completed["results"][0]["reason_code"] == "cannot_cross_validate"
    assert completed["results"][0]["consecutive_fresh_count"] == 1
    assert resilience.route_resilience(route_id)["freshness"]["status"] == (
        "unverified_single"
    )
    assert store.connect().execute(
        "SELECT state FROM apify_actor_candidates WHERE id = ?",
        (str(active[0]["candidate_id"]),),
    ).fetchone()["state"] == "open"

    second = resilience.create_freshness_check(
        route_id,
        trigger_kind="manual",
        actor_user_id=str(owner["id"]),
        cost_confirmed=True,
        expected_generation=int(ops.get_route(route_id)["generation"]),
        approved_max_total_charge_usd=float(
            resilience.freshness_plan(route_id)["max_total_charge_usd"]
        ),
    )
    resilience.begin_freshness_check(str(second["check_id"]))
    recovered = resilience.complete_freshness_check(
        str(second["check_id"]),
        samples=[
            {
                "candidate_id": str(active[0]["candidate_id"]),
                "revision_id": str(active[0]["revision_id"]),
                "successful": True,
                "timely": True,
                "semantic_outcome": "valid_nonempty",
                "reason_code": "freshness_sample_valid",
                "latest_published_at": "2026-08-11T00:00:00+00:00",
                "latest_item_id": "single",
                "actual_cost_usd": 0.001,
                "cost_final": True,
            }
        ],
    )
    assert recovered["results"][0]["status"] == "unverified_single"
    assert recovered["results"][0]["consecutive_fresh_count"] == 2
    candidate = store.connect().execute(
        "SELECT state, last_error_code FROM apify_actor_candidates WHERE id = ?",
        (str(active[0]["candidate_id"]),),
    ).fetchone()
    assert dict(candidate) == {"state": "closed", "last_error_code": None}


def test_freshness_cost_reconciliation_publishes_only_final_charges(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    pool, _acquisition, _validation = _validation_pool(store)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    route_id = str(route["route_id"])
    active = [
        slot
        for slot in ops.get_route(route_id)["slots"]
        if slot["candidate_state"] != "disabled"
    ]
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="freshness-cost-owner",
        password="safe-test-password",
        role="owner",
    )
    resilience = ApifyActorResilienceService(store)
    check = resilience.create_freshness_check(
        route_id,
        trigger_kind="manual",
        actor_user_id=str(owner["id"]),
        cost_confirmed=True,
        expected_generation=int(route["generation"]),
        approved_max_total_charge_usd=float(
            resilience.freshness_plan(route_id)["max_total_charge_usd"]
        ),
    )
    check_id = str(check["check_id"])
    resilience.begin_freshness_check(check_id)
    completed = resilience.complete_freshness_check(
        check_id,
        samples=[
            {
                "candidate_id": str(slot["candidate_id"]),
                "revision_id": str(slot["revision_id"]),
                "successful": True,
                "timely": True,
                "semantic_outcome": "valid_nonempty",
                "reason_code": "freshness_sample_valid",
                "latest_published_at": "2026-08-11T00:00:00+00:00",
                "latest_item_id": "shared-latest",
                "actual_cost_usd": 0.0001,
                "cost_final": False,
            }
            for slot in active
        ],
    )
    assert completed["actual_cost_usd"] is None
    assert completed["cost_final"] is False
    assert resilience.route_resilience(route_id)["freshness"][
        "last_actual_cost_usd"
    ] is None
    assert all(
        event["final_cost_usd"] is None
        for event in resilience.list_events(
            route_id=route_id,
            phase="freshness",
        )["events"]
        if event["reason_code"] == "latest_fingerprint_matches"
    )

    validation_pool = ApifyKeyPoolService(
        store,
        secret_store=pool.secret_store,
        run_purpose="validation",
        require_validation_key=True,
    )
    for index, (slot, actual) in enumerate(zip(active, (0.001, 0.002), strict=True)):
        logical_run_id = f"freshness:{check_id}:{slot['candidate_id']}"
        lease = validation_pool.acquire_credential(
            logical_run_id=logical_run_id
        )
        validation_pool.assert_lease_startable(lease)
        validation_pool.register_run(
            lease,
            f"freshness-remote-{index}",
            f"freshness-dataset-{index}",
        )
        validation_pool.record_run_accounting(
            lease,
            actual_cost_usd=actual,
            cost_final=True,
        )
        validation_pool.mark_run_terminal(
            lease,
            f"freshness-remote-{index}",
            "SUCCEEDED",
        )

    reconciled = resilience.reconcile_terminal_freshness_costs()
    settled = resilience.get_freshness_check(check_id)

    assert reconciled == {"results": 2, "checks": 1}
    assert settled["actual_cost_usd"] == pytest.approx(0.003)
    assert settled["cost_final"] is True
    assert resilience.route_resilience(route_id)["freshness"][
        "last_actual_cost_usd"
    ] == pytest.approx(0.003)
    cost_events = resilience.list_events(
        route_id=route_id,
        phase="cost_reconciliation",
    )["events"]
    assert len(cost_events) == 2
    assert sorted(event["final_cost_usd"] for event in cost_events) == [
        0.001,
        0.002,
    ]


def test_two_actor_same_time_mismatch_stays_ambiguous_across_rounds(
    tmp_path,
) -> None:
    store = _store(tmp_path)
    _validation_pool(store)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    route_id = str(route["route_id"])
    active = [
        slot
        for slot in ops.get_route(route_id)["slots"]
        if slot["candidate_state"] != "disabled"
    ]
    states_before = {
        str(row["id"]): str(row["state"])
        for row in store.connect().execute(
            """
            SELECT id, state FROM apify_actor_candidates
            WHERE id IN (?, ?)
            """,
            (str(active[0]["candidate_id"]), str(active[1]["candidate_id"])),
        ).fetchall()
    }
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="ambiguous-freshness-owner",
        password="safe-test-password",
        role="owner",
    )
    resilience = ApifyActorResilienceService(store)

    for round_index in range(2):
        check = resilience.create_freshness_check(
            route_id,
            trigger_kind="manual",
            actor_user_id=str(owner["id"]),
            cost_confirmed=True,
            expected_generation=int(ops.get_route(route_id)["generation"]),
            approved_max_total_charge_usd=float(
                resilience.freshness_plan(route_id)["max_total_charge_usd"]
            ),
        )
        resilience.begin_freshness_check(str(check["check_id"]))
        completed = resilience.complete_freshness_check(
            str(check["check_id"]),
            samples=[
                {
                    "candidate_id": str(slot["candidate_id"]),
                    "revision_id": str(slot["revision_id"]),
                    "successful": True,
                    "timely": True,
                    "semantic_outcome": "valid_nonempty",
                    "reason_code": "freshness_sample_valid",
                    "latest_published_at": "2026-08-11T00:00:00+00:00",
                    "latest_item_id": f"different-{index}",
                    "actual_cost_usd": 0.001 + round_index / 10000,
                    "cost_final": True,
                }
                for index, slot in enumerate(active)
            ],
        )
        assert [row["status"] for row in completed["results"]] == [
            "suspected_stale",
            "suspected_stale",
        ]
        assert [
            row["consecutive_stale_count"] for row in completed["results"]
        ] == [1, 1]
        assert {row["reason_code"] for row in completed["results"]} == {
            "ambiguous_peer_mismatch"
        }

    states_after = {
        str(row["id"]): str(row["state"])
        for row in store.connect().execute(
            """
            SELECT id, state FROM apify_actor_candidates
            WHERE id IN (?, ?)
            """,
            (str(active[0]["candidate_id"]), str(active[1]["candidate_id"])),
        ).fetchall()
    }
    assert states_after == states_before


def test_evaluation_memory_retry_and_diagnostics_are_bounded_and_safe(tmp_path) -> None:
    store = _store(tmp_path)
    ops = ApifyActorOpsService(store)
    route = _route(ops)
    active = next(slot for slot in ops.get_route(str(route["route_id"]))["slots"])
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="diagnostic-owner",
        password="safe-test-password",
        role="owner",
    )
    resilience = ApifyActorResilienceService(store)
    fingerprint = hashlib.sha256(b"stable-evidence").hexdigest()
    evaluation = resilience.record_evaluation(
        route_id=str(route["route_id"]),
        candidate_id=str(active["candidate_id"]),
        revision_id=str(active["revision_id"]),
        evidence_fingerprint=fingerprint,
        policy_mode="compatibility",
        stage="canary",
        outcome="failed",
        reason_code="apify_actor_contract_mismatch",
        deterministic=True,
    )
    assert resilience.deterministic_failure(
        route_id=str(route["route_id"]),
        candidate_id=str(active["candidate_id"]),
        evidence_fingerprint=fingerprint,
        policy_mode="compatibility",
        stage="canary",
    ) is not None
    resilience.retry_evaluation_once(
        str(evaluation["evaluation_id"]),
        actor_user_id=str(owner["id"]),
    )
    assert resilience.deterministic_failure(
        route_id=str(route["route_id"]),
        candidate_id=str(active["candidate_id"]),
        evidence_fingerprint=fingerprint,
        policy_mode="compatibility",
        stage="canary",
    ) is None
    retry_events = resilience.list_events(
        route_id=str(route["route_id"]),
        phase="evaluation_retry",
    )["events"]
    assert retry_events[0]["reason_code"] == "manual_retry_once"
    with pytest.raises(ActorResilienceError) as repeated:
        resilience.retry_evaluation_once(
            str(evaluation["evaluation_id"]),
            actor_user_id=str(owner["id"]),
        )
    assert repeated.value.code == "evaluation_retry_unavailable"

    assert resilience.emit_event(
        route_id=str(route["route_id"]),
        candidate_id=str(active["candidate_id"]),
        actor_public_name="private-target-must-be-ignored",
        phase="canary",
        outcome="failed",
        reason_code="apify_actor_contract_mismatch",
        final_cost_usd=0.001,
        request_id="request-safe-id",
        job_id="job-safe-id",
    ) is True
    page = resilience.list_events(
        route_id=str(route["route_id"]),
        phase="canary",
        outcome="failed",
        limit=1,
    )
    assert len(page["events"]) == 1
    event = page["events"][0]
    assert event["actor_public_name"] == active["actor_public_name"]
    assert "private-target" not in str(page)
    assert not {
        "token",
        "target",
        "input",
        "body",
        "remote_run_id",
        "dataset_id",
        "raw_error",
    } & set(event)
    assert resilience.emit_event(
        route_id=str(route["route_id"]),
        actor_public_name="Public Store Actor",
        phase="discovery",
        outcome="succeeded",
        reason_code="candidate_found",
    ) is True
    discovery_event = resilience.list_events(
        route_id=str(route["route_id"]),
        phase="discovery",
        limit=1,
    )["events"][0]
    assert discovery_event["actor_public_name"] == "Public Store Actor"
    thirty_day_page = resilience.list_events(
        since=datetime.now(timezone.utc) - timedelta(days=30),
    )
    assert thirty_day_page["events"]
    with pytest.raises(ActorResilienceError) as too_old:
        resilience.list_events(
            since=datetime.now(timezone.utc) - timedelta(days=31),
        )
    assert too_old.value.code == "diagnostic_range_too_old"
    naive_now = datetime.now(timezone.utc).replace(tzinfo=None)
    naive_page = resilience.list_events(
        since=naive_now - timedelta(hours=1),
        until=naive_now + timedelta(minutes=1),
    )
    assert naive_page["events"]
