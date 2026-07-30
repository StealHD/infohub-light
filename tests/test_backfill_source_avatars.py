from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.backfill_source_avatars import main
from src.services.source_avatar import SourceAvatarRefresh
from src.storage.service_store import ServiceStore


def test_backfill_defaults_to_network_free_dry_run(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "owner-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="github_release",
        display_name="Release",
        config={"owner": "openai", "repo": "codex"},
    )
    store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Paid profile",
        config={"platform": "x", "kind": "profile", "target": "openai"},
    )
    store.close()
    monkeypatch.setattr(
        sys,
        "argv",
        ["backfill_source_avatars.py", "--data-dir", str(tmp_path)],
    )

    assert main() == 0

    result = json.loads(capsys.readouterr().out)
    assert result["mode"] == "dry_run"
    assert result["status_counts"] == {
        "eligible": 1,
        "paid_source_skipped": 1,
    }
    verify = ServiceStore(tmp_path)
    assert verify.connect().execute(
        "SELECT COUNT(*) FROM media_assets"
    ).fetchone()[0] == 0
    verify.close()


def test_backfill_apply_requires_explicit_free_only(monkeypatch):
    monkeypatch.setattr(
        sys,
        "argv",
        ["backfill_source_avatars.py", "--apply"],
    )

    with pytest.raises(SystemExit, match="--apply requires --free-only"):
        main()


def test_backfill_apply_never_routes_paid_sources_to_avatar_resolution(
    tmp_path,
    monkeypatch,
    capsys,
):
    monkeypatch.setenv("HORIZON_AUTH_USER", "owner")
    monkeypatch.setenv("HORIZON_AUTH_PASSWORD", "owner-password")
    store = ServiceStore(tmp_path)
    store.initialize()
    workspace = store.get_default_workspace()
    owner = store.get_user_by_username("owner")
    free_source_id = store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="github_release",
        display_name="Release",
        config={"owner": "openai", "repo": "codex"},
    )
    store.create_source(
        workspace_id=workspace["id"],
        scope="private",
        owner_user_id=owner["id"],
        source_type="apify_social",
        display_name="Paid profile",
        config={"platform": "x", "kind": "profile", "target": "openai"},
    )
    store.close()
    calls = []

    class AvatarService:
        def __init__(self, *_args, **_kwargs):
            pass

        def refresh_sources(
            self,
            *,
            workspace_id,
            source_ids,
            resolve_missing_source_ids,
        ):
            calls.append(
                (workspace_id, tuple(source_ids), tuple(resolve_missing_source_ids))
            )
            return [SourceAvatarRefresh(source_ids[0], "candidate_missing")]

    monkeypatch.setattr(
        "scripts.backfill_source_avatars.SourceAvatarService",
        AvatarService,
    )
    monkeypatch.setattr(
        sys,
        "argv",
        [
            "backfill_source_avatars.py",
            "--data-dir",
            str(tmp_path),
            "--apply",
            "--free-only",
        ],
    )

    assert main() == 0

    result = json.loads(capsys.readouterr().out)
    assert calls == [
        (workspace["id"], (free_source_id,), (free_source_id,))
    ]
    assert result["status_counts"] == {
        "candidate_missing": 1,
        "paid_source_skipped": 1,
    }


def test_backfill_script_runs_directly_from_its_repository(tmp_path):
    script = Path(__file__).resolve().parents[1] / "scripts" / (
        "backfill_source_avatars.py"
    )

    result = subprocess.run(
        [sys.executable, str(script), "--help"],
        cwd=tmp_path,
        capture_output=True,
        text=True,
        check=False,
    )

    assert result.returncode == 0
    assert "--free-only" in result.stdout
