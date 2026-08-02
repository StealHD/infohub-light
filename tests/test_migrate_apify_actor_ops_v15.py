from __future__ import annotations

import hashlib
import json
import os
import sqlite3

import pytest

import scripts.migrate_apify_actor_ops_v15 as migration_module
from scripts.migrate_apify_actor_ops_v15 import (
    V15_TABLES,
    V15_TRIGGERS,
    migrate_apify_actor_ops_v15,
)
from src.storage.service_store import (
    APIFY_ACTOR_OPS_MIGRATION_CHECKSUM,
    APIFY_ACTOR_OPS_MIGRATION_NAME,
    APIFY_ACTOR_OPS_MIGRATION_VERSION,
    DEFAULT_WORKSPACE_ID,
    ServiceStore,
)


_ATTEMPT_V13_DDL = """
    CREATE TABLE apify_actor_attempts_v13 (
        id TEXT PRIMARY KEY,
        workspace_id TEXT NOT NULL,
        route_key TEXT NOT NULL,
        route_generation INTEGER NOT NULL CHECK(route_generation >= 1),
        candidate_id TEXT NOT NULL,
        source_id TEXT,
        job_id TEXT,
        attempt_group_id TEXT NOT NULL,
        attempt_index INTEGER NOT NULL CHECK(attempt_index BETWEEN 1 AND 3),
        status TEXT NOT NULL CHECK(status IN (
            'reserved', 'running', 'succeeded', 'valid_empty',
            'actor_failed', 'target_failed',
            'start_outcome_unknown', 'cancelled'
        )),
        semantic_outcome TEXT,
        reserved_usd REAL NOT NULL DEFAULT 0.02
            CHECK(reserved_usd >= 0 AND reserved_usd <= 0.02),
        actual_cost_usd REAL
            CHECK(actual_cost_usd IS NULL OR actual_cost_usd >= 0),
        cost_final INTEGER NOT NULL DEFAULT 0 CHECK(cost_final IN (0, 1)),
        last_error_code TEXT,
        created_at TEXT NOT NULL,
        started_at TEXT,
        terminal_at TEXT,
        updated_at TEXT NOT NULL,
        FOREIGN KEY(workspace_id, route_key)
            REFERENCES apify_actor_routes(workspace_id, route_key)
            ON DELETE CASCADE,
        FOREIGN KEY(candidate_id)
            REFERENCES apify_actor_candidates(id) ON DELETE RESTRICT,
        FOREIGN KEY(source_id)
            REFERENCES source_catalog(id) ON DELETE SET NULL,
        FOREIGN KEY(job_id)
            REFERENCES fetch_jobs(id) ON DELETE SET NULL
    )
"""
_ATTEMPT_V13_COLUMNS = (
    "id",
    "workspace_id",
    "route_key",
    "route_generation",
    "candidate_id",
    "source_id",
    "job_id",
    "attempt_group_id",
    "attempt_index",
    "status",
    "semantic_outcome",
    "reserved_usd",
    "actual_cost_usd",
    "cost_final",
    "last_error_code",
    "created_at",
    "started_at",
    "terminal_at",
    "updated_at",
)


def _downgrade_to_v14(data_dir) -> None:
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    for trigger in V15_TRIGGERS:
        connection.execute(f"DROP TRIGGER IF EXISTS {trigger}")
    # The current fresh-schema fixture includes all later migrations. A true
    # v14 snapshot cannot contain v17 batch tables that reference v15 rows.
    connection.execute("DROP TABLE IF EXISTS apify_actor_canary_batch_items")
    connection.execute("DROP TABLE IF EXISTS apify_actor_canary_batches")
    connection.execute("DROP TABLE apify_actor_validations")
    connection.execute("DROP TABLE apify_actor_discovery_run_revisions")
    connection.execute("DROP TABLE apify_route_active_slots")
    connection.execute("DROP TABLE apify_source_route_bindings")
    connection.execute("DROP TABLE apify_actor_discovery_runs")
    connection.execute("DROP TABLE apify_actor_discovery_settings")
    connection.execute("DROP TABLE apify_actor_metadata_observations")
    connection.execute(_ATTEMPT_V13_DDL)
    selected = ", ".join(_ATTEMPT_V13_COLUMNS)
    connection.execute(
        f"""
        INSERT INTO apify_actor_attempts_v13 ({selected})
        SELECT {selected} FROM apify_actor_attempts
        """
    )
    connection.execute("DROP TABLE apify_actor_attempts")
    connection.execute(
        "ALTER TABLE apify_actor_attempts_v13 RENAME TO apify_actor_attempts"
    )
    connection.execute(
        """
        CREATE INDEX idx_apify_actor_attempts_group
            ON apify_actor_attempts(
                workspace_id, route_key, attempt_group_id, attempt_index
            )
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_apify_actor_attempts_candidate_time
            ON apify_actor_attempts(candidate_id, created_at DESC)
        """
    )
    connection.execute(
        """
        CREATE INDEX idx_apify_actor_attempts_failed_cost
            ON apify_actor_attempts(workspace_id, route_key, terminal_at)
            WHERE status IN (
                'actor_failed', 'target_failed', 'start_outcome_unknown'
            )
        """
    )
    connection.execute("DROP TABLE apify_actor_adapter_revisions")
    connection.execute("DROP TABLE apify_actor_route_profiles")
    connection.execute(
        """
        DELETE FROM apify_actor_routes
        WHERE route_key IN (
            'youtube/channel/items',
            'instagram/profile/items'
        )
        """
    )
    connection.execute("DELETE FROM schema_migrations WHERE version >= 15")
    connection.commit()
    connection.execute("PRAGMA foreign_keys = ON")
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    store.close()


def _table_names(connection: sqlite3.Connection) -> set[str]:
    return {
        str(row["name"])
        for row in connection.execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }


def _seed_second_workspace(store: ServiceStore) -> str:
    workspace_id = "workspace-v15-other"
    now = "2026-07-30T00:00:00+00:00"
    store.connect().execute(
        """
        INSERT INTO workspaces (id, name, created_at, updated_at)
        VALUES (?, 'Other workspace', ?, ?)
        """,
        (workspace_id, now, now),
    )
    store.connect().commit()
    store._seed_apify_actor_routes()
    store._seed_apify_actor_ops_v15()
    return workspace_id


