from __future__ import annotations

import hashlib
import sqlite3
from pathlib import Path

import pytest
from fastapi.testclient import TestClient

import scripts.migrate_actorops_v2 as migration_module
from scripts.migrate_actorops_v2 import migrate
from src.api.server import create_app
from src.services.worker_migration_gate import first_required_worker_startup_migration
from src.services.apify_actor_ops import ApifyActorOpsService
from src.storage.actorops_v2_schema import (
    ACTOROPS_V2_MIGRATION_NAME,
    ACTOROPS_V2_MIGRATION_VERSION,
    V2_TABLES,
)
from src.storage.apify_actor_auto_pool_schema import (
    install_schema as install_auto_pool_schema,
    mark_migrated as mark_auto_pool_migrated,
)
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _drop_v2(store: ServiceStore) -> None:
    connection = store.connect()
    connection.execute("PRAGMA foreign_keys = OFF")
    try:
        connection.execute("BEGIN IMMEDIATE")
        for table in reversed(V2_TABLES):
            connection.execute(f"DROP TABLE IF EXISTS {table}")
        connection.execute(
            "DELETE FROM schema_migrations WHERE version = ?",
            (ACTOROPS_V2_MIGRATION_VERSION,),
        )
        connection.commit()
    finally:
        connection.execute("PRAGMA foreign_keys = ON")


