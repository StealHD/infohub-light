"""Offline catalog migration preserves populated databases and rejects uncertain shape."""
import sqlite3
from contextlib import closing
from concurrent.futures import ThreadPoolExecutor
from datetime import datetime, timezone
from pathlib import Path

import pytest

from test_source_identity_isolation import identity_store, source  # noqa: F401
from src.storage import source_identity_schema as schema
from src.storage.service_store import ServiceStore


@pytest.fixture
def legacy_store(identity_store):
    store, workspace, users = identity_store
    original = source(store, workspace, users[0])
    subscription = store.create_subscription(user_id=users[0], source_id=original["id"])
    conn = store.connect()
    conn.execute("""INSERT INTO user_source_health(subscription_id,workspace_id,user_id,source_id,
        status,last_attempt_at,created_at,updated_at) VALUES(?,?,?,?,'healthy','now','now','now')""",
        (subscription["id"], workspace, users[0], original["id"]))
    for name in schema.INDEX_SQL:
        conn.execute(f"DROP INDEX {name}")
    for name in schema.TRIGGER_SQL:
        conn.execute(f"DROP TRIGGER {name}")
    conn.execute("DELETE FROM schema_migrations WHERE version=46")
    conn.execute(schema.LEGACY_SQL)
    conn.commit()
    return store, workspace, users, original


def business_rows(conn):
    return {name: conn.execute(f"SELECT * FROM {name} ORDER BY 1").fetchall()
        for name in ("source_catalog", "user_subscriptions", "users", "user_source_health", "fetch_jobs", "actor_source_bindings_v2")}


def test_preview_preserves_database_bytes_and_apply_preserves_rows(legacy_store):
    from scripts.migrate_source_identity_v46 import migrate
    store, _, _, original = legacy_store
    conn = store.connect()
    before = business_rows(conn)
    path = store.data_dir / "service.db"
    conn.execute("PRAGMA wal_checkpoint(TRUNCATE)")
    bytes_before = path.read_bytes()
    assert migrate(store.data_dir)["status"] == "migration_required"
    assert path.read_bytes() == bytes_before
    assert not (store.data_dir / "backups").exists()
    result = migrate(store.data_dir, apply=True, services_stopped=True)
    backup = Path(result["backup"])
    assert backup.stat().st_mode & 0o777 == 0o600
    assert schema.ready(conn)
    assert business_rows(conn) == before
    assert store.get_source(original["id"]) == original
    with closing(sqlite3.connect(backup)) as old:
        assert not schema.ready(old)
        assert schema.preflight(old)["status"] == "migration_required"
        assert old.execute("PRAGMA integrity_check").fetchone()[0] == "ok"
        assert not old.execute("PRAGMA foreign_key_check").fetchall()
    changes = conn.total_changes
    assert migrate(store.data_dir, apply=True)["status"] == "already_migrated"
    assert conn.total_changes == changes
    assert len(list(backup.parent.glob("*.db"))) == 1


def test_existing_initialize_never_installs_or_repairs_identity(legacy_store):
    store, workspace, users, original = legacy_store
    store.initialize()
    assert not schema.ready(store.connect())
    with pytest.raises(schema.SourceIdentityMigrationRequiredError):
        source(store, workspace, users[1])
    with pytest.raises(schema.SourceIdentityMigrationRequiredError):
        store.update_source(original["id"], display_name="changed")
    assert store.get_source(original["id"]) == original
    schema.apply_migration(store.connect())
    source(store, workspace, users[1])
    store.initialize()
    assert schema.ready(store.connect())
    store.connect().execute("DROP INDEX idx_source_catalog_shared_identity")
    store.connect().commit()
    store.initialize()
    assert not schema.ready(store.connect())


@pytest.mark.parametrize("corruption", ["marker", "partial", "unknown", "predicate", "owner", "duplicates"])
def test_invalid_legacy_state_fails_closed(legacy_store, corruption):
    store, _, _, original = legacy_store
    conn = store.connect()
    if corruption == "marker":
        conn.execute("INSERT INTO schema_migrations VALUES(46,'other','wrong','now')")
    elif corruption == "partial":
        conn.execute(next(iter(schema.INDEX_SQL.values())))
    elif corruption == "unknown":
        conn.execute("CREATE UNIQUE INDEX mystery_identity ON source_catalog(source_key)")
    elif corruption == "predicate":
        conn.execute(f"DROP INDEX {schema.LEGACY_INDEX}")
        conn.execute(f"CREATE UNIQUE INDEX {schema.LEGACY_INDEX} ON source_catalog(workspace_id,source_key)")
    elif corruption == "owner":
        conn.execute("UPDATE source_catalog SET owner_user_id=NULL WHERE id=?", (original["id"],))
    else:
        conn.execute(f"DROP INDEX {schema.LEGACY_INDEX}")
        conn.execute("CREATE UNIQUE INDEX idx_source_catalog_workspace_source_key ON source_catalog(id)")
    conn.commit()
    before = list(conn.iterdump())
    with pytest.raises(ValueError):
        schema.apply_migration(conn)
    assert list(conn.iterdump()) == before


