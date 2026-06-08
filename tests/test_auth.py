import json
import threading
from functools import partial
from http.server import ThreadingHTTPServer
from pathlib import Path
from urllib.error import HTTPError
from urllib.request import Request, urlopen

from src.ui.auth import (
    AuthSettings,
    create_session_token,
    hash_password,
    verify_password_hash,
    verify_session_token,
)
from src.ui.server import RadarWebHandler


def _minimal_config():
    return {
        "version": "1.0",
        "ai": {
            "provider": "openai",
            "model": "gpt-4o-mini",
            "api_key_env": "OPENAI_API_KEY",
        },
        "sources": {"rss": [], "hackernews": {"enabled": True}},
        "filtering": {"ai_score_threshold": 7.5, "time_window_hours": 24},
    }


def _request_json(url, *, payload=None, headers=None):
    body = None
    request_headers = dict(headers or {})
    if payload is not None:
        body = json.dumps(payload).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = Request(url, data=body, headers=request_headers)
    with urlopen(request, timeout=5) as response:
        return response.status, response.headers, json.loads(response.read().decode("utf-8"))


def _start_server(data_dir: Path, static_dir: Path):
    handler = partial(RadarWebHandler, data_dir=data_dir, static_dir=static_dir)
    server = ThreadingHTTPServer(("127.0.0.1", 0), handler)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    return server, f"http://127.0.0.1:{server.server_address[1]}"


def test_auth_password_hash_verification():
    stored_hash = hash_password("correct horse battery staple")

    assert verify_password_hash("correct horse battery staple", stored_hash)
    assert not verify_password_hash("wrong", stored_hash)
    assert not verify_password_hash("correct horse battery staple", "not-a-valid-hash")


def test_auth_session_token_round_trip_and_expiry():
    settings = AuthSettings(
        enabled=True,
        username="admin",
        password="secret",
        password_hash=None,
        session_secret="session-secret",
        cookie_secure=False,
        session_ttl_seconds=60,
    )

    token = create_session_token(settings, "admin", now=1000)

    assert verify_session_token(settings, token, now=1020) == "admin"
    assert verify_session_token(settings, token, now=1100) is None
    assert verify_session_token(settings, token + "tampered", now=1020) is None


def test_web_config_api_requires_auth_when_enabled(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_ENABLED", "true")
    monkeypatch.setenv("HORIZON_AUTH_USER", "admin")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")

    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    (data_dir / "site").mkdir(parents=True)
    static_dir.mkdir()
    (data_dir / "config.json").write_text(
        json.dumps(_minimal_config()),
        encoding="utf-8",
    )
    (data_dir / "site" / "radar-data.json").write_text(
        json.dumps({"items": []}),
        encoding="utf-8",
    )
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")

    server, base_url = _start_server(data_dir, static_dir)
    try:
        try:
            _request_json(base_url + "/api/config")
        except HTTPError as exc:
            assert exc.code == 401
            assert "需要登录" in exc.read().decode("utf-8")
        else:
            raise AssertionError("/api/config should require auth")

        status, _, payload = _request_json(base_url + "/radar-data.json")
        assert status == 200
        assert payload == {"items": []}

        status, headers, payload = _request_json(
            base_url + "/api/auth/login",
            payload={"username": "admin", "password": "secret"},
        )
        assert status == 200
        assert payload["auth"]["authenticated"] is True
        cookie = headers["Set-Cookie"]
        assert "horizon_session=" in cookie
        assert "secret" not in cookie

        status, _, payload = _request_json(
            base_url + "/api/config",
            headers={"Cookie": cookie},
        )
        assert status == 200
        assert payload["config"]["version"] == "1.0"
    finally:
        server.shutdown()
        server.server_close()
