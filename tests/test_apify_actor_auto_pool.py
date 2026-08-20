"""Regression coverage for retirement of the unpublished auto-pool workflow."""

from __future__ import annotations

import asyncio
import hashlib
import os
from datetime import datetime, timezone

import httpx
import pytest

from test_apify_actor_ops_api import _client, _login
from test_apify_actor_pool_staging_v18 import _revision, _route

from src.services.apify_actor_auto_pool_reconcile import (
    _read_once,
    reconcile_retirement,
)
from src.services.apify_actor_auto_pool_retirement import (
    RETIREMENT_CODE,
    apply_retirement,
    inspect_retirement,
)
from src.services.apify_actor_ops import ApifyActorOpsService
from src.services.job_queue import JobQueue
from src.services.secret_store import SecretStore
from src.storage.apify_actor_auto_pool_schema import (
    install_schema,
    mark_migrated,
    migration_marker_exists,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


NOW = datetime(2026, 8, 20, 8, 0, tzinfo=timezone.utc)


def _owner(store: ServiceStore) -> str:
    existing = store.get_user_by_username("owner", workspace_id=DEFAULT_WORKSPACE_ID)
    if existing:
        return str(existing["id"])
    return str(store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="owner",
        password="secret-password",
        role="owner",
    )["id"])


def _install_historical_schema(store: ServiceStore) -> None:
    connection = store.connect()
    install_schema(connection)
    mark_migrated(connection, commit=False)
    connection.commit()


def _insert_auto_run(
    store: ServiceStore,
    *,
    run_id: str,
    route_id: str,
    discovery_id: str,
    owner_id: str,
    status: str = "running",
) -> None:
    now = NOW.isoformat()
    store.connect().execute(
        """INSERT INTO apify_actor_auto_pool_runs (
               run_id, workspace_id, route_id, slot_name, goal, status,
               budget_cap_usd, total_spent_usd, last_discovery_run_id,
               last_canary_batch_id, error_code, created_by_user_id,
               created_at, updated_at
           ) VALUES (?, ?, ?, 'backup_2', 'add_slot', ?, 0.50, 0, ?, NULL,
                     NULL, ?, ?, ?)""",
        (run_id, DEFAULT_WORKSPACE_ID, route_id, status, discovery_id,
         owner_id, now, now),
    )
    store.connect().commit()


def _seed_free_auto_work(tmp_path):
    store = ServiceStore(tmp_path)
    store.initialize()
    _install_historical_schema(store)
    ops = ApifyActorOpsService(store, now=lambda: NOW)
    route = _route(store, "youtube/channel/items")
    owner_id = _owner(store)
    discovery = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="auto_pool",
        expected_generation=int(route["generation"]),
    )
    _insert_auto_run(
        store,
        run_id="auto-running",
        route_id=str(route["route_id"]),
        discovery_id=str(discovery["run_id"]),
        owner_id=owner_id,
    )
    JobQueue(store).create_job(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=owner_id,
        job_type="apify_actor_discovery",
        payload={"run_id": str(discovery["run_id"])},
        max_attempts=1,
    )
    return store, ops, route, discovery, owner_id


def _insert_batch(
    store: ServiceStore,
    *,
    route_id: str,
    discovery_id: str,
    owner_id: str,
    batch_id: str = "auto-batch",
    status: str = "failed",
    cost_final: int = 0,
) -> None:
    stamp = NOW.isoformat()
    store.connect().execute(
        """INSERT INTO apify_actor_canary_batches (
               batch_id, workspace_id, route_id, discovery_run_id,
               approval_key_hash, approved_generation, plan_hash,
               max_candidates, max_total_charge_usd, per_candidate_cap_usd,
               goal, pool_stage_id, status, planned_count, success_count,
               publisher_count, actual_cost_usd, cost_final, stop_reason,
               created_by_user_id, created_at, started_at, completed_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, 1, ?, 1, 0.05, 0.05, 'initial_pool',
                     NULL, ?, 0, 0, 0, 0, ?, 'retirement-test', ?, ?, ?, ?, ?)""",
        (
            batch_id, DEFAULT_WORKSPACE_ID, route_id, discovery_id,
            hashlib.sha256(f"approval:{batch_id}".encode()).hexdigest(),
            hashlib.sha256(f"plan:{batch_id}".encode()).hexdigest(),
            status, cost_final, owner_id, stamp, stamp, stamp, stamp,
        ),
    )
    store.connect().commit()


