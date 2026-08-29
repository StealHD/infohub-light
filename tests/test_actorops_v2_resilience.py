from __future__ import annotations

import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest

import scripts.migrate_actorops_v2_resilience as resilience_migration
from scripts.migrate_actorops_v2_resilience import migrate, preview
from src.apify_actor_identity import source_target_fingerprint
from src.services.apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from src.services.actorops.domain import (
    CandidateLifecycle,
    DiscoveryStage,
    DiscoveryStatus,
)
from src.services.actorops.repository import ActorOpsRepository
from src.storage.actorops_v2_resilience_schema import (
    MIGRATION_VERSION,
    migration_marker_exists,
    schema_shapes_valid,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _manifest(actor_id: str) -> str:
    return json.dumps({
        "version": 1,
        "actor_id": actor_id,
        "build_number": "1.0.0",
        "input": {"target": {"$ref": "target.handle"}},
        "output": {
            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
            "published_at": {
                "pointers": ["/createdAt"],
                "transforms": ["parse_datetime"],
            },
            "text": {"pointers": ["/text"], "transforms": ["to_string"]},
            "author_handle": {
                "pointers": ["/author"],
                "transforms": ["to_string"],
            },
        },
        "semantics": {
            "identity": {
                "output_field": "author_handle",
                "target_ref": "target.handle",
                "match": "handle",
            },
            "url_host_allowlist": ["example.com"],
        },
    })


def _repository(tmp_path: Path):
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    route = connection.execute(
        "SELECT * FROM actor_routes_v2 WHERE platform='x'"
    ).fetchone()
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace", owner_user_id=None,
        source_type="apify_social", display_name="Resilience source",
        config={"platform": "x", "kind": "profile", "target": "openai"},
    )
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    fingerprint = source_target_fingerprint(
        DEFAULT_WORKSPACE_ID, str(route["route_id"]), "openai", platform="x",
    )
    with repository.transaction():
        for index in range(2):
            candidate_id = f"candidate-{index}"
            actor_id = f"publisher/actor-{index}"
            manifest = _manifest(actor_id)
            repository.create_candidate(
                candidate_id=candidate_id, route_id=str(route["route_id"]),
                actor_id=actor_id, publisher="publisher",
                build_id=f"build-{index}", build_number="1.0.0",
                manifest_json=manifest,
                manifest_hash=actor_manifest_hash(parse_actor_manifest(manifest)),
                input_schema_hash="b" * 64, output_schema_hash="c" * 64,
                lifecycle=CandidateLifecycle.CERTIFIED,
            )
            connection.execute(
                "UPDATE actor_candidates_v2 SET assignment_role=?, priority=? WHERE candidate_id=?",
                ("active" if index == 0 else "standby", index, candidate_id),
            )
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (
                   binding_id, workspace_id, source_id, route_id, target_fingerprint,
                   status, binding_version, created_at, updated_at
               ) VALUES ('binding-resilience', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
            (DEFAULT_WORKSPACE_ID, source_id, route["route_id"], fingerprint,
             "2026-08-24T00:00:00+00:00", "2026-08-24T00:00:00+00:00"),
        )
    return store, repository, str(route["route_id"]), source_id


def _terminal_discovery(
    repository: ActorOpsRepository,
    discovery_id: str,
    status: DiscoveryStatus,
) -> None:
    with repository.transaction():
        row = repository.discovery.get(discovery_id)
        repository.discovery.checkpoint(
            discovery_id,
            expected_status=DiscoveryStatus(str(row["status"])),
            expected_stage=DiscoveryStage(str(row["stage"])),
            expected_generation=int(row["generation"]),
            status=DiscoveryStatus.RUNNING,
            stage=(
                DiscoveryStage.PERSIST
                if status is DiscoveryStatus.COMPLETED
                else DiscoveryStage(str(row["stage"]))
            ),
            checkpoint_hash=None,
            search_cursor=None,
            query_count=int(row["query_count"]),
            candidate_count=int(row["candidate_count"]),
            rejection_count=int(row["rejection_count"]),
        )
        row = repository.discovery.get(discovery_id)
        repository.discovery.checkpoint(
            discovery_id,
            expected_status=DiscoveryStatus.RUNNING,
            expected_stage=DiscoveryStage(str(row["stage"])),
            expected_generation=int(row["generation"]),
            status=status,
            stage=DiscoveryStage(str(row["stage"])),
            checkpoint_hash=None,
            search_cursor=None,
            query_count=int(row["query_count"]),
            candidate_count=int(row["candidate_count"]),
            rejection_count=int(row["rejection_count"]),
        )


