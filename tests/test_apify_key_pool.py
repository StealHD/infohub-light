from __future__ import annotations

import asyncio
import threading
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

from src.scrapers.apify_client import ApifyCredentialFailureKind
from src.services.apify_key_pool import (
    ApifyKeyBusyError,
    ApifyKeyDrainPendingError,
    ApifyKeyPoolBlockedError,
    ApifyKeyPoolConflictError,
    ApifyKeyPoolExhaustedError,
    ApifyKeyPoolService,
    apify_key_pool_enabled,
    apify_pool_generation,
)
from src.services.secret_store import SecretStore
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


FIXED_NOW = datetime(2026, 7, 23, 8, 0, tzinfo=timezone.utc)
TOKENS = {
    "APIFY_TOKEN_A": "apify-private-token-a",
    "APIFY_TOKEN_B": "apify-private-token-b",
    "APIFY_TOKEN_C": "apify-private-token-c",
}


def _create_apify_ref(
    store: ServiceStore,
    *,
    env_name: str,
) -> dict:
    return store.create_secret_ref(
        workspace_id=DEFAULT_WORKSPACE_ID,
        owner_user_id=None,
        name=env_name.removeprefix("APIFY_TOKEN_"),
        env_name=env_name,
        kind="provider",
        provider="apify",
    )


def _pool(
    tmp_path,
    *,
    count: int = 2,
    now: datetime = FIXED_NOW,
) -> tuple[ServiceStore, SecretStore, ApifyKeyPoolService, list[dict]]:
    store = ServiceStore(tmp_path)
    store.initialize()
    secrets = SecretStore(tmp_path)
    refs: list[dict] = []
    for env_name in list(TOKENS)[:count]:
        refs.append(_create_apify_ref(store, env_name=env_name))
        secrets.set(env_name, TOKENS[env_name])
    store.initialize()
    service = ApifyKeyPoolService(
        store,
        secret_store=secrets,
        now=lambda: now,
    )
    return store, secrets, service, refs


def test_schema_v8_seeds_referenced_apify_key_idempotently_without_token_values(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    secret_store = SecretStore(tmp_path)
    first = _create_apify_ref(store, env_name="APIFY_TOKEN_A")
    second = _create_apify_ref(store, env_name="APIFY_TOKEN_B")
    third = _create_apify_ref(store, env_name="APIFY_TOKEN_C")
    secret_store.set("APIFY_TOKEN_A", TOKENS["APIFY_TOKEN_A"])
    secret_store.set("APIFY_TOKEN_B", TOKENS["APIFY_TOKEN_B"])
    secret_store.set("APIFY_TOKEN_C", TOKENS["APIFY_TOKEN_C"])
    store.connect().executemany(
        "UPDATE secret_refs SET created_at = ? WHERE id = ?",
        (
            ("2026-01-01T00:00:00+00:00", first["id"]),
            ("2026-01-03T00:00:00+00:00", second["id"]),
            ("2026-01-02T00:00:00+00:00", third["id"]),
        ),
    )
    store.connect().commit()

    store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="A",
        config={"platform": "x"},
        secret_env="APIFY_TOKEN_A",
    )
    for index in range(2):
        store.create_source(
            workspace_id=DEFAULT_WORKSPACE_ID,
            scope="workspace",
            owner_user_id=None,
            source_type="apify_social",
            display_name=f"B{index}",
            config={"platform": "x"},
            secret_env="APIFY_TOKEN_B",
        )
    store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="C",
        config={"platform": "x"},
        secret_env="APIFY_TOKEN_C",
    )

    store.initialize()
    first_generation = apify_pool_generation(store, DEFAULT_WORKSPACE_ID)
    store.initialize()

    marker = store.connect().execute(
        "SELECT name FROM schema_migrations WHERE version = 8"
    ).fetchone()
    tables = {
        row["name"]
        for row in store.connect()
        .execute(
            """
            SELECT name FROM sqlite_master
            WHERE type = 'table' AND name LIKE 'apify_%'
            """
        )
        .fetchall()
    }
    public = ApifyKeyPoolService(store, secret_store=secret_store).public_state(
        DEFAULT_WORKSPACE_ID
    )

    assert marker["name"] == "apify_key_pool_v8"
    assert {
        "apify_actor_runs",
        "apify_key_pool_members",
        "apify_key_pool_state",
    } <= tables
    assert public["active_secret_id"] == second["id"]
    assert [member["secret_id"] for member in public["members"]] == [
        second["id"],
        first["id"],
        third["id"],
    ]
    assert public["generation"] == first_generation
    database_dump = "\n".join(store.connect().iterdump())
    assert TOKENS["APIFY_TOKEN_A"] not in database_dump
    assert TOKENS["APIFY_TOKEN_B"] not in database_dump
    assert TOKENS["APIFY_TOKEN_C"] not in database_dump


