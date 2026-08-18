from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from scripts.migrate_apify_actor_resilience_v21 import (
    _DETERMINISTIC_CANARY_FAILURES,
    _evidence_fingerprint,
    migrate,
)
from scripts.migrate_apify_actor_validation_tuning_v20 import _rebuild_table
from src.services.apify_actor_ops import actor_evidence_fingerprint
from src.storage.service_store import (
    DEFAULT_WORKSPACE_ID,
    ServiceStore,
    apify_actor_resilience_v21_schema_shapes_valid,
)


def _downgrade_to_v20_shape(store: ServiceStore) -> None:
    """Produce a realistic v20 shape without v21-only run/key columns."""

    connection = store.connect()
    connection.execute(
        """
        UPDATE apify_actor_route_profiles
        SET min_runtime_healthy = 2, min_publishers = 2
        WHERE route_key = 'youtube/channel/items'
        """
    )
    connection.commit()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for table in (
            "apify_actor_freshness_results",
            "apify_actor_freshness_checks",
            "apify_actor_evaluation_history",
            "apify_actor_diagnostic_events",
        ):
            connection.execute(f"DROP TABLE {table}")
        connection.execute("DROP INDEX idx_apify_key_pool_one_validation")
        connection.execute("DROP INDEX idx_apify_key_pool_one_active")
        connection.execute(
            "ALTER TABLE apify_key_pool_members DROP COLUMN role"
        )
        connection.execute("ALTER TABLE apify_actor_runs DROP COLUMN purpose")
        route_triggers = connection.execute(
            """
            SELECT name, sql FROM sqlite_master
            WHERE type = 'trigger'
              AND sql LIKE '%apify_actor_route_profiles%'
            ORDER BY name
            """
        ).fetchall()
        for trigger in route_triggers:
            connection.execute(f'DROP TRIGGER "{str(trigger["name"])}"')
        _rebuild_table(
            connection,
            "apify_actor_route_profiles",
            replacements=(
                (
                    "CHECK(min_runtime_healthy BETWEEN 1 AND 3)",
                    "CHECK(min_runtime_healthy BETWEEN 2 AND 3)",
                ),
                (
                    "CHECK(min_publishers BETWEEN 1 AND 3)",
                    "CHECK(min_publishers BETWEEN 2 AND 3)",
                ),
            ),
            index_sql=(
                """
                CREATE INDEX idx_apify_actor_route_profiles_capability
                ON apify_actor_route_profiles(
                    workspace_id, platform, target_type, capability, status
                )
                """,
            ),
        )
        for trigger in route_triggers:
            if trigger["sql"]:
                connection.execute(str(trigger["sql"]))
        compatibility_suffix = (
            "'upgrade_legacy',\n                    'compatibility_single'",
            "'upgrade_legacy'",
        )
        _rebuild_table(
            connection,
            "apify_actor_canary_batches",
            replacements=(compatibility_suffix,),
            index_sql=(
                """
                CREATE INDEX idx_apify_actor_canary_batches_route
                ON apify_actor_canary_batches(
                    workspace_id, route_id, created_at DESC
                )
                """,
            ),
        )
        _rebuild_table(
            connection,
            "apify_actor_pool_stages",
            replacements=(
                compatibility_suffix,
                (
                    "CHECK(target_slot_count BETWEEN 1 AND 3)",
                    "CHECK(target_slot_count BETWEEN 2 AND 3)",
                ),
            ),
            index_sql=(
                """
                CREATE UNIQUE INDEX idx_apify_actor_pool_stages_active
                ON apify_actor_pool_stages(workspace_id, route_id)
                WHERE status NOT IN (
                    'applied', 'stale', 'failed', 'cancelled'
                )
                """,
            ),
        )
        connection.execute(
            """
            CREATE UNIQUE INDEX idx_apify_key_pool_one_active
            ON apify_key_pool_members(workspace_id)
            WHERE status = 'active'
            """
        )
        connection.execute("DELETE FROM schema_migrations WHERE version = 23")
        connection.commit()
    except Exception:
        connection.rollback()
        raise
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def test_v21_backfill_uses_actor_evidence_and_keeps_transient_failures_retryable(
) -> None:
    evidence = {
        "route_id": "route-1",
        "candidate_id": "candidate-1",
        "actor_id": "publisher/actor",
        "build_id": "build-1",
        "build_number": "1.0.0",
        "manifest_hash": "a" * 64,
        "pricing_json": '{"minimalMaxTotalChargeUsd":0.01}',
    }
    assert _evidence_fingerprint(evidence) == actor_evidence_fingerprint(
        route_id="route-1",
        candidate_id="candidate-1",
        actor_id="publisher/actor",
        build_id="build-1",
        build_number="1.0.0",
        manifest_hash="a" * 64,
        pricing={"minimalMaxTotalChargeUsd": 0.01},
    )
    assert actor_evidence_fingerprint(
        route_id="route-1",
        candidate_id="candidate-1",
        actor_id="publisher/actor",
        build_id="build-1",
        build_number="1.0.0",
        manifest_hash="a" * 64,
        pricing={"minimalMaxTotalChargeUsd": 0.01},
        output_schema_hash="b" * 64,
    ) != actor_evidence_fingerprint(
        route_id="route-1",
        candidate_id="candidate-1",
        actor_id="publisher/actor",
        build_id="build-1",
        build_number="1.0.0",
        manifest_hash="a" * 64,
        pricing={"minimalMaxTotalChargeUsd": 0.01},
        output_schema_hash="c" * 64,
    )
    assert "apify_actor_contract_mismatch" in _DETERMINISTIC_CANARY_FAILURES
    assert "apify_actor_run_timed_out" not in _DETERMINISTIC_CANARY_FAILURES


