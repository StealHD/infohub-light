"""Regression coverage for the YouTube observed-output certification path."""

from __future__ import annotations

import asyncio
import hashlib
import json

import pytest

from src.services.apify_actor_manifest import (
    ActorManifestError,
    ActorRuntime,
    ActorTarget,
    map_actor_output,
)
from src.services.apify_actor_discovery import ApifyActorDiscoveryService
from src.services.apify_actor_observed_probe import (
    can_observe_youtube_probe,
    map_canary_output,
    observed_manifest_with_identity,
    promote_observed_youtube_revision,
)
from src.services.apify_actor_ops import (
    PAID_CANARY_CONFIRMATION,
    ApifyActorOpsService,
)
from src.services.apify_actor_youtube_observation_discovery import (
    observation_probe_deterministic_failure,
    observation_probe_eligible,
    observation_probe_manifest_hash,
)
from src.storage.service_store import ServiceStore
from test_apify_actor_pool_staging_v18 import FIXED_NOW, _route


ACTOR_ID = "grow_media/youtube-channel"
BUILD_NUMBER = "1.2.3"
TARGET = ActorTarget(
    canonical_url="https://www.youtube.com/@YouTube",
    native_id="UCBR8-60-B28hp2BmDPdntcQ",
    handle="YouTube",
)


def _placeholder_manifest() -> dict:
    return {
        "version": 1,
        "actor_id": ACTOR_ID,
        "build_number": BUILD_NUMBER,
        "input": {"channelUrls": [{"$ref": "target.canonical_url"}]},
        "output": {
            "native_id": {"pointers": ["/__probe_native_id"]},
            "url": {"pointers": ["/__probe_url"]},
            "published_at": {"pointers": ["/__probe_published_at"]},
            "title": {"pointers": ["/__probe_title"]},
            "source_native_id": {"pointers": ["/__probe_source_native_id"]},
        },
        "semantics": {
            "identity": {
                "output_field": "source_native_id",
                "target_ref": "target.native_id",
                "match": "exact",
            },
            "url_host_allowlist": ["youtube.com", "youtu.be"],
        },
    }


def _evidence() -> dict:
    return {"exact_successful_build": True, "input_validation": True}


def _content_row(**overrides: object) -> dict:
    row: dict[str, object] = {
        "videoId": "abC_123",
        "videoUrl": "https://www.youtube.com/watch?v=abC_123",
        "publishedAt": "2026-08-18T01:02:03Z",
        "title": "A real public video",
        "channelId": TARGET.native_id,
    }
    row.update(overrides)
    return row


def test_observed_probe_accepts_only_matching_content_and_mints_standard_manifest() -> None:
    placeholder = _placeholder_manifest()

    assert can_observe_youtube_probe(
        platform="youtube", target_type="channel", capability="items",
        manifest=placeholder, security_evidence=_evidence(),
    )
    mapped, draft = map_canary_output(
        placeholder, [_content_row()], TARGET, ActorRuntime(max_items=1),
        platform="youtube", target_type="channel", capability="items",
        security_evidence=_evidence(),
    )

    assert mapped.semantic_outcome == "valid_nonempty"
    assert draft is not None
    observed = observed_manifest_with_identity(
        draft, actor_id=ACTOR_ID, build_number=BUILD_NUMBER,
        input_template=placeholder["input"],
    )
    remapped = map_actor_output(observed, [_content_row()], TARGET, ActorRuntime())
    assert remapped.items[0].native_id == "abC_123"
    assert observed["output"]["native_id"]["pointers"] == ["/videoId"]
    assert "__probe" not in str(observed)