def _seed_invalid_youtube_profile_route(
    store: ServiceStore,
    *,
    job_status: str = "succeeded",
    run_count: int = 2,
) -> tuple[str, list[str]]:
    users = store.list_users(workspace_id=DEFAULT_WORKSPACE_ID)
    owner = users[0] if users else store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="migration-test-owner",
        password="safe-test-password",
        role="owner",
    )
    connection = store.connect()
    now = "2026-07-31T00:00:00+00:00"
    route_id = "route-invalid-youtube-profile"
    route_key = "youtube/profile/items"
    connection.execute(
        """
        INSERT INTO apify_actor_routes (
            workspace_id, route_key, generation, status,
            active_candidate_id, last_switch_reason, last_switch_at,
            budget_blocked_until, blocked_reason, created_at, updated_at
        ) VALUES (?, ?, 1, 'blocked', NULL, 'support_check', ?, NULL,
                  'discovery_required', ?, ?)
        """,
        (DEFAULT_WORKSPACE_ID, route_key, now, now, now),
    )
    connection.execute(
        """
        INSERT INTO apify_actor_route_profiles (
            route_id, workspace_id, route_key, platform, target_type,
            capability, mode, required_slots, min_runtime_healthy,
            min_publishers, per_run_cap_usd, status,
            metadata_check_interval_seconds, policy_version, generation,
            created_at, updated_at
        ) VALUES (?, ?, ?, 'youtube', 'profile', 'items', 'fallback',
                  3, 2, 2, 0.02, 'discovery_required', 604800,
                  'actor_ops_v1', 1, ?, ?)
        """,
        (route_id, DEFAULT_WORKSPACE_ID, route_key, now, now),
    )
    for slot_name in ("primary", "backup_1", "backup_2"):
        connection.execute(
            """
            INSERT INTO apify_route_active_slots (
                workspace_id, route_id, slot_name, candidate_id,
                revision_id, updated_at
            ) VALUES (?, ?, ?, NULL, NULL, ?)
            """,
            (DEFAULT_WORKSPACE_ID, route_id, slot_name, now),
        )
    run_ids: list[str] = []
    for index in range(run_count):
        run_id = f"invalid-youtube-profile-run-{index}"
        run_ids.append(run_id)
        connection.execute(
            """
            INSERT INTO apify_actor_discovery_runs (
                run_id, workspace_id, route_id, stage, trigger_reason,
                budget_usd, error_code, query_count, candidate_count,
                rejection_summary_json, created_at, updated_at
            ) VALUES (?, ?, ?, 'blocked_ai_unavailable', 'support_check',
                      0.10, 'discovery_ai_disabled', 0, 0, '[]', ?, ?)
            """,
            (run_id, DEFAULT_WORKSPACE_ID, route_id, now, now),
        )
        connection.execute(
            """
            INSERT INTO fetch_jobs (
                id, workspace_id, user_id, job_type, status, priority,
                attempts, max_attempts, payload_json, result_json,
                created_at, finished_at, updated_at
            ) VALUES (?, ?, ?, 'apify_actor_discovery', ?, 50, 1, 1, ?,
                      '{}', ?, ?, ?)
            """,
            (
                f"invalid-youtube-profile-job-{index}",
                DEFAULT_WORKSPACE_ID,
                str(owner["id"]),
                job_status,
                json.dumps({"run_id": run_id}),
                now,
                now if job_status != "queued" else None,
                now,
            ),
        )
    connection.execute(
        """
        UPDATE apify_actor_discovery_settings
        SET enabled = 1, ai_provider = 'gemini',
            ai_model = 'legacy-model', generation = generation + 1,
            updated_at = ?
        WHERE workspace_id = ?
        """,
        (now, DEFAULT_WORKSPACE_ID),
    )
    connection.execute(
        """
        UPDATE schema_migrations
        SET checksum = 'apify-actor-ops-three-slot-v15'
        WHERE version = ?
        """,
        (APIFY_ACTOR_OPS_MIGRATION_VERSION,),
    )
    connection.commit()
    return route_id, run_ids


def test_v15_dry_run_does_not_create_database(tmp_path) -> None:
    result = migrate_apify_actor_ops_v15(
        data_dir=tmp_path / "data",
        backup_dir=tmp_path / "backups",
        apply=False,
    )

    assert result == {
        "applied": False,
        "database_exists": False,
        "v13_migrated": False,
        "v13_ready": False,
        "v14_migrated": False,
        "v14_ready": False,
        "migrated": False,
        "schema_ready": False,
        "backup_path": None,
        "invalid_routes_deleted": 0,
        "invalid_route_slots_deleted": 0,
        "invalid_route_discovery_runs_deleted": 0,
        "invalid_route_jobs_deleted": 0,
        "discovery_settings_reset": 0,
        "catalog_generation_bump": 0,
    }
    assert not (tmp_path / "data" / "service.db").exists()


