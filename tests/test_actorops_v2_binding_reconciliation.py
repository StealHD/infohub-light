from __future__ import annotations

import json
from pathlib import Path

from src.services.apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from src.services.actorops.binding_reconciliation import ActorOpsBindingReconciler
from src.services.actorops.binding_service import ActorOpsBindingService
from src.services.actorops.domain import AssignmentRole, CandidateLifecycle
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _store(tmp_path: Path) -> ServiceStore:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    return store


def _manifest(actor_id: str) -> str:
    return json.dumps(
        {
            "version": 1,
            "actor_id": actor_id,
            "build_number": "1.0.0",
            "input": {"username": {"$ref": "target.handle"}},
            "output": {
                "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
                "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
                "published_at": {"pointers": ["/createdAt"], "transforms": ["parse_datetime"]},
                "text": {"pointers": ["/text"], "transforms": ["to_string"]},
                "author_handle": {"pointers": ["/username"], "transforms": ["to_string"]},
            },
            "semantics": {
                "identity": {
                    "output_field": "author_handle",
                    "target_ref": "target.handle",
                    "match": "handle",
                },
                "url_host_allowlist": ["instagram.com"],
            },
        },
        sort_keys=True,
    )


def _instagram_source(store: ServiceStore, name: str) -> str:
    return store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name=name,
        config={"platform": "instagram", "kind": "profile", "target": name},
        source_key=f"instagram:{name}",
        enabled=False,
    )


def _owner_id(store: ServiceStore) -> str:
    return str(
        store.create_user(
            workspace_id=DEFAULT_WORKSPACE_ID,
            username="owner",
            password="test-password",
            role="owner",
        )["id"]
    )


def test_local_candidate_proof_auto_verifies_and_enables_an_active_subscription(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    source_id = _instagram_source(store, "sooyaaa__")
    bindings = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    binding = bindings.ensure(source_id)
    manifest = _manifest("publisher/instagram-ready")
    with bindings.repository.transaction():
        route = bindings.repository.get_route(binding.route_id)
        bindings.repository.connection.execute(
            "UPDATE actor_routes_v2 SET runtime_mode='active' WHERE route_id=?",
            (binding.route_id,),
        )
        bindings.repository.create_candidate(
            candidate_id="instagram-ready",
            route_id=binding.route_id,
            actor_id="publisher/instagram-ready",
            publisher="publisher",
            build_id="build-instagram-ready",
            build_number="1.0.0",
            manifest_json=manifest,
            manifest_hash=actor_manifest_hash(parse_actor_manifest(manifest)),
            input_schema_hash="a" * 64,
            output_schema_hash="b" * 64,
            lifecycle=CandidateLifecycle.CERTIFIED,
        )
        bindings.repository.assign_candidate(
            binding.route_id,
            "instagram-ready",
            AssignmentRole.ACTIVE,
            priority=0,
            expected_route_generation=route.generation,
            expected_candidate_generation=1,
        )
    store.create_subscription(
        user_id=_owner_id(store), source_id=source_id, enabled=True
    )

    result = ActorOpsBindingReconciler(
        store, workspace_id=DEFAULT_WORKSPACE_ID
    ).reconcile_source(source_id)

    assert result.state == "enabled"
    assert result.proof_kind == "deterministic"
    assert result.binding_promoted is True
    assert result.source_activated is True
    assert bindings.repository.get_binding(source_id).status == "ready"
    assert store.get_source(source_id)["enabled"] is True
    assert store.connect().execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0


def test_missing_local_proof_keeps_subscribed_source_preparing_without_attempt(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    source_id = _instagram_source(store, "pendingprofile")
    ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID).ensure(source_id)
    store.create_subscription(
        user_id=_owner_id(store), source_id=source_id, enabled=True
    )

    result = ActorOpsBindingReconciler(
        store, workspace_id=DEFAULT_WORKSPACE_ID
    ).reconcile_source(source_id)

    assert result.state == "preparing"
    assert result.reason == "actorops_v2_binding_no_runnable_candidate"
    assert result.binding_promoted is False
    assert store.get_source(source_id)["enabled"] is False
    assert store.connect().execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0


def test_explicitly_disabled_binding_is_never_auto_enabled(tmp_path: Path) -> None:
    store = _store(tmp_path)
    source_id = _instagram_source(store, "disabledprofile")
    bindings = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    bindings.ensure(source_id)
    bindings.disable(source_id)
    store.update_source(source_id, enabled=True)
    store.create_subscription(
        user_id=_owner_id(store), source_id=source_id, enabled=True
    )

    result = ActorOpsBindingReconciler(
        store, workspace_id=DEFAULT_WORKSPACE_ID
    ).reconcile_source(source_id)

    assert result.state == "disabled"
    assert result.reason == "actorops_v2_binding_disabled"
    assert store.get_source(source_id)["enabled"] is False


def test_workspace_reconciliation_is_bounded_to_one_hundred_sources(
    tmp_path: Path,
) -> None:
    store = _store(tmp_path)
    owner_id = _owner_id(store)
    bindings = ActorOpsBindingService(store, workspace_id=DEFAULT_WORKSPACE_ID)
    for index in range(101):
        source_id = _instagram_source(store, f"queuedprofile{index}")
        bindings.ensure(source_id)
        store.create_subscription(user_id=owner_id, source_id=source_id, enabled=True)

    summary = ActorOpsBindingReconciler(
        store, workspace_id=DEFAULT_WORKSPACE_ID
    ).reconcile_workspace(limit=1_000)

    assert summary.checked_count == 100
    assert summary.verified_binding_count == 0
    assert summary.enabled_source_count == 0
    assert summary.blocked_binding_count == 100