def test_observed_probe_accepts_a_video_row_with_nested_channel_identity() -> None:
    row = _content_row()
    row.pop("channelId")
    row["channel"] = {
        "id": TARGET.native_id,
        "handle": "@YouTube",
        "url": TARGET.canonical_url,
    }

    mapped, draft = map_canary_output(
        _placeholder_manifest(), [row], TARGET, ActorRuntime(max_items=1),
        platform="youtube", target_type="channel", capability="items",
        security_evidence=_evidence(),
    )

    assert mapped.semantic_outcome == "valid_nonempty"
    assert draft is not None
    assert draft["output"]["source_native_id"]["pointers"] == ["/channel/id"]


def test_promoted_manifest_skips_channel_metadata_before_a_content_row() -> None:
    manifest = _placeholder_manifest()
    manifest["output"] = {
        "native_id": {"pointers": ["/videoId"], "transforms": ["to_string"]},
        "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
        "published_at": {"pointers": ["/publishedAt"], "transforms": ["parse_datetime"]},
        "title": {"pointers": ["/title"], "transforms": ["to_string"]},
        "source_native_id": {"pointers": ["/channelId"], "transforms": ["to_string"]},
    }
    metadata = {
        "channelId": TARGET.native_id,
        "title": "Channel profile metadata",
        "url": TARGET.canonical_url,
    }
    content = _content_row(url="https://www.youtube.com/watch?v=abC_123")

    result = map_actor_output(
        manifest, [metadata, content], TARGET, ActorRuntime(max_items=1)
    )

    assert result.semantic_outcome == "valid_nonempty"
    assert [item.native_id for item in result.items] == ["abC_123"]
    assert result.excluded_rows == 1


def test_observed_probe_classifies_demo_rows_as_placeholders() -> None:
    with pytest.raises(ActorManifestError) as caught:
        map_canary_output(
            _placeholder_manifest(), [{"demo": True}], TARGET,
            ActorRuntime(max_items=1), platform="youtube",
            target_type="channel", capability="items",
            security_evidence=_evidence(),
        )

    assert caught.value.code == "apify_actor_placeholder"


@pytest.mark.parametrize(
    "row",
    [
        _content_row(channelId="not-the-target"),
        _content_row(videoUrl="https://www.youtube.com/@YouTube"),
        _content_row(videoUrl="https://www.youtube.com/watch?v=other"),
    ],
)
def test_observed_probe_rejects_metadata_wrong_identity_or_mismatched_video(row: dict) -> None:
    with pytest.raises(ActorManifestError, match="matching content") as caught:
        map_canary_output(
            _placeholder_manifest(), [row], TARGET, ActorRuntime(),
            platform="youtube", target_type="channel", capability="items",
            security_evidence=_evidence(),
        )
    assert caught.value.code == "apify_actor_contract_mismatch"


