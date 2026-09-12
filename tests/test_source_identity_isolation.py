"""Catalog identity is scoped to an owner or the shared workspace."""
import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from src.storage.service_store import ServiceStore, SourceKeyConflictError


@pytest.fixture
def identity_store(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()["id"]
    users = [store.create_user(workspace_id=workspace, username=name,
             password="test-password", role="member") for name in ("alice", "bob")]
    yield store, workspace, [user["id"] for user in users]
    store.close()


def source(store, workspace, owner, *, scope="private", key="github_release:openclaw/openclaw", **kwargs):
    return store.upsert_source(workspace_id=workspace, scope=scope,
        owner_user_id=owner, source_type="github_release", display_name="OpenClaw",
        config={"owner": "openclaw", "repo": "openclaw"}, source_key=key, **kwargs)


def test_same_target_has_independent_private_and_shared_identities(identity_store):
    store, workspace, users = identity_store
    first = source(store, workspace, users[0])
    second = source(store, workspace, users[1])
    shared = source(store, workspace, None, scope="public")
    assert len({first["id"], second["id"], shared["id"]}) == 3
    assert store.get_source(first["id"]) == first
    assert store.get_source_by_key(workspace_id=workspace, source_key=first["source_key"],
        scope="private", owner_user_id=users[0])["id"] == first["id"]
    visible = store.get_visible_sources_by_key(store.get_user(users[0]), first["source_key"])
    assert {row["id"] for row in visible} == {first["id"], shared["id"]}


@pytest.mark.parametrize("owner", [None, "", "  "])
def test_private_owner_required(identity_store, owner):
    store, workspace, _ = identity_store
    with pytest.raises(ValueError, match="private source owner is required"):
        source(store, workspace, owner)


def test_same_identity_concurrent_upserts_reuse_one_id(identity_store):
    store, workspace, users = identity_store
    def write(_):
        try:
            return source(store, workspace, users[0])["id"]
        finally:
            store.close_current()
    with ThreadPoolExecutor(max_workers=4) as executor:
        ids = list(executor.map(write, range(8)))
    assert len(set(ids)) == 1


def test_share_collision_and_key_patch_are_atomic(identity_store):
    store, workspace, users = identity_store
    private = source(store, workspace, users[0])
    shared = source(store, workspace, None, scope="public")
    other = source(store, workspace, users[0], key="github_release:other/repo")
    with pytest.raises(SourceKeyConflictError):
        store.update_source(private["id"], scope="public")
    with pytest.raises(SourceKeyConflictError):
        store.update_source(other["id"], source_key=private["source_key"])
    assert [store.get_source(row["id"]) for row in (private, shared, other)] == [private, shared, other]


def test_owner_constraint_applies_to_direct_sql(identity_store):
    store, workspace, users = identity_store
    private = source(store, workspace, users[0])
    with pytest.raises(sqlite3.IntegrityError, match="private source owner is required"):
        store.connect().execute("UPDATE source_catalog SET owner_user_id=NULL WHERE id=?", (private["id"],))
    store.connect().rollback()


def test_disabled_source_remains_visible_by_identity(identity_store):
    store, workspace, users = identity_store
    disabled = source(store, workspace, users[0], enabled=False)
    hidden = source(store, workspace, users[1], enabled=False)
    visible = store.get_visible_sources_by_key(store.get_user(users[0]), disabled["source_key"])
    assert [(row["id"], row["enabled"]) for row in visible] == [(disabled["id"], False)]
    assert hidden["id"] not in {row["id"] for row in visible}


def test_delete_account_keeps_sanitized_tombstone_without_reassigning_owner(identity_store):
    store, workspace, users = identity_store
    original = source(store, workspace, users[0])
    owner = store.get_user_by_username("owner")
    assert store.delete_user(users[0], reassigned_user_id=owner["id"])
    tombstone = store.get_source(original["id"])
    assert tombstone["owner_user_id"] is None
    assert tombstone["scope"] == "private"
    assert tombstone["source_key"] is None and tombstone["enabled"] is False
    assert tombstone["config"] == {} and tombstone["secret_env"] is None
    assert store.get_visible_sources_by_key(owner, original["source_key"]) == []
    with pytest.raises(sqlite3.IntegrityError):
        store.connect().execute("UPDATE source_catalog SET enabled=1 WHERE id=?", (original["id"],))
    store.connect().rollback()


def test_direct_create_translates_private_identity_conflict(identity_store):
    store, workspace, users = identity_store
    original = source(store, workspace, users[0])
    with pytest.raises(SourceKeyConflictError):
        store.create_source(workspace_id=workspace, scope="private", owner_user_id=users[0],
            source_type="github_release", display_name="duplicate", config={}, source_key=original["source_key"])
    assert store.get_source(original["id"]) == original
