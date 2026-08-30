from __future__ import annotations

import json
from dataclasses import replace
from datetime import datetime, timezone
from pathlib import Path

import pytest

from src.api.actorops_v2_projection import (
    actorops_v2_candidate_projection,
    actorops_v2_route_additions,
)
from src.services.apify_actor_manifest import (
    actor_manifest_hash,
    parse_actor_manifest,
)
from src.services.actorops.adapter_rows import validate_and_enrich_adapter_rows
from src.services.actorops.adapters import build_default_registry
from src.services.actorops.domain import AssignmentRole, CandidateLifecycle
from src.services.actorops.domain import RouteKey
from src.services.actorops.ports import (
    ActorManifest,
    FetchWindow,
    NormalizedBatch,
    PresentationEvidence,
)
from src.services.actorops.presentation_mapping import (
    CandidatePresentationMappings,
    avatar_pointer_from_rows,
    avatar_pointer_from_schema,
)
from src.services.actorops.repository import ActorOpsRepository
from src.storage.actorops_v2_presentation_schema_sql import SCHEMA_SQL
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _repository(
    tmp_path: Path,
) -> tuple[ServiceStore, ActorOpsRepository, object]:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    if connection.execute(
        """SELECT 1 FROM sqlite_master
           WHERE type='table' AND name='actor_candidate_presentation_mappings_v2'"""
    ).fetchone() is None:
        connection.executescript(SCHEMA_SQL)
    route_id = str(
        connection.execute(
            "SELECT route_id FROM actor_routes_v2 WHERE platform='instagram'"
        ).fetchone()[0]
    )
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    manifest = json.dumps(
        {
            "version": 1,
            "actor_id": "publisher/avatar",
            "build_number": "1.0.0",
            "input": {"username": {"$ref": "target.handle"}},
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
                "url_host_allowlist": ["instagram.com"],
            },
        }
    )
    with repository.transaction():
        candidate = repository.create_candidate(
            candidate_id="avatar-candidate",
            route_id=route_id,
            actor_id="publisher/avatar",
            publisher="publisher",
            build_id="build-avatar",
            build_number="1.0.0",
            manifest_json=manifest,
            manifest_hash=actor_manifest_hash(parse_actor_manifest(manifest)),
            input_schema_hash="b" * 64,
            output_schema_hash="c" * 64,
            lifecycle=CandidateLifecycle.CERTIFIED,
        )
    return store, repository, candidate


@pytest.mark.parametrize(
    ("platform", "schema", "expected"),
    [
        (
            "x",
            {
                "properties": {
                    "author": {
                        "type": "object",
                        "properties": {"profileImageUrlHttps": {"type": "string"}},
                    }
                }
            },
            "/author/profileImageUrlHttps",
        ),
        (
            "x",
            {"properties": {"user_profile_image_url": {"type": "string"}}},
            "/user_profile_image_url",
        ),
        (
            "instagram",
            {
                "properties": {
                    "owner": {
                        "properties": {"profile_pic_url": {"type": "string"}}
                    }
                }
            },
            "/owner/profile_pic_url",
        ),
        (
            "youtube",
            {
                "$defs": {
                    "channel": {
                        "properties": {"channelThumbnailUrl": {"type": "string"}}
                    }
                },
                "properties": {"channel": {"$ref": "#/$defs/channel"}},
            },
            "/channel/channelThumbnailUrl",
        ),
    ],
)
def test_schema_refresh_finds_safe_nested_platform_aliases(
    platform: str, schema: dict[str, object], expected: str
) -> None:
    assert avatar_pointer_from_schema(schema, platform) == expected


def test_success_observation_persists_only_pointer_and_enriches_ephemeral_url(
    tmp_path: Path,
) -> None:
    store, repository, candidate = _repository(tmp_path)
    mappings = CandidatePresentationMappings(repository)
    rows = (
        {
            "owner": {
                "profile_pic_url": "https://cdn.example/avatar.jpg",
                "secret": "must-not-be-stored",
            }
        },
    )

    batch = mappings.enrich_batch(
        candidate,
        "instagram",
        NormalizedBatch(
            items=(),
            semantic_outcome="valid_nonempty",
            presentation_evidence=PresentationEvidence(
                rows=rows,
                avatar_url="https://cdn.example/avatar.jpg",
                content_row_count=1,
            ),
        ),
    )

    row = repository.connection.execute(
        "SELECT * FROM actor_candidate_presentation_mappings_v2"
    ).fetchone()
    assert row["avatar_json_pointer"] == "/owner/profile_pic_url"
    assert row["evidence_kind"] == "observed"
    assert "cdn.example" not in json.dumps(dict(row), sort_keys=True)
    assert "must-not-be-stored" not in json.dumps(dict(row), sort_keys=True)
    assert batch.source_avatar_url == "https://cdn.example/avatar.jpg"
    store.close()


