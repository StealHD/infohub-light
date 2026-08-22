from __future__ import annotations

from scripts.migrate_apify_actor_ops_v15 import migrate_apify_actor_ops_v15
from scripts.migrate_apify_discovery_limits_v16 import migrate
from src.storage.service_store import ServiceStore
from tests.actorops_v1_migration_fixture import initialize_historical_actorops
from tests.test_migrate_apify_actor_ops_v15 import _downgrade_to_v14


def test_v16_offline_migration_adds_safe_measurement_columns(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _downgrade_to_v14(data_dir)
    pre_v15 = ServiceStore(data_dir)
    pre_v15.connect().execute("DELETE FROM schema_migrations WHERE version = 18")
    pre_v15.connect().commit()
    pre_v15.close()
    migrate_apify_actor_ops_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "v15-backups",
        apply=True,
    )
    before = ServiceStore(data_dir)
    before.initialize()
    assert before.apify_discovery_limits_v16_migration_required() is True
    before.close()

    result = migrate(
        data_dir,
        apply=True,
        backup_dir=tmp_path / "v16-backups",
    )

    assert result["applied"] is True
    assert result["backup_mode"] == "0o600"
    store = ServiceStore(data_dir)
    store.initialize()
    assert store.apify_discovery_limits_v16_migration_required() is False
    settings = store.connect().execute(
        "SELECT max_output_tokens FROM apify_actor_discovery_settings"
    ).fetchone()
    assert settings["max_output_tokens"] == 4096
    run_columns = {
        row["name"]
        for row in store.connect().execute(
            "PRAGMA table_info(apify_actor_discovery_runs)"
        ).fetchall()
    }
    assert {
        "measurement_mode",
        "ai_max_output_tokens",
        "ai_completion_tokens",
        "ai_reasoning_tokens",
        "ai_finish_reason",
        "ai_latency_ms",
        "ai_response_bytes",
        "ai_json_status",
        "ai_manifest_status",
    } <= run_columns
    assert store.connect().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.connect().execute("PRAGMA foreign_key_check").fetchall() == []
    store.close()


def test_v16_migration_refuses_active_actor_ops_job(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _downgrade_to_v14(data_dir)
    pre_v15 = ServiceStore(data_dir)
    pre_v15.connect().execute("DELETE FROM schema_migrations WHERE version = 18")
    pre_v15.connect().commit()
    pre_v15.close()
    migrate_apify_actor_ops_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "v15-backups",
        apply=True,
    )
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.create_user(
        workspace_id="default",
        username="v16-owner",
        password="safe-test-password",
        role="owner",
    )
    store.connect().execute(
        """
        INSERT INTO fetch_jobs (
            id, workspace_id, user_id, job_type, status, payload_json,
            priority, attempts, max_attempts, created_at, updated_at
        ) VALUES (
            'active-v16-test', 'default', ?, 'apify_actor_discovery',
            'queued', '{"run_id":"test"}', 1, 0, 1,
            '2026-08-01T00:00:00+00:00', '2026-08-01T00:00:00+00:00'
        )
        """,
        (owner["id"],),
    )
    store.connect().commit()
    store.close()

    import pytest

    with pytest.raises(RuntimeError, match="active discovery/canary jobs"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "v16-backups")
    assert not (tmp_path / "v16-backups").exists()
