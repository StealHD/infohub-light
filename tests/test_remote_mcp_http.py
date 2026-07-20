import httpx
import pytest
import sqlite3
from fastapi.testclient import TestClient
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from src.api.server import create_app
from src.mcp.remote_server import AgentDelegationTokenVerifier, DelegationRateLimiter
from src.services.job_queue import JobQueue
from src.services.user_feed_store import UserFeedStore


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _app(tmp_path, monkeypatch, *, enabled: bool = True):
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
    static_dir.mkdir(parents=True)
    static_dir.joinpath("assets").mkdir()
    static_dir.joinpath("index.html").write_text("<!doctype html>", encoding="utf-8")
    return create_app(data_dir=tmp_path / "data", static_dir=static_dir)


def _token(app):
    store = app.state.service_store
    user = store.get_user_by_username("owner")
    connection, token = store.create_agent_delegation(
        workspace_id=user["workspace_id"], user_id=user["id"], name="Test OpenClaw"
    )
    return user, connection, token


def _seed_feed(app, user):
    UserFeedStore(app.state.service_store).save_snapshot(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        job_id=None,
        payload={
            "schema_version": 2,
            "generated_at": "2026-07-16T00:00:00+00:00",
            "items": [
                {
                    "id": "article-1",
                    "title": "Remote MCP",
                    "source": "Example",
                    "source_type": "rss",
                    "url": "https://example.com/article-1",
                    "published_at": "2026-07-16T00:00:00+00:00",
                    "excerpt": "Read-only feed item",
                }
            ],
        },
    )
    return JobQueue(app.state.service_store).create_job(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        job_type="source_test",
    )


def _business_dump(app):
    return "\n".join(
        statement
        for statement in app.state.service_store.connect().iterdump()
        if "agent_delegations" not in statement
    )


def _initialize_payload():
    return {
        "jsonrpc": "2.0",
        "id": 1,
        "method": "initialize",
        "params": {
            "protocolVersion": "2025-11-25",
            "capabilities": {},
            "clientInfo": {"name": "pytest", "version": "1"},
        },
    }


def test_delegation_rate_limiter_refills_at_sixty_calls_per_minute():
    now = [100.0]
    limiter = DelegationRateLimiter(clock=lambda: now[0])

    assert [limiter.allow("delegation-1") for _ in range(10)] == [True] * 10
    assert limiter.allow("delegation-1") is False

    now[0] += 0.99
    assert limiter.allow("delegation-1") is False
    now[0] += 0.01
    assert limiter.allow("delegation-1") is True
    assert limiter.allow("delegation-1") is False

    now[0] += 10.0
    assert [limiter.allow("delegation-1") for _ in range(10)] == [True] * 10
    assert limiter.allow("delegation-1") is False


def test_disabled_remote_mcp_never_falls_through_to_spa(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, enabled=False)

    response = TestClient(app, follow_redirects=False).post(
        "/mcp", json=_initialize_payload()
    )

    assert response.status_code == 404
    assert response.headers["content-type"].startswith("application/json")
    assert "<!doctype html>" not in response.text


@pytest.mark.anyio
async def test_remote_mcp_uses_exact_path_static_bearer_and_transport_security(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch)
    _user, _connection, token = _token(app)
    transport = httpx.ASGITransport(app=app)
    headers = {"Accept": "application/json, text/event-stream"}

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8080",
            follow_redirects=False,
        ) as client:
            exact = await client.post("/mcp", json=_initialize_payload(), headers=headers)
            invalid = await client.post(
                "/mcp",
                json=_initialize_payload(),
                headers={**headers, "Authorization": "Bearer invalid"},
            )
            wrong_host = await client.post(
                "/mcp",
                json=_initialize_payload(),
                headers={
                    **headers,
                    "Authorization": f"Bearer {token}",
                    "Host": "evil.example",
                },
            )
            wrong_origin = await client.post(
                "/mcp",
                json=_initialize_payload(),
                headers={
                    **headers,
                    "Authorization": f"Bearer {token}",
                    "Origin": "https://evil.example",
                },
            )
            valid = await client.post(
                "/mcp",
                json=_initialize_payload(),
                headers={**headers, "Authorization": f"Bearer {token}"},
            )
            too_large = await client.post(
                "/mcp",
                content=b"x" * (256 * 1024 + 1),
                headers={**headers, "Authorization": f"Bearer {token}"},
            )
            trailing_slash = await client.get("/mcp/")
            nested_path = await client.get("/mcp/not-a-route")

    assert exact.status_code == 401
    assert exact.headers.get("location") is None
    assert invalid.status_code == 401
    assert wrong_host.status_code == 421
    assert wrong_origin.status_code == 403
    assert valid.status_code == 200
    assert too_large.status_code == 413
    assert trailing_slash.status_code == 404
    assert trailing_slash.headers.get("location") is None
    assert trailing_slash.headers["content-type"].startswith("application/json")
    assert nested_path.status_code == 404
    assert nested_path.headers["content-type"].startswith("application/json")