def test_promoting_observed_output_repoints_settled_validation_to_immutable_build(tmp_path) -> None:
    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    route = _route(store, "youtube/channel/items")
    route_id = str(route["route_id"])
    run = ops.create_discovery_run(
        route_id, trigger_reason="observed-output", expected_generation=int(route["generation"]),
    )
    candidate_id = ops.ensure_candidate(route_id, actor_id=ACTOR_ID)
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id, actor_id=ACTOR_ID, publisher="grow_media",
        build_id="build-1.2.3", build_number=BUILD_NUMBER,
        manifest=_placeholder_manifest(),
        input_schema_hash=hashlib.sha256(b"input").hexdigest(),
        output_schema_hash=hashlib.sha256(b"output").hexdigest(),
        security_evidence=_evidence(), discovery_run_id=str(run["run_id"]),
    )
    ops.update_discovery_run(
        str(run["run_id"]), expected_stage="queued", stage="awaiting_canary_approval",
    )
    approval = ops.approve_revision_canary(
        route_id, revision_id, expected_generation=int(route["generation"]),
        approval_id="observed-output-test", confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.01, reference_fingerprint=hashlib.sha256(b"youtube-reference").hexdigest(),
        discovery_run_id=str(run["run_id"]),
    )
    ops.record_validation(
        str(approval["validation_id"]), status="succeeded", semantic_outcome="valid_nonempty",
        cost_usd=0.01, cost_final=True,
    )
    _, draft = map_canary_output(
        _placeholder_manifest(), [_content_row()], TARGET, ActorRuntime(),
        platform="youtube", target_type="channel", capability="items", security_evidence=_evidence(),
    )
    assert draft is not None
    observed = observed_manifest_with_identity(
        draft, actor_id=ACTOR_ID, build_number=BUILD_NUMBER,
        input_template=_placeholder_manifest()["input"],
    )

    promoted = promote_observed_youtube_revision(
        ops, validation_id=str(approval["validation_id"]), manifest=observed,
    )

    assert promoted["revision_id"] != revision_id
    row = store.connect().execute(
        """SELECT lifecycle, observed_manifest, manifest_json, build_id, build_number
           FROM apify_actor_adapter_revisions WHERE revision_id = ?""",
        (promoted["revision_id"],),
    ).fetchone()
    assert row is not None
    assert (row["lifecycle"], row["observed_manifest"]) == ("probationary", 1)
    assert (row["build_id"], row["build_number"]) == ("build-1.2.3", BUILD_NUMBER)
    assert "__probe" not in str(row["manifest_json"])
    store.connect().execute(
        """UPDATE apify_route_active_slots
           SET candidate_id = ?, revision_id = ?
           WHERE workspace_id = ? AND route_id = ? AND slot_name = 'primary'""",
        (candidate_id, str(promoted["revision_id"]), ops.workspace_id, route_id),
    )
    store.connect().commit()
    frozen = ops.freeze_execution(route_id, enforce_gate=False)
    assert frozen.slots[0].observed_manifest is True
    assert frozen.slots[0].manifest is not None
    assert frozen.slots[0].manifest.build_number == BUILD_NUMBER


