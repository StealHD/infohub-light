from __future__ import annotations

import os
from pathlib import Path

import pytest

from scripts.migrate_route_price_caps import migrate
from src.storage.service_store import DEFAULT_WORKSPACE_ID, ServiceStore


def _seed_caps(data_dir: Path, *, x_cap: float = 0.02) -> dict[str, int]:
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    connection.execute(
        """UPDATE apify_actor_route_profiles
           SET per_run_cap_usd = CASE route_key
               WHEN 'youtube/channel/items' THEN 0.03
               WHEN 'instagram/profile/items' THEN 0.04
               WHEN 'x/profile' THEN ?
               ELSE per_run_cap_usd END""",
        (x_cap,),
    )
    connection.commit()
    generations = {
        str(row["route_key"]): int(row["generation"])
        for row in connection.execute(
            """SELECT route_key, generation FROM apify_actor_route_profiles
               WHERE route_key IN ('youtube/channel/items',
                                   'instagram/profile/items', 'x/profile')"""
        ).fetchall()
    }
    store.close()
    return generations


def _route_rows(data_dir: Path) -> dict[str, tuple[float, int]]:
    store = ServiceStore(data_dir)
    rows = {
        str(row["route_key"]): (
            float(row["per_run_cap_usd"]),
            int(row["generation"]),
        )
        for row in store.connect().execute(
            """SELECT route_key, per_run_cap_usd, generation
               FROM apify_actor_route_profiles
               WHERE route_key IN ('youtube/channel/items',
                                   'instagram/profile/items', 'x/profile')"""
        ).fetchall()
    }
    store.close()
    return rows


def test_price_cap_dry_run_requires_existing_database_and_stays_read_only(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    missing = tmp_path / "missing"
    with pytest.raises(RuntimeError, match="does not exist"):
        migrate(missing, apply=False)
    assert not missing.exists()

    monkeypatch.setenv("HORIZON_SQLITE_JOURNAL_MODE", "DELETE")
    data_dir = tmp_path / "data"
    generations = _seed_caps(data_dir, x_cap=0.02)
    database = data_dir / "service.db"
    before = database.read_bytes()
    for suffix in ("-wal", "-shm"):
        assert not Path(f"{database}{suffix}").exists()

    result = migrate(data_dir, apply=False)

    assert result["applied"] is False
    assert {row["route_key"]: row["action"] for row in result["routes"]} == {
        "instagram/profile/items": "would_update",
        "x/profile": "unchanged",
        "youtube/channel/items": "would_update",
    }
    assert database.read_bytes() == before
    assert {key: value[1] for key, value in _route_rows(data_dir).items()} == generations
    for suffix in ("-wal", "-shm"):
        assert not Path(f"{database}{suffix}").exists()


def test_price_cap_dry_run_reads_committed_wal_state(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setenv("HORIZON_SQLITE_JOURNAL_MODE", "WAL")
    data_dir = tmp_path / "data"
    store = ServiceStore(data_dir)
    store.initialize()
    connection = store.connect()
    connection.execute("PRAGMA wal_autocheckpoint = 0")
    connection.execute(
        """UPDATE apify_actor_route_profiles SET per_run_cap_usd = 0.07
           WHERE route_key = 'youtube/channel/items'"""
    )
    connection.commit()
    database = data_dir / "service.db"
    assert Path(f"{database}-wal").stat().st_size > 0

    result = migrate(data_dir, apply=False)

    youtube = next(
        row for row in result["routes"]
        if row["route_key"] == "youtube/channel/items"
    )
    assert youtube["current_cap_usd"] == 0.07
    assert youtube["action"] == "would_update"
    store.close()


def test_price_cap_apply_requires_offline_confirmation_before_backup(
    tmp_path: Path,
) -> None:
    data_dir = tmp_path / "data"
    _seed_caps(data_dir)

    with pytest.raises(RuntimeError, match="confirm API and Worker"):
        migrate(data_dir, apply=True, backup_dir=tmp_path / "backups")

    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize("active_kind", ["worker", "actor_job"])
def test_price_cap_apply_rejects_active_actorops_work_before_backup(
    tmp_path: Path, active_kind: str
) -> None:
    data_dir = tmp_path / "data"
    _seed_caps(data_dir)
    store = ServiceStore(data_dir)
    if active_kind == "worker":
        store.upsert_worker_heartbeat("price-cap-worker", "idle")
    else:
        owner = store.create_user(
            workspace_id=DEFAULT_WORKSPACE_ID,
            username="price-cap-owner",
            password="safe-test-password",
            role="owner",
        )
        store.connect().execute(
            """INSERT INTO fetch_jobs (
                   id, workspace_id, user_id, job_type, status, payload_json,
                   created_at, updated_at
               ) VALUES ('price-cap-active', ?, ?, 'apify_actor_discovery',
                         'queued', '{}', '2030-01-01T00:00:00+00:00',
                         '2030-01-01T00:00:00+00:00')""",
            (DEFAULT_WORKSPACE_ID, owner["id"]),
        )
        store.connect().commit()
    store.close()

    expected = "active workers" if active_kind == "worker" else "active ActorOps jobs"
    with pytest.raises(RuntimeError, match=expected):
        migrate(
            data_dir,
            apply=True,
            backup_dir=tmp_path / "backups",
            confirmed_stopped=True,
        )
    assert not (tmp_path / "backups").exists()


@pytest.mark.parametrize(
    ("x_cap", "expected_x_cap", "x_generation_bump"),
    [(0.02, 0.02, 0), (100.0, 0.10, 1)],
)
def test_price_cap_apply_backs_up_normalizes_and_is_idempotent(
    tmp_path: Path,
    x_cap: float,
    expected_x_cap: float,
    x_generation_bump: int,
) -> None:
    data_dir = tmp_path / "data"
    generations = _seed_caps(data_dir, x_cap=x_cap)

    result = migrate(
        data_dir,
        apply=True,
        backup_dir=tmp_path / "backups",
        confirmed_stopped=True,
    )

    assert result["applied"] is True
    assert result["backup_mode"] == "0o600"
    assert os.stat(result["backup"]).st_mode & 0o777 == 0o600
    rows = _route_rows(data_dir)
    assert {key: value[0] for key, value in rows.items()} == {
        "instagram/profile/items": 0.10,
        "x/profile": expected_x_cap,
        "youtube/channel/items": 0.10,
    }
    assert {key: value[1] for key, value in rows.items()} == {
        "instagram/profile/items": generations["instagram/profile/items"] + 1,
        "x/profile": generations["x/profile"] + x_generation_bump,
        "youtube/channel/items": generations["youtube/channel/items"] + 1,
    }

    again = migrate(data_dir, apply=True, confirmed_stopped=True)
    assert again["applied"] is False
    assert again["backup"] is None
    assert _route_rows(data_dir) == rows
