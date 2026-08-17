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


def test_actor_resilience_admin_api_configures_key_frequency_and_preference(
    tmp_path,
    monkeypatch,
):
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    created_secrets = []
    for name, env_name in (
        ("Acquisition", "APIFY_ACTOROPS_ACQUISITION"),
        ("Validation", "APIFY_ACTOROPS_VALIDATION"),
    ):
        response = client.post(
            "/api/admin/secrets",
            json={
                "name": name,
                "kind": "apify",
                "provider": "apify",
                "env_name": env_name,
                "value": f"private-{name.casefold()}-token",
            },
        )
        assert response.status_code == 200, response.text
        created_secrets.append(response.json()["data"])

    pool = client.get("/api/admin/apify-key-pool").json()["data"]
    selected = client.put(
        "/api/admin/apify-key-pool/validation-key",
        json={
            "secret_id": created_secrets[1]["id"],
            "expected_generation": pool["generation"],
        },
    )
    assert selected.status_code == 200, selected.text
    key_state = selected.json()["data"]
    assert key_state["schema_version"] == 2
    assert key_state["validation_secret_id"] == created_secrets[1]["id"]
    assert next(
        row
        for row in key_state["members"]
        if row["secret_id"] == created_secrets[1]["id"]
    )["role"] == "validation"

    routes = client.get("/api/admin/apify-routes").json()["data"]["routes"]
    x_route = next(row for row in routes if row["route_key"] == "x/profile")
    detail_url = f"/api/admin/apify-routes/{x_route['route_id']}"
    detail = client.get(detail_url).json()["data"]
    assert detail["admission_mode"] == "standard"
    assert detail["freshness"]["interval_hours"] == 24
    assert detail["freshness"]["validation_key"]["usable"] is True

    missing_confirmation = client.patch(
        f"{detail_url}/freshness-settings",
        json={
            "enabled": True,
            "interval_hours": 24,
            "expected_generation": detail["generation"],
            "standing_authorization_confirmed": False,
        },
    )
    assert missing_confirmation.status_code == 412
    assert missing_confirmation.json()["error"]["code"] == (
        "freshness_authorization_required"
    )
    configured = client.patch(
        f"{detail_url}/freshness-settings",
        json={
            "enabled": True,
            "interval_hours": 24,
            "expected_generation": detail["generation"],
            "standing_authorization_confirmed": True,
        },
    )
    assert configured.status_code == 200, configured.text
    configured_detail = configured.json()["data"]
    assert configured_detail["route_id"] == x_route["route_id"]
    assert configured_detail["freshness"]["enabled"] is True
    assert configured_detail["freshness"]["interval_hours"] == 24

    plan = client.get(f"{detail_url}/freshness-plan")
    assert plan.status_code == 200, plan.text
    plan_data = plan.json()["data"]
    assert plan_data["requires_cost_confirmation"] is True
    assert plan_data["max_total_charge_usd"] <= 0.06
    unconfirmed = client.post(
        f"{detail_url}/freshness-checks",
        json={
            "cost_confirmed": False,
            "expected_generation": configured_detail["generation"],
            "max_total_charge_usd": plan_data["max_total_charge_usd"],
        },
    )
    assert unconfirmed.status_code == 412
    assert unconfirmed.json()["error"]["code"] == (
        "freshness_cost_confirmation_required"
    )
    changed_cap = client.post(
        f"{detail_url}/freshness-checks",
        json={
            "cost_confirmed": True,
            "expected_generation": configured_detail["generation"],
            "max_total_charge_usd": round(
                plan_data["max_total_charge_usd"] / 2,
                6,
            ),
        },
    )
    assert changed_cap.status_code == 409
    assert changed_cap.json()["error"]["code"] == "freshness_plan_conflict"
    queued = client.post(
        f"{detail_url}/freshness-checks",
        json={
            "cost_confirmed": True,
            "expected_generation": configured_detail["generation"],
            "max_total_charge_usd": plan_data["max_total_charge_usd"],
        },
    )
    assert queued.status_code == 200, queued.text
    assert queued.json()["data"]["check"]["status"] == "queued"

    ops = ApifyActorOpsService(store)
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Preference source",
        config={"platform": "x", "kind": "profile", "target": "example"},
    )
    binding = ops.bind_source(
        source_id=source_id,
        route_id=str(x_route["route_id"]),
        target_fingerprint=hashlib.sha256(b"preference-source").hexdigest(),
        mode="primary",
    )
    preferred = next(
        slot
        for slot in ops.get_route(str(x_route["route_id"]))["slots"]
        if slot["candidate_state"] == "closed"
    )
    preference = client.patch(
        f"/api/admin/sources/{source_id}/apify-preference",
        json={
            "candidate_id": preferred["candidate_id"],
            "expected_generation": binding["generation"],
        },
    )
    assert preference.status_code == 200, preference.text
    preference_data = preference.json()["data"]
    assert preference_data["mode"] == "manual"
    assert preference_data["preferred_actor_name"] == preferred["actor_public_name"]

    events = client.get(
        "/api/admin/apify-actor-events",
        params={"route_id": x_route["route_id"], "limit": 100},
    )
    assert events.status_code == 200, events.text
    timeline = events.json()["data"]
    assert {row["phase"] for row in timeline["events"]} >= {
        "freshness",
        "freshness_settings",
        "source_preference",
    }
    for forbidden in (
        "private-acquisition-token",
        "private-validation-token",
        "target_fingerprint",
        "remote_run_id",
        "dataset_id",
        "raw_error",
    ):
        assert forbidden not in events.text


