import json
import logging

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.logging_utils import configure_logging


def _flush_managed_handlers() -> None:
    for logger in (
        logging.getLogger(),
        logging.getLogger("inteliscope.operations"),
    ):
        for handler in logger.handlers:
            if getattr(handler, "_inteliscope_managed_handler", False):
                handler.flush()


def _close_managed_handlers() -> None:
    for logger in (
        logging.getLogger(),
        logging.getLogger("inteliscope.operations"),
    ):
        for handler in tuple(logger.handlers):
            if getattr(handler, "_inteliscope_managed_handler", False):
                logger.removeHandler(handler)
                handler.close()


def _app(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    static_dir.joinpath("index.html").write_text(
        "<!doctype html>", encoding="utf-8"
    )
    log_dir = tmp_path / "logs"
    configure_logging(log_dir, service="api")
    app = create_app(
        data_dir=tmp_path / "data",
        static_dir=static_dir,
        log_dir=log_dir,
    )
    return app, log_dir


def _events(log_dir):
    _flush_managed_handlers()
    return [
        json.loads(line)
        for line in log_dir.joinpath("operations-api.jsonl")
        .read_text(encoding="utf-8")
        .splitlines()
    ]


def test_api_generates_request_ids_and_logs_login_without_request_values(
    tmp_path,
    monkeypatch,
):
    app, log_dir = _app(tmp_path, monkeypatch)
    try:
        with TestClient(app) as client:
            denied = client.post(
                "/api/auth/login?token=query-secret",
                headers={"X-Request-ID": "attacker-controlled"},
                json={"username": "private-name", "password": "wrong-password"},
            )
            accepted = client.post(
                "/api/auth/login",
                headers={"X-Request-ID": "attacker-controlled"},
                json={"username": "owner", "password": "secret-password"},
            )

        assert denied.status_code == 401
        assert accepted.status_code == 200
        assert denied.headers["X-Request-ID"].startswith("req_")
        assert accepted.headers["X-Request-ID"].startswith("req_")
        assert accepted.headers["X-Request-ID"] != "attacker-controlled"

        login_events = [
            event for event in _events(log_dir) if event["action"] == "login"
        ]
        assert [event["outcome"] for event in login_events] == [
            "denied",
            "succeeded",
        ]
        assert login_events[0]["error_code"] == "invalid_credentials"
        assert login_events[0]["request_id"] == denied.headers["X-Request-ID"]
        assert login_events[1]["request_id"] == accepted.headers["X-Request-ID"]
        assert all(event["route"] == "/api/auth/login" for event in login_events)
        assert all(event["method"] == "POST" for event in login_events)

        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                log_dir / "runtime-api.jsonl",
                log_dir / "operations-api.jsonl",
            )
        )
        for forbidden in (
            "query-secret",
            "attacker-controlled",
            "private-name",
            "wrong-password",
            "secret-password",
        ):
            assert forbidden not in combined
    finally:
        _close_managed_handlers()


def test_api_transaction_leak_rolls_back_and_never_logs_success(
    tmp_path,
    monkeypatch,
):
    app, log_dir = _app(tmp_path, monkeypatch)
    store = app.state.service_store
    owner = store.get_user_by_username("owner")
    original_display_name = owner["display_name"]

    def leak_transaction(user_id, **_updates):
        conn = store.connect()
        conn.execute("BEGIN IMMEDIATE")
        conn.execute(
            "UPDATE users SET display_name = ? WHERE id = ?",
            ("must-rollback", user_id),
        )

    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={"username": "owner", "password": "secret-password"},
            )
            assert login.status_code == 200
            monkeypatch.setattr(store, "update_user", leak_transaction)
            changed = client.post(
                "/api/me/password",
                json={
                    "current_password": "secret-password",
                    "new_password": "replacement-password",
                },
            )

        assert changed.status_code == 500
        assert changed.json()["error"]["code"] == "database_transaction_leak"
        assert (
            store.get_user(owner["id"])["display_name"]
            == original_display_name
        )
        password_events = [
            event
            for event in _events(log_dir)
            if event["action"] == "password_change"
        ]
        assert len(password_events) == 1
        assert password_events[0]["outcome"] == "failed"
        assert (
            password_events[0]["error_code"]
            == "database_transaction_leak"
        )
        assert "succeeded" not in {
            event["outcome"] for event in password_events
        }
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                log_dir / "runtime-api.jsonl",
                log_dir / "operations-api.jsonl",
            )
        )
        assert "secret-password" not in combined
        assert "replacement-password" not in combined
    finally:
        _close_managed_handlers()


def test_unhandled_read_error_only_writes_runtime_diagnostics(
    tmp_path,
    monkeypatch,
):
    app, log_dir = _app(tmp_path, monkeypatch)

    def fail_read(*_args, **_kwargs):
        raise RuntimeError("safe-read-failure")

    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={"username": "owner", "password": "secret-password"},
            )
            assert login.status_code == 200
            monkeypatch.setattr(
                "src.services.preferred_source_notifications."
                "PreferredSourceNotificationService.get_public_settings",
                fail_read,
            )
            with pytest.raises(RuntimeError, match="safe-read-failure"):
                client.get("/api/me/notification-settings?private=query")

        assert [event["action"] for event in _events(log_dir)] == ["login"]
        runtime = log_dir.joinpath("runtime-api.jsonl").read_text(
            encoding="utf-8"
        )
        assert "api_request_failed" in runtime
        assert "/api/me/notification-settings" in runtime
        assert "?private=query" not in runtime
    finally:
        _close_managed_handlers()
