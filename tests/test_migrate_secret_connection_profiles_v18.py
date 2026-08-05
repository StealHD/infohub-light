from __future__ import annotations

from scripts.migrate_secret_connection_profiles_v18 import migrate
from src.storage.service_store import ServiceStore


def _remove_base_url_column(data_dir) -> None:
    store = ServiceStore(data_dir)
    store.initialize()
    store.connect().execute("ALTER TABLE secret_refs DROP COLUMN base_url")
    store.connect().commit()
    store.close()


def test_v18_offline_migration_adds_per_key_base_url(tmp_path) -> None:
    data_dir = tmp_path / "data"
    _remove_base_url_column(data_dir)

    preview = migrate(data_dir, apply=False)
    assert preview["required"] is True

    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result["applied"] is True
    assert result["backup_mode"] == "0o600"
    store = ServiceStore(data_dir)
    store.initialize()
    columns = {
        row["name"]
        for row in store.connect().execute("PRAGMA table_info(secret_refs)").fetchall()
    }
    assert "base_url" in columns
    assert store.connect().execute("PRAGMA integrity_check").fetchone()[0] == "ok"
    assert store.connect().execute("PRAGMA foreign_key_check").fetchall() == []
    store.close()


def test_v18_migration_is_idempotent(tmp_path) -> None:
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    store.close()

    result = migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert result == {
        "required": False,
        "applied": False,
        "database": str(data_dir / "service.db"),
    }
