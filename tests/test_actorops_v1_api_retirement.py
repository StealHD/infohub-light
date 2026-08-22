"""Phase 5 contract: v1 ActorOps admin routes cannot reach online state."""

from __future__ import annotations

from pathlib import Path

from fastapi.testclient import TestClient

from src.services.actorops.domain import AssignmentRole
from tests.test_actorops_v1_retirement_boundary import (
    install_actorops_v1_deny_authorizer,
)
from tests.test_actorops_v2_api_facade import (
    _client,
    _login,
    _route_with_one_assignment,
    _route_with_two_assignments,
)


RETIRED_ADMIN_ENDPOINTS = (
    ("GET", "/api/admin/apify-routes/route/pool-candidates"),
    ("PUT", "/api/admin/apify-routes/route/active-pool"),
    ("POST", "/api/admin/apify-routes/route/active-pool/remove"),
    ("POST", "/api/admin/apify-routes/route/active-pool/activate"),
    ("POST", "/api/admin/apify-routes/route/verified-pool-activation"),
    ("PATCH", "/api/admin/apify-routes/route/freshness-settings"),
    ("GET", "/api/admin/apify-routes/route/freshness-plan"),
    ("POST", "/api/admin/apify-routes/route/freshness-checks"),
    ("GET", "/api/admin/apify-freshness-checks/check"),
    ("POST", "/api/admin/apify-support-checks"),
    ("GET", "/api/admin/apify-discovery-runs/run"),
    ("GET", "/api/admin/apify-discovery-runs/run/canary-plan"),
    ("POST", "/api/admin/apify-discovery-runs/run/canary-plan"),
    ("POST", "/api/admin/apify-discovery-runs/run/canary-batches"),
    ("POST", "/api/admin/apify-discovery-runs/run/candidates/revision/canary"),
    ("GET", "/api/admin/apify-canary-batches/batch"),
    ("PATCH", "/api/admin/sources/source/apify-preference"),
    ("POST", "/api/admin/sources/source/apify-validations/revision/canary"),
    ("POST", "/api/admin/apify-actor-evaluations/evaluation/retry"),
    ("POST", "/api/admin/apify-routes/route/validations/reconcile"),
    ("GET", "/api/admin/apify-discovery-settings"),
    ("PATCH", "/api/admin/apify-discovery-settings"),
    ("POST", "/api/admin/apify-discovery-measurements"),
    ("GET", "/api/admin/apify-actor-routes/x/profile"),
    ("PUT", "/api/admin/apify-actor-routes/x/profile/order"),
    ("POST", "/api/admin/apify-actor-routes/x/profile/candidates/candidate/enable"),
    ("POST", "/api/admin/apify-actor-routes/x/profile/candidates/candidate/disable"),
    ("POST", "/api/admin/apify-actor-routes/x/profile/candidates/candidate/canary"),
)


def _deny_v1_history(client: TestClient, monkeypatch) -> None:
    store = client.app.state.service_store
    original_connect = store.connect

    def denied_connect():
        connection = original_connect()
        install_actorops_v1_deny_authorizer(connection)
        return connection

    monkeypatch.setattr(store, "connect", denied_connect)


def test_retired_actorops_v1_endpoints_are_authenticated_stable_410s(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)

    unauthenticated = client.get(RETIRED_ADMIN_ENDPOINTS[0][1])
    assert unauthenticated.status_code == 401

    _login(client)
    for method, path in RETIRED_ADMIN_ENDPOINTS:
        response = client.request(method, path, json={})

        assert response.status_code == 410, (method, path, response.text)
        assert response.json() == {
            "ok": False,
            "error": {
                "code": "actorops_v1_retired",
                "message": "ActorOps v1 admin API 已退役。",
                "retryable": False,
                "action": "Use the ActorOps v2 Route, Discovery, Binding or Replacement API.",
            },
        }


