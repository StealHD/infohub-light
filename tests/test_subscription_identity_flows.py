"""Cross-user catalog identities exercised through REST and MCP services."""

import pytest

from src.services.agent_change_proposal import AgentProposalError
from tests.remote_mcp_subscription_routing_cases import CREATE_CASES
from tests.api_service_test_support import client as make_client, login
from tests.remote_mcp_subscription_service_test_support import _actor, context  # noqa: F401


def test_owner_can_create_shared_github_beside_another_private(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    store = client.app.state.service_store
    workspace = store.get_default_workspace()
    other = store.create_user(workspace_id=workspace["id"], username="other-admin",
                              password="test-password", role="admin")
    hidden_id = store.create_source(
        workspace_id=workspace["id"], scope="private", owner_user_id=other["id"],
        source_type="github_release", display_name="Hidden target",
        config={"owner": "openclaw", "repo": "openclaw"},
        source_key="github_release:openclaw/openclaw",
    )
    original = store.get_source(hidden_id)
    login(client)
    response = client.post("/api/catalog/sources", json={
        "type": "github_release", "display_name": "OpenClaw Releases",
        "config": {"owner": "openclaw", "repo": "openclaw", "fetch_limit": 1},
        "enabled": True,
    })
    assert response.status_code == 200, response.json()
    created = response.json()["data"]
    assert created["id"] != hidden_id
    assert created["scope"] == "public"
    assert store.get_source(hidden_id) == original
    visible = client.get("/api/catalog/sources").json()["data"]
    assert hidden_id not in repr(visible)


def _prepare(ctx, user):
    return ctx["service"].prepare_create_subscription(
        actor=_actor(ctx, user), source={
            "mode": "private", "type": "github", "display_name": "OpenClaw",
            "config": {"repository": "openclaw/openclaw"},
        }, subscription={}, schedule=None,
    )


def _apply(ctx, user, prepared):
    return ctx["service"].apply_subscription_change(
        actor=_actor(ctx, user), proposal_id=prepared["proposal_id"],
        confirmation_text=prepared["confirmation_text"],
    )["result"]


@pytest.mark.parametrize("other_applies_first", [True, False])
def test_private_proposals_do_not_collide_across_users(context, other_applies_first):
    first = _prepare(context, "member")
    second = _prepare(context, "other")
    order = [("other", second), ("member", first)] if other_applies_first else [
        ("member", first), ("other", second)]
    results = {user: _apply(context, user, proposal) for user, proposal in order}
    assert results["member"]["source_id"] != results["other"]["source_id"]
    for user, result in results.items():
        source = context["store"].get_source(result["source_id"])
        assert source["scope"] == "private"
        assert source["owner_user_id"] == context[user]["id"]
        assert len(context["store"].list_user_subscriptions(context[user]["id"])) == 1
    assert context["store"].connect().execute("SELECT COUNT(*) FROM fetch_jobs").fetchone()[0] == 0
    with pytest.raises(AgentProposalError) as collision:
        _prepare(context, "member")
    assert collision.value.code == "source_key_conflict"


def test_existing_private_does_not_block_other_users_prepare(context):
    other_result = _apply(context, "other", _prepare(context, "other"))
    original = context["store"].get_source(other_result["source_id"])
    member = _apply(context, "member", _prepare(context, "member"))
    assert member["source_id"] != other_result["source_id"]
    assert context["store"].get_source(other_result["source_id"]) == original


def test_missing_identity_migration_blocks_prepare_without_proposal(context):
    conn = context["store"].connect()
    conn.execute("DELETE FROM schema_migrations WHERE version=46")
    conn.commit()
    with pytest.raises(AgentProposalError) as error:
        _prepare(context, "member")
    assert error.value.code == "source_identity_migration_required"
    assert error.value.status_code == 503
    assert conn.execute("SELECT COUNT(*) FROM agent_change_proposals").fetchone()[0] == 0


def test_missing_identity_migration_http_is_explicit_and_reading_still_works(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    conn = client.app.state.service_store.connect()
    conn.execute("DELETE FROM schema_migrations WHERE version=46")
    conn.commit()
    login(client)
    for response in (
        client.get("/api/health/ready"),
        client.post("/api/catalog/sources", json={"type": "github_release",
            "display_name": "Public", "config": {"owner": "openclaw", "repo": "openclaw"}}),
    ):
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "source_identity_migration_required"
    assert client.get("/api/catalog/sources").status_code == 200
    assert conn.execute("SELECT COUNT(*) FROM source_catalog").fetchone()[0] == 0


def test_catalog_create_never_overwrites_existing_config(tmp_path, monkeypatch):
    client, _ = make_client(tmp_path, monkeypatch)
    login(client)
    payload = {"type": "github_release", "scope": "private", "display_name": "Original",
               "config": {"owner": "openclaw", "repo": "openclaw", "fetch_limit": 20}}
    first = client.post("/api/catalog/sources", json=payload)
    assert first.status_code == 200
    original = client.app.state.service_store.get_source(first.json()["data"]["id"])
    retry = client.post("/api/catalog/sources", json=payload | {"display_name": "Ignored rename"})
    assert retry.status_code == 200
    assert client.app.state.service_store.get_source(original["id"]) == original
    changed = payload | {"config": payload["config"] | {"fetch_limit": 1}}
    conflict = client.post("/api/catalog/sources", json=changed)
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "source_key_conflict"
    assert client.app.state.service_store.get_source(original["id"]) == original


@pytest.mark.parametrize("first_scope,second_scope", [("public", "workspace"), ("workspace", "public")])
def test_catalog_create_does_not_change_shared_scope(tmp_path, monkeypatch, first_scope, second_scope):
    client, _ = make_client(tmp_path, monkeypatch)
    login(client)
    payload = {"type": "github_release", "scope": first_scope, "display_name": "Original",
               "config": {"owner": "openclaw", "repo": "openclaw"}}
    first = client.post("/api/catalog/sources", json=payload)
    assert first.status_code == 200
    original = client.app.state.service_store.get_source(first.json()["data"]["id"])
    conflict = client.post("/api/catalog/sources", json=payload | {"scope": second_scope})
    assert conflict.status_code == 409
    assert conflict.json()["error"]["code"] == "source_key_conflict"
    assert client.app.state.service_store.get_source(original["id"]) == original


@pytest.mark.parametrize("source_type,config", [
    ("x_profile", {"target": "@OpenAI"}),
    ("instagram_profile", {"target": "@sooyaaa__"}),
    ("youtube_channel", {"url": "UCabcdefghijklmnopqrstuv"}),
])
def test_new_pending_source_can_subscribe_but_creation_retry_cannot_enable_it(
    tmp_path, monkeypatch, source_type, config,
):
    client, _ = make_client(tmp_path, monkeypatch)
    login(client)
    payload = {"type": source_type, "display_name": "Pending", "config": config}
    created = client.post("/api/catalog/sources", json=payload)
    assert created.status_code == 200
    source = created.json()["data"]
    assert source["enabled"] is False
    assert source["can_subscribe"] is True
    original = client.app.state.service_store.get_source(source["id"])
    retry = client.post("/api/catalog/sources", json=payload)
    assert retry.status_code == 200
    assert retry.json()["data"]["can_subscribe"] is False
    assert "_catalog_reused" not in retry.json()["data"]
    assert client.app.state.service_store.get_source(source["id"]) == original
    subscribed = client.post(f"/api/catalog/sources/{source['id']}/subscribe")
    assert subscribed.status_code == 200
    conn = client.app.state.service_store.connect()
    assert conn.execute("SELECT COUNT(*) FROM fetch_jobs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0


@pytest.mark.parametrize("source_type", CREATE_CASES)
@pytest.mark.parametrize("migrated", [False, True], ids=["fresh", "migrated"])
def test_all_self_service_types_keep_other_private_identity_isolated(context, source_type, migrated):
    from scripts.migrate_source_identity_v46 import migrate
    from src.storage import source_identity_schema as schema

    def prepare(user):
        return context["service"].prepare_create_subscription(
            actor=_actor(context, user), source={"mode": "private", "type": source_type,
                "display_name": "Audit target", "config": CREATE_CASES[source_type]},
            subscription={}, schedule=None,
        )

    store = context["store"]
    original_id = _apply(context, "other", prepare("other"))["source_id"]
    original = store.get_source(original_id)
    conn = store.connect()
    if migrated:
        for name in schema.INDEX_SQL:
            conn.execute(f"DROP INDEX {name}")
        for name in schema.TRIGGER_SQL:
            conn.execute(f"DROP TRIGGER {name}")
        conn.execute("DELETE FROM schema_migrations WHERE version=46")
        conn.execute(schema.LEGACY_SQL)
        conn.commit()
        assert migrate(store.data_dir, apply=True, services_stopped=True)["status"] == "applied"
    prepared = prepare("member")
    assert store.list_user_subscriptions(context["member"]["id"]) == []
    created = _apply(context, "member", prepared)
    assert created["source_id"] != original_id
    assert store.get_source(original_id) == original
    assert store.get_source(created["source_id"])["owner_user_id"] == context["member"]["id"]
    assert conn.execute("SELECT COUNT(*) FROM fetch_jobs").fetchone()[0] == 0
    assert conn.execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0
