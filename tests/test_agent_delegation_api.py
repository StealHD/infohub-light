from fastapi.testclient import TestClient

from src.api.server import create_app


def _client(tmp_path, monkeypatch, *, enabled: bool) -> TestClient:
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv(
        "HORIZON_REMOTE_MCP_ENABLED", "true" if enabled else "false"
    )
    if enabled:
        monkeypatch.setenv(
            "HORIZON_REMOTE_MCP_PUBLIC_URL", "http://127.0.0.1:8080/mcp"
        )
    else:
        monkeypatch.delenv("HORIZON_REMOTE_MCP_PUBLIC_URL", raising=False)
    static_dir = tmp_path / "static"
    static_dir.mkdir()
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
    connection_id = payload["connection"]["id"]

    listing = client.get("/api/me/agent-delegations").json()["data"]
    assert listing["enabled"] is True
    assert listing["mcp_url"] == "http://127.0.0.1:8080/mcp"
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
