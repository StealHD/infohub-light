from __future__ import annotations

import asyncio
import hashlib
import json
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path

import pytest

from scripts import migrate_actorops_v2_operator_controls as operator_migration
from scripts.migrate_actorops_v2_operator_controls import migrate
from src.apify_actor_identity import source_target_fingerprint
from src.services.apify_actor_manifest import (
    ActorManifestError,
    actor_manifest_hash,
    parse_actor_manifest,
)
from src.services.actorops.domain import (
    AssignmentRole,
    AttemptStatus,
    CandidateLifecycle,
    FailureClass,
    ReplacementStatus,
    RouteKey,
)
from src.services.actorops.dataset_adaptation import DatasetAdaptationService
from src.services.actorops.ports import (
    DiscoveryAiResult, DiscoveryMapping, DiscoveryRevision, NormalizedBatch,
    ProbePreflightResult, RemoteRunResult, TargetSpec,
)
from src.services.actorops.registry import AdapterRegistry
from src.services.actorops.input_plan import create_input_plan
from src.services.actorops.replacement import ActorOpsReplacementRunner
from src.services.actorops.replacement_revalidation import (
    ReplacementRevalidationError,
    revalidate_failed_replacement,
)
from src.services.actorops.replacement_preview import (
    check_replacement_preview,
    settle_replacement_preview_failure,
)
from src.services.actorops.repository import ActorOpsConflict, ActorOpsRepository
from src.services.actorops.runtime import ActorOpsRuntimeError
from src.services.actorops.runtime_candidate_health import candidate_operational_states
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
    async def verify_candidate(self, candidate, *, max_charge_usd):
        return ProbePreflightResult(True)


class _Remote:
    def __init__(self):
        self.requests = []

    async def execute(self, request, events):
        self.requests.append(request)
        events.starting(secret_ref_id="ref", secret_version=1, pool_generation=1)
        events.registered(remote_run_id="replacement-run", dataset_id="dataset")
        events.running()
        return RemoteRunResult(({"id": "one"},), "replacement-run", "dataset", 0.01, True)


class _RejectingRemote(_Remote):
    async def execute(self, request, events):
        self.requests.append(request)
        events.starting(secret_ref_id="ref", secret_version=1, pool_generation=1)
        raise ActorOpsRuntimeError(
            "apify_actor_start_rejected",
            failure_class=FailureClass.CANDIDATE,
            proven_no_start=True,
        )


class _IncompatibleAdapter(_Adapter):
    def build_actor_input(self, target, manifest, window):
        raise ValueError("candidate input contract is incompatible")


class _ManifestErrorAdapter(_Adapter):
    def build_actor_input(self, target, manifest, window):
        raise ActorManifestError(
            "apify_manifest_input_invalid",
            "candidate input cannot be rendered",
        )


class _OutputFailureAdapter(_Adapter):
    def validate_output(self, rows, target, manifest, window):
        raise ActorManifestError(
            "apify_actor_contract_mismatch", "old local mapping rule failed"
        )


class _NoEvidenceAdapter(_Adapter):
    def validate_output(self, rows, target, manifest, window):
        return NormalizedBatch((), "valid_empty")


class _DatasetReader:
    def __init__(self):
        self.calls = 0

    async def read_dataset(self, dataset_id, *, max_items):
        self.calls += 1
        assert dataset_id == "dataset" and max_items == 4
        return ({"id": "one"},)


class _NestedAdaptationAdapter(_Adapter):
    def map_discovery_manifest(self, revision):
        return DiscoveryMapping(None, "actorops_discovery_mapping_pending")

    def validate_output(self, rows, target, manifest, window):
        parsed = parse_actor_manifest(manifest.manifest_json)
        if parsed.row_extraction is None:
            raise ActorManifestError(
                "apify_actor_contract_mismatch", "flat mapping cannot read rows"
            )
        assert rows and rows[0]["item"]["id"] == "one"
        return NormalizedBatch((object(),), "valid_nonempty")


class _ObservedCatalog(_Catalog):
    def __init__(self, revision):
        self.revision = revision

    async def get_revision(self, actor_id):
        assert actor_id == self.revision.actor_id
        return self.revision


class _ObservedMapper:
    def __init__(self, manifest):
        self.manifest = manifest
        self.calls = 0

    async def map(self, route_key, revisions):
        self.calls += 1
        assert revisions[0].mapping_feedback == "observed_mapping_failed"
        return DiscoveryAiResult(mappings={
            revisions[0].actor_id: DiscoveryMapping(self.manifest)
        })


class _NestedRemote(_Remote):
    async def execute(self, request, events):
        self.requests.append(request)
        events.starting(secret_ref_id="ref", secret_version=1, pool_generation=1)
        events.registered(remote_run_id="replacement-run", dataset_id="dataset")
        events.running()
        return RemoteRunResult(({
            "results": [{
                "id": "one", "url": "https://example.com/openai/one",
                "createdAt": "2026-08-29T00:00:00Z", "text": "new",
                "author": "openai",
            }],
        },), "replacement-run", "dataset", 0.01, True)