def test_discovery_sends_only_safe_opaque_youtube_build_to_observed_canary(tmp_path) -> None:
    class OpaqueYoutubeMetadata:
        def __init__(self) -> None:
            self.validations: list[dict] = []

        async def search_store(self, _query: str):
            return [{"actorId": ACTOR_ID}]

        async def get_actor(self, _actor_id: str):
            return {
                "id": "youtube-opaque-actor",
                "username": "grow_media",
                "name": "youtube-channel",
                "isPublic": True,
                "isRunnable": True,
                "isDeprecated": False,
                "actorPermissionLevel": "LIMITED_PERMISSIONS",
                "taggedBuilds": {"latest": {"buildId": "build-1.2.3", "buildNumber": BUILD_NUMBER}},
                "pricingInfos": [{
                    "startedAt": "2020-01-01T00:00:00Z",
                    "pricingModel": "PAY_PER_EVENT",
                    "minimalMaxTotalChargeUsd": 0.01,
                    "pricingPerEvent": {"actorChargeEvents": {"video": {"eventPriceUsd": 0.001}}},
                }],
            }

        async def get_build(self, _build_id: str):
            return {
                "status": "SUCCEEDED",
                "buildNumber": BUILD_NUMBER,
                "inputSchema": json.dumps({"type": "object", "properties": {"url": {"type": "string"}, "maxItems": {"type": "integer"}}}),
                "actorDefinition": {"storages": {"dataset": {"actorSpecification": 1, "fields": {}}}},
            }

        async def validate_input(self, _actor_id: str, _build_number: str, actor_input: dict):
            self.validations.append(dict(actor_input))
            return True

    store = ServiceStore(tmp_path)
    store.initialize()
    ops = ApifyActorOpsService(store, now=lambda: FIXED_NOW)
    ops.patch_discovery_settings(
        expected_generation=1,
        enabled=True,
        call_limit=3,
    )
    route = _route(store, "youtube/channel/items")
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="manual_slot_candidate_refresh",
        expected_generation=int(route["generation"]),
    )
    metadata = OpaqueYoutubeMetadata()

    async def unexpected_ai(_prompt: dict):
        raise AssertionError("opaque YouTube Build must not spend an AI proposal")

    outcome = asyncio.run(
        ApifyActorDiscoveryService(ops, metadata, unexpected_ai).run_discovery(
            str(run["run_id"]), queries=["youtube channel"]
        )
    )

    assert outcome.stage == "awaiting_canary_approval"
    assert outcome.rejected == ()
    assert len(outcome.revision_ids) == 1
    revision_id = outcome.revision_ids[0]
    revision = ops.get_revision(revision_id)
    manifest = json.loads(store.connect().execute(
        "SELECT manifest_json FROM apify_actor_adapter_revisions WHERE revision_id = ?",
        (revision_id,),
    ).fetchone()["manifest_json"])
    assert "__probe_" in str(manifest)
    assert revision["security_evidence"]["output_schema_proves_items"] is False
    assert metadata.validations and metadata.validations[0]["maxItems"] == 1
    history = store.connect().execute(
        """SELECT policy_mode, stage, outcome FROM apify_actor_evaluation_history
           WHERE workspace_id = ? AND candidate_id = ? ORDER BY rowid""",
        (ops.workspace_id, str(revision["candidate_id"])),
    ).fetchall()
    assert {(row["policy_mode"], row["stage"], row["outcome"]) for row in history} >= {
        ("standard", "static_validation", "passed"),
        ("standard", "input_validation", "passed"),
    }
    candidate = store.connect().execute(
        "SELECT state FROM apify_actor_candidates WHERE id = ?",
        (str(revision["candidate_id"]),),
    ).fetchone()
    assert candidate is not None and candidate["state"] == "disabled"

    approval = ops.approve_revision_canary(
        str(route["route_id"]), revision_id,
        expected_generation=int(route["generation"]),
        approval_id="opaque-youtube-test",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.01,
        reference_fingerprint=hashlib.sha256(b"youtube-reference").hexdigest(),
        discovery_run_id=str(run["run_id"]),
    )
    ops.record_validation(
        str(approval["validation_id"]), status="succeeded",
        semantic_outcome="valid_nonempty", cost_usd=0.01, cost_final=True,
    )
    _, draft = map_canary_output(
        manifest, [_content_row()], TARGET, ActorRuntime(max_items=1),
        platform="youtube", target_type="channel", capability="items",
        security_evidence=revision["security_evidence"],
    )
    assert draft is not None
    promoted = promote_observed_youtube_revision(
        ops,
        validation_id=str(approval["validation_id"]),
        manifest=observed_manifest_with_identity(
            draft, actor_id=ACTOR_ID, build_number=BUILD_NUMBER,
            input_template=manifest["input"],
        ),
    )
    assert promoted["revision_id"] != revision_id
    assert store.connect().execute(
        "SELECT state FROM apify_actor_candidates WHERE id = ?",
        (str(revision["candidate_id"]),),
    ).fetchone()["state"] == "probationary"

    failed_run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="manual_slot_candidate_refresh",
        expected_generation=int(route["generation"]),
    )
    failed_revision = ops.create_adapter_revision(
        candidate_id=str(revision["candidate_id"]), actor_id=ACTOR_ID,
        publisher="grow_media", build_id=str(revision["build_id"]),
        build_number=BUILD_NUMBER, manifest=manifest,
        input_schema_hash=str(revision["input_schema_hash"]),
        output_schema_hash=str(revision["output_schema_hash"]),
        pricing=revision["pricing"],
        security_evidence=revision["security_evidence"],
        discovery_run_id=str(failed_run["run_id"]),
    )
    ops.update_discovery_run(
        str(failed_run["run_id"]), expected_stage="queued",
        stage="awaiting_canary_approval",
    )
    failed_approval = ops.approve_revision_canary(
        str(route["route_id"]), failed_revision,
        expected_generation=int(route["generation"]),
        approval_id="opaque-youtube-failure", confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.01,
        reference_fingerprint=hashlib.sha256(b"youtube-reference-failure").hexdigest(),
        discovery_run_id=str(failed_run["run_id"]),
    )
    ops.record_validation(
        str(failed_approval["validation_id"]), status="failed",
        semantic_outcome="apify_actor_contract_mismatch",
        cost_usd=0.01, cost_final=True,
    )
    assert observation_probe_deterministic_failure(
        store.connect(), workspace_id=ops.workspace_id, route_id=str(route["route_id"]),
        candidate_id=str(revision["candidate_id"]), actor_id=ACTOR_ID,
        build_id=str(revision["build_id"]), build_number=BUILD_NUMBER,
        input_schema_hash=str(revision["input_schema_hash"]),
        output_schema_hash=str(revision["output_schema_hash"]),
        manifest_hash=observation_probe_manifest_hash(
            actor_id=ACTOR_ID,
            build_number=BUILD_NUMBER,
            input_template=manifest["input"],
        ),
        pricing={**revision["pricing"], "minimalMaxTotalChargeUsd": 0.009},
    ) is None
    assert observation_probe_deterministic_failure(
        store.connect(), workspace_id=ops.workspace_id, route_id=str(route["route_id"]),
        candidate_id=str(revision["candidate_id"]), actor_id=ACTOR_ID,
        build_id=str(revision["build_id"]), build_number=BUILD_NUMBER,
        input_schema_hash=str(revision["input_schema_hash"]),
        output_schema_hash=str(revision["output_schema_hash"]),
        manifest_hash=hashlib.sha256(b"changed-youtube-input-contract").hexdigest(),
        pricing=revision["pricing"],
    ) is None
    replay = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="manual_slot_candidate_refresh",
        expected_generation=int(route["generation"]),
    )
    repeated = asyncio.run(
        ApifyActorDiscoveryService(ops, metadata, unexpected_ai).run_discovery(
            str(replay["run_id"]), queries=["youtube channel"]
        )
    )
    assert repeated.stage == "candidate_shortfall"
    assert repeated.revision_ids == ()
    assert repeated.rejected == ({
        "actor_id": ACTOR_ID,
        "reason": "actor_evaluation_deterministic_failure",
    },)
    assert len(metadata.validations) == 1


