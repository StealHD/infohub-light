from __future__ import annotations

import asyncio
import hashlib
import json
from datetime import datetime, timedelta, timezone

from src.services.apify_actor_discovery import _json_hash
from src.services.apify_actor_maintenance import (
    ApifyActorMetadataMaintenance,
)
from src.services.apify_actor_ops import (
    ApifyActorOpsService,
    revision_set_hash,
    source_target_fingerprint,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


NOW = datetime(2030, 1, 1, 8, 0, tzinfo=timezone.utc)
INPUT_SCHEMA = {
    "type": "object",
    "properties": {"url": {"type": "string"}},
}
OUTPUT_SCHEMA = {
    "type": "object",
    "properties": {"id": {"type": "string"}},
}
PRICING = {
    "pricingModel": "PAY_PER_EVENT",
    "minimalMaxTotalChargeUsd": 0.01,
    "pricingPerEvent": {
        "actorChargeEvents": {
            "item": {"eventPriceUsd": 0.01},
        }
    },
}


def _manifest(actor_id: str, build_number: str) -> dict:
    return {
        "version": 1,
        "actor_id": actor_id,
        "build_number": build_number,
        "input": {"url": {"$ref": "target.canonical_url"}},
        "output": {
            "native_id": {"pointers": ["/id"]},
            "url": {
                "pointers": ["/url"],
                "transforms": ["normalize_url"],
            },
            "published_at": {
                "pointers": ["/publishedAt"],
                "transforms": ["parse_datetime"],
            },
            "title": {"pointers": ["/title"]},
            "source_native_id": {"pointers": ["/channelId"]},
        },
        "semantics": {
            "identity": {
                "output_field": "source_native_id",
                "target_ref": "target.native_id",
                "match": "exact",
            },
            "url_host_allowlist": ["youtube.com"],
        },
    }


def _ready_route(store: ServiceStore):
    ops = ApifyActorOpsService(store, now=lambda: NOW)
    route = next(
        route
        for route in ops.list_routes()
        if route["route_key"] == "youtube/channel/items"
    )
    revisions = []
    actors = (
        ("publisher-a/one", "publisher-a"),
        ("publisher-b/two", "publisher-b"),
        ("publisher-a/three", "publisher-a"),
    )
    for index, (actor_id, publisher) in enumerate(actors, start=1):
        candidate_id = ops.ensure_candidate(
            str(route["route_id"]),
            actor_id=actor_id,
        )
        revision_id = ops.create_adapter_revision(
            candidate_id=candidate_id,
            actor_id=actor_id,
            publisher=publisher,
            build_id=f"build-{index}",
            build_number=f"1.0.{index}",
            manifest=_manifest(actor_id, f"1.0.{index}"),
            input_schema_hash=_json_hash(INPUT_SCHEMA),
            output_schema_hash=_json_hash(OUTPUT_SCHEMA),
            pricing=PRICING,
            permission_level="LIMITED_PERMISSIONS",
            lifecycle="static_valid",
        )
        store.connect().execute(
            """
            UPDATE apify_actor_adapter_revisions
            SET lifecycle = ?
            WHERE revision_id = ?
            """,
            (
                "certified" if index < 3 else "probationary",
                revision_id,
            ),
        )
        store.connect().commit()
        revisions.append(revision_id)
    route = ops.get_route(str(route["route_id"]))
    ops.replace_active_pool(
        str(route["route_id"]),
        slots={
            "primary": revisions[0],
            "backup_1": revisions[1],
            "backup_2": revisions[2],
        },
        expected_generation=int(route["generation"]),
    )
    return ops, ops.get_route(str(route["route_id"])), revisions


class _Metadata:
    def __init__(self) -> None:
        self.default_builds = {
            "publisher-a/one": ("build-1", "1.0.1"),
            "publisher-b/two": ("build-2", "1.0.2"),
            "publisher-a/three": ("build-3", "1.0.3"),
        }
        self.schemas = {
            "build-1": (INPUT_SCHEMA, OUTPUT_SCHEMA),
            "build-2": (INPUT_SCHEMA, OUTPUT_SCHEMA),
            "build-3": (INPUT_SCHEMA, OUTPUT_SCHEMA),
        }
        self.views = {
            "build-1": {"overview": {"title": "Overview"}},
            "build-2": {"overview": {"title": "Overview"}},
            "build-3": {"overview": {"title": "Overview"}},
        }
        self.missing_permissions: set[str] = set()
        self.missing_pricing: set[str] = set()
        self.calls: list[tuple[str, str]] = []

    async def get_actor(self, actor_id: str):
        self.calls.append(("actor", actor_id))
        build_id, build_number = self.default_builds[actor_id]
        publisher, name = actor_id.split("/", 1)
        actor = {
            "id": f"opaque-{name}",
            "username": publisher,
            "name": name,
            "isPublic": True,
            "isRunnable": True,
            "isDeprecated": False,
            "actorPermissionLevel": "LIMITED_PERMISSIONS",
            "taggedBuilds": {
                "latest": {
                    "buildId": build_id,
                    "buildNumber": build_number,
                }
            },
            "pricingInfos": [
                {
                    "startedAt": "2020-01-01T00:00:00Z",
                    **PRICING,
                }
            ],
            "README": "must never be persisted or sent to AI",
        }
        if actor_id in self.missing_permissions:
            actor.pop("actorPermissionLevel")
        if actor_id in self.missing_pricing:
            actor["pricingInfos"] = []
        return actor

    async def get_build(self, build_id: str):
        self.calls.append(("build", build_id))
        input_schema, output_schema = self.schemas[build_id]
        number = build_id.rsplit("-", 1)[1]
        return {
            "status": "SUCCEEDED",
            "buildNumber": f"1.0.{number}",
            "inputSchema": json.dumps(input_schema),
            "actorDefinition": {
                "storages": {
                    "dataset": {
                        "actorSpecification": 1,
                        "fields": output_schema,
                        "views": self.views[build_id],
                    }
                }
            },
        }


def test_metadata_check_is_due_once_and_unchanged_creates_no_proposal(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    _ops, route, _revisions = _ready_route(store)
    metadata = _Metadata()

    first = asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            lambda _workspace_id: metadata,
            now=lambda: NOW,
        ).run_if_due()
    )
    second = asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            lambda _workspace_id: metadata,
            now=lambda: NOW + timedelta(hours=1),
        ).run_if_due()
    )

    assert first == {
        "claimed": 1,
        "unchanged": 1,
        "changed": 0,
        "quarantined": 0,
        "stale": 0,
        "failed": 0,
    }
    assert second["claimed"] == 0
    assert len(metadata.calls) == 6
    assert (
        store.connect().execute(
            """
            SELECT COUNT(*)
            FROM apify_actor_discovery_runs
            WHERE route_id = ?
            """,
            (route["route_id"],),
        ).fetchone()[0]
        == 0
    )