class _TrackingCatalog(_Catalog):
    def __init__(self):
        self.called = False

    async def verify_candidate(self, candidate, *, max_charge_usd):
        self.called = True
        return await super().verify_candidate(
            candidate, max_charge_usd=max_charge_usd
        )


def _manifest(actor_id: str, *, target_ref: str = "target.handle") -> str:
    return json.dumps({
        "version": 1, "actor_id": actor_id, "build_number": "1.0.0",
        "input": {"target": {"$ref": target_ref}},
        "output": {
            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
            "published_at": {"pointers": ["/createdAt"], "transforms": ["parse_datetime"]},
            "text": {"pointers": ["/text"], "transforms": ["to_string"]},
            "author_handle": {"pointers": ["/author"], "transforms": ["to_string"]},
        },
        "semantics": {"identity": {"output_field": "author_handle", "target_ref": "target.handle", "match": "handle"}, "url_host_allowlist": ["example.com"]},
    })


def _setup(tmp_path: Path, *, replacement_target_ref: str = "target.handle"):
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
            """INSERT INTO actor_source_bindings_v2 (binding_id,workspace_id,source_id,route_id,target_fingerprint,status,binding_version,created_at,updated_at)
               VALUES ('operator-binding',?,?,?,?, 'ready',1,'2026-08-21T00:00:00+00:00','2026-08-21T00:00:00+00:00')""",
            (DEFAULT_WORKSPACE_ID, source_id, route_id, fingerprint),
        )
        for candidate_id, lifecycle in (("active", CandidateLifecycle.CERTIFIED), ("replacement", CandidateLifecycle.STATIC_VALID)):
            target_ref = (
                replacement_target_ref
                if candidate_id == "replacement"
                else "target.handle"
            )
            manifest = _manifest(
                f"publisher/{candidate_id}", target_ref=target_ref
            )
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


def test_store_metadata_normalizes_nested_public_event_pricing() -> None:
    metadata = normalize_store_metadata({
        "actorId": "apify/instagram-api-scraper", "title": "Instagram API Scraper",
        "pricingInfos": [{
            "pricingModel": "PAY_PER_EVENT",
            "pricingPerEvent": {"actorChargeEvents": {
                "apify-actor-start": {"eventPriceUsd": 0.005, "isOneTimeEvent": True},
                "apify-default-dataset-item": {
                    "eventTitle": "Dataset item", "isPrimaryEvent": True,
                    "eventTieredPricingUsd": {"FREE": {"tieredEventPriceUsd": 0}, "PAID": {"tieredEventPriceUsd": 0.009}},
                },
            }},
        }],
    }, fallback_slug="apify/instagram-api-scraper")

    assert metadata.pricing == ({
        "pricingModel": "PAY_PER_EVENT", "pricePerRunUsd": 0.014,
        "pricingPeriod": "estimated", "unitName": "run",
    },)


def test_store_metadata_uses_verified_public_slug_for_an_opaque_actor_id(tmp_path: Path) -> None:
    store, repository, _route_id, _source_id = _setup(tmp_path)
    opaque = normalize_store_metadata(
        {"id": "opaqueActorId", "username": "apify", "name": "instagram-api-scraper"},
        fallback_slug="opaqueActorId",
    )
    assert opaque.actor_slug == "apify/instagram-api-scraper"
    with repository.transaction():
        stored = repository.operator.upsert_metadata("replacement", opaque)
    assert stored.actor_slug == "apify/instagram-api-scraper"
    store.close()


@pytest.mark.parametrize(
    ("adapter", "expected_error"),
    [
        (
            _IncompatibleAdapter(),
            "actorops_replacement_input_contract_invalid",
        ),
        (
            _ManifestErrorAdapter(),
            "actorops_replacement_input_contract_invalid",
        ),
    ],
    ids=["value-error", "manifest-error"],
)
def test_replacement_preview_rejects_local_contract_before_catalog_or_paid_facts(
    tmp_path: Path, adapter: _Adapter, expected_error: str,
) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    registry = AdapterRegistry()
    registry.register(adapter)
    catalog = _TrackingCatalog()

    result = asyncio.run(check_replacement_preview(
        store,
        repository,
        registry,
        catalog,
        route_id=route_id,
        candidate_id="replacement",
        max_charge_usd=0.05,
    ))
    settle_replacement_preview_failure(
        repository,
        result,
        route_id=route_id,
        candidate_id="replacement",
        expected_candidate_generation=repository.get_candidate("replacement").generation,
    )

    assert result.allowed is False
    assert result.error_code == expected_error
    assert catalog.called is False
    candidate = repository.get_candidate("replacement")
    assert candidate_operational_states(repository, (candidate,))[
        candidate.candidate_id
    ].confirmed_failure is True
    assert store.connect().execute(
        "SELECT COUNT(*) FROM actor_replacement_plans_v2"
    ).fetchone()[0] == 0
    assert store.connect().execute(
        "SELECT COUNT(*) FROM actor_attempts_v2"
    ).fetchone()[0] == 0
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0] == 0
    assert store.connect().execute(
        "SELECT COUNT(*) FROM actor_route_repairs_v2 WHERE source_id=?",
        (source_id,),
    ).fetchone()[0] == 1
    store.close()


