from __future__ import annotations

from tests.remote_mcp_subscription_http_test_support import *  # noqa: F403

@pytest.mark.anyio
@pytest.mark.parametrize(
    ("failure_kind", "exception_type"),
    [("integer", ValueError), ("recursion", RecursionError)],
    ids=("value-error", "recursion-error"),
)
async def test_input_triggered_pre_parse_failures_are_stable_audited_and_charged_once(
    tmp_path, monkeypatch, caplog, failure_kind, exception_type
):
    if failure_kind == "integer":
        integer_limit = sys.get_int_max_str_digits()
        assert integer_limit > 0
        sensitive_value = "9" * (integer_limit + 1)
    else:
        nesting_depth = 120_000
        sensitive_value = "[" * nesting_depth + "0" + "]" * nesting_depth

    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    _user, connection, token = _delegation(app)
    tool = app.state.remote_mcp._tool_manager.get_tool("get_my_feed")
    assert tool is not None
    with pytest.raises(exception_type):
        tool.fn_metadata.pre_parse_json({"limit": sensitive_value})
    caplog.set_level(logging.INFO, logger="src.mcp.remote_server")

    async with _mcp_session(app, token) as session:
        pre_parse_failure = await session.call_tool(
            "get_my_feed", {"limit": sensitive_value}
        )
        fillers = [
            await session.call_tool("get_source_setup_guide", {})
            for _ in range(9)
        ]
        limited = await session.call_tool("get_my_feed", {})

    assert pre_parse_failure.isError is True
    assert pre_parse_failure.content[0].text == "invalid_request"
    assert all(call.isError is False for call in fillers)
    assert limited.isError is True
    assert limited.content[0].text == "rate_limited"

    records = _audit_records(caplog)
    assert len(records) == 11
    _assert_fixed_audit_record(
        records[0],
        delegation_id=connection["id"],
        outcome="invalid_request",
        tool="get_my_feed",
    )
    for record in records[1:10]:
        _assert_fixed_audit_record(
            record,
            delegation_id=connection["id"],
            outcome="ok",
            tool="get_source_setup_guide",
        )
    _assert_fixed_audit_record(
        records[10],
        delegation_id=connection["id"],
        outcome="rate_limited",
        tool="get_my_feed",
    )
    serialized_evidence = repr(pre_parse_failure) + "\n" + caplog.text
    assert sensitive_value not in serialized_evidence
    for forbidden_detail in (
        "exceeds the limit",
        "integer string conversion",
        "stack overflow",
        "while decoding a json array",
        "valueerror",
        "recursionerror",
    ):
        assert forbidden_detail not in serialized_evidence.lower()


@pytest.mark.anyio
async def test_invalid_registered_calls_consume_burst_before_validation_without_leaks(
    tmp_path, monkeypatch, caplog
):
    sensitive_value = "invalid-burst-sensitive-value"
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    _user, connection, token = _delegation(app)
    caplog.set_level(logging.INFO, logger="src.mcp.remote_server")

    async with _mcp_session(app, token) as session:
        calls = [
            await session.call_tool(
                "prepare_create_subscription",
                _invalid_write_arguments(sensitive_value),
            )
            for _ in range(11)
        ]

    assert [call.content[0].text for call in calls[:10]] == ["invalid_request"] * 10
    assert calls[10].content[0].text == "rate_limited"
    records = _audit_records(caplog)
    assert len(records) == len(calls)
    for record in records[:10]:
        _assert_fixed_audit_record(
            record, delegation_id=connection["id"], outcome="invalid_request"
        )
    _assert_fixed_audit_record(
        records[10], delegation_id=connection["id"], outcome="rate_limited"
    )
    serialized_evidence = repr(calls) + "\n" + caplog.text
    for forbidden_detail in (
        sensitive_value,
        "https://example.com/invalid-burst.xml",
        "validation error",
        "extra_forbidden",
        "input_value",
    ):
        assert forbidden_detail not in serialized_evidence.lower()


