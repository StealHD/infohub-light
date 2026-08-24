from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.server import create_app


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    static = tmp_path / "static"
    static.mkdir()
    static.joinpath("index.html").write_text("<!doctype html>", encoding="utf-8")
    client = TestClient(create_app(data_dir=tmp_path / "data", static_dir=static))
    assert client.post(
        "/api/auth/login",
        json={"username": "owner", "password": "secret-password"},
    ).status_code == 200
    return client


def test_admin_lists_previews_and_applies_system_setting_alias(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)

    listed = client.get("/api/admin/system-settings")
    assert listed.status_code == 200
    data = listed.json()["data"]
    assert data["generation"] == 1
    assert len(data["settings"]) == 21
    assert all("env_name" in item and "value" in item for item in data["settings"])

    prepared = client.post(
        "/api/admin/system-settings/proposals",
        json={
            "expected_generation": 1,
            "changes": [{
                "key": "INFOHUB_MAX_WORKSPACE_FETCH_ATTEMPTS_PER_DAY",
                "value": 500,
            }],
        },
    )
    assert prepared.status_code == 200
    proposal = prepared.json()["data"]
    assert proposal["changes"][0]["key"] == (
        "limits.max_workspace_fetch_attempts_per_day"
    )
    assert proposal["warnings"]

    mismatch = client.post(
        f"/api/admin/system-settings/proposals/{proposal['proposal_id']}/apply",
        json={"confirmation": "wrong"},
    )
    assert mismatch.status_code == 409
    assert mismatch.json()["error"]["code"] == "system_settings_confirmation_mismatch"

    applied = client.post(
        f"/api/admin/system-settings/proposals/{proposal['proposal_id']}/apply",
        json={"confirmation": proposal["confirmation"]},
    )
    assert applied.status_code == 200
    assert applied.json()["data"]["generation"] == 2
    updated = client.get("/api/admin/system-settings").json()["data"]
    setting = next(
        item for item in updated["settings"]
        if item["key"] == "limits.max_workspace_fetch_attempts_per_day"
    )
    assert setting["value"] == 500
    assert setting["source"] == "override"


def test_system_settings_routes_are_admin_only_and_strict(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    store = client.app.state.service_store
    workspace = store.get_default_workspace()
    store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
        role="member",
    )
    client.post("/api/auth/logout")
    assert client.post(
        "/api/auth/login",
        json={"username": "member", "password": "member-password"},
    ).status_code == 200
    assert client.get("/api/admin/system-settings").status_code == 403

    client.post("/api/auth/logout")
    client.post(
        "/api/auth/login",
        json={"username": "owner", "password": "secret-password"},
    )
    invalid = client.post(
        "/api/admin/system-settings/proposals",
        json={
            "expected_generation": 1,
            "changes": [{"key": "DATABASE_URL", "value": 1}],
            "unexpected": True,
        },
    )
    assert invalid.status_code == 400
    assert invalid.json()["error"]["code"] == "invalid_request"