@pytest.mark.parametrize("kind", ["index", "trigger", "marker"])
def test_ready_validates_exact_marker_index_and_trigger_shape(identity_store, kind):
    store, _, _ = identity_store
    conn = store.connect()
    assert schema.ready(conn)
    if kind == "index":
        conn.execute("DROP INDEX idx_source_catalog_shared_identity")
        conn.execute("CREATE UNIQUE INDEX idx_source_catalog_shared_identity ON source_catalog(workspace_id,source_key) WHERE scope='public'")
    elif kind == "trigger":
        conn.execute("DROP TRIGGER source_catalog_private_owner_update")
        conn.execute("CREATE TRIGGER source_catalog_private_owner_update BEFORE UPDATE ON source_catalog BEGIN SELECT 1; END")
    else:
        conn.execute("UPDATE schema_migrations SET checksum='wrong' WHERE version=46")
    conn.commit()
    assert not schema.ready(conn)
    with pytest.raises(ValueError):
        schema.apply_migration(conn)


def test_offline_acknowledgement_and_worker_guard(legacy_store, monkeypatch):
    from scripts import migrate_source_identity_v46 as script
    store = legacy_store[0]
    with pytest.raises(ValueError, match="Stop API and Worker"):
        script.migrate(store.data_dir, apply=True)
    monkeypatch.setattr(script, "active_workers_fail_closed", lambda _: ["private-worker-id"])
    assert script.migrate(store.data_dir)["blocker_counts"]["workers"] == 1
    with pytest.raises(ValueError, match="Stop API and Worker"):
        script.migrate(store.data_dir, apply=True, services_stopped=True)
    assert not (store.data_dir / "backups").exists()


@pytest.mark.parametrize("migration_committed", [False, True])
def test_script_failure_preserves_other_connection_commit(legacy_store, monkeypatch, migration_committed):
    from scripts import migrate_source_identity_v46 as script
    store, _, _, original = legacy_store
    store.close()
    apply_original = script.apply_migration
    database = store.data_dir / "service.db"

    def fail_after_other_writer(conn):
        if migration_committed:
            apply_original(conn)
        with closing(sqlite3.connect(database)) as other, other:
            other.execute("UPDATE source_catalog SET display_name='concurrent update' WHERE id=?", (original["id"],))
        raise ValueError("injected failure after concurrent commit")

    monkeypatch.setattr(script, "apply_migration", fail_after_other_writer)
    with pytest.raises(ValueError, match="injected"):
        script.migrate(store.data_dir, apply=True, services_stopped=True)
    assert schema.ready(store.connect()) is migration_committed
    assert store.get_source(original["id"])["display_name"] == "concurrent update"
    backups = list((store.data_dir / "backups").glob("*.db"))
    assert len(backups) == 1
    with closing(sqlite3.connect(backups[0])) as backup:
        assert not schema.ready(backup)
        assert backup.execute("SELECT display_name FROM source_catalog WHERE id=?", (original["id"],)).fetchone()[0] == original["display_name"]


def test_restarted_worker_after_backup_preserves_concurrent_write(legacy_store, monkeypatch):
    from scripts import migrate_source_identity_v46 as script
    store, _, _, original = legacy_store
    store.close()
    guard = script.active_workers_fail_closed
    calls = 0

    def restart_before_final_guard(database):
        nonlocal calls
        calls += 1
        if calls == 3:
            now = datetime.now(timezone.utc).isoformat()
            with closing(sqlite3.connect(database)) as other, other:
                other.execute("UPDATE source_catalog SET display_name='worker update' WHERE id=?", (original["id"],))
                other.execute("""INSERT INTO worker_heartbeats(worker_id,state,started_at,heartbeat_at,updated_at)
                    VALUES('restarted-worker','idle',?,?,?)""", (now, now, now))
        return guard(database)

    monkeypatch.setattr(script, "active_workers_fail_closed", restart_before_final_guard)
    with pytest.raises(ValueError, match="Stop API and Worker"):
        script.migrate(store.data_dir, apply=True, services_stopped=True)
    assert calls == 3
    assert not schema.ready(store.connect())
    assert store.get_source(original["id"])["display_name"] == "worker update"
    assert store.connect().execute("SELECT count(*) FROM worker_heartbeats").fetchone()[0] == 1
    assert len(list((store.data_dir / "backups").glob("*.db"))) == 1