def test_pool_reads_key_values_only_from_secret_store(tmp_path, monkeypatch) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ref = _create_apify_ref(store, env_name="APIFY_ENV_ONLY")
    monkeypatch.setenv("APIFY_ENV_ONLY", "must-not-be-used-by-pool")
    store.initialize()
    service = ApifyKeyPoolService(store, secret_store=SecretStore(tmp_path))

    with pytest.raises(ApifyKeyPoolExhaustedError):
        service.acquire_credential()

    state = service.public_state(DEFAULT_WORKSPACE_ID)
    member = next(item for item in state["members"] if item["secret_id"] == ref["id"])
    assert state["status"] == "exhausted"
    assert member["status"] == "invalid"


def test_order_update_is_atomic_across_two_connections_and_preserves_active(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, secret_store, service, refs = _pool(tmp_path, count=3)
    second_store = ServiceStore(tmp_path, db_path=store.db_path)
    second_store.initialize()
    second_service = ApifyKeyPoolService(
        second_store,
        secret_store=secret_store,
        now=lambda: FIXED_NOW,
    )
    initial = service.public_state(DEFAULT_WORKSPACE_ID)
    active = initial["active_secret_id"]
    standbys = [
        member["secret_id"]
        for member in initial["members"]
        if member["secret_id"] != active
    ]
    barrier = threading.Barrier(2)

    def reorder(
        coordinator: ApifyKeyPoolService,
        order: list[str],
    ) -> str:
        barrier.wait(timeout=5)
        try:
            coordinator.reorder(
                DEFAULT_WORKSPACE_ID,
                expected_generation=initial["generation"],
                secret_ids=order,
            )
        except ApifyKeyPoolConflictError:
            return ApifyKeyPoolConflictError.code
        return "success"

    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(
            executor.map(
                lambda item: reorder(*item),
                [
                    (service, [active, standbys[0], standbys[1]]),
                    (second_service, [active, standbys[1], standbys[0]]),
                ],
            )
        )

    assert sorted(results) == [ApifyKeyPoolConflictError.code, "success"]
    final = service.public_state(DEFAULT_WORKSPACE_ID)
    assert final["generation"] == initial["generation"] + 1
    assert final["members"][0]["secret_id"] == active
    with pytest.raises(ApifyKeyBusyError):
        service.reorder(
            DEFAULT_WORKSPACE_ID,
            expected_generation=final["generation"],
            secret_ids=[standbys[0], active, standbys[1]],
        )
    assert {ref["id"] for ref in refs} == {
        member["secret_id"] for member in final["members"]
    }

    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "false")
    promoted = final["members"][1]["secret_id"]
    rollout_order = [
        promoted,
        *[
            member["secret_id"]
            for member in final["members"]
            if member["secret_id"] != promoted
        ],
    ]
    prepared = service.reorder(
        DEFAULT_WORKSPACE_ID,
        expected_generation=final["generation"],
        secret_ids=rollout_order,
    )
    assert prepared["active_secret_id"] == promoted
    assert prepared["members"][0]["status"] == "active"


