from __future__ import annotations

import sqlite3
from pathlib import Path

from scripts.migrate_system_settings_v31 import migrate, preview
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore
from src.storage.system_settings_v31_schema import (
    MIGRATION_CHECKSUM,
    MIGRATION_NAME,
    MIGRATION_VERSION,
    migration_marker_exists,
    schema_shapes_valid,
)


def _restore_global_30(data_dir: Path) -> None:
    connection = sqlite3.connect(data_dir / "service.db")
    connection.execute("PRAGMA foreign_keys=ON")
    try:
        connection.execute("DROP TRIGGER trg_workspace_system_settings_seed")
        connection.execute("DROP TABLE system_setting_change_proposals")
        connection.execute("DROP TABLE workspace_system_settings")
        connection.execute(
            "DELETE FROM schema_migrations WHERE version=?", (MIGRATION_VERSION,)
        )
        connection.commit()
    finally:
        connection.close()


def test_global_31_is_explicit_atomic_and_idempotent(tmp_path: Path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    store.close()
    _restore_global_30(data_dir)

    assert preview(data_dir)["status"] == "migration_required"
    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")
    assert result["status"] == "applied"
    assert result["workspace_rows_seeded"] == 1
    assert result["backup_mode"] == "0o600"

    connection = sqlite3.connect(data_dir / "service.db")
    try:
        marker = connection.execute(
            "SELECT name, checksum FROM schema_migrations WHERE version=?",
            (MIGRATION_VERSION,),
        ).fetchone()
        assert marker == (MIGRATION_NAME, MIGRATION_CHECKSUM)
        assert migration_marker_exists(connection)
        assert schema_shapes_valid(connection)
        assert connection.execute(
            """SELECT generation, overrides_json FROM workspace_system_settings
               WHERE workspace_id=?""",
            (DEFAULT_WORKSPACE_ID,),
        ).fetchone() == (1, "{}")
        assert connection.execute("PRAGMA integrity_check").fetchone() == ("ok",)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    finally:
        connection.close()

    assert migrate(data_dir, apply=True)["status"] == "already_migrated"
