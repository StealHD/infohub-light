from __future__ import annotations

import hashlib
import json
from datetime import datetime, timedelta, timezone
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

from src.api.server import create_app
from src.services.storage_governance import (
    StorageGovernanceError,
    StorageGovernanceService,
)
from src.services.user_content_store import UserContentStore
from src.services.user_item_state import UserItemStateStore
from src.storage.service_store import ServiceStore


def _store(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    return store, workspace, owner


def _old_item(article_id: str, published_at: str) -> dict:
    return {
        "id": article_id,
        "title": f"Archived {article_id}",
        "source": "Archive Source",
        "published_at": published_at,
        "summary_zh": "保留的摘要",
        "presentation": {
            "content": {
                "title": f"Archived {article_id}",
                "excerpt": "保留的摘要",
                "body_text": f"完整正文 {article_id}",
                "body_truncated": False,
                "body_completeness": "captured",
            }
        },
    }


def _seed_media(
    store: ServiceStore,
    *,
    workspace_id: str,
    user_id: str,
    article_id: str,
    created_at: str,
) -> tuple[str, Path]:
    data = f"media:{article_id}".encode()
    checksum = hashlib.sha256(data).hexdigest()
    relative_path = f"media/{article_id}.bin"
    path = Path(store.data_dir) / relative_path
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)
    media_id = f"media-{article_id}"
    store.connect().execute(
        """
        INSERT INTO media_assets (
            id, workspace_id, user_id, article_id, asset_kind, remote_url,
            local_path, mime_type, byte_size, checksum, alt, visibility_scope,
            status, created_at, updated_at
        ) VALUES (?, ?, ?, ?, 'content_image', '', ?, 'application/octet-stream',
                  ?, ?, '', 'private', 'ready', ?, ?)
        """,
        (
            media_id,
            workspace_id,
            user_id,
            article_id,
            relative_path,
            len(data),
            checksum,
            created_at,
            created_at,
        ),
    )
    store.connect().commit()
    return media_id, path


def test_archive_is_preview_first_protects_user_state_and_restores_idempotently(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    old = (now - timedelta(days=100)).isoformat()
    content = UserContentStore(store)
    content.upsert_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[
            _old_item("cold-item", old),
            _old_item("saved-item", old),
            _old_item("later-item", old),
        ],
        seen_at=old,
    )
    states = UserItemStateStore(store)
    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="saved-item",
        is_saved=True,
    )
    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="later-item",
        is_later=True,
    )
    media_id, media_path = _seed_media(
        store,
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="cold-item",
        created_at=old,
    )
    service = StorageGovernanceService(store)

    plan = service.create_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        operation="archive",
        now=now,
    )
    assert plan["payload"]["preview"] == {
        "item_count": 1,
        "media_count": 1,
        "cutoff_at": (now - timedelta(days=90)).isoformat(),
        "protected_items_excluded": True,
    }

    # A protection change invalidates the preview and must leave all online data intact.
    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="cold-item",
        is_saved=True,
    )
    with pytest.raises(StorageGovernanceError, match="candidates changed"):
        service.apply_plan(
            workspace_id=workspace["id"],
            actor_user_id=owner["id"],
            actor_role="owner",
            plan_id=plan["id"],
            now=now + timedelta(minutes=1),
        )
    assert media_path.exists()
    assert store.connect().execute(
        "SELECT archived_at FROM user_content_items WHERE article_id = 'cold-item'"
    ).fetchone()["archived_at"] is None

    states.update_state(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        article_id="cold-item",
        is_saved=False,
    )
    plan = service.create_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        operation="archive",
        now=now,
    )
    applied = service.apply_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        plan_id=plan["id"],
        now=now + timedelta(minutes=1),
    )
    batch_id = applied["result"]["batch_id"]
    cold = store.connect().execute(
        """
        SELECT body_text, archived_at, item_json
        FROM user_content_items WHERE article_id = 'cold-item'
        """
    ).fetchone()
    assert cold["body_text"] == ""
    assert cold["archived_at"]
    assert json.loads(cold["item_json"])["summary_zh"] == "保留的摘要"
    assert store.connect().execute(
        "SELECT 1 FROM user_content_items WHERE article_id = 'saved-item'"
    ).fetchone()
    assert store.connect().execute(
        "SELECT 1 FROM media_assets WHERE id = ?", (media_id,)
    ).fetchone() is None
    assert not media_path.exists()

    restore = service.create_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        operation="restore",
        payload={"batch_id": batch_id},
        now=now + timedelta(minutes=2),
    )
    restored = service.apply_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        plan_id=restore["id"],
        now=now + timedelta(minutes=3),
    )
    assert restored["result"]["item_count"] == 1
    assert restored["result"]["media_count"] == 1
    assert media_path.exists()
    assert store.connect().execute(
        "SELECT body_text FROM user_content_items WHERE article_id = 'cold-item'"
    ).fetchone()["body_text"] == "完整正文 cold-item"
    assert service.apply_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        plan_id=restore["id"],
        now=now + timedelta(minutes=4),
    )["status"] == "applied"


