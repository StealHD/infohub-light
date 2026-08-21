from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass
from pathlib import Path

from scripts import migrate_actorops_v2_operator_controls as operator_migration
from scripts.migrate_actorops_v2_operator_controls import migrate
from src.apify_actor_identity import source_target_fingerprint
from src.services.apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from src.services.actorops.domain import AssignmentRole, AttemptStatus, CandidateLifecycle, ReplacementStatus, RouteKey
from src.services.actorops.ports import NormalizedBatch, ProbePreflightResult, RemoteRunResult, TargetSpec
from src.services.actorops.registry import AdapterRegistry
from src.services.actorops.replacement import ActorOpsReplacementRunner
from src.services.actorops.repository import ActorOpsRepository
from src.services.actorops.store_metadata import normalize_store_metadata
from src.services import worker_actorops_v2_metadata as metadata_worker
from src.services import worker_actorops_v2_replacement as replacement_worker
from src.storage.actorops_v2_operator_schema import migration_marker_exists, schema_shapes_valid
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


class _Adapter:
    route_key = RouteKey("test", "profile", "items")

    def normalize_target(self, config):
        return TargetSpec(canonical_url=f"https://example.com/{config['target']}", handle=str(config["target"]))

    def build_actor_input(self, target, manifest, window):
        return {"target": target.handle, "limit": window.max_items}

    def validate_output(self, rows, target, manifest, window):
        return NormalizedBatch((object(),), "valid_nonempty")

    async def fetch_native_fallback(self, target, window):
        raise AssertionError("replacement does not use native fallback")


@dataclass
class _Catalog:
    async def verify(self, candidate, *, max_charge_usd):
        return ProbePreflightResult(True)


class _Remote:
    async def execute(self, request, events):
        events.starting(secret_ref_id="ref", secret_version=1, pool_generation=1)
        events.registered(remote_run_id="replacement-run", dataset_id="dataset")
        events.running()
        return RemoteRunResult(({"id": "one"},), "replacement-run", "dataset", 0.01, True)


def _manifest(actor_id: str) -> str:
    return json.dumps({
        "version": 1, "actor_id": actor_id, "build_number": "1.0.0",
        "input": {"target": {"$ref": "target.handle"}},
        "output": {
            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
            "published_at": {"pointers": ["/createdAt"], "transforms": ["parse_datetime"]},
            "text": {"pointers": ["/text"], "transforms": ["to_string"]},
            "author_handle": {"pointers": ["/author"], "transforms": ["to_string"]},
        },
        "semantics": {"identity": {"output_field": "author_handle", "target_ref": "target.handle", "match": "handle"}, "url_host_allowlist": ["example.com"]},
    })


def _setup(tmp_path: Path):
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    route_id = str(connection.execute("SELECT route_id FROM actor_routes_v2 WHERE platform='x'").fetchone()[0])
    connection.execute("UPDATE actor_routes_v2 SET platform='test', per_run_cap_usd=0.05 WHERE route_id=?", (route_id,))
    source_id = store.create_source(workspace_id=DEFAULT_WORKSPACE_ID, scope="workspace", owner_user_id=None, source_type="apify_social", display_name="Test source", config={"target": "openai"})
    fingerprint = source_target_fingerprint(DEFAULT_WORKSPACE_ID, route_id, "openai", platform="test")
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        connection.execute(
            """INSERT INTO actor_source_bindings_v2 (binding_id,workspace_id,source_id,route_id,target_fingerprint,status,binding_version,source_v1_generation,created_at,updated_at)
               VALUES ('operator-binding',?,?,?,?, 'ready',1,1,'2026-08-21T00:00:00+00:00','2026-08-21T00:00:00+00:00')""",
            (DEFAULT_WORKSPACE_ID, source_id, route_id, fingerprint),
        )
        for candidate_id, lifecycle in (("active", CandidateLifecycle.CERTIFIED), ("replacement", CandidateLifecycle.STATIC_VALID)):
            manifest = _manifest(f"publisher/{candidate_id}")
            repository.create_candidate(candidate_id=candidate_id, route_id=route_id, actor_id=f"publisher/{candidate_id}", publisher="publisher", build_id=f"build-{candidate_id}", build_number="1.0.0", manifest_json=manifest, manifest_hash=actor_manifest_hash(parse_actor_manifest(manifest)), input_schema_hash="a" * 64, output_schema_hash="b" * 64, lifecycle=lifecycle)
        repository.assign_candidate(route_id, "active", AssignmentRole.ACTIVE, priority=0, expected_route_generation=1, expected_candidate_generation=1)
        for candidate_id in ("active", "replacement"):
            repository.operator.upsert_metadata(candidate_id, normalize_store_metadata({"actorId": f"publisher/{candidate_id}", "title": f"{candidate_id} title", "username": "publisher", "stats": {"rating": 4.5, "reviewCount": 10, "totalUsers": 100}, "pricingInfos": [{"pricingModel": "PAY_PER_EVENT", "pricePerUnitUsd": 0.01, "unitName": "result"}]}, fallback_slug=f"publisher/{candidate_id}"))
    return store, repository, route_id, source_id


