from __future__ import annotations

import asyncio
import json
from dataclasses import dataclass, field
from pathlib import Path

from src.services.actorops.adapters import build_default_registry
from src.services.actorops.discovery import (
    ActorOpsDiscovery,
    DiscoveryCatalogError,
)
from src.services.actorops.ports import DiscoveryAiResult, DiscoveryMapping, DiscoveryRevision
from src.services.actorops.discovery_ai import _object
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


def test_ai_absence_keeps_unresolved_mapping_pending_without_failing_job(
    tmp_path: Path,
) -> None:
    store, repository, _route_id = _repository(tmp_path)
    catalog = _Catalog({"publisher/incomplete": _revision("publisher/incomplete", complete=False)})

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
    assert catalog.searches == 1
    store.close()


def test_ai_hallucinated_schema_field_stays_mapping_pending(tmp_path: Path) -> None:
    store, repository, _route_id = _repository(tmp_path)
    catalog = _Catalog({"publisher/incomplete": _revision("publisher/incomplete", complete=False)})

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


def test_ai_mapping_is_bounded_to_the_first_exact_revision(tmp_path: Path) -> None:
    store, repository, _route_id = _repository(tmp_path)
    catalog = _Catalog({
        f"publisher/incomplete-{index}": _revision(
            f"publisher/incomplete-{index}", complete=False,
        )
        for index in range(4)
    })

    class _Ai:
        seen: tuple[str, ...] = ()

        async def map(self, _route_key, revisions):
            self.seen = tuple(revision.actor_id for revision in revisions)
            return DiscoveryAiResult(mappings={}, config_id="safe-config")

    mapper = _Ai()
    result = asyncio.run(
        ActorOpsDiscovery(repository, build_default_registry(), catalog, ai_mapper=mapper).run("discovery-one")
    )

    assert result.status == "completed"
    assert mapper.seen == ("publisher/incomplete-0",)
    assert len(repository.discovery.list_candidates("discovery-one")) == 4
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


def test_generic_discovery_has_no_platform_or_feed_knowledge() -> None:
    source = Path("src/services/actorops/discovery.py").read_text()
    assert "if platform" not in source
    assert "source_catalog" not in source
    assert "publish_success" not in source