def test_observation_probe_is_available_to_items_route_combinations() -> None:
    for platform, target_type, capability in (
        ("youtube", "channel", "items"),
        ("x", "profile", "items"),
        ("instagram", "profile", "items"),
    ):
        assert observation_probe_eligible(
            platform=platform, target_type=target_type, capability=capability,
            output_schema_proves_items=False,
        )
    for platform, target_type, capability in (
        ("youtube", "profile", "items"),
        ("youtube", "channel", "profile"),
        ("x", "channel", "items"),
        ("instagram", "channel", "items"),
    ):
        assert not observation_probe_eligible(
            platform=platform, target_type=target_type, capability=capability,
            output_schema_proves_items=False,
        )


X_TARGET = ActorTarget(
    canonical_url="https://x.com/someuser",
    native_id="123456789",
    handle="someuser",
)
IG_TARGET = ActorTarget(
    canonical_url="https://www.instagram.com/someuser/",
    native_id="12345",
    handle="someuser",
)


def _handle_placeholder(actor_id: str, hosts: list[str]) -> dict:
    return {
        "version": 1,
        "actor_id": actor_id,
        "build_number": "1.0.0",
        "input": {"handle": [{"$ref": "target.handle"}]},
        "output": {
            "native_id": {"pointers": ["/__probe_native_id"]},
            "url": {"pointers": ["/__probe_url"]},
            "published_at": {"pointers": ["/__probe_published_at"]},
            "text": {"pointers": ["/__probe_text"]},
            "author_handle": {"pointers": ["/__probe_author_handle"]},
        },
        "semantics": {
            "identity": {
                "output_field": "author_handle",
                "target_ref": "target.handle",
                "match": "handle",
            },
            "url_host_allowlist": hosts,
        },
    }