def test_unpublished_auto_pool_routes_are_not_registered(tmp_path, monkeypatch) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    route = _route(store, "youtube/channel/items")
    response = client.post(
        f"/api/admin/apify-routes/{route['route_id']}/auto-pool",
        json={"goal": "add_slot", "target_slot": "backup_2", "expected_generation": 1},
    )
    assert response.status_code == 404
    assert client.get("/api/admin/apify-auto-pool-runs/old-run").status_code == 404


def test_inspect_is_read_only_and_reports_only_auto_owned_work(tmp_path) -> None:
    store, _ops, _route_row, _discovery, _owner_id = _seed_free_auto_work(tmp_path)
    store.close()
    database = tmp_path / "service.db"
    before = (database.stat().st_size, database.stat().st_mtime_ns)
    sidecars = {suffix: os.path.exists(f"{database}{suffix}") for suffix in ("-wal", "-shm")}

    result = inspect_retirement(tmp_path, now=NOW)

    assert result["running_auto_run_count"] == 1
    assert result["active_auto_discovery_count"] == 1
    assert result["active_auto_job_count"] == 1
    assert result["requires_changes"] is True
    assert "active_worker_ids" not in result
    assert (database.stat().st_size, database.stat().st_mtime_ns) == before
    assert {suffix: os.path.exists(f"{database}{suffix}") for suffix in sidecars} == sidecars


def test_apply_is_backed_up_atomic_and_idempotent(tmp_path) -> None:
    store, _ops, route, discovery, owner_id = _seed_free_auto_work(tmp_path)
    _insert_auto_run(
        store,
        run_id="auto-succeeded-history",
        route_id=str(route["route_id"]),
        discovery_id=str(discovery["run_id"]),
        owner_id=owner_id,
        status="succeeded",
    )
    store.close()
    backups = tmp_path / "backups"

    with pytest.raises(RuntimeError, match="explicit API and Worker stopped"):
        apply_retirement(
            tmp_path,
            backup_dir=backups,
            confirm_api_stopped=False,
            confirm_worker_stopped=True,
            now=NOW,
        )
    applied = apply_retirement(
        tmp_path,
        backup_dir=backups,
        confirm_api_stopped=True,
        confirm_worker_stopped=True,
        now=NOW,
    )

    assert applied["applied"] is True
    assert applied["backup_mode"] == "0o600"
    assert (applied["jobs_cancelled"], applied["discoveries_failed"], applied["runs_cancelled"]) == (1, 1, 1)
    assert os.stat(applied["backup_path"]).st_mode & 0o777 == 0o600
    connection = ServiceStore(tmp_path).connect()
    assert migration_marker_exists(connection)
    rows = connection.execute(
        "SELECT run_id, status, error_code FROM apify_actor_auto_pool_runs ORDER BY run_id"
    ).fetchall()
    assert [(row["run_id"], row["status"], row["error_code"]) for row in rows] == [
        ("auto-running", "cancelled", RETIREMENT_CODE),
        ("auto-succeeded-history", "succeeded", None),
    ]
    connection.close()
    second = apply_retirement(
        tmp_path,
        backup_dir=backups,
        confirm_api_stopped=True,
        confirm_worker_stopped=True,
        now=NOW,
    )
    assert second == {"applied": False, "already_retired": True, "backup_path": None}
    assert len(list(backups.glob("*.db"))) == 1


def test_apply_fails_closed_for_heartbeat_cost_and_unknown_start(tmp_path) -> None:
    store, _ops, route, discovery, owner_id = _seed_free_auto_work(tmp_path)
    store.upsert_worker_heartbeat("actor-worker", "stopping", now=NOW)
    store.close()
    with pytest.raises(RuntimeError, match="heartbeat safety window"):
        apply_retirement(
            tmp_path, backup_dir=tmp_path / "heartbeat-backups",
            confirm_api_stopped=True, confirm_worker_stopped=True, now=NOW,
        )
    assert not (tmp_path / "heartbeat-backups").exists()

    reopened = ServiceStore(tmp_path)
    reopened.connect().execute(
        "UPDATE worker_heartbeats SET heartbeat_at = ?",
        ("2000-01-01T00:00:00+00:00",),
    )
    reopened.connect().commit()
    _insert_batch(
        reopened,
        route_id=str(route["route_id"]),
        discovery_id=str(discovery["run_id"]),
        owner_id=owner_id,
        status="failed",
        cost_final=0,
    )
    reopened.close()
    with pytest.raises(RuntimeError, match="costs are not final"):
        apply_retirement(
            tmp_path, backup_dir=tmp_path / "cost-backups",
            confirm_api_stopped=True, confirm_worker_stopped=True, now=NOW,
        )
    connection = ServiceStore(tmp_path).connect()
    connection.execute(
        """UPDATE apify_actor_canary_batches
           SET status = 'blocked_unknown_start', cost_final = 1
           WHERE batch_id = 'auto-batch'"""
    )
    connection.commit()
    connection.close()
    with pytest.raises(RuntimeError, match="unknown Actor start"):
        apply_retirement(
            tmp_path, backup_dir=tmp_path / "unknown-backups",
            confirm_api_stopped=True, confirm_worker_stopped=True, now=NOW,
        )


