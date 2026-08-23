from __future__ import annotations

import logging
import re
import sys
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


def _assert_fixed_audit_record(
    record: str,
    *,
    delegation_id: str,
    outcome: str,
    tool: str = "prepare_create_subscription",
):
    assert re.fullmatch(
        rf"remote_mcp_call delegation_id={re.escape(delegation_id)} "
        rf"tool={re.escape(tool)} proposal_id=- action=- "
        rf"outcome={outcome} elapsed_ms=\d+ request_id=mcp_[0-9a-f]{{32}}",
        record,
    )

def test_support_exports_subscription_http_fixture_and_app_factory() -> None:
    assert callable(anyio_backend)
    assert callable(_app)


__all__ = [
    name
    for name in globals()
    if not name.startswith("__")
    and name != "test_support_exports_subscription_http_fixture_and_app_factory"
]