def test_replacement_preview_names_a_missing_native_target_id(
    tmp_path: Path,
) -> None:
    store, repository, route_id, _source_id = _setup(
        tmp_path, replacement_target_ref="target.native_id"
    )
    registry = AdapterRegistry()
    registry.register(_Adapter())
    catalog = _TrackingCatalog()

    result = asyncio.run(check_replacement_preview(
        store,
        repository,
        registry,
        catalog,
        route_id=route_id,
        candidate_id="replacement",
        max_charge_usd=0.05,
    ))

    assert result.error_code == "actorops_replacement_target_native_id_missing"
    assert result.settlement_code == "actorops_v2_candidate_contract_invalid"
    assert catalog.called is False
    store.close()


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


def test_failed_paid_dataset_can_be_revalidated_without_rewriting_cost_or_starting_actor(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    with repository.transaction():
        plan = repository.operator.create_plan(
            plan_id="failed-plan", route_id=route_id,
            target_assignment=AssignmentRole.ACTIVE, target_priority=0,
            proposed_candidate_id="replacement",
            idempotency_key="failed-plan-idempotency", created_by_user_id="owner",
            per_probe_cap_usd=0.05, total_cap_usd=0.05,
        )
        plan = repository.operator.transition_plan(
            plan.plan_id, current=plan.status, target=ReplacementStatus.AUTHORIZED,
            expected_generation=plan.generation,
        )
    failing_registry = AdapterRegistry()
    failing_registry.register(_OutputFailureAdapter())
    failed = asyncio.run(ActorOpsReplacementRunner(
        repository, failing_registry, _Remote(), _Catalog(),
    ).run(plan.plan_id, {source_id: {"target": "openai"}}))
    assert failed["error_code"] == "actorops_replacement_contract_mismatch"
    origin = store.connect().execute(
        "SELECT * FROM actor_attempts_v2 WHERE attempt_group_id='failed-plan'"
    ).fetchone()
    assert origin["status"] == "failed" and origin["actual_cost_usd"] == 0.01

    reader = _DatasetReader()
    registry = AdapterRegistry()
    registry.register(_Adapter())
    failed_plan = repository.operator.get_plan("failed-plan")
    recovered = asyncio.run(revalidate_failed_replacement(
        store, repository, registry, reader, _Catalog(),
        plan_id=failed_plan.plan_id,
        expected_generation=failed_plan.generation,
        idempotency_key="revalidate-failed-plan-key",
        created_by_user_id="owner",
    ))

    assert recovered.plan.status is ReplacementStatus.READY
    assert recovered.proof_count == 1 and reader.calls == 1
    assert repository.get_candidate(recovered.candidate_id).lifecycle is CandidateLifecycle.PROBATIONARY
    unchanged = repository.get_attempt(str(origin["attempt_id"]))
    assert unchanged["status"] == "failed" and unchanged["actual_cost_usd"] == 0.01
    proof = store.connect().execute(
        "SELECT * FROM actor_attempts_v2 WHERE candidate_id=? AND status='succeeded'",
        (recovered.candidate_id,),
    ).fetchone()
    assert proof["remote_run_id"] is None
    assert proof["actual_cost_usd"] == 0 and proof["cost_final"] == 1

    replay = asyncio.run(revalidate_failed_replacement(
        store, repository, registry, reader, _Catalog(),
        plan_id=failed_plan.plan_id,
        expected_generation=failed_plan.generation,
        idempotency_key="revalidate-failed-plan-key",
        created_by_user_id="owner",
    ))
    assert replay.plan.plan_id == recovered.plan.plan_id
    assert replay.proof_count == 0 and reader.calls == 1
    store.close()


def test_paid_probe_reuses_same_dataset_for_observed_successor_without_second_run(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    input_schema = {
        "type": "object", "required": ["username"],
        "properties": {"username": {"type": "string"}},
    }
    output_schema = {
        "type": "object", "properties": {
            "results": {"type": "array", "items": {
                "type": "object", "properties": {
                    "id": {"type": "string"}, "url": {"type": "string"},
                    "createdAt": {"type": "string"},
                    "text": {"type": "string"},
                    "author": {"type": "string"},
                },
            }},
        },
    }
    initial_manifest = _manifest("publisher/adaptive")
    schema_hash = lambda value: hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with repository.transaction():
        adaptive = repository.create_candidate(
            candidate_id="adaptive", route_id=route_id,
            actor_id="publisher/adaptive", publisher="publisher",
            build_id="build-adaptive", build_number="1.0.0",
            manifest_json=initial_manifest,
            manifest_hash=actor_manifest_hash(parse_actor_manifest(initial_manifest)),
            input_schema_hash=schema_hash(input_schema),
            output_schema_hash=schema_hash(output_schema),
            lifecycle=CandidateLifecycle.STATIC_VALID,
        )
        repository.operator.upsert_metadata(
            adaptive.candidate_id,
            normalize_store_metadata({
                "actorId": "publisher/adaptive", "title": "Adaptive",
                "username": "publisher", "pricingInfos": [{
                    "pricingModel": "PAY_PER_EVENT",
                    "pricePerUnitUsd": 0.01, "unitName": "result",
                }],
            }, fallback_slug="publisher/adaptive"),
        )
        plan = repository.operator.create_plan(
            plan_id="adaptive-plan", route_id=route_id,
            target_assignment=AssignmentRole.ACTIVE, target_priority=0,
            proposed_candidate_id=adaptive.candidate_id,
            idempotency_key="adaptive-plan-key", created_by_user_id="owner",
            per_probe_cap_usd=0.05, total_cap_usd=0.05,
        )
        plan = repository.operator.transition_plan(
            plan.plan_id, current=plan.status,
            target=ReplacementStatus.AUTHORIZED,
            expected_generation=plan.generation,
        )
    observed_manifest = json.dumps({
        "version": 1, "actor_id": "publisher/adaptive",
        "build_number": "1.0.0",
        "input": {"username": {"$ref": "target.handle"}},
        "row_extraction": {
            "mode": "nested_array", "pointers": ["/results"],
            "filters": [],
        },
        "output": {
            "native_id": {"pointers": ["/item/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/item/url"], "transforms": ["normalize_url"]},
            "published_at": {"pointers": ["/item/createdAt"], "transforms": ["parse_datetime"]},
            "text": {"pointers": ["/item/text"], "transforms": ["to_string"]},
            "author_handle": {"pointers": ["/item/author"], "transforms": ["to_string"]},
        },
        "semantics": {
            "identity": {"output_field": "author_handle", "target_ref": "target.handle", "match": "handle"},
            "url_host_allowlist": ["example.com"],
        },
    })
    revision = DiscoveryRevision(
        actor_id="publisher/adaptive", publisher="publisher",
        build_id="build-adaptive", build_number="1.0.0",
        price_per_run_usd=0.01, input_schema=input_schema,
        output_schema=output_schema,
    )
    mapper = _ObservedMapper(observed_manifest)
    registry = AdapterRegistry()
    registry.register(_NestedAdaptationAdapter())
    remote = _NestedRemote()
    runner = ActorOpsReplacementRunner(
        repository, registry, remote, _ObservedCatalog(revision),
        ai_mapper=mapper,
    )

    adapted = asyncio.run(runner.run(
        plan.plan_id, {source_id: {"target": "openai"}}
    ))
    ready = asyncio.run(runner.run(
        plan.plan_id, {source_id: {"target": "openai"}}
    ))

    assert adapted["status"] == "revalidated", adapted
    assert adapted["new_actor_runs"] == 0 and mapper.calls == 1
    assert ready["status"] == "ready" and len(remote.requests) == 1
    successor_id = str(adapted["candidate_id"])
    assert successor_id != "adaptive"
    assert repository.get_candidate(successor_id).lifecycle is CandidateLifecycle.PROBATIONARY
    assert repository.get_candidate("adaptive").last_error_code == "actorops_discovery_mapping_superseded"
    evidence = repository.connection.execute(
        "SELECT * FROM actor_attempts_v2 WHERE candidate_id=? AND logical_job_id LIKE 'revalidate:%'",
        (successor_id,),
    ).fetchone()
    assert evidence["actual_cost_usd"] == 0 and evidence["dataset_id"] == "dataset"
    store.close()


def test_missing_output_schema_uses_one_sample_run_then_retargets_successor(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    input_schema = {
        "type": "object", "required": ["username"],
        "properties": {"username": {"type": "string"}},
    }
    revision = DiscoveryRevision(
        actor_id="publisher/sample", publisher="publisher",
        build_id="build-sample", build_number="1.0.0",
        price_per_run_usd=0.01, input_schema=input_schema, output_schema={},
    )
    input_plan, error = create_input_plan(
        revision, {"username": {"$ref": "target.handle"}}
    )
    assert input_plan is not None and error is None
    schema_hash = lambda value: hashlib.sha256(
        json.dumps(value, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()
    with repository.transaction():
        candidate = repository.create_candidate(
            candidate_id="sample", route_id=route_id,
            actor_id=revision.actor_id, publisher=revision.publisher,
            build_id=revision.build_id, build_number=revision.build_number,
            manifest_json=None, manifest_hash=None,
            input_schema_hash=schema_hash(input_schema),
            output_schema_hash=schema_hash({}),
            lifecycle=CandidateLifecycle.MAPPING_PENDING,
        )
        repository.sampling.upsert_ready(candidate, input_plan)
        repository.operator.upsert_metadata(
            candidate.candidate_id,
            normalize_store_metadata({
                "actorId": revision.actor_id, "title": "Sample Actor",
                "username": "publisher", "pricingInfos": [{
                    "pricingModel": "PAY_PER_EVENT",
                    "pricePerUnitUsd": 0.01, "unitName": "result",
                }],
            }, fallback_slug=revision.actor_id),
        )
        plan = repository.operator.create_plan(
            plan_id="sample-plan", route_id=route_id,
            target_assignment=AssignmentRole.ACTIVE, target_priority=0,
            proposed_candidate_id=candidate.candidate_id,
            idempotency_key="sample-plan-key", created_by_user_id="owner",
            per_probe_cap_usd=0.05, total_cap_usd=0.05,
        )
        plan = repository.operator.transition_plan(
            plan.plan_id, current=plan.status,
            target=ReplacementStatus.AUTHORIZED,
            expected_generation=plan.generation,
        )
    observed_manifest = json.dumps({
        "version": 1, "actor_id": revision.actor_id,
        "build_number": revision.build_number,
        "input": {"username": {"$ref": "target.handle"}},
        "row_extraction": {
            "mode": "nested_array", "pointers": ["/results"], "filters": [],
        },
        "output": {
            "native_id": {"pointers": ["/item/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/item/url"], "transforms": ["normalize_url"]},
            "published_at": {"pointers": ["/item/createdAt"], "transforms": ["parse_datetime"]},
            "text": {"pointers": ["/item/text"], "transforms": ["to_string"]},
            "author_handle": {"pointers": ["/item/author"], "transforms": ["to_string"]},
        },
        "semantics": {
            "identity": {
                "output_field": "author_handle",
                "target_ref": "target.handle", "match": "handle",
            },
            "url_host_allowlist": ["example.com"],
        },
    })
    mapper = _ObservedMapper(observed_manifest)
    registry = AdapterRegistry()
    registry.register(_NestedAdaptationAdapter())
    remote = _NestedRemote()
    runner = ActorOpsReplacementRunner(
        repository, registry, remote, _ObservedCatalog(revision),
        ai_mapper=mapper,
    )

    adapted = asyncio.run(runner.run(
        plan.plan_id, {source_id: {"target": "openai"}}
    ))
    ready = asyncio.run(runner.run(
        plan.plan_id, {source_id: {"target": "openai"}}
    ))

    assert adapted["status"] == "revalidated", adapted
    assert adapted["new_actor_runs"] == 0
    assert ready["status"] == "ready"
    assert len(remote.requests) == 1 and mapper.calls == 1
    sample_attempt = repository.connection.execute(
        """SELECT failure_class,error_code FROM actor_attempts_v2
           WHERE attempt_group_id=? AND remote_run_id IS NOT NULL""",
        (plan.plan_id,),
    ).fetchone()
    assert sample_attempt["failure_class"] == "internal"
    assert sample_attempt["error_code"] == (
        "actorops_replacement_observed_mapping_required"
    )
    successor = repository.get_candidate(str(adapted["candidate_id"]))
    assert successor.lifecycle is CandidateLifecycle.PROBATIONARY
    assert repository.get_candidate("sample").last_error_code == "actorops_discovery_mapping_superseded"
    store.close()




def test_revalidation_clears_old_contract_rejection_without_claiming_empty_as_proof(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    with repository.transaction():
        plan = repository.operator.create_plan(
            plan_id="empty-plan", route_id=route_id,
            target_assignment=AssignmentRole.ACTIVE, target_priority=0,
            proposed_candidate_id="replacement",
            idempotency_key="empty-plan-idempotency", created_by_user_id="owner",
            per_probe_cap_usd=0.05, total_cap_usd=0.05,
        )
        plan = repository.operator.transition_plan(
            plan.plan_id, current=plan.status,
            target=ReplacementStatus.AUTHORIZED,
            expected_generation=plan.generation,
        )
    failing = AdapterRegistry()
    failing.register(_OutputFailureAdapter())
    result = asyncio.run(ActorOpsReplacementRunner(
        repository, failing, _Remote(), _Catalog(),
    ).run(plan.plan_id, {source_id: {"target": "openai"}}))
    assert result["error_code"] == "actorops_replacement_contract_mismatch"

    compatible = AdapterRegistry()
    compatible.register(_NoEvidenceAdapter())
    failed_plan = repository.operator.get_plan(plan.plan_id)
    recovered = asyncio.run(revalidate_failed_replacement(
        store, repository, compatible, _DatasetReader(), _Catalog(),
        plan_id=failed_plan.plan_id,
        expected_generation=failed_plan.generation,
        idempotency_key="revalidate-empty-plan-key",
        created_by_user_id="owner",
    ))

    assert recovered.plan.status is ReplacementStatus.PREVIEWED
    candidate = repository.get_candidate(recovered.candidate_id)
    assert candidate.lifecycle is CandidateLifecycle.STATIC_VALID
    candidate_row = repository.connection.execute(
        "SELECT last_error_code,last_success_at FROM actor_candidates_v2 WHERE candidate_id=?",
        (candidate.candidate_id,),
    ).fetchone()
    assert candidate_row["last_error_code"] is None
    assert candidate_row["last_success_at"] is None
    evidence = repository.connection.execute(
        "SELECT * FROM actor_attempts_v2 WHERE logical_job_id LIKE 'revalidate:%'"
    ).fetchone()
    assert evidence["semantic_outcome"] == "no_evidence"
    assert evidence["remote_run_id"] is None and evidence["actual_cost_usd"] == 0
    assert not repository.operator.proofs_complete(recovered.plan)
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
    assert captured["require_validation_key"] is False
    assert result["error_code"] == "actorops_replacement_credential_unavailable"
    store.close()


def test_manual_selection_can_restore_a_previously_active_inactive_candidate(tmp_path: Path) -> None:
    store, repository, route_id, _source_id = _setup(tmp_path)
    active = repository.get_candidate("active")
    replacement = repository.get_candidate("replacement")
    with repository.transaction():
        replacement = repository.record_candidate_outcome(
            replacement.candidate_id, expected_generation=replacement.generation, succeeded=True,
        )
        replacement = repository.transition_candidate(
            replacement.candidate_id, CandidateLifecycle.STATIC_VALID,
            CandidateLifecycle.PROBATIONARY, expected_generation=replacement.generation,
        )
        # Model a completed zero-cost restore point: a runnable replacement is
        # active and the original active Candidate is retained as inactive.
        stamp = "2026-08-21T00:00:00+00:00"
        store.connect().execute(
            "UPDATE actor_candidates_v2 SET assignment_role='inactive', priority=NULL, generation=generation+1, updated_at=? WHERE candidate_id='active'",
            (stamp,),
        )
        store.connect().execute(
            "UPDATE actor_candidates_v2 SET assignment_role='active', priority=0, generation=generation+1, updated_at=? WHERE candidate_id='replacement'",
            (stamp,),
        )
        store.connect().execute(
            "UPDATE actor_routes_v2 SET generation=generation+1, updated_at=? WHERE route_id=?",
            (stamp, route_id),
        )
        current_route = repository.get_route(route_id)
        original = repository.get_candidate("active")
        repository.promote_standby_candidate(
            route_id, original.candidate_id,
            expected_route_generation=current_route.generation,
            expected_candidate_generation=original.generation,
        )
    assert repository.get_candidate("active").assignment_role is AssignmentRole.ACTIVE
    assert repository.get_candidate("replacement").assignment_role is AssignmentRole.INACTIVE
    store.close()


def test_explicit_replacement_runs_one_probe_then_applies_without_feed_updates(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    with repository.transaction():
        plan = repository.operator.create_plan(plan_id="replacement-plan", route_id=route_id, target_assignment=AssignmentRole.ACTIVE, target_priority=0, proposed_candidate_id="replacement", idempotency_key="replacement-idempotency-key", created_by_user_id="owner", per_probe_cap_usd=0.05, total_cap_usd=0.05)
        plan = repository.operator.transition_plan(plan.plan_id, current=plan.status, target=ReplacementStatus.AUTHORIZED, expected_generation=plan.generation)
    registry = AdapterRegistry()
    registry.register(_Adapter())
    remote = _Remote()
    runner = ActorOpsReplacementRunner(repository, registry, remote, _Catalog())
    first = asyncio.run(runner.run(plan.plan_id, {source_id: {"target": "openai"}}))
    assert first["status"] == "proved"
    assert remote.requests[0].max_items == 1
    assert remote.requests[0].dataset_item_limit == 4
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


def test_replacement_start_rejection_settles_and_rejects_candidate(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    with repository.transaction():
        plan = repository.operator.create_plan(
            plan_id="replacement-rejected-plan",
            route_id=route_id,
            target_assignment=AssignmentRole.ACTIVE,
            target_priority=0,
            proposed_candidate_id="replacement",
            idempotency_key="replacement-rejected-key",
            created_by_user_id="owner",
            per_probe_cap_usd=0.05,
            total_cap_usd=0.05,
        )
        plan = repository.operator.transition_plan(
            plan.plan_id,
            current=plan.status,
            target=ReplacementStatus.AUTHORIZED,
            expected_generation=plan.generation,
        )
    registry = AdapterRegistry()
    registry.register(_Adapter())

    result = asyncio.run(ActorOpsReplacementRunner(
        repository, registry, _RejectingRemote(), _Catalog()
    ).run(plan.plan_id, {source_id: {"target": "openai"}}))

    attempt = repository.connection.execute(
        "SELECT * FROM actor_attempts_v2 WHERE attempt_group_id=?",
        (plan.plan_id,),
    ).fetchone()
    assert result["status"] == "failed"
    assert tuple(attempt[key] for key in (
        "status", "actual_cost_usd", "cost_final", "error_code"
    )) == ("failed", 0.0, 1, "apify_actor_start_rejected")
    assert repository.get_candidate(
        "replacement"
    ).lifecycle is CandidateLifecycle.REJECTED
    assert repository.operator.get_plan(
        plan.plan_id
    ).status is ReplacementStatus.FAILED
    store.close()


def test_explicit_replacement_can_target_a_standby_slot(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    standby_manifest = _manifest("publisher/standby")
    with repository.transaction():
        standby = repository.create_candidate(
            candidate_id="standby",
            route_id=route_id,
            actor_id="publisher/standby",
            publisher="publisher",
            build_id="build-standby",
            build_number="1.0.0",
            manifest_json=standby_manifest,
            manifest_hash=actor_manifest_hash(parse_actor_manifest(standby_manifest)),
            input_schema_hash="a" * 64,
            output_schema_hash="b" * 64,
            lifecycle=CandidateLifecycle.CERTIFIED,
        )
        route = repository.get_route(route_id)
        repository.assign_candidate(
            route_id,
            standby.candidate_id,
            AssignmentRole.STANDBY,
            priority=1,
            expected_route_generation=route.generation,
            expected_candidate_generation=standby.generation,
        )
        plan = repository.operator.create_plan(
            plan_id="standby-replacement-plan",
            route_id=route_id,
            target_assignment=AssignmentRole.STANDBY,
            target_priority=1,
            proposed_candidate_id="replacement",
            idempotency_key="standby-replacement-idempotency",
            created_by_user_id="owner",
            per_probe_cap_usd=0.05,
            total_cap_usd=0.05,
        )
        plan = repository.operator.transition_plan(
            plan.plan_id,
            current=plan.status,
            target=ReplacementStatus.AUTHORIZED,
            expected_generation=plan.generation,
        )

    registry = AdapterRegistry()
    registry.register(_Adapter())
    runner = ActorOpsReplacementRunner(repository, registry, _Remote(), _Catalog())
    assert asyncio.run(runner.run(plan.plan_id, {source_id: {"target": "openai"}}))["status"] == "proved"
    assert asyncio.run(runner.run(plan.plan_id, {source_id: {"target": "openai"}}))["status"] == "ready"
    ready = repository.operator.get_plan(plan.plan_id)
    with repository.transaction():
        repository.operator.apply_plan(ready.plan_id, expected_generation=ready.generation)

    replacement = repository.get_candidate("replacement")
    assert replacement.assignment_role is AssignmentRole.STANDBY
    assert replacement.priority == 1
    assert repository.get_candidate("standby").assignment_role is AssignmentRole.INACTIVE
    assert repository.get_candidate("active").assignment_role is AssignmentRole.ACTIVE
    store.close()


def test_explicit_replacement_can_fill_an_empty_standby_slot(tmp_path: Path) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    with repository.transaction():
        plan = repository.operator.create_plan(
            plan_id="standby-fill-plan",
            route_id=route_id,
            target_assignment=AssignmentRole.STANDBY,
            target_priority=1,
            proposed_candidate_id="replacement",
            idempotency_key="standby-fill-idempotency",
            created_by_user_id="owner",
            per_probe_cap_usd=0.05,
            total_cap_usd=0.05,
        )
        assert plan.current_candidate_id == plan.proposed_candidate_id
        plan = repository.operator.transition_plan(
            plan.plan_id,
            current=plan.status,
            target=ReplacementStatus.AUTHORIZED,
            expected_generation=plan.generation,
        )

    registry = AdapterRegistry()
    registry.register(_Adapter())
    runner = ActorOpsReplacementRunner(repository, registry, _Remote(), _Catalog())
    assert asyncio.run(runner.run(
        plan.plan_id, {source_id: {"target": "openai"}},
    ))["status"] == "proved"
    assert asyncio.run(runner.run(
        plan.plan_id, {source_id: {"target": "openai"}},
    ))["status"] == "ready"
    ready = repository.operator.get_plan(plan.plan_id)
    with repository.transaction():
        repository.operator.apply_plan(
            ready.plan_id, expected_generation=ready.generation,
        )

    replacement = repository.get_candidate("replacement")
    assert replacement.assignment_role is AssignmentRole.STANDBY
    assert replacement.priority == 1
    assert repository.get_candidate("active").assignment_role is AssignmentRole.ACTIVE
    store.close()


def test_stale_replacement_plans_expire_and_release_the_route(tmp_path: Path) -> None:
    store, repository, route_id, _source_id = _setup(tmp_path)
    with repository.transaction():
        plan = repository.operator.create_plan(
            plan_id="expired-preview", route_id=route_id,
            target_assignment=AssignmentRole.ACTIVE, target_priority=0,
            proposed_candidate_id="replacement", idempotency_key="expired-preview",
            created_by_user_id="owner", per_probe_cap_usd=0.05,
            total_cap_usd=0.05,
        )
        repository.connection.execute(
            """UPDATE actor_replacement_plans_v2
               SET updated_at='2026-08-20T00:00:00+00:00' WHERE plan_id=?""",
            (plan.plan_id,),
        )
        assert repository.operator.expire_stale_plans(
            now=datetime(2026, 8, 20, 1, tzinfo=timezone.utc)
        ) == (plan.plan_id,)
        replacement = repository.operator.create_plan(
            plan_id="replacement-after-expiry", route_id=route_id,
            target_assignment=AssignmentRole.ACTIVE, target_priority=0,
            proposed_candidate_id="replacement", idempotency_key="after-expiry",
            created_by_user_id="owner", per_probe_cap_usd=0.05,
            total_cap_usd=0.05,
        )
    expired = repository.operator.get_plan(plan.plan_id)
    assert expired.status is ReplacementStatus.CANCELLED
    assert expired.error_code == "actorops_replacement_expired"
    assert replacement.status is ReplacementStatus.PREVIEWED
    store.close()


def test_exhausted_adaptation_releases_route_without_faulting_candidate(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    with repository.transaction():
        plan = repository.operator.create_plan(
            plan_id="adaptation-failed", route_id=route_id,
            target_assignment=AssignmentRole.ACTIVE, target_priority=0,
            proposed_candidate_id="replacement", idempotency_key="adaptation-failed",
            created_by_user_id="owner", per_probe_cap_usd=0.05,
            total_cap_usd=0.05,
        )
        plan = repository.operator.transition_plan(
            plan.plan_id, current=plan.status,
            target=ReplacementStatus.AUTHORIZED,
            expected_generation=plan.generation,
        )
        plan = repository.operator.transition_plan(
            plan.plan_id, current=plan.status,
            target=ReplacementStatus.RUNNING,
            expected_generation=plan.generation,
        )
    result = asyncio.run(DatasetAdaptationService(
        repository, AdapterRegistry(), None, None, ai_mapper=None,
    )._pending(plan, "actorops_replacement_observed_mapping_failed"))

    failed = repository.operator.get_plan(plan.plan_id)
    assert result.status == "adaptation_failed"
    assert failed.status is ReplacementStatus.FAILED
    assert failed.error_code == "actorops_replacement_observed_mapping_failed"
    assert repository.get_candidate("replacement").lifecycle is CandidateLifecycle.STATIC_VALID

    with repository.transaction():
        legacy = repository.operator.create_plan(
            plan_id="legacy-adaptation-pending", route_id=route_id,
            target_assignment=AssignmentRole.ACTIVE, target_priority=0,
            proposed_candidate_id="replacement", idempotency_key="legacy-adaptation-pending",
            created_by_user_id="owner", per_probe_cap_usd=0.05,
            total_cap_usd=0.05,
        )
        legacy = repository.operator.transition_plan(
            legacy.plan_id, current=legacy.status,
            target=ReplacementStatus.AUTHORIZED,
            expected_generation=legacy.generation,
        )
        legacy = repository.operator.transition_plan(
            legacy.plan_id, current=legacy.status,
            target=ReplacementStatus.RUNNING,
            expected_generation=legacy.generation,
        )
        legacy = repository.operator.note_plan(
            legacy.plan_id, status=legacy.status,
            expected_generation=legacy.generation,
            error_code="actorops_replacement_adaptation_pending",
        )
    assert repository.operator.list_due_plans()[0].plan_id == legacy.plan_id
    remote = _Remote()
    runner = ActorOpsReplacementRunner(
        repository, AdapterRegistry(), remote, _Catalog(),
    )
    resumed = asyncio.run(runner.run(
        legacy.plan_id, {source_id: {"target": "openai"}},
    ))
    assert resumed["status"] == "failed" and remote.requests == []
    assert repository.operator.get_plan(legacy.plan_id).status is ReplacementStatus.FAILED
    store.close()


def test_running_replacement_can_be_cancelled_without_erasing_unsettled_cost(
    tmp_path: Path,
) -> None:
    store, repository, route_id, source_id = _setup(tmp_path)
    with repository.transaction():
        plan = repository.operator.create_plan(
            plan_id="running-cost-plan", route_id=route_id,
            target_assignment=AssignmentRole.ACTIVE, target_priority=0,
            proposed_candidate_id="replacement", idempotency_key="running-cost-plan",
            created_by_user_id="owner", per_probe_cap_usd=0.05,
            total_cap_usd=0.05,
        )
        plan = repository.operator.transition_plan(
            plan.plan_id, current=plan.status, target=ReplacementStatus.AUTHORIZED,
            expected_generation=plan.generation,
        )
        plan = repository.operator.transition_plan(
            plan.plan_id, current=plan.status, target=ReplacementStatus.RUNNING,
            expected_generation=plan.generation,
        )
        binding = repository.get_binding(source_id)
        repository.create_attempt(
            attempt_id="running-cost-attempt", idempotency_key="running-cost-attempt",
            route_id=route_id, source_id=source_id, candidate_id="replacement",
            kind="probe", attempt_group_id=plan.plan_id, attempt_index=0,
            route_generation=repository.get_route(route_id).generation,
            binding_version=binding.binding_version,
            target_fingerprint=binding.target_fingerprint, reserved_usd=0.05,
        )
        repository.connection.execute(
            """UPDATE actor_replacement_plans_v2
               SET updated_at='2026-08-20T00:00:00+00:00' WHERE plan_id=?""",
            (plan.plan_id,),
        )
        assert repository.operator.expire_stale_plans(
            now=datetime(2026, 8, 22, tzinfo=timezone.utc)
        ) == ()
        cancelled = repository.operator.cancel_plan(
            plan.plan_id, expected_generation=plan.generation
        )
        assert cancelled.status is ReplacementStatus.CANCELLED
    assert repository.operator.get_plan(plan.plan_id).status is ReplacementStatus.CANCELLED
    assert repository.get_attempt("running-cost-attempt")["cost_final"] == 0
    store.close()
