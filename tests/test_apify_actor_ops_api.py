from __future__ import annotations

import hashlib
import json

from fastapi.testclient import TestClient

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
        "x/profile",
        "youtube/channel/items",
        "instagram/profile/items",
    }
    detail = client.get(
        f"/api/admin/apify-routes/{routes[0]['route_id']}"
    )
    assert detail.status_code == 200, detail.text
    assert [slot["slot"] for slot in detail.json()["data"]["slots"]] == [
        "primary",
        "backup_1",
        "backup_2",
    ]
    for forbidden in (
        "remote_run_id",
        "dataset_id",
        "target_fingerprint",
        "manifest_json",
        "security_evidence",
        "token",
    ):
        assert forbidden not in detail.text.casefold()


def test_capability_catalog_requires_fully_certified_three_slot_route(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    before = client.get("/api/catalog/source-capabilities")
    assert before.status_code == 200
    assert before.json()["data"]["capabilities"] == []

    _ops, route, _revisions = _ready_route(store)
    after = client.get("/api/catalog/source-capabilities")
    assert after.status_code == 200
    capabilities = after.json()["data"]["capabilities"]
    assert [item["profile_id"] for item in capabilities] == [route["route_id"]]
    assert capabilities[0]["platform"] == "instagram"
    assert [field["name"] for field in capabilities[0]["fields"]] == [
        "profile_id",
        "target",
    ]


def test_youtube_fallback_capability_uses_native_source_fields(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, _revisions = _ready_route(
        store,
        route_key="youtube/channel/items",
    )

    response = client.get("/api/catalog/source-capabilities")

    assert response.status_code == 200, response.text
    capability = next(
        item
        for item in response.json()["data"]["capabilities"]
        if item["profile_id"] == route["route_id"]
    )
    assert capability["storage_type"] == "youtube_channel"
    assert capability["mode"] == "fallback"
    assert [field["name"] for field in capability["fields"]] == [
        "url",
        "keep_latest_item",
    ]


def test_route_detail_projects_newer_exact_build_revision_diff(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops, route, revisions = _ready_route(store)
    current = ops.get_revision(revisions[0])
    proposed_revision_id = ops.create_adapter_revision(
        candidate_id=str(current["candidate_id"]),
        actor_id=str(current["actor_id"]),
        publisher=str(current["publisher"]),
        build_id="build-api-ready-primary-next",
        build_number="2.0.1",
        manifest=_manifest(str(current["actor_id"]), "2.0.1", host="instagram.com"),
        lifecycle="static_valid",
    )

    response = client.get(f"/api/admin/apify-routes/{route['route_id']}")
    assert response.status_code == 200, response.text
    assert response.json()["data"]["revision_diffs"] == [
        {
            "slot": "primary",
            "current_revision_id": revisions[0],
            "proposed_revision_id": proposed_revision_id,
            "changes": ["build_id", "build_number", "manifest_hash"],
        }
    ]


def test_member_support_check_uses_generation_and_viewer_is_denied(
    tmp_path,
    monkeypatch,
):
    client, _store = _client(tmp_path, monkeypatch)
    _login(client)
    client.post(
        "/api/users",
        json={
            "username": "member",
            "password": "member-password",
            "role": "member",
        },
    )
    client.post(
        "/api/users",
        json={
            "username": "viewer",
            "password": "viewer-password",
            "role": "viewer",
        },
    )
    client.post("/api/auth/logout")
    _login(client, "member", "member-password")
    catalog = client.get("/api/catalog/source-capabilities").json()["data"]

    created = client.post(
        "/api/admin/apify-support-checks",
        json={
            "platform": "instagram",
            "target_type": "profile",
            "capability": "items",
            "expected_generation": catalog["generation"],
        },
    )
    assert created.status_code == 200, created.text
    created_data = created.json()["data"]
    assert created_data["kind"] == "discovery"
    assert created_data["discovery_run_id"]
    assert created_data["generation"] == catalog["generation"]
    assert created_data["route_generation"] == 1
    unsupported = client.post(
        "/api/admin/apify-support-checks",
        json={
            "platform": "youtube",
            "target_type": "profile",
            "capability": "items",
            "expected_generation": 999,
        },
    )
    assert unsupported.status_code == 422
    assert unsupported.json()["error"]["code"] == (
        "apify_actor_route_profile_unsupported"
    )
    conflict = client.post(
        "/api/admin/apify-support-checks",
        json={
            "platform": "x",
            "target_type": "profile",
            "capability": "items",
            "expected_generation": 999,
        },
    )
    assert conflict.status_code == 409
    forced = client.post(
        "/api/admin/apify-support-checks",
        json={
            "platform": "x",
            "target_type": "profile",
            "capability": "items",
            "expected_generation": catalog["generation"],
            "force_discovery": True,
        },
    )
    assert forced.status_code == 403

    client.post("/api/auth/logout")
    _login(client, "viewer", "viewer-password")
    denied = client.post(
        "/api/admin/apify-support-checks",
        json={
            "platform": "mastodon",
            "target_type": "profile",
            "capability": "items",
            "expected_generation": 1,
        },
    )
    assert denied.status_code == 403


def test_youtube_source_stays_native_enabled_and_gets_pending_fallback_binding(
    tmp_path,
    monkeypatch,
):
    client, store = _client(tmp_path, monkeypatch)
    _login(client)

    created = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "youtube_channel",
            "display_name": "OpenAI YouTube",
            "config": {"url": YOUTUBE_FEED},
            "enabled": True,
        },
    )
    assert created.status_code == 200, created.text
    source = created.json()["data"]
    assert source["type"] == "rss"
    assert source["enabled"] is True

    binding = ApifyActorOpsService(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
    ).get_source_binding(source["id"])
    assert binding["mode"] == "fallback"
    assert binding["validation_status"] == "pending_validation"
    support = client.get(
        f"/api/admin/sources/{source['id']}/apify-support"
    )
    assert support.status_code == 200, support.text
    assert support.json()["data"]["binding_status"] == "pending_validation"


def test_source_support_projects_independent_budget_and_inflight_canary(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, revisions = _ready_route(store)
    created = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "apify_social",
            "display_name": "Private target must stay hidden",
            "config": {
                "profile_id": route["route_id"],
                "target": "private_target_secret_123",
            },
            "enabled": True,
        },
    )
    assert created.status_code == 200, created.text
    source_id = created.json()["data"]["id"]
    support_endpoint = f"/api/admin/sources/{source_id}/apify-support"
    support = client.get(support_endpoint)
    assert support.status_code == 200, support.text
    support_data = support.json()["data"]
    assert support_data["budget_cap_usd"] == 0.06
    assert support_data["spent_usd"] == 0
    assert support_data["remaining_budget_usd"] == 0.06

    route_detail = client.get(
        f"/api/admin/apify-routes/{route['route_id']}"
    )
    assert route_detail.status_code == 200, route_detail.text
    embedded_sources = route_detail.json()["data"]["source_validations"]
    assert [item["source_id"] for item in embedded_sources] == [source_id]
    assert all("source_name" not in item for item in embedded_sources)
    assert "Private target must stay hidden" not in route_detail.text
    assert "private_target_secret_123" not in route_detail.text

    approved = client.post(
        f"/api/admin/sources/{source_id}/apify-validations/{revisions[0]}/canary",
        json={
            "expected_generation": support_data["generation"],
            "approval_id": "source-budget-approval-0001",
            "confirmation": "确认付费试跑",
            "max_total_charge_usd": 0.01,
        },
    )
    assert approved.status_code == 200, approved.text

    refreshed = client.get(support_endpoint)
    assert refreshed.status_code == 200, refreshed.text
    refreshed_data = refreshed.json()["data"]
    assert refreshed_data["spent_usd"] == 0.01
    assert round(refreshed_data["remaining_budget_usd"], 2) == 0.05
    assert refreshed_data["slots"][0]["status"] == "queued"
    assert refreshed_data["slots"][0]["can_canary"] is False


