"""Settle a start_outcome_unknown attempt once its remote Run is terminal.

Regression for the blocked Key-pool / route barrier: a Worker restart could
mark an acquisition attempt ``start_outcome_unknown`` before the remote Run
reached a terminal status.  Once Apify confirms ``succeeded``, the attempt
must be projected to a terminal state and the route / Key-pool barrier
released, otherwise every platform is stuck behind ``apify_key_pool_blocked``.
"""

from __future__ import annotations

from datetime import datetime, timezone

from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _now() -> str:
    return datetime.now(timezone.utc).isoformat()


def _manifest(actor_id: str) -> dict:
    return {
        "version": 1,
        "actor_id": actor_id,
        "build_number": "1.0.0",
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


def test_terminal_run_releases_start_unknown_barrier(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = next(
        item for item in ops.list_routes()
        if item["route_key"] == "instagram/profile/items"
    )
    route_id = str(route["route_id"])
    candidate_id = ops.ensure_candidate(
        route_id, actor_id="settle/actor"
    )
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id="settle/actor",
        publisher="settle",
        build_id="settle-build",
        build_number="1.0.0",
        manifest=_manifest("settle/actor"),
    )
    now = _now()
    attempt_id = "apify-attempt-settle-terminal"
    connection = store.connect()
    connection.execute(
        """
        INSERT INTO apify_actor_attempts (
            id, workspace_id, route_key, route_generation, candidate_id,
            attempt_group_id, attempt_index, status,
            semantic_outcome, reserved_usd, actual_cost_usd, cost_final,
            adapter_revision_id, build_id, build_number, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'settle-group', 1, 'start_outcome_unknown',
                  'apify_run_reconcile_required', 0.02, NULL, 0, ?, ?, ?,
                  ?, ?)
        """,
        (
            attempt_id,
            DEFAULT_WORKSPACE_ID,
            route["route_key"],
            int(route["generation"]),
            candidate_id,
            revision_id,
            "settle-build",
            "1.0.0",
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO apify_actor_runs (
            id, workspace_id, logical_run_id, secret_id, secret_version,
            pool_generation, remote_run_id, status, charge_reserved_usd,
            charge_actual_usd, charge_final, purpose, created_at,
            terminal_at, updated_at
        ) VALUES ('apifyrun-settle-terminal', ?, ?, 'secret-settle', 1, 1,
                  'remote-settle-run', 'succeeded', 0.02, 0.00005, 0,
                  'acquisition', ?, ?, ?)
        """,
        (DEFAULT_WORKSPACE_ID, attempt_id, now, now, now),
    )
    # Simulate the barrier written by the previous unknown-start projection.
    connection.execute(
        """
        UPDATE apify_actor_route_profiles
        SET status = 'blocked_unknown_start', generation = generation + 1
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route_id),
    )
    connection.execute(
        """
        UPDATE apify_actor_routes
        SET status = 'blocked', blocked_reason = 'start_outcome_unknown',
            generation = generation + 1
        WHERE workspace_id = ? AND route_key = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_key"]),
    )
    connection.execute(
        """
        UPDATE apify_key_pool_state
        SET status = 'blocked', blocked_reason = 'start_outcome_unknown',
            generation = generation + 1
        WHERE workspace_id = ?
        """,
        (DEFAULT_WORKSPACE_ID,),
    )
    connection.commit()

    result = ops.reconcile_unfinished_attempts()

    assert result == {
        "cancelled": 1,
        "blocked": 0,
        "routes_blocked": 0,
        "batches_blocked": 0,
    }
    attempt = connection.execute(
        "SELECT status, semantic_outcome FROM apify_actor_attempts WHERE id = ?",
        (attempt_id,),
    ).fetchone()
    assert attempt["status"] == "cancelled"
    assert attempt["semantic_outcome"] == "apify_worker_restart_result_lost"
    assert ops.get_route(route_id)["status"] == "ready"
    pool = connection.execute(
        "SELECT status, blocked_reason FROM apify_key_pool_state WHERE workspace_id = ?",
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    assert pool["status"] == "ready"
    assert pool["blocked_reason"] is None


def test_running_run_keeps_unknown_barrier(tmp_path) -> None:
    """A still-non-terminal Run must keep the attempt unknown (no premature release)."""

    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = next(
        item for item in ops.list_routes()
        if item["route_key"] == "instagram/profile/items"
    )
    candidate_id = ops.ensure_candidate(str(route["route_id"]), actor_id="keep/actor")
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id="keep/actor",
        publisher="keep",
        build_id="keep-build",
        build_number="1.0.0",
        manifest=_manifest("keep/actor"),
    )
    now = _now()
    attempt_id = "apify-attempt-keep-unknown"
    connection = store.connect()
    connection.execute(
        """
        INSERT INTO apify_actor_attempts (
            id, workspace_id, route_key, route_generation, candidate_id,
            attempt_group_id, attempt_index, status, semantic_outcome,
            reserved_usd, actual_cost_usd, cost_final, adapter_revision_id,
            build_id, build_number, created_at, updated_at
        ) VALUES (?, ?, ?, ?, ?, 'keep-group', 1, 'start_outcome_unknown',
                  'apify_worker_restart_reconcile_required', 0.02, NULL, 0,
                  ?, ?, ?, ?, ?)
        """,
        (
            attempt_id,
            DEFAULT_WORKSPACE_ID,
            route["route_key"],
            int(route["generation"]),
            candidate_id,
            revision_id,
            "keep-build",
            "1.0.0",
            now,
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO apify_actor_runs (
            id, workspace_id, logical_run_id, secret_id, secret_version,
            pool_generation, remote_run_id, status, charge_reserved_usd,
            charge_final, purpose, created_at, updated_at
        ) VALUES ('apifyrun-keep-unknown', ?, ?, 'secret-keep', 1, 1,
                  'remote-keep-run', 'running', 0.02, 0, 'acquisition', ?, ?)
        """,
        (DEFAULT_WORKSPACE_ID, attempt_id, now, now),
    )
    connection.commit()

    result = ops.reconcile_unfinished_attempts()

    assert result["blocked"] == 1
    assert result["cancelled"] == 0
    attempt = connection.execute(
        "SELECT status FROM apify_actor_attempts WHERE id = ?",
        (attempt_id,),
    ).fetchone()
    assert attempt["status"] == "start_outcome_unknown"
