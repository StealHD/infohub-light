from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

import src.storage.service_store as service_store


NOW = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def store(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    instance = service_store.ServiceStore(tmp_path)
    instance.initialize()
    return instance


@pytest.fixture
def delegation(store):
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    row, _token = store.create_agent_delegation(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        name="Proposal tests",
    )
    return {
        "id": row["id"],
        "workspace_id": workspace["id"],
        "user_id": owner["id"],
    }


def proposal_values(
    delegation,
    index: int,
    *,
    created_at: datetime = NOW,
    payload=None,
):
    return {
        "proposal_id": f"agp_{index}",
        "workspace_id": delegation["workspace_id"],
        "user_id": delegation["user_id"],
        "delegation_id": delegation["id"],
        "kind": "create",
        "source_id": None,
        "subscription_id": None,
        "payload": payload
        if payload is not None
        else {
            "source": {
                "type": "rss",
                "config": {"url": f"https://example.com/{index}.xml"},
            }
        },
        "preview": {"action": "create", "source_name": f"RSS {index}"},
        "fingerprints": {"source_updated_at": None},
        "confirmation_hash": f"sha256-{index}",
        "created_at": created_at.isoformat(),
        "expires_at": (created_at + timedelta(minutes=10)).isoformat(),
    }


def test_agent_change_proposal_schema_v7_is_idempotent(store):
    store.initialize()
    store.initialize()

    connection = store.connect()
    columns = {
        row["name"]
        for row in connection.execute("PRAGMA table_info(agent_change_proposals)")
    }
    indexes = {
        row["name"]
        for row in connection.execute("PRAGMA index_list(agent_change_proposals)")
    }
    foreign_keys = {
        (row["from"], row["table"], row["to"], row["on_delete"])
        for row in connection.execute(
            "PRAGMA foreign_key_list(agent_change_proposals)"
        )
    }
    marker = connection.execute(
        "SELECT name, checksum FROM schema_migrations WHERE version = 7"
    ).fetchone()

    assert columns == {
        "id",
        "workspace_id",
        "user_id",
        "delegation_id",
        "kind",
        "source_id",
        "subscription_id",
        "payload_json",
        "preview_json",
        "fingerprints_json",
        "confirmation_hash",
        "status",
        "created_at",
        "expires_at",
        "applied_at",
        "result_summary_json",
        "updated_at",
    }
    assert indexes >= {
        "idx_agent_change_proposals_delegation_status_expires",
        "idx_agent_change_proposals_status_updated",
    }
    assert foreign_keys == {
        ("workspace_id", "workspaces", "id", "CASCADE"),
        ("user_id", "users", "id", "CASCADE"),
        ("delegation_id", "agent_delegations", "id", "CASCADE"),
    }
    assert marker["name"] == "agent_change_proposals_v7"
    assert marker["checksum"] == "agent-change-proposals-v7"


def test_proposal_projection_parses_json_without_exposing_raw_columns(
    store, delegation
):
    created = store.create_agent_change_proposal(**proposal_values(delegation, 1))
    fetched = store.get_agent_change_proposal(created["id"])

    assert fetched == created
    assert created["payload"]["source"]["type"] == "rss"
    assert created["preview"] == {"action": "create", "source_name": "RSS 1"}
    assert created["fingerprints"] == {"source_updated_at": None}
    assert created["result_summary"] is None
    assert not any(key.endswith("_json") for key in created)


@pytest.mark.parametrize(
    "payload,secret",
    [
        ({"source": {"config": {"secret_env": "RSS_TOKEN"}}}, "RSS_TOKEN"),
        ({"request": {"headers": {"Authorization": "Bearer hidden"}}}, "hidden"),
        ({"source": {"url": "https://example.com/feed?api_key=hidden"}}, "hidden"),
        ({"notes": ["Authorization: Basic dXNlcjpwYXNz"]}, "dXNlcjpwYXNz"),
        ({"job": {"payload": {"target": "private-body"}}}, "private-body"),
        ({"source": {"config": {"opaque": b"Bearer hidden-bytes"}}}, "hidden-bytes"),
    ],
)
def test_proposal_payload_rejects_sensitive_shapes_without_echoing_values(
    store, delegation, payload, secret
):
    with pytest.raises(ValueError) as error:
        store.create_agent_change_proposal(
            **proposal_values(delegation, 1, payload=payload)
        )

    assert str(error.value) == "proposal data contains prohibited sensitive content"
    assert secret not in str(error.value)
    assert store.connect().execute(
        "SELECT COUNT(*) FROM agent_change_proposals"
    ).fetchone()[0] == 0


def test_proposal_ttl_is_exactly_ten_minutes(store, delegation):
    values = proposal_values(delegation, 1)
    values["expires_at"] = (NOW + timedelta(minutes=9, seconds=59)).isoformat()

    with pytest.raises(ValueError, match="proposal expiry must be exactly ten minutes"):
        store.create_agent_change_proposal(**values)


def test_proposal_pending_limit_is_atomic_under_concurrency(store, delegation):
    def create(index: int) -> bool:
        try:
            store.create_agent_change_proposal(**proposal_values(delegation, index))
        except service_store.AgentProposalLimitError as error:
            assert str(error) == "agent proposal pending limit reached"
            return False
        return True

    with ThreadPoolExecutor(max_workers=12) as executor:
        results = list(executor.map(create, range(12)))

    assert results.count(True) == 10
    assert results.count(False) == 2
    assert store.connect().execute(
        "SELECT COUNT(*) FROM agent_change_proposals WHERE status = 'pending'"
    ).fetchone()[0] == 10


def test_create_expires_elapsed_rows_and_only_prunes_old_rows_for_same_delegation(
    store, delegation
):
    other, _token = store.create_agent_delegation(
        workspace_id=delegation["workspace_id"],
        user_id=delegation["user_id"],
        name="Other delegation",
    )
    other_delegation = {**delegation, "id": other["id"]}
    ancient = NOW - timedelta(days=2)
    recent = NOW - timedelta(minutes=11)
    store.create_agent_change_proposal(
        **proposal_values(delegation, 1, created_at=ancient)
    )
    store.create_agent_change_proposal(
        **proposal_values(delegation, 2, created_at=recent)
    )
    store.create_agent_change_proposal(
        **proposal_values(other_delegation, 3, created_at=ancient)
    )

    created = store.create_agent_change_proposal(
        **proposal_values(delegation, 4, created_at=NOW)
    )

    assert created["status"] == "pending"
    assert store.get_agent_change_proposal("agp_1") is None
    assert store.get_agent_change_proposal("agp_2")["status"] == "expired"
    assert store.get_agent_change_proposal("agp_3")["status"] == "pending"


def test_proposal_status_changes_are_legal_and_respect_transaction_ownership(
    store, delegation
):
    connection = store.connect()
    store.create_agent_change_proposal(**proposal_values(delegation, 1))

    connection.execute("BEGIN IMMEDIATE")
    applied = store.apply_agent_change_proposal(
        "agp_1",
        applied_at=(NOW + timedelta(minutes=1)).isoformat(),
        result_summary={"subscription_id": "sub_1"},
        commit=False,
    )
    assert connection.in_transaction is True
    assert applied["status"] == "applied"
    assert applied["result_summary"] == {"subscription_id": "sub_1"}
    connection.rollback()
    assert store.get_agent_change_proposal("agp_1")["status"] == "pending"

    expired = store.expire_agent_change_proposal(
        "agp_1", now=(NOW + timedelta(minutes=10)).isoformat()
    )
    assert expired["status"] == "expired"
    assert store.expire_agent_change_proposal(
        "agp_1", now=(NOW + timedelta(minutes=11)).isoformat()
    ) == expired
    with pytest.raises(ValueError, match="proposal is not pending"):
        store.apply_agent_change_proposal(
            "agp_1",
            applied_at=(NOW + timedelta(minutes=11)).isoformat(),
            result_summary={},
        )


def test_proposal_cleanup_maintenance_deletes_only_old_consumed_rows(
    store, delegation
):
    old = NOW - timedelta(days=31, minutes=10)
    pending_old = NOW - timedelta(days=31)
    store.create_agent_change_proposal(
        **proposal_values(delegation, 1, created_at=old)
    )
    store.apply_agent_change_proposal(
        "agp_1",
        applied_at=(old + timedelta(minutes=5)).isoformat(),
        result_summary={},
    )
    store.create_agent_change_proposal(
        **proposal_values(delegation, 2, created_at=pending_old)
    )
    connection = store.connect()
    connection.execute(
        "UPDATE agent_change_proposals SET expires_at = ? WHERE id = 'agp_2'",
        ((NOW + timedelta(days=1)).isoformat(),),
    )
    connection.commit()

    result = store.cleanup_agent_change_proposals(
        now=NOW.isoformat(), maintenance=True
    )

    assert result == {"expired": 0, "deleted": 1}
    assert store.get_agent_change_proposal("agp_1") is None
    assert store.get_agent_change_proposal("agp_2")["status"] == "pending"


def test_create_source_commit_false_and_conflict_error_preserve_outer_transaction(
    store, delegation
):
    connection = store.connect()
    connection.execute("BEGIN IMMEDIATE")
    source_id = store.create_source(
        workspace_id=delegation["workspace_id"],
        scope="private",
        owner_user_id=delegation["user_id"],
        source_type="rss",
        display_name="Transactional RSS",
        config={"url": "https://example.com/transactional.xml"},
        source_key="rss:https://example.com/transactional.xml",
        commit=False,
    )
    assert connection.in_transaction is True
    connection.rollback()
    assert store.get_source(source_id) is None

    store.create_source(
        workspace_id=delegation["workspace_id"],
        scope="private",
        owner_user_id=delegation["user_id"],
        source_type="rss",
        display_name="First RSS",
        config={"url": "https://example.com/first.xml"},
        source_key="rss:duplicate",
    )
    with pytest.raises(service_store.SourceKeyConflictError) as error:
        store.create_source(
            workspace_id=delegation["workspace_id"],
            scope="private",
            owner_user_id=delegation["user_id"],
            source_type="rss",
            display_name="Duplicate RSS",
            config={"url": "https://example.com/duplicate.xml"},
            source_key="rss:duplicate",
        )
    assert error.value.source_key == "rss:duplicate"
