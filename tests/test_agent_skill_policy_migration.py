"""Global 41 migration is explicit, backed up, repeatable, and defaults closed."""

import sqlite3
from pathlib import Path

from scripts.migrate_agent_skill_policy_v41 import migrate
from src.storage.service_store import ServiceStore


def test_global_41_preview_apply_and_repeat(tmp_path, monkeypatch):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "test-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    store.connect().execute("DROP TABLE agent_skill_policy_syncs")
    store.connect().execute("DROP TABLE workspace_agent_skill_policies")
    store.connect().execute("DELETE FROM schema_migrations WHERE version=41")
    store.connect().commit()
    store.close()
    assert migrate(tmp_path, apply=False)["status"] == "migration_required"
    result = migrate(tmp_path, apply=True)
    assert result["status"] == "applied" and result["integrity_check"] == "ok"
    assert Path(result["backup"]).stat().st_mode & 0o777 == 0o600
    connection = sqlite3.connect(tmp_path / "service.db")
    row = connection.execute(
        "SELECT revision,allowed_skill_keys_json,sync_state FROM workspace_agent_skill_policies"
    ).fetchone()
    assert row == (1, "[]", "pending")
    connection.close()
    assert migrate(tmp_path, apply=True)["status"] == "already_migrated"