def test_v15_upgrade_safely_removes_empty_youtube_profile_route(tmp_path) -> None:
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    store = ServiceStore(data_dir)
    store.initialize()
    before_catalog_generation = int(
        store.connect().execute(
            "SELECT 1 + COALESCE(SUM(generation), 0) "
            "FROM apify_actor_route_profiles WHERE workspace_id = ?",
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()[0]
    )
    x_history_before = store.connect().execute(
        """
        SELECT COUNT(*), COALESCE(SUM(generation), 0)
        FROM apify_actor_routes
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    _seed_invalid_youtube_profile_route(store)
    before_catalog_generation += 1
    store.close()

    result = migrate_apify_actor_ops_v15(
        data_dir=data_dir,
        backup_dir=backup_dir,
        apply=True,
    )

    assert result["invalid_routes_deleted"] == 1
    assert result["invalid_route_slots_deleted"] == 3
    assert result["invalid_route_discovery_runs_deleted"] == 2
    assert result["invalid_route_jobs_deleted"] == 2
    assert result["discovery_settings_reset"] == 1
    assert result["catalog_generation_bump"] == 2
    assert os.stat(result["backup_path"]).st_mode & 0o777 == 0o600
    migrated = ServiceStore(data_dir)
    migrated.initialize()
    connection = migrated.connect()
    assert connection.execute(
        """
        SELECT COUNT(*) FROM apify_actor_route_profiles
        WHERE platform = 'youtube' AND target_type = 'profile'
          AND capability = 'items'
        """
    ).fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM fetch_jobs "
        "WHERE id LIKE 'invalid-youtube-profile-job-%'"
    ).fetchone()[0] == 0
    after_catalog_generation = int(
        connection.execute(
            "SELECT 1 + COALESCE(SUM(generation), 0) "
            "FROM apify_actor_route_profiles WHERE workspace_id = ?",
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()[0]
    )
    assert after_catalog_generation == before_catalog_generation + 1
    assert connection.execute(
        """
        SELECT COUNT(*), COALESCE(SUM(generation), 0)
        FROM apify_actor_routes
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone() == x_history_before
    settings = connection.execute(
        """
        SELECT enabled, ai_provider, ai_model, secret_ref_id, generation
        FROM apify_actor_discovery_settings WHERE workspace_id = ?
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    assert (settings["enabled"], settings["ai_provider"], settings["ai_model"]) == (
        0,
        "",
        "",
    )
    assert settings["secret_ref_id"] is None
    assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    migrated.close()


@pytest.mark.parametrize("evidence", ("candidate", "binding", "fee"))
def test_v15_route_repair_restores_backup_when_material_evidence_exists(
    tmp_path,
    evidence,
) -> None:
    data_dir = tmp_path / evidence
    backup_dir = tmp_path / f"backups-{evidence}"
    store = ServiceStore(data_dir)
    store.initialize()
    route_id, _run_ids = _seed_invalid_youtube_profile_route(store)
    connection = store.connect()
    now = "2026-07-31T00:00:00+00:00"
    if evidence in {"candidate", "fee"}:
        connection.execute(
            """
            INSERT INTO apify_actor_candidates (
                id, workspace_id, route_key, actor_id, adapter_key,
                display_name, position, state, created_at, updated_at
            ) VALUES ('invalid-route-candidate', ?, 'youtube/profile/items',
                      'publisher/invalid', 'manifest_v1', 'Invalid', 0,
                      'closed', ?, ?)
            """,
            (DEFAULT_WORKSPACE_ID, now, now),
        )
    if evidence == "fee":
        connection.execute(
            """
            INSERT INTO apify_actor_attempts (
                id, workspace_id, route_key, route_generation, candidate_id,
                attempt_group_id, attempt_index, status, reserved_usd,
                actual_cost_usd, cost_final, created_at, terminal_at,
                updated_at
            ) VALUES ('invalid-route-paid-attempt', ?,
                      'youtube/profile/items', 1, 'invalid-route-candidate',
                      'invalid-route-paid-group', 1, 'succeeded', 0.02,
                      0.01, 1, ?, ?, ?)
            """,
            (DEFAULT_WORKSPACE_ID, now, now, now),
        )
    if evidence == "binding":
        source_id = store.create_source(
            workspace_id=DEFAULT_WORKSPACE_ID,
            scope="workspace",
            owner_user_id=None,
            source_type="apify_social",
            display_name="Invalid bound source",
            config={"target": "opaque", "profile_id": route_id},
            source_key="invalid-youtube-profile-binding",
        )
        connection.execute(
            """
            INSERT INTO apify_source_route_bindings (
                binding_id, workspace_id, source_id, route_id,
                target_fingerprint, mode, validation_status, generation,
                created_at, updated_at
            ) VALUES ('invalid-route-binding', ?, ?, ?, ?, 'fallback',
                      'pending_validation', 1, ?, ?)
            """,
            (
                DEFAULT_WORKSPACE_ID,
                source_id,
                route_id,
                "a" * 64,
                now,
                now,
            ),
        )
    connection.commit()
    store.close()

    with pytest.raises(RuntimeError, match="unsafe youtube/profile/items repair"):
        migrate_apify_actor_ops_v15(
            data_dir=data_dir,
            backup_dir=backup_dir,
            apply=True,
        )

    restored = sqlite3.connect(data_dir / "service.db")
    try:
        assert restored.execute(
            "SELECT COUNT(*) FROM apify_actor_route_profiles "
            "WHERE route_id = ?",
            (route_id,),
        ).fetchone()[0] == 1
        assert restored.execute(
            "SELECT checksum FROM schema_migrations WHERE version = ?",
            (APIFY_ACTOR_OPS_MIGRATION_VERSION,),
        ).fetchone()[0] == "apify-actor-ops-three-slot-v15"
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        restored.close()
    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    assert os.stat(backups[0]).st_mode & 0o777 == 0o600


def test_v15_refuses_active_discovery_job_before_backup(tmp_path) -> None:
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    store = ServiceStore(data_dir)
    store.initialize()
    route_id, _run_ids = _seed_invalid_youtube_profile_route(
        store,
        job_status="queued",
        run_count=1,
    )
    store.close()

    with pytest.raises(RuntimeError, match="active Actor discovery/Canary jobs"):
        migrate_apify_actor_ops_v15(
            data_dir=data_dir,
            backup_dir=backup_dir,
            apply=True,
        )

    assert not list(backup_dir.glob("*.db"))
    connection = sqlite3.connect(data_dir / "service.db")
    try:
        assert connection.execute(
            "SELECT COUNT(*) FROM apify_actor_route_profiles WHERE route_id = ?",
            (route_id,),
        ).fetchone()[0] == 1
    finally:
        connection.close()


def test_actor_ops_uses_global_version_17_without_overwriting_notifications(
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    _downgrade_to_v14(data_dir)
    store = ServiceStore(data_dir)
    store.initialize()
    now = "2026-07-31T00:00:00+00:00"
    store.connect().executemany(
        """
        INSERT INTO schema_migrations(version, name, checksum, applied_at)
        VALUES (?, ?, ?, ?)
        """,
        (
            (
                15,
                "multichannel_notifications_v15",
                "telegram-multichannel-notifications-v15",
                now,
            ),
            (
                16,
                "notification_targets_v16",
                "reusable-notification-targets-v16",
                now,
            ),
        ),
    )
    store.connect().commit()
    store.close()

    result = migrate_apify_actor_ops_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )
    assert result["applied"] is True

    connection = sqlite3.connect(data_dir / "service.db")
    rows = {
        int(row[0]): (str(row[1]), str(row[2]))
        for row in connection.execute(
            """
            SELECT version, name, checksum FROM schema_migrations
            WHERE version IN (15, 16, ?)
            """,
            (APIFY_ACTOR_OPS_MIGRATION_VERSION,),
        ).fetchall()
    }
    connection.close()
    assert rows[15][0] == "multichannel_notifications_v15"
    assert rows[16][0] == "notification_targets_v16"
    assert rows[APIFY_ACTOR_OPS_MIGRATION_VERSION] == (
        APIFY_ACTOR_OPS_MIGRATION_NAME,
        APIFY_ACTOR_OPS_MIGRATION_CHECKSUM,
    )


def test_fresh_store_has_three_v15_profiles_and_legacy_x_projection(
    tmp_path,
) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()

    assert store.apify_actor_ops_v15_migration_required() is False
    assert V15_TABLES <= _table_names(connection)
    profiles = [
        tuple(row)
        for row in connection.execute(
            """
            SELECT route_key, platform, target_type, capability, mode, status
            FROM apify_actor_route_profiles
            ORDER BY route_key
            """
        ).fetchall()
    ]
    assert profiles == [
        (
            "instagram/profile/items",
            "instagram",
            "profile",
            "items",
            "primary",
            "candidate_shortfall",
        ),
        (
            "x/profile",
            "x",
            "profile",
            "items",
            "primary",
            "legacy_validation_pending",
        ),
        (
            "youtube/channel/items",
            "youtube",
            "channel",
            "items",
            "fallback",
            "candidate_shortfall",
        ),
    ]
    assert connection.execute(
        "SELECT COUNT(*) FROM apify_actor_routes"
    ).fetchone()[0] == 1
    assert connection.execute(
        "SELECT COUNT(*) FROM apify_route_active_slots"
    ).fetchone()[0] == 9
    revisions = connection.execute(
        """
        SELECT lifecycle, build_id, build_number, manifest_json, manifest_hash,
               canary_passed_at, security_evidence_json
        FROM apify_actor_adapter_revisions
        ORDER BY revision_id
        """
    ).fetchall()
    assert len(revisions) == 3
    assert {
        str(row["lifecycle"]) for row in revisions
    } == {"legacy_builtin"}
    for row in revisions:
        assert row["build_id"] is None
        assert row["build_number"] is None
        assert row["manifest_json"] is None
        assert row["manifest_hash"] is None
        assert row["canary_passed_at"] is None
        evidence = json.loads(str(row["security_evidence_json"]))
        assert evidence["exact_build_proven"] is False
        assert evidence["certification_proven"] is False
    assert tuple(
        connection.execute(
            """
            SELECT enabled, ai_provider, ai_model, secret_ref_id, call_limit,
                   generation
            FROM apify_actor_discovery_settings
            WHERE workspace_id = ?
            """,
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()
    ) == (0, "", "", None, 3, 1)
    store.close()


@pytest.mark.parametrize(
    ("column", "replacement"),
    (
        ("adapter_revision_id", None),
        ("build_id", "changed-build-id"),
        ("build_number", "changed-build-number"),
        ("manifest_hash", "b" * 64),
        ("target_fingerprint", "b" * 64),
    ),
)
def test_v15_attempt_adapter_snapshot_is_immutable(
    tmp_path,
    column,
    replacement,
) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    slot = connection.execute(
        """
        SELECT slot.candidate_id, slot.revision_id, profile.generation
        FROM apify_route_active_slots AS slot
        JOIN apify_actor_route_profiles AS profile
          ON profile.route_id = slot.route_id
        WHERE profile.workspace_id = ?
          AND profile.route_key = 'x/profile'
          AND slot.slot_name = 'primary'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    now = "2026-07-30T00:00:00+00:00"
    connection.execute(
        """
        INSERT INTO apify_actor_attempts (
            id, workspace_id, route_key, route_generation, candidate_id,
            source_id, job_id, attempt_group_id, attempt_index, status,
            semantic_outcome, reserved_usd, actual_cost_usd, cost_final,
            adapter_revision_id, build_id, build_number, manifest_hash,
            target_fingerprint, last_error_code, created_at, started_at,
            terminal_at, updated_at
        ) VALUES (
            'immutable-attempt', ?, 'x/profile', ?, ?, NULL, NULL,
            'immutable-group', 1, 'running', NULL, 0.02, NULL, 0,
            ?, 'build-id', 'build-number', ?, ?, NULL, ?, ?, NULL, ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            int(slot["generation"]),
            str(slot["candidate_id"]),
            str(slot["revision_id"]),
            "a" * 64,
            "c" * 64,
            now,
            now,
            now,
        ),
    )
    connection.commit()

    with pytest.raises(sqlite3.IntegrityError, match="snapshot is immutable"):
        connection.execute(
            f"""
            UPDATE apify_actor_attempts
            SET {column} = ?, updated_at = ?
            WHERE id = 'immutable-attempt'
            """,
            (replacement, "2026-07-30T00:01:00+00:00"),
        )
    connection.rollback()
    assert connection.execute(
        """
        SELECT status FROM apify_actor_attempts
        WHERE id = 'immutable-attempt'
        """
    ).fetchone()["status"] == "running"
    store.close()


def test_v15_rejects_cross_workspace_actor_ops_associations(tmp_path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    other_workspace = _seed_second_workspace(store)
    other_source = store.create_source(
        workspace_id=other_workspace,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Other X",
        config={
            "platform": "x",
            "kind": "profile",
            "target": "@other",
        },
        source_key="apify_social:x:profile:other",
    )
    other_secret = store.create_secret_ref(
        workspace_id=other_workspace,
        owner_user_id=None,
        name="Other discovery",
        env_name="OTHER_APIFY_DISCOVERY_KEY",
        kind="ai",
        provider="test",
    )
    connection = store.connect()
    default_slot = connection.execute(
        """
        SELECT profile.route_id, slot.candidate_id, slot.revision_id,
               profile.generation
        FROM apify_actor_route_profiles AS profile
        JOIN apify_route_active_slots AS slot
          ON slot.route_id = profile.route_id
        WHERE profile.workspace_id = ?
          AND profile.route_key = 'x/profile'
          AND slot.slot_name = 'primary'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    other_slot = connection.execute(
        """
        SELECT profile.route_id, slot.candidate_id, slot.revision_id,
               profile.generation
        FROM apify_actor_route_profiles AS profile
        JOIN apify_route_active_slots AS slot
          ON slot.route_id = profile.route_id
        WHERE profile.workspace_id = ?
          AND profile.route_key = 'x/profile'
          AND slot.slot_name = 'primary'
        """,
        (other_workspace,),
    ).fetchone()
    default_youtube_slot = connection.execute(
        """
        SELECT profile.route_id, slot.candidate_id, slot.revision_id
        FROM apify_actor_route_profiles AS profile
        JOIN apify_route_active_slots AS slot
          ON slot.route_id = profile.route_id
        WHERE profile.workspace_id = ?
          AND profile.route_key = 'youtube/channel/items'
          AND slot.slot_name = 'primary'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    now = "2026-07-30T00:00:00+00:00"
    connection.executemany(
        """
        INSERT INTO apify_actor_discovery_runs (
            run_id, workspace_id, route_id, stage, trigger_reason,
            budget_usd, query_count, created_at, updated_at
        ) VALUES (?, ?, ?, 'created', 'test', 0.10, 0, ?, ?)
        """,
        (
            (
                "default-discovery-run",
                DEFAULT_WORKSPACE_ID,
                str(default_slot["route_id"]),
                now,
                now,
            ),
            (
                "other-discovery-run",
                other_workspace,
                str(other_slot["route_id"]),
                now,
                now,
            ),
        ),
    )
    connection.execute(
        """
        INSERT INTO apify_actor_attempts (
            id, workspace_id, route_key, route_generation, candidate_id,
            attempt_group_id, attempt_index, status, reserved_usd,
            cost_final, adapter_revision_id, created_at, updated_at
        ) VALUES (
            'other-attempt', ?, 'x/profile', ?, ?,
            'other-group', 1, 'reserved', 0.02, 0, ?, ?, ?
        )
        """,
        (
            other_workspace,
            int(other_slot["generation"]),
            str(other_slot["candidate_id"]),
            str(other_slot["revision_id"]),
            now,
            now,
        ),
    )
    connection.commit()

    def rejects(statement: str, parameters: tuple) -> None:
        with pytest.raises(sqlite3.IntegrityError):
            connection.execute(statement, parameters)
        connection.rollback()

    rejects(
        """
        INSERT INTO apify_actor_adapter_revisions (
            revision_id, workspace_id, candidate_id, actor_id, publisher,
            security_evidence_json, lifecycle, created_at
        ) VALUES (
            'cross-revision', ?, ?, 'cross/actor', 'cross', '{}',
            'legacy_builtin', ?
        )
        """,
        (
            other_workspace,
            str(default_slot["candidate_id"]),
            now,
        ),
    )
    rejects(
        """
        UPDATE apify_route_active_slots
        SET candidate_id = ?, revision_id = ?, updated_at = ?
        WHERE workspace_id = ?
          AND route_id = ?
          AND slot_name = 'primary'
        """,
        (
            str(default_slot["candidate_id"]),
            str(default_slot["revision_id"]),
            now,
            other_workspace,
            str(other_slot["route_id"]),
        ),
    )
    rejects(
        """
        UPDATE apify_route_active_slots
        SET candidate_id = ?, revision_id = ?, updated_at = ?
        WHERE workspace_id = ? AND route_id = ? AND slot_name = 'primary'
        """,
        (
            str(default_slot["candidate_id"]),
            str(default_slot["revision_id"]),
            now,
            DEFAULT_WORKSPACE_ID,
            str(default_youtube_slot["route_id"]),
        ),
    )
    rejects(
        """
        INSERT INTO apify_actor_adapter_revisions (
            revision_id, workspace_id, candidate_id, actor_id, publisher,
            discovery_run_id, security_evidence_json, lifecycle, created_at
        ) VALUES (
            'cross-discovery-revision', ?, ?, 'cross/discovery', 'cross',
            'other-discovery-run', '{}', 'legacy_builtin', ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            str(default_slot["candidate_id"]),
            now,
        ),
    )
    rejects(
        """
        INSERT INTO apify_actor_validations (
            validation_id, workspace_id, route_id, source_id, revision_id,
            attempt_id, discovery_run_id, kind, target_fingerprint,
            status, created_at
        ) VALUES (
            'cross-discovery-validation', ?, ?, NULL, ?, NULL,
            'other-discovery-run', 'source_canary', NULL, 'succeeded', ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            str(default_slot["route_id"]),
            str(default_slot["revision_id"]),
            now,
        ),
    )
    rejects(
        """
        INSERT INTO apify_actor_discovery_run_revisions (
            workspace_id, run_id, revision_id, created_at
        ) VALUES (?, 'other-discovery-run', ?, ?)
        """,
        (
            DEFAULT_WORKSPACE_ID,
            str(default_slot["revision_id"]),
            now,
        ),
    )
    rejects(
        """
        INSERT INTO apify_source_route_bindings (
            binding_id, workspace_id, source_id, route_id,
            target_fingerprint, mode, validation_status, generation,
            created_at, updated_at
        ) VALUES (
            'cross-binding', ?, ?, ?, ?, 'primary', 'pending', 1, ?, ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            other_source,
            str(default_slot["route_id"]),
            "a" * 64,
            now,
            now,
        ),
    )
    rejects(
        """
        INSERT INTO apify_actor_discovery_runs (
            run_id, workspace_id, route_id, stage, trigger_reason,
            budget_usd, query_count, created_at, updated_at
        ) VALUES (
            'cross-discovery', ?, ?, 'created', 'test', 0.10, 0, ?, ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            str(other_slot["route_id"]),
            now,
            now,
        ),
    )
    rejects(
        """
        INSERT INTO apify_actor_validations (
            validation_id, workspace_id, route_id, source_id, revision_id,
            attempt_id, kind, target_fingerprint, status, created_at
        ) VALUES (
            'cross-validation', ?, ?, NULL, ?, NULL,
            'source_canary', NULL, 'succeeded', ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            str(default_slot["route_id"]),
            str(other_slot["revision_id"]),
            now,
        ),
    )
    rejects(
        """
        INSERT INTO apify_actor_validations (
            validation_id, workspace_id, route_id, source_id, revision_id,
            attempt_id, kind, target_fingerprint, status, created_at
        ) VALUES (
            'cross-validation-source', ?, ?, ?, ?, NULL,
            'source_canary', NULL, 'succeeded', ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            str(default_slot["route_id"]),
            other_source,
            str(default_slot["revision_id"]),
            now,
        ),
    )
    rejects(
        """
        INSERT INTO apify_actor_validations (
            validation_id, workspace_id, route_id, source_id, revision_id,
            attempt_id, kind, target_fingerprint, status, created_at
        ) VALUES (
            'cross-validation-attempt', ?, ?, NULL, ?, ?,
            'source_canary', NULL, 'succeeded', ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            str(default_slot["route_id"]),
            str(default_slot["revision_id"]),
            "other-attempt",
            now,
        ),
    )
    rejects(
        """
        UPDATE apify_actor_discovery_settings
        SET secret_ref_id = ?, updated_at = ?
        WHERE workspace_id = ?
        """,
        (
            str(other_secret["id"]),
            now,
            DEFAULT_WORKSPACE_ID,
        ),
    )
    rejects(
        """
        INSERT INTO apify_actor_attempts (
            id, workspace_id, route_key, route_generation, candidate_id,
            attempt_group_id, attempt_index, status, reserved_usd,
            cost_final, adapter_revision_id, created_at, updated_at
        ) VALUES (
            'cross-attempt', ?, 'x/profile', ?, ?,
            'cross-group', 1, 'reserved', 0.02, 0, ?, ?, ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            int(default_slot["generation"]),
            str(default_slot["candidate_id"]),
            str(other_slot["revision_id"]),
            now,
            now,
        ),
    )
    rejects(
        """
        INSERT INTO apify_actor_validations (
            validation_id, workspace_id, route_id, source_id, revision_id,
            attempt_id, kind, target_fingerprint, status, created_at
        ) VALUES (
            'missing-reference-fingerprint', ?, ?, NULL, ?, NULL,
            'route_reference', NULL, 'succeeded', ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            str(default_slot["route_id"]),
            str(default_slot["revision_id"]),
            now,
        ),
    )
    connection.execute(
        """
        INSERT INTO apify_actor_adapter_revisions (
            revision_id, workspace_id, candidate_id, actor_id, publisher,
            discovery_run_id, security_evidence_json, lifecycle, created_at
        ) VALUES (
            'local-discovery-revision', ?, ?, 'local/discovery', 'local',
            'default-discovery-run', '{}', 'legacy_builtin', ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            str(default_slot["candidate_id"]),
            now,
        ),
    )
    connection.commit()
    rejects(
        "DELETE FROM apify_actor_discovery_runs WHERE run_id = ?",
        ("default-discovery-run",),
    )
    store.close()


def test_existing_v14_database_requires_explicit_v15_apply(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _downgrade_to_v14(data_dir)

    store = ServiceStore(data_dir)
    store.initialize()
    assert store.apify_actor_ops_v15_migration_required() is True
    assert not V15_TABLES & _table_names(store.connect())
    attempt_columns = {
        str(row["name"])
        for row in store.connect().execute(
            "PRAGMA table_info(apify_actor_attempts)"
        ).fetchall()
    }
    assert not {"adapter_revision_id", "build_number", "manifest_hash"} & (
        attempt_columns
    )
    assert store.connect().execute(
        "SELECT 1 FROM schema_migrations WHERE version = ?",
        (APIFY_ACTOR_OPS_MIGRATION_VERSION,),
    ).fetchone() is None
    store.close()


def test_normal_initialize_never_repairs_partial_actor_ops_marker(
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    _downgrade_to_v14(data_dir)
    store = ServiceStore(data_dir)
    store.initialize()
    store.mark_apify_actor_ops_v15_migrated()
    before_columns = tuple(
        row["name"]
        for row in store.connect().execute(
            "PRAGMA table_info(apify_actor_attempts)"
        ).fetchall()
    )
    store.close()

    reopened = ServiceStore(data_dir)
    reopened.initialize()
    assert not V15_TABLES & _table_names(reopened.connect())
    assert tuple(
        row["name"]
        for row in reopened.connect().execute(
            "PRAGMA table_info(apify_actor_attempts)"
        ).fetchall()
    ) == before_columns
    assert reopened.apify_actor_ops_v15_migration_required() is True
    reopened.close()

    applied = migrate_apify_actor_ops_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )
    assert applied["applied"] is True
    assert applied["schema_ready"] is True


def test_explicit_migration_replaces_same_name_weak_trigger(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    connection.executescript(
        """
        DROP TRIGGER trg_apify_actor_attempt_freeze_immutable;
        CREATE TRIGGER trg_apify_actor_attempt_freeze_immutable
        BEFORE UPDATE ON apify_actor_attempts
        FOR EACH ROW
        WHEN NEW.adapter_revision_id IS NOT OLD.adapter_revision_id
        BEGIN
            SELECT RAISE(ABORT, 'weak legacy trigger');
        END;
        """
    )
    connection.commit()
    assert store.apify_actor_ops_v15_migration_required() is True
    store.close()

    reopened = ServiceStore(data_dir)
    reopened.initialize()
    weak_sql = str(
        reopened.connect().execute(
            """
            SELECT sql FROM sqlite_master
            WHERE type = 'trigger'
              AND name = 'trg_apify_actor_attempt_freeze_immutable'
            """
        ).fetchone()[0]
    )
    assert "target_fingerprint" not in weak_sql
    reopened.close()

    result = migrate_apify_actor_ops_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )
    assert result["applied"] is True
    repaired = ServiceStore(data_dir)
    repaired.initialize()
    assert repaired.apify_actor_ops_v15_migration_required() is False
    repaired.close()


def test_explicit_migration_repairs_actor_ops_marker_checksum(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    store.connect().execute(
        """
        UPDATE schema_migrations SET checksum = 'wrong-checksum'
        WHERE version = ? AND name = ?
        """,
        (
            APIFY_ACTOR_OPS_MIGRATION_VERSION,
            APIFY_ACTOR_OPS_MIGRATION_NAME,
        ),
    )
    store.connect().commit()
    store.close()

    reopened = ServiceStore(data_dir)
    reopened.initialize()
    assert reopened.apify_actor_ops_v15_migration_required() is True
    reopened.close()
    result = migrate_apify_actor_ops_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )
    assert result["applied"] is True
    repaired = ServiceStore(data_dir)
    repaired.initialize()
    assert repaired.apify_actor_ops_v15_migration_required() is False
    repaired.close()


def test_actor_ops_dependency_checks_precede_already_migrated_return(
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    store.connect().execute(
        "DELETE FROM schema_migrations WHERE version = 14"
    )
    store.connect().commit()
    store.close()

    with pytest.raises(RuntimeError, match="Webhook providers v14"):
        migrate_apify_actor_ops_v15(
            data_dir=data_dir,
            backup_dir=tmp_path / "backups",
            apply=True,
        )
    assert not (tmp_path / "backups").exists()


def test_v15_backs_up_preserves_v13_history_and_seeds_x_bindings(
    tmp_path,
) -> None:
    data_dir = tmp_path / "data"
    _downgrade_to_v14(data_dir)
    store = ServiceStore(data_dir)
    store.initialize()
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="Legacy X",
        config={
            "platform": "x",
            "kind": "profile",
            "target": "@ExampleProfile",
        },
        source_key="apify_social:x:profile:exampleprofile",
    )
    candidate = store.connect().execute(
        """
        SELECT id FROM apify_actor_candidates
        WHERE workspace_id = ? AND route_key = 'x/profile'
        ORDER BY position LIMIT 1
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    candidate_id = str(candidate["id"])
    now = "2026-07-30T00:00:00+00:00"
    store.connect().execute(
        """
        UPDATE apify_actor_routes
        SET generation = 7, status = 'degraded',
            last_switch_reason = 'preserve-me', updated_at = ?
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (now, DEFAULT_WORKSPACE_ID),
    )
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'closed', success_count = 9, failure_count = 2,
            last_success_at = ?, updated_at = ?
        WHERE id = ?
        """,
        (now, now, candidate_id),
    )
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = 'closed', updated_at = ?
        WHERE workspace_id = ? AND route_key = 'x/profile' AND position = 1
        """,
        (now, DEFAULT_WORKSPACE_ID),
    )
    store.connect().execute(
        """
        INSERT INTO apify_actor_attempts (
            id, workspace_id, route_key, route_generation, candidate_id,
            source_id, job_id, attempt_group_id, attempt_index, status,
            semantic_outcome, reserved_usd, actual_cost_usd, cost_final,
            last_error_code, created_at, started_at, terminal_at, updated_at
        ) VALUES (
            'legacy-attempt', ?, 'x/profile', 7, ?, ?, NULL,
            'legacy-group', 1, 'succeeded', 'valid_nonempty',
            0.02, 0.013, 1, NULL, ?, ?, ?, ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            candidate_id,
            source_id,
            now,
            now,
            now,
            now,
        ),
    )
    store.connect().execute(
        """
        INSERT INTO apify_actor_target_health (
            workspace_id, route_key, candidate_id, source_id,
            had_valid_nonempty, consecutive_failures, last_semantic_outcome,
            last_valid_at, last_failure_at, paused_until, updated_at
        ) VALUES (
            ?, 'x/profile', ?, ?, 1, 0, 'valid_nonempty',
            ?, NULL, NULL, ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            candidate_id,
            source_id,
            now,
            now,
        ),
    )
    store.connect().execute(
        """
        INSERT INTO apify_actor_runs (
            id, workspace_id, logical_run_id, secret_id, secret_version,
            pool_generation, remote_run_id, dataset_id, status,
            last_error_code, created_at, started_at, terminal_at, updated_at,
            charge_reserved_usd, charge_actual_usd, charge_final
        ) VALUES (
            'legacy-run', ?, 'legacy-attempt', 'legacy-secret', 1, 1,
            'remote-redacted', 'dataset-redacted', 'succeeded', NULL,
            ?, ?, ?, ?, 0.02, 0.013, 1
        )
        """,
        (DEFAULT_WORKSPACE_ID, now, now, now, now),
    )
    store.connect().commit()
    before_route = dict(
        store.connect().execute(
            """
            SELECT * FROM apify_actor_routes
            WHERE workspace_id = ? AND route_key = 'x/profile'
            """,
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()
    )
    before_candidate = dict(
        store.connect().execute(
            "SELECT * FROM apify_actor_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
    )
    before_attempt = dict(
        store.connect().execute(
            "SELECT * FROM apify_actor_attempts WHERE id = 'legacy-attempt'"
        ).fetchone()
    )
    store.close()

    result = migrate_apify_actor_ops_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )

    assert result["applied"] is True
    assert result["route_profile_count"] == 3
    assert result["revision_count"] == 3
    assert result["slot_count"] == 9
    assert result["source_binding_count"] == 1
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_errors"] == 0
    assert result["backup_path"]
    assert os.stat(result["backup_path"]).st_mode & 0o777 == 0o600

    migrated = ServiceStore(data_dir)
    migrated.initialize()
    connection = migrated.connect()
    assert migrated.apify_actor_ops_v15_migration_required() is False
    assert dict(
        connection.execute(
            """
            SELECT * FROM apify_actor_routes
            WHERE workspace_id = ? AND route_key = 'x/profile'
            """,
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()
    ) == before_route
    assert dict(
        connection.execute(
            "SELECT * FROM apify_actor_candidates WHERE id = ?",
            (candidate_id,),
        ).fetchone()
    ) == before_candidate
    migrated_attempt = dict(
        connection.execute(
            "SELECT * FROM apify_actor_attempts WHERE id = 'legacy-attempt'"
        ).fetchone()
    )
    for key, value in before_attempt.items():
        assert migrated_attempt[key] == value
    assert migrated_attempt["adapter_revision_id"] is None
    assert migrated_attempt["build_id"] is None
    assert migrated_attempt["build_number"] is None
    assert migrated_attempt["manifest_hash"] is None
    assert connection.execute(
        """
        SELECT COUNT(*) FROM apify_actor_target_health
        WHERE source_id = ?
        """,
        (source_id,),
    ).fetchone()[0] == 1
    assert tuple(
        connection.execute(
            """
            SELECT charge_reserved_usd, charge_actual_usd, charge_final
            FROM apify_actor_runs WHERE id = 'legacy-run'
            """
        ).fetchone()
    ) == (0.02, 0.013, 1)
    x_profile = connection.execute(
        """
        SELECT route_id, generation, status
        FROM apify_actor_route_profiles
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    expected_route_id = "apify-route-" + hashlib.sha256(
        "\x1f".join(
            (
                "apify-actor-ops-v15",
                DEFAULT_WORKSPACE_ID,
                "x/profile",
            )
        ).encode("utf-8")
    ).hexdigest()[:32]
    assert x_profile["route_id"] == expected_route_id
    assert x_profile["generation"] == 7
    assert x_profile["status"] == "legacy_validation_pending"
    slots = connection.execute(
        """
        SELECT slot_name, candidate_id, revision_id
        FROM apify_route_active_slots
        WHERE route_id = ?
        ORDER BY CASE slot_name
            WHEN 'primary' THEN 0
            WHEN 'backup_1' THEN 1
            ELSE 2
        END
        """,
        (expected_route_id,),
    ).fetchall()
    assert len(slots) == 3
    assert all(row["candidate_id"] and row["revision_id"] for row in slots)
    binding = connection.execute(
        """
        SELECT * FROM apify_source_route_bindings
        WHERE source_id = ?
        """,
        (source_id,),
    ).fetchone()
    assert binding["route_id"] == expected_route_id
    assert binding["validation_status"] == "legacy_validation_pending"
    assert binding["verified_revision_set_hash"] is None
    from src.services.apify_actor_ops import source_target_fingerprint

    assert str(binding["target_fingerprint"]) == source_target_fingerprint(
        DEFAULT_WORKSPACE_ID,
        expected_route_id,
        "@ExampleProfile",
        platform="x",
    )
    from src.services.apify_actor_ops import ApifyActorOpsService

    ApifyActorOpsService(migrated).assert_source_target(
        expected_route_id,
        source_id,
        "https://x.com/exampleprofile",
    )
    assert ApifyActorOpsService(migrated).schedule_gate(
        expected_route_id
    ).allowed is True
    assert "target" not in binding.keys()
    migrated.close()

    repeated = migrate_apify_actor_ops_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )
    assert repeated["applied"] is False
    assert repeated["reason"] == "already_migrated"
    assert repeated["schema_ready"] is True


def test_v15_preserves_legacy_unknown_start_block(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _downgrade_to_v14(data_dir)
    store = ServiceStore(data_dir)
    store.initialize()
    store.connect().execute(
        """
        UPDATE apify_actor_routes
        SET status = 'blocked', blocked_reason = 'apify_run_reconcile_required'
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (DEFAULT_WORKSPACE_ID,),
    )
    store.connect().execute(
        """
        UPDATE apify_actor_candidates
        SET state = CASE WHEN position < 2 THEN 'closed' ELSE 'disabled' END
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (DEFAULT_WORKSPACE_ID,),
    )
    store.connect().commit()
    store.close()

    migrate_apify_actor_ops_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )
    migrated = ServiceStore(data_dir)
    migrated.initialize()
    route = migrated.connect().execute(
        """
        SELECT route_id, status FROM apify_actor_route_profiles
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    assert route["status"] == "blocked_unknown_start"
    from src.services.apify_actor_ops import ApifyActorOpsService

    gate = ApifyActorOpsService(migrated).schedule_gate(str(route["route_id"]))
    assert gate.allowed is False
    assert gate.error_code == "apify_actor_route_blocked"
    migrated.close()


def test_v15_restores_v14_backup_when_post_initialize_validation_fails(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    _downgrade_to_v14(data_dir)
    monkeypatch.setattr(
        migration_module,
        "_v15_schema_ready",
        lambda _connection, *, require_marker: False,
    )

    with pytest.raises(RuntimeError, match="schema verification failed"):
        migrate_apify_actor_ops_v15(
            data_dir=data_dir,
            backup_dir=backup_dir,
            apply=True,
        )

    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    assert os.stat(backups[0]).st_mode & 0o777 == 0o600
    connection = sqlite3.connect(data_dir / "service.db")
    try:
        assert not V15_TABLES & {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?",
            (APIFY_ACTOR_OPS_MIGRATION_VERSION,),
        ).fetchone() is None
        assert "adapter_revision_id" not in {
            str(row[1])
            for row in connection.execute(
                "PRAGMA table_info(apify_actor_attempts)"
            ).fetchall()
        }
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()


def test_v15_detects_non_x_route_history_change_and_restores_backup(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    backup_dir = tmp_path / "backups"
    _downgrade_to_v14(data_dir)
    store = ServiceStore(data_dir)
    store.initialize()
    now = "2026-07-30T00:00:00+00:00"
    store.connect().execute(
        """
        INSERT INTO apify_actor_routes (
            workspace_id, route_key, generation, status,
            active_candidate_id, last_switch_reason, last_switch_at,
            budget_blocked_until, blocked_reason, created_at, updated_at
        ) VALUES (
            ?, 'legacy/non-x', 11, 'degraded',
            NULL, 'preserve-all-routes', ?, NULL, NULL, ?, ?
        )
        """,
        (DEFAULT_WORKSPACE_ID, now, now, now),
    )
    store.connect().commit()
    store.close()
    original_initialize = ServiceStore.initialize

    def initialize_and_corrupt_non_x_route(self, *args, **kwargs):
        original_initialize(self, *args, **kwargs)
        if kwargs.get("prepare_apify_actor_ops_v15"):
            self.connect().execute(
                """
                UPDATE apify_actor_routes
                SET generation = 12
                WHERE workspace_id = ? AND route_key = 'legacy/non-x'
                """,
                (DEFAULT_WORKSPACE_ID,),
            )
            self.connect().commit()

    monkeypatch.setattr(
        ServiceStore,
        "initialize",
        initialize_and_corrupt_non_x_route,
    )

    with pytest.raises(RuntimeError, match="legacy Apify routing history changed"):
        migrate_apify_actor_ops_v15(
            data_dir=data_dir,
            backup_dir=backup_dir,
            apply=True,
        )

    connection = sqlite3.connect(data_dir / "service.db")
    try:
        assert connection.execute(
            """
            SELECT generation FROM apify_actor_routes
            WHERE workspace_id = ? AND route_key = 'legacy/non-x'
            """,
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()[0] == 11
        assert connection.execute(
            "SELECT 1 FROM schema_migrations WHERE version = ?",
            (APIFY_ACTOR_OPS_MIGRATION_VERSION,),
        ).fetchone() is None
        assert not V15_TABLES & {
            str(row[0])
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert connection.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()
    backups = list(backup_dir.glob("*.db"))
    assert len(backups) == 1
    assert os.stat(backups[0]).st_mode & 0o777 == 0o600


def test_v15_requires_v13_v14_and_stopped_worker(tmp_path) -> None:
    missing_v14 = tmp_path / "missing-v14"
    _downgrade_to_v14(missing_v14)
    store = ServiceStore(missing_v14)
    store.initialize()
    store.connect().execute(
        "DELETE FROM schema_migrations WHERE version = 14"
    )
    store.connect().commit()
    store.close()

    with pytest.raises(RuntimeError, match="Webhook providers v14"):
        migrate_apify_actor_ops_v15(
            data_dir=missing_v14,
            backup_dir=tmp_path / "backups-v14",
            apply=True,
        )
    assert not (tmp_path / "backups-v14").exists()

    active = tmp_path / "active-worker"
    _downgrade_to_v14(active)
    store = ServiceStore(active)
    store.initialize()
    store.upsert_worker_heartbeat("active-v15-worker", "idle")
    store.close()

    with pytest.raises(RuntimeError, match="heartbeat safety window"):
        migrate_apify_actor_ops_v15(
            data_dir=active,
            backup_dir=tmp_path / "backups-worker",
            apply=True,
        )
    assert not (tmp_path / "backups-worker").exists()


def test_v15_route_cap_can_exceed_legacy_two_cent_ceiling(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _downgrade_to_v14(data_dir)
    migrate_apify_actor_ops_v15(
        data_dir=data_dir,
        backup_dir=tmp_path / "backups",
        apply=True,
    )
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    connection.execute(
        """
        UPDATE apify_actor_route_profiles
        SET per_run_cap_usd = 0.05, updated_at = updated_at
        WHERE workspace_id = ? AND route_key = 'x/profile'
        """,
        (DEFAULT_WORKSPACE_ID,),
    )
    slot = connection.execute(
        """
        SELECT slot.candidate_id, slot.revision_id, profile.generation
        FROM apify_route_active_slots AS slot
        JOIN apify_actor_route_profiles AS profile
          ON profile.route_id = slot.route_id
        WHERE profile.workspace_id = ?
          AND profile.route_key = 'x/profile'
          AND slot.slot_name = 'primary'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    connection.execute(
        """
        INSERT INTO apify_actor_attempts (
            id, workspace_id, route_key, route_generation, candidate_id,
            source_id, job_id, attempt_group_id, attempt_index, status,
            semantic_outcome, reserved_usd, actual_cost_usd, cost_final,
            adapter_revision_id, build_id, build_number, manifest_hash,
            last_error_code, created_at, started_at, terminal_at, updated_at
        ) VALUES (
            'raised-cap-attempt', ?, 'x/profile', ?, ?, NULL, NULL,
            'raised-cap-group', 1, 'reserved', NULL, 0.05, NULL, 0,
            ?, NULL, NULL, NULL, NULL, ?, NULL, NULL, ?
        )
        """,
        (
            DEFAULT_WORKSPACE_ID,
            int(slot["generation"]),
            str(slot["candidate_id"]),
            str(slot["revision_id"]),
            "2026-07-30T00:00:00+00:00",
            "2026-07-30T00:00:00+00:00",
        ),
    )
    connection.commit()
    assert tuple(
        connection.execute(
            """
            SELECT reserved_usd, adapter_revision_id
            FROM apify_actor_attempts
            WHERE id = 'raised-cap-attempt'
            """
        ).fetchone()
    ) == (0.05, slot["revision_id"])
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    store.close()
