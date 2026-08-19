from __future__ import annotations

import hashlib

from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _route(store: ServiceStore):
    return store.connect().execute(
        """SELECT * FROM apify_actor_route_profiles
           WHERE workspace_id = ? AND route_key = 'youtube/channel/items'""",
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()


def test_youtube_channel_handle_only_manifest_is_not_canary_eligible(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = _route(store)
    actor_id = "publisher/handle-only-youtube"
    manifest = {
        "version": 1,
        "actor_id": actor_id,
        "build_number": "1.0.1",
        "input": {"channelUsername": {"$ref": "target.handle"}},
        "output": {
            "native_id": {"pointers": ["/videoId"], "transforms": ["to_string"]},
            "url": {"pointers": ["/videoUrl"], "transforms": ["normalize_url"]},
            "published_at": {"pointers": ["/publishedAt"], "transforms": ["parse_datetime"]},
            "title": {"pointers": ["/title"], "transforms": ["to_string"]},
            "author_handle": {"pointers": ["/channelHandle"], "transforms": ["to_string"]},
        },
        "semantics": {
            "identity": {"output_field": "author_handle", "target_ref": "target.handle", "match": "handle"},
            "url_host_allowlist": ["youtube.com"],
        },
    }
    candidate_id = ops.ensure_candidate(str(route["route_id"]), actor_id=actor_id)
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher",
        build_id="build-handle-only",
        build_number="1.0.1",
        manifest=manifest,
        input_schema_hash=hashlib.sha256(b"input").hexdigest(),
        output_schema_hash=hashlib.sha256(b"output").hexdigest(),
        lifecycle="static_valid",
    )
    assert ops.revision_canary_block_reason(str(route["route_id"]), revision_id) == (
        "apify_manifest_youtube_channel_identity_unverifiable"
    )
