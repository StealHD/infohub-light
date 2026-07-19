import pytest
import sqlite3

from fastapi.testclient import TestClient

from src.api.server import create_app


def _client(
    tmp_path,
    monkeypatch,
    *,
    enabled: bool,
    subscription_writes_enabled: bool = False,
) -> TestClient:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv(
        "HORIZON_REMOTE_MCP_ENABLED", "true" if enabled else "false"
    )
    monkeypatch.setenv(
        "HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED",
        "true" if subscription_writes_enabled else "false",
    )
    if enabled:
        monkeypatch.setenv(
            "HORIZON_REMOTE_MCP_PUBLIC_URL", "http://127.0.0.1:8080/mcp"
        )
    else:
        monkeypatch.delenv("HORIZON_REMOTE_MCP_PUBLIC_URL", raising=False)
    static_dir = tmp_path / "static"
    static_dir.mkdir(parents=True)
    static_dir.joinpath("index.html").write_text("<!doctype html>", encoding="utf-8")
    return TestClient(create_app(data_dir=tmp_path / "data", static_dir=static_dir))


def _login(client: TestClient, username: str = "owner", password: str = "secret-password"):
    response = client.post(
        "/api/auth/login", json={"username": username, "password": password}
    )
    assert response.status_code == 200


def test_agent_delegation_api_lists_when_disabled_but_rejects_creation(
    tmp_path, monkeypatch
):
    client = _client(tmp_path, monkeypatch, enabled=False)
    _login(client)

    listing = client.get("/api/me/agent-delegations")
    created = client.post("/api/me/agent-delegations", json={"name": "My Mac"})

    assert listing.status_code == 200
    assert listing.json() == {
        "ok": True,
        "data": {
            "enabled": False,
            "mcp_url": "",
            "subscription_writes_enabled": False,
            "token_ttl_days": 90,
            "max_active": 5,
            "connections": [],
        },
    }
    assert created.status_code == 409
    assert created.json()["error"]["code"] == "remote_mcp_disabled"


def test_agent_delegation_api_returns_secret_once_and_supports_rename_and_revoke(
    tmp_path, monkeypatch
):
    client = _client(tmp_path, monkeypatch, enabled=True)
    _login(client)

    created = client.post(
        "/api/me/agent-delegations", json={"name": "My Mac"}
    )

    assert created.status_code == 201
    assert created.headers["cache-control"] == "no-store"
    payload = created.json()["data"]
    assert payload["token"].startswith("ih_mcp_v1_")
    assert payload["connection"]["name"] == "My Mac"
    assert payload["connection"]["access"] == "read"
    assert payload["connection"]["scopes"] == ["inteliscope:read"]
    connection_id = payload["connection"]["id"]

    listing = client.get("/api/me/agent-delegations").json()["data"]
    assert listing["enabled"] is True
    assert listing["mcp_url"] == "http://127.0.0.1:8080/mcp"
    assert listing["subscription_writes_enabled"] is False
    assert listing["connections"] == [payload["connection"]]
    assert "token" not in listing
    assert all("token" not in connection for connection in listing["connections"])

    renamed = client.patch(
        f"/api/me/agent-delegations/{connection_id}",
        json={"name": "Desktop"},
    )
    assert renamed.status_code == 200
    assert renamed.json()["data"]["name"] == "Desktop"

    revoked = client.delete(f"/api/me/agent-delegations/{connection_id}")
    repeated = client.delete(f"/api/me/agent-delegations/{connection_id}")
    assert revoked.json() == {"ok": True, "data": {"revoked": True}}
    assert repeated.json() == {"ok": True, "data": {"revoked": True}}
    assert client.get("/api/me/agent-delegations").json()["data"]["connections"][
        0
    ]["status"] == "revoked"


@pytest.mark.parametrize(
    "stored_scopes",
    [
        "[",
        sqlite3.Binary(b"\x80"),
        sqlite3.Binary(b'[\"inteliscope:read\"]'),
        '["inteliscope:read"]' + (" " * 513),
        "[" * 65 + '"inteliscope:read"' + "]" * 65,
        '{"scope":"inteliscope:read"}',
        '["unexpected"]',
        '["inteliscope:read","inteliscope:read"]',
    ],
)
def test_agent_delegation_api_lists_corrupt_scopes_as_empty_read_connections(
    tmp_path, monkeypatch, stored_scopes
):
    client = _client(tmp_path, monkeypatch, enabled=True)
    _login(client)
    created = client.post("/api/me/agent-delegations", json={"name": "Corrupt"})
    connection_id = created.json()["data"]["connection"]["id"]
    client.app.state.service_store.connect().execute(
        "UPDATE agent_delegations SET scopes_json = ? WHERE id = ?",
        (stored_scopes, connection_id),
    )
    client.app.state.service_store.connect().commit()

    response = client.get("/api/me/agent-delegations")

    assert response.status_code == 200
    connection = response.json()["data"]["connections"][0]
    assert connection["access"] == "read"
    assert connection["scopes"] == []


