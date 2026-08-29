from __future__ import annotations

import asyncio
import hashlib
import json
from pathlib import Path

import pytest

from src.services.actorops.apify_catalog import ApifyDiscoveryCatalog
from src.services.actorops.discovery import DiscoveryCatalogError
from src.services.actorops.domain import AssignmentRole, CandidateLifecycle, CandidateRecord
from src.services.actorops.ports import DiscoveryActorMatch


class _Metadata:
    async def search_store(self, _query):
        return (
            {
                "actorId": "opaque-provider-id",
                "username": "publisher", "name": "actor",
                "title": "Tweet Actor",
                "description": "Profile timeline tweets.",
                "stats": {
                    "totalUsers": 1200, "actorReviewRating": 4.8,
                    "actorReviewCount": 19, "bookmarkCount": 31,
                },
            },
            {"actorId": "opaque-provider-id"},
        )

    async def get_actor(self, actor_id):
        assert actor_id == "publisher/actor"
        return {
            "id": "actor-1",
            "username": "Publisher",
            "isPublic": True,
            "taggedBuilds": {"latest": {"buildId": "build-1", "buildNumber": "1.0.0"}},
            "pricingInfos": [{"pricePerRunUsd": 0.02}],
        }

    async def get_build(self, build_id):
        assert build_id == "build-1"
        return {
            "id": "build-1",
            "actorId": "actor-1",
            "buildNumber": "1.0.0",
            "status": "SUCCEEDED",
            "inputSchema": {"properties": {"profile": {"type": "string"}}},
            "datasetSchema": {"properties": {"id": {"type": "string"}}},
        }


def test_apify_catalog_reads_only_public_actor_build_metadata() -> None:
    catalog = ApifyDiscoveryCatalog(_Metadata())

    assert asyncio.run(catalog.search("profile actor")) == (
        DiscoveryActorMatch(
            "opaque-provider-id", total_users=1200, rating=4.8,
            review_count=19, bookmark_count=31,
            display_name="Tweet Actor",
            short_description="Profile timeline tweets.",
        ),
    )
    revision = asyncio.run(catalog.get_revision("publisher/actor"))

    assert revision.publisher == "publisher"
    assert revision.build_id == "build-1"
    assert revision.price_per_run_usd == 0.02
    assert revision.input_schema["properties"]
    source = Path("src/services/actorops/apify_catalog.py").read_text()
    assert "run_actor" not in source
    assert ".abort" not in source
    assert "dataset_items" not in source


def test_apify_catalog_accepts_public_build_act_id_ownership() -> None:
    class _PublicBuildShape(_Metadata):
        async def get_build(self, build_id):
            build = dict(await super().get_build(build_id))
            build["actId"] = build.pop("actorId")
            return build

    revision = asyncio.run(
        ApifyDiscoveryCatalog(_PublicBuildShape()).get_revision(
            "publisher/actor"
        )
    )

    assert revision.build_id == "build-1"


def test_apify_catalog_estimates_nested_public_event_pricing() -> None:
    class _NestedPricing(_Metadata):
        async def get_actor(self, actor_id):
            actor = await super().get_actor(actor_id)
            actor["pricingInfos"] = [{
                "pricingModel": "PAY_PER_EVENT",
                "startedAt": "2026-01-01T00:00:00.000Z",
                "pricingPerEvent": {"actorChargeEvents": {
                    "apify-actor-start": {
                        "eventPriceUsd": 0.005,
                        "eventTitle": "Actor start",
                        "isOneTimeEvent": True,
                    },
                    "apify-default-dataset-item": {
                        "eventTitle": "Dataset item",
                        "isPrimaryEvent": True,
                        "eventTieredPricingUsd": {
                            "FREE": {"tieredEventPriceUsd": 0},
                            "BRONZE": {"tieredEventPriceUsd": 0.003},
                            "ENTERPRISE": {"tieredEventPriceUsd": 0.009},
                        },
                    },
                }},
            }]
            return actor

    revision = asyncio.run(ApifyDiscoveryCatalog(_NestedPricing()).get_revision("publisher/actor"))

    # The public Store payload has a one-time start charge plus a tiered primary
    # dataset event.  Discovery must use a conservative finite estimate rather
    # than rejecting the exact revision merely because the old flat price field
    # is absent.
    assert revision.price_per_run_usd == 0.014