def test_apply_blocks_and_never_changes_unrelated_acquisition_run(tmp_path) -> None:
    store, _ops, _route_row, _discovery, _owner_id = _seed_free_auto_work(tmp_path)
    stamp = NOW.isoformat()
    store.connect().execute(
        """INSERT INTO apify_actor_runs (
               id, workspace_id, logical_run_id, purpose, secret_id,
               secret_version, pool_generation, remote_run_id, dataset_id,
               status, created_at, started_at, updated_at,
               charge_reserved_usd, charge_actual_usd, charge_final
           ) VALUES ('acquisition-local', ?, NULL, 'acquisition', 'acquisition-key',
                     1, 1, 'acquisition-remote', 'acquisition-dataset', 'running',
                     ?, ?, ?, 0.02, NULL, 0)""",
        (DEFAULT_WORKSPACE_ID, stamp, stamp, stamp),
    )
    store.connect().commit()
    store.close()

    summary = inspect_retirement(tmp_path, now=NOW)
    assert summary["unrelated_nonterminal_actor_run_count"] == 1
    with pytest.raises(RuntimeError, match="nonterminal Actor Runs"):
        apply_retirement(
            tmp_path, backup_dir=tmp_path / "acquisition-backups",
            confirm_api_stopped=True, confirm_worker_stopped=True, now=NOW,
        )
    connection = ServiceStore(tmp_path).connect()
    row = connection.execute(
        "SELECT purpose, status, remote_run_id FROM apify_actor_runs WHERE id = 'acquisition-local'"
    ).fetchone()
    assert tuple(row) == ("acquisition", "running", "acquisition-remote")
    connection.close()


def test_reconcile_requires_stopped_worker_before_secret_or_network(tmp_path) -> None:
    store, _ops, _route_row, _discovery, _owner_id = _seed_free_auto_work(tmp_path)
    store.upsert_worker_heartbeat("reconcile-worker", "idle", now=NOW)
    store.close()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(500)

    transport = httpx.MockTransport(handler)
    with pytest.raises(RuntimeError, match="explicit Worker stopped"):
        reconcile_retirement(
            tmp_path,
            confirm_worker_stopped=False,
            http_transport=transport,
            now=NOW,
        )
    with pytest.raises(RuntimeError, match="heartbeat safety window"):
        reconcile_retirement(
            tmp_path,
            confirm_worker_stopped=True,
            http_transport=transport,
            now=NOW,
        )
    assert requests == []