def test_agent_delegation_api_allows_viewer_and_isolates_connections_by_user(
    tmp_path, monkeypatch
):
    client = _client(tmp_path, monkeypatch, enabled=True)
    _login(client)
    store = client.app.state.service_store
    workspace = store.get_default_workspace()
    store.create_user(
        workspace_id=workspace["id"],
        username="viewer",
        password="viewer-password",
        role="viewer",
    )
    owner_connection = client.post(
        "/api/me/agent-delegations", json={"name": "Owner Mac"}
    ).json()["data"]["connection"]

    client.post("/api/auth/logout")
    _login(client, "viewer", "viewer-password")
    viewer_created = client.post(
        "/api/me/agent-delegations", json={"name": "Viewer Mac"}
    )
    assert viewer_created.status_code == 201
    viewer_listing = client.get("/api/me/agent-delegations").json()["data"]
    assert [item["name"] for item in viewer_listing["connections"]] == ["Viewer Mac"]

    assert client.patch(
        f"/api/me/agent-delegations/{owner_connection['id']}",
        json={"name": "Not Mine"},
    ).status_code == 404
    assert client.delete(
        f"/api/me/agent-delegations/{owner_connection['id']}"
    ).status_code == 404


def test_agent_delegation_api_enforces_five_active_connections(tmp_path, monkeypatch):
    client = _client(tmp_path, monkeypatch, enabled=True)
    _login(client)
    for index in range(5):
        response = client.post(
            "/api/me/agent-delegations", json={"name": f"Device {index}"}
        )
        assert response.status_code == 201

    limited = client.post(
        "/api/me/agent-delegations", json={"name": "One too many"}
    )
    assert limited.status_code == 409
    assert limited.json()["error"]["code"] == "agent_delegation_limit"


def test_write_delegation_requires_independent_feature_flag(tmp_path, monkeypatch):
    disabled_client = _client(tmp_path / "disabled", monkeypatch, enabled=True)
    _login(disabled_client)

    rejected = disabled_client.post(
        "/api/me/agent-delegations",
        json={"name": "Write Mac", "access": "subscriptions_write"},
    )

    assert rejected.status_code == 409
    assert rejected.json()["error"]["code"] == "subscription_writes_disabled"
    assert disabled_client.get("/api/me/agent-delegations").json()["data"][
        "connections"
    ] == []

    enabled_client = _client(
        tmp_path / "enabled",
        monkeypatch,
        enabled=True,
        subscription_writes_enabled=True,
    )
    _login(enabled_client)
    created = enabled_client.post(
        "/api/me/agent-delegations",
        json={"name": "Write Mac", "access": "subscriptions_write"},
    )

    assert created.status_code == 201
    connection = created.json()["data"]["connection"]
    assert connection["access"] == "subscriptions_write"
    assert connection["scopes"] == [
        "inteliscope:read",
        "inteliscope:subscriptions:write",
    ]
    assert enabled_client.get("/api/me/agent-delegations").json()["data"][
        "subscription_writes_enabled"
    ] is True


@pytest.mark.parametrize("subscription_writes_enabled", [False, True])
def test_viewer_write_delegation_is_stably_forbidden_but_read_remains_allowed(
    tmp_path, monkeypatch, subscription_writes_enabled
):
    client = _client(
        tmp_path,
        monkeypatch,
        enabled=True,
        subscription_writes_enabled=subscription_writes_enabled,
    )
    _login(client)
    store = client.app.state.service_store
    workspace = store.get_default_workspace()
    store.create_user(
        workspace_id=workspace["id"],
        username="viewer",
        password="viewer-password",
        role="viewer",
    )
    client.post("/api/auth/logout")
    _login(client, "viewer", "viewer-password")

    write_response = client.post(
        "/api/me/agent-delegations",
        json={"name": "Viewer Write", "access": "subscriptions_write"},
    )
    read_response = client.post(
        "/api/me/agent-delegations",
        json={"name": "Viewer Read"},
    )

    assert write_response.status_code == 403
    assert write_response.json()["error"]["code"] == "forbidden"
    assert read_response.status_code == 201
    assert read_response.json()["data"]["connection"]["access"] == "read"


def test_rename_payload_cannot_change_delegation_access(tmp_path, monkeypatch):
    client = _client(
        tmp_path,
        monkeypatch,
        enabled=True,
        subscription_writes_enabled=True,
    )
    _login(client)
    created = client.post(
        "/api/me/agent-delegations", json={"name": "Read connection"}
    ).json()["data"]["connection"]

    response = client.patch(
        f"/api/me/agent-delegations/{created['id']}",
        json={"name": "Escalated", "access": "subscriptions_write"},
    )

    assert response.status_code == 400
    assert response.json()["error"]["code"] == "invalid_request"
    unchanged = client.get("/api/me/agent-delegations").json()["data"][
        "connections"
    ][0]
    assert unchanged["name"] == "Read connection"
    assert unchanged["access"] == "read"