def test_v21_migration_is_offline_backed_up_and_idempotent(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _downgrade_to_v20_shape(store)
    store.close()

    # Ordinary API/Worker initialization must leave the old shape untouched
    # and reach the readiness migration gate instead of referencing v21-only
    # columns while creating indexes.
    gated = ServiceStore(data_dir)
    gated.initialize()
    assert gated.apify_actor_resilience_v21_migration_required() is True
    assert "role" not in {
        str(row[1])
        for row in gated.connect().execute(
            "PRAGMA table_info(apify_key_pool_members)"
        ).fetchall()
    }
    gated.close()

    assert migrate(data_dir, apply=False)["required"] is True
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["applied"] is True
    assert result["backup_mode"] == "0o600"
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_violations"] == 0
    assert Path(result["backup"]).stat().st_mode & 0o777 == 0o600
    migrated = ServiceStore(data_dir)
    migrated.initialize()
    assert migrated.apify_actor_resilience_v21_migration_required() is False
    assert apify_actor_resilience_v21_schema_shapes_valid(migrated.connect())
    youtube = migrated.connect().execute(
        """
        SELECT min_runtime_healthy, min_publishers, admission_mode,
               freshness_enabled
        FROM apify_actor_route_profiles
        WHERE workspace_id = ? AND route_key = 'youtube/channel/items'
        """,
        (DEFAULT_WORKSPACE_ID,),
    ).fetchone()
    assert dict(youtube) == {
            "min_runtime_healthy": 2,
            "min_publishers": 2,
        "admission_mode": "standard",
        "freshness_enabled": 0,
    }
    assert migrated.connect().execute(
        """
        SELECT COUNT(*) AS count FROM apify_key_pool_members
        WHERE role = 'validation'
        """
    ).fetchone()["count"] == 0
    revision = migrated.connect().execute(
        "SELECT revision_id FROM apify_actor_adapter_revisions LIMIT 1"
    ).fetchone()
    assert revision is not None
    with pytest.raises(
        sqlite3.IntegrityError,
        match="configuration is immutable",
    ):
        migrated.connect().execute(
            """
            UPDATE apify_actor_adapter_revisions
            SET execution_mode = CASE execution_mode
                WHEN 'pinned' THEN 'current' ELSE 'pinned' END
            WHERE revision_id = (
                SELECT revision_id FROM apify_actor_adapter_revisions LIMIT 1
            )
            """
        )
    migrated.close()

    repeated = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert repeated["already_migrated"] is True
    assert repeated["applied"] is False


def test_v21_migration_refuses_nonterminal_actor_work(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _downgrade_to_v20_shape(store)
    store.connect().execute(
        """
        UPDATE apify_actor_runs
        SET status = 'start_outcome_unknown'
        WHERE id = (
            SELECT id FROM apify_actor_runs ORDER BY created_at LIMIT 1
        )
        """
    )
    row = store.connect().execute(
        "SELECT id FROM apify_actor_runs ORDER BY created_at LIMIT 1"
    ).fetchone()
    if row is None:
        secret = store.create_secret_ref(
            workspace_id=DEFAULT_WORKSPACE_ID,
            owner_user_id=None,
            name="Migration key",
            env_name="APIFY_MIGRATION_KEY",
            kind="provider",
            provider="apify",
        )
        store.initialize()
        member = store.connect().execute(
            "SELECT generation FROM apify_key_pool_state WHERE workspace_id = ?",
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone()
        store.connect().execute(
            """
            INSERT INTO apify_actor_runs (
                id, workspace_id, secret_id, secret_version,
                pool_generation, status, created_at, updated_at
            ) VALUES (
                'migration-unresolved-run', ?, ?, 1, ?,
                'start_outcome_unknown',
                '2026-08-11T00:00:00+00:00',
                '2026-08-11T00:00:00+00:00'
            )
            """,
            (DEFAULT_WORKSPACE_ID, secret["id"], int(member["generation"])),
        )
    store.connect().commit()
    store.close()

    try:
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    except RuntimeError as exc:
        assert "active ActorOps jobs" in str(exc)
    else:
        raise AssertionError("migration unexpectedly ignored unresolved Actor work")
