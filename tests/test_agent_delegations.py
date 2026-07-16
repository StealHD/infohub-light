import hashlib
import re
from datetime import datetime, timedelta, timezone
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.storage.service_store import AgentDelegationLimitError, ServiceStore


def test_agent_delegation_schema_and_marker_are_initialized(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")

    store = ServiceStore(tmp_path)
    store.initialize()
    store.initialize()

    columns = {
        row["name"]
        for row in store.connect().execute("PRAGMA table_info(agent_delegations)")
    }
    indexes = {
        row["name"]
        for row in store.connect().execute("PRAGMA index_list(agent_delegations)")
    }
    migration = store.connect().execute(
        "SELECT name, checksum FROM schema_migrations WHERE version = 6"
    ).fetchone()

    assert columns == {
        "id",
        "workspace_id",
        "user_id",
        "name",
        "client_type",
        "token_hash",
        "token_prefix",
        "scopes_json",
        "created_at",
        "expires_at",
        "last_used_at",
        "revoked_at",
        "revocation_reason",
        "updated_at",
    }
    assert "idx_agent_delegations_user_created" in indexes
    assert "idx_agent_delegations_workspace_user_status" in indexes
    assert migration["name"] == "agent_delegations_v6"
    assert migration["checksum"] == "agent-delegations-v6-remote-mcp"


def test_agent_delegation_secret_is_returned_once_and_only_its_hash_is_stored(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setattr(
        "src.storage.service_store._now_iso",
        lambda: "2026-07-16T00:00:00+00:00",
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    user = store.get_user_by_username("owner")

    delegation, token = store.create_agent_delegation(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        name="My Mac",
    )

    row = store.connect().execute(
        "SELECT * FROM agent_delegations WHERE id = ?", (delegation["id"],)
    ).fetchone()
    assert re.fullmatch(r"ih_mcp_v1_[A-Za-z0-9_-]{43}", token)
    assert row["token_hash"] == hashlib.sha256(token.encode()).hexdigest()
    assert row["token_prefix"] == token[:18]
    assert token not in tmp_path.joinpath("service.db").read_bytes().decode(
        "utf-8", errors="ignore"
    )
    assert delegation == {
        "id": row["id"],
        "name": "My Mac",
        "client_type": "openclaw",
        "scopes": ["inteliscope:read"],
        "token_prefix": token[:18],
        "created_at": "2026-07-16T00:00:00+00:00",
        "expires_at": "2026-10-14T00:00:00+00:00",
        "last_used_at": None,
        "revoked_at": None,
        "status": "active",
    }
    assert store.list_agent_delegations(user["id"]) == [delegation]


def test_agent_delegation_authentication_is_bounded_and_usage_touch_is_coalesced(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    clock = [datetime(2026, 7, 16, tzinfo=timezone.utc)]
    monkeypatch.setattr(
        "src.storage.service_store._now_iso", lambda: clock[0].isoformat()
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    user = store.get_user_by_username("owner")
    delegation, token = store.create_agent_delegation(
        workspace_id=user["workspace_id"], user_id=user["id"], name="Laptop"
    )

    principal = store.authenticate_agent_delegation(token)
    assert principal == {
        "delegation_id": delegation["id"],
        "workspace_id": user["workspace_id"],
        "user_id": user["id"],
        "role": "owner",
        "scopes": ["inteliscope:read"],
        "expires_at": delegation["expires_at"],
    }
    assert store.list_agent_delegations(user["id"])[0]["last_used_at"] == clock[
        0
    ].isoformat()

    clock[0] += timedelta(minutes=14)
    assert store.authenticate_agent_delegation(token) == principal
    assert store.list_agent_delegations(user["id"])[0]["last_used_at"] == (
        clock[0] - timedelta(minutes=14)
    ).isoformat()

    clock[0] += timedelta(minutes=1)
    assert store.authenticate_agent_delegation(token) == principal
    assert store.list_agent_delegations(user["id"])[0]["last_used_at"] == clock[
        0
    ].isoformat()
    assert store.authenticate_agent_delegation(f"{token}tampered") is None


def test_agent_delegations_are_self_scoped_renamable_and_permanently_revoked(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    viewer = store.create_user(
        workspace_id=workspace["id"],
        username="viewer",
        password="viewer-password",
        role="viewer",
    )
    delegation, token = store.create_agent_delegation(
        workspace_id=workspace["id"], user_id=viewer["id"], name="Viewer Mac"
    )

    assert store.rename_agent_delegation(
        viewer["id"], delegation["id"], "Viewer Desktop"
    )["name"] == "Viewer Desktop"
    assert store.rename_agent_delegation(owner["id"], delegation["id"], "Stolen") is None
    assert store.revoke_agent_delegation(owner["id"], delegation["id"]) is False
    assert store.revoke_agent_delegation(viewer["id"], delegation["id"]) is True
    assert store.revoke_agent_delegation(viewer["id"], delegation["id"]) is True
    assert store.authenticate_agent_delegation(token) is None
    assert store.list_agent_delegations(viewer["id"])[0]["status"] == "revoked"


def test_disabling_user_revokes_all_delegations_and_reenable_does_not_restore_them(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    user = store.get_user_by_username("owner")
    delegation, token = store.create_agent_delegation(
        workspace_id=user["workspace_id"], user_id=user["id"], name="Laptop"
    )

    store.update_user(user["id"], enabled=False)
    revoked = store.list_agent_delegations(user["id"])[0]
    assert revoked["id"] == delegation["id"]
    assert revoked["status"] == "revoked"
    assert store.connect().execute(
        "SELECT revocation_reason FROM agent_delegations WHERE id = ?",
        (delegation["id"],),
    ).fetchone()["revocation_reason"] == "user_disabled"
    assert store.authenticate_agent_delegation(token) is None

    store.update_user(user["id"], enabled=True)
    assert store.authenticate_agent_delegation(token) is None


def test_agent_delegation_active_limit_is_atomic_under_concurrency(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    user = store.get_user_by_username("owner")

    def create(index: int) -> bool:
        try:
            store.create_agent_delegation(
                workspace_id=user["workspace_id"],
                user_id=user["id"],
                name=f"Device {index}",
            )
        except AgentDelegationLimitError as exc:
            assert str(exc) == "agent delegation active limit reached"
            return False
        return True

    with ThreadPoolExecutor(max_workers=8) as executor:
        results = list(executor.map(create, range(8)))

    assert results.count(True) == 5
    assert results.count(False) == 3
    assert len(store.list_agent_delegations(user["id"])) == 5


def test_expired_agent_delegation_no_longer_authenticates_or_counts_toward_limit(
    tmp_path, monkeypatch
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    clock = [datetime(2026, 7, 16, tzinfo=timezone.utc)]
    monkeypatch.setattr(
        "src.storage.service_store._now_iso", lambda: clock[0].isoformat()
    )
    store = ServiceStore(tmp_path)
    store.initialize()
    user = store.get_user_by_username("owner")
    _, expired_token = store.create_agent_delegation(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        name="Expired",
        ttl_days=1,
        max_active=1,
    )

    clock[0] += timedelta(days=1)
    assert store.authenticate_agent_delegation(expired_token) is None
    replacement, _ = store.create_agent_delegation(
        workspace_id=user["workspace_id"],
        user_id=user["id"],
        name="Replacement",
        max_active=1,
    )
    assert replacement["status"] == "active"
