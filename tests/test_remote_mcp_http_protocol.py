from __future__ import annotations

from tests.remote_mcp_http_test_support import *  # noqa: F403

@pytest.mark.anyio
async def test_workspace_operation_logs_require_explicit_admin_delegation_and_filter(
    tmp_path,
    monkeypatch,
):
    app = _app(tmp_path, monkeypatch)
    store = app.state.service_store
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    admin = store.create_user(
        workspace_id=workspace["id"],
        username="workspace-admin",
        password="admin-password",
        role="admin",
    )
    member = store.create_user(
        workspace_id=workspace["id"],
        username="workspace-member",
        password="member-password",
        role="member",
    )
    owner_old_token = store.create_agent_delegation(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        name="Old owner token",
    )[1]
    admin_workspace_token = store.create_agent_delegation(
        workspace_id=workspace["id"],
        user_id=admin["id"],
        name="Explicit workspace diagnostics",
        diagnostics_scope="workspace",
    )[1]
    member_token = store.create_agent_delegation(
        workspace_id=workspace["id"],
        user_id=member["id"],
        name="Member token",
    )[1]
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_dir.joinpath("operations-api.jsonl").write_text(
        "".join(
            json.dumps(
                {
                    "schema_version": 1,
                    "event_id": f"evt_workspace_{index}",
                    "timestamp": now,
                    "level": "warning",
                    "service": "api",
                    "category": "request",
                    "action": "unhandled_error",
                    "outcome": "failed",
                    "workspace_id": workspace["id"],
                    "actor_user_id": user["id"],
                    "request_id": f"req_workspace_{index}",
                    "error_code": "internal_error",
                    "stage": "request",
                    "error_fingerprint": f"err_workspace_{index}",
                }
            )
            + "\n"
            for index, user in enumerate((owner, member), start=1)
        ),
        encoding="utf-8",
    )
    transport = httpx.ASGITransport(app=app)

    async def call(token, arguments):
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
                    return await session.call_tool(
                        "query_operation_logs",
                        arguments,
                    )

    async with app.router.lifespan_context(app):
        old_owner = await call(
            owner_old_token,
            {"scope": "workspace", "minimum_level": "warning"},
        )
        member_denied = await call(
            member_token,
            {"scope": "workspace", "minimum_level": "warning"},
        )
        broad_denied = await call(
            admin_workspace_token,
            {"scope": "workspace"},
        )
        workspace_result = await call(
            admin_workspace_token,
            {"scope": "workspace", "minimum_level": "warning"},
        )
        store.update_user(admin["id"], role="member")
        downgraded = await call(
            admin_workspace_token,
            {"scope": "workspace", "minimum_level": "warning"},
        )

    assert old_owner.isError is True
    assert "diagnostics_scope_required" in old_owner.content[0].text
    assert member_denied.isError is True
    assert "diagnostics_scope_required" in member_denied.content[0].text
    assert broad_denied.isError is True
    assert "diagnostics_filter_required" in broad_denied.content[0].text
    assert workspace_result.isError is False
    payload = workspace_result.structuredContent
    assert payload["scope"] == "workspace"
    assert {event["event_id"] for event in payload["events"]} == {
        "evt_workspace_1",
        "evt_workspace_2",
    }
    assert all(
        event["stage"] == "request"
        and event["error_fingerprint"].startswith("err_workspace_")
        for event in payload["events"]
    )
    serialized = json.dumps(payload)
    assert owner["id"] not in serialized
    assert member["id"] not in serialized
    assert workspace["id"] not in serialized
    assert downgraded.isError is True
    assert "diagnostics_scope_required" in downgraded.content[0].text


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
