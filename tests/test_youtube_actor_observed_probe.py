"""Regression coverage for the YouTube observed-output certification path."""

from __future__ import annotations

import hashlib

import pytest

from src.services.apify_actor_manifest import (
    ActorManifestError,
    ActorRuntime,
    ActorTarget,
    map_actor_output,
)
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


@pytest.mark.parametrize(
    "row",
    [
        _content_row(channelId="not-the-target"),
        _content_row(videoUrl="https://www.youtube.com/@YouTube"),
        _content_row(videoUrl="https://www.youtube.com/watch?v=other"),
    ],
)
def test_observed_probe_rejects_metadata_wrong_identity_or_mismatched_video(row: dict) -> None:
    with pytest.raises(ActorManifestError, match="matching YouTube content") as caught:
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
