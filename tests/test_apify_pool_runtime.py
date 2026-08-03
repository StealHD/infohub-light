from __future__ import annotations

import asyncio
from datetime import datetime, timedelta, timezone

import httpx

from src.services.apify_key_pool import ApifyKeyPoolService
from src.services.apify_pool_runtime import reconcile_apify_pool
from src.services.secret_store import SecretStore
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


class _Quota:
    def __init__(self) -> None:
        self.calls: list[str] = []

    async def fetch(self, *, secret_id: str, token: str):
        del token
        self.calls.append(secret_id)
        now = datetime.now(timezone.utc)
        return {
            "remaining_included_credits_usd": 5.0,
            "checked_at": now.isoformat(),
            "cycle_start_at": (now - timedelta(days=1)).isoformat(),
            "cycle_end_at": (now + timedelta(days=29)).isoformat(),
            "monthly_included_credits_usd": 10.0,
            "monthly_usage_usd": 5.0,
            "max_monthly_usage_usd": 20.0,
            "remaining_hard_limit_usd": 15.0,
        }


def _pool(tmp_path) -> tuple[ServiceStore, SecretStore, ApifyKeyPoolService, list[dict]]:
    store = ServiceStore(tmp_path)
    store.initialize()
    secret_store = SecretStore(tmp_path)
    refs = []
    for suffix in ("A", "B"):
        env_name = f"APIFY_TOKEN_{suffix}"
        refs.append(
            store.create_secret_ref(
                workspace_id=DEFAULT_WORKSPACE_ID,
                owner_user_id=None,
                name=f"Apify {suffix}",
                env_name=env_name,
                kind="provider",
                provider="apify",
            )
        )
        secret_store.set(env_name, f"private-token-{suffix.lower()}")
    store.initialize()
    return (
        store,
        secret_store,
        ApifyKeyPoolService(store, secret_store=secret_store),
        refs,
    )