def test_default_build_change_proposes_without_replacing_pinned_revision(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_route(store)
    metadata = _Metadata()
    asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            lambda _workspace_id: metadata,
            now=lambda: NOW,
        ).run_if_due()
    )
    metadata.default_builds["publisher-a/one"] = ("build-new", "2.0.0")

    result = asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            lambda _workspace_id: metadata,
            now=lambda: NOW + timedelta(days=8),
        ).run_if_due()
    )

    assert result["changed"] == 1
    current = ops.get_route(str(route["route_id"]))
    assert current["generation"] == route["generation"]
    assert current["slots"][0]["revision_id"] == revisions[0]
    assert current["slots"][0]["build_number"] == "1.0.1"
    proposal = store.connect().execute(
        """
        SELECT stage, trigger_reason
        FROM apify_actor_discovery_runs
        WHERE route_id = ?
        """,
        (route["route_id"],),
    ).fetchone()
    assert proposal["stage"] == "queued"
    assert "actor_default_build_changed" in proposal["trigger_reason"]
    ops.update_discovery_run(
        store.connect().execute(
            """
            SELECT run_id
            FROM apify_actor_discovery_runs
            WHERE route_id = ?
            """,
            (route["route_id"],),
        ).fetchone()["run_id"],
        expected_stage="queued",
        stage="failed",
    )
    repeated = asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            lambda _workspace_id: metadata,
            now=lambda: NOW + timedelta(days=16),
        ).run_if_due()
    )
    assert repeated["unchanged"] == 1
    assert store.connect().execute(
        """
        SELECT COUNT(*)
        FROM apify_actor_discovery_runs
        WHERE route_id = ?
        """,
        (route["route_id"],),
    ).fetchone()[0] == 1


def test_dataset_presentation_view_change_is_not_contract_drift(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_route(store)
    metadata = _Metadata()
    asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            lambda _workspace_id: metadata,
            now=lambda: NOW,
        ).run_if_due()
    )
    metadata.views["build-1"] = {
        "overview": {
            "title": "Renamed presentation only",
            "transformation": {"fields": ["title"]},
        }
    }

    result = asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            lambda _workspace_id: metadata,
            now=lambda: NOW + timedelta(days=8),
        ).run_if_due()
    )

    assert result["unchanged"] == 1
    assert result["quarantined"] == 0
    assert ops.get_route(str(route["route_id"]))["generation"] == (
        route["generation"]
    )
    assert ops.get_revision(revisions[0])["lifecycle"] == "certified"
    assert store.connect().execute(
        """
        SELECT COUNT(*)
        FROM apify_actor_discovery_runs
        WHERE route_id = ?
        """,
        (route["route_id"],),
    ).fetchone()[0] == 0


