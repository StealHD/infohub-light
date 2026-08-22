from __future__ import annotations

import json
from datetime import datetime, timezone
from pathlib import Path

from fastapi.testclient import TestClient

from src.api.actorops_v2_projection import actorops_v2_route_additions
from src.api.server import create_app
from src.services.actorops.domain import (
    AssignmentRole, CandidateLifecycle, DiscoveryStage, DiscoveryStatus,
)
from src.services.actorops.repository import ActorOpsRepository
from src.services.actorops.admin_service import ActorOpsAdminUnavailable
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from tests.test_actorops_v1_retirement_boundary import (
    install_actorops_v1_deny_authorizer,
)


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


def _route_with_two_assignments(store: ServiceStore) -> tuple[ActorOpsRepository, str]:
    repository, route_id = _route_with_one_assignment(store)
    with repository.transaction():
        repository.create_candidate(
            candidate_id="facade-backup", route_id=route_id,
            actor_id="publisher/backup", publisher="backup publisher",
            build_id="build-backup", build_number="2.0.0", manifest_json="{}",
            manifest_hash="d" * 64, input_schema_hash="e" * 64,
            output_schema_hash="f" * 64, lifecycle=CandidateLifecycle.CERTIFIED,
        )
        repository.assign_candidate(
            route_id, "facade-backup", AssignmentRole.STANDBY, priority=1,
            expected_route_generation=2, expected_candidate_generation=1,
        )
    return repository, route_id