def test_observation_repairs_invalid_ready_pointer_with_valid_lower_alias(
    tmp_path: Path,
) -> None:
    store, repository, candidate = _repository(tmp_path)
    stamp = "2026-08-27T00:00:00+00:00"
    repository.connection.execute(
        """INSERT INTO actor_candidate_presentation_mappings_v2 (
               workspace_id, candidate_id, build_id, output_schema_hash,
               mapping_status, avatar_json_pointer, evidence_kind,
               generation, created_at, updated_at
           ) VALUES (?, ?, ?, ?, 'ready', '/profile_pic_url',
                     'observed', 1, ?, ?)""",
        (
            DEFAULT_WORKSPACE_ID,
            candidate.candidate_id,
            candidate.build_id,
            candidate.output_schema_hash,
            stamp,
            stamp,
        ),
    )
    rows = (
        {
            "profile_pic_url": "not-a-url",
            "avatar": "https://cdn.example/valid-avatar.png",
        },
    )

    assert avatar_pointer_from_rows(rows, "instagram") == "/avatar"
    batch = CandidatePresentationMappings(repository).enrich_batch(
        candidate,
        "instagram",
        NormalizedBatch(
            items=(),
            semantic_outcome="valid_nonempty",
            presentation_evidence=PresentationEvidence(
                rows=rows,
                avatar_url="https://cdn.example/valid-avatar.png",
                content_row_count=1,
            ),
        ),
    )

    row = repository.connection.execute(
        "SELECT * FROM actor_candidate_presentation_mappings_v2"
    ).fetchone()
    assert row["avatar_json_pointer"] == "/avatar"
    assert row["evidence_kind"] == "observed"
    assert row["generation"] == 2
    serialized = json.dumps(dict(row), sort_keys=True)
    assert "cdn.example" not in serialized
    assert "valid-avatar" not in serialized
    assert batch.source_avatar_url == "https://cdn.example/valid-avatar.png"
    store.close()


@pytest.mark.parametrize("evidence_kind", ["schema", "manifest"])
def test_success_replaces_non_target_ready_pointer_with_target_evidence(
    tmp_path: Path,
    evidence_kind: str,
) -> None:
    store, repository, candidate = _repository(tmp_path)
    stamp = "2026-08-27T00:00:00+00:00"
    repository.connection.execute(
        """INSERT INTO actor_candidate_presentation_mappings_v2 (
               workspace_id, candidate_id, build_id, output_schema_hash,
               mapping_status, avatar_json_pointer, evidence_kind,
               generation, created_at, updated_at
           ) VALUES (?, ?, ?, ?, 'ready', '/embedded/profilePicUrlHD',
                     ?, 7, ?, ?)""",
        (
            DEFAULT_WORKSPACE_ID,
            candidate.candidate_id,
            candidate.build_id,
            candidate.output_schema_hash,
            evidence_kind,
            stamp,
            stamp,
        ),
    )
    rows = ({"user": {"avatar": "https://cdn.example/target.png"}},)
    batch = NormalizedBatch(
        items=(),
        semantic_outcome="valid_nonempty",
        source_avatar_url="https://cdn.example/target.png",
        presentation_evidence=PresentationEvidence(
            rows=rows,
            avatar_url="https://cdn.example/target.png",
            content_row_count=1,
        ),
    )

    resolved = CandidatePresentationMappings(repository).enrich_batch(
        candidate, "instagram", batch
    )

    row = repository.connection.execute(
        "SELECT * FROM actor_candidate_presentation_mappings_v2"
    ).fetchone()
    assert row["mapping_status"] == "ready"
    assert row["avatar_json_pointer"] == "/user/avatar"
    assert row["evidence_kind"] == "observed"
    assert row["generation"] == 8
    assert resolved.source_avatar_url == "https://cdn.example/target.png"
    store.close()


def test_success_downgrades_invalid_manifest_pointer_without_restoring_it(
    tmp_path: Path,
) -> None:
    store, repository, candidate = _repository(tmp_path)
    manifest = json.loads(candidate.manifest_json)
    manifest["output"]["author_avatar_url"] = {
        "pointers": ["/embedded/profilePicUrlHD"],
        "transforms": ["normalize_url"],
    }
    candidate = replace(candidate, manifest_json=json.dumps(manifest))
    mappings = CandidatePresentationMappings(repository)
    mappings.refresh_pointer(
        candidate,
        "/embedded/profilePicUrlHD",
        evidence_kind="manifest",
    )
    batch = NormalizedBatch(
        items=(),
        semantic_outcome="valid_nonempty",
        presentation_evidence=PresentationEvidence(content_row_count=1),
    )

    first = mappings.enrich_batch(candidate, "instagram", batch)
    second = mappings.enrich_batch(candidate, "instagram", batch)

    row = repository.connection.execute(
        "SELECT * FROM actor_candidate_presentation_mappings_v2"
    ).fetchone()
    assert row["mapping_status"] == "missing"
    assert row["avatar_json_pointer"] is None
    assert row["evidence_kind"] == "observed"
    assert row["generation"] == 2
    assert first.source_avatar_url is None
    assert second.source_avatar_url is None
    store.close()