def test_freshness_queue_failure_finalizes_check_and_route_state(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    for name, env_name in (
        ("Acquisition", "APIFY_ACTOROPS_ACQUISITION_QUEUE_FAILURE"),
        ("Validation", "APIFY_ACTOROPS_VALIDATION_QUEUE_FAILURE"),
    ):
        secret = client.post(
            "/api/admin/secrets",
            json={
                "name": name,
                "kind": "apify",
                "provider": "apify",
                "env_name": env_name,
                "value": f"private-{name.casefold()}-token",
            },
        ).json()["data"]
    pool = client.get("/api/admin/apify-key-pool").json()["data"]
    selected = client.put(
        "/api/admin/apify-key-pool/validation-key",
        json={
            "secret_id": secret["id"],
            "expected_generation": pool["generation"],
        },
    )
    assert selected.status_code == 200, selected.text
    routes = client.get("/api/admin/apify-routes").json()["data"]["routes"]
    route = next(item for item in routes if item["route_key"] == "x/profile")
    route_url = f"/api/admin/apify-routes/{route['route_id']}"
    detail = client.get(route_url).json()["data"]
    plan = client.get(f"{route_url}/freshness-plan").json()["data"]

    def fail_create_job(*_args, **_kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(JobQueue, "create_job", fail_create_job)
    response = client.post(
        f"{route_url}/freshness-checks",
        json={
            "cost_confirmed": True,
            "expected_generation": detail["generation"],
            "max_total_charge_usd": plan["max_total_charge_usd"],
        },
    )
    assert response.status_code == 500
    check = store.connect().execute(
        """
        SELECT status, error_code FROM apify_actor_freshness_checks
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    ).fetchone()
    assert dict(check) == {
        "status": "failed",
        "error_code": "job_queue_failed",
    }
    profile = store.connect().execute(
        """
        SELECT freshness_status, freshness_next_check_at
        FROM apify_actor_route_profiles
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    ).fetchone()
    assert dict(profile) == {
        "freshness_status": "failed",
        "freshness_next_check_at": None,
    }
    event = store.connect().execute(
        """
        SELECT outcome, reason_code FROM apify_actor_diagnostic_events
        WHERE workspace_id = ? AND route_id = ? AND phase = 'freshness'
        ORDER BY created_at DESC, event_id DESC LIMIT 1
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    ).fetchone()
    assert dict(event) == {
        "outcome": "failed",
        "reason_code": "job_queue_failed",
    }


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


def test_platform_alias_auto_routes_redacts_config_and_locks_changed_target(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, _revisions = _ready_route(store, route_key="x/profile")

    before_key = client.get("/api/catalog/source-types")
    assert before_key.status_code == 200, before_key.text
    before_x = next(
        item
        for item in before_key.json()["data"]["source_types"]
        if item["type"] == "x_profile"
    )
    assert before_x["availability"] == "temporarily_unavailable"
    assert before_x["unavailable_reason"] == "workspace_credential_unavailable"

    secret = client.post(
        "/api/admin/secrets",
        json={
            "name": "Workspace social connection",
            "kind": "apify",
            "provider": "apify",
            "env_name": "APIFY_PLATFORM_ALIAS_TEST",
            "value": "private-test-token",
        },
    )
    assert secret.status_code == 200, secret.text

    catalog = client.get("/api/catalog/source-types")
    assert catalog.status_code == 200, catalog.text
    x_definition = next(
        item
        for item in catalog.json()["data"]["source_types"]
        if item["type"] == "x_profile"
    )
    assert x_definition["availability"] == "ready"
    assert x_definition["unavailable_reason"] is None
    assert "catalog_source_type" not in x_definition
    serialized_definition = json.dumps(x_definition).casefold()
    for forbidden in ("apify", "actor", "route", "profile_id"):
        assert forbidden not in serialized_definition

    rejected_internal = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "x_profile",
            "display_name": "Invalid X",
            "config": {
                "target": "openai",
                "profile_id": route["route_id"],
            },
        },
    )
    assert rejected_internal.status_code == 400
    assert rejected_internal.json()["error"]["code"] == "invalid_source_config"

    created = client.post(
        "/api/catalog/sources",
        json={
            "scope": "workspace",
            "type": "x_profile",
            "display_name": "OpenAI X",
            "description": "Public updates",
            "config": {
                "target": "@OpenAI",
                "fetch_limit": 3,
                "analysis_mode": "full",
            },
            "enabled": True,
        },
    )
    assert created.status_code == 200, created.text
    public_source = created.json()["data"]
    assert public_source["type"] == "apify_social"
    assert public_source["setup_type"] == "x_profile"
    assert public_source["enabled"] is False
    assert public_source["config"] == {
        "target": "@OpenAI",
        "fetch_limit": 3,
        "analysis_mode": "full",
    }
    for forbidden in ("profile_id", "platform", "kind", "secret_env"):
        assert forbidden not in public_source.get("config", {})
        assert forbidden not in public_source
    assert public_source["source_key"].startswith("apify_social:")

    stored = store.get_source(public_source["id"])
    assert stored["config"]["profile_id"] == route["route_id"]
    assert "platform" not in stored["config"]
    assert "kind" not in stored["config"]
    binding = ApifyActorOpsService(store).get_source_binding(public_source["id"])
    assert binding["route_id"] == route["route_id"]
    assert binding["validation_status"] == "pending_validation"

    partial_config_patch = client.patch(
        f"/api/catalog/sources/{public_source['id']}",
        json={"config": {"target": "@OpenAI"}},
    )
    assert partial_config_patch.status_code == 200, partial_config_patch.text
    assert partial_config_patch.json()["data"]["config"] == public_source["config"]
    partial_stored = store.get_source(public_source["id"])
    assert partial_stored["config"]["profile_id"] == route["route_id"]
    assert partial_stored["config"]["fetch_limit"] == 3
    assert partial_stored["config"]["analysis_mode"] == "full"

    connection = store.connect()
    connection.execute(
        """
        UPDATE apify_actor_route_profiles
        SET status = 'blocked'
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    )
    connection.commit()
    metadata_patch = client.patch(
        f"/api/catalog/sources/{public_source['id']}",
        json={"display_name": "OpenAI on X", "description": "Renamed safely"},
    )
    assert metadata_patch.status_code == 200, metadata_patch.text
    assert metadata_patch.json()["data"]["display_name"] == "OpenAI on X"
    assert metadata_patch.json()["data"]["config"] == public_source["config"]

    changed_target = client.patch(
        f"/api/catalog/sources/{public_source['id']}",
        json={
            "config": {
                "target": "another-account",
                "fetch_limit": 3,
                "analysis_mode": "full",
            }
        },
    )
    assert changed_target.status_code == 409
    assert changed_target.json()["error"]["code"] == "apify_actor_route_not_ready"

    legacy_changed_target = client.patch(
        f"/api/catalog/sources/{public_source['id']}",
        json={
            "config": {
                "profile_id": route["route_id"],
                "target": "another-account",
                "fetch_limit": 3,
                "analysis_mode": "full",
            }
        },
    )
    assert legacy_changed_target.status_code == 409
    assert legacy_changed_target.json()["error"]["code"] == (
        "apify_actor_route_not_ready"
    )

    changed_fetch_limit = client.patch(
        f"/api/catalog/sources/{public_source['id']}",
        json={"config": {"fetch_limit": 4}},
    )
    assert changed_fetch_limit.status_code == 409
    assert changed_fetch_limit.json()["error"]["code"] == "apify_actor_route_not_ready"

    changed_enabled = client.patch(
        f"/api/catalog/sources/{public_source['id']}",
        json={"enabled": True},
    )
    assert changed_enabled.status_code == 409
    assert changed_enabled.json()["error"]["code"] == "apify_actor_route_not_ready"


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


def test_support_catalog_and_checks_are_owner_admin_only(
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
    assert forced.status_code == 200, forced.text

    client.post("/api/auth/logout")
    _login(client, "member", "member-password")
    assert client.get("/api/catalog/source-capabilities").status_code == 403
    member_denied = client.post(
        "/api/admin/apify-support-checks",
        json={
            "platform": "x",
            "target_type": "profile",
            "capability": "items",
            "expected_generation": catalog["generation"],
        },
    )
    assert member_denied.status_code == 403

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


def test_youtube_source_requires_actor_validation_and_gets_primary_binding(
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
    assert binding["mode"] == "primary"
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
    assert refreshed_data["spent_usd"] == 0
    assert refreshed_data["reserved_usd"] == 0.01
    assert round(refreshed_data["remaining_budget_usd"], 2) == 0.05
    assert refreshed_data["slots"][0]["status"] == "queued"
    assert refreshed_data["slots"][0]["can_canary"] is False


def test_legacy_source_support_blocks_paid_canary_before_job_creation(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops = ApifyActorOpsService(store)
    route = next(
        item for item in ops.list_routes() if item["route_key"] == "x/profile"
    )
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Legacy source stays private",
        config={"platform": "x", "kind": "profile", "target": "private"},
    )
    binding = ops.bind_source(
        source_id=source_id,
        route_id=str(route["route_id"]),
        target_fingerprint=hashlib.sha256(b"legacy-source").hexdigest(),
        mode="primary",
    )
    support_url = f"/api/admin/sources/{source_id}/apify-support"

    support = client.get(support_url)
    assert support.status_code == 200, support.text
    data = support.json()["data"]
    assert data["schema_version"] == 2
    assert data["next_action"] == {
        "kind": "upgrade_pool_required",
        "reason": "apify_actor_source_requires_pool_upgrade",
    }
    assert all(slot["status"] == "blocked" for slot in data["slots"])
    assert all(slot["can_canary"] is False for slot in data["slots"])
    assert data["activation_confirmation"] is None

    counts_before = {
        "validations": store.connect().execute(
            "SELECT COUNT(*) FROM apify_actor_validations"
        ).fetchone()[0],
            "jobs": store.connect().execute(
                "SELECT COUNT(*) FROM fetch_jobs"
        ).fetchone()[0],
    }
    rejected = client.post(
        f"/api/admin/sources/{source_id}/apify-validations/"
        f"{data['slots'][0]['revision_id']}/canary",
        json={
            "expected_generation": int(binding["generation"]),
            "approval_id": "legacy-source-blocked-approval",
            "confirmation": "确认付费试跑",
            "max_total_charge_usd": 0.01,
        },
    )
    assert rejected.status_code == 412, rejected.text
    assert rejected.json()["error"]["code"] == (
        "apify_actor_source_requires_pool_upgrade"
    )
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_validations"
    ).fetchone()[0] == counts_before["validations"]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs"
    ).fetchone()[0] == counts_before["jobs"]


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
    _ops, route, _revisions = _ready_route(store, route_key="x/profile")

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
    assert source["setup_type"] == "x_profile"
    assert source["config"] == {
        "target": "openai",
        "fetch_limit": 20,
        "analysis_mode": "full",
    }
    assert "profile_id" not in source["config"]
    stored = store.get_source(source["id"])
    assert stored["config"]["profile_id"] == route["route_id"]
    assert "platform" not in source["config"]
    assert "kind" not in source["config"]
    binding = ApifyActorOpsService(store).get_source_binding(source["id"])
    assert binding["validation_status"] == "pending_validation"
    assert binding["route_id"] == stored["config"]["profile_id"]

    legacy_patch = client.patch(
        f"/api/catalog/sources/{source['id']}",
        json={
            "config": {
                "profile_id": route["route_id"],
                "target": "openai",
                "fetch_limit": 25,
                "analysis_mode": "personal_only",
            }
        },
    )
    assert legacy_patch.status_code == 200, legacy_patch.text
    assert legacy_patch.json()["data"]["setup_type"] == "x_profile"
    assert legacy_patch.json()["data"]["config"] == {
        "target": "openai",
        "fetch_limit": 25,
        "analysis_mode": "personal_only",
    }
    assert store.get_source(source["id"])["config"]["profile_id"] == route["route_id"]


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


def test_candidate_refresh_queues_one_free_discovery_atomically(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops = ApifyActorOpsService(store)
    route = next(
        item
        for item in ops.list_routes()
        if item["route_key"] == "instagram/profile/items"
    )

    response = client.post(
        f"/api/admin/apify-routes/{route['route_id']}/pool-candidates/refresh",
        json={"expected_generation": int(route["generation"])},
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["status"] == "refreshing"
    assert data["route_id"] == route["route_id"]
    run = store.connect().execute(
        """
        SELECT stage, trigger_reason FROM apify_actor_discovery_runs
        WHERE workspace_id = ? AND run_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, data["run_id"]),
    ).fetchone()
    assert dict(run) == {
        "stage": "queued",
        "trigger_reason": "manual_candidate_refresh",
    }
    job = store.connect().execute(
        """
        SELECT status, max_attempts FROM fetch_jobs
        WHERE workspace_id = ? AND job_type = 'apify_actor_discovery'
          AND json_extract(payload_json, '$.run_id') = ?
        """,
        (DEFAULT_WORKSPACE_ID, data["run_id"]),
    ).fetchone()
    assert dict(job) == {"status": "queued", "max_attempts": 1}

    duplicate = client.post(
        f"/api/admin/apify-routes/{route['route_id']}/pool-candidates/refresh",
        json={"expected_generation": int(route["generation"])},
    )
    assert duplicate.status_code == 409
    assert duplicate.json()["error"]["code"] == "apify_actor_discovery_active"
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM apify_actor_discovery_runs
        WHERE workspace_id = ? AND route_id = ?
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    ).fetchone()[0] == 1
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM fetch_jobs
        WHERE workspace_id = ? AND job_type = 'apify_actor_discovery'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()[0] == 1


def test_candidate_refresh_job_failure_rolls_back_discovery(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops = ApifyActorOpsService(store)
    route = next(
        item
        for item in ops.list_routes()
        if item["route_key"] == "instagram/profile/items"
    )

    def fail_create_job(*_args, **_kwargs):
        raise RuntimeError("queue unavailable")

    monkeypatch.setattr(JobQueue, "create_job", fail_create_job)
    response = client.post(
        f"/api/admin/apify-routes/{route['route_id']}/pool-candidates/refresh",
        json={"expected_generation": int(route["generation"])},
    )

    assert response.status_code == 500
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM apify_actor_discovery_runs
        WHERE workspace_id = ? AND route_id = ?
          AND trigger_reason = 'manual_candidate_refresh'
        """,
        (DEFAULT_WORKSPACE_ID, route["route_id"]),
    ).fetchone()[0] == 0
    assert store.connect().execute(
        """
        SELECT COUNT(*) FROM fetch_jobs
        WHERE workspace_id = ? AND job_type = 'apify_actor_discovery'
        """,
        (DEFAULT_WORKSPACE_ID,),
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


def test_youtube_active_pool_api_accepts_route_minimum_single_actor(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, revisions = _ready_route(
        store,
        route_key="youtube/channel/items",
        activate=False,
    )

    response = client.put(
        f"/api/admin/apify-routes/{route['route_id']}/active-pool",
        json={
            "expected_generation": route["generation"],
            "slots": [
                {"slot": "primary", "revision_id": revisions[0]},
                {"slot": "backup_1", "revision_id": None},
                {"slot": "backup_2", "revision_id": None},
            ],
        },
    )

    assert response.status_code == 200, response.text
    data = response.json()["data"]
    assert data["min_runtime_healthy"] == 1
    assert data["runnable_slots"] == 1
    assert data["slots"][0]["runnable"] is True
    assert [slot["revision_id"] for slot in data["slots"]] == [
        revisions[0],
        None,
        None,
    ]


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
    assert projected["schema_version"] == 5
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
    assert projected["spent_usd"] == 0
    assert projected["reserved_usd"] == 0.02
    assert projected["unreconciled_cost_count"] == 0
    assert projected["rejections"] == [
        {"reason": "actor_full_permission", "count": 2}
    ]
    assert "not-persisted" not in response.text


def test_canary_batch_plan_is_server_selected_and_approval_is_atomic(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, run, revisions = _discovery_batch_candidates(store)
    plan_endpoint = (
        f"/api/admin/apify-discovery-runs/{run['run_id']}/canary-plan"
    )
    plan_response = client.get(plan_endpoint)
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()["data"]
    assert plan["ready"] is True
    assert plan["activation_ready"] is False
    assert plan["max_total_charge_usd"] == 0.06
    assert plan["attempts_used"] == 0
    assert plan["attempts_remaining"] == 5
    assert plan["budget_remaining_usd"] == 0.1
    assert len(plan["items"]) == 3
    assert {item["revision_id"] for item in plan["items"]} == set(revisions)
    assert len({item["publisher"] for item in plan["items"]}) == 3

    endpoint = (
        f"/api/admin/apify-discovery-runs/{run['run_id']}/canary-batches"
    )
    request = {
        "expected_generation": route["generation"],
        "expected_plan_hash": plan["plan_hash"],
        "approval_id": "batch-approval-api-0001",
        "confirmation": "确认付费验证主备",
        "max_candidates": 3,
        "max_total_charge_usd": plan["max_total_charge_usd"],
    }
    approved = client.post(endpoint, json=request)
    assert approved.status_code == 200, approved.text
    payload = approved.json()["data"]
    assert payload["batch"]["status"] == "queued"
    assert payload["batch"]["planned_count"] == 3
    assert payload["batch"]["actual_cost_usd"] is None
    assert payload["batch"]["cost_final"] is False
    assert payload["job"]["status"] == "queued"
    batch_id = payload["batch"]["batch_id"]

    validations = store.connect().execute(
        """
        SELECT status, cost_usd, cost_final, counts_toward_canary
        FROM apify_actor_validations
        WHERE discovery_run_id = ?
        ORDER BY created_at
        """,
        (run["run_id"],),
    ).fetchall()
    assert len(validations) == 3
    assert all(str(row["status"]) == "queued" for row in validations)
    assert all(row["cost_usd"] is None for row in validations)
    assert all(int(row["cost_final"]) == 0 for row in validations)
    assert all(int(row["counts_toward_canary"]) == 0 for row in validations)

    replay = client.post(endpoint, json=request)
    assert replay.status_code == 200, replay.text
    replay_data = replay.json()["data"]
    assert replay_data["batch"]["batch_id"] == batch_id
    assert replay_data["job"]["id"] == payload["job"]["id"]
    assert store.connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs WHERE job_type = 'apify_actor_canary_batch'"
    ).fetchone()[0] == 1

    refreshed = client.get(
        f"/api/admin/apify-discovery-runs/{run['run_id']}"
    )
    assert refreshed.status_code == 200, refreshed.text
    assert refreshed.json()["data"]["canary_batch"]["batch_id"] == batch_id


def test_canary_plan_reuses_route_history_after_empty_replenishment(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops, route, original_run, revisions = _discovery_batch_candidates(store)
    validation = ops.approve_revision_canary(
        str(route["route_id"]),
        revisions[0],
        expected_generation=int(route["generation"]),
        approval_id="route-history-success-0001",
        confirmation="确认付费试跑",
        max_cost_usd=0.02,
        reference_fingerprint=hashlib.sha256(
            b"route-history-reference"
        ).hexdigest(),
        discovery_run_id=str(original_run["run_id"]),
    )
    ops.record_validation(
        str(validation["validation_id"]),
        status="succeeded",
        semantic_outcome="valid_nonempty",
        cost_usd=0.001,
        cost_final=True,
        counts_toward_canary=True,
    )
    ops.transition_revision(
        revisions[0],
        expected_lifecycle="static_valid",
        lifecycle="probationary",
    )
    replenishment = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="canary_batch_replenishment",
        expected_generation=int(route["generation"]),
    )
    ops.update_discovery_run(
        str(replenishment["run_id"]),
        expected_stage="queued",
        stage="candidate_shortfall",
        error_code="input_validation_candidate_shortfall",
        candidate_count=0,
    )

    response = client.get(
        f"/api/admin/apify-discovery-runs/{replenishment['run_id']}/canary-plan"
    )

    assert response.status_code == 200, response.text
    plan = response.json()["data"]
    assert plan["ready"] is True
    assert plan["successful_actor_count"] == 1
    assert plan["successful_publisher_count"] == 1
    assert plan["attempts_used"] == 1
    assert plan["attempts_remaining"] == 4
    assert plan["budget_remaining_usd"] == 0.099
    assert plan["max_total_charge_usd"] == 0.02
    assert [item["revision_id"] for item in plan["items"]] == [revisions[1]]

    approved = client.post(
        (
            f"/api/admin/apify-discovery-runs/{replenishment['run_id']}"
            "/canary-batches"
        ),
        json={
            "expected_generation": route["generation"],
            "expected_plan_hash": plan["plan_hash"],
            "approval_id": "route-history-batch-0001",
            "confirmation": "确认付费验证主备",
            "max_candidates": 3,
            "max_total_charge_usd": plan["max_total_charge_usd"],
        },
    )
    assert approved.status_code == 200, approved.text
    approved_data = approved.json()["data"]
    assert approved_data["batch"]["planned_count"] == 1
    assert approved_data["batch"]["items"][0]["revision_id"] == revisions[1]
    assert approved_data["job"]["status"] == "queued"


def test_canary_batch_rejects_stale_plan_and_browser_candidate_override(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    _ops, route, run, revisions = _discovery_batch_candidates(store)
    plan = client.get(
        f"/api/admin/apify-discovery-runs/{run['run_id']}/canary-plan"
    ).json()["data"]
    endpoint = (
        f"/api/admin/apify-discovery-runs/{run['run_id']}/canary-batches"
    )
    base = {
        "expected_generation": route["generation"],
        "expected_plan_hash": plan["plan_hash"],
        "approval_id": "batch-approval-api-0002",
        "confirmation": "确认付费验证主备",
        "max_candidates": 3,
        "max_total_charge_usd": plan["max_total_charge_usd"],
    }
    override = client.post(
        endpoint,
        json={**base, "revision_ids": revisions[:2]},
    )
    assert override.status_code == 400

    stale = client.post(
        endpoint,
        json={**base, "expected_plan_hash": "0" * 64},
    )
    assert stale.status_code == 409
    assert stale.json()["error"]["code"] == "apify_actor_canary_plan_conflict"
    assert store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_canary_batches"
    ).fetchone()[0] == 0
    assert store.connect().execute(
        "SELECT COUNT(*) FROM fetch_jobs WHERE job_type = 'apify_actor_canary_batch'"
    ).fetchone()[0] == 0


def test_third_slot_api_is_server_selected_safe_and_applies_frozen_stage(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops, route, base_revisions = _ready_route(
        store,
        route_key="youtube/channel/items",
        activate=False,
    )
    active = ops.replace_active_pool(
        str(route["route_id"]),
        slots={
            "primary": base_revisions[0],
            "backup_1": base_revisions[1],
            "backup_2": None,
        },
        expected_generation=int(route["generation"]),
    )
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="api-third-slot",
        expected_generation=int(active["generation"]),
    )
    actor_id = "publisher-c/api-third-slot"
    candidate_id = ops.ensure_candidate(str(route["route_id"]), actor_id=actor_id)
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher-c",
        build_id="build-api-third-slot",
        build_number="8.0.4",
        manifest=_manifest(actor_id, "8.0.4"),
        lifecycle="static_valid",
        discovery_run_id=str(run["run_id"]),
    )
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="queued",
        stage="awaiting_canary_approval",
    )
    plan_endpoint = (
        f"/api/admin/apify-discovery-runs/{run['run_id']}"
        "/canary-plan?goal=complete_third"
    )
    plan_response = client.get(plan_endpoint)
    assert plan_response.status_code == 200, plan_response.text
    plan = plan_response.json()["data"]
    assert plan["schema_version"] == 2
    assert plan["goal"] == "complete_third"
    assert plan["required_success_count"] == 1
    assert [item["revision_id"] for item in plan["items"]] == [revision_id]
    assert "_source_snapshot" not in plan_response.text
    assert "target_fingerprint" not in plan_response.text

    endpoint = f"/api/admin/apify-discovery-runs/{run['run_id']}/canary-batches"
    request = {
        "goal": "complete_third",
        "expected_generation": active["generation"],
        "expected_plan_hash": plan["plan_hash"],
        "approval_id": "api-third-stage-approval-0001",
        "confirmation": "确认付费验证主备",
        "max_candidates": plan["max_candidates"],
        "max_total_charge_usd": plan["max_total_charge_usd"],
    }
    forbidden = client.post(
        endpoint,
        json={**request, "revision_ids": [revision_id], "source_ids": []},
    )
    assert forbidden.status_code == 400
    approved = client.post(endpoint, json=request)
    assert approved.status_code == 200, approved.text
    payload = approved.json()["data"]
    batch = payload["batch"]
    assert batch["goal"] == "complete_third"
    assert batch["pool_stage"]["goal"] == "complete_third"
    assert "target_fingerprint" not in approved.text
    assert "source_name" not in approved.text

    item = ops.get_canary_batch(str(batch["batch_id"]))["items"][0]
    ops.record_validation(
        str(item["validation_id"]),
        status="succeeded",
        semantic_outcome="valid_nonempty",
        cost_usd=0.01,
        cost_final=True,
    )
    ops.update_canary_batch_item(
        str(batch["batch_id"]),
        int(item["ordinal"]),
        status="succeeded",
        semantic_outcome="valid_nonempty",
        actual_cost_usd=0.01,
        cost_final=True,
    )
    ops.transition_revision(
        revision_id,
        expected_lifecycle="static_valid",
        lifecycle="probationary",
    )
    assert ops.prepare_pool_stage_source_validations(
        str(batch["pool_stage_id"])
    ) == []
    assert ops.finalize_canary_batch(str(batch["batch_id"]))["status"] == (
        "activation_ready"
    )
    store.connect().execute(
        """
        UPDATE fetch_jobs
        SET status = 'succeeded', finished_at = updated_at
        WHERE id = ?
        """,
        (payload["job"]["id"],),
    )
    store.connect().commit()

    before = client.get(f"/api/admin/apify-routes/{route['route_id']}")
    assert before.status_code == 200
    assert before.json()["data"]["workflow"]["kind"] == (
        "backup_2_activation_approval_required"
    )
    activated = client.post(
        f"/api/admin/apify-routes/{route['route_id']}/active-pool/activate",
        json={
            "expected_generation": active["generation"],
            "confirmation": "确认启用 Actor 主备",
            "stage_id": batch["pool_stage_id"],
            "expected_plan_hash": plan["plan_hash"],
            "apply_id": "api-third-stage-apply-0001",
        },
    )
    assert activated.status_code == 200, activated.text
    activated_data = activated.json()["data"]
    assert [slot["revision_id"] for slot in activated_data["slots"][:2]] == (
        base_revisions[:2]
    )
    assert activated_data["slots"][2]["revision_id"] == revision_id
    assert activated_data["workflow"]["kind"] == "probation_observing"
    assert "target_fingerprint" not in activated.text


def test_manual_third_slot_accepts_only_opaque_candidate_and_probationary_base(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops, route, base_revisions = _ready_route(
        store,
        route_key="youtube/channel/items",
        activate=False,
    )
    store.connect().execute(
        """
        UPDATE apify_actor_adapter_revisions SET lifecycle = 'probationary'
        WHERE workspace_id = ? AND revision_id IN (?, ?)
        """,
        (DEFAULT_WORKSPACE_ID, base_revisions[0], base_revisions[1]),
    )
    store.connect().commit()
    active = ops.replace_active_pool(
        str(route["route_id"]),
        slots={
            "primary": base_revisions[0],
            "backup_1": base_revisions[1],
            "backup_2": None,
        },
        expected_generation=int(route["generation"]),
    )
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="api-manual-third-slot",
        expected_generation=int(active["generation"]),
    )
    actor_id = "publisher-c/api-manual-third-slot"
    candidate_id = ops.ensure_candidate(str(route["route_id"]), actor_id=actor_id)
    older_revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher-c",
        build_id="build-api-manual-third-slot",
        build_number="9.0.1",
        manifest=_manifest(actor_id, "9.0.1"),
        lifecycle="static_valid",
        discovery_run_id=str(run["run_id"]),
    )
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher-c",
        build_id="build-api-manual-third-slot-latest",
        build_number="9.0.2",
        manifest=_manifest(actor_id, "9.0.2"),
        lifecycle="static_valid",
        discovery_run_id=str(run["run_id"]),
    )
    assert revision_id != older_revision_id
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="queued",
        stage="awaiting_canary_approval",
    )

    candidates_response = client.get(
        f"/api/admin/apify-routes/{route['route_id']}/pool-candidates"
        "?goal=complete_third"
    )
    assert candidates_response.status_code == 200, candidates_response.text
    candidates = candidates_response.json()["data"]
    assert candidates["required_selection_count"] == 1
    assert len(candidates["candidates"]) == 1
    candidate = candidates["candidates"][0]
    assert {key: candidate[key] for key in (
        "candidate_id", "actor_public_name", "publisher", "pricing",
        "selectable", "unavailable_reason",
    )} == {
        "candidate_id": candidate_id,
        "actor_public_name": "publisher-c Actor",
        "publisher": "publisher-c",
        "pricing": {},
        "selectable": True,
        "unavailable_reason": None,
    }
    assert candidate["max_validation_charge_usd"] == 0.10
    assert candidate["validation_options"] == {
        "timeout_seconds": 300,
        "timeout_min_seconds": 180,
        "timeout_max_seconds": 900,
        "sample_items": 1,
        "allowed_sample_items": [1],
        "max_charge_usd": 0.02,
        "max_charge_limit_usd": 0.10,
        "supports_sample_items": False,
        "options_hash": candidate["validation_options"]["options_hash"],
        "profile_hash": candidate["validation_options"]["profile_hash"],
    }
    assert len(candidate["validation_options"]["options_hash"]) == 64
    assert len(candidate["validation_options"]["profile_hash"]) == 64
    assert candidate["last_failure"] is None
    assert candidate["requires_profile_change"] is False
    assert "revision_id" not in candidates_response.text
    assert "manifest_hash" not in candidates_response.text
    assert actor_id not in candidates_response.text

    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'disabled',
            last_error_code = 'apify_actor_candidate_unavailable'
        WHERE workspace_id = ? AND id = ?
        """,
        (DEFAULT_WORKSPACE_ID, candidate_id),
    )
    store.connect().commit()
    disabled = client.get(
        f"/api/admin/apify-routes/{route['route_id']}/pool-candidates"
        "?goal=complete_third"
    )
    assert disabled.status_code == 200
    assert disabled.json()["data"]["candidates"][0] == {
        **candidate,
        "selectable": False,
        "unavailable_reason": "apify_actor_candidate_unavailable",
    }
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'closed', last_error_code = NULL
        WHERE workspace_id = ? AND id = ?
        """,
        (DEFAULT_WORKSPACE_ID, candidate_id),
    )
    store.connect().commit()

    plan_endpoint = f"/api/admin/apify-discovery-runs/{run['run_id']}/canary-plan"
    plan_request = {
        "goal": "complete_third",
        "candidate_ids": [candidate_id],
        "candidate_validation_profiles": [{
            "candidate_id": candidate_id,
            "timeout_seconds": 300,
            "sample_items": 1,
            "max_charge_usd": 0.02,
            "options_hash": candidate["validation_options"]["options_hash"],
        }],
        "expected_generation": active["generation"],
        "target_slot_count": 3,
    }
    forbidden = client.post(
        plan_endpoint,
        json={**plan_request, "revision_id": revision_id},
    )
    assert forbidden.status_code == 400
    planned = client.post(plan_endpoint, json=plan_request)
    assert planned.status_code == 200, planned.text
    plan = planned.json()["data"]
    assert plan["schema_version"] == 3
    assert plan["selection_mode"] == "manual"
    assert plan["target_slot_count"] == 3
    assert plan["items"][0]["candidate_id"] == candidate_id
    assert plan["items"][0]["revision_id"] == revision_id
    assert plan["items"][0]["build_number"] == "9.0.2"

    approved = client.post(
        f"/api/admin/apify-discovery-runs/{run['run_id']}/canary-batches",
        json={
            "goal": "complete_third",
            "candidate_ids": [candidate_id],
            "candidate_validation_profiles": plan_request[
                "candidate_validation_profiles"
            ],
            "target_slot_count": 3,
            "expected_generation": active["generation"],
            "expected_plan_hash": plan["plan_hash"],
            "approval_id": "api-manual-third-stage-0001",
            "confirmation": "确认付费验证主备",
            "max_candidates": 1,
            "max_total_charge_usd": plan["max_total_charge_usd"],
        },
    )
    assert approved.status_code == 200, approved.text
    stage = approved.json()["data"]["batch"]["pool_stage"]
    assert stage["goal"] == "complete_third"
    assert stage["selection_mode"] == "manual"
    assert stage["target_slot_count"] == 3