def test_fresh_store_installs_global_28_and_normalizes_safe_store_metadata(tmp_path: Path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    assert migration_marker_exists(store.connect()) and schema_shapes_valid(store.connect())
    metadata = normalize_store_metadata({"actorId": "apify/instagram-api-scraper", "title": "Instagram API Scraper", "description": "safe", "username": "apify", "isApifyMaintained": True, "stats": {"actorReviewRating": 3.2, "actorReviewCount": 35, "bookmarkCount": 296, "totalUsers": 18_000, "monthlyActiveUsers": 1_000}, "pricingInfos": [{"pricingModel": "PAY_PER_EVENT", "pricePerUnitUsd": 0.0014, "unitName": "result", "unexpected": "drop"}]}, fallback_slug="fallback/actor")
    assert metadata.actor_slug == "apify/instagram-api-scraper"
    assert metadata.rating == 3.2 and metadata.bookmark_count == 296
    assert metadata.pricing == ({"pricingModel": "PAY_PER_EVENT", "pricePerUnitUsd": 0.0014, "unitName": "result"},)


def test_global_28_migration_is_explicit_and_repeatable(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    connection.execute("DROP TABLE actor_replacement_plans_v2")
    connection.execute("DROP TABLE actor_candidate_store_metadata_v2")
    connection.execute("DELETE FROM schema_migrations WHERE version=28")
    connection.commit()
    store.close()
    statements: list[str] = []
    original_connect = operator_migration._connect

    def traced_connect(path, *, read_only):
        result = original_connect(path, read_only=read_only)
        result.set_trace_callback(statements.append)
        return result

    operator_migration._connect = traced_connect
    try:
        assert migrate(data_dir, apply=False)["status"] == "migration_required"
    finally:
        operator_migration._connect = original_connect
    applied = migrate(data_dir, apply=True)
    assert applied["status"] == "applied" and applied["backup_mode"] == "0o600"
    assert migrate(data_dir, apply=True)["status"] == "already_migrated"
    compact = "\n".join(statements).replace(" ", "")
    assert "version=25" not in compact and "version=27" not in compact


def test_existing_exact_settled_proofs_make_replacement_ready_without_new_probe(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    candidate = repository.get_candidate("replacement")
    binding = repository.operator.binding_set(route_id)[0]
    with repository.transaction():
        candidate = repository.record_candidate_outcome(candidate.candidate_id, expected_generation=candidate.generation, succeeded=True)
        candidate = repository.transition_candidate(candidate.candidate_id, CandidateLifecycle.STATIC_VALID, CandidateLifecycle.PROBATIONARY, expected_generation=candidate.generation)
        repository.create_attempt(
            attempt_id="existing-proof", idempotency_key="existing-proof-key", route_id=route_id,
            source_id=source_id, candidate_id=candidate.candidate_id, kind="probe",
            attempt_group_id="earlier-plan", attempt_index=1, route_generation=repository.get_route(route_id).generation,
            binding_version=binding[1], target_fingerprint=binding[2], reserved_usd=0.01,
        )
        repository.update_attempt_start("existing-proof", expected_generation=1, secret_ref_id="ref", secret_version=1, pool_generation=1)
        repository.register_attempt_run("existing-proof", expected_generation=2, remote_run_id="earlier-run", dataset_id="dataset")
        repository.transition_attempt("existing-proof", AttemptStatus.REGISTERED, AttemptStatus.RUNNING, expected_generation=3)
        repository.complete_attempt("existing-proof", status=AttemptStatus.SUCCEEDED, semantic_outcome="valid_nonempty", actual_cost_usd=0.01, cost_final=True)
        plan = repository.operator.create_plan(
            plan_id="existing-proof-plan", route_id=route_id, target_assignment=AssignmentRole.ACTIVE,
            target_priority=0, proposed_candidate_id=candidate.candidate_id,
            idempotency_key="existing-proof-replacement-key", created_by_user_id="owner",
            per_probe_cap_usd=0.05, total_cap_usd=0.05,
        )
        plan = repository.operator.transition_plan(plan.plan_id, current=plan.status, target=ReplacementStatus.AUTHORIZED, expected_generation=plan.generation)
    registry = AdapterRegistry()
    registry.register(_Adapter())
    result = asyncio.run(ActorOpsReplacementRunner(repository, registry, _Remote(), _Catalog()).run(plan.plan_id, {source_id: {"target": "openai"}}))
    assert result["status"] == "ready"
    assert store.connect().execute("SELECT COUNT(*) FROM actor_attempts_v2 WHERE kind='probe'").fetchone()[0] == 1
    store.close()


def test_metadata_refresh_only_reads_current_active_or_standby_candidates(tmp_path: Path, monkeypatch) -> None:
    store, _repository, route_id, _source_id = _setup(tmp_path)
    seen: list[str] = []

    class _StoreCatalog:
        async def store_metadata(self, candidate):
            seen.append(candidate.candidate_id)
            return normalize_store_metadata(
                {"actorId": candidate.actor_id, "title": candidate.candidate_id},
                fallback_slug=candidate.actor_id,
            )

    monkeypatch.setattr(metadata_worker, "_catalog", lambda *_args: _StoreCatalog())
    result = asyncio.run(metadata_worker._refresh(
        workspace_id=DEFAULT_WORKSPACE_ID, route_id=route_id, store=store, data_dir=str(tmp_path),
    ))

    assert result == {"refreshed": 1, "failed": 0}
    assert seen == ["active"]
    store.close()


def test_replacement_uses_existing_validation_key_purpose(tmp_path: Path, monkeypatch) -> None:
    store, repository, route_id, _source_id = _setup(tmp_path)
    with repository.transaction():
        plan = repository.operator.create_plan(
            plan_id="purpose-plan", route_id=route_id, target_assignment=AssignmentRole.ACTIVE,
            target_priority=0, proposed_candidate_id="replacement",
            idempotency_key="purpose-plan-idempotency", created_by_user_id="owner",
            per_probe_cap_usd=0.05, total_cap_usd=0.05,
        )
        repository.operator.transition_plan(
            plan.plan_id, current=plan.status, target=ReplacementStatus.AUTHORIZED,
            expected_generation=plan.generation,
        )
    captured: dict[str, object] = {}

    def unavailable_coordinator(*_args, **kwargs):
        captured.update(kwargs)
        return None

    monkeypatch.setattr(replacement_worker, "apify_coordinator_for_workspace", unavailable_coordinator)
    result = asyncio.run(replacement_worker._run_plan(
        {"workspace_id": DEFAULT_WORKSPACE_ID, "payload_json": {"plan_id": plan.plan_id}},
        str(tmp_path), store,
    ))

    assert captured["purpose"] == "validation"
    assert result["error_code"] == "actorops_replacement_credential_unavailable"
    store.close()


def test_explicit_replacement_runs_one_probe_then_applies_without_feed_updates(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    with repository.transaction():
        plan = repository.operator.create_plan(plan_id="replacement-plan", route_id=route_id, target_assignment=AssignmentRole.ACTIVE, target_priority=0, proposed_candidate_id="replacement", idempotency_key="replacement-idempotency-key", created_by_user_id="owner", per_probe_cap_usd=0.05, total_cap_usd=0.05)
        plan = repository.operator.transition_plan(plan.plan_id, current=plan.status, target=ReplacementStatus.AUTHORIZED, expected_generation=plan.generation)
    registry = AdapterRegistry()
    registry.register(_Adapter())
    runner = ActorOpsReplacementRunner(repository, registry, _Remote(), _Catalog())
    first = asyncio.run(runner.run(plan.plan_id, {source_id: {"target": "openai"}}))
    assert first["status"] == "proved"
    second = asyncio.run(runner.run(plan.plan_id, {source_id: {"target": "openai"}}))
    assert second["status"] == "ready"
    ready = repository.operator.get_plan(plan.plan_id)
    with repository.transaction():
        applied = repository.operator.apply_plan(ready.plan_id, expected_generation=ready.generation)
    assert applied.status.value == "applied"
    assert repository.get_candidate("replacement").assignment_role is AssignmentRole.ACTIVE
    assert repository.get_candidate("active").assignment_role is AssignmentRole.INACTIVE
    assert store.connect().execute("SELECT COUNT(*) FROM actor_attempts_v2 WHERE kind='probe'").fetchone()[0] == 1
    store.close()