@pytest.mark.anyio
async def test_real_mcp_client_lists_fourteen_tools_with_exact_annotations_and_calls_reads(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch)
    user, _connection, token = _token(app)
    job = _seed_feed(app, user)
    source_id = app.state.service_store.create_source(
        workspace_id=user["workspace_id"],
        scope="private",
        owner_user_id=user["id"],
        source_type="rss",
        display_name="MCP diagnostics",
        config={"url": "https://example.com/diagnostics.xml"},
        source_key="rss:mcp-diagnostics",
    )
    subscription = app.state.service_store.create_subscription(
        user_id=user["id"], source_id=source_id
    )
    before = _business_dump(app)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8080",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            async with streamable_http_client(
                "http://127.0.0.1:8080/mcp",
                http_client=client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    listed = await session.list_tools()
                    result = await session.call_tool(
                        "get_my_feed", {"collection": "latest", "limit": 20}
                    )
                    remaining_results = [
                        await session.call_tool(
                            "get_item", {"article_id": "article-1"}
                        ),
                        await session.call_tool("list_subscriptions", {}),
                        await session.call_tool("source_health", {}),
                        await session.call_tool("list_jobs", {}),
                        await session.call_tool("get_job", {"job_id": job["id"]}),
                        await session.call_tool("get_source_setup_guide", {}),
                        await session.call_tool("list_available_sources", {}),
                        await session.call_tool(
                            "diagnose_source",
                            {"subscription_id": subscription["id"]},
                        ),
                        await session.call_tool(
                            "diagnose_job", {"job_id": job["id"]}
                        ),
                    ]

    assert [tool.name for tool in listed.tools] == [
        "get_my_feed",
        "get_item",
        "list_subscriptions",
        "source_health",
        "list_jobs",
        "get_job",
        "get_source_setup_guide",
        "list_available_sources",
        "prepare_create_subscription",
        "prepare_update_subscription",
        "prepare_delete_subscription",
        "apply_subscription_change",
        "diagnose_source",
        "diagnose_job",
    ]
    get_item_schema = next(
        tool.inputSchema for tool in listed.tools if tool.name == "get_item"
    )
    assert get_item_schema["properties"]["body_offset"] | {
        "minimum": 0,
        "maximum": 20_000,
    } == get_item_schema["properties"]["body_offset"]
    assert get_item_schema["properties"]["max_body_chars"] | {
        "minimum": 1,
        "maximum": 8000,
    } == get_item_schema["properties"]["max_body_chars"]
    annotations = {tool.name: tool.annotations for tool in listed.tools}
    assert all(
        tool.inputSchema.get("additionalProperties") is False
        for tool in listed.tools
    )
    for name in {
        "get_my_feed",
        "get_item",
        "list_subscriptions",
        "source_health",
        "list_jobs",
        "get_job",
        "get_source_setup_guide",
        "list_available_sources",
        "diagnose_source",
        "diagnose_job",
    }:
        assert annotations[name].readOnlyHint is True
        assert annotations[name].destructiveHint is False
        assert annotations[name].idempotentHint is True
        assert annotations[name].openWorldHint is False
    for name in {
        "prepare_create_subscription",
        "prepare_update_subscription",
        "prepare_delete_subscription",
    }:
        assert annotations[name].readOnlyHint is False
        assert annotations[name].destructiveHint is False
        assert annotations[name].idempotentHint is False
        assert annotations[name].openWorldHint is False
    assert annotations["apply_subscription_change"].readOnlyHint is False
    assert annotations["apply_subscription_change"].destructiveHint is True
    assert annotations["apply_subscription_change"].idempotentHint is False
    assert annotations["apply_subscription_change"].openWorldHint is False
    assert result.isError is False
    assert result.structuredContent["items"][0]["article_id"] == "article-1"
    assert all(call.isError is False for call in remaining_results)
    assert _business_dump(app) == before


@pytest.mark.anyio
async def test_remote_mcp_masks_internal_errors_with_a_request_id(
    tmp_path,
    monkeypatch,
    caplog,
):
    def fail_safely(*_args, **_kwargs):
        raise RuntimeError("Bearer super-secret internal detail")

    monkeypatch.setattr(
        "src.mcp.remote_service.RemoteMCPReadService.source_health",
        fail_safely,
    )
    app = _app(tmp_path, monkeypatch)
    _user, _connection, token = _token(app)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8080",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            async with streamable_http_client(
                "http://127.0.0.1:8080/mcp",
                http_client=client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool("source_health", {})

    message = result.content[0].text
    assert result.isError is True
    assert "internal_error request_id=mcp_" in message
    assert "super-secret" not in message
    assert "super-secret" not in caplog.text