def _x_content_row(**overrides: object) -> dict:
    row: dict[str, object] = {
        "tweetId": "123456789",
        "tweetUrl": "https://x.com/someuser/status/123456789",
        "createdAt": "2026-08-18T01:02:03Z",
        "text": "A real tweet",
        "username": "someuser",
    }
    row.update(overrides)
    return row


def _ig_content_row(**overrides: object) -> dict:
    row: dict[str, object] = {
        "postId": "12345",
        "postUrl": "https://www.instagram.com/p/abc123/",
        "timestamp": "2026-08-18T01:02:03Z",
        "caption": "A real post",
        "username": "someuser",
    }
    row.update(overrides)
    return row


def test_observed_probe_accepts_x_post_row_and_mints_handle_manifest() -> None:
    placeholder = _handle_placeholder("publisher/x-posts", ["x.com", "twitter.com"])
    assert can_observe_youtube_probe(
        platform="x", target_type="profile", capability="items",
        manifest=placeholder, security_evidence=_evidence(),
    )
    mapped, draft = map_canary_output(
        placeholder, [_x_content_row()], X_TARGET, ActorRuntime(max_items=1),
        platform="x", target_type="profile", capability="items",
        security_evidence=_evidence(),
    )
    assert mapped.semantic_outcome == "valid_nonempty"
    assert draft is not None
    assert draft["output"]["native_id"]["pointers"] == ["/tweetId"]
    assert draft["output"]["author_handle"]["pointers"] == ["/username"]
    assert draft["semantics"]["identity"]["match"] == "handle"


def test_observed_probe_accepts_instagram_post_row_and_mints_handle_manifest() -> None:
    placeholder = _handle_placeholder("publisher/ig-posts", ["instagram.com"])
    mapped, draft = map_canary_output(
        placeholder, [_ig_content_row()], IG_TARGET, ActorRuntime(max_items=1),
        platform="instagram", target_type="profile", capability="items",
        security_evidence=_evidence(),
    )
    assert mapped.semantic_outcome == "valid_nonempty"
    assert draft is not None
    assert draft["output"]["native_id"]["pointers"] == ["/postId"]
    assert draft["output"]["author_handle"]["pointers"] == ["/username"]


def test_observed_probe_rejects_x_row_with_wrong_handle() -> None:
    placeholder = _handle_placeholder("publisher/x-posts", ["x.com", "twitter.com"])
    with pytest.raises(ActorManifestError, match="matching content"):
        map_canary_output(
            placeholder, [_x_content_row(username="someoneelse")], X_TARGET,
            ActorRuntime(), platform="x", target_type="profile",
            capability="items", security_evidence=_evidence(),
        )


def test_observed_probe_accepts_nested_x_tweets_with_url_derived_id() -> None:
    placeholder = _handle_placeholder("publisher/x-tweets", ["x.com", "twitter.com"])
    row = {
        "count": 1,
        "pages": 1,
        "tweets": [
            {
                "author": "someuser",
                "snippet": "A real tweet",
                "date": "2026-04-04 21:33:51",
                "url": "https://twitter.com/someuser/status/2040543394741838265",
            }
        ],
    }
    mapped, draft = map_canary_output(
        placeholder, [row], X_TARGET, ActorRuntime(max_items=1),
        platform="x", target_type="profile", capability="items",
        security_evidence=_evidence(),
    )
    assert mapped.semantic_outcome == "valid_nonempty"
    assert mapped.items[0].native_id == "2040543394741838265"
    assert draft is not None
    assert draft["output"]["text"]["pointers"] == ["/tweets/0/snippet"]
    assert draft["output"]["author_handle"]["pointers"] == ["/tweets/0/author"]
