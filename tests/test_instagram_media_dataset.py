import json
from datetime import datetime, timezone

import httpx
import pytest

from src.services.actorops.attempt_recovery import request_fingerprint
from src.services.actorops.known_dataset_reader import KnownDatasetError, read_known_dataset
from src.services.actorops.ports import FetchWindow
from src.services.actorops.repository import ActorOpsRepository
from src.services.instagram_media_repair import preview_media_repair, apply_media_repair, MediaRepairError, _state, _dataset_item
from test_instagram_actor_media import row
from test_instagram_media_repair import repair, image, record


def dataset_attempt(repair):
    store, args, candidate = repair
    conn = store.connect()
    original = json.loads(record(store)["item_json"])
    original.pop("remote_media_urls")
    conn.execute("UPDATE user_content_items SET item_json=?", (json.dumps(original),))
    binding = conn.execute("SELECT * FROM actor_source_bindings_v2").fetchone()
    conn.commit()
    repository = ActorOpsRepository(conn, args["workspace_id"])
    window = FetchWindow(10, datetime(2026, 8, 19, tzinfo=timezone.utc), None)
    with repository.transaction():
        repository.create_attempt(attempt_id="media-attempt", idempotency_key="media-attempt",
            route_id=candidate.route_id, source_id=args["source_id"], candidate_id=candidate.candidate_id,
            kind="fetch", attempt_group_id="media-group", attempt_index=0, route_generation=1,
            binding_version=1, target_fingerprint=binding["target_fingerprint"], reserved_usd=0.1,
            logical_job_id="media-job", request_schema_version=1,
            request_fingerprint=request_fingerprint(target_fingerprint=binding["target_fingerprint"],
                candidate=candidate, route_cap_usd=0.1, window=window),
            window_since=window.since.isoformat(), window_until=None, max_items=10)
        conn.execute("UPDATE actor_attempts_v2 SET status='starting'")
        conn.execute("UPDATE actor_attempts_v2 SET status='registered'")
        conn.execute("""UPDATE actor_attempts_v2 SET status='succeeded', result_state='validated',
            cost_final=1, actual_cost_usd=0.01, dataset_id='existing-data', remote_run_id='existing-run'""")
    return dict(repository.get_attempt("media-attempt"))


def test_existing_dataset_repair_validates_identity_and_frozen_request(repair):
    store, args, _ = repair
    dataset_attempt(repair)
    rows = [row(displayUrl="https://cdn.example/one.png")]
    reads = []
    def reader(store, attempt):
        reads.append(attempt["dataset_id"])
        return rows
    plan = preview_media_repair(store, **args, reader=reader)
    assert reads == ["existing-data"] and plan.public()["available_images"] == 1
    assert apply_media_repair(store, plan, expected_preview=plan.fingerprint, fetch_image=image)["cached_images"] == 1
    state, _ = _state(store, **args)
    state["attempts"][0]["manifest_hash"] = "0" * 64
    blocked, reason = _dataset_item(store, state, args["article_id"], reader)
    assert blocked is None and reason == "instagram_dataset_request_changed" and len(reads) == 1


def test_dataset_unavailable_foreign_identity_and_changed_results(repair):
    store, args, _ = repair
    dataset_attempt(repair)
    def unavailable(*_):
        raise KnownDatasetError("instagram_dataset_unavailable")
    assert preview_media_repair(store, **args, reader=unavailable).reason == "instagram_dataset_unavailable"
    foreign = preview_media_repair(store, **args, reader=lambda *_: [row(author="foreign", displayUrl="https://cdn.example/x.png")])
    assert foreign.item is None
    first = preview_media_repair(store, **args, reader=lambda *_: [row(displayUrl="https://cdn.example/a.png")])
    changed = preview_media_repair(store, **args, reader=lambda *_: [row(displayUrl="https://cdn.example/b.png")])
    with pytest.raises(MediaRepairError, match="preview_changed"):
        apply_media_repair(store, changed, expected_preview=first.fingerprint, fetch_image=image)


def test_known_reader_only_gets_original_dataset_without_reservation(repair, monkeypatch):
    store, args, _ = repair
    attempt = dataset_attempt(repair)
    conn = store.connect()
    conn.execute("""INSERT INTO secret_refs(id,workspace_id,name,env_name,scope,kind,provider,created_at,updated_at)
        VALUES('media-secret',?,'test','MEDIA_REPAIR_TEST_TOKEN','workspace','apify','apify','now','now')""", (args["workspace_id"],))
    conn.execute("""INSERT INTO apify_actor_runs(id,workspace_id,logical_run_id,secret_id,secret_version,
        pool_generation,remote_run_id,dataset_id,status,charge_final,created_at,updated_at)
        VALUES('ledger',?,'media-attempt','media-secret',1,1,'existing-run','existing-data','succeeded',1,'now','now')""", (args["workspace_id"],))
    conn.commit()
    monkeypatch.setenv("MEDIA_REPAIR_TEST_TOKEN", "test-fixture-not-a-real-token")
    requests = []
    def handler(request):
        requests.append(request)
        assert request.method == "GET" and request.url.host == "api.apify.com"
        assert request.url.path == "/v2/datasets/existing-data/items"
        assert request.url.params["limit"] == "10"
        return httpx.Response(200, json=[row(displayUrl="https://cdn.example/a.png")])
    before = conn.total_changes
    assert len(read_known_dataset(store, attempt, transport=httpx.MockTransport(handler))) == 1
    assert conn.total_changes == before and len(requests) == 1
    for status in (403, 404, 500, 302):
        with pytest.raises(KnownDatasetError, match="unavailable"):
            read_known_dataset(store, attempt, transport=httpx.MockTransport(lambda _: httpx.Response(status)))
    with pytest.raises(KnownDatasetError, match="shape_invalid"):
        read_known_dataset(store, attempt, transport=httpx.MockTransport(lambda _: httpx.Response(200, json={})))