def test_stale_ready_pointer_cas_cannot_overwrite_newer_observation(
    tmp_path: Path,
) -> None:
    store, repository, candidate = _repository(tmp_path)
    mappings = CandidatePresentationMappings(repository)
    mappings.refresh_pointer(candidate, "/embedded/avatar", evidence_kind="schema")
    stale = mappings.current(candidate)
    repository.connection.execute(
        """UPDATE actor_candidate_presentation_mappings_v2
              SET avatar_json_pointer='/user/avatar', evidence_kind='observed',
                  generation=generation+1
            WHERE workspace_id=? AND candidate_id=?""",
        (DEFAULT_WORKSPACE_ID, candidate.candidate_id),
    )

    current = mappings._replace_invalid_ready(candidate, stale, None)

    assert current.status == "ready"
    assert current.avatar_json_pointer == "/user/avatar"
    assert current.evidence_kind == "observed"
    assert current.generation == 2
    store.close()


def test_validated_adapter_rows_replace_embedded_schema_pointer(
    tmp_path: Path,
) -> None:
    store, repository, candidate = _repository(tmp_path)
    value = json.loads(candidate.manifest_json)
    value["output"]["author_handle"] = {
        "pointers": ["/user/username"],
        "transforms": ["to_string"],
    }
    value["output"]["author_avatar_url"] = {
        "pointers": ["/embedded/profilePicUrlHD"],
        "transforms": ["normalize_url"],
    }
    manifest_json = json.dumps(value)
    candidate = replace(candidate, manifest_json=manifest_json)
    manifest = ActorManifest(
        actor_id=candidate.actor_id,
        build_id=str(candidate.build_id),
        build_number=str(candidate.build_number),
        manifest_json=manifest_json,
        manifest_hash=str(candidate.manifest_hash),
    )
    CandidatePresentationMappings(repository).refresh_pointer(
        candidate,
        "/embedded/profilePicUrlHD",
        evidence_kind="schema",
    )
    row = {
        "id": "item-1",
        "url": "https://www.instagram.com/p/item-1/",
        "createdAt": "2026-08-20T00:00:00Z",
        "text": "target content",
        "user": {
            "username": "openai",
            "avatar": "https://cdn.example/target.jpg",
        },
        "embedded": {
            "profilePicUrlHD": "https://cdn.example/other-person.jpg"
        },
    }
    adapter = build_default_registry().require(
        RouteKey("instagram", "profile", "items")
    )
    target = adapter.normalize_target({"target": "openai"})

    batch = validate_and_enrich_adapter_rows(
        repository,
        adapter,
        (row,),
        target,
        manifest,
        FetchWindow(1, datetime(2026, 8, 19, tzinfo=timezone.utc), None),
        candidate,
        "instagram",
    )

    mapping = repository.connection.execute(
        "SELECT * FROM actor_candidate_presentation_mappings_v2"
    ).fetchone()
    assert mapping["avatar_json_pointer"] == "/user/avatar"
    assert mapping["evidence_kind"] == "observed"
    assert mapping["generation"] == 2
    assert batch.source_avatar_url == "https://cdn.example/target.jpg"
    assert "author_avatar_url" not in batch.items[0].metadata
    store.close()


def test_failed_avatar_resolution_preserves_existing_batch_avatar(
    tmp_path: Path,
) -> None:
    store, repository, candidate = _repository(tmp_path)
    mappings = CandidatePresentationMappings(repository)
    mappings.refresh_pointer(candidate, "/owner/profile_pic_url")
    original = NormalizedBatch(
        items=(),
        semantic_outcome="valid_nonempty",
        source_avatar_url="https://cached.example/old.png",
    )

    batch = mappings.enrich_batch(
        candidate,
        "instagram",
        original,
    )

    assert batch is original
    assert batch.source_avatar_url == "https://cached.example/old.png"
    store.close()


def test_sidecar_write_failure_does_not_fail_valid_paid_batch(
    tmp_path: Path,
) -> None:
    store, repository, candidate = _repository(tmp_path)
    repository.connection.execute(
        """CREATE TRIGGER reject_avatar_sidecar_insert
           BEFORE INSERT ON actor_candidate_presentation_mappings_v2
           BEGIN SELECT RAISE(ABORT, 'sidecar unavailable'); END"""
    )
    rows = ({"owner": {"profile_pic_url": "https://cdn.example/avatar.jpg"}},)
    original = NormalizedBatch(
        items=(),
        semantic_outcome="valid_nonempty",
        source_avatar_url="https://cdn.example/avatar.jpg",
        presentation_evidence=PresentationEvidence(
            rows=rows,
            avatar_url="https://cdn.example/avatar.jpg",
            content_row_count=1,
        ),
    )

    batch = CandidatePresentationMappings(repository).enrich_batch(
        candidate,
        "instagram",
        original,
    )

    assert batch is original
    assert batch.semantic_outcome == "valid_nonempty"
    store.close()