def test_restart_reconcile_preserves_registered_run_for_get_only_resume(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    _store, _secret_store, coordinator, refs = _pool(tmp_path)
    lease = coordinator.acquire_credential(logical_run_id="source-fetch-a")
    coordinator.register_run(lease, "remote-old", "dataset-old")
    requests: list[tuple[str, str, str]] = []
    quota = _Quota()

    state = asyncio.run(
        reconcile_apify_pool(
            coordinator,
            quota_service=quota,
            http_transport=httpx.MockTransport(
                lambda request: (_ for _ in ()).throw(
                    AssertionError(f"unexpected request: {request}")
                )
            ),
        )
    )

    assert state["status"] == "ready"
    assert state["active_secret_id"] == lease.secret_id
    assert state["generation"] == lease.pool_generation
    assert coordinator.get_run(lease.reservation_id)["status"] == "running"
    assert requests == []
    assert set(quota.calls) == {str(ref["id"]) for ref in refs}
    assert "remote-old" not in repr(state)
    assert "dataset-old" not in repr(state)


def test_existing_drain_still_aborts_registered_run_before_failover(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    _store, _secret_store, coordinator, _refs = _pool(tmp_path)
    lease = coordinator.acquire_credential(logical_run_id="source-fetch-a")
    coordinator.register_run(lease, "remote-old", "dataset-old")
    coordinator.begin_drain(
        lease.secret_id,
        target_status="standby",
        reason="operator_drain",
    )
    requests: list[tuple[str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append((request.method, request.url.path))
        if request.method == "POST":
            return httpx.Response(
                200,
                json={"data": {"id": "remote-old", "status": "ABORTING"}},
            )
        return httpx.Response(
            200,
            json={"data": {"id": "remote-old", "status": "ABORTED"}},
        )

    state = asyncio.run(
        reconcile_apify_pool(
            coordinator,
            quota_service=_Quota(),
            http_transport=httpx.MockTransport(handler),
        )
    )

    assert state["status"] == "ready"
    assert state["active_secret_id"] != lease.secret_id
    assert state["generation"] == lease.pool_generation + 1
    assert coordinator.get_run(lease.reservation_id)["status"] == "aborted"
    assert requests == [
        ("POST", "/v2/actor-runs/remote-old/abort"),
        ("GET", "/v2/actor-runs/remote-old"),
        ("GET", "/v2/actor-runs/remote-old"),
    ]


def test_restart_with_unregistered_reservation_blocks_without_needing_token(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    _store, secret_store, coordinator, _refs = _pool(tmp_path)
    lease = coordinator.acquire_credential(logical_run_id="unknown-start")
    secret_store.delete(lease.env_name)

    state = asyncio.run(reconcile_apify_pool(coordinator))

    assert state["status"] == "blocked"
    assert state["blocked_reason"] == "apify_restart_start_outcome_unknown"
    run = coordinator.get_run(lease.reservation_id)
    assert run["status"] == "start_outcome_unknown"
    assert run["last_error_code"] == "apify_restart_start_outcome_unknown"
    assert lease.reservation_id not in repr(state)


def test_unknown_start_with_authoritative_empty_window_recovers_without_post(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, _secret_store, coordinator, _refs = _pool(tmp_path)
    lease = coordinator.acquire_credential(logical_run_id="canary-attempt")
    coordinator.report_start_outcome_unknown(
        lease,
        error_code="apify_start_http_outcome_unknown",
    )
    old_dt = datetime.now(timezone.utc) - timedelta(minutes=2)
    old = old_dt.isoformat()
    store.connect().execute(
        "UPDATE apify_actor_runs SET created_at = ?, updated_at = ? WHERE id = ?",
        (old, old, lease.reservation_id),
    )
    store.connect().commit()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        assert request.method == "GET"
        assert request.url.path == "/v2/actor-runs"
        assert request.url.params["limit"] == "1000"
        assert request.url.params["startedAfter"] == (
            (old_dt - timedelta(seconds=5))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        assert request.url.params["startedBefore"] == (
            (old_dt + timedelta(seconds=30))
            .isoformat(timespec="milliseconds")
            .replace("+00:00", "Z")
        )
        return httpx.Response(
            200,
            json={"data": {"items": [], "total": 0, "count": 0}},
        )

    state = asyncio.run(
        reconcile_apify_pool(
            coordinator,
            quota_service=_Quota(),
            http_transport=httpx.MockTransport(handler),
        )
    )

    assert state["status"] == "ready"
    assert len(requests) == 1
    run = coordinator.get_run(lease.reservation_id)
    assert run["status"] == "start_rejected"
    assert run["last_error_code"] == "apify_start_not_created"
    assert run["charge_actual_usd"] == 0
    assert run["charge_final"] == 1


def test_unknown_start_with_any_account_run_remains_blocked(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, _secret_store, coordinator, _refs = _pool(tmp_path)
    lease = coordinator.acquire_credential(logical_run_id="canary-attempt")
    coordinator.report_start_outcome_unknown(lease)
    old = (datetime.now(timezone.utc) - timedelta(minutes=2)).isoformat()
    store.connect().execute(
        "UPDATE apify_actor_runs SET created_at = ?, updated_at = ? WHERE id = ?",
        (old, old, lease.reservation_id),
    )
    store.connect().commit()

    state = asyncio.run(
        reconcile_apify_pool(
            coordinator,
            quota_service=_Quota(),
            http_transport=httpx.MockTransport(
                lambda _request: httpx.Response(
                    200,
                    json={
                        "data": {
                            "items": [{"id": "redacted-remote-run"}],
                            "total": 1,
                            "count": 1,
                        }
                    },
                )
            ),
        )
    )

    assert state["status"] == "blocked"
    assert coordinator.get_run(lease.reservation_id)["status"] == "start_outcome_unknown"


def test_terminal_cost_is_refreshed_after_settlement_window(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    store, _secret_store, coordinator, _refs = _pool(tmp_path)
    lease = coordinator.acquire_credential(logical_run_id="settled-attempt")
    coordinator.register_run(lease, "remote-settlement", "dataset-settlement")
    coordinator.record_run_accounting(
        lease,
        actual_cost_usd=0.00005,
        cost_final=True,
    )
    coordinator.mark_run_terminal(lease, "remote-settlement", "SUCCEEDED")

    state = asyncio.run(
        reconcile_apify_pool(
            coordinator,
            quota_service=_Quota(),
            http_transport=httpx.MockTransport(
                lambda request: httpx.Response(
                    200,
                    json={
                        "data": {
                            "id": "remote-settlement",
                            "status": "SUCCEEDED",
                            "usageTotalUsd": 0.00505,
                        }
                    },
                )
            ),
        )
    )

    assert state["status"] == "ready"
    run = coordinator.get_run(lease.reservation_id)
    assert run["charge_actual_usd"] == 0.00505
    assert run["charge_final"] == 1