def _seed_v1_candidate(store: ServiceStore) -> tuple[str, str, str]:
    ops = ApifyActorOpsService(store)
    route = next(item for item in ops.list_routes() if item["platform"] == "youtube")
    route_id = str(route["route_id"])
    candidate_id = ops.ensure_candidate(route_id, actor_id="publisher/youtube-videos")
    revision_id = ops.create_adapter_revision(
        candidate_id=candidate_id,
        actor_id="publisher/youtube-videos",
        publisher="publisher",
        build_id="build-youtube",
        build_number="1.0.0",
        manifest={
            "version": 1,
            "actor_id": "publisher/youtube-videos",
            "build_number": "1.0.0",
            "input": {"startUrls": [{"url": {"$ref": "target.canonical_url"}}]},
            "output": {
                "native_id": {"pointers": ["/id"], "transforms": ["to_string"]},
                "url": {"pointers": ["/url"], "transforms": ["normalize_url"]},
                "published_at": {"pointers": ["/createdAt"], "transforms": ["parse_datetime"]},
                "title": {"pointers": ["/title"], "transforms": ["to_string"]},
                "source_native_id": {"pointers": ["/channelId"], "transforms": ["to_string"]},
            },
            "semantics": {
                "identity": {
                    "output_field": "source_native_id",
                    "target_ref": "target.native_id",
                    "match": "exact",
                },
                "url_host_allowlist": ["youtube.com"],
            },
        },
        lifecycle="static_valid",
    )
    connection = store.connect()
    connection.execute(
        "UPDATE apify_actor_adapter_revisions SET lifecycle = 'certified' WHERE revision_id = ?",
        (revision_id,),
    )
    connection.commit()
    connection.execute(
        """UPDATE apify_route_active_slots
           SET candidate_id = ?, revision_id = ?, updated_at = ?
           WHERE workspace_id = ? AND route_id = ? AND slot_name = 'primary'""",
        (
            candidate_id,
            revision_id,
            "2026-08-20T00:00:00+00:00",
            DEFAULT_WORKSPACE_ID,
            route_id,
        ),
    )
    connection.commit()
    source_id = store.create_source(
        workspace_id=DEFAULT_WORKSPACE_ID,
        scope="workspace",
        owner_user_id=None,
        source_type="apify_social",
        display_name="YouTube v2 backfill",
        config={"platform": "youtube", "kind": "channel", "target": "channel-v2"},
    )
    target_fingerprint = hashlib.sha256(b"channel-v2").hexdigest()
    binding = ops.bind_source(
        source_id=source_id,
        route_id=route_id,
        target_fingerprint=target_fingerprint,
        mode="primary",
    )
    connection.execute(
        "UPDATE apify_source_route_bindings SET active_candidate_id = ? WHERE binding_id = ?",
        (candidate_id, binding["binding_id"]),
    )
    connection.execute(
        """INSERT INTO apify_actor_attempts (
               id, workspace_id, route_key, route_generation, candidate_id,
               source_id, attempt_group_id, attempt_index, status,
               reserved_usd, actual_cost_usd, cost_final,
               adapter_revision_id, build_id, build_number, manifest_hash,
               target_fingerprint, created_at, started_at, terminal_at, updated_at
           ) VALUES (?, ?, ?, ?, ?, ?, ?, 1, 'succeeded', 0.01, 0.001, 1,
                     ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
        (
            "v1-terminal-attempt",
            DEFAULT_WORKSPACE_ID,
            str(route["route_key"]),
            int(route["generation"]),
            candidate_id,
            source_id,
            "v1-terminal-group",
            revision_id,
            "build-youtube",
            "1.0.0",
            str(connection.execute(
                "SELECT manifest_hash FROM apify_actor_adapter_revisions WHERE revision_id = ?",
                (revision_id,),
            ).fetchone()[0]),
            target_fingerprint,
            "2026-08-20T00:00:00+00:00",
            "2026-08-20T00:00:01+00:00",
            "2026-08-20T00:00:02+00:00",
            "2026-08-20T00:00:02+00:00",
        ),
    )
    connection.commit()
    return route_id, revision_id, source_id


def test_fresh_bootstrap_installs_v2_without_global_25(tmp_path: Path) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    connection = store.connect()
    assert connection.execute(
        "SELECT name FROM schema_migrations WHERE version = ?",
        (ACTOROPS_V2_MIGRATION_VERSION,),
    ).fetchone()[0] == ACTOROPS_V2_MIGRATION_NAME
    assert {row[0] for row in connection.execute(
        "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'actor_%_v2'"
    )} == set(V2_TABLES)
    assert connection.execute(
        "SELECT 1 FROM schema_migrations WHERE version = 25"
    ).fetchone() is None
    assert connection.execute("SELECT COUNT(*) FROM actor_routes_v2").fetchone()[0] == 3
    store.close()


def test_existing_v24_migration_backfills_and_is_idempotent(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    route_id, revision_id, source_id = _seed_v1_candidate(store)
    _drop_v2(store)
    store.close()

    preview = migrate(data_dir, apply=False)
    assert preview["status"] == "migration_required"
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert result["status"] == "applied"
    assert result["backup_mode"] == "0o600"

    migrated = ServiceStore(data_dir)
    connection = migrated.connect()
    candidate = connection.execute(
        "SELECT assignment_role, lifecycle FROM actor_candidates_v2 WHERE candidate_id = ?",
        (revision_id,),
    ).fetchone()
    assert tuple(candidate) == ("active", "certified")
    binding = connection.execute(
        "SELECT last_known_good_candidate_id FROM actor_source_bindings_v2 WHERE source_id = ?",
        (source_id,),
    ).fetchone()
    assert binding[0] == revision_id
    assert connection.execute("SELECT COUNT(*) FROM actor_attempts_v2").fetchone()[0] == 0
    assert connection.execute("SELECT COUNT(*) FROM actor_discovery_jobs_v2").fetchone()[0] == 0
    assert connection.execute(
        "SELECT COUNT(*) FROM actor_maintenance_policies_v2 WHERE enabled = 0"
    ).fetchone()[0] == 4
    assert connection.execute(
        "SELECT runtime_mode FROM actor_routes_v2 WHERE route_id = ?", (route_id,)
    ).fetchone()[0] == "disabled"
    migrated.close()
    assert migrate(data_dir, apply=True)["status"] == "already_migrated"


@pytest.mark.parametrize(
    "terminal_status", ("valid_empty", "actor_failed", "target_failed")
)
def test_migration_allows_settled_legacy_attempt_statuses(
    tmp_path: Path, terminal_status: str
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _seed_v1_candidate(store)
    store.connect().execute(
        "UPDATE apify_actor_attempts SET status=? WHERE id='v1-terminal-attempt'",
        (terminal_status,),
    )
    store.connect().commit()
    _drop_v2(store)
    store.close()

    assert migrate(data_dir, apply=False)["status"] == "migration_required"


def test_global_25_presence_and_damage_are_ignored(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _drop_v2(store)
    connection = store.connect()
    connection.execute("BEGIN IMMEDIATE")
    install_auto_pool_schema(connection)
    mark_auto_pool_migrated(connection, commit=False)
    connection.execute("ALTER TABLE apify_actor_auto_pool_runs DROP COLUMN error_code")
    connection.commit()
    store.close()
    assert migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")["status"] == "applied"


def test_migration_sql_never_targets_global_25(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _drop_v2(store)
    store.close()
    statements: list[str] = []
    real_connect = sqlite3.connect

    def traced_connect(*args, **kwargs):
        connection = real_connect(*args, **kwargs)
        connection.set_trace_callback(statements.append)
        return connection

    monkeypatch.setattr(migration_module.sqlite3, "connect", traced_connect)
    assert migrate(data_dir, apply=False)["status"] == "migration_required"
    joined = "\n".join(statements).casefold()
    assert "version = 25" not in joined
    assert "apify_actor_auto_pool_runs" not in joined


def test_migration_refuses_active_or_unsettled_work_without_backup(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _drop_v2(store)
    store.connect().execute(
        """INSERT INTO apify_actor_runs (
               id, workspace_id, purpose, secret_id, secret_version,
               pool_generation, status, created_at, updated_at,
               charge_reserved_usd, charge_final
           ) VALUES ('v2-blocker', ?, 'validation', 'secret-ref', 1, 1,
                     'start_outcome_unknown', ?, ?, 0.05, 0)""",
        (DEFAULT_WORKSPACE_ID, "2026-08-20T00:00:00+00:00", "2026-08-20T00:00:00+00:00"),
    )
    store.connect().commit()
    store.close()
    result = migrate(data_dir, apply=False)
    assert result["status"] == "blocked"
    with pytest.raises(RuntimeError, match="ActorOps work must settle"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert not (tmp_path / "backups").exists()


def test_partial_v2_schema_fails_closed(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _drop_v2(store)
    store.connect().execute("CREATE TABLE actor_routes_v2 (route_id TEXT PRIMARY KEY)")
    store.connect().commit()
    store.close()
    with pytest.raises(RuntimeError, match="partial ActorOps v2 schema"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")


def test_missing_v2_does_not_gate_v1_api_or_worker(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _drop_v2(store)
    store.create_user(
        workspace_id=DEFAULT_WORKSPACE_ID,
        username="v2-schema-owner",
        password="safe-test-password",
        role="owner",
    )
    assert first_required_worker_startup_migration(store) is None
    store.close()
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    with TestClient(create_app(data_dir=data_dir, static_dir=static_dir)) as client:
        assert client.get("/api/health/ready").status_code == 200


def test_enabled_v2_conditionally_gates_api_and_worker(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _drop_v2(store)
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "true")
    assert first_required_worker_startup_migration(store) == "actorops_v2"
    store.close()
    static_dir = tmp_path / "static"
    static_dir.mkdir()
    (static_dir / "index.html").write_text("<!doctype html>", encoding="utf-8")
    with TestClient(create_app(data_dir=data_dir, static_dir=static_dir)) as client:
        response = client.get("/api/health/ready")
        assert response.status_code == 503
        assert response.json()["error"]["code"] == "migration_required"


def test_postcheck_failure_restores_pre_migration_database(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    _drop_v2(store)
    before_routes = store.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_route_profiles"
    ).fetchone()[0]
    store.close()
    real_shape_check = migration_module.schema_shapes_valid
    calls = 0

    def fail_postcheck(connection):
        nonlocal calls
        calls += 1
        return False if calls >= 1 else real_shape_check(connection)

    monkeypatch.setattr(migration_module, "schema_shapes_valid", fail_postcheck)
    with pytest.raises(RuntimeError, match="post-migration checks failed"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    restored = ServiceStore(data_dir)
    assert restored.connect().execute(
        "SELECT COUNT(*) FROM apify_actor_route_profiles"
    ).fetchone()[0] == before_routes
    assert restored.connect().execute(
        "SELECT 1 FROM schema_migrations WHERE version = 26"
    ).fetchone() is None
    restored.close()
