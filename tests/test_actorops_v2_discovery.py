from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field, replace
from pathlib import Path
from types import SimpleNamespace

from src.services.actorops.adapters import build_default_registry
from src.services.actorops.discovery import (
    ActorOpsDiscovery,
    DiscoveryCatalogError,
)
from src.services.actorops.ports import (
    DiscoveryActorMatch,
    DiscoveryAiResult,
    DiscoveryMapping,
    DiscoveryRevision,
)
from src.services.actorops.discovery_ai import _mapping, _object
from src.services.actorops.discovery_mapping_issues import candidate_mapping_issue
from src.services.actorops.discovery_route_type import store_match_is_wrong_type
from src.services.actorops.domain import CandidateLifecycle
from src.services.actorops.repository import ActorOpsRepository
from src.services.apify_actor_manifest import actor_manifest_hash, parse_actor_manifest
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _revision(
    actor_id: str, *, complete: bool = True, price_per_run_usd: float | None = 0.01,
) -> DiscoveryRevision:
    properties = {
        "id": {"type": "string"},
        "url": {"type": "string"},
        "createdAt": {"type": "string"},
        "text": {"type": "string"},
    }
    if complete:
        properties["author"] = {"type": "string"}
    return DiscoveryRevision(
        actor_id=actor_id,
        publisher=actor_id.split("/", 1)[0],
        build_id=f"build-{actor_id.rsplit('/', 1)[-1]}",
        build_number="1.0.0",
        price_per_run_usd=price_per_run_usd,
        input_schema={"properties": {"profile": {"type": "string"}}},
        output_schema={"properties": properties},
    )


def _without_post_url(revision: DiscoveryRevision) -> DiscoveryRevision:
    properties = dict(revision.output_schema["properties"])
    properties.pop("url", None)
    return replace(revision, output_schema={"properties": properties})


@dataclass
class _Catalog:
    revisions: dict[str, DiscoveryRevision]
    fail_search_once: bool = False
    fail_read_once: bool = False
    searches: int = 0
    reads: list[str] = field(default_factory=list)

    async def search(self, _query: str) -> tuple[str, ...]:
        self.searches += 1
        if self.fail_search_once:
            self.fail_search_once = False
            raise DiscoveryCatalogError("catalog_temporary", retryable=True)
        return tuple(self.revisions)

    async def get_revision(self, actor_id: str) -> DiscoveryRevision:
        self.reads.append(actor_id)
        if self.fail_read_once:
            self.fail_read_once = False
            raise DiscoveryCatalogError("catalog_temporary", retryable=True)
        return self.revisions[actor_id]


