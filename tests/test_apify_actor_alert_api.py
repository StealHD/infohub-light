from __future__ import annotations

import json

from fastapi.testclient import TestClient

from src.api.server import create_app
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


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
    (static_dir / "index.html").write_text(
        "<!doctype html>",
        encoding="utf-8",
    )
    app = create_app(data_dir=data_dir, static_dir=static_dir)
    store = ServiceStore(data_dir)
    store.initialize()
    return TestClient(app), store


def _login(
    client: TestClient,
    username: str = "owner",
    password: str = "secret-password",
) -> None:
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200


def test_apify_actor_alert_settings_are_admin_only_and_write_only(
    tmp_path,
    monkeypatch,
):
    client, store = _client(tmp_path, monkeypatch)
    unauthenticated = client.get("/api/admin/apify-actor-alert-settings")
    assert unauthenticated.status_code == 401

    _login(client)
    initial = client.get("/api/admin/apify-actor-alert-settings")
    assert initial.status_code == 200
    assert initial.headers["cache-control"] == "no-store"
    initial_data = initial.json()["data"]
    assert initial_data["enabled"] is False
    assert initial_data["events"] == [
        "actor_switched",
        "route_exhausted",
        "quota_low",
        "budget_blocked",
        "start_outcome_unknown",
        "recovered",
    ]

    webhook = "https://hooks.example.com/apify?token=write-only-secret"
    updated = client.patch(
        "/api/admin/apify-actor-alert-settings",
        json={
            "enabled": True,
            "channel": "webhook",
            "events": ["actor_switched", "recovered"],
            "webhook_url": webhook,
        },
    )
    assert updated.status_code == 200, updated.text
    assert updated.headers["cache-control"] == "no-store"
    assert updated.json()["data"]["webhook_configured"] is True
    assert updated.json()["data"]["events"] == [
        "actor_switched",
        "recovered",
    ]
    assert webhook not in updated.text
    assert "write-only-secret" not in updated.text
    assert webhook.encode() not in store.db_path.read_bytes()

    invalid = client.patch(
        "/api/admin/apify-actor-alert-settings",
        json={"enabled": True, "unexpected": "field"},
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_request"

    created_member = client.post(
        "/api/users",
        json={
            "username": "member",
            "password": "member-password",
            "role": "member",
        },
    )
    assert created_member.status_code == 200
    client.post("/api/auth/logout")
    _login(client, "member", "member-password")
    denied = client.get("/api/admin/apify-actor-alert-settings")
    assert denied.status_code == 403
    assert denied.json()["error"]["code"] == "forbidden"


def test_apify_actor_alert_incidents_project_only_safe_fields(
    tmp_path,
    monkeypatch,
):
    client, _store = _client(tmp_path, monkeypatch)
    _login(client)
    service = client.app.state.apify_actor_alerts
    service.open_incident(
        workspace_id=DEFAULT_WORKSPACE_ID,
        route_key="x/profile",
        incident_key="actor_unhealthy:scrape_badger",
        event_type="actor_switched",
        severity="warning",
        payload={
            "actor_name": "ScrapeBadger",
            "active_actor_name": "Dami",
            "reason_code": "placeholder_records",
            "raw_error": "must-not-escape",
            "target": "@private-target",
            "run_id": "remote-run-secret",
        },
    )

    response = client.get("/api/admin/apify-actor-alert-incidents?limit=20")
    assert response.status_code == 200
    assert response.headers["cache-control"] == "no-store"
    incidents = response.json()["data"]["incidents"]
    assert len(incidents) == 1
    assert incidents[0]["actor_name"] == "ScrapeBadger"
    assert incidents[0]["active_actor_name"] == "Dami"
    assert incidents[0]["reason_code"] == "placeholder_records"
    for forbidden in (
        "must-not-escape",
        "@private-target",
        "remote-run-secret",
        "raw_error",
        "run_id",
    ):
        assert forbidden not in response.text


def test_apify_actor_alert_test_endpoint_has_no_apify_side_effect(
    tmp_path,
    monkeypatch,
):
    client, store = _client(tmp_path, monkeypatch)
    _login(client)
    called: list[tuple[str, str]] = []
    monkeypatch.setattr(
        client.app.state.apify_actor_alerts,
        "send_test",
        lambda *, workspace_id, actor_user_id: (
            called.append((workspace_id, actor_user_id))
            or {"sent": True, "channel": "webhook"}
        ),
    )
    before_runs = store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0]

    response = client.post("/api/admin/apify-actor-alert-settings/test")

    assert response.status_code == 200
    assert response.json()["data"] == {
        "sent": True,
        "channel": "webhook",
    }
    assert len(called) == 1
    after_runs = store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_runs"
    ).fetchone()[0]
    assert after_runs == before_runs
