"""Shared FastAPI fixture helpers for focused API test modules."""

import json

from fastapi.testclient import TestClient

from src.api.server import create_app
from src.storage.service_store import ServiceStore


def client(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    (data_dir / "site").mkdir(parents=True)
    static_dir.mkdir(parents=True)
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    return TestClient(create_app(data_dir=data_dir, static_dir=static_dir)), data_dir


def login(client):
    response = client.post(
        "/api/auth/login",
        json={"username": "owner", "password": "secret-password"},
    )
    assert response.status_code == 200
    assert response.json()["ok"] is True
    return response


def login_as(client, username, password):
    response = client.post(
        "/api/auth/login",
        json={"username": username, "password": password},
    )
    assert response.status_code == 200
    return response


def seed_manual_refresh_subscription(data_dir, *, username="owner", scope="private"):
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    user = store.get_user_by_username(username)
    assert workspace is not None and user is not None
    source_id = store.create_source(
        workspace_id=workspace["id"],
        scope=scope,
        owner_user_id=user["id"] if scope == "private" else None,
        source_type="rss",
        display_name=f"{username} Manual Refresh",
        config={"url": f"https://example.com/{username}-{scope}-manual.xml"},
    )
    subscription = store.create_subscription(user_id=user["id"], source_id=source_id)
    store.close()
    return source_id, subscription["id"]
