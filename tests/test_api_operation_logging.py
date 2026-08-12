import json
import logging

from fastapi.testclient import TestClient

from src.api.server import create_app
from src.logging_utils import configure_logging
from src.services.operation_log import safe_emit_operation_event
from src.storage.service_store import ServiceStore


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
        verification_store = ServiceStore(store.data_dir)
        assert verification_store.get_user(owner["id"])["display_name"] == original_display_name
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


def test_readiness_reports_logging_degradation_without_hiding_api_health(
    tmp_path,
    monkeypatch,
):
    app, _log_dir = _app(tmp_path, monkeypatch)
    operation_handler = next(
        handler
        for handler in logging.getLogger("inteliscope.operations").handlers
        if getattr(handler, "channel", None) == "operations"
    )

    class FailingStream:
        def write(self, _value):
            raise OSError("simulated disk failure")

        def flush(self):
            return None

        def close(self):
            return None

    try:
        with TestClient(app) as client:
            ready = client.get("/api/health/ready")
            assert ready.status_code == 200
            assert ready.json()["data"]["logging_status"] == "ready"

            operation_handler.stream.close()
            operation_handler.stream = FailingStream()
            assert (
                safe_emit_operation_event(
                    category="job",
                    action="claim",
                    outcome="running",
                    workspace_id="workspace_1",
                    subject_user_id="user_1",
                    job_id="job_1",
                )
                is False
            )
            degraded = client.get("/api/health/ready")

        assert degraded.status_code == 200
        assert degraded.json()["data"]["status"] == "ready"
        assert degraded.json()["data"]["logging_status"] == "degraded"
    finally:
        _close_managed_handlers()


def test_telegram_transport_write_logs_only_safe_changed_fields(
    tmp_path,
    monkeypatch,
):
    app, log_dir = _app(tmp_path, monkeypatch)
    token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
    try:
        with TestClient(app) as client:
            login = client.post(
                "/api/auth/login",
                json={
                    "username": "owner",
                    "password": "secret-password",
                },
            )
            assert login.status_code == 200
            monkeypatch.setattr(
                app.state.workspace_telegram_transport,
                "upsert",
                lambda **_kwargs: {
                    "schema_version": 1,
                    "configured": True,
                    "token_configured": True,
                    "enabled": False,
                    "generation": 1,
                    "ready": False,
                },
            )
            changed = client.patch(
                "/api/admin/notification-telegram-transport",
                json={"bot_token": token},
            )

        assert changed.status_code == 200
        events = [
            event
            for event in _events(log_dir)
            if event["action"] == "telegram_transport_update"
        ]
        assert len(events) == 1
        assert events[0]["outcome"] == "succeeded"
        assert events[0]["changed_fields"] == ["bot_token"]
        combined = "\n".join(
            path.read_text(encoding="utf-8")
            for path in (
                log_dir / "runtime-api.jsonl",
                log_dir / "operations-api.jsonl",
            )
        )
        assert token not in combined
    finally:
        _close_managed_handlers()


def test_unhandled_read_error_returns_request_id_and_safe_operation_event(
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
            failed = client.get(
                "/api/me/notification-settings?private=query"
            )

        assert failed.status_code == 500
        assert failed.headers["X-Request-ID"].startswith("req_")
        assert failed.json()["error"]["code"] == "internal_error"
        events = _events(log_dir)
        assert [event["action"] for event in events] == [
            "login",
            "unhandled_error",
        ]
        failure = events[-1]
        assert failure["category"] == "request"
        assert failure["request_id"] == failed.headers["X-Request-ID"]
        assert failure["route"] == "/api/me/notification-settings"
        assert failure["method"] == "GET"
        assert failure["stage"] == "request"
        assert failure["error_code"] == "internal_error"
        assert failure["error_fingerprint"].startswith("err_")
        runtime = log_dir.joinpath("runtime-api.jsonl").read_text(
            encoding="utf-8"
        )
        assert "api_request_failed" in runtime
        assert "/api/me/notification-settings" in runtime
        assert "?private=query" not in runtime
        assert "safe-read-failure" not in runtime
    finally:
        _close_managed_handlers()