def test_global_31_is_explicit_for_existing_store_and_fresh_for_new_store(tmp_path: Path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    assert migration_marker_exists(connection)
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    for table in (
        "actor_execution_events_v2", "actor_route_repairs_v2",
        "actor_source_candidate_freshness_v2",
    ):
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,))
    connection.commit()
    connection.execute("PRAGMA foreign_keys=ON")
    store.close()

    assert preview(tmp_path / "data")["status"] == "migration_required"
    result = migrate(tmp_path / "data", apply=True, backup_dir=tmp_path / "backups")
    assert result["status"] == "applied"
    assert result["backup_mode"] == "0o600"
    assert migrate(tmp_path / "data", apply=True, backup_dir=tmp_path / "backups")["status"] == "already_migrated"
    reopened = ServiceStore(tmp_path / "data")
    reopened.initialize()
    try:
        assert migration_marker_exists(reopened.connect())
        assert schema_shapes_valid(reopened.connect())
    finally:
        reopened.close()


def test_migration_failure_restores_the_previous_global_30_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    connection.commit()
    connection.execute("PRAGMA foreign_keys=OFF")
    for table in (
        "actor_execution_events_v2", "actor_route_repairs_v2",
        "actor_source_candidate_freshness_v2",
    ):
        connection.execute(f"DROP TABLE {table}")
    connection.execute("DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,))
    connection.commit()
    connection.execute("PRAGMA foreign_keys=ON")
    store.close()

    original = resilience_migration.apply_migration

    def fail_after_apply(db):
        original(db)
        raise RuntimeError("forced migration verification failure")

    monkeypatch.setattr(resilience_migration, "apply_migration", fail_after_apply)
    with pytest.raises(RuntimeError, match="forced migration verification failure"):
        resilience_migration.migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    restored = ServiceStore(data_dir)
    restored.initialize()
    try:
        assert not migration_marker_exists(restored.connect())
        assert preview(data_dir)["status"] == "migration_required"
    finally:
        restored.close()


def test_three_scheduled_no_advance_cross_checks_and_demotes_per_source(tmp_path: Path) -> None:
    store, repository, _route_id, source_id = _repository(tmp_path)
    try:
        binding = repository.get_binding(source_id)
        repository.resilience.record_regular_result(
            binding=binding, candidate_id="candidate-0", outcome="no_advance",
            logical_job_id="manual-fetch", natural_schedule=False,
        )
        assert repository.connection.execute(
            "SELECT COUNT(*) FROM actor_source_candidate_freshness_v2"
        ).fetchone()[0] == 0
        for index in range(3):
            repository.resilience.record_regular_result(
                binding=binding, candidate_id="candidate-0", outcome="no_advance",
                logical_job_id=f"scheduled-{index}", natural_schedule=True,
            )
        plan = repository.resilience.plan_candidates(
            binding=binding, candidates=repository.freeze_execution(
                binding.route_id, source_id, binding.target_fingerprint,
            ).candidates, natural_schedule=True,
        )
        assert plan.cross_check is True
        assert plan.primary_candidate_id == "candidate-0"
        assert plan.candidates[0].candidate_id == "candidate-1"

        result = repository.resilience.record_cross_check(
            binding=binding, primary_candidate_id="candidate-0",
            candidate_id="candidate-1", outcome="advanced", logical_job_id="scheduled-4",
        )
        assert result == "source_stale"
        assert repository.get_binding(source_id).preferred_candidate_id == "candidate-1"
        row = repository.connection.execute(
            """SELECT state, cooldown_until FROM actor_source_candidate_freshness_v2
               WHERE source_id=? AND candidate_id='candidate-0'""", (source_id,),
        ).fetchone()
        assert tuple(row)[0] == "source_stale"
        assert row["cooldown_until"] is not None
        repository.connection.execute(
            "UPDATE actor_source_bindings_v2 SET binding_version=2 WHERE source_id=?",
            (source_id,),
        )
        repository.connection.commit()
        rebound = repository.get_binding(source_id)
        reset = repository.resilience.plan_candidates(
            binding=rebound, candidates=repository.freeze_execution(
                rebound.route_id, source_id, rebound.target_fingerprint,
            ).candidates, natural_schedule=True,
        )
        assert reset.cross_check is False
    finally:
        store.close()


def test_second_source_confirmation_is_required_for_global_stale_demotion(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    try:
        binding = repository.get_binding(source_id)
        for index in range(3):
            repository.resilience.record_regular_result(
                binding=binding, candidate_id="candidate-0", outcome="no_advance",
                logical_job_id=f"first-{index}", natural_schedule=True,
            )
        assert repository.resilience.record_cross_check(
            binding=binding, primary_candidate_id="candidate-0", candidate_id="candidate-1",
            outcome="advanced", logical_job_id="first-cross-check",
        ) == "source_stale"
        assert repository.get_candidate("candidate-0").lifecycle is CandidateLifecycle.CERTIFIED

        second_source = store.create_source(
            workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace", owner_user_id=None,
            source_type="apify_social", display_name="Second resilience source",
            config={"platform": "x", "kind": "profile", "target": "second"},
        )
        second_fingerprint = source_target_fingerprint(
            DEFAULT_WORKSPACE_ID, route_id, "second", platform="x",
        )
        with repository.transaction():
            repository.connection.execute(
                """INSERT INTO actor_source_bindings_v2 (
                       binding_id, workspace_id, source_id, route_id, target_fingerprint,
                       status, binding_version, created_at, updated_at
                   ) VALUES ('binding-resilience-second', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
                (DEFAULT_WORKSPACE_ID, second_source, route_id, second_fingerprint,
                 "2026-08-24T00:00:00+00:00", "2026-08-24T00:00:00+00:00"),
            )
        second_binding = repository.get_binding(second_source)
        for index in range(3):
            repository.resilience.record_regular_result(
                binding=second_binding, candidate_id="candidate-0", outcome="no_advance",
                logical_job_id=f"second-{index}", natural_schedule=True,
            )
        assert repository.resilience.record_cross_check(
            binding=second_binding, primary_candidate_id="candidate-0", candidate_id="candidate-1",
            outcome="advanced", logical_job_id="second-cross-check",
        ) == "source_stale"
        assert repository.get_candidate("candidate-0").lifecycle is CandidateLifecycle.QUARANTINED
    finally:
        store.close()


def test_paid_failure_backoff_escalates_and_half_open_is_singleflight(
    tmp_path: Path,
) -> None:
    store, repository, _route_id, source_id = _repository(tmp_path)
    try:
        binding = repository.get_binding(source_id)
        for expected_streak, expected_hours in ((1, 6), (2, 12), (3, 24)):
            repository.resilience.record_paid_candidate_failure(
                binding=binding, candidate_id="candidate-0",
                logical_job_id=f"paid-failure-{expected_streak}",
            )
            row = repository.connection.execute(
                """SELECT failure_streak, cooldown_until, cooldown_reason
                   FROM actor_source_candidate_freshness_v2
                   WHERE source_id=? AND candidate_id='candidate-0'""",
                (source_id,),
            ).fetchone()
            remaining = datetime.fromisoformat(str(row["cooldown_until"])) - datetime.now(
                timezone.utc
            )
            assert row["failure_streak"] == expected_streak
            assert row["cooldown_reason"] == "paid_candidate_failure"
            assert timedelta(hours=expected_hours) - timedelta(minutes=1) < remaining
            repository.connection.execute(
                """UPDATE actor_source_candidate_freshness_v2
                      SET cooldown_until=?, half_open_lease_until=NULL,
                          half_open_lease_token=NULL
                    WHERE source_id=? AND candidate_id='candidate-0'""",
                ((datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(), source_id),
            )
            repository.connection.commit()

        candidate = repository.get_candidate("candidate-0")
        first = repository.resilience.plan_candidates(
            binding=binding, candidates=(candidate,), natural_schedule=False,
            logical_job_id="half-open-a",
        )
        second = repository.resilience.plan_candidates(
            binding=binding, candidates=(candidate,), natural_schedule=False,
            logical_job_id="half-open-b",
        )
        replay = repository.resilience.plan_candidates(
            binding=binding, candidates=(candidate,), natural_schedule=False,
            logical_job_id="half-open-a",
        )
        assert [item.candidate_id for item in first.candidates] == ["candidate-0"]
        assert second.candidates == ()
        assert [item.candidate_id for item in replay.candidates] == ["candidate-0"]

        repository.resilience.record_candidate_success(
            binding=binding, candidate_id="candidate-0",
            logical_job_id="half-open-a",
        )
        closed = repository.connection.execute(
            """SELECT state, failure_streak, cooldown_until,
                      half_open_lease_until, half_open_lease_token
                 FROM actor_source_candidate_freshness_v2
                WHERE source_id=? AND candidate_id='candidate-0'""",
            (source_id,),
        ).fetchone()
        assert tuple(closed) == ("neutral", 0, None, None, None)
    finally:
        store.close()


def test_same_logical_job_advances_candidate_circuit_only_once(tmp_path: Path) -> None:
    store, repository, _route_id, source_id = _repository(tmp_path)
    try:
        binding = repository.get_binding(source_id)
        repository.resilience.record_stale_regression(
            binding=binding,
            candidate_id="candidate-0",
            logical_job_id="same-logical-job",
        )
        repository.resilience.record_paid_candidate_failure(
            binding=binding,
            candidate_id="candidate-0",
            logical_job_id="same-logical-job",
        )

        row = repository.connection.execute(
            """SELECT failure_streak, last_outcome, cooldown_reason, last_job_id
                 FROM actor_source_candidate_freshness_v2
                WHERE source_id=? AND candidate_id='candidate-0'""",
            (source_id,),
        ).fetchone()
        assert tuple(row) == (
            1,
            "stale_regression",
            "stale_regression",
            "same-logical-job",
        )
    finally:
        store.close()


def test_repair_and_trace_are_durable_and_redacted(tmp_path: Path, monkeypatch) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    try:
        monkeypatch.setattr(
            "src.services.actorops.repository_resilience.safe_emit_operation_event",
            lambda **_values: True,
        )
        repair = repository.resilience.ensure_repair(
            route_id=route_id, source_id=source_id, origin_job_id="job-safe",
            trigger_code="actorops_route_exhausted",
        )
        assert repair["status"] == "blocked"
        assert repair["error_code"] == "actorops_repair_not_authorized"
        repository.resilience.emit(
            root_job_id="job-safe", route_id=route_id, source_id=source_id,
            candidate_id="candidate-0", repair_id=str(repair["repair_id"]),
            phase="candidate_selection", outcome="selected", counts={"candidate_count": 2},
        )
        events, cursor, completeness = repository.resilience.execution_events(root_job_id="job-safe")
        assert cursor is None
        assert completeness == "complete"
        assert events[0]["counts"] == {"candidate_count": 2}
        assert "target" not in events[0]
        assert "input" not in events[0]
    finally:
        store.close()


def test_cost_settlement_wakes_every_blocked_repair_on_the_route(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    try:
        other_source_id = store.create_source(
            workspace_id=DEFAULT_WORKSPACE_ID,
            scope="workspace",
            owner_user_id=None,
            source_type="apify_social",
            display_name="Other repair source",
            config={"platform": "x", "kind": "profile", "target": "other"},
        )
        fingerprint = source_target_fingerprint(
            DEFAULT_WORKSPACE_ID, route_id, "other", platform="x"
        )
        stamp = "2026-08-24T00:00:00+00:00"
        with repository.transaction():
            repository.connection.execute(
                """INSERT INTO actor_source_bindings_v2 (
                       binding_id, workspace_id, source_id, route_id,
                       target_fingerprint, status, binding_version,
                       created_at, updated_at
                   ) VALUES ('binding-repair-other', ?, ?, ?, ?, 'ready', 1, ?, ?)""",
                (
                    DEFAULT_WORKSPACE_ID,
                    other_source_id,
                    route_id,
                    fingerprint,
                    stamp,
                    stamp,
                ),
            )
            for index, repair_source_id in enumerate((source_id, other_source_id)):
                repository.connection.execute(
                    """INSERT INTO actor_route_repairs_v2 (
                           repair_id, workspace_id, route_id, source_id,
                           trigger_code, status, error_code, attempt_count,
                           next_attempt_at, created_at, updated_at
                       ) VALUES (?, ?, ?, ?, 'actorops_route_exhausted', 'blocked',
                                 'actorops_repair_cost_settlement_required', 1,
                                 ?, ?, ?)""",
                    (
                        f"repair-cost-{index}",
                        DEFAULT_WORKSPACE_ID,
                        route_id,
                        repair_source_id,
                        "2099-01-01T00:00:00+00:00",
                        stamp,
                        stamp,
                    ),
                )

        assert repository.resilience.wake_repairs_after_cost_settlement(
            route_id=route_id, source_id=source_id
        ) == 2
        rows = repository.connection.execute(
            """SELECT source_id, next_attempt_at FROM actor_route_repairs_v2
                WHERE repair_id LIKE 'repair-cost-%' ORDER BY source_id"""
        ).fetchall()
        assert {str(row["source_id"]) for row in rows} == {
            source_id,
            other_source_id,
        }
        assert all(str(row["next_attempt_at"]) != "2099-01-01T00:00:00+00:00" for row in rows)
    finally:
        store.close()


def test_authorized_repair_recovers_healthy_route_and_discovers_for_single_path(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    try:
        store.create_user(
            workspace_id=DEFAULT_WORKSPACE_ID, username="resilience-owner",
            password="safe-test-password", role="owner",
        )
        owner = store.connect().execute(
            "SELECT id FROM users WHERE workspace_id=? ORDER BY created_at LIMIT 1",
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()
        assert owner is not None
        store.connect().execute(
            """UPDATE actor_maintenance_policies_v2 SET enabled=1,
                   authorized_by_user_id=?, authorized_at='2026-08-24T00:00:00+00:00'
               WHERE workspace_id=?""",
            (owner["id"], DEFAULT_WORKSPACE_ID),
        )
        store.connect().commit()
        repair = repository.resilience.ensure_repair(
            route_id=route_id, source_id=source_id, origin_job_id="job-repair",
            trigger_code="actorops_route_exhausted",
        )
        assert repair["status"] == "queued"
        advanced = repository.resilience.advance_repair(str(repair["repair_id"]))
        assert advanced["status"] == "recovered"
        assert advanced["discovery_id"] is None

        with repository.transaction():
            repository.connection.execute(
                """UPDATE actor_candidates_v2
                      SET lifecycle='disabled', assignment_role='inactive',
                          priority=NULL, generation=generation+1
                    WHERE candidate_id='candidate-1'"""
            )
        single_path = repository.resilience.ensure_repair(
            route_id=route_id,
            source_id=source_id,
            origin_job_id="job-repair-single-path",
            trigger_code="actorops_route_at_risk",
        )
        discovering = repository.resilience.advance_repair(
            str(single_path["repair_id"])
        )
        assert discovering["status"] == "discovering"
        assert discovering["discovery_id"]
        discovery = repository.discovery.get(str(discovering["discovery_id"]))
        assert discovery["trigger_reason"] == "production_exhausted"
    finally:
        store.close()


def test_repair_records_budget_block_without_remote_activity(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    try:
        owner = store.create_user(
            workspace_id=DEFAULT_WORKSPACE_ID, username="budget-owner",
            password="safe-test-password", role="owner",
        )
        store.connect().execute(
            """UPDATE actor_maintenance_policies_v2 SET enabled=1,
                   authorized_by_user_id=?, authorized_at='2026-08-24T00:00:00+00:00'
               WHERE workspace_id=?""",
            (owner["id"], DEFAULT_WORKSPACE_ID),
        )
        store.connect().execute(
            """UPDATE actor_maintenance_policies_v2 SET monthly_budget_usd=0.01
               WHERE workspace_id=? AND route_id IS NULL""",
            (DEFAULT_WORKSPACE_ID,),
        )
        store.connect().commit()

        repair = repository.resilience.ensure_repair(
            route_id=route_id, source_id=source_id, origin_job_id="job-budget",
            trigger_code="actorops_route_exhausted",
        )

        assert repair["status"] == "blocked"
        assert repair["error_code"] == "actorops_repair_monthly_budget_exhausted"
        assert repository.connection.execute(
            "SELECT COUNT(*) FROM actor_attempts_v2 WHERE kind='probe'"
        ).fetchone()[0] == 0
    finally:
        store.close()


def test_repair_skips_rejected_discovery_candidate_and_uses_next_candidate(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    try:
        store.create_user(
            workspace_id=DEFAULT_WORKSPACE_ID,
            username="repair-rotation-owner",
            password="safe-test-password",
            role="owner",
        )
        with repository.transaction():
            repository.connection.execute(
                """UPDATE actor_candidates_v2
                      SET lifecycle='disabled', assignment_role='inactive',
                          priority=NULL, generation=generation+1
                    WHERE candidate_id='candidate-1'"""
            )
            for candidate_id in ("repair-rejected", "repair-usable"):
                actor_id = f"publisher/{candidate_id}"
                manifest = _manifest(actor_id)
                repository.create_candidate(
                    candidate_id=candidate_id,
                    route_id=route_id,
                    actor_id=actor_id,
                    publisher="publisher",
                    build_id=f"build-{candidate_id}",
                    build_number="1.0.0",
                    manifest_json=manifest,
                    manifest_hash=actor_manifest_hash(parse_actor_manifest(manifest)),
                    input_schema_hash="e" * 64,
                    output_schema_hash="f" * 64,
                    lifecycle=CandidateLifecycle.STATIC_VALID,
                )
            rejected = repository.get_candidate("repair-rejected")
            repository.transition_candidate(
                rejected.candidate_id,
                CandidateLifecycle.STATIC_VALID,
                CandidateLifecycle.REJECTED,
                expected_generation=rejected.generation,
                error_class="candidate",
                error_code="actorops_discovery_validation_rejected",
            )
        repair = repository.resilience.ensure_repair(
            route_id=route_id,
            source_id=source_id,
            origin_job_id="repair-rotation",
            trigger_code="actorops_insufficient_stable_paths",
        )
        discovering = repository.resilience.advance_repair(str(repair["repair_id"]))
        discovery_id = str(discovering["discovery_id"])
        with repository.transaction():
            repository.discovery.link_candidate(
                discovery_id,
                candidate_id="repair-rejected",
                rank=0,
                status="accepted",
                rejection_code=None,
            )
            repository.discovery.link_candidate(
                discovery_id,
                candidate_id="repair-usable",
                rank=1,
                status="accepted",
                rejection_code=None,
            )
        _terminal_discovery(
            repository, discovery_id, DiscoveryStatus.COMPLETED
        )
        assert repository.resilience.wake_repairs_after_discovery(discovery_id) == 1

        awaiting = repository.resilience.advance_repair(str(repair["repair_id"]))

        assert awaiting["status"] == "awaiting_probe"
        assert awaiting["candidate_id"] == "repair-usable"
    finally:
        store.close()


def test_failed_discovery_is_cleared_before_a_new_repair_round(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _repository(tmp_path)
    try:
        store.create_user(
            workspace_id=DEFAULT_WORKSPACE_ID,
            username="repair-retry-owner",
            password="safe-test-password",
            role="owner",
        )
        with repository.transaction():
            repository.connection.execute(
                """UPDATE actor_candidates_v2
                      SET lifecycle='disabled', assignment_role='inactive',
                          priority=NULL, generation=generation+1
                    WHERE candidate_id='candidate-1'"""
            )
        repair = repository.resilience.ensure_repair(
            route_id=route_id,
            source_id=source_id,
            origin_job_id="repair-discovery-retry",
            trigger_code="actorops_insufficient_stable_paths",
        )
        discovering = repository.resilience.advance_repair(str(repair["repair_id"]))
        first_discovery_id = str(discovering["discovery_id"])
        _terminal_discovery(
            repository, first_discovery_id, DiscoveryStatus.FAILED
        )
        repository.resilience.wake_repairs_after_discovery(first_discovery_id)

        blocked = repository.resilience.advance_repair(str(repair["repair_id"]))

        assert blocked["status"] == "blocked"
        assert blocked["discovery_id"] is None
        assert blocked["candidate_id"] is None
        assert blocked["attempt_count"] == 1
        unchanged = repository.resilience.ensure_repair(
            route_id=route_id,
            source_id=source_id,
            origin_job_id="repair-discovery-retry-repeat",
            trigger_code="actorops_insufficient_stable_paths",
        )
        assert unchanged["attempt_count"] == 1
        assert unchanged["next_attempt_at"] == blocked["next_attempt_at"]
        with repository.transaction():
            repository.connection.execute(
                """UPDATE actor_route_repairs_v2 SET next_attempt_at=?
                    WHERE repair_id=?""",
                (
                    (datetime.now(timezone.utc) - timedelta(minutes=1)).isoformat(),
                    repair["repair_id"],
                ),
            )

        restarted = repository.resilience.advance_repair(str(repair["repair_id"]))

        assert restarted["status"] == "discovering"
        assert restarted["discovery_id"] != first_discovery_id
        assert repository.discovery.get(str(restarted["discovery_id"]))["status"] == "queued"
        _terminal_discovery(
            repository,
            str(restarted["discovery_id"]),
            DiscoveryStatus.FAILED,
        )
        second_block = repository.resilience.advance_repair(
            str(repair["repair_id"])
        )
        remaining = datetime.fromisoformat(
            str(second_block["next_attempt_at"])
        ) - datetime.now(timezone.utc)
        assert second_block["attempt_count"] == 2
        assert timedelta(minutes=119) < remaining <= timedelta(minutes=120)
    finally:
        store.close()