def test_generic_actor_primary_source_rejects_uncertified_route(
    tmp_path,
    monkeypatch,
):
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    route = next(
        route
        for route in ApifyActorOpsService(store).list_routes()
        if route["route_key"] == "instagram/profile/items"
    )

    response = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "apify_social",
            "display_name": "Instagram profile",
            "config": {
                "profile_id": route["route_id"],
                "target": "openai",
            },
            "enabled": True,
        },
    )
    assert response.status_code == 409
    assert response.json()["error"]["code"] == "apify_actor_route_not_ready"
    assert store.connect().execute(
        "SELECT COUNT(*) FROM source_catalog"
    ).fetchone()[0] == 0


def test_legacy_x_profile_create_rejects_status_only_actor_route(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    connection = store.connect()
    connection.execute(
        """
        UPDATE apify_actor_route_profiles
        SET status = 'ready'
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (DEFAULT_WORKSPACE_ID,),
    )
    connection.execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'closed'
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (DEFAULT_WORKSPACE_ID,),
    )
    connection.commit()

    response = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "apify_social",
            "display_name": "Legacy shaped X profile",
            "config": {
                "platform": "x",
                "kind": "profile",
                "target": "openai",
            },
            "enabled": True,
        },
    )
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "apify_actor_route_not_ready"
    assert connection.execute(
        "SELECT COUNT(*) FROM source_catalog"
    ).fetchone()[0] == 0


def test_legacy_x_profile_create_is_mapped_after_full_capability_gate(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ready_route(store, route_key="x/profile")

    response = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "apify_social",
            "display_name": "Legacy shaped X profile",
            "config": {
                "platform": "x",
                "kind": "profile",
                "target": "openai",
            },
            "enabled": True,
        },
    )
    assert response.status_code == 200, response.text
    source = response.json()["data"]
    assert source["enabled"] is False
    assert source["config"]["profile_id"]
    assert "platform" not in source["config"]
    assert "kind" not in source["config"]
    binding = ApifyActorOpsService(store).get_source_binding(source["id"])
    assert binding["validation_status"] == "pending_validation"
    assert binding["route_id"] == source["config"]["profile_id"]


def test_discovery_settings_use_global_ai_and_are_cas_guarded(tmp_path, monkeypatch):
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    current = client.get("/api/admin/apify-discovery-settings")
    assert current.status_code == 200
    settings = current.json()["data"]
    assert settings["schema_version"] == 4
    assert settings["max_output_tokens"] == 4096
    assert settings["recommended_max_output_tokens"] is None
    assert settings["enabled"] is False
    assert settings["ai_config_id"] == "global-ai-unavailable"
    assert settings["ai_options"][0]["ready"] is False
    assert "secret_id" not in current.text
    assert "api_key_env" not in current.text

    rejected_legacy = client.patch(
        "/api/admin/apify-discovery-settings",
        json={
            "expected_generation": settings["generation"],
            "provider": "deepseek",
        },
    )
    assert rejected_legacy.status_code == 400

    owner = store.list_users(workspace_id=DEFAULT_WORKSPACE_ID)[0]
    monkeypatch.delenv("ACTOR_DISCOVERY_TEST_KEY", raising=False)
    secret = store.create_secret_ref(
        workspace_id=DEFAULT_WORKSPACE_ID,
        owner_user_id=str(owner["id"]),
        name="Actor Discovery Test",
        env_name="ACTOR_DISCOVERY_TEST_KEY",
        kind="ai",
        provider="deepseek",
    )
    config_path = tmp_path / "data" / "config.json"
    config_data = json.loads(config_path.read_text(encoding="utf-8"))
    config_data["ai"] = {
        "enabled": True,
        "provider": "deepseek",
        "model": "deepseek-chat",
        "api_key_env": "ACTOR_DISCOVERY_TEST_KEY",
    }
    config_path.write_text(json.dumps(config_data), encoding="utf-8")
    updated = client.patch(
        "/api/admin/apify-discovery-settings",
        json={
            "expected_generation": settings["generation"],
            "max_queries_per_run": 2,
        },
    )
    assert updated.status_code == 200, updated.text
    updated_settings = updated.json()["data"]
    assert updated_settings["ai_options"][0]["key_name"] == "Actor Discovery Test"
    assert updated_settings["ai_options"][0]["ready"] is False
    unavailable = client.patch(
        "/api/admin/apify-discovery-settings",
        json={
            "expected_generation": updated_settings["generation"],
            "enabled": True,
            "ai_config_id": updated_settings["ai_options"][0]["id"],
        },
    )
    assert unavailable.status_code == 409
    assert unavailable.json()["error"]["code"] == (
        "apify_actor_discovery_global_ai_unavailable"
    )

    SecretStore(tmp_path / "data").set(
        "ACTOR_DISCOVERY_TEST_KEY",
        "test-only-discovery-secret",
    )
    configured = client.get("/api/admin/apify-discovery-settings").json()["data"]
    assert configured["ai_options"][0]["ready"] is True
    assert configured["ai_options"][0]["provider"] == "deepseek"
    assert configured["ai_options"][0]["model"] == "deepseek-chat"

    enabled = client.patch(
        "/api/admin/apify-discovery-settings",
        json={
            "expected_generation": configured["generation"],
            "enabled": True,
            "ai_config_id": configured["ai_config_id"],
        },
    )
    assert enabled.status_code == 200, enabled.text
    enabled_settings = enabled.json()["data"]
    assert enabled_settings["enabled"] is True
    assert enabled_settings["generation"] == configured["generation"] + 1
    secondary = store.create_secret_ref(
        workspace_id=DEFAULT_WORKSPACE_ID,
        owner_user_id=str(owner["id"]),
        name="Actor Discovery Secondary",
        env_name="ACTOR_DISCOVERY_SECONDARY_TEST_KEY",
        kind="ai",
        provider="deepseek",
    )
    SecretStore(tmp_path / "data").set(
        "ACTOR_DISCOVERY_SECONDARY_TEST_KEY",
        "test-only-secondary-secret",
    )
    choices = client.get("/api/admin/apify-discovery-settings").json()["data"]
    secondary_option = next(
        option
        for option in choices["ai_options"]
        if option["key_name"] == "Actor Discovery Secondary"
    )
    assert secondary_option["preferred"] is False
    switched = client.patch(
        "/api/admin/apify-discovery-settings",
        json={
            "expected_generation": choices["generation"],
            "ai_config_id": secondary_option["id"],
        },
    )
    assert switched.status_code == 200, switched.text
    switched_settings = switched.json()["data"]
    assert switched_settings["ai_config_id"] == secondary_option["id"]
    assert ApifyActorOpsService(store).get_discovery_settings()[
        "secret_ref_id"
    ] == secondary["id"]
    protected = client.delete(f"/api/admin/secrets/{secondary['id']}")
    assert protected.status_code == 409
    assert protected.json()["error"]["code"] == "secret_in_use"
    output_updated = client.patch(
        "/api/admin/apify-discovery-settings",
        json={
            "expected_generation": switched_settings["generation"],
            "max_output_tokens": 12288,
        },
    )
    assert output_updated.status_code == 200, output_updated.text
    output_settings = output_updated.json()["data"]
    assert output_settings["max_output_tokens"] == 12288

    measurement = client.post(
        "/api/admin/apify-discovery-measurements",
        json={
            "expected_generation": output_settings["generation"],
            "confirmation": "确认AI容量测试",
            "max_output_tokens": 32768,
            "route_keys": [
                "youtube/channel/items",
                "instagram/profile/items",
            ],
        },
    )
    assert measurement.status_code == 200, measurement.text
    measured = measurement.json()["data"]
    assert len(measured["runs"]) == 2
    assert len(measured["jobs"]) == 2
    frozen = store.connect().execute(
        """
        SELECT measurement_mode, ai_max_output_tokens
        FROM apify_actor_discovery_runs
        WHERE trigger_reason = 'admin_ai_measurement'
        ORDER BY created_at
        """
    ).fetchall()
    assert [tuple(row) for row in frozen] == [(1, 32768), (1, 32768)]
    conflict = client.patch(
        "/api/admin/apify-discovery-settings",
        json={
            "expected_generation": settings["generation"],
            "enabled": False,
        },
    )
    assert conflict.status_code == 409


def test_paid_canary_approval_replay_returns_original_job(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops, route, run, revision_id = _discovery_revision(store)
    endpoint = (
        f"/api/admin/apify-discovery-runs/{run['run_id']}/candidates/"
        f"{revision_id}/canary"
    )
    payload = {
        "expected_generation": int(route["generation"]),
        "approval_id": "approval-api-replay-0001",
        "confirmation": "确认付费试跑",
        "max_total_charge_usd": 0.02,
    }

    first = client.post(endpoint, json=payload)
    assert first.status_code == 200, first.text
    first_data = first.json()["data"]
    validation_id = first_data["validation"]["validation_id"]
    job_id = first_data["job"]["id"]
    ops.record_validation(
        validation_id,
        status="succeeded",
        semantic_outcome="valid_nonempty",
        cost_usd=0.01,
    )
    store.connect().execute(
        """
        UPDATE fetch_jobs
        SET status = 'succeeded', finished_at = updated_at
        WHERE id = ?
        """,
        (job_id,),
    )
    store.connect().commit()

    replay = client.post(endpoint, json=payload)
    assert replay.status_code == 200, replay.text
    replay_data = replay.json()["data"]
    assert replay_data["validation"]["validation_id"] == validation_id
    assert replay_data["job"]["id"] == job_id
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_validations"
    ).fetchone()[0] == 1
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM fetch_jobs
        WHERE job_type = 'apify_actor_validation'
        """
    ).fetchone()[0] == 1
    persisted = store.connect().execute(
        """
        SELECT approval_key_hash
        FROM apify_actor_validations
        WHERE validation_id = ?
        """,
        (validation_id,),
    ).fetchone()
    assert persisted["approval_key_hash"] == hashlib.sha256(
        payload["approval_id"].encode()
    ).hexdigest()


def test_paid_canary_job_failure_rolls_back_approval(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, run, revision_id = _discovery_revision(store)

    def fail_create_job(*_args, **_kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(JobQueue, "create_job", fail_create_job)
    response = client.post(
        (
            f"/api/admin/apify-discovery-runs/{run['run_id']}/candidates/"
            f"{revision_id}/canary"
        ),
        json={
            "expected_generation": int(route["generation"]),
            "approval_id": "approval-api-rollback-0001",
            "confirmation": "确认付费试跑",
            "max_total_charge_usd": 0.02,
        },
    )
    assert response.status_code == 500
    assert response.json()["error"]["code"] == "internal_error"
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_validations"
    ).fetchone()[0] == 0
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM fetch_jobs
        WHERE job_type = 'apify_actor_validation'
        """
    ).fetchone()[0] == 0


def test_paid_canary_rejects_non_approval_discovery_stage(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops, route, run, revision_id = _discovery_revision(store)
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="awaiting_canary_approval",
        stage="failed",
        error_code="worker_interrupted",
    )

    response = client.post(
        (
            f"/api/admin/apify-discovery-runs/{run['run_id']}/candidates/"
            f"{revision_id}/canary"
        ),
        json={
            "expected_generation": int(route["generation"]),
            "approval_id": "approval-invalid-stage-0001",
            "confirmation": "确认付费试跑",
            "max_total_charge_usd": 0.02,
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == (
        "apify_actor_discovery_not_awaiting_approval"
    )
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_validations"
    ).fetchone()[0] == 0
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM fetch_jobs
        WHERE job_type = 'apify_actor_validation'
        """
    ).fetchone()[0] == 0


def test_route_cap_hot_update_and_manual_rediscovery_are_cas_guarded(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, _revisions = _ready_route(store)
    slots = [
        {"slot": slot["slot_name"], "revision_id": slot["revision_id"]}
        for slot in route["slots"]
    ]
    updated = client.put(
        f"/api/admin/apify-routes/{route['route_id']}/active-pool",
        json={
            "expected_generation": route["generation"],
            "per_run_cap_usd": 0.03,
            "slots": slots,
        },
    )
    assert updated.status_code == 200, updated.text
    updated_route = updated.json()["data"]
    assert updated_route["per_run_cap_usd"] == 0.03
    assert updated_route["generation"] == route["generation"] + 1

    conflict = client.put(
        f"/api/admin/apify-routes/{route['route_id']}/active-pool",
        json={
            "expected_generation": route["generation"],
            "per_run_cap_usd": 0.04,
            "slots": slots,
        },
    )
    assert conflict.status_code == 409
    route_catalog = client.get("/api/admin/apify-routes").json()["data"]
    rediscovery = client.post(
        "/api/admin/apify-support-checks",
        json={
            "platform": "instagram",
            "target_type": "profile",
            "capability": "items",
            "expected_generation": route_catalog["generation"],
            "force_discovery": True,
        },
    )
    assert rediscovery.status_code == 200, rediscovery.text
    rediscovery_data = rediscovery.json()["data"]
    assert rediscovery_data["kind"] == "discovery"
    assert rediscovery_data["discovery_run_id"]
    assert rediscovery_data["generation"] == route_catalog["generation"]
    assert rediscovery_data["route_generation"] == updated_route["generation"]
    assert rediscovery_data["job"]["status"] == "queued"


def test_route_activation_uses_server_recommendation_and_exact_confirmation(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, revision_ids = _ready_route(
        store,
        route_key="youtube/channel/items",
        activate=False,
    )
    endpoint = (
        f"/api/admin/apify-routes/{route['route_id']}/active-pool/activate"
    )

    detail = client.get(
        f"/api/admin/apify-routes/{route['route_id']}"
    )
    assert detail.status_code == 200, detail.text
    recommendation = detail.json()["data"]["activation_recommendation"]
    assert recommendation["ready"] is True
    assert recommendation["already_active"] is False
    assert {
        slot["revision_id"] for slot in recommendation["slots"]
    } == set(revision_ids)

    invalid = client.post(
        endpoint,
        json={
            "expected_generation": route["generation"],
            "confirmation": "确认首次启用",
        },
    )
    assert invalid.status_code == 400

    activated = client.post(
        endpoint,
        json={
            "expected_generation": route["generation"],
            "confirmation": "确认启用 Actor 主备",
        },
    )
    assert activated.status_code == 200, activated.text
    payload = activated.json()["data"]
    assert payload["generation"] == route["generation"] + 1
    assert payload["runnable_slots"] == 3
    assert payload["activation_recommendation"]["already_active"] is True

    replay = client.post(
        endpoint,
        json={
            "expected_generation": payload["generation"],
            "confirmation": "确认启用 Actor 主备",
        },
    )
    assert replay.status_code == 409
    assert replay.json()["error"]["code"] == (
        "apify_actor_active_pool_already_active"
    )


def test_route_activation_projects_expedited_two_actor_pool(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, revision_ids = _ready_route(
        store,
        route_key="instagram/profile/items",
        activate=False,
    )
    store.connect().executemany(
        """
        UPDATE apify_actor_adapter_revisions
        SET lifecycle = ?
        WHERE revision_id = ?
        """,
        [
            ("probationary", revision_ids[0]),
            ("probationary", revision_ids[1]),
            ("static_valid", revision_ids[2]),
        ],
    )
    store.connect().commit()

    detail = client.get(f"/api/admin/apify-routes/{route['route_id']}")
    assert detail.status_code == 200, detail.text
    recommendation = detail.json()["data"]["activation_recommendation"]
    assert recommendation["ready"] is True
    assert recommendation["activation_mode"] == "expedited_2of3"
    assert [slot["revision_id"] for slot in recommendation["slots"]] == [
        revision_ids[0],
        revision_ids[1],
        None,
    ]

    activated = client.post(
        f"/api/admin/apify-routes/{route['route_id']}/active-pool/activate",
        json={
            "expected_generation": route["generation"],
            "confirmation": "确认启用 Actor 主备",
        },
    )
    assert activated.status_code == 200, activated.text
    payload = activated.json()["data"]
    assert payload["support_status"] == "supported"
    assert payload["runtime_status"] == "degraded"
    assert payload["runnable_slots"] == 2
    assert [slot["revision_id"] for slot in payload["slots"]] == [
        revision_ids[0],
        revision_ids[1],
        None,
    ]


def test_discovery_projection_reports_rank_rejections_and_committed_spend(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops, route, run, revision_id = _discovery_revision(store)
    ops.update_discovery_run(
        run["run_id"],
        expected_stage="awaiting_canary_approval",
        stage="awaiting_canary_approval",
        candidate_count=1,
        rejections=(
            {"actor_id": "not-persisted", "reason": "actor_full_permission"},
            {"actor_id": "not-persisted-2", "reason": "actor_full_permission"},
        ),
    )
    approved = client.post(
        (
            f"/api/admin/apify-discovery-runs/{run['run_id']}/candidates/"
            f"{revision_id}/canary"
        ),
        json={
            "expected_generation": int(route["generation"]),
            "approval_id": "approval-projection-0001",
            "confirmation": "确认付费试跑",
            "max_total_charge_usd": 0.02,
        },
    )
    assert approved.status_code == 200, approved.text

    response = client.get(
        f"/api/admin/apify-discovery-runs/{run['run_id']}"
    )
    assert response.status_code == 200, response.text
    projected = response.json()["data"]
    assert projected["schema_version"] == 3
    assert projected["canary_attempts_used"] == 0
    assert projected["canary_attempts_limit"] == 5
    assert projected["canary_attempts_remaining"] == 5
    assert projected["canary_timeout_seconds"] == 300
    assert projected["candidates"][0]["rank"] == 1
    assert projected["candidates"][0]["validation_status"] == "queued"
    assert projected["candidates"][0]["canary_in_flight"] is True
    assert projected["candidates"][0]["awaiting_approval"] is False
    assert projected["candidates"][0]["revision"]["pricing"] == {
        "model": "PAY_PER_EVENT",
        "billing_unit": "event",
        "unit_price_min_usd": 0.001,
        "unit_price_max_usd": 0.015,
        "minimum_charge_usd": None,
        "minimum_run_cap_usd": 0.02,
    }
    assert projected["spent_usd"] == 0.02
    assert projected["rejections"] == [
        {"reason": "actor_full_permission", "count": 2}
    ]
    assert "not-persisted" not in response.text


def test_discovery_projection_reports_persisted_partial_pool(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops, _route, run, _revision_id = _discovery_revision(store)
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="awaiting_canary_approval",
        stage="candidate_shortfall",
        error_code="input_validation_candidate_shortfall",
        candidate_count=1,
    )

    response = client.get(
        f"/api/admin/apify-discovery-runs/{run['run_id']}"
    )

    assert response.status_code == 200, response.text
    projected = response.json()["data"]
    assert projected["candidate_count"] == 1
    assert projected["candidate_shortfall"] == 2
    assert projected["publisher_count"] == 1
    assert projected["publisher_shortfall"] == 1
    assert len(projected["candidates"]) == 1
    assert projected["candidates"][0]["awaiting_approval"] is False
