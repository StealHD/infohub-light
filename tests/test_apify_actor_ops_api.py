from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient

from tests.actorops_v1_projection_fixture import public_actor_ops_detail
from src.api.server import create_app
from src.services.job_queue import JobQueue
from src.services.apify_actor_ops import ApifyActorOpsService
from src.services.secret_store import SecretStore
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


YOUTUBE_CHANNEL_ID = "UCabcdefghijklmnopqrstuv"
YOUTUBE_FEED = (
    "https://www.youtube.com/feeds/videos.xml?"
    f"channel_id={YOUTUBE_CHANNEL_ID}"
)


def _manifest(
    actor_id: str,
    build_number: str,
    *,
    host: str = "youtube.com",
) -> dict:
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
            "url_host_allowlist": [host],
        },
    }


def _ready_route(
    store: ServiceStore,
    *,
    route_key: str = "instagram/profile/items",
    activate: bool = True,
):
    ops = ApifyActorOpsService(store)
    route = next(
        route for route in ops.list_routes() if route["route_key"] == route_key
    )
    platform = str(route["platform"])
    host = {
        "instagram": "instagram.com",
        "x": "x.com",
        "youtube": "youtube.com",
    }[platform]
    revisions: list[str] = []
    for index, publisher in enumerate(("publisher-a", "publisher-b", "publisher-a"), start=1):
        actor_id = f"{publisher}/api-ready-{index}"
        candidate_id = ops.ensure_candidate(route["route_id"], actor_id=actor_id)
        revision_id = ops.create_adapter_revision(
            candidate_id=candidate_id,
            actor_id=actor_id,
            publisher=publisher,
            build_id=f"build-api-ready-{index}",
            build_number=f"1.0.{index}",
            manifest=_manifest(actor_id, f"1.0.{index}", host=host),
            lifecycle="static_valid",
        )
        store.connect().execute(
            """
            UPDATE apify_actor_adapter_revisions
            SET lifecycle = ?
            WHERE revision_id = ?
            """,
            ("certified" if index < 3 else "probationary", revision_id),
        )
        store.connect().commit()
        revisions.append(revision_id)
    if not activate:
        return ops, ops.get_route(str(route["route_id"])), revisions
    detail = ops.replace_active_pool(
        route["route_id"],
        slots={
            "primary": revisions[0],
            "backup_1": revisions[1],
            "backup_2": revisions[2],
        },
        expected_generation=route["generation"],
    )
    return ops, detail, revisions


def _discovery_revision(store: ServiceStore):
    ops = ApifyActorOpsService(store)
    route = next(
        route
        for route in ops.list_routes()
        if route["route_key"] == "youtube/channel/items"
    )
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="test",
        expected_generation=int(route["generation"]),
    )
    actor_id = "publisher/api-canary"
    candidate_id = ops.ensure_candidate(
        str(route["route_id"]),
        actor_id=actor_id,
    )
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher",
        build_id="build-api-canary",
        build_number="1.0.1",
        manifest=_manifest(actor_id, "1.0.1"),
        pricing={
            "pricingModel": "PAY_PER_EVENT",
            "minimalMaxTotalChargeUsd": 0.02,
            "pricingPerEvent": {
                "actorChargeEvents": {
                    "item": {"eventPriceUsd": 0.001},
                    "detail": {"eventPriceUsd": 0.015},
                }
            },
        },
        lifecycle="static_valid",
        discovery_run_id=str(run["run_id"]),
    )
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="queued",
        stage="awaiting_canary_approval",
    )
    run = ops.get_discovery_run(str(run["run_id"]))
    return ops, route, run, revision_id


def _discovery_batch_candidates(store: ServiceStore):
    ops = ApifyActorOpsService(store)
    route = next(
        route
        for route in ops.list_routes()
        if route["route_key"] == "instagram/profile/items"
    )
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="test-two-publisher-batch",
        expected_generation=int(route["generation"]),
    )
    revisions = []
    for index, publisher in enumerate(
        ("publisher-one", "publisher-two", "publisher-three"),
        start=1,
    ):
        actor_id = f"{publisher}/api-canary-{index}"
        candidate_id = ops.ensure_candidate(
            str(route["route_id"]),
            actor_id=actor_id,
        )
        revisions.append(
            ops.create_adapter_revision(
                candidate_id=candidate_id,
                actor_id=actor_id,
                publisher=publisher,
                build_id=f"build-api-canary-{index}",
                build_number=f"1.0.{index}",
                manifest=_manifest(
                    actor_id,
                    f"1.0.{index}",
                    host="instagram.com",
                ),
                pricing={
                    "pricingModel": "PAY_PER_EVENT",
                    "minimalMaxTotalChargeUsd": 0.02,
                    "pricingPerEvent": {
                        "actorChargeEvents": {
                            "item": {"eventPriceUsd": 0.001 * index},
                        }
                    },
                },
                lifecycle="static_valid",
                discovery_run_id=str(run["run_id"]),
            )
        )
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="queued",
        stage="awaiting_canary_approval",
    )
    run = ops.get_discovery_run(str(run["run_id"]))
    return ops, route, run, revisions


def _client(tmp_path, monkeypatch) -> tuple[TestClient, ServiceStore]:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    data_dir.mkdir()
    static_dir.mkdir()
    (data_dir / "config.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "ai": {"enabled": False},
                "tags": [],
                "personal_tags": [],
                "sources": {
                    "rss": [],
                    "github": [],
                    "hackernews": {"enabled": False},
                },
                "filtering": {
                    "ai_score_threshold": 7.5,
                    "time_window_hours": 24,
                },
            }
        ),
        encoding="utf-8",
    )
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = create_app(data_dir=data_dir, static_dir=static_dir)
    store = ServiceStore(data_dir)
    store.initialize()
    return TestClient(app), store


def _login(client: TestClient, username="owner", password="secret-password"):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


def test_actor_ops_routes_are_admin_only_safe_and_three_slot(tmp_path, monkeypatch):
    client, _store = _client(tmp_path, monkeypatch)
    assert client.get("/api/admin/apify-routes").status_code == 401
    _login(client)

    response = client.get("/api/admin/apify-routes")
    assert response.status_code == 200, response.text
    assert response.headers["cache-control"] == "no-store"
    routes = response.json()["data"]["routes"]
    assert {route["route_key"] for route in routes} == {
        "x/profile/items",
        "youtube/channel/items",
        "instagram/profile/items",
    }
    detail = client.get(
        f"/api/admin/apify-routes/{routes[0]['route_id']}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["data"]["schema_version"] == 2
    for forbidden in (
        "remote_run_id",
        "dataset_id",
        "target_fingerprint",
        "manifest_json",
        "security_evidence",
        "token",
    ):
        assert forbidden not in detail.text.casefold()