@pytest.mark.anyio
async def test_valid_invalid_and_business_errors_share_one_charge_each(
    tmp_path, monkeypatch, caplog
):
    sensitive_value = "mixed-bucket-sensitive-value"
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    _user, connection, token = _delegation(app)
    caplog.set_level(logging.INFO, logger="src.mcp.remote_server")

    async with _mcp_session(app, token) as session:
        invalid_calls = [
            await session.call_tool(
                "prepare_create_subscription",
                _invalid_write_arguments(sensitive_value),
            )
            for _ in range(3)
        ]
        valid_calls = [
            await session.call_tool("get_source_setup_guide", {}) for _ in range(3)
        ]
        business_errors = [
            await session.call_tool("diagnose_job", {"job_id": "job_missing"})
            for _ in range(4)
        ]
        limited = await session.call_tool(
            "prepare_create_subscription",
            _invalid_write_arguments(sensitive_value),
        )

    assert [call.content[0].text for call in invalid_calls] == ["invalid_request"] * 3
    assert all(call.isError is False for call in valid_calls)
    assert all(call.content[0].text.endswith(": not_found") for call in business_errors)
    assert limited.content[0].text == "rate_limited"
    records = _audit_records(caplog)
    assert len(records) == 11
    assert sum(" outcome=invalid_request " in record for record in records) == 3
    assert sum(" outcome=ok " in record for record in records) == 3
    assert sum(" outcome=not_found " in record for record in records) == 4
    assert sum(" outcome=rate_limited " in record for record in records) == 1
    assert all(f"delegation_id={connection['id']} " in record for record in records)
    assert sensitive_value not in repr(invalid_calls) + caplog.text


@pytest.mark.anyio
async def test_same_delegation_has_independent_buckets_in_two_apps(
    tmp_path, monkeypatch, caplog
):
    sensitive_value = "app-local-sensitive-value"
    shared_root = tmp_path / "shared"
    first = _app(shared_root, monkeypatch, writes_enabled=True)
    _user, connection, token = _delegation(first)
    second_static = tmp_path / "second-static"
    second_static.mkdir(parents=True)
    second_static.joinpath("assets").mkdir()
    second_static.joinpath("index.html").write_text(
        "<!doctype html>", encoding="utf-8"
    )
    second = create_app(
        data_dir=shared_root / "data",
        static_dir=second_static,
    )
    caplog.set_level(logging.INFO, logger="src.mcp.remote_server")

    async with _mcp_session(first, token) as session:
        first_calls = [
            await session.call_tool(
                "prepare_create_subscription",
                _invalid_write_arguments(sensitive_value),
            )
            for _ in range(11)
        ]
    async with _mcp_session(second, token) as session:
        second_call = await session.call_tool(
            "prepare_create_subscription",
            _invalid_write_arguments(sensitive_value),
        )

    assert [call.content[0].text for call in first_calls[:10]] == [
        "invalid_request"
    ] * 10
    assert first_calls[10].content[0].text == "rate_limited"
    assert second_call.content[0].text == "invalid_request"
    records = _audit_records(caplog)
    assert len(records) == 12
    assert all(f"delegation_id={connection['id']} " in record for record in records)
    assert sensitive_value not in repr(first_calls) + repr(second_call) + caplog.text


@pytest.mark.anyio
async def test_unauthenticated_and_unknown_tools_are_not_charged_or_audited(
    tmp_path, monkeypatch, caplog
):
    sensitive_value = "unknown-tool-sensitive-value"
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    app.state.remote_mcp._delegation_limiter.refill_per_second = 0.0
    _user, _connection, token = _delegation(app)
    caplog.set_level(logging.INFO, logger="src.mcp.remote_server")
    transport = httpx.ASGITransport(app=app)

    async with app.router.lifespan_context(app):
        async with httpx.AsyncClient(
            transport=transport,
            base_url="http://127.0.0.1:8080",
            headers={"Accept": "application/json, text/event-stream"},
        ) as client:
            unauthenticated = await client.post(
                "/mcp",
                json={
                    "jsonrpc": "2.0",
                    "id": 2,
                    "method": "tools/call",
                    "params": {
                        "name": "prepare_create_subscription",
                        "arguments": _invalid_write_arguments(sensitive_value),
                    },
                },
            )
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
                    unknown = await session.call_tool(
                        "unknown_tool",
                        {"value": sensitive_value},
                    )
                    registered = [
                        await session.call_tool(
                            "prepare_create_subscription",
                            _invalid_write_arguments(sensitive_value),
                        )
                        for _ in range(11)
                    ]

    assert unauthenticated.status_code == 401
    assert unknown.isError is True
    assert unknown.content[0].text == "Unknown tool: unknown_tool"
    assert [call.content[0].text for call in registered] == ["invalid_request"] * 10 + ["rate_limited"]
    records = _audit_records(caplog)
    assert len(records) == 11
    assert all(" tool=prepare_create_subscription " in record for record in records)
    assert sensitive_value not in repr(unknown) + repr(registered) + caplog.text


