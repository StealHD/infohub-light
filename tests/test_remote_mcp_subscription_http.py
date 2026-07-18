from __future__ import annotations

import logging
import re
from contextlib import asynccontextmanager

import httpx
import pytest
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from src.api.server import create_app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _app(tmp_path, monkeypatch, *, writes_enabled: bool):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    monkeypatch.setenv("HORIZON_REMOTE_MCP_ENABLED", "true")
    monkeypatch.setenv(
        "HORIZON_REMOTE_MCP_PUBLIC_URL", "http://127.0.0.1:8080/mcp"
    )
    monkeypatch.setenv(
        "HORIZON_REMOTE_MCP_SUBSCRIPTION_WRITES_ENABLED",
        "true" if writes_enabled else "false",
    )
    static_dir = tmp_path / "static"
    static_dir.mkdir(parents=True)
    static_dir.joinpath("assets").mkdir()
    static_dir.joinpath("index.html").write_text(
        "<!doctype html>", encoding="utf-8"
    )
    return create_app(data_dir=tmp_path / "data", static_dir=static_dir)


def _delegation(app, *, access: str = "subscriptions_write", user=None):
    store = app.state.service_store
    user = user or store.get_user_by_username("owner")
    connection, token = store.create_agent_delegation(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        name=f"MCP {access}",
        access=access,
    )
    return user, connection, token


@asynccontextmanager
async def _mcp_session(app, token):
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
                    yield session


def _table_count(app, table: str) -> int:
    return int(
        app.state.service_store.connect()
        .execute(f"SELECT COUNT(*) FROM {table}")
        .fetchone()[0]
    )


def _audit_records(caplog):
    return [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.mcp.remote_server"
        and record.getMessage().startswith("remote_mcp_call ")
    ]


def _invalid_write_arguments(sensitive_value: str):
    return {
        "source": {
            "mode": "private",
            "type": "rss",
            "display_name": "Invalid burst",
            "config": {"url": "https://example.com/invalid-burst.xml"},
        },
        "user_id": sensitive_value,
    }


def _assert_fixed_audit_record(record: str, *, delegation_id: str, outcome: str):
    assert re.fullmatch(
        rf"remote_mcp_call delegation_id={re.escape(delegation_id)} "
        r"tool=prepare_create_subscription proposal_id=- action=- "
        rf"outcome={outcome} elapsed_ms=\d+ request_id=mcp_[0-9a-f]{{32}}",
        record,
    )


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
    assert [call.content[0].text for call in registered[:10]] == [
        "invalid_request"
    ] * 10
    assert registered[10].content[0].text == "rate_limited"
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


@pytest.mark.anyio
async def test_tool_schemas_forbid_extra_identity_and_keep_config_as_only_open_container(
    tmp_path, monkeypatch
):
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    _user, _connection, token = _delegation(app)

    async with _mcp_session(app, token) as session:
        listed = await session.list_tools()
        tool = next(
            item for item in listed.tools if item.name == "prepare_create_subscription"
        )
        rejected_identity = await session.call_tool(
            "prepare_create_subscription",
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Forged",
                    "config": {"url": "https://example.com/forged.xml"},
                },
                "user_id": "forged-user",
            },
        )
        rejected_config = await session.call_tool(
            "prepare_create_subscription",
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Unsafe",
                    "config": {
                        "url": "https://example.com/unsafe.xml",
                        "headers": {"Authorization": "redacted-test-value"},
                    },
                }
            },
        )
        other_unsafe_configs = []
        for field, value in (
            ("secret", "never-log-this-secret"),
            ("path", "/private/unsafe-path"),
            ("sql", "SELECT private_data"),
            ("user_id", "forged-config-user"),
        ):
            other_unsafe_configs.append(
                await session.call_tool(
                    "prepare_create_subscription",
                    {
                        "source": {
                            "mode": "private",
                            "type": "rss",
                            "display_name": "Unsafe",
                            "config": {
                                "url": "https://example.com/unsafe.xml",
                                field: value,
                            },
                        }
                    },
                )
            )

    schema = tool.inputSchema
    assert schema["additionalProperties"] is False
    private_source = schema["$defs"]["PrivateSourceInput"]
    source_union = schema["properties"]["source"]
    assert source_union["discriminator"]["propertyName"] == "mode"
    assert set(source_union["discriminator"]["mapping"]) == {"existing", "private"}
    assert private_source["additionalProperties"] is False
    assert set(private_source["properties"]) == {
        "mode",
        "type",
        "display_name",
        "config",
        "description",
        "default_channel",
        "default_topics",
    }
    assert private_source["properties"]["config"]["additionalProperties"] is True
    assert rejected_identity.isError is True
    assert "forged-user" not in rejected_identity.content[0].text
    assert rejected_config.isError is True
    assert rejected_config.content[0].text.endswith(": invalid_source_config")
    assert "redacted-test-value" not in rejected_config.content[0].text
    assert all(result.isError is True for result in other_unsafe_configs)
    assert all(
        result.content[0].text.endswith(": invalid_source_config")
        for result in other_unsafe_configs
    )
    serialized_errors = repr(other_unsafe_configs)
    for forbidden_value in (
        "never-log-this-secret",
        "/private/unsafe-path",
        "SELECT private_data",
        "forged-config-user",
    ):
        assert forbidden_value not in serialized_errors
    assert _table_count(app, "agent_change_proposals") == 0