def test_exact_schema_drift_quarantines_and_fences_route_and_binding(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_route(store)
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="rss",
        display_name="YouTube",
        config={
            "url": (
                "https://www.youtube.com/feeds/videos.xml?"
                "channel_id=UCabcdefghijklmnopqrstuv"
            )
        },
    )
    target = store.get_source(source_id)["config"]["url"]
    binding = ops.bind_source(
        source_id=source_id,
        route_id=str(route["route_id"]),
        target_fingerprint=source_target_fingerprint(
            DEFAULT_WORKSPACE_ID,
            str(route["route_id"]),
            target,
            platform="youtube",
        ),
        mode="fallback",
    )
    store.connect().execute(
        """
        UPDATE apify_source_route_bindings
        SET validation_status = 'ready_3of3',
            verified_revision_set_hash = ?
        WHERE binding_id = ?
        """,
        (
            revision_set_hash(
                {
                    "primary": revisions[0],
                    "backup_1": revisions[1],
                    "backup_2": revisions[2],
                }
            ),
            binding["binding_id"],
        ),
    )
    store.connect().commit()
    snapshot = ops.freeze_execution(
        str(route["route_id"]),
        source_id=source_id,
    )
    metadata = _Metadata()
    metadata.schemas["build-3"] = (
        INPUT_SCHEMA,
        {
            "type": "object",
            "properties": {"changed": {"type": "number"}},
        },
    )

    result = asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            lambda _workspace_id: metadata,
            now=lambda: NOW,
        ).run_if_due(force=True)
    )

    assert result["quarantined"] == 1
    current = ops.get_route(str(route["route_id"]))
    assert current["generation"] == int(route["generation"]) + 1
    assert current["runtime"]["allowed"] is True
    assert current["runtime"]["runnable_count"] == 2
    assert ops.get_revision(revisions[2])["lifecycle"] == "quarantined"
    assert ops.get_source_binding(source_id)["validation_status"] == (
        "revalidation_pending"
    )
    try:
        ops.assert_publishable(snapshot)
    except Exception as exc:
        assert getattr(exc, "code", "") == "apify_actor_publication_stale"
    else:
        raise AssertionError("quarantined revision did not fence publication")


def test_youtube_fallback_remains_available_with_one_safe_revision(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_route(store)
    metadata = _Metadata()
    metadata.missing_permissions.add("publisher-a/one")
    metadata.missing_pricing.add("publisher-b/two")

    result = asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            lambda _workspace_id: metadata,
            now=lambda: NOW,
        ).run_if_due(force=True)
    )

    assert result["quarantined"] == 1
    assert ops.get_revision(revisions[0])["lifecycle"] == "quarantined"
    assert ops.get_revision(revisions[1])["lifecycle"] == "quarantined"
    current = ops.get_route(str(route["route_id"]))
    assert current["runtime"]["allowed"] is True
    assert current["runtime"]["runnable_count"] == 1


def test_official_pricing_cannot_be_hidden_by_top_level_spoof(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_route(store)

    class SpoofedPricingMetadata(_Metadata):
        async def get_actor(self, actor_id: str):
            actor = await super().get_actor(actor_id)
            if actor_id == "publisher-a/one":
                actor["pricing"] = {"pricingModel": "FREE"}
                actor["pricingInfos"] = [
                    {
                        "startedAt": "2020-01-01T00:00:00Z",
                        "pricingModel": "PAY_PER_EVENT",
                        "pricingPerEvent": {
                            "actorChargeEvents": {
                                "item": {"eventPriceUsd": 0.50},
                            }
                        },
                    }
                ]
            return actor

    result = asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            lambda _workspace_id: SpoofedPricingMetadata(),
            now=lambda: NOW,
        ).run_if_due(force=True)
    )

    assert result["quarantined"] == 1
    assert ops.get_revision(revisions[0])["lifecycle"] == "quarantined"
    current = ops.get_route(str(route["route_id"]))
    assert current["runtime"]["runnable_count"] == 2


def test_oversized_tier_prices_quarantine_instead_of_aborting_maintenance(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops, route, revisions = _ready_route(store)
    oversized = 10**400

    class OversizedTierMetadata(_Metadata):
        async def get_actor(self, actor_id: str):
            actor = await super().get_actor(actor_id)
            if actor_id == "publisher-a/one":
                pricing = {
                    "pricingModel": "PAY_PER_EVENT",
                    "pricingPerEvent": {
                        "actorChargeEvents": {
                            "item": {
                                "eventTieredPricingUsd": {
                                    "FREE": {
                                        "tieredEventPriceUsd": oversized,
                                    }
                                }
                            }
                        }
                    },
                }
            elif actor_id == "publisher-b/two":
                pricing = {
                    "pricingModel": "PRICE_PER_DATASET_ITEM",
                    "tieredPricing": {
                        "FREE": {"tieredPricePerUnitUsd": oversized},
                    },
                }
            else:
                return actor
            actor["pricingInfos"] = [
                {"startedAt": "2020-01-01T00:00:00Z", **pricing}
            ]
            return actor

    result = asyncio.run(
        ApifyActorMetadataMaintenance(
            store,
            lambda _workspace_id: OversizedTierMetadata(),
            now=lambda: NOW,
        ).run_if_due(force=True)
    )

    assert result["quarantined"] == 1
    assert ops.get_revision(revisions[0])["lifecycle"] == "quarantined"
    assert ops.get_revision(revisions[1])["lifecycle"] == "quarantined"
    current = ops.get_route(str(route["route_id"]))
    assert current["runtime"]["allowed"] is True
    assert current["runtime"]["runnable_count"] == 1