def test_manual_compatibility_plan_projects_single_candidate_limit(
    tmp_path,
    monkeypatch,
) -> None:
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops = ApifyActorOpsService(store)
    route = next(
        row for row in ops.list_routes() if row["route_key"] == "x/profile"
    )
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="api-compatibility-shortfall",
        expected_generation=int(route["generation"]),
    )
    revision_id = ops.ensure_compatibility_trial_revision(
        route_id=str(route["route_id"]),
        discovery_run_id=str(run["run_id"]),
        actor_id="compatibility/api-x",
        publisher="compatibility",
        build_id="compatibility-build", build_number="1.0.0",
        pricing={"minimalMaxTotalChargeUsd": 0.01},
        permission_level="limited",
        input_schema_hash="a" * 64, output_schema_hash="b" * 64,
        compatibility_preflight_version=2, free_input_validated=True, output_schema_proves_items=True, x_profile_semantics_proven=True,
    )
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="queued",
        stage="candidate_shortfall",
        error_code="candidate_shortfall",
    )
    candidate_id = str(
        store.connect().execute(
            """
            SELECT candidate_id FROM apify_actor_adapter_revisions
            WHERE workspace_id = ? AND revision_id = ?
            """,
            (DEFAULT_WORKSPACE_ID, revision_id),
        ).fetchone()["candidate_id"]
    )
    candidates_response = client.get(
        f"/api/admin/apify-routes/{route['route_id']}/pool-candidates"
        "?goal=compatibility_single"
    )
    assert candidates_response.status_code == 200, candidates_response.text
    candidate = next(
        row
        for row in candidates_response.json()["data"]["candidates"]
        if row["candidate_id"] == candidate_id
    )
    options = candidate["validation_options"]

    response = client.post(
        f"/api/admin/apify-discovery-runs/{run['run_id']}/canary-plan",
        json={
            "goal": "compatibility_single",
            "candidate_ids": [candidate_id],
            "candidate_validation_profiles": [{
                "candidate_id": candidate_id,
                "timeout_seconds": options["timeout_seconds"],
                "sample_items": options["sample_items"],
                "max_charge_usd": options["max_charge_usd"],
                "options_hash": options["options_hash"],
            }],
            "expected_generation": route["generation"],
            "target_slot_count": 1,
        },
    )

    assert response.status_code == 200, response.text
    plan = response.json()["data"]
    assert plan["goal"] == "compatibility_single"
    assert plan["max_candidates"] == 1
    assert plan["target_slot_count"] == 1
    assert plan["ready"] is True


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


