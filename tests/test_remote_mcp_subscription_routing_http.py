from __future__ import annotations

import pytest

from tests.remote_mcp_subscription_http_test_support import *  # noqa: F403
from tests.remote_mcp_subscription_routing_cases import (
    CREATE_CASES,
    DIRECT_CONFIG_TYPES,
)


@pytest.mark.anyio
async def test_real_tools_list_describes_setup_routing(tmp_path, monkeypatch):
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    _user, _connection, token = _delegation(app)

    async with _mcp_session(app, token) as session:
        tools = {tool.name: tool for tool in (await session.list_tools()).tools}

    resolve_description = tools["resolve_source"].description
    guide_description = tools["get_source_setup_guide"].description
    available_description = tools["list_available_sources"].description
    prepare_description = tools["prepare_create_subscription"].description
    assert "resolution.supported=true" in resolve_description
    assert "currently YouTube" in resolve_description
    assert "configuration_required" in resolve_description
    assert "get_source_setup_guide" in resolve_description
    assert "required_fields" in guide_description
    assert "Empty results" in available_description
    assert "self-service" in prepare_description
    assert "resolution_ref" in prepare_description


@pytest.mark.anyio
@pytest.mark.parametrize("source_type", DIRECT_CONFIG_TYPES)
async def test_real_mcp_wrong_resolver_recovers_through_prepare_apply(
    tmp_path, monkeypatch, source_type
):
    app = _app(tmp_path, monkeypatch, writes_enabled=True)
    user, _connection, token = _delegation(app)

    async with _mcp_session(app, token) as session:
        guide_call = await session.call_tool(
            "get_source_setup_guide", {"source_type": source_type}
        )
        resolved_call = await session.call_tool(
            "resolve_source",
            {"source_type": source_type, "input": "audit public target"},
        )
        prepared_call = await session.call_tool(
            "prepare_create_subscription",
            {
                "source": {
                    "mode": "private",
                    "type": source_type,
                    "display_name": "HTTP Audit " + source_type,
                    "config": CREATE_CASES[source_type],
                }
            },
        )
        assert app.state.service_store.list_user_subscriptions(user["id"]) == []
        prepared = prepared_call.structuredContent
        applied_call = await session.call_tool(
            "apply_subscription_change",
            {
                "proposal_id": prepared["proposal_id"],
                "confirmation_text": prepared["confirmation_text"],
            },
        )

    assert guide_call.structuredContent["source_type"]["resolution"] == {
        "supported": False
    }
    assert resolved_call.structuredContent["status"] == "configuration_required"
    assert prepared_call.isError is False
    assert applied_call.isError is False
    assert applied_call.structuredContent["result"]["subscription_id"]
    assert len(app.state.service_store.list_user_subscriptions(user["id"])) == 1
    assert _table_count(app, "fetch_jobs") == 0