def test_permanent_archive_delete_is_owner_only_and_requires_exact_confirmation(
    tmp_path,
    monkeypatch,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    admin = store.create_user(
        workspace_id=workspace["id"],
        username="storage-admin",
        password="admin-password",
        role="admin",
    )
    now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    old = (now - timedelta(days=100)).isoformat()
    UserContentStore(store).upsert_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[_old_item("delete-item", old)],
        seen_at=old,
    )
    service = StorageGovernanceService(store)
    archive_plan = service.create_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        operation="archive",
        now=now,
    )
    batch_id = service.apply_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        plan_id=archive_plan["id"],
        now=now + timedelta(minutes=1),
    )["result"]["batch_id"]
    restore_plan = service.create_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        operation="restore",
        payload={"batch_id": batch_id},
        now=now + timedelta(minutes=2),
    )
    service.apply_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        plan_id=restore_plan["id"],
        now=now + timedelta(minutes=3),
    )

    with pytest.raises(StorageGovernanceError, match="owner role required"):
        service.create_plan(
            workspace_id=workspace["id"],
            actor_user_id=admin["id"],
            actor_role="admin",
            operation="delete_archive",
            payload={"batch_id": batch_id},
            now=now + timedelta(minutes=4),
        )
    delete_plan = service.create_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        operation="delete_archive",
        payload={"batch_id": batch_id},
        now=now + timedelta(minutes=4),
    )
    with pytest.raises(StorageGovernanceError, match="confirmation must equal"):
        service.apply_plan(
            workspace_id=workspace["id"],
            actor_user_id=owner["id"],
            actor_role="owner",
            plan_id=delete_plan["id"],
            confirmation="确认",
            now=now + timedelta(minutes=5),
        )
    archive_row = store.connect().execute(
        "SELECT status, archive_path FROM storage_archive_batches WHERE id = ?",
        (batch_id,),
    ).fetchone()
    assert archive_row["status"] == "restored"
    assert (Path(store.data_dir) / archive_row["archive_path"]).exists()

    result = service.apply_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        plan_id=delete_plan["id"],
        confirmation=f"永久删除归档 {batch_id}",
        now=now + timedelta(minutes=5),
    )
    assert result["result"]["operation"] == "delete_archive"
    assert store.connect().execute(
        "SELECT status FROM storage_archive_batches WHERE id = ?",
        (batch_id,),
    ).fetchone()["status"] == "deleted"


def test_cleanup_plan_never_deletes_stable_content(tmp_path, monkeypatch):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    now = datetime(2026, 7, 27, 12, 0, tzinfo=timezone.utc)
    old = (now - timedelta(days=400)).isoformat()
    UserContentStore(store).upsert_items(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        items=[_old_item("retained-item", old)],
        seen_at=old,
    )
    service = StorageGovernanceService(store)
    plan = service.create_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        operation="cleanup",
        now=now,
    )
    assert plan["payload"]["preview"]["permanent_content_deletes"] == 0
    applied = service.apply_plan(
        workspace_id=workspace["id"],
        actor_user_id=owner["id"],
        actor_role="owner",
        plan_id=plan["id"],
        now=now + timedelta(minutes=1),
    )
    assert applied["result"]["content_items"] == 0
    assert store.connect().execute(
        "SELECT 1 FROM user_content_items WHERE article_id = 'retained-item'"
    ).fetchone()


@pytest.mark.parametrize(
    ("operation", "payload"),
    [
        ("cleanup", {"days": 1}),
        ("archive", {"cutoff_at": "2026-01-01T00:00:00+00:00"}),
        ("restore", {}),
        ("restore", {"batch_id": 1}),
        ("delete_archive", {"batch_id": "batch", "extra": True}),
    ],
)
def test_storage_plan_rejects_unrecognized_or_unsafe_payloads(
    tmp_path,
    monkeypatch,
    operation,
    payload,
):
    store, workspace, owner = _store(tmp_path, monkeypatch)
    with pytest.raises(StorageGovernanceError, match="does not accept|requires only"):
        StorageGovernanceService(store).create_plan(
            workspace_id=workspace["id"],
            actor_user_id=owner["id"],
            actor_role="owner",
            operation=operation,
            payload=payload,
        )


def test_storage_admin_api_requires_admin_and_supports_preview_apply(
    tmp_path,
    monkeypatch,
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    monkeypatch.setenv("HORIZON_AUTH_SESSION_SECRET", "test-session-secret")
    data_dir = tmp_path / "data"
    static_dir = tmp_path / "static"
    data_dir.mkdir()
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    (data_dir / "config.json").write_text(
        json.dumps(
            {
                "version": "1.0",
                "ai": {
                    "enabled": False,
                    "provider": "openai",
                    "model": "test",
                    "api_key_env": "OPENAI_API_KEY",
                },
                "tags": [],
                "personal_tags": [],
                "sources": {
                    "rss": [],
                    "github": [],
                    "hackernews": {"enabled": False},
                },
                "filtering": {"time_window_hours": 24},
            }
        ),
        encoding="utf-8",
    )
    with TestClient(create_app(data_dir=data_dir, static_dir=static_dir)) as client:
        assert client.get("/api/admin/storage/summary").status_code == 401
        login = client.post(
            "/api/auth/login",
            json={"username": "owner", "password": "secret-password"},
        )
        assert login.status_code == 200
        member = client.post(
            "/api/users",
            json={
                "username": "storage-member",
                "password": "member-password",
                "role": "member",
            },
        )
        assert member.status_code == 200
        assert client.get("/api/admin/storage/summary").status_code == 200
        plan = client.post(
            "/api/admin/storage/plans",
            json={"operation": "cleanup", "payload": {}},
        )
        assert plan.status_code == 200
        plan_id = plan.json()["data"]["id"]
        applied = client.post(
            f"/api/admin/storage/plans/{plan_id}/apply",
            json={"confirmation": ""},
        )
        assert applied.status_code == 200
        assert applied.json()["data"]["status"] == "applied"
        client.post("/api/auth/logout")
        assert client.post(
            "/api/auth/login",
            json={
                "username": "storage-member",
                "password": "member-password",
            },
        ).status_code == 200
        denied = client.get("/api/admin/storage/summary")
        assert denied.status_code == 403
        assert denied.json()["error"]["code"] == "forbidden"
