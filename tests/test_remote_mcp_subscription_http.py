from __future__ import annotations

import logging
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
