"""Regression coverage for restart-safe Actor Canary state projection."""

from __future__ import annotations

import hashlib
from datetime import datetime, timezone

from src.services.apify_actor_ops import (
    PAID_CANARY_CONFIRMATION,
    ApifyActorOpsService,
    RouteExecutionSnapshot,
    RouteSlotSnapshot,
)
from src.services.apify_actor_capability_matrix import (
    reconcile_registered_route_policies,
)
from src.services.job_queue import JobQueue
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _manifest(actor_id: str) -> dict:
    return {
        "version": 1,
        "actor_id": actor_id,
        "build_number": "1.0.1",
        "input": {
            "url": {"$ref": "target.canonical_url"},
            "maxItems": {"$ref": "runtime.max_items"},
        },
        "output": {
            "native_id": {"pointers": ["/id"]},
            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
            "published_at": {
                "pointers": ["/publishedAt"],
                "transforms": ["parse_datetime"],
            },
            "title": {"pointers": ["/title"]},
            "author_handle": {"pointers": ["/handle"]},
        },
        "semantics": {
            "identity": {
                "output_field": "author_handle",
                "target_ref": "target.handle",
                "match": "handle",
            },
            "url_host_allowlist": ["instagram.com"],
        },
    }


def test_restart_marks_batch_item_and_job_unknown_without_replay(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="restart-recovery-owner",
        password="safe-test-password",
        role="owner",
    )
    ops = ApifyActorOpsService(store)
    route = next(
        item for item in ops.list_routes()
        if item["route_key"] == "instagram/profile/items"
    )
    actor_id = "restart-recovery/actor"
    candidate_id = ops.ensure_candidate(str(route["route_id"]), actor_id=actor_id)
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="restart-recovery",
        build_id="restart-build",
        build_number="1.0.1",
        manifest=_manifest(actor_id),
    )
    validation = ops.approve_revision_canary(
        str(route["route_id"]),
        revision_id,
        expected_generation=int(route["generation"]),
        approval_id="restart-recovery-approval-0001",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"restart-reference").hexdigest(),
    )
    batch_id = "apify-canary-batch-restart-recovery"
    now = datetime.now(timezone.utc).isoformat()
    connection = store.connect()
    connection.execute(
        """
        INSERT INTO apify_actor_discovery_runs (
            run_id, workspace_id, route_id, stage, trigger_reason,
            budget_usd, query_count, created_at, updated_at
        ) VALUES ('restart-recovery-run', ?, ?, 'awaiting_canary_approval',
                  'test', 0.02, 1, ?, ?)
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"], now, now),
    )
    connection.execute(
        """
        INSERT INTO apify_actor_canary_batches (
            batch_id, workspace_id, route_id, discovery_run_id,
            approval_key_hash, approved_generation, plan_hash, max_candidates,
            max_total_charge_usd, per_candidate_cap_usd, goal, status,
            planned_count, success_count, publisher_count, cost_final,
            created_by_user_id, created_at, updated_at
        ) VALUES (?, ?, ?, 'restart-recovery-run', ?, ?, ?, 1, 0.02, 0.02,
                  'initial_pool', 'running', 1, 0, 0, 0, ?, ?, ?)
        """,
        (
            batch_id,
            DEFAULT_WORKSPACE_ID,
            route["route_id"],
            "a" * 64,
            int(route["generation"]),
            "b" * 64,
            owner["id"],
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO apify_actor_canary_batch_items (
            workspace_id, batch_id, ordinal, revision_id, validation_id,
            status, authorized_cap_usd, cost_final, updated_at
        ) VALUES (?, ?, 1, ?, ?, 'running', 0.02, 0, ?)
        """,
        (DEFAULT_WORKSPACE_ID, batch_id, revision_id, validation["validation_id"], now),
    )
    connection.commit()
    job = JobQueue(store).create_job(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=str(owner["id"]),
        job_type="apify_actor_canary_batch",
        payload={"batch_id": batch_id},
        priority=100,
        max_attempts=1,
    )
    connection.execute(
        "UPDATE fetch_jobs SET status = 'running' WHERE id = ?", (job["id"],)
    )
    connection.commit()
    snapshot = RouteExecutionSnapshot(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_id=str(route["route_id"]),
        route_key=str(route["route_key"]),
        route_generation=int(route["generation"]),
        per_run_cap_usd=0.02,
        slots=(
            RouteSlotSnapshot(
                slot_name="primary",
                candidate_id=candidate_id,
                revision_id=revision_id,
                actor_id=actor_id,
                publisher="restart-recovery",
                build_id="restart-build",
                build_number="1.0.1",
                manifest_hash=None,
                lifecycle="static_valid",
                candidate_state="open",
                manifest=None,
            ),
        ),
    )
    attempt_id = ops.begin_validation_attempt(
        str(validation["validation_id"]),
        snapshot,
        snapshot.slots[0],
        job_id=str(job["id"]),
    )
    connection.execute(
        """
        INSERT INTO apify_actor_runs (
            id, workspace_id, logical_run_id, secret_id, secret_version,
            pool_generation, remote_run_id, status, charge_reserved_usd,
            charge_final, created_at, updated_at
        ) VALUES ('restart-recovery-run-local', ?, ?, 'secret', 1, 1,
                  'remote-restart-run', 'running', 0.02, 0, ?, ?)
        """,
        (DEFAULT_WORKSPACE_ID, attempt_id, now, now),
    )
    connection.commit()

    result = ops.reconcile_unfinished_attempts()

    assert result == {
        "cancelled": 0,
        "blocked": 1,
        "routes_blocked": 1,
        "batches_blocked": 1,
    }
    assert ops.get_canary_batch(batch_id)["status"] == "blocked_unknown_start"
    assert ops.get_canary_batch(batch_id)["items"][0]["status"] == (
        "blocked_unknown_start"
    )
    assert ops.get_validation(str(validation["validation_id"]))["semantic_outcome"] == (
        "apify_worker_restart_reconcile_required"
    )
    assert JobQueue(store).get_job(str(job["id"]))["status"] == "failed"


def test_youtube_converges_to_the_registered_two_actor_primary_policy(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = next(
        item for item in ops.list_routes()
        if item["route_key"] == "youtube/channel/items"
    )
    assert route["mode"] == "primary"
    assert route["min_runtime_healthy"] == 2
    assert route["min_publishers"] == 2

    connection = store.connect()
    connection.execute(
        """
        UPDATE apify_actor_route_profiles
        SET mode = 'fallback', min_runtime_healthy = 1, min_publishers = 1,
            policy_version = 'actor_ops_v1'
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    )
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    result = reconcile_registered_route_policies(
        connection,
        workspace_id=DEFAULT_WORKSPACE_ID,
        now=datetime.now(timezone.utc).isoformat(),
    )
    connection.commit()

    assert result["routes"] >= 1
    updated = ops.get_route(str(route["route_id"]))
    assert updated["mode"] == "primary"
    assert updated["min_runtime_healthy"] == 2
    assert updated["min_publishers"] == 2