def test_apify_catalog_uses_conservative_flat_run_price_upper_bound() -> None:
    class _ConflictingFlatPricing(_Metadata):
        async def get_actor(self, actor_id):
            actor = await super().get_actor(actor_id)
            actor["pricingInfos"] = [{
                "minimumChargeUsd": 0.005,
                "pricePerRunUsd": 0.02,
                "pricePerUnitUsd": 0.03,
            }]
            return actor

    revision = asyncio.run(
        ApifyDiscoveryCatalog(_ConflictingFlatPricing()).get_revision(
            "publisher/actor"
        )
    )

    assert revision.price_per_run_usd == 0.03


@pytest.mark.parametrize("unavailable", [
    {"isDisabled": True},
    {"isDeprecated": True},
    {"isPublic": False},
])
def test_apify_catalog_rejects_unavailable_actor_before_build_read(
    unavailable: dict[str, object],
) -> None:
    class _UnavailableActor(_Metadata):
        build_read = False

        async def get_actor(self, actor_id):
            actor = await super().get_actor(actor_id)
            actor.update(unavailable)
            return actor

        async def get_build(self, build_id):
            self.build_read = True
            return await super().get_build(build_id)

    metadata = _UnavailableActor()

    with pytest.raises(DiscoveryCatalogError) as caught:
        asyncio.run(
            ApifyDiscoveryCatalog(metadata).get_revision("publisher/actor")
        )

    assert caught.value.code == "actorops_discovery_actor_unavailable"
    assert caught.value.retryable is False
    assert metadata.build_read is False


@pytest.mark.parametrize(
    ("changed_field", "changed_value"),
    [
        ("id", "another-build"),
        ("buildNumber", "2.0.0"),
        ("status", "RUNNING"),
        ("actorId", "another-actor"),
        ("actorId", None),
        ("actId", "another-actor"),
    ],
)
def test_apify_catalog_rejects_tagged_build_mismatch(
    changed_field: str,
    changed_value: object,
) -> None:
    class _ChangedBuild(_Metadata):
        async def get_build(self, build_id):
            build = dict(await super().get_build(build_id))
            if changed_value is None:
                build.pop(changed_field)
            else:
                build[changed_field] = changed_value
            return build

    with pytest.raises(DiscoveryCatalogError) as caught:
        asyncio.run(
            ApifyDiscoveryCatalog(_ChangedBuild()).get_revision(
                "publisher/actor"
            )
        )

    assert caught.value.code == "actorops_discovery_revision_changed"
    assert caught.value.retryable is False


def test_catalog_and_preflight_reject_unverifiable_actor_ownership() -> None:
    class _MissingActorIdentity(_Metadata):
        async def get_actor(self, actor_id):
            actor = await super().get_actor(actor_id)
            actor.pop("id")
            return actor

    catalog = ApifyDiscoveryCatalog(_MissingActorIdentity())
    with pytest.raises(DiscoveryCatalogError) as caught:
        asyncio.run(catalog.get_revision("publisher/actor"))
    preflight = asyncio.run(
        catalog.verify_candidate(_candidate(), max_charge_usd=0.02)
    )

    assert caught.value.code == "actorops_discovery_revision_changed"
    assert preflight.allowed is False
    assert preflight.error_code == "actorops_maintenance_revision_changed"


def test_candidate_probe_preflight_rechecks_exact_public_revision_and_cap() -> None:
    catalog = ApifyDiscoveryCatalog(_Metadata())
    candidate = _candidate()

    assert asyncio.run(catalog.verify_candidate(candidate, max_charge_usd=0.02)).allowed is True
    result = asyncio.run(catalog.verify_candidate(candidate, max_charge_usd=0.01))
    assert result.allowed is False
    assert result.error_code == "actorops_maintenance_price_cap_exceeded"


def test_candidate_preflight_ignores_default_tag_drift_and_reads_exact_build() -> None:
    class _DefaultTagDrift(_Metadata):
        requested_builds: list[str]

        def __init__(self) -> None:
            self.requested_builds = []

        async def get_actor(self, actor_id):
            actor = dict(await super().get_actor(actor_id))
            actor["taggedBuilds"] = {
                "latest": {"buildId": "build-2", "buildNumber": "2.0.0"}
            }
            return actor

        async def get_build(self, build_id):
            self.requested_builds.append(build_id)
            build = dict(await super().get_build(build_id))
            build["tag"] = "legacy-tag"
            return build

    metadata = _DefaultTagDrift()
    result = asyncio.run(
        ApifyDiscoveryCatalog(metadata).verify_candidate(
            _candidate(), max_charge_usd=0.02
        )
    )

    assert result.allowed is True
    assert metadata.requested_builds == ["build-1"]


