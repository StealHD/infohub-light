import sqlite3
from pathlib import Path

import pytest

from scripts.prepare_service_deployment import prepare_deployment_database
from src.services.job_queue import JobQueue
from src.storage.service_store import ServiceStore


def _source_database(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "secret-password")
    data_dir = tmp_path / "source"
    store = ServiceStore(data_dir)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    store.create_session(owner["id"], ttl_seconds=3600)
    delegation, _token = store.create_agent_delegation(
        workspace_id=workspace["id"], user_id=owner["id"], name="Local OpenClaw"
    )
    created_at = "2026-07-17T00:00:00+00:00"
    store.create_agent_change_proposal(
        proposal_id="agp-deployment",
        workspace_id=workspace["id"],
        user_id=owner["id"],
        delegation_id=delegation["id"],
        kind="create",
        source_id=None,
        subscription_id=None,
        payload={"source": {"type": "rss"}},
        preview={"action": "create"},
        fingerprints={},
        confirmation_hash="sha256-deployment",
        created_at=created_at,
        expires_at="2026-07-17T00:10:00+00:00",
    )
    store.upsert_worker_heartbeat("old-worker", "running")
    queue = JobQueue(store)
    queued = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="user_feed_refresh",
    )
    running = queue.create_job(
        workspace_id=workspace["id"],
        user_id=owner["id"],
        job_type="source_fetch",
    )
    claimed = queue.claim_next_job(worker_id="old-worker")
    assert claimed["id"] in {queued["id"], running["id"]}
    store.close()
    return data_dir / "service.db"


def test_prepare_deployment_database_sanitizes_copy_without_mutating_source(tmp_path, monkeypatch):
    source = _source_database(tmp_path, monkeypatch)
    target = tmp_path / "artifact" / "service.db"

    result = prepare_deployment_database(source=source, output=target)

    assert result["output"] == str(target)
    assert result["sessions_removed"] == 1
    assert result["agent_change_proposals_removed"] == 1
    assert result["agent_delegations_removed"] == 1
    assert result["heartbeats_removed"] == 1
    assert result["jobs_cancelled"] == 2
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_errors"] == 0
    assert target.stat().st_mode & 0o777 == 0o600
    assert not Path(str(target) + "-wal").exists()
    assert not Path(str(target) + "-shm").exists()

    source_db = sqlite3.connect(source)
    target_db = sqlite3.connect(target)
    try:
        assert source_db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 1
        assert source_db.execute(
            "SELECT COUNT(*) FROM agent_change_proposals"
        ).fetchone()[0] == 1
        assert source_db.execute(
            "SELECT COUNT(*) FROM agent_delegations"
        ).fetchone()[0] == 1
        assert source_db.execute("SELECT COUNT(*) FROM worker_heartbeats").fetchone()[0] == 1
        assert source_db.execute(
            "SELECT COUNT(*) FROM fetch_jobs WHERE status IN ('queued', 'running')"
        ).fetchone()[0] == 2

        assert target_db.execute("SELECT COUNT(*) FROM sessions").fetchone()[0] == 0
        assert target_db.execute(
            "SELECT COUNT(*) FROM agent_change_proposals"
        ).fetchone()[0] == 0
        assert target_db.execute(
            "SELECT COUNT(*) FROM agent_delegations"
        ).fetchone()[0] == 0
        assert target_db.execute("SELECT COUNT(*) FROM worker_heartbeats").fetchone()[0] == 0
        assert target_db.execute(
            "SELECT COUNT(*) FROM fetch_jobs WHERE status IN ('queued', 'running')"
        ).fetchone()[0] == 0
        cancelled = target_db.execute(
            "SELECT status, error_code, worker_id, claim_token, locked_until "
            "FROM fetch_jobs ORDER BY created_at"
        ).fetchall()
        assert all(row[0] == "cancelled" for row in cancelled)
        assert all(row[1] == "rc1_deployment" for row in cancelled)
        assert all(row[2:] == (None, None, None) for row in cancelled)
        assert target_db.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 2"
        ).fetchone()
    finally:
        source_db.close()
        target_db.close()


def test_prepare_deployment_database_refuses_overwrite_and_source_target_alias(tmp_path, monkeypatch):
    source = _source_database(tmp_path, monkeypatch)
    target = tmp_path / "service-deploy.db"
    target.write_bytes(b"occupied")

    with pytest.raises(FileExistsError):
        prepare_deployment_database(source=source, output=target)

    with pytest.raises(ValueError):
        prepare_deployment_database(source=source, output=source)


def test_prepare_deployment_database_supports_pre_v7_database(tmp_path, monkeypatch):
    source = _source_database(tmp_path, monkeypatch)
    connection = sqlite3.connect(source)
    try:
        connection.execute("DROP TABLE agent_change_proposals")
        connection.execute("DELETE FROM schema_migrations WHERE version = 7")
        connection.commit()
    finally:
        connection.close()
    target = tmp_path / "pre-v7-service.db"

    result = prepare_deployment_database(source=source, output=target)

    assert result["agent_change_proposals_removed"] == 0
    deployed = sqlite3.connect(target)
    try:
        assert deployed.execute(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'agent_change_proposals'"
        ).fetchone() is None
        assert deployed.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        deployed.close()
