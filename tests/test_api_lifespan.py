from __future__ import annotations

import sqlite3

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app


def test_api_lifespan_closes_service_store(tmp_path, monkeypatch) -> None:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    app = create_app(data_dir=data_dir, static_dir=static_dir)
    connection = app.state.service_store.connect()

    with TestClient(app) as client:
        assert client.get("/api/health/live").status_code == 200

    with pytest.raises(sqlite3.ProgrammingError, match="closed database"):
        connection.execute("SELECT 1")
