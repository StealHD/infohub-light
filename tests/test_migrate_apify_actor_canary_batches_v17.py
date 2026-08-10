from __future__ import annotations

import hashlib
import sqlite3

import pytest

from scripts.migrate_apify_actor_canary_batches_v17 import migrate
from src.services.apify_actor_canary import next_reference_fingerprint
from src.services.apify_actor_ops import (
    ApifyActorOpsService,
    PAID_CANARY_CONFIRMATION,
)
from src.storage.service_store import (
    DEFAULT_WORKSPACE_ID,
    ServiceStore,
    apify_actor_canary_batches_v17_schema_shapes_valid,
)


def _manifest(actor_id: str, build_number: str) -> dict:
    return {
        "version": 1,
        "actor_id": actor_id,
        "build_number": build_number,
        "input": {"url": {"$ref": "target.canonical_url"}},
        "output": {
            "native_id": {"pointers": ["/id"]},
            "url": {
                "pointers": ["/url"],
                "transforms": ["normalize_url"],
            },
            "published_at": {
                "pointers": ["/publishedAt"],
                "transforms": ["parse_datetime"],
            },
            "title": {"pointers": ["/title"]},
            "source_native_id": {"pointers": ["/channelId"]},
        },
        "semantics": {
            "identity": {
                "output_field": "source_native_id",
                "target_ref": "target.native_id",
                "match": "exact",
            },
            "url_host_allowlist": ["youtube.com"],
        },
    }


def _remove_v17_marker_and_tables(store: ServiceStore) -> None:
    connection = store.connect()
    connection.execute("DROP TABLE apify_actor_canary_batch_items")
    connection.execute("DROP TABLE apify_actor_canary_batches")
    connection.execute("DELETE FROM schema_migrations WHERE version = 19")
    connection.commit()


def test_v17_schema_validation_accepts_evolved_batch_cost_cap() -> None:
    connection = sqlite3.connect(":memory:")
    try:
        connection.executescript(
            """
            CREATE TABLE apify_actor_validations (
                cost_final INTEGER NOT NULL CHECK(cost_final IN (0, 1)),
                counts_toward_canary INTEGER NOT NULL
                    CHECK(counts_toward_canary IN (0, 1))
            );
            CREATE TABLE apify_actor_canary_batches (
                max_candidates INTEGER NOT NULL
                    CHECK(max_candidates BETWEEN 1 AND 3),
                max_total_charge_usd REAL NOT NULL
                    CHECK(max_total_charge_usd <= 0.30),
                workspace_id TEXT NOT NULL,
                approval_key_hash TEXT NOT NULL,
                UNIQUE(workspace_id, approval_key_hash)
            );
            CREATE TABLE apify_actor_canary_batch_items (
                status TEXT NOT NULL CHECK(status IN (
                    'planned', 'preflight_passed', 'preflight_failed',
                    'queued', 'running', 'succeeded', 'failed',
                    'not_needed_no_charge', 'blocked_unknown_start'
                ))
            );
            """
        )

        assert apify_actor_canary_batches_v17_schema_shapes_valid(connection)
    finally:
        connection.close()