def _repository(tmp_path: Path) -> tuple[ServiceStore, ActorOpsRepository, str]:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    route_id = str(store.connect().execute(
        "SELECT route_id FROM actor_routes_v2 WHERE platform='x'"
    ).fetchone()[0])
    repository = ActorOpsRepository(store.connect(), DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        repository.create_discovery_job(
            discovery_id="discovery-one",
            idempotency_key="discovery-one-key",
            route_id=route_id,
            trigger_reason="test",
            input_fingerprint="a" * 64,
        )
    return store, repository, route_id


def test_deterministic_discovery_persists_one_candidate_and_replay_is_inert(
    tmp_path: Path,
) -> None:
    store, repository, _route_id = _repository(tmp_path)
    catalog = _Catalog({"publisher/actor": _revision("publisher/actor")})
    discovery = ActorOpsDiscovery(repository, build_default_registry(), catalog)

    first = asyncio.run(discovery.run("discovery-one"))
    calls_after_first = (catalog.searches, tuple(catalog.reads))
    second = asyncio.run(discovery.run("discovery-one"))

    job = repository.discovery.get("discovery-one")
    candidates = repository.discovery.list_candidates("discovery-one")
    assert first.status == "completed"
    assert first.idempotent_replay is False
    assert second.idempotent_replay is True
    assert job["stage"] == "persist"
    assert len(candidates) == 1
    assert candidates[0]["status"] == "accepted"
    candidate = repository.get_candidate(str(candidates[0]["candidate_id"]))
    assert candidate.lifecycle.value == "static_valid"
    assert candidate.assignment_role.value == "inactive"
    assert candidate.manifest_hash == actor_manifest_hash(parse_actor_manifest(candidate.manifest_json))
    assert calls_after_first == (catalog.searches, tuple(catalog.reads))
    store.close()


def test_discovery_keeps_nested_avatar_mapping_in_exact_revision_sidecar(
    tmp_path: Path,
) -> None:
    store, repository, _route_id = _repository(tmp_path)
    revision = _revision("publisher/actor")
    revision = DiscoveryRevision(
        actor_id=revision.actor_id,
        publisher=revision.publisher,
        build_id=revision.build_id,
        build_number=revision.build_number,
        price_per_run_usd=revision.price_per_run_usd,
        input_schema=revision.input_schema,
        output_schema={
            **revision.output_schema,
            "properties": {
                **revision.output_schema["properties"],
                "authorProfile": {
                    "type": "object",
                    "properties": {"profileImageUrlHttps": {"type": "string"}},
                },
            },
        },
    )

    result = asyncio.run(
        ActorOpsDiscovery(
            repository,
            build_default_registry(),
            _Catalog({"publisher/actor": revision}),
        ).run("discovery-one")
    )

    row = repository.connection.execute(
        """SELECT mapping_status, avatar_json_pointer, evidence_kind
             FROM actor_candidate_presentation_mappings_v2"""
    ).fetchone()
    candidate = repository.get_candidate(
        str(repository.discovery.list_candidates("discovery-one")[0]["candidate_id"])
    )
    assert result.status == "completed"
    assert "author_avatar_url" not in json.loads(candidate.manifest_json)["output"]
    assert dict(row) == {
        "mapping_status": "ready",
        "avatar_json_pointer": "/authorProfile/profileImageUrlHttps",
        "evidence_kind": "schema",
    }
    store.close()


def test_ai_absence_keeps_unresolved_mapping_pending_without_failing_job(
    tmp_path: Path,
) -> None:
    store, repository, _route_id = _repository(tmp_path)
    catalog = _Catalog({
        "publisher/incomplete": _without_post_url(
            _revision("publisher/incomplete", complete=False)
        )
    })

    result = asyncio.run(
        ActorOpsDiscovery(repository, build_default_registry(), catalog).run("discovery-one")
    )

    candidates = repository.discovery.list_candidates("discovery-one")
    candidate = repository.get_candidate(str(candidates[0]["candidate_id"]))
    assert result.status == "completed"
    assert candidates[0]["status"] == "pending"
    assert candidate.lifecycle.value == "mapping_pending"
    assert candidate.manifest_hash is None
    store.close()


def test_missing_output_schema_persists_probe_eligible_input_plan(
    tmp_path: Path,
) -> None:
    store, repository, _route_id = _repository(tmp_path)
    revision = replace(
        _revision("publisher/sample"),
        input_schema={
            "type": "object",
            "required": ["username"],
            "properties": {"username": {"type": "string"}},
        },
        output_schema={},
    )

    result = asyncio.run(ActorOpsDiscovery(
        repository, build_default_registry(),
        _Catalog({revision.actor_id: revision}),
    ).run("discovery-one"))

    link = repository.discovery.list_candidates("discovery-one")[0]
    candidate = repository.get_candidate(str(link["candidate_id"]))
    sidecar = repository.sampling.get_valid(candidate)
    assert result.status == "completed"
    assert link["status"] == "pending"
    assert link["rejection_code"] == "actorops_discovery_output_sample_required"
    assert candidate.lifecycle is CandidateLifecycle.MAPPING_PENDING
    assert candidate.manifest_json is None
    assert sidecar is not None and sidecar["status"] == "ready"
    store.close()


def test_validation_records_an_unpriced_revision_then_continues_with_other_candidates(
    tmp_path: Path,
) -> None:
    store, repository, _route_id = _repository(tmp_path)
    catalog = _Catalog({
        "publisher/unpriced": _revision("publisher/unpriced", price_per_run_usd=None),
        "publisher/valid": _revision("publisher/valid"),
    })

    result = asyncio.run(ActorOpsDiscovery(repository, build_default_registry(), catalog).run("discovery-one"))

    rows = repository.discovery.list_candidates("discovery-one")
    assert result.status == "completed"
    assert {str(row["status"]) for row in rows} == {"accepted", "rejected"}
    assert any(str(row["rejection_code"]) == "actorops_discovery_validation_rejected" for row in rows)
    store.close()


def test_retry_wait_resumes_the_same_stage_without_regression(tmp_path: Path) -> None:
    store, repository, _route_id = _repository(tmp_path)
    catalog = _Catalog(
        {"publisher/actor": _revision("publisher/actor")}, fail_search_once=True
    )
    discovery = ActorOpsDiscovery(
        repository,
        build_default_registry(),
        catalog,
        retry_delay_seconds=0,
    )

    waiting = asyncio.run(discovery.run("discovery-one"))
    resumed = asyncio.run(discovery.run("discovery-one"))

    assert waiting.status == "retry_wait"
    assert resumed.status == "completed"
    assert repository.discovery.get("discovery-one")["stage"] == "persist"
    store.close()


def test_metadata_retry_reuses_store_checkpoint_without_another_search(tmp_path: Path) -> None:
    store, repository, _route_id = _repository(tmp_path)
    catalog = _Catalog({"publisher/actor": _revision("publisher/actor")}, fail_read_once=True)
    discovery = ActorOpsDiscovery(repository, build_default_registry(), catalog, retry_delay_seconds=0)

    assert asyncio.run(discovery.run("discovery-one")).status == "retry_wait"
    assert repository.discovery.get("discovery-one")["stage"] == "metadata"
    assert asyncio.run(discovery.run("discovery-one")).status == "completed"
    assert catalog.searches == 4
    store.close()


def test_discovery_merges_queries_then_keeps_highest_quality_actors(
    tmp_path: Path,
) -> None:
    store, repository, _route_id = _repository(tmp_path)
    revisions = {
        f"publisher{index}/actor": _revision(f"publisher{index}/actor")
        for index in range(14)
    }

    class _RankedCatalog(_Catalog):
        async def search(self, _query: str):
            self.searches += 1
            return tuple(
                DiscoveryActorMatch(
                    actor_id,
                    total_users=index * 100,
                    rating=4.0 + (index / 100),
                    review_count=index,
                )
                for index, actor_id in enumerate(self.revisions)
            )

    catalog = _RankedCatalog(revisions)
    result = asyncio.run(
        ActorOpsDiscovery(
            repository, build_default_registry(), catalog
        ).run("discovery-one")
    )
    rows = repository.connection.execute(
        """SELECT candidate.actor_id FROM actor_discovery_job_candidates_v2 AS link
             JOIN actor_candidates_v2 AS candidate
               ON candidate.workspace_id=link.workspace_id
              AND candidate.candidate_id=link.candidate_id
            WHERE link.discovery_id='discovery-one'
            ORDER BY link.rank"""
    ).fetchall()

    assert result.status == "completed"
    assert catalog.searches == 4
    assert len(rows) == 5
    assert str(rows[0]["actor_id"]) == "publisher13/actor"
    assert {str(row["actor_id"]) for row in rows}.isdisjoint(
        {f"publisher{index}/actor" for index in range(9)}
    )
    store.close()


def test_discovery_demotes_account_restricted_actor_below_compatible_candidates(
    tmp_path: Path,
) -> None:
    store, repository, _route_id = _repository(tmp_path)
    restricted_id = "popular/restricted"
    compatible_ids = [f"compatible/actor-{index}" for index in range(5)]
    revisions = {
        restricted_id: replace(
            _revision(restricted_id),
            account_fit_rank=2,
            account_fit_reason="actorops_candidate_free_api_restricted",
        ),
        **{
            actor_id: _revision(actor_id)
            for actor_id in compatible_ids
        },
    }

    class _AccountFitCatalog(_Catalog):
        async def search(self, _query: str):
            self.searches += 1
            return (
                DiscoveryActorMatch(
                    restricted_id,
                    total_users=1_000_000,
                    rating=5.0,
                    review_count=10_000,
                ),
                *(
                    DiscoveryActorMatch(
                        actor_id,
                        total_users=1_000 - index,
                        rating=4.0,
                        review_count=10,
                    )
                    for index, actor_id in enumerate(compatible_ids)
                ),
            )

    result = asyncio.run(
        ActorOpsDiscovery(
            repository,
            build_default_registry(),
            _AccountFitCatalog(revisions),
        ).run("discovery-one")
    )
    rows = repository.connection.execute(
        """SELECT candidate.actor_id
             FROM actor_discovery_job_candidates_v2 AS link
             JOIN actor_candidates_v2 AS candidate
               ON candidate.workspace_id=link.workspace_id
              AND candidate.candidate_id=link.candidate_id
            WHERE link.discovery_id='discovery-one'
            ORDER BY link.rank"""
    ).fetchall()

    assert result.status == "completed"
    assert [str(row["actor_id"]) for row in rows] == compatible_ids
    assert restricted_id not in {str(row["actor_id"]) for row in rows}
    store.close()


def test_wrong_store_types_do_not_consume_revision_or_route_slots(
    tmp_path: Path,
) -> None:
    store, repository, _route_id = _repository(tmp_path)
    wrong_ids = [f"publisher/followers-{index}" for index in range(5)]
    relevant_ids = [f"publisher/tweets-{index}" for index in range(20)]
    revisions = {
        actor_id: _revision(actor_id) for actor_id in relevant_ids
    }

    class _TypedCatalog(_Catalog):
        async def search(self, _query: str):
            self.searches += 1
            return (
                *(
                    DiscoveryActorMatch(
                        actor_id, total_users=100_000 - index,
                        display_name="Twitter Followers Scraper",
                    )
                    for index, actor_id in enumerate(wrong_ids)
                ),
                *(
                    DiscoveryActorMatch(
                        actor_id, total_users=10_000 - index,
                        display_name="X Profile Timeline Tweets Scraper",
                    )
                    for index, actor_id in enumerate(relevant_ids)
                ),
            )

    catalog = _TypedCatalog(revisions)
    result = asyncio.run(
        ActorOpsDiscovery(
            repository, build_default_registry(), catalog
        ).run("discovery-one")
    )
    job = repository.discovery.get("discovery-one")
    metrics = json.loads(str(job["search_cursor"]))["metrics"]
    links = repository.discovery.list_candidates("discovery-one")

    assert result.status == "completed"
    assert not set(wrong_ids) & set(catalog.reads)
    assert len(links) == 5
    assert metrics == {
        "marketplace_hits": 25,
        "preflight_blocked": 0,
        "revision_checks": 20,
        "route_relevant": 5,
        "sample_required": 0,
        "static_ready": 5,
        "system_usable": 0,
        "wrong_actor_type": 5,
    }


def test_store_type_gate_rejects_explicit_foreign_products_but_keeps_unknowns() -> None:
    assert store_match_is_wrong_type(
        "youtube",
        DiscoveryActorMatch(
            "scrapestorm/avito-offers-scraper",
            display_name="Avito Offers Scraper",
        ),
    )
    assert store_match_is_wrong_type(
        "instagram",
        DiscoveryActorMatch(
            "publisher/instagram-hashtag-posts",
            display_name="Instagram Hashtag Posts Scraper",
        ),
    )
    assert not store_match_is_wrong_type(
        "x", DiscoveryActorMatch("publisher/opaque-actor")
    )
    assert not store_match_is_wrong_type(
        "youtube",
        DiscoveryActorMatch(
            "lurkapi/youtube-channel-videos-stats-scraper",
            display_name="YouTube Channel Videos Stats Scraper",
        ),
    )


def test_ai_hallucinated_schema_field_stays_mapping_pending(tmp_path: Path) -> None:
    store, repository, _route_id = _repository(tmp_path)
    catalog = _Catalog({
        "publisher/incomplete": _without_post_url(
            _revision("publisher/incomplete", complete=False)
        )
    })

    class _Ai:
        async def map(self, _route_key, _revisions):
            return DiscoveryAiResult(
                mappings={
                    "publisher/incomplete": DiscoveryMapping(json.dumps({
                        "version": 1, "actor_id": "publisher/incomplete", "build_number": "1.0.0",
                        "input": {"profile": {"$ref": "target.handle"}},
                        "output": {
                            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
                            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
                            "published_at": {"pointers": ["/createdAt"], "transforms": ["parse_datetime"]},
                            "text": {"pointers": ["/text"], "transforms": ["to_string"]},
                            "author_handle": {"pointers": ["/invented"], "transforms": ["to_string"]},
                        },
                        "semantics": {"identity": {"output_field": "author_handle", "target_ref": "target.handle", "match": "handle"}, "url_host_allowlist": ["x.com"]},
                    })),
                },
                config_id="safe-config",
            )

    result = asyncio.run(ActorOpsDiscovery(repository, build_default_registry(), catalog, ai_mapper=_Ai()).run("discovery-one"))

    candidates = repository.discovery.list_candidates("discovery-one")
    assert result.status == "completed"
    assert candidates[0]["status"] == "pending"
    assert repository.discovery.get("discovery-one")["ai_config_id"] == "safe-config"
    store.close()


def test_ai_retries_a_deterministic_manifest_that_fails_strict_schema_proof(
    tmp_path: Path,
) -> None:
    store, repository, _route_id = _repository(tmp_path)
    revision = replace(
        _revision("publisher/flexible"),
        input_schema={
            "properties": {
                "profile": {"type": "integer"},
                "handle": {"type": "string"},
            },
        },
    )

    class _Ai:
        calls = 0

        async def map(self, _route_key, revisions):
            self.calls += 1
            actor_id = revisions[0].actor_id
            return DiscoveryAiResult(
                mappings={
                    actor_id: DiscoveryMapping(json.dumps({
                        "version": 1,
                        "actor_id": actor_id,
                        "build_number": "1.0.0",
                        "input": {"handle": {"$ref": "target.handle"}},
                        "output": {
                            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
                            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
                            "published_at": {"pointers": ["/createdAt"], "transforms": ["parse_datetime"]},
                            "text": {"pointers": ["/text"], "transforms": ["to_string"]},
                            "author_handle": {"pointers": ["/author"], "transforms": ["to_string"]},
                        },
                        "semantics": {
                            "identity": {
                                "output_field": "author_handle",
                                "target_ref": "target.handle",
                                "match": "handle",
                            },
                            "url_host_allowlist": ["x.com"],
                        },
                    }))
                },
                config_id="deepseek-config",
            )

    mapper = _Ai()
    result = asyncio.run(ActorOpsDiscovery(
        repository,
        build_default_registry(),
        _Catalog({revision.actor_id: revision}),
        ai_mapper=mapper,
    ).run("discovery-one"))

    linked = repository.discovery.list_candidates("discovery-one")
    candidate = repository.get_candidate(str(linked[0]["candidate_id"]))
    assert result.status == "completed"
    assert mapper.calls == 1
    assert linked[0]["status"] == "accepted"
    assert candidate.lifecycle.value == "static_valid"
    assert json.loads(candidate.manifest_json)["input"] == {
        "handle": {"$ref": "target.handle"}
    }
    store.close()


def test_ai_mapping_isolates_each_of_up_to_six_exact_revisions(tmp_path: Path) -> None:
    store, repository, _route_id = _repository(tmp_path)
    catalog = _Catalog({
            f"publisher/incomplete-{index}": _without_post_url(_revision(
                f"publisher/incomplete-{index}", complete=False,
            ))
            for index in range(4)
    })

    class _Ai:
        seen: list[tuple[str, ...]]

        def __init__(self):
            self.seen = []

        async def map(self, _route_key, revisions):
            self.seen.append(tuple(revision.actor_id for revision in revisions))
            return DiscoveryAiResult(mappings={}, config_id="safe-config")

    mapper = _Ai()
    result = asyncio.run(
        ActorOpsDiscovery(repository, build_default_registry(), catalog, ai_mapper=mapper).run("discovery-one")
    )

    assert result.status == "completed"
    assert mapper.seen == [
        (f"publisher/incomplete-{index}",) for index in range(4)
    ]
    assert len(repository.discovery.list_candidates("discovery-one")) == 4
    store.close()


def test_ai_mapping_stops_after_five_quality_ordered_route_candidates(
    tmp_path: Path,
) -> None:
    store, repository, _route_id = _repository(tmp_path)
    revisions = {
        f"publisher/flexible-{index}": replace(
            _revision(f"publisher/flexible-{index}"),
            input_schema={
                "properties": {
                    "profile": {"type": "integer"},
                    "handle": {"type": "string"},
                },
            },
        )
        for index in range(8)
    }

    class _Ai:
        seen: list[str]

        def __init__(self) -> None:
            self.seen = []

        async def map(self, _route_key, selected):
            revision = selected[0]
            self.seen.append(revision.actor_id)
            return DiscoveryAiResult(
                mappings={
                    revision.actor_id: DiscoveryMapping(json.dumps({
                        "version": 1,
                        "actor_id": revision.actor_id,
                        "build_number": revision.build_number,
                        "input": {"handle": {"$ref": "target.handle"}},
                        "output": {
                            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
                            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
                            "published_at": {"pointers": ["/createdAt"], "transforms": ["parse_datetime"]},
                            "text": {"pointers": ["/text"], "transforms": ["to_string"]},
                            "author_handle": {"pointers": ["/author"], "transforms": ["to_string"]},
                        },
                        "semantics": {
                            "identity": {
                                "output_field": "author_handle",
                                "target_ref": "target.handle",
                                "match": "handle",
                            },
                            "url_host_allowlist": ["x.com"],
                        },
                    })),
                },
                config_id="deepseek-config",
                input_tokens=10,
                completion_tokens=5,
            )

    mapper = _Ai()
    result = asyncio.run(ActorOpsDiscovery(
        repository, build_default_registry(), _Catalog(revisions), ai_mapper=mapper,
    ).run("discovery-one"))
    metrics = json.loads(str(
        repository.discovery.get("discovery-one")["search_cursor"]
    ))["metrics"]
    links = repository.discovery.list_candidates("discovery-one")

    assert result.status == "completed"
    assert mapper.seen == list(revisions)[:5]
    assert len(links) == 5
    assert all(item["status"] == "accepted" for item in links)
    assert metrics["route_relevant"] == metrics["static_ready"] == 5
    store.close()


def test_ai_mapping_response_accepts_a_single_json_code_fence() -> None:
    assert _object("```json\n{\"mappings\": {\"publisher/actor\": {}}}\n```") == {
        "publisher/actor": {}
    }


def test_ai_mapping_response_accepts_bounded_alternate_json_wrappers() -> None:
    assert _object('{"publisher/actor": {"version": 1}}') == {
        "publisher/actor": {"version": 1}
    }
    assert _object('{"mappings": [{"actor_id": "publisher/actor", "manifest": {"version": 1}}]}') == {
        "publisher/actor": {"version": 1}
    }


def test_ai_mapping_response_requires_one_safe_result_per_candidate() -> None:
    parsed = _object(json.dumps({"results": [
        {
            "actor_id": "publisher/actor", "status": "unmappable",
            "error_code": "missing_identity",
        },
    ]}))
    mapping = _mapping(parsed["publisher/actor"])

    assert mapping == DiscoveryMapping(
        None, "actorops_discovery_ai_missing_identity"
    )
    assert _mapping({
        "status": "unmappable", "error_code": "invented_error",
    }) is None
    assert _mapping({
        "status": "unmappable", "error_code": "nested_content_items",
    }) == DiscoveryMapping(
        None, "actorops_discovery_ai_nested_content_items"
    )


def test_adaptable_mapping_gaps_have_safe_public_codes() -> None:
    assert candidate_mapping_issue(SimpleNamespace(
        last_error_code="actorops_discovery_ai_nested_content_items"
    )) == "nested_content_items"
    assert candidate_mapping_issue(SimpleNamespace(
        last_error_code="actorops_discovery_ai_wrong_actor_type"
    )) == "wrong_actor_type"


def test_exact_mapping_retires_and_hides_stale_pending_placeholder(
    tmp_path: Path,
) -> None:
    store, repository, route_id = _repository(tmp_path)
    shared = {
        "route_id": route_id,
        "actor_id": "publisher/actor",
        "publisher": "publisher",
        "build_id": "build-actor",
        "build_number": "1.0.0",
        "input_schema_hash": "b" * 64,
        "output_schema_hash": "c" * 64,
    }
    with repository.transaction():
        pending = repository.create_candidate(
            candidate_id="candidate-pending",
            manifest_json=None,
            manifest_hash=None,
            lifecycle=CandidateLifecycle.MAPPING_PENDING,
            **shared,
        )
        mapped = repository.create_candidate(
            candidate_id="candidate-mapped",
            manifest_json="{}",
            manifest_hash="d" * 64,
            lifecycle=CandidateLifecycle.STATIC_VALID,
            **shared,
        )
        changed = repository.discovery.supersede_pending_mapping(
            route_id=route_id,
            actor_id="publisher/actor",
            build_id="build-actor",
            build_number="1.0.0",
            input_schema_hash="b" * 64,
            output_schema_hash="c" * 64,
            keep_candidate_id=mapped.candidate_id,
        )

    assert changed == 1
    assert repository.get_candidate(pending.candidate_id).lifecycle.value == "rejected"
    assert [item.candidate_id for item in repository.list_route_candidates(route_id)] == [
        mapped.candidate_id
    ]
    store.close()


def test_generic_discovery_has_no_platform_or_feed_knowledge() -> None:
    source = Path("src/services/actorops/discovery.py").read_text()
    assert "if platform" not in source
    assert "source_catalog" not in source
    assert "publish_success" not in source
