from __future__ import annotations

import json
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.actorops_v2_projection import actorops_v2_route_additions
from src.api.server import create_app
from src.services.actorops.domain import AssignmentRole, CandidateLifecycle
from src.services.actorops.repository import ActorOpsRepository
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _store(tmp_path: Path) -> ServiceStore:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    return store


def _route_with_one_assignment(store: ServiceStore) -> tuple[ActorOpsRepository, str]:
    connection = store.connect()
    route_id = str(connection.execute(
        "SELECT route_id FROM actor_routes_v2 ORDER BY route_id LIMIT 1"
    ).fetchone()[0])
    repository = ActorOpsRepository(connection, DEFAULT_WORKSPACE_ID)
    with repository.transaction():
        repository.create_candidate(
            candidate_id="facade-candidate", route_id=route_id,
            actor_id="publisher/facade", publisher="publisher",
            build_id="build-facade", build_number="1.0.0", manifest_json="{}",
            manifest_hash="a" * 64, input_schema_hash="b" * 64,
            output_schema_hash="c" * 64, lifecycle=CandidateLifecycle.CERTIFIED,
        )
        repository.assign_candidate(
            route_id, "facade-candidate", AssignmentRole.ACTIVE, priority=0,
            expected_route_generation=1, expected_candidate_generation=1,
        )
    return repository, route_id


def _client(tmp_path: Path, monkeypatch, *, v2_enabled: bool = True) -> TestClient:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "true" if v2_enabled else "false")
    data_dir = tmp_path / "api-data"
    static_dir = tmp_path / "static"
    data_dir.mkdir()
    static_dir.mkdir()
    (data_dir / "config.json").write_text(json.dumps({
        "version": "1.0", "ai": {"enabled": False}, "tags": [], "personal_tags": [],
        "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
        "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
    }), encoding="utf-8")
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return TestClient(create_app(data_dir=data_dir, static_dir=static_dir))


def _login(client: TestClient) -> None:
    response = client.post("/api/auth/login", json={"username": "owner", "password": "secret-password"})
    assert response.status_code == 200


def test_facade_flag_off_does_not_query_global_26_or_global_25(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path)
    route_id = str(store.connect().execute(
        "SELECT route_id FROM apify_actor_route_profiles ORDER BY route_id LIMIT 1"
    ).fetchone()[0])
    statements: list[str] = []
    store.connect().set_trace_callback(statements.append)
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "false")

    assert actorops_v2_route_additions(store, DEFAULT_WORKSPACE_ID, route_id) is None

    joined = "\n".join(statements).casefold()
    assert "actor_routes_v2" not in joined
    assert "version = 25" not in joined
    store.close()


def test_v1_route_list_stays_global_26_and_25_inert_when_flag_is_off(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch, v2_enabled=False)
    _login(client)
    statements: list[str] = []
    client.app.state.service_store.connect().set_trace_callback(statements.append)

    response = client.get("/api/admin/apify-routes")

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload.get("actorops_version") is None
    assert all("actorops_version" not in route for route in payload["routes"])
    joined = "\n".join(statements).casefold()
    assert "actor_routes_v2" not in joined
    assert "version = 25" not in joined


def test_facade_projects_health_assignment_lkg_and_disabled_policy(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path)
    _repository, route_id = _route_with_one_assignment(store)
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "true")

    projection = actorops_v2_route_additions(store, DEFAULT_WORKSPACE_ID, route_id)

    assert projection is not None
    assert projection["actorops_version"] == 2
    assert projection["health"] == "degraded"
    assert projection["active_candidate"]["candidate_id"] == "facade-candidate"
    assert projection["standby_candidates"] == []
    assert projection["degraded_reason"] == "actorops_v2_route_disabled"
    policy = projection["maintenance_policy"]
    assert policy["authorized"] is False
    assert policy["workspace"]["enabled"] is False
    assert policy["route"]["enabled"] is False
    assert "manifest_json" not in json.dumps(projection, sort_keys=True)
    store.close()


def test_v2_maintenance_policy_routes_are_admin_cas_and_do_not_start_probe(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)

    workspace = client.get("/api/admin/apify-maintenance-policy")
    assert workspace.status_code == 200, workspace.text
    workspace_policy = workspace.json()["data"]
    assert workspace_policy["enabled"] is False
    enabled_workspace = client.patch(
        "/api/admin/apify-maintenance-policy",
        json={"enabled": True, "expected_generation": workspace_policy["generation"]},
    )
    assert enabled_workspace.status_code == 200, enabled_workspace.text

    routes = client.get("/api/admin/apify-routes").json()["data"]["routes"]
    assert routes[0]["actorops_version"] == 2
    assert routes[0]["health"] in {"healthy", "degraded", "unavailable"}
    assert "maintenance_policy" in routes[0]
    assert "manifest_json" not in json.dumps(routes[0], sort_keys=True)
    route_id = str(routes[0]["route_id"])
    route_policy = client.get(f"/api/admin/apify-routes/{route_id}/maintenance-policy")
    assert route_policy.status_code == 200, route_policy.text
    enabled_route = client.patch(
        f"/api/admin/apify-routes/{route_id}/maintenance-policy",
        json={"enabled": True, "expected_generation": route_policy.json()["data"]["route"]["generation"]},
    )
    assert enabled_route.status_code == 200, enabled_route.text
    conflict = client.patch(
        f"/api/admin/apify-routes/{route_id}/maintenance-policy",
        json={"enabled": False, "expected_generation": route_policy.json()["data"]["route"]["generation"]},
    )
    assert conflict.status_code == 409
    assert client.app.state.service_store.connect().execute(
        "SELECT COUNT(*) FROM actor_attempts_v2"
    ).fetchone()[0] == 0


def test_v2_policy_endpoint_is_flag_gated_without_global_26_reads(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch, v2_enabled=False)
    _login(client)
    statements: list[str] = []
    client.app.state.service_store.connect().set_trace_callback(statements.append)

    response = client.get("/api/admin/apify-maintenance-policy")

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "actorops_v2_unavailable"
    joined = "\n".join(statements).casefold()
    assert "actor_routes_v2" not in joined
    assert "version = 25" not in joined
