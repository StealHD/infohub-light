from __future__ import annotations

from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timedelta, timezone

import pytest

import src.storage.service_store as service_store


NOW = datetime(2026, 7, 17, 8, 0, tzinfo=timezone.utc)


@pytest.fixture
def proposal_clock(monkeypatch):
    clock = [NOW]
    monkeypatch.setattr(
        service_store,
        "_proposal_utc_now",
        lambda: clock[0],
        raising=False,
    )
    return clock


@pytest.fixture
def store(tmp_path, monkeypatch, proposal_clock):
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
        ({"source": {"config": {"apiKey": "plain-api-key"}}}, "plain-api-key"),
        ({"source": {"config": {"accessToken": "plain-token"}}}, "plain-token"),
        ({"source": {"config": {"clientSecret": "plain-secret"}}}, "plain-secret"),
        ({"source": {"config": {"ａｐｉＫｅｙ": "nfkc-secret"}}}, "nfkc-secret"),
        (
            {"source": {"url": "https://example.com/feed?accessToken=query-secret"}},
            "query-secret",
        ),
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


@pytest.mark.parametrize(
    "key",
    [
        "apikey",
        "APIKEY",
        "ａｐｉｋｅｙ",
        "ＡＰＩＫＥＹ",
        "accesskey",
        "ACCESSKEY",
        "ａｃｃｅｓｓｋｅｙ",
        "accesstoken",
        "ACCESSTOKEN",
        "ａｃｃｅｓｓｔｏｋｅｎ",
        "authtoken",
        "refreshtoken",
        "clientsecret",
        "clienttoken",
    ],
)
def test_proposal_payload_rejects_controlled_compact_credential_keys(
    store, delegation, key
):
    with pytest.raises(ValueError) as error:
        store.create_agent_change_proposal(
            **proposal_values(
                delegation,
                1,
                payload={"source": {"config": {key: "do-not-echo-compact-secret"}}},
            )
        )

    assert str(error.value) == "proposal data contains prohibited sensitive content"
    assert "do-not-echo-compact-secret" not in str(error.value)


@pytest.mark.parametrize(
    "key",
    [
        "githubtoken",
        "GITHUBTOKEN",
        "ｇｉｔｈｕｂｔｏｋｅｎ",
        "webhooksecret",
        "WEBHOOKSECRET",
        "ｗｅｂｈｏｏｋｓｅｃｒｅｔ",
    ],
)
def test_proposal_payload_rejects_compact_credential_suffix_keys(
    store, delegation, key
):
    with pytest.raises(ValueError) as error:
        store.create_agent_change_proposal(
            **proposal_values(
                delegation,
                1,
                payload={"source": {"config": {key: "do-not-echo-suffix-secret"}}},
            )
        )

    assert str(error.value) == "proposal data contains prohibited sensitive content"
    assert "do-not-echo-suffix-secret" not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/feed?apikey=do-not-echo-query-secret",
        "https://example.com/feed?APIKEY=do-not-echo-query-secret",
        "https://example.com/feed?%61%70%69%6b%65%79=do-not-echo-query-secret",
        "https://example.com/feed?%EF%BD%81%EF%BD%90%EF%BD%89%EF%BD%8B%EF%BD%85%EF%BD%99=do-not-echo-query-secret",
        "https://example.com/feed?clienttoken=do-not-echo-query-secret",
    ],
)
def test_proposal_payload_rejects_compact_and_percent_decoded_query_names(
    store, delegation, url
):
    with pytest.raises(ValueError) as error:
        store.create_agent_change_proposal(
            **proposal_values(
                delegation,
                1,
                payload={"source": {"config": {"url": url}}},
            )
        )

    assert str(error.value) == "proposal data contains prohibited sensitive content"
    assert "do-not-echo-query-secret" not in str(error.value)


@pytest.mark.parametrize(
    "url",
    [
        "https://example.com/feed?githubtoken=do-not-echo-query-secret",
        "https://example.com/feed?GITHUBTOKEN=do-not-echo-query-secret",
        "https://example.com/feed?%67%69%74%68%75%62%74%6f%6b%65%6e=do-not-echo-query-secret",
        "https://example.com/feed?webhooksecret=do-not-echo-query-secret",
    ],
)
def test_proposal_payload_rejects_compact_credential_suffix_query_names(
    store, delegation, url
):
    with pytest.raises(ValueError) as error:
        store.create_agent_change_proposal(
            **proposal_values(
                delegation,
                1,
                payload={"source": {"config": {"url": url}}},
            )
        )

    assert str(error.value) == "proposal data contains prohibited sensitive content"
    assert "do-not-echo-query-secret" not in str(error.value)


@pytest.mark.parametrize(
    "key",
    ["monkey", "hockey", "keyboard_layout", "keynote", "tokenizer", "tokenization"],
)
def test_proposal_payload_allows_safe_keys_containing_key_text(
    store, delegation, key
):
    values = proposal_values(
        delegation,
        1,
        payload={"source": {"config": {key: "safe-business-value"}}},
    )

    created = store.create_agent_change_proposal(**values)

    assert created["payload"] == values["payload"]


@pytest.mark.parametrize(
    "display_name",
    ["Basic Engineering News", "Bearer Market Report"],
)
def test_proposal_payload_allows_basic_and_bearer_business_names(
    store, delegation, display_name
):
    values = proposal_values(
        delegation,
        1,
        payload={"source": {"display_name": display_name}},
    )

    created = store.create_agent_change_proposal(**values)

    assert created["payload"] == values["payload"]


@pytest.mark.parametrize(
    "display_name",
    ["SK-Engineering Weekly", "sk-Engineering Weekly"],
)
def test_proposal_payload_allows_short_sk_business_names(store, delegation, display_name):
    values = proposal_values(
        delegation,
        1,
        payload={"source": {"display_name": display_name}},
    )

    created = store.create_agent_change_proposal(**values)

    assert created["payload"] == values["payload"]


