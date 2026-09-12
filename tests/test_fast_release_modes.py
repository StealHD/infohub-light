"""Release mode routing and conservative standard CI history with real Git."""
import json
import subprocess
from pathlib import Path

import pytest

from scripts.release_mode import commit_mode, git, parse_mode, tag_mode
from scripts.test_gate_changes import GateConfigError
from scripts.test_gate_ci import build_ci_plan, verified_main_base


@pytest.mark.parametrize("message,expected", [
    ("ordinary commit", "standard"),
    ("release\n\nRelease-Mode: fast\n", "fast"),
    ("release\n\nRelease-Mode: standard\n", "standard"),
])
def test_mode_defaults_and_trailers(message, expected):
    assert parse_mode(message) == expected


@pytest.mark.parametrize("message", [
    "release\n\nRelease-Mode: other", "release\n\nRelease-Mode: fast\nRelease-Mode: fast",
    "release\n\nRelease-Mode: fast\n\nnot a trailer", "release\n\nRelease-Mode: fast; echo unsafe",
])
def test_invalid_mode_fails(message):
    with pytest.raises(GateConfigError):
        parse_mode(message)


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / "pyproject.toml").write_text('[project]\nname="horizon"\nversion="1.2.3"\n')
    (tmp_path / "uv.lock").write_text('[[package]]\nname="horizon"\nversion="1.2.3"\nsource={editable="."}\n')
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    return tmp_path


def commit(root, message):
    git(root, "commit", "--allow-empty", "-m", message)
    return git(root, "rev-parse", "HEAD")


def test_fast_success_does_not_truncate_standard_baseline(repository, monkeypatch):
    base = git(repository, "rev-parse", "HEAD")
    fast = commit(repository, "fast\n\nRelease-Mode: fast")
    head = commit(repository, "standard")
    real_run = subprocess.run
    def run(args, **kwargs):
        if args[0] == "gh":
            return subprocess.CompletedProcess(args, 0, json.dumps([
                dict(headSha=sha, status="completed", conclusion="success", event="push", headBranch="main")
                for sha in (fast, base)]), "")
        return real_run(args, **kwargs)
    monkeypatch.setattr(subprocess, "run", run)
    assert verified_main_base(repository, head) == base


def test_fast_push_does_not_query_full_baseline_and_pr_ignores_marker(repository, monkeypatch):
    base = git(repository, "rev-parse", "HEAD")
    head = commit(repository, "fast\n\nRelease-Mode: fast")
    monkeypatch.setattr("scripts.test_gate_ci.verified_main_base", lambda *args: pytest.fail("full baseline queried"))
    mapping = json.loads((Path(__file__).parents[1] / "tests/test_impact_map.json").read_text())
    assert build_ci_plan(repository, "push", base, head, mapping)["release_mode"] == "fast"
    assert build_ci_plan(repository, "pull_request", base, head, mapping)["release_mode"] == "standard"
    manual = build_ci_plan(repository, "workflow_dispatch", base, head, mapping)
    assert manual["e2e_full"] and "full" in manual["selected_groups"]


def test_tag_requires_matching_annotation_and_commit(repository):
    commit(repository, "fast\n\nRelease-Mode: fast")
    git(repository, "tag", "-a", "v1.2.3", "-m", "release")
    with pytest.raises(GateConfigError, match="tag mode"):
        tag_mode(repository, "v1.2.3")
    git(repository, "tag", "-d", "v1.2.3")
    git(repository, "tag", "-a", "v1.2.3", "-m", "release\n\nRelease-Mode: fast")
    assert tag_mode(repository, "v1.2.3") == commit_mode(repository) == "fast"
