from __future__ import annotations

import pytest
import httpx
from mcp import ClientSession
from mcp.client.streamable_http import streamable_http_client

from src.mcp.remote_system_settings_service import RemoteMCPSystemSettingsService
from src.services.agent_change_proposal import AgentProposalError, DelegatedActor
from src.services.system_settings import resolve_system_setting
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from tests.remote_mcp_http_test_support import _app


@pytest.fixture
def anyio_backend():
    return "asyncio"


def _context(tmp_path, *, writes_enabled: bool = True):
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="mcp-settings-owner",
        password="safe-test-password",
        role="owner",
    )
    connection, _token = store.create_agent_delegation(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=owner["id"],
        name="System management",
        access="system_settings_write",
    )
    actor = DelegatedActor(
        workspace_id=DEFAULT_WORKSPACE_ID,
        user_id=owner["id"],
        role="owner",
        delegation_id=connection["id"],
        scopes=tuple(connection["scopes"]),
    )
    return store, actor, RemoteMCPSystemSettingsService(
        store, writes_enabled=writes_enabled
    )


def test_list_works_with_scope_even_when_write_gate_is_off(tmp_path) -> None:
    _store, actor, service = _context(tmp_path, writes_enabled=False)
    assert service.list_system_settings(actor=actor)["generation"] == 1
    with pytest.raises(AgentProposalError) as error:
        service.prepare_update_system_settings(
            actor=actor,
            expected_generation=1,
            changes={"jobs.max_attempts": 4},
        )
    assert error.value.code == "system_settings_writes_disabled"


def test_mcp_prepare_apply_revalidates_delegation_and_applies_alias(tmp_path) -> None:
    store, actor, service = _context(tmp_path)
    prepared = service.prepare_update_system_settings(
        actor=actor,
        expected_generation=1,
        changes={"INFOHUB_MAX_WORKSPACE_FETCH_ATTEMPTS_PER_DAY": 500},
    )
    applied = service.apply_system_settings_change(
        actor=actor,
        proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation"],
    )
    assert applied["generation"] == 2
    assert resolve_system_setting(
        store, DEFAULT_WORKSPACE_ID,
        "limits.max_workspace_fetch_attempts_per_day",
    ) == 500

    store.revoke_agent_delegation(actor.user_id, actor.delegation_id)
    with pytest.raises(AgentProposalError) as error:
        service.prepare_update_system_settings(
            actor=actor,
            expected_generation=2,
            changes={"jobs.max_attempts": 5},
        )
    assert error.value.code == "system_settings_delegation_invalid"


def test_old_read_and_subscription_tokens_are_not_upgraded(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="old-token-owner",
        password="safe-test-password",
        role="owner",
    )
    for access in ("read", "subscriptions_write"):
        connection, _ = store.create_agent_delegation(
            workspace_id=DEFAULT_WORKSPACE_ID,
            user_id=owner["id"],
            name=access,
            access=access,
        )
        actor = DelegatedActor(
            workspace_id=DEFAULT_WORKSPACE_ID,
            user_id=owner["id"],
            role="owner",
            delegation_id=connection["id"],
            scopes=tuple(connection["scopes"]),
        )
        with pytest.raises(AgentProposalError) as error:
            RemoteMCPSystemSettingsService(
                store, writes_enabled=True
            ).list_system_settings(actor=actor)
        assert error.value.code == "system_settings_scope_required"


@pytest.mark.anyio
async def test_real_mcp_system_connection_lists_prepares_and_applies(
    tmp_path, monkeypatch
) -> None:
    monkeypatch.setenv("HORIZON_REMOTE_MCP_SYSTEM_SETTINGS_WRITES_ENABLED", "true")
    app = _app(tmp_path, monkeypatch)
    store = app.state.service_store
    owner = store.get_user_by_username("owner")
    connection, token = store.create_agent_delegation(
        workspace_id=owner["workspace_id"],
        user_id=owner["id"],
        name="System management",
        access="system_settings_write",
    )
    assert connection["scopes"] == [
        "inteliscope:read",
        "inteliscope:system-settings:write",
    ]
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
                    listed = await session.call_tool("list_system_settings", {})
                    prepared = await session.call_tool(
                        "prepare_update_system_settings",
                        {
                            "expected_generation": 1,
                            "changes": [{
                                "key": "INFOHUB_MAX_WORKSPACE_FETCH_ATTEMPTS_PER_DAY",
                                "value": 500,
                            }],
                        },
                    )
                    proposal = prepared.structuredContent
                    applied = await session.call_tool(
                        "apply_system_settings_change",
                        {
                            "proposal_id": proposal["proposal_id"],
                            "confirmation_text": proposal["confirmation"],
                        },
                    )
    assert listed.isError is False
    assert len(listed.structuredContent["settings"]) == 21
    assert prepared.isError is False
    assert applied.isError is False
    assert applied.structuredContent["generation"] == 2
