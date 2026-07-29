from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import pytest

from src.services.apify_actor_route import (
    ApifyActorInvocationResult,
    ApifyActorRouteBlockedError,
    ApifyActorRouteError,
    ApifyActorRouteService,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


FIXED_NOW = datetime(2030, 1, 1, 8, 0, tzinfo=timezone.utc)


class _SemanticFailure(RuntimeError):
    def __init__(
        self,
        code: str,
        *,
        failure_scope: str,
        actual_charge_usd: float | None = None,
        cost_final: bool = False,
    ) -> None:
        self.code = code
        self.failure_scope = failure_scope
        self.actual_charge_usd = actual_charge_usd
        self.cost_final = cost_final
        super().__init__(code)


class _KeyFailure(RuntimeError):
    code = "apify_key_pool_exhausted"
    status_code = 402


class _StartUnknown(RuntimeError):
    code = "apify_start_outcome_unknown"


class _StartedRunReconcile(RuntimeError):
    code = "apify_run_reconcile_required"
    status_code = 402


def _source(store: ServiceStore, name: str) -> str:
    return store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name=name,
        config={"platform": "x", "kind": "profile", "target": name},
    )


def _job(store: ServiceStore, source_id: str, job_id: str) -> str:
    user_id = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username=f"owner-{job_id}",
        password="safe-test-password",
        role="admin",
    )["id"]
    now_iso = FIXED_NOW.isoformat()
    store.connect().execute(
        """
        INSERT INTO fetch_jobs (
            id, workspace_id, user_id, source_id, job_type, status,
            payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'source_fetch', 'running', '{}', ?, ?)
        """,
        (
            job_id,
            DEFAULT_WORKSPACE_ID,
            user_id,
            source_id,
            now_iso,
            now_iso,
        ),
    )
    store.connect().commit()
    return job_id


def _route(tmp_path, *, transitions=None):
    store = ServiceStore(tmp_path)
    store.initialize()
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET retry_at = ?
        WHERE workspace_id = ? AND route_key = 'x/profile'
          AND adapter_key = 'xquik'
        """,
        ((FIXED_NOW + timedelta(days=1)).isoformat(), DEFAULT_WORKSPACE_ID),
    )
    store.connect().commit()
    service = ApifyActorRouteService(
        store,
        now=lambda: FIXED_NOW,
        transition_hook=(
            (lambda event_type, payload: transitions.append((event_type, payload)))
            if transitions is not None
            else None
        ),
    )
    return store, service


def _candidate(store: ServiceStore, adapter_key: str):
    return store.connect().execute(
        """
        SELECT * FROM apify_actor_candidates
        WHERE workspace_id = ? AND route_key = 'x/profile'
          AND adapter_key = ?
        """,
        (DEFAULT_WORKSPACE_ID, adapter_key),
    ).fetchone()


def _make_dami_probationary(store: ServiceStore) -> None:
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'probationary', probation_started_at = ?,
            last_error_code = NULL
        WHERE workspace_id = ? AND route_key = 'x/profile'
          AND adapter_key = 'dami'
        """,
        (FIXED_NOW.isoformat(), DEFAULT_WORKSPACE_ID),
    )
    store.connect().commit()


def test_public_state_has_bounded_cost_and_candidate_projection(tmp_path):
    _store, service = _route(tmp_path)

    state = service.public_state()

    assert state["route"] == "x/profile"
    assert state["status"] == "degraded"
    assert state["quota"]["currency"] == "USD"
    assert state["quota"]["total_remaining_usd"] is None
    assert state["limits"] == {
        "per_run_usd": 0.02,
        "per_job_usd": 0.06,
        "failed_spend_6h_usd": 0.08,
    }
    assert [
        (candidate["display_name"], candidate["listed_price_usd_per_1000"])
        for candidate in state["candidates"]
    ] == [
        ("ScrapeBadger", 0.15),
        ("Dami", 0.30),
        ("Xquik", 15.0),
    ]
    xquik = next(
        candidate
        for candidate in state["candidates"]
        if candidate["display_name"] == "Xquik"
    )
    assert xquik["paid_plan_listed_price_usd_per_1000"] == 0.15
    assert all("remote_run_id" not in candidate for candidate in state["candidates"])
    dami = next(
        candidate
        for candidate in state["candidates"]
        if candidate["display_name"] == "Dami"
    )
    assert dami["state"] == "disabled"
    assert dami["can_enable"] is False
    assert dami["can_canary"] is True


def test_trusted_quota_reserves_one_dollar_and_blocks_new_charge(tmp_path):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    secret = store.create_secret_ref(
        workspace_id=DEFAULT_WORKSPACE_ID,
        owner_user_id=None,
        name="Apify",
        env_name="APIFY_TEST_TOKEN",
        kind="provider",
        provider="apify",
    )
    store.initialize()
    store.connect().execute(
        """
        UPDATE apify_key_pool_members
        SET status = 'active', remaining_included_credits_usd = 0.50,
            monthly_included_credits_usd = 5.00,
            last_checked_at = ?, cycle_end_at = ?, updated_at = ?
        WHERE workspace_id = ? AND secret_id = ?
        """,
        (
            FIXED_NOW.isoformat(),
            (FIXED_NOW + timedelta(days=30)).isoformat(),
            FIXED_NOW.isoformat(),
            DEFAULT_WORKSPACE_ID,
            secret["id"],
        ),
    )
    store.connect().execute(
        """
        UPDATE apify_key_pool_state
        SET status = 'ready', active_secret_id = ?, updated_at = ?
        WHERE workspace_id = ?
        """,
        (secret["id"], FIXED_NOW.isoformat(), DEFAULT_WORKSPACE_ID),
    )
    store.connect().commit()

    calls = []

    async def should_not_run(_lease):
        calls.append(True)
        return ApifyActorInvocationResult(
            value=[],
            semantic_outcome="valid_empty",
        )

    with pytest.raises(ApifyActorRouteBlockedError) as exc_info:
        asyncio.run(
            service.execute_x_profile(
                source_id,
                should_not_run,
            )
        )

    state = service.public_state()
    assert getattr(exc_info.value, "code", None) == "apify_actor_budget_blocked"
    assert calls == []
    assert state["quota"]["total_remaining_usd"] == 0.50
    assert state["quota"]["x_allocatable_usd"] == 0.0
    assert state["status"] == "budget_blocked"
    assert state["last_switch_reason"] == "quota_exhausted"