def test_concurrent_apply_is_idempotent(legacy_store):
    from scripts.migrate_source_identity_v46 import migrate
    store = legacy_store[0]
    store.close()
    with ThreadPoolExecutor(max_workers=2) as executor:
        results = list(executor.map(lambda _: migrate(store.data_dir, apply=True, services_stopped=True), range(2)))
    assert sorted(row["status"] for row in results) == ["already_migrated", "applied"]
    assert len(list((store.data_dir / "backups").glob("*.db"))) == 1


def test_legacy_deleted_account_tombstone_migrates_without_rewriting_rows(legacy_store):
    store, _, users, original = legacy_store
    store.delete_user(users[0], reassigned_user_id=store.get_user_by_username("owner")["id"])
    tombstone = store.get_source(original["id"])
    assert schema.preflight(store.connect())["status"] == "migration_required"
    schema.apply_migration(store.connect())
    assert schema.ready(store.connect())
    assert store.get_source(original["id"]) == tombstone


def test_duplicate_identity_count_and_unknown_expression_index_fail_closed(legacy_store):
    store, _, _, _ = legacy_store
    conn = store.connect()
    conn.execute(f"DROP INDEX {schema.LEGACY_INDEX}")
    columns = [row[1] for row in conn.execute("PRAGMA table_info(source_catalog)")]
    selected = ["'duplicate'" if name == "id" else name for name in columns]
    conn.execute(f"INSERT INTO source_catalog({','.join(columns)}) SELECT {','.join(selected)} FROM source_catalog")
    conn.commit()
    assert schema.invalid_row_counts(conn)["duplicate_identities"] == 1
    with pytest.raises(ValueError):
        schema.apply_migration(conn)
    conn.execute("DELETE FROM source_catalog WHERE id='duplicate'")
    conn.execute(schema.LEGACY_SQL)
    conn.execute("CREATE UNIQUE INDEX unexpected_identity ON source_catalog(lower(source_key))")
    conn.commit()
    with pytest.raises(ValueError, match="unknown"):
        schema.apply_migration(conn)


def test_old_schema_rollback_requires_backup_after_new_identities(legacy_store):
    from scripts.migrate_source_identity_v46 import migrate
    from scripts.migrate_apify_actor_ops_v15 import _restore_database
    store, workspace, users, original = legacy_store
    result = migrate(store.data_dir, apply=True, services_stopped=True)
    added = source(store, workspace, users[1])
    store.create_subscription(user_id=users[1], source_id=added["id"])
    with pytest.raises(sqlite3.IntegrityError):
        store.connect().execute(schema.LEGACY_SQL)
    store.connect().rollback()
    store.close()
    path = store.data_dir / "service.db"
    _restore_database(backup_path=Path(result["backup"]), db_path=path,
                      original_mode=path.stat().st_mode & 0o777)
    assert not schema.ready(store.connect())
    assert store.get_source(original["id"]) == original
    assert store.get_source(added["id"]) is None
    assert store.connect().execute("SELECT count(*) FROM user_subscriptions").fetchone()[0] == 1


def test_migration_failure_before_commit_rolls_back_all_ddl(legacy_store, monkeypatch):
    store = legacy_store[0]
    conn = store.connect()
    before = list(conn.iterdump())
    monkeypatch.setattr(schema, "require_ready", lambda _: (_ for _ in ()).throw(ValueError("injected failure")))
    with pytest.raises(ValueError, match="injected"):
        schema.apply_migration(conn)
    assert list(conn.iterdump()) == before


@pytest.mark.parametrize("correct_shape", [True, False])
def test_historical_source_reference_index_is_preserved_only_with_exact_shape(legacy_store, correct_shape):
    store, _, _, _ = legacy_store
    conn = store.connect()
    conn.execute(schema.REFERENCE_SQL if correct_shape else
        f"CREATE UNIQUE INDEX {schema.REFERENCE_INDEX} ON source_catalog(source_key)")
    conn.commit()
    original = conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (schema.REFERENCE_INDEX,)).fetchone()[0]
    if not correct_shape:
        with pytest.raises(ValueError, match="unknown source identity indexes"):
            schema.apply_migration(conn)
        return
    schema.apply_migration(conn)
    assert schema.ready(conn)
    assert conn.execute("SELECT sql FROM sqlite_master WHERE name=?", (schema.REFERENCE_INDEX,)).fetchone()[0] == original