def test_candidate_preflight_rejects_missing_exact_build() -> None:
    class _MissingBuild(_Metadata):
        async def get_build(self, _build_id):
            raise DiscoveryCatalogError(
                "actorops_discovery_catalog_not_found", retryable=False
            )

    result = asyncio.run(
        ApifyDiscoveryCatalog(_MissingBuild()).verify_candidate(
            _candidate(), max_charge_usd=0.02
        )
    )

    assert result.allowed is False
    assert result.error_code == "actorops_maintenance_revision_changed"


def test_candidate_preflight_rejects_exact_build_identity_mismatch() -> None:
    class _ChangedBuild(_Metadata):
        async def get_build(self, build_id):
            build = dict(await super().get_build(build_id))
            build["id"] = "another-build"
            return build

    result = asyncio.run(
        ApifyDiscoveryCatalog(_ChangedBuild()).verify_candidate(
            _candidate(), max_charge_usd=0.02
        )
    )

    assert result.allowed is False
    assert result.error_code == "actorops_maintenance_revision_changed"


def test_candidate_preflight_rejects_exact_build_schema_drift() -> None:
    class _ChangedSchema(_Metadata):
        async def get_build(self, build_id):
            build = dict(await super().get_build(build_id))
            build["datasetSchema"] = {
                "properties": {"url": {"type": "string"}}
            }
            return build

    result = asyncio.run(
        ApifyDiscoveryCatalog(_ChangedSchema()).verify_candidate(
            _candidate(), max_charge_usd=0.02
        )
    )

    assert result.allowed is False
    assert result.error_code == "actorops_v2_candidate_contract_invalid"


def test_candidate_preflight_defers_when_pricing_is_unavailable() -> None:
    class _MissingPrice(_Metadata):
        async def get_actor(self, actor_id):
            actor = dict(await super().get_actor(actor_id))
            actor.pop("pricingInfos")
            return actor

    result = asyncio.run(
        ApifyDiscoveryCatalog(_MissingPrice()).verify_candidate(
            _candidate(), max_charge_usd=0.02
        )
    )

    assert result.allowed is False
    assert result.error_code == "actorops_maintenance_pricing_unavailable"


def test_apify_catalog_reads_dataset_row_schema_from_actor_definition() -> None:
    class _DefinitionMetadata(_Metadata):
        async def get_build(self, build_id):
            build = dict(await super().get_build(build_id))
            build.update({
                "inputSchema": {"properties": {"username": {"type": "string"}}},
                "actorDefinition": {"storages": {"dataset": {"fields": {
                    "type": "object", "properties": {"id": {"type": "string"}},
                }}}},
            })
            build.pop("datasetSchema")
            return build

    revision = asyncio.run(ApifyDiscoveryCatalog(_DefinitionMetadata()).get_revision("publisher/actor"))

    assert revision.input_schema["properties"] == {"username": {"type": "string"}}
    assert revision.output_schema["properties"] == {"id": {"type": "string"}}


def test_apify_catalog_reads_dataset_view_fields_as_public_row_schema() -> None:
    class _ViewMetadata(_Metadata):
        async def get_build(self, build_id):
            build = dict(await super().get_build(build_id))
            build.pop("datasetSchema")
            build["actorDefinition"] = {
                "storages": {"dataset": {"views": {"overview": {
                    "transformation": {
                        "fields": [
                            "tweetId", "tweetUrl", "createdAt", "fullText",
                            "authorHandle",
                        ]
                    },
                    "display": {"properties": {
                        "tweetUrl": {"format": "link"},
                        "createdAt": {"format": "date"},
                    }},
                }}}}
            }
            return build

    revision = asyncio.run(
        ApifyDiscoveryCatalog(_ViewMetadata()).get_revision("publisher/actor")
    )

    assert revision.output_schema["properties"] == {
        "authorHandle": {"type": "string"},
        "createdAt": {"type": "string", "format": "date-time"},
        "fullText": {"type": "string"},
        "tweetId": {"type": "string"},
        "tweetUrl": {"type": "string", "format": "uri"},
    }


def _hash(value: object) -> str:
    return hashlib.sha256(json.dumps(value, sort_keys=True, separators=(",", ":")).encode()).hexdigest()


def _candidate() -> CandidateRecord:
    return CandidateRecord(
        candidate_id="candidate", route_id="route",
        lifecycle=CandidateLifecycle.PROBATIONARY,
        assignment_role=AssignmentRole.INACTIVE, priority=None, generation=1,
        build_id="build-1", manifest_hash="m" * 64,
        actor_id="publisher/actor", publisher="publisher",
        build_number="1.0.0", manifest_json="{}",
        input_schema_hash=_hash(
            {"properties": {"profile": {"type": "string"}}}
        ),
        output_schema_hash=_hash(
            {"properties": {"id": {"type": "string"}}}
        ),
    )
