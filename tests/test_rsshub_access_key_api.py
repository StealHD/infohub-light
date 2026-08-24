from __future__ import annotations

import json

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.rsshub import RSSHUB_ACCESS_KEY_ENV


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.delenv(RSSHUB_ACCESS_KEY_ENV, raising=False)
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    tmp_path.mkdir(parents=True, exist_ok=True)
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    data_dir.mkdir()
    static_dir.mkdir()
    (data_dir / "config.json").write_text(json.dumps({
        "version": "1.0",
        "ai": {"enabled": False, "provider": "gemini", "model": "gemini-2.5-flash", "api_key_env": "GOOGLE_API_KEY"},
        "tags": [], "personal_tags": [], "sources": {"rss": [], "github": [], "hackernews": {"enabled": False}},
        "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
    }), encoding="utf-8")
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return TestClient(create_app(data_dir=data_dir, static_dir=static_dir))


def _login(client: TestClient, username: str = "owner", password: str = "secret-password") -> None:
    response = client.post("/api/auth/login", json={"username": username, "password": password})
    assert response.status_code == 200, response.text


def _configured_status(client: TestClient) -> bool:
    statuses = client.get("/api/config").json()["data"]["env_status"]
    return next(item for item in statuses if item["name"] == RSSHUB_ACCESS_KEY_ENV)["set"]


def test_rsshub_access_key_is_write_only_and_updates_runtime_status(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)

    missing = client.get("/api/admin/rsshub-access-key")
    assert missing.status_code == 200
    assert missing.json()["data"] == {"configured": False, "management_source": "none"}

    configured = client.put("/api/admin/rsshub-access-key", json={"value": "private-rsshub-key"})
    assert configured.status_code == 200
    assert configured.json()["data"] == {"configured": True, "management_source": "secret_store"}
    assert "private-rsshub-key" not in configured.text
    assert _configured_status(client) is True

    rotated = client.put("/api/admin/rsshub-access-key", json={"value": "rotated-rsshub-key"})
    assert rotated.status_code == 200
    assert "rotated-rsshub-key" not in rotated.text

    deleted = client.delete("/api/admin/rsshub-access-key")
    assert deleted.status_code == 200
    assert deleted.json()["data"] == {"configured": False, "management_source": "none"}
    assert _configured_status(client) is False
    assert client.delete("/api/admin/rsshub-access-key").status_code == 200


@pytest.mark.parametrize("value", ["", "bad\nvalue", "x" * 4097])
def test_rsshub_access_key_rejects_invalid_values_without_overwriting(tmp_path, monkeypatch, value: str) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    assert client.put("/api/admin/rsshub-access-key", json={"value": "known-good"}).status_code == 200

    rejected = client.put("/api/admin/rsshub-access-key", json={"value": value})
    assert rejected.status_code == 400
    if value:
        assert value not in rejected.text
    assert client.get("/api/admin/rsshub-access-key").json()["data"] == {"configured": True, "management_source": "secret_store"}


def test_rsshub_access_key_respects_admin_roles_and_environment_management(tmp_path, monkeypatch) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    for username, role in (("admin", "admin"), ("member", "member"), ("viewer", "viewer")):
        response = client.post("/api/users", json={"username": username, "password": f"{username}-password", "role": role})
        assert response.status_code == 200

    client.post("/api/auth/logout")
    _login(client, "admin", "admin-password")
    assert client.put("/api/admin/rsshub-access-key", json={"value": "admin-key"}).status_code == 200

    for username in ("member", "viewer"):
        client.post("/api/auth/logout")
        _login(client, username, f"{username}-password")
        for method in ("GET", "PUT", "DELETE"):
            response = client.request(method, "/api/admin/rsshub-access-key", json={"value": "blocked-key"} if method == "PUT" else None)
            assert response.status_code == 403
            assert "blocked-key" not in response.text

    environment_client = _client(tmp_path / "environment", monkeypatch)
    monkeypatch.setenv(RSSHUB_ACCESS_KEY_ENV, "deployment-key")
    _login(environment_client)
    status = environment_client.get("/api/admin/rsshub-access-key")
    assert status.json()["data"] == {"configured": True, "management_source": "environment"}
    for method in ("PUT", "DELETE"):
        response = environment_client.request(method, "/api/admin/rsshub-access-key", json={"value": "blocked-key"} if method == "PUT" else None)
        assert response.status_code == 409
        assert "deployment-key" not in response.text
