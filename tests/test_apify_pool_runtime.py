from __future__ import annotations

import asyncio

import httpx

from src.services.apify_key_pool import ApifyKeyPoolService
from src.services.apify_pool_runtime import reconcile_apify_pool
from src.services.secret_store import SecretStore
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


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


def test_restart_reconcile_aborts_registered_run_before_promoting_standby(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    _store, _secret_store, coordinator, _refs = _pool(tmp_path)
    lease = coordinator.acquire_credential(logical_run_id="source-fetch-a")
    coordinator.register_run(lease, "remote-old", "dataset-old")
    requests: list[tuple[str, str, str]] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(
            (
                request.method,
                request.url.path,
                request.headers.get("Authorization", ""),
            )
        )
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
            http_transport=httpx.MockTransport(handler),
        )
    )

    assert state["status"] == "ready"
    assert state["active_secret_id"] != lease.secret_id
    assert state["generation"] == lease.pool_generation + 1
    assert coordinator.get_run(lease.reservation_id)["status"] == "aborted"
    assert [(method, path) for method, path, _auth in requests] == [
        ("POST", "/v2/actor-runs/remote-old/abort"),
        ("GET", "/v2/actor-runs/remote-old"),
    ]
    assert {
        authorization for _method, _path, authorization in requests
    } == {f"Bearer {lease.token}"}
    assert "remote-old" not in repr(state)
    assert "dataset-old" not in repr(state)


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
