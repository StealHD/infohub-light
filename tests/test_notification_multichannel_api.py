from __future__ import annotations

from fastapi.testclient import TestClient

from src.api.server import create_app


def _client(tmp_path, monkeypatch) -> TestClient:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv(
        "HORIZON_AUTH_SESSION_SECRET",
        "test-session-secret",
    )
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    static_dir.joinpath("index.html").write_text(
        "<!doctype html>",
        encoding="utf-8",
    )
    return TestClient(
        create_app(data_dir=tmp_path / "data", static_dir=static_dir)
    )


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


def test_personal_multichannel_patch_and_per_channel_test_wiring(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    service = client.app.state.preferred_source_notifications
    captured: list[dict[str, object]] = []
    test_channels: list[str | None] = []

    def fake_upsert(*, workspace_id, user_id, **updates):
        captured.append(
            {
                "workspace_id": workspace_id,
                "user_id": user_id,
                **updates,
            }
        )
        return {
            "schema_version": 3,
            "enabled": True,
            "channels": ["email", "webhook", "telegram"],
            "channel": "email",
            "channel_states": {
                "email": {"enabled": True},
                "webhook": {"enabled": True},
                "telegram": {"enabled": True},
            },
        }

    def fake_test(*, workspace_id, user_id, channel=None):
        del workspace_id, user_id
        test_channels.append(channel)
        return {"sent": True, "channel": channel or "email"}

    monkeypatch.setattr(service, "upsert_settings", fake_upsert)
    monkeypatch.setattr(service, "send_test", fake_test)
    secret_chat = "-1001234567890"
    updated = client.patch(
        "/api/me/notification-settings",
        json={
            "enabled": True,
            "channels": ["email", "webhook", "telegram"],
            "telegram_chat_id": secret_chat,
        },
    )

    assert updated.status_code == 200, updated.text
    assert updated.json()["data"]["schema_version"] == 3
    assert captured[-1]["channels"] == [
        "email",
        "webhook",
        "telegram",
    ]
    assert captured[-1]["telegram_chat_id"] == secret_chat
    assert secret_chat not in updated.text

    incompatible = client.patch(
        "/api/me/notification-settings",
        json={"channel": "email", "channels": ["email", "webhook"]},
    )
    assert incompatible.status_code == 400
    assert incompatible.json()["error"]["code"] == (
        "invalid_notification_settings"
    )

    no_body = client.post("/api/me/notification-settings/test")
    telegram = client.post(
        "/api/me/notification-settings/test",
        json={"channel": "telegram"},
    )
    assert no_body.status_code == 200
    assert telegram.status_code == 200
    assert test_channels == [None, "telegram"]


def test_telegram_transport_is_admin_only_and_write_only(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    for response in (
        client.get("/api/admin/notification-telegram-transport"),
        client.patch(
            "/api/admin/notification-telegram-transport",
            json={"enabled": False},
        ),
        client.delete("/api/admin/notification-telegram-transport"),
        client.post(
            "/api/admin/notification-telegram-transport/test",
            json={"chat_id": "@anonymous_must_not_send"},
        ),
    ):
        assert response.status_code == 401
        assert response.json()["error"]["code"] == "unauthorized"
    _login(client)
    transport = client.app.state.workspace_telegram_transport
    captured: list[dict[str, object]] = []
    test_chat_ids: list[str] = []

    monkeypatch.setattr(
        transport,
        "get_public_settings",
        lambda *, workspace_id: {
            "schema_version": 1,
            "configured": False,
            "token_configured": False,
            "enabled": False,
            "generation": 0,
            "ready": False,
            "workspace": bool(workspace_id),
        },
    )

    def fake_upsert(*, workspace_id, actor_user_id, **updates):
        captured.append(
            {
                "workspace_id": workspace_id,
                "actor_user_id": actor_user_id,
                **updates,
            }
        )
        return {
            "schema_version": 1,
            "configured": True,
            "token_configured": True,
            "enabled": False,
            "generation": 1,
            "ready": False,
        }

    monkeypatch.setattr(transport, "upsert", fake_upsert)
    monkeypatch.setattr(
        transport,
        "delete",
        lambda **_kwargs: True,
    )

    def fake_test(*, workspace_id, actor_user_id, chat_id):
        del workspace_id, actor_user_id
        test_chat_ids.append(chat_id)
        return {
            "sent": True,
            "generation": 1,
            "message_id": 9001,
            "verification": "telegram_ack",
        }

    monkeypatch.setattr(transport, "send_test", fake_test)

    initial = client.get("/api/admin/notification-telegram-transport")
    assert initial.status_code == 200
    bot_token = "123456789:ABCDEFGHIJKLMNOPQRSTUVWXYZabcdefghi"
    updated = client.patch(
        "/api/admin/notification-telegram-transport",
        json={"bot_token": bot_token},
    )
    assert updated.status_code == 200, updated.text
    assert captured[-1]["bot_token"] == bot_token
    assert bot_token not in updated.text
    assert "token_env_name" not in updated.text
    assert "token_secret_digest" not in updated.text

    chat_id = "@test_delivery_channel"
    tested = client.post(
        "/api/admin/notification-telegram-transport/test",
        json={"chat_id": chat_id},
    )
    assert tested.status_code == 200, tested.text
    assert tested.json()["data"] == {"sent": True, "generation": 1}
    assert test_chat_ids == [chat_id]
    assert chat_id not in tested.text
    assert "message_id" not in tested.text

    deleted = client.delete(
        "/api/admin/notification-telegram-transport"
    )
    assert deleted.status_code == 200
    assert deleted.json()["data"] == {"deleted": True}

    member = client.post(
        "/api/users",
        json={
            "username": "member",
            "password": "member-password",
            "role": "member",
        },
    )
    assert member.status_code == 200
    admin = client.post(
        "/api/users",
        json={
            "username": "notification-admin",
            "password": "admin-password",
            "role": "admin",
        },
    )
    assert admin.status_code == 200
    viewer = client.post(
        "/api/users",
        json={
            "username": "notification-viewer",
            "password": "viewer-password",
            "role": "viewer",
        },
    )
    assert viewer.status_code == 200
    client.post("/api/auth/logout")
    _login(client, "notification-admin", "admin-password")
    assert client.get(
        "/api/admin/notification-telegram-transport"
    ).status_code == 200

    for username, password in (
        ("member", "member-password"),
        ("notification-viewer", "viewer-password"),
    ):
        client.post("/api/auth/logout")
        _login(client, username, password)
        for response in (
            client.get("/api/admin/notification-telegram-transport"),
            client.patch(
                "/api/admin/notification-telegram-transport",
                json={"enabled": False},
            ),
            client.delete("/api/admin/notification-telegram-transport"),
            client.post(
                "/api/admin/notification-telegram-transport/test",
                json={"chat_id": "@read_only_must_not_send"},
            ),
        ):
            assert response.status_code == 403
            assert response.json()["error"]["code"] == "forbidden"


def test_apify_multichannel_wiring_and_incident_schema_v2(
    tmp_path,
    monkeypatch,
) -> None:
    client = _client(tmp_path, monkeypatch)
    _login(client)
    service = client.app.state.apify_actor_alerts
    captured: list[dict[str, object]] = []
    tested_channels: list[str | None] = []

    def fake_upsert(*, workspace_id, actor_user_id, **updates):
        captured.append(
            {
                "workspace_id": workspace_id,
                "actor_user_id": actor_user_id,
                **updates,
            }
        )
        return {
            "schema_version": 3,
            "enabled": True,
            "channels": ["webhook", "telegram"],
            "channel": "webhook",
            "channel_states": {
                "email": {"enabled": False},
                "webhook": {"enabled": True},
                "telegram": {"enabled": True},
            },
        }

    def fake_test(*, workspace_id, actor_user_id, channel=None):
        del workspace_id, actor_user_id
        tested_channels.append(channel)
        return {"sent": True, "channel": channel or "webhook"}

    monkeypatch.setattr(service, "upsert_settings", fake_upsert)
    monkeypatch.setattr(service, "send_test", fake_test)
    monkeypatch.setattr(
        service,
        "list_incidents",
        lambda **_kwargs: [
            {
                "id": "incident-safe",
                "deliveries": [
                    {"channel": "webhook", "status": "succeeded"},
                    {"channel": "telegram", "status": "failed"},
                ],
                "delivery_status": "partial",
            }
        ],
    )

    chat_id = "@alert_destination"
    updated = client.patch(
        "/api/admin/apify-actor-alert-settings",
        json={
            "channels": ["webhook", "telegram"],
            "telegram_chat_id": chat_id,
        },
    )
    assert updated.status_code == 200, updated.text
    assert captured[-1]["channels"] == ["webhook", "telegram"]
    assert captured[-1]["telegram_chat_id"] == chat_id
    assert chat_id not in updated.text

    incompatible = client.patch(
        "/api/admin/apify-actor-alert-settings",
        json={"channel": "email", "channels": ["email"]},
    )
    assert incompatible.status_code == 400
    assert incompatible.json()["error"]["code"] == (
        "invalid_apify_actor_alert_settings"
    )

    tested = client.post(
        "/api/admin/apify-actor-alert-settings/test",
        json={"channel": "telegram"},
    )
    assert tested.status_code == 200
    assert tested_channels == ["telegram"]

    incidents = client.get("/api/admin/apify-actor-alert-incidents")
    assert incidents.status_code == 200
    data = incidents.json()["data"]
    assert data["schema_version"] == 2
    assert data["incidents"][0]["deliveries"] == [
        {"channel": "webhook", "status": "succeeded"},
        {"channel": "telegram", "status": "failed"},
    ]