def test_v2_aliases_do_not_read_v1_history_or_create_v1_jobs(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    repository, route_id = _route_with_two_assignments(client.app.state.service_store)
    route = repository.get_route(route_id)
    _deny_v1_history(client, monkeypatch)

    refresh = client.post(
        f"/api/admin/apify-routes/{route_id}/pool-candidates/refresh",
        json={"expected_generation": route.generation},
    )
    assert refresh.status_code == 200, refresh.text
    assert refresh.json()["data"]["schema_version"] == 2
    assert refresh.json()["data"]["discovery_id"]

    promote = client.post(
        f"/api/admin/apify-routes/{route_id}/active-pool/promote",
        json={
            "target_slot": "backup_1",
            "expected_generation": route.generation,
            "confirmation": "确认设为主用 Actor",
        },
    )
    assert promote.status_code == 200, promote.text
    assert promote.json()["data"]["schema_version"] == 2
    assert repository.get_candidate("facade-backup").assignment_role is AssignmentRole.ACTIVE

    cap = client.patch(
        f"/api/admin/apify-routes/{route_id}/price-cap",
        json={"expected_generation": route.generation + 1, "per_run_cap_usd": 0.01},
    )
    assert cap.status_code == 200, cap.text
    assert cap.json()["data"]["schema_version"] == 2
    assert cap.json()["data"]["per_run_cap_usd"] == 0.01

    rows = client.app.state.service_store.connect().execute(
        "SELECT job_type FROM fetch_jobs ORDER BY created_at"
    ).fetchall()
    assert {str(row["job_type"]) for row in rows}.isdisjoint(
        {"apify_actor_discovery", "apify_actor_validation", "apify_actor_canary_batch", "apify_actor_freshness_check"}
    )


def test_v2_source_support_and_ready_activation_aliases_use_only_v2(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    store = client.app.state.service_store
    repository, route_id = _route_with_one_assignment(store)
    source_id = store.create_source(
        workspace_id="default",
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="v2 alias source",
        config={"platform": "x", "kind": "profile", "target": "example"},
    )
    from src.services.actorops.binding_service import ActorOpsBindingService

    binding = ActorOpsBindingService(store, workspace_id="default").ensure(source_id)
    _deny_v1_history(client, monkeypatch)

    support = client.get(f"/api/admin/sources/{source_id}/apify-support")
    assert support.status_code == 200, support.text
    assert support.json()["data"] == {
        "schema_version": 2,
        "source_id": source_id,
        "route_id": route_id,
        "binding_version": binding.binding_version,
        "binding_status": "pending",
        "enabled": False,
        "execution_mode": "blocked",
        "reason": "actorops_v2_binding_pending",
    }

    activate = client.post(
        f"/api/admin/sources/{source_id}/apify-binding/activate",
        json={
            "expected_generation": binding.binding_version,
            "confirmation": "确认首次启用",
        },
    )
    assert activate.status_code == 409
    assert activate.json()["error"]["code"] == "actorops_v2_binding_not_ready"

    youtube_source_id = store.create_source(
        workspace_id="default",
        scope="workspace",
        owner_user_id=None,
        source_type="rss",
        display_name="v2 ready YouTube alias source",
        config={
            "url": (
                "https://www.youtube.com/feeds/videos.xml?"
                "channel_id=UCabcdefghijklmnopqrstuv"
            )
        },
    )
    youtube_service = ActorOpsBindingService(store, workspace_id="default")
    youtube_pending = youtube_service.ensure(youtube_source_id)
    youtube_ready = youtube_service.verify(
        youtube_source_id,
        expected_binding_version=youtube_pending.binding_version,
        expected_target_fingerprint=youtube_pending.target_fingerprint,
    )

    enabled = client.post(
        f"/api/admin/sources/{youtube_source_id}/apify-binding/activate",
        json={
            "expected_generation": youtube_ready.binding_version,
            "confirmation": "确认首次启用",
        },
    )

    assert enabled.status_code == 200, enabled.text
    assert enabled.json()["data"] == {
        "schema_version": 2,
        "source_id": youtube_source_id,
        "route_id": youtube_ready.route_id,
        "binding_version": youtube_ready.binding_version,
        "binding_status": "ready",
        "enabled": True,
        "execution_mode": "native_fallback",
        "reason": "actorops_v2_route_disabled_native_fallback",
    }


def test_openapi_omits_v1_actorops_payload_paths(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    paths = client.get("/openapi.json").json()["paths"]

    assert "/api/admin/apify-routes/{route_id}/pool-candidates/refresh" in paths
    assert "/api/admin/apify-routes/{route_id}/active-pool/promote" in paths
    for _method, path in RETIRED_ADMIN_ENDPOINTS:
        normalized = path.replace("/route/", "/{route_id}/").replace(
            "/run/", "/{run_id}/"
        ).replace("/revision/", "/{revision_id}/").replace(
            "/batch", "/{batch_id}").replace("/check", "/{check_id}").replace(
            "/source/", "/{source_id}/"
        ).replace("/evaluation/", "/{evaluation_id}/").replace(
            "/candidate/", "/{candidate_id}/"
        )
        assert normalized not in paths
