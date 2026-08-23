from __future__ import annotations

import hashlib
import json
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone
from typing import Any
from unittest.mock import Mock

import pytest

import src.services.agent_change_proposal as proposal_service_module
import src.storage.service_store as service_store_module
from src.mcp.remote_subscription_service import RemoteMCPSubscriptionService
from src.services.agent_change_proposal import (
    AgentChangeProposalService,
    AgentProposalError,
    DelegatedActor,
)
from src.services.source_type_registry import SourceConfigError
from src.services.quota import QuotaExceeded
from src.services.subscription_mutation import SubscriptionMutationService
from src.storage.service_store import (
    AGENT_DELEGATION_READ_SCOPE,
    AGENT_DELEGATION_WRITE_SCOPE,
    ServiceStore,
)


NOW = datetime(2026, 7, 17, 9, 30, tzinfo=timezone.utc)


def _actor(context: dict[str, Any], name: str) -> DelegatedActor:
    user = context[name]
    delegation = context[f"{name}_write"]
    return DelegatedActor(
        workspace_id=context["workspace"]["id"],
        user_id=user["id"],
        role=user["role"],
        delegation_id=delegation["id"],
        scopes=tuple(delegation["scopes"]),
    )


def _read_actor(context: dict[str, Any]) -> DelegatedActor:
    user = context["member"]
    delegation = context["member_read"]
    return DelegatedActor(
        workspace_id=context["workspace"]["id"],
        user_id=user["id"],
        role=user["role"],
        delegation_id=delegation["id"],
        scopes=tuple(delegation["scopes"]),
    )


def _source(
    context: dict[str, Any],
    *,
    name: str,
    source_type: str = "rss",
    scope: str = "workspace",
    owner: str = "owner",
    config: dict[str, Any] | None = None,
    secret_env: str | None = None,
    enabled: bool = True,
) -> dict[str, Any]:
    config = config or {"url": f"https://example.com/{name}.xml"}
    source_id = context["store"].create_source(
        workspace_id=context["workspace"]["id"],
        scope=scope,
        owner_user_id=context[owner]["id"],
        source_type=source_type,
        display_name=name,
        config=config,
        source_key=f"{source_type}:{name}",
        secret_env=secret_env,
        enabled=enabled,
    )
    source = context["store"].get_source(source_id)
    assert source is not None
    return source


@pytest.fixture
def context(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    proposal_clock = [NOW]
    monkeypatch.setattr(
        service_store_module,
        "_proposal_utc_now",
        lambda: proposal_clock[0],
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    member = store.create_user(
        workspace_id=workspace["id"],
        username="member",
        password="member-password",
        role="member",
    )
    other = store.create_user(
        workspace_id=workspace["id"],
        username="other",
        password="other-password",
        role="member",
    )
    viewer = store.create_user(
        workspace_id=workspace["id"],
        username="viewer",
        password="viewer-password",
        role="viewer",
    )

    def delegation(user, access):
        row, _token = store.create_agent_delegation(
            workspace_id=workspace["id"],
            user_id=user["id"],
            name=f"{user['username']} {access}",
            access=access,
        )
        return row

    writes_enabled = [True]
    secret_calls: list[str] = []

    def secret_is_set(name: str) -> bool:
        secret_calls.append(name)
        return name == "VISIBLE_TOKEN"

    mutations = SubscriptionMutationService(store)
    proposals = AgentChangeProposalService(
        store,
        writes_enabled=lambda: writes_enabled[0],
        now=lambda: NOW - timedelta(days=30),
    )
    service = RemoteMCPSubscriptionService(
        store=store,
        mutations=mutations,
        proposals=proposals,
        secret_is_set=secret_is_set,
    )
    return {
        "store": store,
        "workspace": workspace,
        "owner": owner,
        "member": member,
        "other": other,
        "viewer": viewer,
        "member_write": delegation(member, "subscriptions_write"),
        "member_read": delegation(member, "read"),
        "other_write": delegation(other, "subscriptions_write"),
        # The store deliberately permits constructing this row; the Web API is
        # the creation guard and proposal prepare must still reject its live role.
        "viewer_write": delegation(viewer, "subscriptions_write"),
        "writes_enabled": writes_enabled,
        "secret_calls": secret_calls,
        "mutations": mutations,
        "proposals": proposals,
        "proposal_clock": proposal_clock,
        "service": service,
    }


def _proposal_count(context: dict[str, Any]) -> int:
    return int(
        context["store"]
        .connect()
        .execute("SELECT COUNT(*) FROM agent_change_proposals")
        .fetchone()[0]
    )


def _business_dump(context: dict[str, Any]) -> tuple[list[tuple], ...]:
    conn = context["store"].connect()
    return tuple(
        [tuple(row) for row in conn.execute(f"SELECT * FROM {table} ORDER BY 1")]
        for table in (
            "source_catalog",
            "user_subscriptions",
            "user_source_schedules",
        )
    )


def _prepare_private(
    context: dict[str, Any],
    *,
    suffix: str,
    actor: DelegatedActor | None = None,
) -> dict[str, Any]:
    return context["service"].prepare_create_subscription(
        actor=actor or _actor(context, "member"),
        source={
            "mode": "private",
            "type": "rss",
            "display_name": f"Apply {suffix}",
            "config": {"url": f"https://example.com/{suffix}.xml"},
        },
        subscription={"priority": 17},
        schedule={"enabled": False, "interval_minutes": 60},
    )


_CREATE_UPDATE_RESULT_KEYS = {
    "action",
    "source_id",
    "subscription_id",
    "source_enabled",
    "subscription_enabled",
    "schedule_enabled",
    "schedule_interval_minutes",
}
_DELETE_RESULT_KEYS = {
    "action",
    "source_id",
    "subscription_id",
    "source_disabled",
}


def _assert_applied_summary_and_consumed(
    context: dict[str, Any],
    *,
    actor: DelegatedActor,
    prepared: dict[str, Any],
    applied: dict[str, Any],
    expected_result_keys: set[str],
) -> None:
    row = context["store"].get_agent_change_proposal(prepared["proposal_id"])
    assert row["status"] == "applied"
    assert applied == {
        "proposal_id": prepared["proposal_id"],
        "status": "applied",
        "result": row["result_summary"],
    }
    assert set(applied["result"]) == expected_result_keys

    with pytest.raises(AgentProposalError) as consumed:
        context["service"].apply_subscription_change(
            actor=actor,
            proposal_id=prepared["proposal_id"],
            confirmation_text=prepared["confirmation_text"],
        )
    assert consumed.value.code == "proposal_consumed"

def test_support_exports_subscription_fixture_and_actor_factory() -> None:
    assert callable(context)
    assert callable(_actor)


__all__ = [
    name
    for name in globals()
    if not name.startswith("__")
    and name != "test_support_exports_subscription_fixture_and_actor_factory"
]