def test_exact_revision_status_is_stale_for_old_build_mapping(
    tmp_path: Path,
) -> None:
    store, repository, candidate = _repository(tmp_path)
    repository.connection.execute(
        """INSERT INTO actor_candidate_presentation_mappings_v2 (
               workspace_id, candidate_id, build_id, output_schema_hash,
               mapping_status, avatar_json_pointer, evidence_kind,
               generation, created_at, updated_at
           ) VALUES (?, ?, 'old-build', ?, 'ready', '/avatar', 'schema', 1, ?, ?)""",
        (
            DEFAULT_WORKSPACE_ID,
            candidate.candidate_id,
            "d" * 64,
            "2026-08-27T00:00:00+00:00",
            "2026-08-27T00:00:00+00:00",
        ),
    )

    assert CandidatePresentationMappings(repository).status(candidate) == "stale"
    store.close()


def test_public_candidate_projection_exposes_status_not_pointer_or_url(
    tmp_path: Path,
) -> None:
    store, repository, candidate = _repository(tmp_path)
    CandidatePresentationMappings(repository).refresh_pointer(
        candidate, "/owner/profile_pic_url"
    )

    payload = actorops_v2_candidate_projection(repository, candidate)
    serialized = json.dumps(payload, sort_keys=True)

    assert payload["avatar_mapping_status"] == "ready"
    assert payload["compatibility_stage"] in {
        "static_ready", "sample_required", "system_usable"
    }
    assert payload["mapping_evidence"] in {"schema", "dataset"}
    assert payload["dataset_shape"] in {"flat", "nested", "mixed", "unknown"}
    assert isinstance(payload["binding_proof_count"], int)
    assert isinstance(payload["binding_required_count"], int)
    assert payload["compatibility_issue_code"] in {
        None, "binding_proof_incomplete", "route_binding_missing",
    }
    assert "profile_pic_url" not in serialized
    assert "avatar_json_pointer" not in serialized
    assert "http" not in serialized
    store.close()


def test_public_route_projection_uses_shared_operational_summary(
    tmp_path: Path,
) -> None:
    store, repository, candidate = _repository(tmp_path)
    route = repository.get_route(candidate.route_id)
    with repository.transaction():
        repository.assign_candidate(
            candidate.route_id,
            candidate.candidate_id,
            AssignmentRole.ACTIVE,
            priority=0,
            expected_route_generation=route.generation,
            expected_candidate_generation=candidate.generation,
        )

    payload = actorops_v2_route_additions(
        store, DEFAULT_WORKSPACE_ID, candidate.route_id
    )

    assert payload is not None
    assert payload["health"] == "degraded"
    assert payload["health_reason"] == "insufficient_stable_paths"
    assert payload["stable_candidate_count"] == 1
    assert payload["cooling_candidate_count"] == 0
    assert payload["at_risk_source_count"] == 1
    assert payload["unavailable_source_count"] == 0
    assert payload["fallback_source_count"] == 0
    assert payload["next_repair_at"] is None
    assert payload["maintenance_policy"]["workspace"]["authorization_origin"] == (
        "system_default"
    )
    assert payload["maintenance_policy"]["route"]["authorization_origin"] == (
        "system_default"
    )
    assert "authorized_by_user_id" not in json.dumps(
        payload["maintenance_policy"], sort_keys=True
    )
    store.close()


def test_row_observation_rejects_array_paths_and_non_string_values() -> None:
    assert avatar_pointer_from_rows(
        ({"owners": [{"profilePicUrl": "https://example.com/a.png"}]},),
        "instagram",
    ) is None
    assert avatar_pointer_from_rows(
        ({"owner": {"profilePicUrl": {"url": "https://example.com/a.png"}}},),
        "instagram",
    ) is None
    assert avatar_pointer_from_rows(
        ({"owner": {"profilePicUrl": "javascript:alert(1)"}},),
        "instagram",
    ) is None


def test_row_observation_finds_targeted_avatar_after_many_unrelated_fields() -> None:
    row: dict[str, object] = {
        f"unrelated_{index}": {"noise": f"value-{index}"}
        for index in range(300)
    }
    row["user"] = {
        "profile_pic_url": "https://cdn.example/target-avatar.jpg"
    }

    assert avatar_pointer_from_rows((row,), "instagram") == (
        "/user/profile_pic_url"
    )
