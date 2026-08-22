from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from src.apify_actor_identity import source_target_fingerprint
from src.services.actorops.binding_service import (
    ActorOpsBindingError,
    ActorOpsBindingService,
)
from src.services.actorops.domain import (
    AssignmentRole,
    AttemptStatus,
    CandidateLifecycle,
)
from src.services.apify_actor_source_runtime import (
    with_actorops_runtime_profiles,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from tests.test_actorops_v1_retirement_boundary import (
    install_actorops_v1_deny_authorizer,
)


def _store(tmp_path: Path) -> ServiceStore:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    return store


def _source(
    store: ServiceStore,
    *,
    source_type: str,
    config: dict[str, object],
    enabled: bool = True,
) -> str:
    return store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type=source_type,
        display_name="Binding source",
        config=config,
        source_key=f"binding:{source_type}:{config}",
        enabled=enabled,
    )


def test_ensure_creates_only_pending_v2_binding_and_disables_source(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    source_id = _source(
        store,
        source_type="apify_social",
        config={"platform": "x", "kind": "profile", "target": "@OpenAI"},
    )
    uninstall = install_actorops_v1_deny_authorizer(store.connect())
    try:
        binding = ActorOpsBindingService(
            store, workspace_id=DEFAULT_WORKSPACE_ID
        ).ensure(source_id)
    finally:
        uninstall()

    assert binding.status == "pending"
    assert binding.binding_version == 1
    assert store.get_source(source_id)["enabled"] is False
    assert store.connect().execute(
        "SELECT COUNT(*) FROM actor_source_bindings_v2 WHERE source_id=?",
        (source_id,),
    ).fetchone()[0] == 1


def test_pending_binding_cannot_fall_through_to_fixed_actor_runtime(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    source_id = _source(
        store,
        source_type="apify_social",
        config={"platform": "x", "kind": "profile", "target": "OpenAI"},
    )
    ActorOpsBindingService(
        store, workspace_id=DEFAULT_WORKSPACE_ID
    ).ensure(source_id)
    store.update_source(source_id, enabled=True)
    record = {
        **store.get_source(source_id),
        "source_id": source_id,
    }

    projected = with_actorops_runtime_profiles(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        records=(record,),
    )[0]

    assert "profile_id" not in projected["config"]
    assert projected["config"]["enabled"] is False


def test_pending_youtube_binding_cannot_run_rss_fallback(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    source_id = _source(
        store,
        source_type="rss",
        config={
            "url": (
                "https://www.youtube.com/feeds/videos.xml?"
                "channel_id=UCabcdefghijklmnopqrstuv"
            )
        },
    )
    ActorOpsBindingService(
        store, workspace_id=DEFAULT_WORKSPACE_ID
    ).ensure(source_id)
    store.update_source(source_id, enabled=True)
    record = {**store.get_source(source_id), "source_id": source_id}

    projected = with_actorops_runtime_profiles(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        records=(record,),
    )[0]

    assert projected["type"] == "rss"
    assert projected["config"]["enabled"] is False


def test_equivalent_target_is_idempotent_but_real_rebind_is_atomic(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    source_id = _source(
        store,
        source_type="apify_social",
        config={"platform": "instagram", "kind": "profile", "target": "OpenAI"},
    )
    service = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    first = service.ensure(source_id)
    store.update_source(
        source_id,
        config={
            "platform": "instagram",
            "kind": "profile",
            "target": "https://www.instagram.com/openai/",
            "fetch_limit": 40,
        },
    )
    same = service.rebind(source_id)
    assert same.binding_version == first.binding_version

    with service.repository.transaction():
        service.repository.create_candidate(
            candidate_id="rebind-candidate",
            route_id=first.route_id,
            actor_id="publisher/rebind",
            publisher="publisher",
            build_id="rebind-build",
            build_number="1.0.0",
            manifest_json="{}",
            manifest_hash="a" * 64,
            input_schema_hash="b" * 64,
            output_schema_hash="c" * 64,
            lifecycle=CandidateLifecycle.STATIC_VALID,
        )
    store.connect().execute(
        """UPDATE actor_source_bindings_v2
           SET preferred_candidate_id='rebind-candidate',
               last_known_good_candidate_id='rebind-candidate',
               watermark_latest_published_at='2026-01-01T00:00:00+00:00',
               watermark_item_id_hash='abc'
           WHERE source_id=?""",
        (source_id,),
    )
    store.connect().commit()
    store.update_source(
        source_id,
        config={"platform": "instagram", "kind": "profile", "target": "another"},
    )
    changed = service.rebind(source_id)
    row = store.connect().execute(
        "SELECT * FROM actor_source_bindings_v2 WHERE source_id=?", (source_id,)
    ).fetchone()
    assert changed.binding_version == first.binding_version + 1
    assert changed.status == "pending"
    assert row["preferred_candidate_id"] is None
    assert row["last_known_good_candidate_id"] is None
    assert row["watermark_latest_published_at"] is None
    assert row["watermark_item_id_hash"] is None
    assert store.get_source(source_id)["enabled"] is False


def test_disable_reenable_and_ready_promotion_have_monotonic_versions(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    source_id = _source(
        store,
        source_type="rss",
        config={
            "url": (
                "https://www.youtube.com/feeds/videos.xml?"
                "channel_id=UCabcdefghijklmnopqrstuv"
            )
        },
    )
    service = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    pending = service.ensure(source_id)
    ready = service.verify(
        source_id,
        expected_binding_version=pending.binding_version,
        expected_target_fingerprint=pending.target_fingerprint,
    )
    assert ready.status == "ready"
    assert ready.binding_version == pending.binding_version
    service.enable_ready(source_id)
    assert store.get_source(source_id)["enabled"] is True
    with service.repository.transaction():
        service.repository.create_candidate(
            candidate_id="disable-audit-candidate",
            route_id=ready.route_id,
            actor_id="publisher/disable-audit",
            publisher="publisher",
            build_id="disable-build",
            build_number="1.0.0",
            manifest_json="{}",
            manifest_hash="d" * 64,
            input_schema_hash="e" * 64,
            output_schema_hash="f" * 64,
            lifecycle=CandidateLifecycle.STATIC_VALID,
        )
        service.repository.connection.execute(
            """UPDATE actor_source_bindings_v2
               SET preferred_candidate_id='disable-audit-candidate',
                   last_known_good_candidate_id='disable-audit-candidate',
                   watermark_latest_published_at='2026-08-01T00:00:00+00:00'
               WHERE source_id=?""",
            (source_id,),
        )

    disabled = service.disable(source_id)
    repeated = service.disable(source_id)
    assert disabled.status == "disabled"
    assert disabled.binding_version == ready.binding_version + 1
    assert repeated.binding_version == disabled.binding_version
    assert store.get_source(source_id)["enabled"] is False
    audit = store.connect().execute(
        """SELECT preferred_candidate_id, last_known_good_candidate_id,
                  watermark_latest_published_at
           FROM actor_source_bindings_v2 WHERE source_id=?""",
        (source_id,),
    ).fetchone()
    assert audit["preferred_candidate_id"] is None
    assert audit["last_known_good_candidate_id"] == "disable-audit-candidate"
    assert audit["watermark_latest_published_at"] == (
        "2026-08-01T00:00:00+00:00"
    )

    pending_again = service.reenable(source_id)
    assert pending_again.status == "pending"
    assert pending_again.binding_version == disabled.binding_version + 1
    assert store.get_source(source_id)["enabled"] is False


def test_verify_rejects_stale_or_non_v2_evidence(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source_id = _source(
        store,
        source_type="apify_social",
        config={"platform": "x", "kind": "profile", "target": "openai"},
    )
    service = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    binding = service.ensure(source_id)
    with pytest.raises(ActorOpsBindingError, match="evidence_missing"):
        service.verify(
            source_id,
            expected_binding_version=binding.binding_version,
            expected_target_fingerprint=binding.target_fingerprint,
        )


def test_verify_accepts_only_settled_current_v2_probe(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source_id = _source(
        store,
        source_type="apify_social",
        config={"platform": "x", "kind": "profile", "target": "openai"},
    )
    service = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    binding = service.ensure(source_id)
    repository = service.repository
    with repository.transaction():
        repository.create_candidate(
            candidate_id="binding-probe-candidate",
            route_id=binding.route_id,
            actor_id="publisher/binding-probe",
            publisher="publisher",
            build_id="binding-probe-build",
            build_number="1.0.0",
            manifest_json="{}",
            manifest_hash="a" * 64,
            input_schema_hash="b" * 64,
            output_schema_hash="c" * 64,
            lifecycle=CandidateLifecycle.CERTIFIED,
        )
        repository.assign_candidate(
            binding.route_id,
            "binding-probe-candidate",
            AssignmentRole.ACTIVE,
            priority=0,
            expected_route_generation=repository.get_route(binding.route_id).generation,
            expected_candidate_generation=1,
        )
        repository.create_attempt(
            attempt_id="binding-probe-attempt",
            idempotency_key="binding-probe-idempotency",
            route_id=binding.route_id,
            source_id=source_id,
            candidate_id="binding-probe-candidate",
            kind="probe",
            attempt_group_id="binding-probe-group",
            attempt_index=0,
            route_generation=repository.get_route(binding.route_id).generation,
            binding_version=binding.binding_version,
            target_fingerprint="f" * 64,
            reserved_usd=0.01,
        )
        repository.transition_attempt(
            "binding-probe-attempt",
            AttemptStatus.CREATED,
            AttemptStatus.STARTING,
        )
        repository.transition_attempt(
            "binding-probe-attempt",
            AttemptStatus.STARTING,
            AttemptStatus.REGISTERED,
        )
        repository.complete_attempt(
            "binding-probe-attempt",
            status=AttemptStatus.SUCCEEDED,
            semantic_outcome="valid_nonempty",
            actual_cost_usd=0.01,
            cost_final=False,
        )

    with pytest.raises(ActorOpsBindingError, match="evidence_missing"):
        service.verify(
            source_id,
            expected_binding_version=binding.binding_version,
            expected_target_fingerprint=binding.target_fingerprint,
        )
    with repository.transaction():
        repository.connection.execute(
            """UPDATE actor_attempts_v2 SET cost_final=1
               WHERE attempt_id='binding-probe-attempt'"""
        )
    with pytest.raises(ActorOpsBindingError, match="evidence_missing"):
        service.verify(
            source_id,
            expected_binding_version=binding.binding_version,
            expected_target_fingerprint=binding.target_fingerprint,
        )
    with repository.transaction():
        repository.connection.execute(
            """UPDATE actor_attempts_v2 SET target_fingerprint=?
               WHERE attempt_id='binding-probe-attempt'""",
            (binding.target_fingerprint,),
        )
    ready = service.verify(
        source_id,
        expected_binding_version=binding.binding_version,
        expected_target_fingerprint=binding.target_fingerprint,
    )
    assert ready.status == "ready"
    assert ready.binding_version == binding.binding_version
    with pytest.raises(ActorOpsBindingError, match="binding_conflict"):
        service.verify(
            source_id,
            expected_binding_version=binding.binding_version + 1,
            expected_target_fingerprint=binding.target_fingerprint,
        )


def test_execution_state_never_maps_disabled_route_to_v1(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source_id = _source(
        store,
        source_type="rss",
        config={
            "url": (
                "https://www.youtube.com/feeds/videos.xml?"
                "channel_id=UCabcdefghijklmnopqrstuv"
            )
        },
    )
    service = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    binding = service.ensure(source_id)
    service.verify(
        source_id,
        expected_binding_version=binding.binding_version,
        expected_target_fingerprint=source_target_fingerprint(
            DEFAULT_WORKSPACE_ID,
            binding.route_id,
            store.get_source(source_id)["config"]["url"],
            platform="youtube",
        ),
    )
    state = service.execution_state(source_id)
    assert state.allowed is True
    assert state.execution_mode == "native_fallback"
    assert state.reason == "actorops_v2_route_disabled_native_fallback"
    assert store.connect().execute(
        "SELECT COUNT(*) FROM actor_attempts_v2 WHERE source_id=?", (source_id,)
    ).fetchone()[0] == 0


def test_authorizer_rejects_historical_table_but_allows_shared_ledger(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    uninstall = install_actorops_v1_deny_authorizer(store.connect())
    try:
        with pytest.raises(sqlite3.DatabaseError, match="prohibited|not authorized"):
            store.connect().execute("SELECT * FROM apify_source_route_bindings").fetchall()
        store.connect().execute("SELECT * FROM apify_actor_runs LIMIT 1").fetchall()
        store.connect().execute("SELECT * FROM actor_routes_v2 LIMIT 1").fetchall()
    finally:
        uninstall()
