"""AI-assisted output mapping remains value-free and candidate-local."""

import asyncio
import json
from types import SimpleNamespace

import pytest

from src.services.apify_actor_canary_output_mapping import map_validation_output
from src.services.apify_actor_manifest import (
    ActorManifestError,
    ActorRuntime,
    ActorTarget,
    parse_actor_manifest,
)


def _manifest() -> dict:
    return {
        "version": 1,
        "actor_id": "publisher/weird-youtube-output",
        "build_number": "7.4.2",
        "input": {"url": {"$ref": "target.canonical_url"}},
        "output": {
            "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
            "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
            "published_at": {"pointers": ["/published"], "transforms": ["parse_datetime"]},
            "title": {"pointers": ["/title"], "transforms": ["to_string"]},
            "source_native_id": {"pointers": ["/channel"], "transforms": ["to_string"]},
        },
        "semantics": {
            "identity": {"output_field": "source_native_id", "target_ref": "target.native_id", "match": "exact"},
            "url_host_allowlist": ["youtube.com"],
        },
    }


class _Repairer:
    def __init__(self, proposal: dict) -> None:
        self.proposal = proposal
        self.request: dict | None = None

    async def propose_output_mapping(self, request: dict) -> dict:
        self.request = request
        return self.proposal


def _revision() -> dict:
    return {
        "platform": "youtube",
        "route_key": "youtube/channel/items",
        "actor_id": "publisher/weird-youtube-output",
        "build_number": "7.4.2",
        "security_evidence_json": {},
    }


def test_actual_actor_shape_can_repair_only_its_own_manifest() -> None:
    rows = [{
        "result": {
            "assetCode": "video-42",
            "watchLink": "https://www.youtube.com/watch?v=video-42",
            "releasedOn": "2026-08-20T12:00:00Z",
            "captionText": "A public test title",
            "ownerRef": "channel-42",
        }
    }]
    repairer = _Repairer({"output": {
        "native_id": "/result/assetCode",
        "url": "/result/watchLink",
        "published_at": "/result/releasedOn",
        "title": "/result/captionText",
        "source_native_id": "/result/ownerRef",
    }})
    runner = SimpleNamespace(output_mapping_repairer=repairer)

    mapped, repaired = asyncio.run(map_validation_output(
        runner,
        parse_actor_manifest(_manifest()),
        rows,
        ActorTarget(
            canonical_url="https://www.youtube.com/@example",
            native_id="channel-42",
        ),
        ActorRuntime(max_items=1),
        _revision(),
    ))

    assert mapped.semantic_outcome == "valid_nonempty"
    assert len(mapped.items) == 1
    assert repaired is not None
    assert repaired["output"]["native_id"]["pointers"] == ["/result/assetCode"]
    prompt = json.dumps(repairer.request, sort_keys=True)
    for value in ("video-42", "channel-42", "public test title", "@example"):
        assert value not in prompt


def test_unobserved_ai_pointer_keeps_the_original_contract_failure() -> None:
    repairer = _Repairer({"output": {
        "native_id": "/not-observed",
        "url": "/url",
        "published_at": "/published",
        "title": "/title",
        "source_native_id": "/channel",
    }})
    with pytest.raises(ActorManifestError) as excinfo:
        asyncio.run(map_validation_output(
            SimpleNamespace(output_mapping_repairer=repairer),
            parse_actor_manifest(_manifest()),
            [{"anything": "value"}],
            ActorTarget(native_id="channel-42"),
            ActorRuntime(max_items=1),
            _revision(),
        ))
    assert excinfo.value.code in {
        "apify_actor_contract_mismatch",
        "apify_actor_metadata_only",
    }
