"""Regression coverage for restart-safe Actor Canary state projection."""

from __future__ import annotations

import hashlib
import asyncio
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
from src.services.apify_actor_canary_reconciliation import (
    reconcile_interrupted_canary_runs,
)
from src.services.job_queue import JobQueue
from src.services.worker_actor_canary_handler import _CanaryContext, _run_route_items
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
    next_actor_id = "restart-recovery/actor-next"
    next_candidate_id = ops.ensure_candidate(
        str(route["route_id"]), actor_id=next_actor_id
    )
    next_revision_id = ops.create_adapter_revision(
        candidate_id=next_candidate_id,
        actor_id=next_actor_id,
        publisher="restart-recovery-next",
        build_id="restart-build-next",
        build_number="1.0.1",
        manifest=_manifest(next_actor_id),
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
    next_validation = ops.approve_revision_canary(
        str(route["route_id"]),
        next_revision_id,
        expected_generation=int(route["generation"]),
        approval_id="restart-recovery-approval-0002",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(b"restart-reference-next").hexdigest(),
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
            ) VALUES (?, ?, ?, 'restart-recovery-run', ?, ?, ?, 2, 0.02, 0.02,
                      'initial_pool', 'running', 2, 0, 0, 0, ?, ?, ?)
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
    connection.execute(
        """
        INSERT INTO apify_actor_canary_batch_items (
            workspace_id, batch_id, ordinal, revision_id, validation_id,
            status, authorized_cap_usd, cost_final, updated_at
        ) VALUES (?, ?, 2, ?, ?, 'planned', 0.02, 0, ?)
        """,
        (
            DEFAULT_WORKSPACE_ID,
            batch_id,
            next_revision_id,
            next_validation["validation_id"],
            now,
        ),
    )
    stage_id = "apify-pool-stage-restart-recovery"
    connection.execute(
        """
        INSERT INTO apify_actor_pool_stages (
            stage_id, workspace_id, route_id, discovery_run_id,
            initial_batch_id, goal, target_slot_count, selection_mode,
            base_generation, base_pool_hash, plan_hash, approval_key_hash,
            max_total_charge_usd, route_validation_cap_usd, status,
            created_by_user_id, created_at, updated_at
        ) VALUES (?, ?, ?, 'restart-recovery-run', ?, 'initial_pool',
                  2, 'server', ?, ?, ?, ?, 0.02, 0.02, 'queued', ?, ?, ?)
        """,
        (
            stage_id,
            DEFAULT_WORKSPACE_ID,
            route["route_id"],
            batch_id,
            route["generation"],
            "c" * 64,
            "b" * 64,
            "a" * 64,
            owner["id"],
            now,
            now,
        ),
    )
    connection.execute(
        """UPDATE apify_actor_canary_batches SET pool_stage_id = ?
           WHERE workspace_id = ? AND batch_id = ?""",
        (stage_id, DEFAULT_WORKSPACE_ID, batch_id),
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
    attempt_id = _begin_interrupted_remote_run(
        ops=ops,
        connection=connection,
        route=route,
        candidate_id=candidate_id,
        revision_id=revision_id,
        actor_id=actor_id,
        validation_id=str(validation["validation_id"]),
        job_id=str(job["id"]),
        now=now,
    )
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
    assert int(ops.get_route(str(route["route_id"]))["generation"]) == (
        int(route["generation"]) + 1
    )
    assert JobQueue(store).get_job(str(job["id"]))["status"] == "failed"
    _assert_terminal_failure_continues_frozen_batch(
        store=store,
        ops=ops,
        connection=connection,
        route_id=str(route["route_id"]),
        attempt_id=attempt_id,
        validation_id=str(validation["validation_id"]),
        batch_id=batch_id,
        stage_id=stage_id,
        expected_generation=int(route["generation"]),
        data_dir=str(tmp_path),
    )


def _begin_interrupted_remote_run(
    *,
    ops: ApifyActorOpsService,
    connection,
    route: dict,
    candidate_id: str,
    revision_id: str,
    actor_id: str,
    validation_id: str,
    job_id: str,
    now: str,
) -> str:
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
        validation_id,
        snapshot,
        snapshot.slots[0],
        job_id=job_id,
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
    return attempt_id


def _assert_terminal_failure_continues_frozen_batch(
    *,
    store: ServiceStore,
    ops: ApifyActorOpsService,
    connection,
    route_id: str,
    attempt_id: str,
    validation_id: str,
    batch_id: str,
    stage_id: str,
    expected_generation: int,
    data_dir: str,
) -> None:

    # A later free GET reconciliation proves the known Run ended with a
    # deterministic contract failure.  It must unblock only the original
    # frozen batch, so its remaining approved candidates can be processed.
    connection.execute(
        """
        UPDATE apify_actor_attempts
        SET status = 'actor_failed', semantic_outcome = 'apify_actor_contract_mismatch'
        WHERE id = ?
        """,
        (attempt_id,),
    )
    connection.execute(
        """
        UPDATE apify_actor_validations
        SET status = 'failed', semantic_outcome = 'apify_actor_contract_mismatch',
            cost_final = 1
        WHERE validation_id = ?
        """,
        (validation_id,),
    )
    connection.execute(
        """
        UPDATE apify_actor_canary_batch_items
        SET status = 'failed', semantic_outcome = 'apify_actor_contract_mismatch',
            cost_final = 1
        WHERE validation_id = ?
        """,
        (validation_id,),
    )
    # This is the persisted shape observed in the canonical runtime: the
    # profile is blocked while the Stage remained in its former active state.
    connection.execute(
        """UPDATE apify_actor_pool_stages SET status = 'validating_route'
           WHERE workspace_id = ? AND stage_id = ?""",
        (DEFAULT_WORKSPACE_ID, stage_id),
    )
    connection.commit()

    recovery = reconcile_interrupted_canary_runs(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        data_dir=data_dir,
    )

    assert recovery == {"checked": 1, "reconciled": 0, "continued": 1}
    assert ops.get_canary_batch(batch_id)["status"] == "queued"
    assert ops.get_pool_stage(stage_id)["status"] == "queued"
    assert ops.get_route(route_id)["status"] == "ready"
    assert int(ops.get_route(route_id)["generation"]) == expected_generation


def test_resumed_batch_skips_terminal_failure_and_runs_only_next_item() -> None:
    """A recovered batch must not POST its already settled Actor again."""

    ops = _RouteItemOps()
    runner = _RouteItemRunner()
    client = _RouteItemClient()
    context = _CanaryContext(
        job={"id": "recovery-job"},
        store=None,
        ops=ops,
        runner=runner,
        client=client,
        batch_id="recovery-batch",
        current={"route_id": "route-id"},
        goal="initial_pool",
        stage_id=None,
    )

    stop_reason, blocked = asyncio.run(_run_route_items(context))

    assert (stop_reason, blocked) == (None, None)
    assert client.preflighted == ["next-actor"]
    assert runner.executed == ["next-validation"]
    assert all(ordinal != 1 for ordinal, _status in ops.item_updates)


class _RouteItemOps:
    def __init__(self) -> None:
        self.item_updates: list[tuple[int, str]] = []
        self.batch_status = "preflighting"

    def get_canary_batch(self, _batch_id: str) -> dict:
        return {
            "status": self.batch_status,
            "items": [
                {
                    "ordinal": 1,
                    "validation_id": "settled-failure",
                    "revision_id": "settled-revision",
                    "actor_id": "failed-actor",
                    "build_id": "failed-build",
                    "build_number": "1",
                    "status": "failed",
                },
                {
                    "ordinal": 2,
                    "validation_id": "next-validation",
                    "revision_id": "next-revision",
                    "actor_id": "next-actor",
                    "build_id": "next-build",
                    "build_number": "1",
                    "status": "planned",
                },
            ],
        }

    def recommend_active_pool(self, _route_id: str) -> dict:
        return {"ready": False}

    def get_revision(self, _revision_id: str) -> dict:
        return {"security_evidence": {}}

    def update_canary_batch_item(self, _batch_id: str, ordinal: int, *, status: str, **_kwargs) -> None:
        self.item_updates.append((ordinal, status))

    def set_canary_batch_status(self, _batch_id: str, *, status: str, **_kwargs) -> None:
        self.batch_status = status

    def get_validation(self, _validation_id: str) -> dict:
        return {"cost_usd": 0.01, "cost_final": True}


class _RouteItemRunner:
    def __init__(self) -> None:
        self.executed: list[str] = []

    async def run(self, validation_id: str, **_kwargs):
        self.executed.append(validation_id)
        return _RouteItemResult()


class _RouteItemClient:
    def __init__(self) -> None:
        self.preflighted: list[str] = []

    async def preflight_actor_revision(self, actor_id: str, **_kwargs) -> None:
        self.preflighted.append(actor_id)


class _RouteItemResult:
    semantic_outcome = "valid_nonempty"
    cost_usd = 0.01


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