def test_discovery_projection_stops_metadata_only_revision_retries(
    tmp_path,
    monkeypatch,
) -> None:
    monkeypatch.setenv("HORIZON_APIFY_KEY_POOL_ENABLED", "true")
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    ops, route, run, revision_id = _discovery_revision(store)
    validation = ops.approve_revision_canary(
        str(route["route_id"]),
        revision_id,
        expected_generation=int(route["generation"]),
        approval_id="approval-metadata-only-projection",
        confirmation="确认付费试跑",
        max_cost_usd=0.02,
        reference_fingerprint="a" * 64,
        discovery_run_id=str(run["run_id"]),
    )
    store.connect().execute(
        """
        UPDATE apify_actor_validations
        SET status = 'failed', semantic_outcome = 'apify_actor_metadata_only',
            cost_usd = 0.001, completed_at = created_at
        WHERE validation_id = ?
        """,
        (validation["validation_id"],),
    )
    store.connect().commit()

    response = client.get(
        f"/api/admin/apify-discovery-runs/{run['run_id']}"
    )

    assert response.status_code == 200, response.text
    candidate = response.json()["data"]["candidates"][0]
    assert candidate["awaiting_approval"] is False
    assert candidate["revision"]["can_canary"] is False
    assert candidate["rejection_reasons"] == ["apify_actor_metadata_only"]

    repeated = client.post(
        (
            f"/api/admin/apify-discovery-runs/{run['run_id']}/candidates/"
            f"{revision_id}/canary"
        ),
        json={
            "expected_generation": int(route["generation"]),
            "approval_id": "approval-metadata-only-repeat",
            "confirmation": "确认付费试跑",
            "max_total_charge_usd": 0.02,
        },
    )
    assert repeated.status_code == 412, repeated.text
    assert repeated.json()["error"]["code"] == (
        "apify_actor_revision_output_incompatible"
    )
