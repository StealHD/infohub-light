from __future__ import annotations

from tests.remote_mcp_http_test_support import *  # noqa: F403

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


@pytest.mark.anyio
async def test_delegation_token_verifier_uses_the_mcp_126_access_token_contract(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch)
    _user, connection, token = _token(app)

    verified = await AgentDelegationTokenVerifier(
        app.state.service_store
    ).verify_token(token)

    assert verified is not None
    assert verified.token == connection["id"]
    assert verified.client_id == f"openclaw:{connection['id']}"
    assert getattr(verified, "subject", None) is None
    assert getattr(verified, "claims", None) is None


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
async def test_real_mcp_client_lists_seventeen_tools_with_exact_annotations_and_calls_reads(
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
                        await session.call_tool(
                            "search_bilibili_users",
                            {"query": "食贫道", "limit": 5},
                        ),
                        await session.call_tool("list_available_sources", {}),
                        await session.call_tool(
                            "diagnose_source",
                            {"subscription_id": subscription["id"]},
                        ),
                    ]
                    await anyio.sleep(2.05)
                    remaining_results.extend(
                        [
                            await session.call_tool(
                                "resolve_source",
                                {
                                    "source_type": "youtube",
                                    "input": "老高和小茉",
                                    "candidate_urls": [],
                                },
                            ),
                        await session.call_tool(
                            "diagnose_job", {"job_id": job["id"]}
                            ),
                        ]
                    )

    assert [tool.name for tool in listed.tools] == [
        "get_my_feed",
        "get_item",
        "list_subscriptions",
        "source_health",
        "list_jobs",
        "get_job",
        "get_source_setup_guide",
        "search_bilibili_users",
        "resolve_source",
        "list_available_sources",
        "prepare_create_subscription",
        "prepare_update_subscription",
        "prepare_delete_subscription",
        "apply_subscription_change",
        "diagnose_source",
        "diagnose_job",
        "query_operation_logs",
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
    search_schema = next(
        tool.inputSchema
        for tool in listed.tools
        if tool.name == "search_bilibili_users"
    )
    assert search_schema["properties"]["query"]["maxLength"] == 50
    assert search_schema["properties"]["limit"] | {
        "minimum": 1,
        "maximum": 5,
    } == search_schema["properties"]["limit"]
    resolve_schema = next(
        tool.inputSchema
        for tool in listed.tools
        if tool.name == "resolve_source"
    )
    assert resolve_schema["properties"]["input"]["maxLength"] == 2048
    candidate_schema = resolve_schema["properties"]["candidate_urls"]
    candidate_array = next(
        option
        for option in candidate_schema["anyOf"]
        if option.get("type") == "array"
    )
    assert candidate_array["maxItems"] == 5
    assert resolve_schema["properties"]["limit"] | {
        "minimum": 1,
        "maximum": 5,
    } == resolve_schema["properties"]["limit"]
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
        "query_operation_logs",
    }:
        assert annotations[name].readOnlyHint is True
        assert annotations[name].destructiveHint is False
        assert annotations[name].idempotentHint is True
        assert annotations[name].openWorldHint is False
    assert annotations["search_bilibili_users"].readOnlyHint is True
    assert annotations["search_bilibili_users"].destructiveHint is False
    assert annotations["search_bilibili_users"].idempotentHint is True
    assert annotations["search_bilibili_users"].openWorldHint is True
    assert annotations["resolve_source"].readOnlyHint is True
    assert annotations["resolve_source"].destructiveHint is False
    assert annotations["resolve_source"].idempotentHint is True
    assert annotations["resolve_source"].openWorldHint is True
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
    assert next(
        call
        for call in remaining_results
        if call.structuredContent
        and call.structuredContent.get("status") == "discovery_required"
    ).structuredContent["candidates"] == []
    assert _business_dump(app) == before


@pytest.mark.anyio
async def test_query_operation_logs_is_strictly_current_user_scoped_for_all_roles(
    tmp_path,
    monkeypatch,
):
    app = _app(tmp_path, monkeypatch)
    store = app.state.service_store
    workspace = store.get_default_workspace()
    users = {
        "owner": store.get_user_by_username("owner"),
        **{
            role: store.create_user(
                workspace_id=workspace["id"],
                username=f"{role}-logs",
                password=f"{role}-password",
                role=role,
            )
            for role in ("admin", "member", "viewer")
        },
    }
    tokens = {
        role: store.create_agent_delegation(
            workspace_id=workspace["id"],
            user_id=user["id"],
            name=f"{role} log reader",
            access="read",
        )[1]
        for role, user in users.items()
    }
    now = datetime.now(timezone.utc).isoformat().replace("+00:00", "Z")
    raw_events = [
        {
            "schema_version": 1,
            "event_id": f"evt_{role}",
            "timestamp": now,
            "level": "info",
            "service": "api",
            "category": "account",
            "action": "profile_update",
            "outcome": "succeeded",
            "workspace_id": workspace["id"],
            "actor_user_id": user["id"],
            "job_id": f"job_{role}",
            "message": "raw message must not escape",
            "stack": "private stack",
            "path": "/private/log/path",
            "url": "https://private.example/path",
            "authorization": "Bearer private",
            "article_id": "private-article",
        }
        for role, user in users.items()
    ]
    log_dir = tmp_path / "logs"
    log_dir.mkdir()
    log_dir.joinpath("operations-api.jsonl").write_text(
        "".join(json.dumps(event) + "\n" for event in raw_events),
        encoding="utf-8",
    )
    transport = httpx.ASGITransport(app=app)

    results = {}
    async with app.router.lifespan_context(app):
        for role, token in tokens.items():
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
                    async with ClientSession(
                        read_stream, write_stream
                    ) as session:
                        await session.initialize()
                        results[role] = await session.call_tool(
                            "query_operation_logs",
                            {"lookback_hours": 1, "limit": 100},
                        )
                        cross_scope = await session.call_tool(
                            "query_operation_logs",
                            {
                                "lookback_hours": 1,
                                "job_id": (
                                    "job_member"
                                    if role != "member"
                                    else "job_owner"
                                ),
                            },
                        )
                        assert cross_scope.structuredContent["events"] == []

    for role, result in results.items():
        assert result.isError is False
        payload = result.structuredContent
        assert [event["event_id"] for event in payload["events"]] == [
            f"evt_{role}"
        ]
        serialized = json.dumps(payload)
        for user in users.values():
            assert user["id"] not in serialized
        for forbidden in (
            workspace["id"],
            "raw message",
            "private stack",
            "/private/log/path",
            "private.example",
            "Bearer private",
            "private-article",
        ):
            assert forbidden not in serialized