@pytest.mark.parametrize(
    "text",
    [
        "Authorization: Basic dXNlcjpwYXNz",
        "Authorization: Bearer do-not-echo-header-secret",
        "Proxy-Authorization=Bearer do-not-echo-header-secret",
        "Cookie: session=do-not-echo-header-secret",
        "X-API-Key: do-not-echo-header-secret",
        "token=do-not-echo-header-secret",
        "sk-do-not-echo-prefix-secret",
        "sk-proj-abcdefghijklmnopqrstuvwxyz0123456789",
        "eyJhbGciOiJIUzI1NiJ9.eyJzdWIiOiIxMjM0NTY3ODkwIn0.do-not-echo-jwt-secret",
    ],
)
def test_proposal_payload_rejects_explicit_credential_contexts_and_secret_shapes(
    store, delegation, text
):
    with pytest.raises(ValueError) as error:
        store.create_agent_change_proposal(
            **proposal_values(
                delegation,
                1,
                payload={"source": {"notes": text}},
            )
        )

    assert str(error.value) == "proposal data contains prohibited sensitive content"
    assert "do-not-echo" not in str(error.value)


def test_proposal_ttl_is_exactly_ten_minutes(store, delegation):
    values = proposal_values(delegation, 1)
    values["expires_at"] = (NOW + timedelta(minutes=9, seconds=59)).isoformat()

    with pytest.raises(ValueError, match="proposal expiry must be exactly ten minutes"):
        store.create_agent_change_proposal(**values)


def test_proposal_persists_authoritative_now_and_fixed_ttl(store, delegation):
    caller_time = NOW - timedelta(days=30)

    created = store.create_agent_change_proposal(
        **proposal_values(delegation, 1, created_at=caller_time)
    )

    assert created["created_at"] == NOW.isoformat()
    assert created["expires_at"] == (NOW + timedelta(minutes=10)).isoformat()
    assert created["updated_at"] == NOW.isoformat()


def test_future_created_at_cannot_expire_pending_rows_or_bypass_limit(
    store, delegation
):
    for index in range(10):
        store.create_agent_change_proposal(
            **proposal_values(delegation, index)
        )

    with pytest.raises(
        service_store.AgentProposalLimitError,
        match="agent proposal pending limit reached",
    ):
        store.create_agent_change_proposal(
            **proposal_values(
                delegation,
                10,
                created_at=NOW + timedelta(days=365),
            )
        )

    assert store.connect().execute(
        "SELECT COUNT(*) FROM agent_change_proposals WHERE status = 'pending'"
    ).fetchone()[0] == 10


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
    store.create_agent_change_proposal(**proposal_values(delegation, 1))
    store.create_agent_change_proposal(**proposal_values(delegation, 2))
    store.create_agent_change_proposal(**proposal_values(other_delegation, 3))
    connection = store.connect()
    for proposal_id, timestamp in (
        ("agp_1", ancient),
        ("agp_2", recent),
        ("agp_3", ancient),
    ):
        connection.execute(
            """
            UPDATE agent_change_proposals
            SET created_at = ?, expires_at = ?, updated_at = ?
            WHERE id = ?
            """,
            (
                timestamp.isoformat(),
                (timestamp + timedelta(minutes=10)).isoformat(),
                timestamp.isoformat(),
                proposal_id,
            ),
        )
    connection.commit()

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


def test_backdated_applied_at_cannot_apply_a_really_expired_proposal(
    store, delegation, proposal_clock
):
    store.create_agent_change_proposal(**proposal_values(delegation, 1))
    proposal_clock[0] = NOW + timedelta(minutes=11)

    with pytest.raises(ValueError, match="proposal is not pending"):
        store.apply_agent_change_proposal(
            "agp_1",
            applied_at=(NOW + timedelta(minutes=1)).isoformat(),
            result_summary={},
        )

    assert store.get_agent_change_proposal("agp_1")["status"] == "pending"


def test_safe_business_identifier_keys_remain_allowed(store, delegation):
    values = proposal_values(
        delegation,
        1,
        payload={
            "source_id": "src_1",
            "subscription_id": "sub_1",
            "confirmation_hash": "sha256-public-proof",
        },
    )

    created = store.create_agent_change_proposal(**values)

    assert created["payload"] == values["payload"]


def test_proposal_cleanup_maintenance_deletes_only_old_consumed_rows(
    store, delegation
):
    old = NOW - timedelta(days=31, minutes=10)
    pending_old = NOW - timedelta(days=31)
    store.create_agent_change_proposal(**proposal_values(delegation, 1))
    store.apply_agent_change_proposal(
        "agp_1",
        applied_at=(old + timedelta(minutes=5)).isoformat(),
        result_summary={},
    )
    store.create_agent_change_proposal(**proposal_values(delegation, 2))
    connection = store.connect()
    connection.execute(
        """
        UPDATE agent_change_proposals
        SET created_at = ?, expires_at = ?, applied_at = ?, updated_at = ?
        WHERE id = 'agp_1'
        """,
        (
            old.isoformat(),
            (old + timedelta(minutes=10)).isoformat(),
            (old + timedelta(minutes=5)).isoformat(),
            (old + timedelta(minutes=5)).isoformat(),
        ),
    )
    connection.execute(
        """
        UPDATE agent_change_proposals
        SET created_at = ?, expires_at = ?, updated_at = ?
        WHERE id = 'agp_2'
        """,
        (
            pending_old.isoformat(),
            (NOW + timedelta(days=1)).isoformat(),
            pending_old.isoformat(),
        ),
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