@pytest.mark.anyio
@pytest.mark.parametrize(
    ("arguments", "sensitive_value"),
    [
        (
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Outer Extra",
                    "config": {"url": "https://example.com/outer.xml"},
                },
                "user_id": "outer-extra-sensitive-value",
            },
            "outer-extra-sensitive-value",
        ),
        (
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Nested Extra",
                    "config": {"url": "https://example.com/nested.xml"},
                },
                "subscription": {"user_id": "nested-extra-sensitive-value"},
            },
            "nested-extra-sensitive-value",
        ),
        (
            {
                "source": {
                    "mode": "invalid-discriminator-sensitive-value",
                    "source_id": "source_unused",
                }
            },
            "invalid-discriminator-sensitive-value",
        ),
        (
            {
                "source": {
                    "mode": "private",
                    "type": "rss",
                    "display_name": "Range Error",
                    "config": {"url": "https://example.com/range.xml"},
                },
                "subscription": {"priority": 987654321},
            },
            "987654321",
        ),
    ],
    ids=("outer-extra", "nested-extra", "discriminator", "range"),
)
async def test_authenticated_validation_failures_are_stable_audited_and_redacted(
    tmp_path, monkeypatch, caplog, arguments, sensitive_value
):
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    _user, connection, token = _delegation(app)
    caplog.set_level(logging.INFO, logger="src.mcp.remote_server")

    async with _mcp_session(app, token) as session:
        result = await session.call_tool(
            "prepare_create_subscription",
            arguments,
        )

    assert result.isError is True
    assert result.content[0].text == "invalid_request"
    audit_records = [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.mcp.remote_server"
        and record.getMessage().startswith("remote_mcp_call ")
    ]
    assert len(audit_records) == 1
    assert re.fullmatch(
        rf"remote_mcp_call delegation_id={re.escape(connection['id'])} "
        r"tool=prepare_create_subscription proposal_id=- action=- "
        r"outcome=invalid_request elapsed_ms=\d+ request_id=mcp_[0-9a-f]{32}",
        audit_records[0],
    )
    serialized_evidence = result.content[0].text + "\n" + caplog.text
    assert sensitive_value not in serialized_evidence
    for forbidden_detail in (
        "validation error",
        "extra_forbidden",
        "union_tag_invalid",
        "less_than_equal",
        "input_value",
    ):
        assert forbidden_detail not in serialized_evidence.lower()
    assert _table_count(app, "agent_change_proposals") == 0


@pytest.mark.anyio
@pytest.mark.parametrize("exception_type", [RuntimeError, ValueError])
async def test_new_tool_internal_error_and_fixed_audit_log_are_redacted(
    tmp_path, monkeypatch, caplog, exception_type
):
    def fail_safely(*_args, **_kwargs):
        raise exception_type("Bearer hidden-diagnostic-value")

    monkeypatch.setattr(
        "src.mcp.remote_diagnostics.RemoteMCPDiagnostics.diagnose_job",
        fail_safely,
    )
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    _user, connection, token = _delegation(app)
    caplog.set_level(logging.INFO, logger="src.mcp.remote_server")

    async with _mcp_session(app, token) as session:
        result = await session.call_tool("diagnose_job", {"job_id": "job_missing"})

    assert result.isError is True
    assert "internal_error request_id=mcp_" in result.content[0].text
    assert "hidden-diagnostic-value" not in result.content[0].text
    records = [
        record.getMessage()
        for record in caplog.records
        if record.name == "src.mcp.remote_server"
        and record.getMessage().startswith("remote_mcp_call ")
    ]
    assert len(records) == 1
    assert records[0].startswith(
        f"remote_mcp_call delegation_id={connection['id']} tool=diagnose_job "
        "proposal_id=- action=- outcome=internal_error elapsed_ms="
    )
    assert " request_id=mcp_" in records[0]
    assert "job_missing" not in records[0]
    assert "hidden-diagnostic-value" not in caplog.text