def test_two_previously_healthy_targets_open_actor_and_switch_serially(tmp_path):
    transitions = []
    store, service = _route(tmp_path, transitions=transitions)
    _make_dami_probationary(store)
    source_a = _source(store, "account-a")
    source_b = _source(store, "account-b")

    async def healthy(lease):
        assert lease.adapter_key == "scrape_badger"
        return ApifyActorInvocationResult(
            value=["post"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.001,
            cost_final=True,
        )

    assert asyncio.run(service.execute_x_profile(source_a, healthy)) == ["post"]
    assert asyncio.run(service.execute_x_profile(source_b, healthy)) == ["post"]

    calls = []

    async def fail_primary(lease):
        calls.append(lease.adapter_key)
        if lease.adapter_key == "scrape_badger":
            raise _SemanticFailure(
                "apify_actor_placeholder",
                failure_scope="actor",
                actual_charge_usd=0.002,
                cost_final=True,
            )
        return ApifyActorInvocationResult(
            value=["backup"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.001,
            cost_final=True,
        )

    assert asyncio.run(service.execute_x_profile(source_a, fail_primary)) == ["backup"]
    assert _candidate(store, "scrape_badger")["state"] == "closed"
    assert asyncio.run(service.execute_x_profile(source_b, fail_primary)) == ["backup"]

    state = service.public_state()
    assert calls == ["scrape_badger", "dami", "scrape_badger", "dami"]
    assert _candidate(store, "scrape_badger")["state"] == "open"
    assert state["active_candidate_id"] == _candidate(store, "dami")["id"]
    assert state["status"] == "degraded"
    assert any(event == "actor_switched" for event, _payload in transitions)


def test_raw_empty_opens_only_after_two_distinct_previously_healthy_targets(
    tmp_path,
):
    store, service = _route(tmp_path)
    _make_dami_probationary(store)
    source_a = _source(store, "account-a")
    source_b = _source(store, "account-b")

    async def healthy(_lease):
        return ApifyActorInvocationResult(
            value=["post"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.0,
            cost_final=True,
        )

    asyncio.run(service.execute_x_profile(source_a, healthy))
    asyncio.run(service.execute_x_profile(source_b, healthy))
    calls = []

    async def raw_empty(lease):
        calls.append(lease.adapter_key)
        if lease.adapter_key == "scrape_badger":
            return ApifyActorInvocationResult(
                value=[],
                semantic_outcome="suspicious_empty",
                actual_cost_usd=0.001,
                cost_final=True,
            )
        return ApifyActorInvocationResult(
            value=["backup"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.001,
            cost_final=True,
        )

    assert asyncio.run(service.execute_x_profile(source_a, raw_empty)) == []
    assert _candidate(store, "scrape_badger")["state"] == "closed"
    # Repeating the same account still cannot create Actor-wide evidence.
    assert asyncio.run(service.execute_x_profile(source_a, raw_empty)) == []
    assert _candidate(store, "scrape_badger")["state"] == "closed"
    assert asyncio.run(service.execute_x_profile(source_b, raw_empty)) == ["backup"]

    assert calls == [
        "scrape_badger",
        "scrape_badger",
        "scrape_badger",
        "dami",
    ]
    assert _candidate(store, "scrape_badger")["state"] == "open"


def test_target_failure_pauses_only_subscription_after_second_failure(tmp_path):
    store, service = _route(tmp_path)
    source_id = _source(store, "private-account")
    initial_candidate = dict(_candidate(store, "scrape_badger"))

    async def unavailable(_lease):
        raise _SemanticFailure(
            "apify_actor_target_unavailable",
            failure_scope="target",
            actual_charge_usd=0.001,
            cost_final=True,
        )

    for _index in range(2):
        with pytest.raises(_SemanticFailure):
            asyncio.run(service.execute_x_profile(source_id, unavailable))

    candidate = _candidate(store, "scrape_badger")
    gate = service.schedule_gate(source_id)
    assert candidate["state"] == "closed"
    assert candidate["failure_count"] == initial_candidate["failure_count"]
    assert gate.allowed is False
    assert gate.error_code == "apify_actor_target_paused"
    assert gate.retry_at == FIXED_NOW + timedelta(hours=6)


def test_key_failure_does_not_mark_actor_or_try_another_candidate(tmp_path):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    calls = []

    async def key_failure(lease):
        calls.append(lease.adapter_key)
        raise _KeyFailure()

    with pytest.raises(_KeyFailure):
        asyncio.run(service.execute_x_profile(source_id, key_failure))

    assert calls == ["scrape_badger"]
    assert _candidate(store, "scrape_badger")["failure_count"] == 0
    attempt = store.connect().execute(
        "SELECT status FROM apify_actor_attempts ORDER BY created_at DESC LIMIT 1"
    ).fetchone()
    assert attempt["status"] == "cancelled"


def test_proven_no_post_key_cancel_does_not_consume_actor_job_budget(tmp_path):
    store, service = _route(tmp_path)
    source_id = _source(store, "no-post-budget-account")
    job_id = _job(store, source_id, "no-post-budget-job")
    calls: list[str] = []

    async def key_failure(lease):
        calls.append(lease.adapter_key)
        raise _KeyFailure()

    with pytest.raises(_KeyFailure):
        asyncio.run(
            service.execute_x_profile(
                source_id,
                key_failure,
                job_id=job_id,
            )
        )

    async def healthy(lease):
        calls.append(lease.adapter_key)
        return ApifyActorInvocationResult(
            value=["post"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.0,
            cost_final=True,
        )

    assert asyncio.run(
        service.execute_x_profile(
            source_id,
            healthy,
            job_id=job_id,
        )
    ) == ["post"]
    rows = store.connect().execute(
        """
        SELECT attempt_group_id, attempt_index, status
        FROM apify_actor_attempts
        WHERE job_id = ?
        ORDER BY created_at, id
        """,
        (job_id,),
    ).fetchall()
    progress = service._attempt_group_progress(
        str(rows[0]["attempt_group_id"]),
        source_id=source_id,
        job_id=job_id,
    )
    assert calls == ["scrape_badger", "scrape_badger"]
    assert sorted(str(row["status"]) for row in rows) == [
        "cancelled",
        "succeeded",
    ]
    assert [int(row["attempt_index"]) for row in rows] == [1, 1]
    assert progress["charged_attempts"] == 1
    assert progress["reserved_spend_usd"] == pytest.approx(0.02)


def test_start_outcome_unknown_blocks_route_without_fallback(tmp_path):
    transitions = []
    store, service = _route(tmp_path, transitions=transitions)
    source_id = _source(store, "account")
    calls = []

    async def unknown(lease):
        calls.append(lease.adapter_key)
        raise _StartUnknown()

    with pytest.raises(_StartUnknown):
        asyncio.run(service.execute_x_profile(source_id, unknown))

    state = service.public_state()
    assert calls == ["scrape_badger"]
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "apify_start_outcome_unknown"
    assert any(event == "start_outcome_unknown" for event, _payload in transitions)


def test_started_run_reconcile_blocks_actor_route_without_fallback(tmp_path):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    calls = []

    async def pending(lease):
        calls.append(lease.adapter_key)
        raise _StartedRunReconcile()

    with pytest.raises(_StartedRunReconcile):
        asyncio.run(service.execute_x_profile(source_id, pending))

    assert calls == ["scrape_badger"]
    state = service.public_state()
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "apify_run_reconcile_required"


def test_failed_charge_fuse_uses_conservative_reservation(tmp_path):
    transitions = []
    store, service = _route(tmp_path, transitions=transitions)
    source_id = _source(store, "account")
    candidate_id = _candidate(store, "scrape_badger")["id"]

    for _index in range(4):
        lease = service.reserve_canary(
            candidate_id,
            source_id,
            expected_generation=service.route_generation(),
        )
        service.mark_running(lease)
        service.record_failure(
            lease,
            failure_scope="actor",
            semantic_outcome="apify_actor_error_record",
            error_code="apify_actor_error_record",
            actual_cost_usd=None,
            cost_final=False,
        )

    state = service.public_state()
    assert state["status"] == "budget_blocked"
    assert service.schedule_gate(source_id).allowed is False
    assert any(event == "budget_blocked" for event, _payload in transitions)


def test_half_open_requires_two_real_post_successes_without_reclaiming_primary(
    tmp_path,
):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    active_id = service.public_state()["active_candidate_id"]
    xquik_id = _candidate(store, "xquik")["id"]
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'half_open', retry_at = ?, probe_claimed_at = NULL
        WHERE id = ?
        """,
        (FIXED_NOW.isoformat(), xquik_id),
    )
    store.connect().commit()

    seen = []

    async def healthy(lease):
        seen.append(lease.adapter_key)
        return ApifyActorInvocationResult(
            value=["post"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.0,
            cost_final=True,
        )

    asyncio.run(service.execute_x_profile(source_id, healthy))
    assert _candidate(store, "xquik")["state"] == "half_open"
    # The first real-post recovery proof holds the half-open probe for an hour.
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET probe_claimed_at = ?
        WHERE id = ?
        """,
        ((FIXED_NOW - timedelta(hours=1)).isoformat(), xquik_id),
    )
    store.connect().commit()
    asyncio.run(service.execute_x_profile(source_id, healthy))

    assert seen == ["xquik", "xquik"]
    assert _candidate(store, "xquik")["state"] == "closed"
    assert service.public_state()["active_candidate_id"] == active_id
    assert service.public_state()["status"] == "degraded"


def test_half_open_valid_empty_resets_recovery_and_holds_probe(tmp_path):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    xquik_id = _candidate(store, "xquik")["id"]
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'half_open', retry_at = ?, recovery_successes = 1,
            probe_claimed_at = NULL
        WHERE id = ?
        """,
        (FIXED_NOW.isoformat(), xquik_id),
    )
    store.connect().commit()

    async def empty(_lease):
        return ApifyActorInvocationResult(
            value=[],
            semantic_outcome="valid_empty",
            actual_cost_usd=0.0,
            cost_final=True,
        )

    asyncio.run(service.execute_x_profile(source_id, empty))
    xquik = _candidate(store, "xquik")
    assert xquik["state"] == "half_open"
    assert xquik["recovery_successes"] == 0
    assert xquik["probe_claimed_at"] == FIXED_NOW.isoformat()

    seen = []

    async def primary(lease):
        seen.append(lease.adapter_key)
        return ApifyActorInvocationResult(
            value=[],
            semantic_outcome="valid_empty",
            actual_cost_usd=0.0,
            cost_final=True,
        )

    asyncio.run(service.execute_x_profile(source_id, primary))
    assert seen == ["scrape_badger"]


def test_paid_canary_runs_full_attempt_lifecycle_without_fallback(tmp_path):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    dami_id = _candidate(store, "dami")["id"]
    generation_before = service.route_generation()
    seen = []

    async def canary(lease):
        seen.append((lease.adapter_key, lease.canary))
        return ApifyActorInvocationResult(
            value=["post"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.003,
            cost_final=True,
        )

    result = asyncio.run(
        service.execute_x_profile(
            source_id,
            canary,
            candidate_id=dami_id,
            expected_generation=service.route_generation(),
            canary=True,
        )
    )
    attempt = store.connect().execute(
        "SELECT status, actual_cost_usd, cost_final FROM apify_actor_attempts"
    ).fetchone()

    assert result == ["post"]
    assert result._apify_actor_route_generation == service.route_generation()
    assert service.route_generation() == generation_before + 1
    assert seen == [("dami", True)]
    assert _candidate(store, "dami")["state"] == "probationary"
    assert _candidate(store, "dami")["probation_started_at"] == FIXED_NOW.isoformat()
    assert dict(attempt) == {
        "status": "succeeded",
        "actual_cost_usd": 0.003,
        "cost_final": 1,
    }


def test_dami_requires_real_post_canaries_from_two_enabled_profiles(tmp_path):
    store, service = _route(tmp_path)
    first_source_id = _source(store, "first-account")
    second_source_id = _source(store, "second-account")
    dami_id = _candidate(store, "dami")["id"]

    async def real_post(_lease):
        return ApifyActorInvocationResult(
            value=["post"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.001,
            cost_final=True,
        )

    asyncio.run(
        service.execute_x_profile(
            first_source_id,
            real_post,
            candidate_id=dami_id,
            expected_generation=service.route_generation(),
            canary=True,
        )
    )
    assert _candidate(store, "dami")["state"] == "disabled"
    assert _candidate(store, "dami")["last_error_code"] == "canary_required"

    asyncio.run(
        service.execute_x_profile(
            second_source_id,
            real_post,
            candidate_id=dami_id,
            expected_generation=service.route_generation(),
            canary=True,
        )
    )
    assert _candidate(store, "dami")["state"] == "probationary"


def test_dami_empty_canary_stays_disabled_and_cannot_enter_normal_route(tmp_path):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    dami_id = _candidate(store, "dami")["id"]

    async def empty(_lease):
        return ApifyActorInvocationResult(
            value=[],
            semantic_outcome="valid_empty",
            actual_cost_usd=0.0,
            cost_final=True,
        )

    asyncio.run(
        service.execute_x_profile(
            source_id,
            empty,
            candidate_id=dami_id,
            expected_generation=service.route_generation(),
            canary=True,
        )
    )

    assert _candidate(store, "dami")["state"] == "disabled"
    assert service.public_state()["active_candidate_id"] == _candidate(
        store, "scrape_badger"
    )["id"]


def test_admin_reorder_promotes_first_healthy_candidate(tmp_path):
    store, service = _route(tmp_path)
    _make_dami_probationary(store)
    state = service.public_state()
    dami_id = _candidate(store, "dami")["id"]
    scrape_id = _candidate(store, "scrape_badger")["id"]
    xquik_id = _candidate(store, "xquik")["id"]

    reordered = service.reorder(
        [dami_id, scrape_id, xquik_id],
        expected_generation=state["generation"],
    )

    assert reordered["active_candidate_id"] == dami_id
    assert reordered["last_switch_reason"] == "admin_reorder"
    assert reordered["status"] == "degraded"


def test_admin_disable_keeps_route_degraded_while_backup_is_available(tmp_path):
    store, service = _route(tmp_path)
    _make_dami_probationary(store)
    scrape_id = _candidate(store, "scrape_badger")["id"]
    dami_id = _candidate(store, "dami")["id"]

    disabled = service.disable(
        scrape_id,
        expected_generation=service.route_generation(),
    )

    assert disabled["active_candidate_id"] == dami_id
    assert disabled["status"] == "degraded"


def test_due_open_candidate_becomes_one_clean_half_open_probe(tmp_path):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    xquik_id = _candidate(store, "xquik")["id"]
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'open', retry_at = ?, recovery_successes = 9,
            probe_claimed_at = ?
        WHERE id = ?
        """,
        (
            FIXED_NOW.isoformat(),
            (FIXED_NOW - timedelta(hours=2)).isoformat(),
            xquik_id,
        ),
    )
    store.connect().commit()

    assert service.schedule_gate(source_id).allowed is True
    candidate = _candidate(store, "xquik")
    assert candidate["state"] == "half_open"
    assert candidate["recovery_successes"] == 0
    assert candidate["probe_claimed_at"] is None


def test_actor_attempt_cost_aggregates_every_key_run_for_logical_attempt(tmp_path):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    lease = service.reserve_canary(
        _candidate(store, "scrape_badger")["id"],
        source_id,
        expected_generation=service.route_generation(),
    )
    service.mark_running(lease)
    now_iso = FIXED_NOW.isoformat()
    store.connect().executemany(
        """
        INSERT INTO apify_actor_runs (
            id, workspace_id, logical_run_id, secret_id, secret_version,
            pool_generation, remote_run_id, dataset_id, status,
            charge_reserved_usd, charge_actual_usd, charge_final,
            created_at, terminal_at, updated_at
        ) VALUES (?, ?, ?, ?, 1, 1, ?, ?, ?, 0.02, ?, ?, ?, ?, ?)
        """,
        (
            (
                "key-prestart",
                DEFAULT_WORKSPACE_ID,
                lease.attempt_id,
                "secret-a",
                None,
                None,
                "start_rejected",
                None,
                0,
                now_iso,
                now_iso,
                now_iso,
            ),
            (
                "key-succeeded",
                DEFAULT_WORKSPACE_ID,
                lease.attempt_id,
                "secret-b",
                "remote-run",
                "dataset",
                "succeeded",
                0.007,
                1,
                now_iso,
                now_iso,
                now_iso,
            ),
        ),
    )
    store.connect().commit()

    service.record_success(
        lease,
        semantic_outcome="valid_nonempty",
        actual_cost_usd=0.001,
        cost_final=True,
    )

    attempt = store.connect().execute(
        """
        SELECT actual_cost_usd, cost_final
        FROM apify_actor_attempts WHERE id = ?
        """,
        (lease.attempt_id,),
    ).fetchone()
    assert dict(attempt) == {"actual_cost_usd": 0.007, "cost_final": 1}


@pytest.mark.parametrize(
    "error_code",
    ["apify_actor_deleted", "apify_actor_build_unavailable"],
)
def test_missing_or_unbuildable_actor_opens_immediately_and_falls_back(
    tmp_path,
    error_code,
):
    store, service = _route(tmp_path)
    _make_dami_probationary(store)
    source_id = _source(store, "account")
    calls = []

    async def invoke(lease):
        calls.append(lease.adapter_key)
        if lease.adapter_key == "scrape_badger":
            raise _SemanticFailure(error_code, failure_scope="actor")
        return ApifyActorInvocationResult(
            value=["backup"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.0,
            cost_final=True,
        )

    assert asyncio.run(service.execute_x_profile(source_id, invoke)) == ["backup"]
    assert calls == ["scrape_badger", "dami"]
    assert _candidate(store, "scrape_badger")["state"] == "open"


def test_restart_reconcile_cancels_safe_reservation_and_blocks_unknown_start(
    tmp_path,
):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    candidate_id = _candidate(store, "scrape_badger")["id"]
    safe = service.reserve_canary(
        candidate_id,
        source_id,
        expected_generation=service.route_generation(),
    )
    unknown = service.reserve_canary(
        _candidate(store, "dami")["id"],
        source_id,
        expected_generation=service.route_generation(),
    )
    service.mark_running(unknown)
    now_iso = FIXED_NOW.isoformat()
    store.connect().execute(
        """
        INSERT INTO apify_actor_runs (
            id, workspace_id, logical_run_id, secret_id, secret_version,
            pool_generation, status, charge_reserved_usd,
            charge_final, created_at, updated_at
        ) VALUES (?, ?, ?, 'safe-secret-id', 1, 1,
            'start_outcome_unknown', 0.02, 0, ?, ?)
        """,
        (
            "apify-key-run-unknown",
            DEFAULT_WORKSPACE_ID,
            unknown.attempt_id,
            now_iso,
            now_iso,
        ),
    )
    store.connect().commit()

    result = service.reconcile_unfinished_attempts()
    rows = {
        row["id"]: dict(row)
        for row in store.connect().execute(
            """
            SELECT id, status, actual_cost_usd, cost_final
            FROM apify_actor_attempts
            WHERE id IN (?, ?)
            """,
            (safe.attempt_id, unknown.attempt_id),
        ).fetchall()
    }

    assert result == {
        "cancelled": 1,
        "blocked_attempts": 1,
        "route_blocked": True,
    }
    assert rows[safe.attempt_id]["status"] == "cancelled"
    assert rows[safe.attempt_id]["actual_cost_usd"] == 0.0
    assert rows[safe.attempt_id]["cost_final"] == 1
    assert rows[unknown.attempt_id]["status"] == "start_outcome_unknown"
    assert rows[unknown.attempt_id]["cost_final"] == 0
    assert service.public_state()["status"] == "blocked"
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM apify_actor_attempts
        WHERE status IN ('reserved', 'running')
        """
    ).fetchone()[0] == 0


def test_restart_reconcile_blocks_any_linked_remote_run_and_preserves_accounting(
    tmp_path,
):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    candidate_id = _candidate(store, "scrape_badger")["id"]
    lease = service.reserve_canary(
        candidate_id,
        source_id,
        expected_generation=service.route_generation(),
    )
    service.mark_running(lease)
    now_iso = FIXED_NOW.isoformat()
    store.connect().execute(
        """
        INSERT INTO apify_actor_runs (
            id, workspace_id, logical_run_id, secret_id, secret_version,
            pool_generation, remote_run_id, status,
            charge_reserved_usd, charge_actual_usd, charge_final,
            created_at, terminal_at, updated_at
        ) VALUES (?, ?, ?, 'safe-secret-id', 1, 1, 'remote-safe-id',
            'aborted', 0.02, 0.007, 1, ?, ?, ?)
        """,
        (
            "apify-key-run-aborted",
            DEFAULT_WORKSPACE_ID,
            lease.attempt_id,
            now_iso,
            now_iso,
            now_iso,
        ),
    )
    store.connect().commit()

    result = service.reconcile_unfinished_attempts()
    attempt = store.connect().execute(
        """
        SELECT status, actual_cost_usd, cost_final
        FROM apify_actor_attempts WHERE id = ?
        """,
        (lease.attempt_id,),
    ).fetchone()

    assert result["cancelled"] == 0
    assert result["blocked_attempts"] == 1
    assert dict(attempt) == {
        "status": "running",
        "actual_cost_usd": 0.007,
        "cost_final": 1,
    }
    assert service.public_state()["status"] == "blocked"
    assert store.connect().execute(
        """
        SELECT status FROM apify_key_pool_state
        WHERE workspace_id = ?
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()["status"] == "blocked"


def test_restart_succeeded_dataset_resumes_same_attempt_without_new_reservation(
    tmp_path,
):
    store, service = _route(tmp_path)
    source_id = _source(store, "account")
    user_id = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="resume-owner",
        password="safe-test-password",
        role="admin",
    )["id"]
    job_id = "resume-job"
    now_iso = FIXED_NOW.isoformat()
    store.connect().execute(
        """
        INSERT INTO fetch_jobs (
            id, workspace_id, user_id, source_id, job_type, status,
            payload_json, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'source_fetch', 'queued', '{}', ?, ?)
        """,
        (
            job_id,
            DEFAULT_WORKSPACE_ID,
            user_id,
            source_id,
            now_iso,
            now_iso,
        ),
    )
    lease = service.reserve_canary(
        _candidate(store, "scrape_badger")["id"],
        source_id,
        expected_generation=service.route_generation(),
        job_id=job_id,
    )
    service.mark_running(lease)
    store.connect().execute(
        """
        INSERT INTO apify_actor_runs (
            id, workspace_id, logical_run_id, secret_id, secret_version,
            pool_generation, remote_run_id, dataset_id, status,
            charge_reserved_usd, charge_actual_usd, charge_final,
            created_at, terminal_at, updated_at
        ) VALUES (
            'resume-key-run', ?, ?, 'resume-secret', 1, 1,
            'remote-run', 'dataset', 'succeeded',
            0.02, 0.005, 1, ?, ?, ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            lease.attempt_id,
            now_iso,
            now_iso,
            now_iso,
        ),
    )
    store.connect().commit()
    service.reconcile_unfinished_attempts()
    seen = []

    async def resume(resume_lease):
        seen.append(resume_lease.resume_run_id)
        return ApifyActorInvocationResult(
            value=["resumed"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.005,
            cost_final=True,
        )

    result = asyncio.run(
        service.execute_x_profile(
            source_id,
            resume,
            job_id=job_id,
            candidate_id=lease.candidate_id,
            expected_generation=service.route_generation(),
            canary=True,
        )
    )

    assert result == ["resumed"]
    assert seen == ["resume-key-run"]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_attempts"
    ).fetchone()[0] == 1
    assert service.public_state()["status"] == "degraded"


def test_same_job_retry_reuses_group_and_skips_failed_actor(tmp_path) -> None:
    store, service = _route(tmp_path)
    source_id = _source(store, "stable-job-account")
    job_id = _job(store, source_id, "stable-route-job")
    calls: list[str] = []

    async def fail_primary(lease):
        calls.append(lease.adapter_key)
        raise _SemanticFailure(
            "apify_actor_deleted",
            failure_scope="actor",
            actual_charge_usd=0.0,
            cost_final=True,
        )

    with pytest.raises(ApifyActorRouteError):
        asyncio.run(
            service.execute_x_profile(
                source_id,
                fail_primary,
                job_id=job_id,
            )
        )
    _make_dami_probationary(store)

    async def backup(lease):
        calls.append(lease.adapter_key)
        return ApifyActorInvocationResult(
            value=["backup"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.0,
            cost_final=True,
        )

    assert asyncio.run(
        service.execute_x_profile(source_id, backup, job_id=job_id)
    ) == ["backup"]
    rows = store.connect().execute(
        """
        SELECT attempt_group_id, attempt_index, candidate_id
        FROM apify_actor_attempts
        WHERE job_id = ?
        ORDER BY attempt_index
        """,
        (job_id,),
    ).fetchall()
    assert calls == ["scrape_badger", "dami"]
    assert len({str(row["attempt_group_id"]) for row in rows}) == 1
    assert [int(row["attempt_index"]) for row in rows] == [1, 2]
    assert len({str(row["candidate_id"]) for row in rows}) == 2


def test_same_job_never_exceeds_three_actor_reservations(tmp_path) -> None:
    store, service = _route(tmp_path)
    _make_dami_probationary(store)
    source_id = _source(store, "bounded-job-account")
    job_id = _job(store, source_id, "bounded-route-job")
    xquik = _candidate(store, "xquik")
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'closed', retry_at = NULL, last_error_code = NULL
        WHERE id = ?
        """,
        (xquik["id"],),
    )
    store.connect().commit()
    calls: list[str] = []

    async def fail(lease):
        calls.append(lease.adapter_key)
        raise _SemanticFailure(
            "apify_actor_deleted",
            failure_scope="actor",
            actual_charge_usd=0.0,
            cost_final=True,
        )

    with pytest.raises(ApifyActorRouteError):
        asyncio.run(service.execute_x_profile(source_id, fail, job_id=job_id))
    calls_after_first_run = list(calls)
    with pytest.raises(ApifyActorRouteError) as exc_info:
        asyncio.run(service.execute_x_profile(source_id, fail, job_id=job_id))

    rows = store.connect().execute(
        """
        SELECT attempt_group_id, reserved_usd
        FROM apify_actor_attempts
        WHERE job_id = ?
        """,
        (job_id,),
    ).fetchall()
    assert getattr(exc_info.value, "code", None) == (
        "apify_actor_job_budget_exhausted"
    )
    assert calls_after_first_run == ["scrape_badger", "dami", "xquik"]
    assert calls == calls_after_first_run
    assert len(rows) == 3
    assert len({str(row["attempt_group_id"]) for row in rows}) == 1
    assert sum(float(row["reserved_usd"]) for row in rows) == pytest.approx(0.06)


def test_terminal_success_dataset_replays_without_new_reservation(tmp_path) -> None:
    store, service = _route(tmp_path)
    source_id = _source(store, "terminal-replay-account")
    job_id = _job(store, source_id, "terminal-replay-job")
    seen: list[str | None] = []

    async def invoke(lease):
        seen.append(lease.resume_run_id)
        if lease.resume_run_id is None:
            now_iso = FIXED_NOW.isoformat()
            store.connect().execute(
                """
                INSERT INTO apify_actor_runs (
                    id, workspace_id, logical_run_id, secret_id,
                    secret_version, pool_generation, remote_run_id,
                    dataset_id, status, charge_reserved_usd,
                    charge_actual_usd, charge_final, created_at,
                    terminal_at, updated_at
                ) VALUES (
                    'terminal-ledger-run', ?, ?, 'terminal-secret',
                    1, 1, 'terminal-remote', 'terminal-dataset',
                    'succeeded', 0.02, 0.004, 1, ?, ?, ?
                )
                """,
                (
                    DEFAULT_WORKSPACE_ID,
                    lease.attempt_id,
                    now_iso,
                    now_iso,
                    now_iso,
                ),
            )
            store.connect().commit()
        return ApifyActorInvocationResult(
            value=["post"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.004,
            cost_final=True,
        )

    assert asyncio.run(
        service.execute_x_profile(source_id, invoke, job_id=job_id)
    ) == ["post"]
    assert asyncio.run(
        service.execute_x_profile(source_id, invoke, job_id=job_id)
    ) == ["post"]
    assert seen == [None, "terminal-ledger-run"]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_attempts WHERE job_id = ?",
        (job_id,),
    ).fetchone()[0] == 1


def test_terminal_success_without_dataset_fails_closed(tmp_path) -> None:
    store, service = _route(tmp_path)
    source_id = _source(store, "missing-dataset-account")
    job_id = _job(store, source_id, "missing-dataset-job")

    async def first(_lease):
        return ApifyActorInvocationResult(
            value=["post"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.0,
            cost_final=True,
        )

    asyncio.run(service.execute_x_profile(source_id, first, job_id=job_id))
    calls: list[bool] = []

    async def must_not_run(_lease):
        calls.append(True)
        return ApifyActorInvocationResult(
            value=[],
            semantic_outcome="valid_empty",
        )

    with pytest.raises(ApifyActorRouteError) as exc_info:
        asyncio.run(
            service.execute_x_profile(
                source_id,
                must_not_run,
                job_id=job_id,
            )
        )
    assert getattr(exc_info.value, "code", None) == (
        "apify_run_reconcile_required"
    )
    assert calls == []
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_attempts WHERE job_id = ?",
        (job_id,),
    ).fetchone()[0] == 1


def test_admin_disable_rejects_inflight_result_but_settles_cost(tmp_path) -> None:
    store, service = _route(tmp_path)
    source_id = _source(store, "generation-race-account")
    before_successes = int(_candidate(store, "scrape_badger")["success_count"])

    async def late_success(lease):
        service.disable(
            lease.candidate_id,
            expected_generation=service.route_generation(),
        )
        return ApifyActorInvocationResult(
            value=["stale"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.005,
            cost_final=True,
        )

    with pytest.raises(ApifyActorRouteError) as exc_info:
        asyncio.run(service.execute_x_profile(source_id, late_success))

    attempt = store.connect().execute(
        """
        SELECT status, semantic_outcome, actual_cost_usd, cost_final
        FROM apify_actor_attempts
        ORDER BY created_at DESC LIMIT 1
        """
    ).fetchone()
    assert getattr(exc_info.value, "code", None) == (
        "apify_actor_route_generation_conflict"
    )
    assert dict(attempt) == {
        "status": "cancelled",
        "semantic_outcome": "apify_actor_route_generation_conflict",
        "actual_cost_usd": 0.005,
        "cost_final": 1,
    }
    assert _candidate(store, "scrape_badger")["state"] == "disabled"
    assert int(_candidate(store, "scrape_badger")["success_count"]) == (
        before_successes
    )
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_target_health WHERE source_id = ?",
        (source_id,),
    ).fetchone()[0] == 0


def test_generation_conflict_cost_stays_inside_stable_job_limits(tmp_path) -> None:
    store, service = _route(tmp_path)
    _make_dami_probationary(store)
    source_id = _source(store, "generation-budget-account")
    job_id = _job(store, source_id, "generation-budget-job")
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'closed', retry_at = NULL, last_error_code = NULL
        WHERE workspace_id = ? AND route_key = 'x/profile'
          AND adapter_key = 'xquik'
        """,
        (DEFAULT_WORKSPACE_ID,),
    )
    store.connect().commit()
    calls: list[str] = []

    async def stale_paid_result(lease):
        calls.append(lease.adapter_key)
        candidate_ids = [
            str(row["id"])
            for row in store.connect().execute(
                """
                SELECT id
                FROM apify_actor_candidates
                WHERE workspace_id = ? AND route_key = 'x/profile'
                ORDER BY position, id
                """,
                (DEFAULT_WORKSPACE_ID,),
            ).fetchall()
        ]
        service.reorder(
            list(reversed(candidate_ids)),
            expected_generation=lease.route_generation,
        )
        return ApifyActorInvocationResult(
            value=["stale"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.005,
            cost_final=True,
        )

    for _index in range(3):
        with pytest.raises(ApifyActorRouteError) as exc_info:
            asyncio.run(
                service.execute_x_profile(
                    source_id,
                    stale_paid_result,
                    job_id=job_id,
                )
            )
        assert getattr(exc_info.value, "code", None) == (
            "apify_actor_route_generation_conflict"
        )

    with pytest.raises(ApifyActorRouteError) as exc_info:
        asyncio.run(
            service.execute_x_profile(
                source_id,
                stale_paid_result,
                job_id=job_id,
            )
        )

    rows = store.connect().execute(
        """
        SELECT status, semantic_outcome, reserved_usd, actual_cost_usd
        FROM apify_actor_attempts
        WHERE job_id = ?
        ORDER BY attempt_index, id
        """,
        (job_id,),
    ).fetchall()
    assert getattr(exc_info.value, "code", None) == (
        "apify_actor_job_budget_exhausted"
    )
    assert len(calls) == 3
    assert len(set(calls)) == 3
    assert len(rows) == 3
    assert {str(row["status"]) for row in rows} == {"cancelled"}
    assert {
        str(row["semantic_outcome"]) for row in rows
    } == {"apify_actor_route_generation_conflict"}
    assert sum(float(row["reserved_usd"]) for row in rows) == pytest.approx(0.06)
    assert sum(float(row["actual_cost_usd"]) for row in rows) == pytest.approx(
        0.015
    )
    assert service._failed_spend(
        store.connect(),
        FIXED_NOW,
    ) == pytest.approx(0.015)


def test_all_key_quota_snapshots_must_be_fresh_before_charge(tmp_path) -> None:
    store, _service = _route(tmp_path)
    source_id = _source(store, "quota-freshness-account")
    refs = [
        store.create_secret_ref(
            workspace_id=DEFAULT_WORKSPACE_ID,
            owner_user_id=None,
            name=f"Apify {suffix}",
            env_name=f"APIFY_QUOTA_{suffix}",
            kind="provider",
            provider="apify",
        )
        for suffix in ("A", "B")
    ]
    store.initialize()
    store.connect().execute(
        """
        UPDATE apify_key_pool_members
        SET status = 'active', remaining_included_credits_usd = 5,
            last_checked_at = ?, updated_at = ?
        WHERE workspace_id = ? AND secret_id = ?
        """,
        (
            FIXED_NOW.isoformat(),
            FIXED_NOW.isoformat(),
            DEFAULT_WORKSPACE_ID,
            refs[0]["id"],
        ),
    )
    store.connect().execute(
        """
        UPDATE apify_key_pool_members
        SET status = 'standby', remaining_included_credits_usd = 5,
            last_checked_at = ?, updated_at = ?
        WHERE workspace_id = ? AND secret_id = ?
        """,
        (
            (FIXED_NOW - timedelta(seconds=61)).isoformat(),
            FIXED_NOW.isoformat(),
            DEFAULT_WORKSPACE_ID,
            refs[1]["id"],
        ),
    )
    store.connect().commit()
    service = ApifyActorRouteService(
        store,
        now=lambda: FIXED_NOW,
        enforce_quota_admission=True,
    )
    calls: list[bool] = []

    async def fetch(_lease):
        calls.append(True)
        return ApifyActorInvocationResult(
            value=[],
            semantic_outcome="valid_empty",
            actual_cost_usd=0.0,
            cost_final=True,
        )

    assert service.public_state()["quota"]["x_allocatable_usd"] is None
    assert service.schedule_gate(source_id).error_code == (
        "apify_actor_quota_unknown"
    )
    with pytest.raises(ApifyActorRouteBlockedError) as exc_info:
        asyncio.run(service.execute_x_profile(source_id, fetch))
    assert getattr(exc_info.value, "code", None) == "apify_actor_quota_unknown"
    assert calls == []
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_attempts"
    ).fetchone()[0] == 0

    store.connect().execute(
        """
        UPDATE apify_key_pool_members
        SET last_checked_at = ?, updated_at = ?
        WHERE workspace_id = ? AND secret_id = ?
        """,
        (
            FIXED_NOW.isoformat(),
            FIXED_NOW.isoformat(),
            DEFAULT_WORKSPACE_ID,
            refs[1]["id"],
        ),
    )
    store.connect().commit()
    assert asyncio.run(service.execute_x_profile(source_id, fetch)) == []
    assert calls == [True]


def test_outstanding_reservations_consume_failed_spend_headroom(tmp_path) -> None:
    store, service = _route(tmp_path)
    candidate_id = _candidate(store, "scrape_badger")["id"]
    sources = [_source(store, f"concurrent-{index}") for index in range(5)]
    generation = service.route_generation()

    for source_id in sources[:4]:
        service._reserve_forced(
            candidate_id,
            source_id=source_id,
            job_id=None,
            expected_generation=generation,
        )

    with pytest.raises(ApifyActorRouteBlockedError) as exc_info:
        service._reserve_forced(
            candidate_id,
            source_id=sources[4],
            job_id=None,
            expected_generation=generation,
        )
    assert getattr(exc_info.value, "code", None) == "apify_actor_budget_blocked"
    row = store.connect().execute(
        """
        SELECT COUNT(*) AS count, SUM(reserved_usd) AS reserved
        FROM apify_actor_attempts
        WHERE status IN ('reserved', 'running')
        """
    ).fetchone()
    assert int(row["count"]) == 4
    assert float(row["reserved"]) == pytest.approx(0.08)
    assert service.public_state()["status"] != "budget_blocked"


def test_canary_and_natural_traffic_are_bidirectionally_exclusive(
    tmp_path,
) -> None:
    store, service = _route(tmp_path)
    _make_dami_probationary(store)
    primary_id = _candidate(store, "scrape_badger")["id"]
    source_id = _source(store, "canary-mutex-account")
    natural = service._reserve_next(
        source_id=source_id,
        job_id=None,
        attempt_group_id="natural-mutex-group",
        excluded_candidate_ids=set(),
    )
    with pytest.raises(ApifyActorRouteError) as exc_info:
        service.reserve_canary(
            primary_id,
            source_id,
            expected_generation=service.route_generation(),
        )
    assert getattr(exc_info.value, "code", None) == "apify_actor_canary_active"
    service.cancel_attempt(natural, error_code="test_complete")

    user_id = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="canary-mutex-owner",
        password="safe-test-password",
        role="admin",
    )["id"]
    now_iso = FIXED_NOW.isoformat()
    store.connect().execute(
        """
        INSERT INTO fetch_jobs (
            id, workspace_id, user_id, source_id, job_type, status,
            payload_json, created_at, updated_at
        ) VALUES (
            'queued-canary-mutex', ?, ?, ?, 'source_test', 'queued',
            json_object(
                'reason', 'apify_actor_canary',
                'apify_actor_candidate_id', ?
            ),
            ?, ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            user_id,
            source_id,
            primary_id,
            now_iso,
            now_iso,
        ),
    )
    store.connect().commit()
    seen: list[str] = []

    async def fetch(lease):
        seen.append(lease.adapter_key)
        return ApifyActorInvocationResult(
            value=["backup"],
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.0,
            cost_final=True,
        )

    assert asyncio.run(service.execute_x_profile(source_id, fetch)) == ["backup"]
    assert seen == ["dami"]


def test_zero_sample_probation_disables_once_after_48_hours(tmp_path) -> None:
    store, service = _route(tmp_path)
    source_id = _source(store, "probation-clock-account")
    dami_id = _candidate(store, "dami")["id"]
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'probationary', probation_started_at = ?,
            last_error_code = NULL
        WHERE id = ?
        """,
        ((FIXED_NOW - timedelta(hours=48)).isoformat(), dami_id),
    )
    store.connect().commit()
    generation_before = service.route_generation()

    assert service.schedule_gate(source_id).allowed is True
    assert _candidate(store, "dami")["state"] == "disabled"
    assert _candidate(store, "dami")["last_error_code"] == "probation_failed"
    assert service.route_generation() == generation_before + 1

    assert service.schedule_gate(source_id).allowed is True
    assert service.route_generation() == generation_before + 1
