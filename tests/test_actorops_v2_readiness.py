from __future__ import annotations

from src.services.actorops.readiness import actorops_v2_enabled, require_actorops_v2_if_enabled
from src.storage.actorops_v2_schema import ACTOROPS_V2_MIGRATION_VERSION, V2_TABLES
from src.storage.service_store import ServiceStore


def test_disabled_flag_never_queries_global_26(tmp_path, monkeypatch) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    monkeypatch.delenv("ACTOROPS_V2_ENABLED", raising=False)
    statements: list[str] = []
    store.connect().set_trace_callback(statements.append)
    require_actorops_v2_if_enabled(store)
    assert not any("actor_routes_v2" in statement or "version = 26" in statement for statement in statements)
    assert not any("version = 25" in statement or "apify_actor_auto_pool_runs" in statement for statement in statements)
    assert actorops_v2_enabled() is False
    store.close()


def test_enabled_flag_requires_complete_global_26(tmp_path, monkeypatch) -> None:
    store = ServiceStore(tmp_path / "data")
    store.initialize()
    monkeypatch.setenv("ACTOROPS_V2_ENABLED", "true")
    require_actorops_v2_if_enabled(store)
    connection = store.connect()
    connection.execute("PRAGMA foreign_keys = OFF")
    connection.execute(f"DROP TABLE {V2_TABLES[-1]}")
    connection.commit()
    connection.execute("PRAGMA foreign_keys = ON")
    try:
        require_actorops_v2_if_enabled(store)
    except RuntimeError as error:
        assert "actorops_v2" in str(error)
    else:
        raise AssertionError("partial global 26 must fail closed")
    assert connection.execute(
        "SELECT name FROM schema_migrations WHERE version=?", (ACTOROPS_V2_MIGRATION_VERSION,)
    ).fetchone()
    store.close()