def test_standby_reorder_does_not_invalidate_active_key_run(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    _store, _secret_store, service, _refs = _pool(tmp_path, count=3)
    initial = service.public_state(DEFAULT_WORKSPACE_ID)
    lease = service.acquire_credential()
    active = initial["active_secret_id"]
    standbys = [
        member["secret_id"]
        for member in initial["members"]
        if member["secret_id"] != active
    ]

    reordered = service.reorder(
        DEFAULT_WORKSPACE_ID,
        expected_generation=initial["generation"],
        secret_ids=[active, *reversed(standbys)],
    )

    assert reordered["generation"] == lease.pool_generation + 1
    service.assert_lease_startable(lease)
    service.register_run(lease, "remote-after-order", "dataset-after-order")
    service.mark_run_terminal(lease, "remote-after-order", "FAILED")
    assert (
        service.should_retry_after_terminal(
            lease,
            "remote-after-order",
            "FAILED",
        )
        is False
    )


def test_started_run_reconciliation_blocks_pool_and_preserves_terminal_dataset(
    tmp_path,
) -> None:
    _store, _secrets, service, _refs = _pool(tmp_path, count=1)
    lease = service.acquire_credential(logical_run_id="route-attempt")
    service.register_run(
        lease,
        "remote-run",
        "remote-dataset",
        "route-attempt",
    )
    service.mark_run_terminal(lease, "remote-run", "SUCCEEDED")

    service.block_run_reconciliation(
        lease,
        "apify_run_reconcile_required",
    )

    state = service.public_state(DEFAULT_WORKSPACE_ID)
    run = service.get_run(lease.reservation_id)
    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "apify_run_reconcile_required"
    assert run["status"] == "succeeded"
    assert run["dataset_id"] == "remote-dataset"
    with pytest.raises(ApifyKeyPoolBlockedError):
        service.acquire_credential(logical_run_id="must-not-repost")

    service.complete_run_reconciliation(lease)

    recovered = service.public_state(DEFAULT_WORKSPACE_ID)
    assert recovered["status"] == "ready"
    assert recovered["blocked_reason"] is None


def test_concurrent_reservations_share_generation_and_drain_blocks_new_runs(
    tmp_path,
) -> None:
    store, secret_store, service, _refs = _pool(tmp_path)
    second_store = ServiceStore(tmp_path, db_path=store.db_path)
    second_store.initialize()
    second_service = ApifyKeyPoolService(
        second_store,
        secret_store=secret_store,
        now=lambda: FIXED_NOW,
    )
    barrier = threading.Barrier(2)

    def acquire(coordinator: ApifyKeyPoolService):
        barrier.wait(timeout=5)
        return coordinator.acquire_credential()

    with ThreadPoolExecutor(max_workers=2) as executor:
        leases = list(executor.map(acquire, [service, second_service]))

    assert leases[0].secret_id == leases[1].secret_id
    assert leases[0].pool_generation == leases[1].pool_generation
    assert leases[0].reservation_id != leases[1].reservation_id
    assert all(lease.quota_check_required for lease in leases)
    assert TOKENS["APIFY_TOKEN_A"] not in repr(leases[0])

    service.release_reservation(leases[0], "apify_explicit_reject")
    service.begin_drain(
        leases[0].secret_id,
        target_status="depleted",
        reason="apify_credits_depleted",
    )
    with pytest.raises(ApifyKeyDrainPendingError) as pending:
        service.complete_drain_and_failover(DEFAULT_WORKSPACE_ID)
    assert pending.value.active_run_count == 1
    with pytest.raises(ApifyKeyDrainPendingError):
        second_service.acquire_credential()

    second_service.release_reservation(leases[1], "apify_explicit_reject")
    switched = service.complete_drain_and_failover(DEFAULT_WORKSPACE_ID)

    assert switched["status"] == "ready"
    assert switched["generation"] == leases[0].pool_generation + 1
    assert switched["active_secret_id"] != leases[0].secret_id


def test_async_failure_aborts_all_old_generation_runs_before_switch(tmp_path) -> None:
    _store, _secrets, service, _refs = _pool(tmp_path)
    first = service.acquire_credential(logical_run_id="job-a")
    second = service.acquire_credential(logical_run_id="job-b")
    service.register_run(first, "remote-a", "dataset-a")
    service.register_run(second, "remote-b", "dataset-b")
    aborted: list[tuple[str, str, int]] = []

    async def abort_run(lease, remote_run_id: str) -> str:
        aborted.append(
            (lease.secret_id, remote_run_id, lease.pool_generation)
        )
        assert TOKENS["APIFY_TOKEN_A"] not in repr(lease)
        return "ABORTED"

    asyncio.run(
        service.report_credential_failure(
            first,
            failure_kind=ApifyCredentialFailureKind.DEPLETED,
            status_code=402,
            error_type="platform-usage-limit-exceeded",
            abort_run=abort_run,
        )
    )

    public = service.public_state(DEFAULT_WORKSPACE_ID)
    assert {remote_id for _secret_id, remote_id, _generation in aborted} == {
        "remote-a",
        "remote-b",
    }
    assert len({generation for _secret_id, _remote_id, generation in aborted}) == 1
    assert public["status"] == "ready"
    assert public["active_secret_id"] != first.secret_id
    serialized = repr(public)
    assert "remote-a" not in serialized
    assert "dataset-a" not in serialized
    assert TOKENS["APIFY_TOKEN_A"] not in serialized


def test_aborted_peer_waits_for_generation_switch_before_retrying(tmp_path) -> None:
    _store, _secrets, service, _refs = _pool(tmp_path)
    lease = service.acquire_credential()
    service.register_run(lease, "remote-peer", "dataset-peer")
    service.begin_drain(
        lease.secret_id,
        target_status="depleted",
        reason="apify_credits_depleted",
    )
    service.mark_run_terminal(lease, "remote-peer", "ABORTED")

    assert (
        service.should_retry_after_terminal(lease, "remote-peer", "ABORTED")
        is None
    )

    service.complete_drain_and_failover(DEFAULT_WORKSPACE_ID)

    assert (
        service.should_retry_after_terminal(lease, "remote-peer", "ABORTED")
        is True
    )


def test_quota_freshness_depletion_exhaustion_and_verified_recovery_tail(
    tmp_path,
) -> None:
    _store, _secrets, service, _refs = _pool(tmp_path)
    first = service.acquire_credential()
    cycle_end = (FIXED_NOW + timedelta(days=1)).isoformat()
    service.record_quota_snapshot(
        first,
        remaining_included_credits_usd=0,
        cycle_end_at=cycle_end,
    )

    async def unexpected_abort(_lease, _remote_run_id: str) -> str:
        raise AssertionError("a rejected preflight did not create a remote Run")

    asyncio.run(
        service.report_credential_failure(
            first,
            failure_kind=ApifyCredentialFailureKind.DEPLETED,
            status_code=402,
            error_type="quota-preflight-depleted",
            abort_run=unexpected_abort,
        )
    )

    after_switch = service.public_state(DEFAULT_WORKSPACE_ID)
    second_id = after_switch["active_secret_id"]
    assert after_switch["members"][-1]["secret_id"] == first.secret_id
    assert after_switch["members"][-1]["status"] == "depleted"

    recovered = service.record_member_quota(
        workspace_id=DEFAULT_WORKSPACE_ID,
        secret_id=first.secret_id,
        remaining_included_credits_usd=10,
        checked_at=(FIXED_NOW + timedelta(days=1, seconds=1)).isoformat(),
        cycle_end_at=(FIXED_NOW + timedelta(days=31)).isoformat(),
    )
    assert recovered["active_secret_id"] == second_id
    assert recovered["members"][-1]["secret_id"] == first.secret_id
    assert recovered["members"][-1]["status"] == "standby"

    service.record_member_quota(
        workspace_id=DEFAULT_WORKSPACE_ID,
        secret_id=first.secret_id,
        remaining_included_credits_usd=0,
        cycle_end_at=cycle_end,
    )
    service.record_member_quota(
        workspace_id=DEFAULT_WORKSPACE_ID,
        secret_id=second_id,
        remaining_included_credits_usd=0,
        cycle_end_at=cycle_end,
    )
    with pytest.raises(ApifyKeyPoolExhaustedError):
        service.acquire_credential()
    assert service.schedule_gate(DEFAULT_WORKSPACE_ID) == {
        "blocked": True,
        "code": "apify_key_pool_exhausted",
        "retry_at": cycle_end,
    }
    assert service.recover_due_members(
        DEFAULT_WORKSPACE_ID,
        now=FIXED_NOW,
    ) == []
    assert set(
        service.recover_due_members(
            DEFAULT_WORKSPACE_ID,
            now=FIXED_NOW + timedelta(days=2),
        )
    ) == {first.secret_id, second_id}

    restored = service.record_member_quota(
        workspace_id=DEFAULT_WORKSPACE_ID,
        secret_id=first.secret_id,
        remaining_included_credits_usd=10,
        checked_at=(FIXED_NOW + timedelta(days=2)).isoformat(),
        cycle_end_at=(FIXED_NOW + timedelta(days=32)).isoformat(),
    )
    assert restored["status"] == "ready"
    assert restored["active_secret_id"] == first.secret_id


def test_exhausted_retry_time_ignores_invalid_key_cycle_metadata(tmp_path) -> None:
    _store, _secrets, service, _refs = _pool(tmp_path)
    depleted = service.acquire_credential()
    depleted_cycle_end = (FIXED_NOW + timedelta(days=2)).isoformat()
    service.record_quota_snapshot(
        depleted,
        remaining_included_credits_usd=0,
        cycle_end_at=depleted_cycle_end,
    )

    async def unexpected_abort(_lease, _remote_run_id: str) -> str:
        raise AssertionError("no remote Run was created")

    asyncio.run(
        service.report_credential_failure(
            depleted,
            failure_kind=ApifyCredentialFailureKind.DEPLETED,
            status_code=402,
            error_type="quota-preflight-depleted",
            abort_run=unexpected_abort,
        )
    )
    invalid = service.acquire_credential()
    service.record_quota_snapshot(
        invalid,
        remaining_included_credits_usd=5,
        cycle_end_at=(FIXED_NOW + timedelta(days=1)).isoformat(),
    )
    service.release_reservation(invalid)
    asyncio.run(
        service.report_credential_failure(
            invalid,
            failure_kind=ApifyCredentialFailureKind.INVALID,
            status_code=401,
            error_type="invalid-token",
            abort_run=unexpected_abort,
        )
    )

    assert service.schedule_gate(DEFAULT_WORKSPACE_ID)["retry_at"] == depleted_cycle_end


def test_fresh_quota_snapshot_skips_recheck_but_never_persists_token(tmp_path) -> None:
    store, _secrets, service, _refs = _pool(tmp_path)
    first = service.acquire_credential()
    service.record_quota_snapshot(
        first,
        remaining_included_credits_usd=4.5,
        monthly_included_credits_usd=10,
        monthly_usage_usd=5.5,
        max_monthly_usage_usd=20,
        remaining_hard_limit_usd=14.5,
    )
    service.release_reservation(first)

    second = service.acquire_credential()

    assert second.quota_check_required is False
    database_dump = "\n".join(store.connect().iterdump())
    assert second.token not in database_dump


def test_unknown_start_outcome_blocks_pool_and_is_not_publicly_exposed(tmp_path) -> None:
    _store, _secrets, service, _refs = _pool(tmp_path)
    lease = service.acquire_credential()

    service.report_start_outcome_unknown(
        lease,
        error_code="apify_start_outcome_unknown",
    )

    public = service.public_state(DEFAULT_WORKSPACE_ID)
    assert public["status"] == "blocked"
    assert public["blocked_reason"] == "apify_start_outcome_unknown"
    assert public["members"][0]["active_run_count"] == 1
    assert lease.reservation_id not in repr(public)
    with pytest.raises(ApifyKeyPoolBlockedError):
        service.acquire_credential()


def test_restart_blocks_unregistered_reservation_without_reading_secret(
    tmp_path,
) -> None:
    store, secret_store, service, _refs = _pool(tmp_path)
    lease = service.acquire_credential()
    for env_name in TOKENS:
        if secret_store.status(env_name)["is_set"]:
            secret_store.delete(env_name)

    restarted = ApifyKeyPoolService(
        store,
        secret_store=secret_store,
        now=lambda: FIXED_NOW + timedelta(minutes=1),
    )

    assert restarted.block_unregistered_reservations(DEFAULT_WORKSPACE_ID) == 1
    assert restarted.block_unregistered_reservations(DEFAULT_WORKSPACE_ID) == 0
    public = restarted.public_state(DEFAULT_WORKSPACE_ID)
    assert public["status"] == "blocked"
    assert public["blocked_reason"] == "apify_start_outcome_unknown"
    assert lease.reservation_id not in repr(public)


def test_secret_lifecycle_guards_active_key_and_removes_nonbusy_member(tmp_path) -> None:
    store, _secrets, service, refs = _pool(tmp_path)
    public = service.public_state(DEFAULT_WORKSPACE_ID)
    active_id = public["active_secret_id"]
    standby_id = next(ref["id"] for ref in refs if ref["id"] != active_id)

    with pytest.raises(ApifyKeyBusyError):
        service.ensure_secret_mutable(active_id)
    assert service.ensure_secret_mutable(standby_id)["busy"] is False
    old_version = store.get_secret_ref(standby_id)["version"]
    store.touch_secret_ref(standby_id)
    assert store.get_secret_ref(standby_id)["version"] == old_version + 1

    after_removal = service.remove_secret(standby_id)
    assert [member["secret_id"] for member in after_removal["members"]] == [active_id]
    assert store.delete_secret_ref(standby_id) is True
    assert service.remove_secret("secret_missing") is None


def test_quota_refresh_candidates_include_every_incomplete_or_stale_usable_key(
    tmp_path,
) -> None:
    store, _secrets, service, refs = _pool(tmp_path)
    store.connect().execute(
        """
        UPDATE apify_key_pool_members
        SET remaining_included_credits_usd = 5,
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
        SET remaining_included_credits_usd = NULL,
            last_checked_at = ?, updated_at = ?
        WHERE workspace_id = ? AND secret_id = ?
        """,
        (
            (FIXED_NOW + timedelta(seconds=61)).isoformat(),
            FIXED_NOW.isoformat(),
            DEFAULT_WORKSPACE_ID,
            refs[1]["id"],
        ),
    )
    store.connect().commit()

    assert service.quota_refresh_candidates(
        DEFAULT_WORKSPACE_ID,
        now=FIXED_NOW,
    ) == [refs[1]["id"]]

    store.connect().execute(
        """
        UPDATE apify_key_pool_members
        SET last_checked_at = ?
        WHERE workspace_id = ? AND secret_id = ?
        """,
        (
            (FIXED_NOW - timedelta(seconds=61)).isoformat(),
            DEFAULT_WORKSPACE_ID,
            refs[0]["id"],
        ),
    )
    store.connect().commit()
    assert set(
        service.quota_refresh_candidates(
            DEFAULT_WORKSPACE_ID,
            now=FIXED_NOW,
        )
    ) == {refs[0]["id"], refs[1]["id"]}


def test_pool_rollout_flag_defaults_false(monkeypatch) -> None:
    monkeypatch.delenv("HORIZON_APIFY_KEY_POOL_ENABLED", raising=False)
    assert apify_key_pool_enabled() is False
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    assert apify_key_pool_enabled() is True