def _seed_reconcilable_failed_run(tmp_path) -> None:
    store, ops, route, discovery, owner_id = _seed_free_auto_work(tmp_path)
    revision_id = _revision(
        ops,
        str(route["route_id"]),
        actor_id="publisher-reconcile/youtube-reconcile",
        publisher="publisher-reconcile",
        build_number="99.0.1",
        host="youtube.com",
        discovery_run_id=str(discovery["run_id"]),
    )
    candidate = store.connect().execute(
        "SELECT candidate_id FROM apify_actor_adapter_revisions WHERE revision_id = ?",
        (revision_id,),
    ).fetchone()
    _insert_batch(
        store, route_id=str(route["route_id"]), discovery_id=str(discovery["run_id"]),
        owner_id=owner_id, status="failed", cost_final=0,
    )
    secret = store.create_secret_ref(
        workspace_id=DEFAULT_WORKSPACE_ID, owner_user_id=owner_id,
        name="retirement original key", env_name="RETIREMENT_ORIGINAL_KEY",
        kind="apify", provider="apify",
    )
    SecretStore(tmp_path).set("RETIREMENT_ORIGINAL_KEY", "original-secret-token")
    stamp = NOW.isoformat()
    connection = store.connect()
    connection.execute(
        """INSERT INTO apify_actor_attempts (
               id, workspace_id, route_key, route_generation, candidate_id,
               attempt_group_id, attempt_index, status, semantic_outcome,
               reserved_usd, actual_cost_usd, cost_final, adapter_revision_id,
               build_id, build_number, manifest_hash, target_fingerprint,
               created_at, terminal_at, updated_at
           ) VALUES ('auto-attempt', ?, ?, 1, ?, 'auto-group', 1,
                     'actor_failed', 'apify_run_status_unavailable', 0.05,
                     NULL, 0, ?, 'build', '99.0.1', ?, ?, ?, ?, ?)""",
        (
            DEFAULT_WORKSPACE_ID, str(route["route_key"]), str(candidate["candidate_id"]),
            revision_id, hashlib.sha256(b"manifest").hexdigest(),
            hashlib.sha256(b"target").hexdigest(), stamp, stamp, stamp,
        ),
    )
    connection.execute(
        """INSERT INTO apify_actor_validations (
               validation_id, workspace_id, route_id, revision_id, attempt_id,
               discovery_run_id, kind, approved_max_cost_usd, target_fingerprint,
               status, semantic_outcome, cost_usd, cost_final,
               validation_sample_items, created_at, completed_at
           ) VALUES ('auto-validation', ?, ?, ?, 'auto-attempt', ?,
                     'route_reference', 0.05, ?, 'failed',
                     'apify_run_status_unavailable', NULL, 0, 1, ?, ?)""",
        (
            DEFAULT_WORKSPACE_ID, str(route["route_id"]), revision_id,
            str(discovery["run_id"]), hashlib.sha256(b"target").hexdigest(), stamp, stamp,
        ),
    )
    connection.execute(
        """INSERT INTO apify_actor_canary_batch_items (
               workspace_id, batch_id, ordinal, revision_id, validation_id,
               status, semantic_outcome, authorized_cap_usd, actual_cost_usd,
               cost_final, completed_at, updated_at
           ) VALUES (?, 'auto-batch', 1, ?, 'auto-validation', 'failed',
                     'apify_run_status_unavailable', 0.05, NULL, 0, ?, ?)""",
        (DEFAULT_WORKSPACE_ID, revision_id, stamp, stamp),
    )
    connection.execute(
        """INSERT INTO apify_actor_runs (
               id, workspace_id, logical_run_id, purpose, secret_id,
               secret_version, pool_generation, remote_run_id, dataset_id,
               status, created_at, started_at, updated_at,
               charge_reserved_usd, charge_actual_usd, charge_final
           ) VALUES ('auto-durable', ?, 'auto-attempt', 'validation', ?, 1, 1,
                     'known-remote', 'known-dataset', 'running', ?, ?, ?, 0.05, NULL, 0)""",
        (DEFAULT_WORKSPACE_ID, str(secret["id"]), stamp, stamp, stamp),
    )
    connection.commit()
    store.close()


def test_reconcile_uses_original_key_one_get(tmp_path) -> None:
    _seed_reconcilable_failed_run(tmp_path)
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(
            200,
            json={"data": {"id": "known-remote", "status": "FAILED", "usageTotalUsd": 0.02}},
        )

    result = reconcile_retirement(
        tmp_path,
        confirm_worker_stopped=True,
        http_transport=httpx.MockTransport(handler),
        now=NOW,
    )

    assert result == {
        "checked": 1, "reconciled": 1, "unresolved": 0,
        "finalized_batches": 0,
    }
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/v2/actor-runs/known-remote")
    ]
    assert requests[0].headers["Authorization"] == "Bearer original-secret-token"
    connection = ServiceStore(tmp_path).connect()
    row = connection.execute(
        "SELECT status, charge_actual_usd, charge_final FROM apify_actor_runs WHERE id = 'auto-durable'"
    ).fetchone()
    assert tuple(row) == ("failed", 0.02, 1)
    connection.close()