def _client(tmp_path: Path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
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


def test_facade_reads_only_v2_route_facts(tmp_path: Path) -> None:
    store = _store(tmp_path)
    route_id = str(store.connect().execute(
        "SELECT route_id FROM actor_routes_v2 ORDER BY route_id LIMIT 1"
    ).fetchone()[0])
    statements: list[str] = []
    store.connect().set_trace_callback(statements.append)
    assert actorops_v2_route_additions(store, DEFAULT_WORKSPACE_ID, route_id)

    joined = "\n".join(statements).casefold()
    assert "actor_routes_v2" in joined
    assert "apify_actor_route_profiles" not in joined
    store.close()


def test_admin_route_list_is_v2_only(tmp_path: Path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    response = client.get("/api/admin/apify-routes")

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["schema_version"] == 2
    assert {route["route_key"] for route in payload["routes"]} == {
        "x/profile/items", "instagram/profile/items", "youtube/channel/items",
    }


def test_facade_projects_health_assignment_lkg_and_disabled_policy(
    tmp_path: Path, monkeypatch
) -> None:
    store = _store(tmp_path)
    _repository, route_id = _route_with_one_assignment(store)
    projection = actorops_v2_route_additions(store, DEFAULT_WORKSPACE_ID, route_id)

    assert projection is not None
    assert projection["actorops_version"] == 2
    assert projection["health"] == "degraded"
    assert projection["route_generation"] == 2
    assert projection["active_candidate"]["candidate_id"] == "facade-candidate"
    assert projection["active_candidate"]["generation"] == 2
    assert projection["standby_candidates"] == []
    assert projection["binding_summary"] == {"ready_count": 0, "pending_count": 0}
    assert projection["degraded_reason"] == "actorops_v2_route_disabled"
    policy = projection["maintenance_policy"]
    assert policy["authorized"] is False
    assert policy["workspace"]["enabled"] is False
    assert policy["route"]["enabled"] is False
    assert "manifest_json" not in json.dumps(projection, sort_keys=True)
    store.close()


def test_v2_candidate_promotion_is_admin_cas_and_does_not_start_actor(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    store = client.app.state.service_store
    repository, route_id = _route_with_two_assignments(store)
    route = repository.get_route(route_id)
    backup = repository.get_candidate("facade-backup")

    response = client.post(
        f"/api/admin/apify-routes/{route_id}/v2-candidates/facade-backup/promote",
        json={
            "expected_route_generation": route.generation,
            "expected_candidate_generation": backup.generation,
            "confirmation": "确认设为主用 Actor",
        },
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    assert payload["active_candidate"]["candidate_id"] == "facade-backup"
    assert repository.get_candidate("facade-candidate").assignment_role is AssignmentRole.STANDBY
    assert store.connect().execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0

    conflict = client.post(
        f"/api/admin/apify-routes/{route_id}/v2-candidates/facade-candidate/promote",
        json={
            "expected_route_generation": route.generation,
            "expected_candidate_generation": 4,
            "confirmation": "确认设为主用 Actor",
        },
    )
    assert conflict.status_code == 409


def test_v2_price_cap_is_cas_and_a_raise_requires_explicit_confirmation(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    repository, route_id = _route_with_one_assignment(client.app.state.service_store)
    route = repository.get_route(route_id)

    raise_without_confirmation = client.patch(
        f"/api/admin/apify-routes/{route_id}/v2-price-cap",
        json={"expected_route_generation": route.generation, "cap_usd": route.per_run_cap_usd + 0.01},
    )
    assert raise_without_confirmation.status_code == 422
    lowered = client.patch(
        f"/api/admin/apify-routes/{route_id}/v2-price-cap",
        json={"expected_route_generation": route.generation, "cap_usd": 0.01},
    )
    assert lowered.status_code == 200, lowered.text
    assert lowered.json()["data"]["per_run_cap_usd"] == 0.01
    assert client.app.state.service_store.connect().execute(
        "SELECT COUNT(*) FROM actor_attempts_v2"
    ).fetchone()[0] == 0


def test_v2_free_discovery_can_explicitly_retry_a_terminal_failure(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    repository, route_id = _route_with_one_assignment(client.app.state.service_store)
    route = repository.get_route(route_id)
    import src.api.actorops_v2_operator_routes as operator_routes
    from datetime import datetime, timezone

    key = operator_routes._hash(
        "operator-discovery", route_id, str(route.generation),
        datetime.now(timezone.utc).strftime("%Y%m%d%H"),
    )
    with repository.transaction():
        repository.create_discovery_job(
            discovery_id="terminal-discovery", idempotency_key=key, route_id=route_id,
            trigger_reason="operator_refresh",
            input_fingerprint=operator_routes._hash("route", str(route.route_key)),
        )
        repository.transition_discovery(
            "terminal-discovery", DiscoveryStatus.QUEUED, DiscoveryStage.STORE_SEARCH,
            DiscoveryStatus.RUNNING, DiscoveryStage.STORE_SEARCH,
        )
        repository.transition_discovery(
            "terminal-discovery", DiscoveryStatus.RUNNING, DiscoveryStage.STORE_SEARCH,
            DiscoveryStatus.FAILED, DiscoveryStage.STORE_SEARCH,
        )

    response = client.post(
        f"/api/admin/apify-routes/{route_id}/v2-discoveries",
        json={"expected_route_generation": route.generation},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["created"] is True
    assert response.json()["data"]["discovery_id"] != "terminal-discovery"


def test_v2_free_discovery_can_retry_completed_search_without_candidate(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    repository, route_id = _route_with_one_assignment(client.app.state.service_store)
    route = repository.get_route(route_id)
    import src.api.actorops_v2_operator_routes as operator_routes
    from datetime import datetime, timezone

    key = operator_routes._hash(
        "operator-discovery", route_id, str(route.generation),
        datetime.now(timezone.utc).strftime("%Y%m%d%H"),
    )
    with repository.transaction():
        repository.create_discovery_job(
            discovery_id="empty-discovery", idempotency_key=key, route_id=route_id,
            trigger_reason="operator_refresh",
            input_fingerprint=operator_routes._hash("route", str(route.route_key)),
        )
        repository.transition_discovery(
            "empty-discovery", DiscoveryStatus.QUEUED, DiscoveryStage.STORE_SEARCH,
            DiscoveryStatus.RUNNING, DiscoveryStage.STORE_SEARCH,
        )
        for stage in (
            DiscoveryStage.METADATA, DiscoveryStage.VALIDATION, DiscoveryStage.MAPPING,
            DiscoveryStage.RANKING, DiscoveryStage.PERSIST,
        ):
            previous = repository.discovery.get("empty-discovery")
            repository.transition_discovery(
                "empty-discovery", DiscoveryStatus.RUNNING, DiscoveryStage(str(previous["stage"])),
                DiscoveryStatus.RUNNING, stage,
            )
        repository.transition_discovery(
            "empty-discovery", DiscoveryStatus.RUNNING, DiscoveryStage.PERSIST,
            DiscoveryStatus.COMPLETED, DiscoveryStage.PERSIST,
        )

    response = client.post(
        f"/api/admin/apify-routes/{route_id}/v2-discoveries",
        json={"expected_route_generation": route.generation},
    )

    assert response.status_code == 200, response.text
    assert response.json()["data"]["created"] is True
    assert response.json()["data"]["discovery_id"] != "empty-discovery"


def test_v2_binding_verify_returns_zero_cost_evidence_failure(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    store = client.app.state.service_store
    repository, route_id = _route_with_one_assignment(store)
    route = repository.get_route(route_id)
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Pending v2 proof",
        config={
            "platform": route.route_key.platform,
            "kind": route.route_key.target_type,
            "target": "example",
        },
    )
    from src.services.actorops.binding_service import ActorOpsBindingService

    ActorOpsBindingService(
        store, workspace_id=DEFAULT_WORKSPACE_ID
    ).ensure(source_id)
    response = client.post(
        f"/api/admin/apify-routes/{route_id}/v2-bindings/verify",
        json={
            "expected_route_generation": route.generation,
            "confirmation": "确认核验来源绑定",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "actorops_v2_binding_evidence_missing"
    assert store.connect().execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0


def test_v2_manual_controls_ignore_feature_flag_and_read_only_v2(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    repository, route_id = _route_with_one_assignment(client.app.state.service_store)
    source_id = client.app.state.service_store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace", owner_user_id=None, source_type="apify_social",
        display_name="Pending proof",
        config={"platform": "x", "kind": "profile", "target": "example"},
    )
    from src.services.actorops.binding_service import ActorOpsBindingService

    ActorOpsBindingService(
        client.app.state.service_store, workspace_id=DEFAULT_WORKSPACE_ID
    ).ensure(source_id)
    statements: list[str] = []
    client.app.state.service_store.connect().set_trace_callback(statements.append)

    response = client.post(
        f"/api/admin/apify-routes/{route_id}/v2-bindings/verify",
        json={
            "expected_route_generation": repository.get_route(route_id).generation,
            "confirmation": "确认核验来源绑定",
        },
    )

    assert response.status_code == 409
    assert response.json()["error"]["code"] == "actorops_v2_binding_evidence_missing"
    joined = "\n".join(statements).casefold()
    assert "actor_routes_v2" in joined
    assert "apify_source_route_bindings" not in joined
    assert "version = 25" not in joined


def test_v2_operator_controls_ignore_feature_flag_and_read_only_v2(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    _repository, route_id = _route_with_one_assignment(client.app.state.service_store)
    response = client.get(f"/api/admin/apify-routes/{route_id}/v2-candidates")

    assert response.status_code == 200
    assert "facade-candidate" in {
        item["candidate_id"] for item in response.json()["data"]["candidates"]
    }


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
    assert client.get("/api/admin/apify-routes").json()["data"]["schema_version"] == 2
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


def test_v2_policy_endpoint_ignores_feature_flag_without_global_26_reads(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    response = client.get("/api/admin/apify-maintenance-policy")

    assert response.status_code == 200


def test_admin_list_and_detail_work_when_v1_history_reads_are_denied(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    store = client.app.state.service_store
    _repository, route_id = _route_with_one_assignment(store)
    original_connect = store.connect

    def denied_connect():
        connection = original_connect()
        install_actorops_v1_deny_authorizer(connection)
        return connection

    monkeypatch.setattr(store, "connect", denied_connect)

    listed = client.get("/api/admin/apify-routes")
    detail = client.get(f"/api/admin/apify-routes/{route_id}")

    assert listed.status_code == 200, listed.text
    assert detail.status_code == 200, detail.text
    data = detail.json()["data"]
    assert data["schema_version"] == 2
    assert data["candidates"]
    serialized = json.dumps(data, sort_keys=True)
    for forbidden in (
        "apify_actor_", "target_fingerprint", "manifest_json", "remote_run_id",
        "dataset_id", "secret_ref_id", "idempotency_key",
    ):
        assert forbidden not in serialized


def test_admin_distinguishes_missing_v2_migration_from_unavailable_store(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    store = client.app.state.service_store
    store.connect().execute("DROP TABLE actor_replacement_plans_v2")
    store.connect().commit()

    migration = client.get("/api/admin/apify-routes")

    assert migration.status_code == 503
    assert migration.json()["error"]["code"] == "actorops_v2_migration_required"

    from src.api import actorops_admin_routes

    monkeypatch.setattr(
        actorops_admin_routes.ActorOpsAdminService,
        "list_routes",
        lambda _self: (_ for _ in ()).throw(ActorOpsAdminUnavailable("store_down")),
    )
    unavailable = client.get("/api/admin/apify-routes")

    assert unavailable.status_code == 503
    assert unavailable.json()["error"]["code"] == "actorops_v2_unavailable"


def test_actorops_events_use_redacted_operation_log_actions_only(
    tmp_path: Path, monkeypatch
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    workspace_id = DEFAULT_WORKSPACE_ID
    user_id = str(
        client.app.state.service_store.connect().execute(
            "SELECT id FROM users WHERE username='owner'"
        ).fetchone()[0]
    )
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    stamp = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    entries = [
        {
            "schema_version": 1, "event_id": "evt_v2", "timestamp": stamp,
            "level": "info", "service": "api", "category": "source",
            "action": "actorops_v2_candidate_promote", "outcome": "succeeded",
            "workspace_id": workspace_id, "actor_user_id": user_id,
            "target_fingerprint": "do-not-expose",
        },
        {
            "schema_version": 1, "event_id": "evt_legacy", "timestamp": stamp,
            "level": "info", "service": "api", "category": "source",
            "action": "actor_canary_queue", "outcome": "queued",
            "workspace_id": workspace_id, "actor_user_id": user_id,
        },
    ]
    (log_dir / "operations-api.jsonl").write_text(
        "\n".join(json.dumps(item) for item in entries) + "\n", encoding="utf-8"
    )

    response = client.get(
        "/api/admin/apify-actor-events",
        params={"action": "actorops_v2_candidate_promote"},
    )

    assert response.status_code == 200, response.text
    payload = response.json()["data"]
    events = payload["events"]
    assert [event["event_id"] for event in events] == ["evt_v2"]
    assert payload["truncated"] is False
    assert "target_fingerprint" not in json.dumps(events)