def test_v17_offline_migration_adds_batch_ledger_and_backup(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _remove_v17_marker_and_tables(store)
    store.close()

    dry_run = migrate(data_dir, apply=False)
    assert dry_run["required"] is True
    result = migrate(
        data_dir,
        apply=True,
        backup_dir=tmp_path / "backups",
    )

    assert result["applied"] is True
    assert result["backup_mode"] == "0o600"
    assert result["integrity_check"] == "ok"
    assert result["foreign_key_violations"] == 0
    migrated = ServiceStore(data_dir)
    migrated.initialize()
    assert migrated.apify_actor_canary_batches_v17_migration_required() is False
    tables = {
        str(row["name"])
        for row in migrated.connect().execute(
            "SELECT name FROM sqlite_master WHERE type = 'table'"
        ).fetchall()
    }
    assert {
        "apify_actor_canary_batches",
        "apify_actor_canary_batch_items",
    } <= tables
    validation_columns = {
        str(row["name"])
        for row in migrated.connect().execute(
            "PRAGMA table_info(apify_actor_validations)"
        ).fetchall()
    }
    assert {"cost_final", "counts_toward_canary"} <= validation_columns
    assert migrated.connect().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert migrated.connect().execute("PRAGMA foreign_key_check").fetchall() == []
    migrated.close()


def test_v17_repairs_proven_start_rejection_as_zero_cost(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    ops = ApifyActorOpsService(store)
    route = next(
        item
        for item in ops.list_routes()
        if item["route_key"] == "youtube/channel/items"
    )
    run = ops.create_discovery_run(
        str(route["route_id"]),
        trigger_reason="migration-test",
        expected_generation=int(route["generation"]),
    )
    actor_id = "publisher-gone/exact-build"
    candidate_id = ops.ensure_candidate(str(route["route_id"]), actor_id=actor_id)
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id=actor_id,
        publisher="publisher-gone",
        build_id="build-gone",
        build_number="0.0.900",
        manifest=_manifest(actor_id, "0.0.900"),
        input_schema_hash=hashlib.sha256(b"input").hexdigest(),
        output_schema_hash=hashlib.sha256(b"output").hexdigest(),
        lifecycle="static_valid",
        discovery_run_id=str(run["run_id"]),
    )
    ops.update_discovery_run(
        str(run["run_id"]),
        expected_stage="queued",
        stage="awaiting_canary_approval",
    )
    reference_fingerprint = next_reference_fingerprint(
        store,
        workspace_id=DEFAULT_WORKSPACE_ID,
        platform="youtube",
        route_id=str(route["route_id"]),
        revision_id=revision_id,
    )
    validation = ops.approve_revision_canary(
        str(route["route_id"]),
        revision_id,
        expected_generation=int(route["generation"]),
        approval_id="migration-no-start-approval",
        confirmation=PAID_CANARY_CONFIRMATION,
        max_cost_usd=0.02,
        reference_fingerprint=reference_fingerprint,
        discovery_run_id=str(run["run_id"]),
    )
    revision = ops.get_revision(revision_id)
    now = "2026-08-01T00:00:00+00:00"
    attempt_id = "migration-no-start-attempt"
    store.connect().execute(
        """
        INSERT INTO apify_actor_attempts (
            id, workspace_id, route_key, route_generation, candidate_id,
            source_id, attempt_group_id, attempt_index, status,
            semantic_outcome, reserved_usd, actual_cost_usd, cost_final,
            adapter_revision_id, build_id, build_number, manifest_hash,
            target_fingerprint, created_at, started_at, terminal_at, updated_at
        ) VALUES (
            ?, ?, ?, ?, ?, NULL, 'migration:no-start', 1,
            'actor_failed', 'apify_actor_start_rejected', 0.02, NULL, 0,
            ?, ?, ?, ?, ?, ?, ?, ?, ?
        )
        """,
        (
            attempt_id,
            DEFAULT_WORKSPACE_ID,
            route["route_key"],
            route["generation"],
            candidate_id,
            revision_id,
            revision["build_id"],
            revision["build_number"],
            revision["manifest_hash"],
            reference_fingerprint,
            now,
            now,
            now,
            now,
        ),
    )
    store.connect().execute(
        """
        INSERT INTO apify_actor_runs (
            id, workspace_id, logical_run_id, secret_id, secret_version,
            pool_generation, status, last_error_code, created_at, started_at,
            terminal_at, updated_at, charge_reserved_usd,
            charge_actual_usd, charge_final
        ) VALUES (
            'migration-no-start-run', ?, ?, 'secret-redacted', 1, 1,
            'start_rejected', 'apify_start_http_403', ?, ?, ?, ?, 0, NULL, 0
        )
        """,
        (DEFAULT_WORKSPACE_ID, attempt_id, now, now, now, now),
    )
    store.connect().execute(
        """
        UPDATE apify_actor_validations
        SET status = 'failed', semantic_outcome = 'apify_actor_start_rejected',
            attempt_id = ?, cost_usd = 0.02, completed_at = ?
        WHERE validation_id = ?
        """,
        (attempt_id, now, validation["validation_id"]),
    )
    _remove_v17_marker_and_tables(store)
    store.close()

    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert result["repairs"]["no_start_repaired"] == 1
    migrated = ServiceStore(data_dir)
    migrated.initialize()
    repaired = migrated.connect().execute(
        """
        SELECT validation.cost_usd, validation.cost_final,
               validation.counts_toward_canary, validation.semantic_outcome,
               attempt.status AS attempt_status,
               run.charge_actual_usd, run.charge_final,
               revision.lifecycle, candidate.state
        FROM apify_actor_validations AS validation
        JOIN apify_actor_attempts AS attempt ON attempt.id = validation.attempt_id
        JOIN apify_actor_runs AS run ON run.logical_run_id = attempt.id
        JOIN apify_actor_adapter_revisions AS revision
          ON revision.revision_id = validation.revision_id
        JOIN apify_actor_candidates AS candidate
          ON candidate.id = revision.candidate_id
        WHERE validation.validation_id = ?
        """,
        (validation["validation_id"],),
    ).fetchone()
    assert repaired["cost_usd"] == 0
    assert repaired["cost_final"] == 1
    assert repaired["counts_toward_canary"] == 0
    assert repaired["semantic_outcome"] == "apify_actor_revision_unavailable"
    assert repaired["attempt_status"] == "cancelled"
    assert repaired["charge_actual_usd"] == 0
    assert repaired["charge_final"] == 1
    assert repaired["lifecycle"] == "rejected"
    assert repaired["state"] == "disabled"
    migrated.close()


def test_v17_migration_refuses_active_actor_job_before_backup(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="migration-owner",
        password="safe-test-password",
        role="owner",
    )
    _remove_v17_marker_and_tables(store)
    store.connect().execute(
        """
        INSERT INTO fetch_jobs (
            id, workspace_id, user_id, job_type, status, payload_json,
            priority, attempts, max_attempts, created_at, updated_at
        ) VALUES (
            'active-canary-batch-test', ?, ?, 'apify_actor_validation',
            'queued', '{}', 100, 0, 1,
            '2026-08-01T00:00:00+00:00', '2026-08-01T00:00:00+00:00'
        )
        """,
        (DEFAULT_WORKSPACE_ID, owner["id"]),
    )
    store.connect().commit()
    store.close()

    with pytest.raises(RuntimeError, match="active ActorOps jobs"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert not (tmp_path / "backups").exists()


def test_v17_migration_restores_backup_when_schema_verification_fails(
    tmp_path,
    monkeypatch,
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    owner = store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="migration-restore-owner",
        password="safe-test-password",
        role="owner",
    )
    _remove_v17_marker_and_tables(store)
    store.close()

    monkeypatch.setattr(
        "scripts.migrate_apify_actor_canary_batches_v17."
        "apify_actor_canary_batches_v17_schema_shapes_valid",
        lambda _connection: False,
    )
    with pytest.raises(RuntimeError, match="batch schema validation"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    restored = sqlite3.connect(data_dir / "service.db")
    try:
        assert restored.execute(
            "SELECT username FROM users WHERE id = ?",
            (owner["id"],),
        ).fetchone() == ("migration-restore-owner",)
        tables = {
            str(row[0])
            for row in restored.execute(
                "SELECT name FROM sqlite_master WHERE type = 'table'"
            ).fetchall()
        }
        assert "apify_actor_canary_batches" not in tables
        assert "apify_actor_canary_batch_items" not in tables
        assert restored.execute(
            "SELECT 1 FROM schema_migrations WHERE version = 19"
        ).fetchone() is None
        assert restored.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert restored.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        restored.close()