@pytest.mark.anyio
async def test_real_mcp_client_prepare_apply_is_atomic_and_single_use(
    tmp_path, monkeypatch, caplog
):
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    user, _connection, token = _delegation(app)
    caplog.set_level(logging.INFO, logger="src.mcp.remote_server")
    before = {
        table: _table_count(app, table)
        for table in ("source_catalog", "user_subscriptions", "user_source_schedules")
    }

    async with _mcp_session(app, token) as session:
        prepared = await session.call_tool(
            "prepare_create_subscription",
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "MCP Example",
                    "config": {"url": "https://example.com/mcp-feed.xml"},
                },
                "subscription": {"priority": 17},
                "schedule": {"enabled": False, "interval_minutes": 60},
            },
        )
        assert prepared.isError is False
        proposal = prepared.structuredContent
        assert proposal["kind"] == "create"
        assert proposal["confirmation_text"].startswith("确认执行 ")
        assert {
            table: _table_count(app, table)
            for table in before
        } == before

        applied = await session.call_tool(
            "apply_subscription_change",
            {
                "proposal_id": proposal["proposal_id"],
                "confirmation_text": proposal["confirmation_text"],
            },
        )
        consumed = await session.call_tool(
            "apply_subscription_change",
            {
                "proposal_id": proposal["proposal_id"],
                "confirmation_text": proposal["confirmation_text"],
            },
        )

    assert applied.isError is False
    assert applied.structuredContent["status"] == "applied"
    source = next(
        item
        for item in app.state.service_store.list_visible_sources(user)
        if item["display_name"] == "MCP Example"
    )
    subscription = app.state.service_store.get_user_subscription_for_source(
        user["id"], source["id"]
    )
    assert source["scope"] == "private"
    assert source["owner_user_id"] == user["id"]
    assert subscription is not None
    assert consumed.isError is True
    assert consumed.content[0].text.endswith(": proposal_consumed")
    audit_records = [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.mcp.remote_server"
        and record.getMessage().startswith("remote_mcp_call ")
    ]
    proposal_records = [
        record
        for record in audit_records
        if f"proposal_id={proposal['proposal_id']}" in record
    ]
    assert len(proposal_records) == 3
    assert any(" action=create_subscription outcome=ok " in record for record in proposal_records)
    assert any(" action=apply outcome=proposal_consumed " in record for record in proposal_records)
    serialized_logs = "\n".join(audit_records)
    assert proposal["confirmation_text"] not in serialized_logs
    assert "https://example.com/mcp-feed.xml" not in serialized_logs
    assert "MCP Example" not in serialized_logs


@pytest.mark.anyio
async def test_real_mcp_client_read_delegation_gets_stable_write_scope_error(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    _user, _connection, token = _delegation(app, access="read")

    async with _mcp_session(app, token) as session:
        result = await session.call_tool(
            "prepare_create_subscription",
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Denied",
                    "config": {"url": "https://example.com/denied.xml"},
                }
            },
        )

    assert result.isError is True
    assert result.content[0].text.endswith(": write_scope_required")
    assert _table_count(app, "agent_change_proposals") == 0


@pytest.mark.anyio
async def test_real_mcp_client_flag_off_gets_stable_disabled_error(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch, writes_enabled=False)
    _user, _connection, token = _delegation(app)

    async with _mcp_session(app, token) as session:
        result = await session.call_tool(
            "prepare_create_subscription",
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Denied",
                    "config": {"url": "https://example.com/denied.xml"},
                }
            },
        )

    assert result.isError is True
    assert result.content[0].text.endswith(": subscription_writes_disabled")
    assert _table_count(app, "agent_change_proposals") == 0


@pytest.mark.anyio
async def test_new_tools_use_claim_identity_and_hide_cross_user_objects(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    store = app.state.service_store
    owner = store.get_user_by_username("owner")
    source_id = store.create_source(
        workspace_id=owner["workspace_id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="rss",
        display_name="Owner only",
        config={"url": "https://example.com/owner.xml"},
        source_key="rss:owner-only",
    )
    subscription = store.create_subscription(user_id=owner["id"], source_id=source_id)
    other = store.create_user(
        workspace_id=owner["workspace_id"],
        username="other-admin",
        password="other-admin-password",
        role="admin",
    )
    _user, _connection, token = _delegation(app, user=other)

    async with _mcp_session(app, token) as session:
        diagnosed = await session.call_tool(
            "diagnose_source", {"subscription_id": subscription["id"]}
        )
        updated = await session.call_tool(
            "prepare_update_subscription",
            {
                "subscription_id": subscription["id"],
                "subscription_updates": {"priority": 20},
            },
        )

    assert diagnosed.isError is True
    assert diagnosed.content[0].text.endswith(": not_found")
    assert updated.isError is True
    assert updated.content[0].text.endswith(": not_found")