@pytest.mark.anyio
async def test_remote_mcp_rate_limits_bursts_per_delegation(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch)
    _user, _connection, token = _token(app)
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8080",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            async with streamable_http_client(
                "http://127.0.0.1:8080/mcp",
                http_client=client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    calls = [
                        await session.call_tool("source_health", {})
                        for _ in range(20)
                    ]

    assert any(
        call.isError and "rate_limited" in call.content[0].text for call in calls
    )


@pytest.mark.anyio
async def test_remote_mcp_rejects_missing_scope_revoked_and_disabled_user_tokens(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch)
    user, connection, token = _token(app)
    store = app.state.service_store
    transport = httpx.ASGITransport(app=app)
    headers = {
        "Accept": "application/json, text/event-stream",
        "Authorization": f"Bearer {token}",
    }

    store.connect().execute(
        "UPDATE agent_delegations SET scopes_json = '[]' WHERE id = ?",
        (connection["id"],),
    )
    store.connect().commit()
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8080"
        ) as client:
            invalid = await client.post(
                "/mcp",
                json=_initialize_payload(),
                headers={**headers, "Authorization": "Bearer invalid"},
            )
            insufficient = await client.post(
                "/mcp", json=_initialize_payload(), headers=headers
            )
            store.connect().execute(
                "UPDATE agent_delegations SET scopes_json = '[\"inteliscope:read\"]' WHERE id = ?",
                (connection["id"],),
            )
            store.connect().commit()
            store.revoke_agent_delegation(user["id"], connection["id"])
            revoked = await client.post(
                "/mcp", json=_initialize_payload(), headers=headers
            )
            _connection2, token2 = store.create_agent_delegation(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                name="Second",
            )
            store.update_user(user["id"], enabled=False)
            disabled = await client.post(
                "/mcp",
                json=_initialize_payload(),
                headers={**headers, "Authorization": f"Bearer {token2}"},
            )

    assert insufficient.status_code == 403
    assert invalid.status_code == 401
    assert revoked.status_code == 401
    assert disabled.status_code == 401
    assert invalid.text == revoked.text == disabled.text


@pytest.mark.anyio
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
async def test_remote_mcp_rejects_corrupt_stored_scope_values_without_500(
    tmp_path, monkeypatch, stored_scopes
):
    app = _app(tmp_path, monkeypatch)
    _user, connection, token = _token(app)
    store = app.state.service_store
    store.connect().execute(
        "UPDATE agent_delegations SET scopes_json = ? WHERE id = ?",
        (stored_scopes, connection["id"]),
    )
    store.connect().commit()

    verified = await AgentDelegationTokenVerifier(store).verify_token(token)
    transport = httpx.ASGITransport(app=app)
    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport, base_url="http://127.0.0.1:8080"
        ) as client:
            response = await client.post(
                "/mcp",
                json=_initialize_payload(),
                headers={
                    "Accept": "application/json, text/event-stream",
                    "Authorization": f"Bearer {token}",
                },
            )

    assert verified is not None
    assert verified.scopes == []
    assert response.status_code == 403


@pytest.mark.anyio
async def test_admin_delegation_still_cannot_read_another_users_item(
    tmp_path,
    monkeypatch,
):
    app = _app(tmp_path, monkeypatch)
    store = app.state.service_store
    owner = store.get_user_by_username("owner")
    _seed_feed(app, owner)
    admin = store.create_user(
        workspace_id=owner["workspace_id"],
        username="second-admin",
        password="second-admin-password",
        role="admin",
    )
    _connection, token = store.create_agent_delegation(
        workspace_id=admin["workspace_id"],
        user_id=admin["id"],
        name="Admin OpenClaw",
    )
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8080",
            headers={"Authorization": f"Bearer {token}"},
        ) as client:
            async with streamable_http_client(
                "http://127.0.0.1:8080/mcp",
                http_client=client,
                terminate_on_close=False,
            ) as (read_stream, write_stream, _get_session_id):
                async with ClientSession(read_stream, write_stream) as session:
                    await session.initialize()
                    result = await session.call_tool(
                        "get_item",
                        {"article_id": "article-1"},
                    )

    assert result.isError is True
    assert result.content[0].text.endswith(": not_found")


@pytest.mark.anyio
async def test_each_fastapi_app_owns_an_independent_mcp_session_manager(
    tmp_path, monkeypatch
):
    first = _app(tmp_path / "first", monkeypatch)
    second = _app(tmp_path / "second", monkeypatch)
    assert first.state.remote_mcp is not second.state.remote_mcp
    assert first.state.remote_mcp.session_manager is not second.state.remote_mcp.session_manager

    async with first.router.lifespan_context(first):
        pass
    async with second.router.lifespan_context(second):
        pass