def test_reconcile_finishes_local_unknown_barrier_after_durable_run_was_final(
    tmp_path,
) -> None:
    _seed_reconcilable_failed_run(tmp_path)
    connection = ServiceStore(tmp_path).connect()
    connection.execute(
        "UPDATE apify_actor_attempts SET status = 'start_outcome_unknown' WHERE id = 'auto-attempt'"
    )
    connection.execute(
        "UPDATE apify_actor_route_profiles SET status = 'blocked_unknown_start' WHERE route_key = 'youtube/channel/items'"
    )
    connection.execute(
        """UPDATE apify_actor_routes SET status = 'blocked',
                  blocked_reason = 'start_outcome_unknown'
           WHERE route_key = 'youtube/channel/items'"""
    )
    connection.execute(
        """UPDATE apify_actor_runs SET status = 'failed',
                  charge_actual_usd = 0.02, charge_final = 1
           WHERE id = 'auto-durable'"""
    )
    connection.commit()
    connection.close()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        return httpx.Response(200, json={
            "data": {"id": "known-remote", "status": "FAILED", "usageTotalUsd": 0.02}
        })

    result = reconcile_retirement(
        tmp_path, confirm_worker_stopped=True,
        http_transport=httpx.MockTransport(handler), now=NOW,
    )

    assert result["reconciled"] == 1 and result["unresolved"] == 0
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/v2/actor-runs/known-remote")
    ]
    connection = ServiceStore(tmp_path).connect()
    attempt = connection.execute(
        "SELECT status, actual_cost_usd, cost_final FROM apify_actor_attempts WHERE id = 'auto-attempt'"
    ).fetchone()
    profile = connection.execute(
        "SELECT status FROM apify_actor_route_profiles WHERE route_key = 'youtube/channel/items'"
    ).fetchone()
    route = connection.execute(
        "SELECT status, blocked_reason FROM apify_actor_routes WHERE route_key = 'youtube/channel/items'"
    ).fetchone()
    assert tuple(attempt) == ("cancelled", 0.02, 1)
    assert profile["status"] == "ready"
    assert tuple(route) == ("degraded", None)
    connection.close()


def test_reconcile_repairs_final_local_item_and_terminalizes_batch(tmp_path) -> None:
    _seed_reconcilable_failed_run(tmp_path)
    connection = ServiceStore(tmp_path).connect()
    connection.execute(
        """UPDATE apify_actor_validations
           SET semantic_outcome = 'apify_actor_contract_mismatch',
               cost_usd = 0.02, cost_final = 1
           WHERE validation_id = 'auto-validation'"""
    )
    connection.execute(
        """UPDATE apify_actor_attempts
           SET semantic_outcome = 'apify_actor_contract_mismatch',
               actual_cost_usd = 0.02, cost_final = 1
           WHERE id = 'auto-attempt'"""
    )
    connection.execute(
        """UPDATE apify_actor_runs
           SET status = 'succeeded', charge_actual_usd = 0.02, charge_final = 1
           WHERE id = 'auto-durable'"""
    )
    connection.execute(
        "UPDATE apify_actor_canary_batches SET status = 'running' WHERE batch_id = 'auto-batch'"
    )
    connection.commit()
    connection.close()
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if "/actor-runs/" in request.url.path:
            return httpx.Response(200, json={
                "data": {"id": "known-remote", "status": "SUCCEEDED", "usageTotalUsd": 0.02}
            })
        return httpx.Response(200, json=[])

    result = reconcile_retirement(
        tmp_path,
        confirm_worker_stopped=True,
        http_transport=httpx.MockTransport(handler),
        now=NOW,
    )

    assert result == {
        "checked": 1, "reconciled": 1, "unresolved": 0,
        "finalized_batches": 1,
    }
    assert [request.method for request in requests] == ["GET"]
    connection = ServiceStore(tmp_path).connect()
    item = connection.execute(
        "SELECT actual_cost_usd, cost_final FROM apify_actor_canary_batch_items WHERE validation_id = 'auto-validation'"
    ).fetchone()
    batch = connection.execute(
        "SELECT status, actual_cost_usd, cost_final FROM apify_actor_canary_batches WHERE batch_id = 'auto-batch'"
    ).fetchone()
    assert tuple(item) == (0.02, 1)
    assert tuple(batch) == ("partial", 0.02, 1)
    connection.close()


def test_single_read_fetches_exact_dataset_without_post_or_retry() -> None:
    requests: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        requests.append(request)
        if request.url.path.endswith("/actor-runs/exact-run"):
            return httpx.Response(200, json={
                "data": {"id": "exact-run", "status": "SUCCEEDED", "usageTotalUsd": 0.01}
            })
        return httpx.Response(200, json=[{"id": "one"}])

    async def execute():
        async with httpx.AsyncClient(transport=httpx.MockTransport(handler)) as client:
            return await _read_once(
                client, token="exact-original-token", remote_run_id="exact-run",
                dataset_id="exact-dataset", item_limit=2, base_url="https://api.apify.com/v2",
            )

    observed = asyncio.run(execute())
    assert observed.status == "SUCCEEDED" and observed.actual_cost_usd == 0.01
    assert [(request.method, request.url.path) for request in requests] == [
        ("GET", "/v2/actor-runs/exact-run"),
        ("GET", "/v2/datasets/exact-dataset/items"),
    ]
    assert all(request.headers["Authorization"] == "Bearer exact-original-token" for request in requests)
