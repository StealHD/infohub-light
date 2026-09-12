"""CI impact proofs use real Git trees and bounded, mocked Actions evidence."""

import json
import stat
import subprocess
from pathlib import Path

import pytest

from scripts import test_gate_ci as ci
from scripts.test_gate_changes import GateConfigError, load_mapping

ROOT = Path(__file__).resolve().parents[1]
MAPPING = load_mapping(ROOT / "tests/test_impact_map.json")
PROJECT = '''[project]
name = "horizon"
version = "1.0.0"
dependencies = ["dependency>=1", "other>=1"]
[build-system]
requires = ["hatchling"]
build-backend = "hatchling.build"
[tool.example]
enabled = true
'''
LOCK = '''version = 1
revision = 3
[[package]]
name = "horizon"
version = "1.0.0"
source = { editable = "." }
dependencies = [{ name = "dependency" }, { name = "other" }]
[[package]]
name = "dependency"
version = "1.0.0"
source = { registry = "https://example.invalid/simple" }
sdist = { url = "https://example.invalid/pkg.tar.gz", hash = "sha256:123", size = 123 }
'''


def git(repo, *args):
    return subprocess.check_output(["git", *args], cwd=repo, text=True).strip()


def commit(repo, message="change"):
    git(repo, "add", "-A")
    git(repo, "commit", "-qm", message)
    return git(repo, "rev-parse", "HEAD")


def write(repo, relative, content):
    path = repo / relative
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content, encoding="utf-8")


def bump(repo):
    write(repo, "pyproject.toml", PROJECT.replace('version = "1.0.0"', 'version = "1.0.1"'))
    write(repo, "uv.lock", LOCK.replace('version = "1.0.0"', 'version = "1.0.1"', 1))


@pytest.fixture
def repo(tmp_path):
    path = tmp_path / "repo"
    path.mkdir()
    git(path, "init", "-q", "-b", "main")
    git(path, "config", "user.name", "CI Test")
    git(path, "config", "user.email", "ci-test@example.invalid")
    git(path, "config", "core.filemode", "true")
    write(path, "pyproject.toml", PROJECT)
    write(path, "uv.lock", LOCK)
    write(path, "docs/notes.md", "Initial\n")
    commit(path, "base")
    return path


def success(sha, **overrides):
    return {
        "headSha": sha, "status": "completed", "conclusion": "success",
        "event": "push", "headBranch": "main", **overrides,
    }


@pytest.fixture
def mock_gh(monkeypatch):
    original = subprocess.run
    calls = []

    def install(payload=None, *, output=None, returncode=0, error=None):
        def run(argv, **kwargs):
            if argv[0] != "gh":
                return original(argv, **kwargs)
            calls.append((argv, kwargs))
            if error:
                raise error
            return subprocess.CompletedProcess(
                argv, returncode, stdout=json.dumps(payload) if output is None else output,
                stderr="untrusted remote error",
            )
        monkeypatch.setattr(ci.subprocess, "run", run)
        return calls

    return install


def plan(repo, base, head, event="push"):
    return ci.build_ci_plan(repo, event, base, head, MAPPING)


def assert_full_fallback(result):
    assert result["selected_groups"] == ["control", "full"]
    assert result["backend_impacted"] is result["frontend_impacted"] is True
    assert result["ui_impacted"] is result["e2e_full"] is True
    assert result["e2e_targets"] == []
    assert result["metadata_only"] is False
    assert result["verified_main_base"] is None


def test_nearest_older_first_parent_success_wins_over_run_order(repo, mock_gh):
    oldest = git(repo, "rev-parse", "HEAD")
    write(repo, "docs/notes.md", "Green main\n")
    nearest = commit(repo)
    write(repo, "src/services/feed_payload.py", "VALUE = 1\n")
    head = commit(repo)
    calls = mock_gh([success(oldest), success(head), success("f" * 40), success(nearest)])

    result = plan(repo, oldest, head)

    assert result["verified_main_base"] == result["base_sha"] == nearest
    assert result["head_sha"] == head
    assert result["selected_groups"] == ["control", "python_feed"]
    assert result["changed_files"] == ["src/services/feed_payload.py"]
    assert calls[0][0] == [
        "gh", "run", "list", "--workflow", "test-gate.yml", "--branch", "main",
        "--event", "push", "--status", "success", "--limit", "100", "--json",
        "headSha,status,conclusion,event,headBranch",
    ]
    assert calls[0][1]["timeout"] == 30


def test_second_parent_success_cannot_replace_main_baseline(repo, mock_gh):
    base = git(repo, "rev-parse", "HEAD")
    git(repo, "checkout", "-qb", "side")
    write(repo, "docs/side.md", "side\n")
    side = commit(repo)
    git(repo, "checkout", "-q", "main")
    write(repo, "src/services/feed_payload.py", "VALUE = 1\n")
    commit(repo)
    git(repo, "merge", "--no-ff", "-qm", "merge", "side")
    head = git(repo, "rev-parse", "HEAD")
    mock_gh([success(side), success(base)])

    result = plan(repo, side, head)

    assert result["verified_main_base"] == base
    assert result["backend_impacted"] is True


@pytest.mark.parametrize("conclusion", ["failure", "cancelled"])
def test_failed_intervening_ui_change_remains_in_version_push_impact(repo, mock_gh, conclusion):
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "frontend/src/features/workbench-live/FeedInsightsPanel.tsx", "export const value = 1;\n")
    intervening = commit(repo)
    bump(repo)
    head = commit(repo)
    mock_gh([success(intervening, conclusion=conclusion), success(base)])

    result = plan(repo, intervening, head)

    assert result["base_sha"] == base
    assert result["metadata_only"] is False
    assert result["ui_impacted"] is True
    assert result["backend_impacted"] is result["frontend_impacted"] is True
    assert "frontend/src/features/workbench-live/FeedInsightsPanel.tsx" in result["changed_files"]


@pytest.mark.parametrize("override", [
    {"status": "in_progress"}, {"conclusion": "failure"}, {"conclusion": "cancelled"},
    {"event": "pull_request"}, {"headBranch": "feature"}, {"headSha": "invalid"},
    {"headSha": 123}, {"headBranch": None},
])
def test_unverified_run_identity_forces_all_domains(repo, mock_gh, override):
    base = git(repo, "rev-parse", "HEAD")
    bump(repo)
    head = commit(repo)
    mock_gh([success(base, **override), success(head)])

    assert_full_fallback(plan(repo, base, head))


@pytest.mark.parametrize("kwargs", [
    {"payload": []}, {"payload": {}}, {"payload": [None, {}, 1]},
    {"output": "malformed JSON"}, {"returncode": 1},
    {"error": FileNotFoundError("gh missing")},
    {"error": subprocess.TimeoutExpired("gh", 30)},
])
def test_missing_main_evidence_does_not_fail_planning(repo, mock_gh, kwargs):
    base = git(repo, "rev-parse", "HEAD")
    write(repo, "docs/notes.md", "docs only\n")
    head = commit(repo)
    mock_gh(**kwargs)

    result = plan(repo, base, head)

    assert_full_fallback(result)
    assert result["base_sha"] == base
    assert result["status"] == "planned"


@pytest.mark.parametrize("base", ["", "0" * 40, "missing-revision"])
def test_unavailable_before_uses_parent_but_still_forces_full(repo, mock_gh, base):
    parent = git(repo, "rev-parse", "HEAD")
    bump(repo)
    head = commit(repo)
    mock_gh([])

    result = plan(repo, base, head)

    assert_full_fallback(result)
    assert result["base_sha"] == parent


def test_initial_commit_without_history_still_runs_full(repo, mock_gh):
    head = git(repo, "rev-parse", "HEAD")
    mock_gh([])
    result = plan(repo, "", head)
    assert_full_fallback(result)
    assert result["base_sha"] == head


@pytest.mark.parametrize("base", ["", "missing", "0" * 40])
def test_invalid_pr_base_uses_parent_only_as_full_gate_baseline(repo, mock_gh, base):
    write(repo, "src/services/feed_payload.py", "VALUE = 1\n")
    parent = commit(repo)
    write(repo, "docs/notes.md", "docs after unverified code\n")
    head = commit(repo)
    calls = mock_gh([])

    result = plan(repo, base, head, "pull_request")

    assert_full_fallback(result)
    assert result["base_sha"] == parent
    assert calls == []


@pytest.mark.parametrize("base", ["missing", "HEAD"])
def test_pr_root_commit_without_comparison_history_is_full(repo, mock_gh, base):
    head = git(repo, "rev-parse", "HEAD")
    mock_gh([])
    assert_full_fallback(plan(repo, base, head, "pull_request"))


def test_verified_main_version_pair_runs_only_control(repo, mock_gh):
    base = git(repo, "rev-parse", "HEAD")
    bump(repo)
    head = commit(repo)
    mock_gh([success(base)])

    result = plan(repo, base, head)

    assert result["metadata_only"] is True
    assert result["verified_main_base"] == base
    assert result["selected_groups"] == ["control"]
    assert result["changed_files"] == ["pyproject.toml", "uv.lock"]
    assert result["counts"] == {"changed_files": 2, "selected_groups": 1}
    assert result["backend_impacted"] is result["frontend_impacted"] is result["ui_impacted"] is False


@pytest.mark.parametrize("event", ["pull_request", "workflow_dispatch"])
def test_other_events_keep_normal_version_mapping_without_network(repo, mock_gh, event):
    base = git(repo, "rev-parse", "HEAD")
    bump(repo)
    head = commit(repo)
    calls = mock_gh(error=AssertionError("PR planning must not query Actions"))

    result = plan(repo, base, head, event)

    assert result["metadata_only"] is False
    assert result["selected_groups"] == ["control", "full"]
    assert result["verified_main_base"] is None
    assert calls == []


@pytest.mark.parametrize("file,old,new", [
    ("pyproject.toml", "dependency>=1", "dependency>=2"),
    ("pyproject.toml", 'requires = ["hatchling"]', 'requires = ["other"]'),
    ("pyproject.toml", "enabled = true", "enabled = 1"),
    ("pyproject.toml", '["dependency>=1", "other>=1"]', '["other>=1", "dependency>=1"]'),
    ("uv.lock", "sha256:123", "sha256:456"),
    ("uv.lock", 'version = "1.0.0"', 'version = "2.0.0"'),
    ("uv.lock", "revision = 3", "revision = 4"),
    ("uv.lock", "size = 123", "size = 456"),
    ("uv.lock", 'editable = "."', 'editable = "other"'),
    ("uv.lock", '{ name = "dependency" }, { name = "other" }', '{ name = "other" }, { name = "dependency" }'),
])
def test_nonversion_toml_changes_use_normal_full_mapping(repo, mock_gh, file, old, new):
    base = git(repo, "rev-parse", "HEAD")
    bump(repo)
    path = repo / file
    path.write_text(path.read_text().replace(old, new), encoding="utf-8")
    head = commit(repo)
    mock_gh([success(base)])

    result = plan(repo, base, head)

    assert result["metadata_only"] is False
    assert result["selected_groups"] == ["control", "full"]


@pytest.mark.parametrize("relative", ["docs/extra.md", "data/extra.txt", ".env.example", "private_token.txt"])
def test_raw_diff_additional_paths_block_fastpath_even_if_selector_excludes_them(repo, mock_gh, relative):
    base = git(repo, "rev-parse", "HEAD")
    bump(repo)
    write(repo, relative, "fixture\n")
    head = commit(repo)
    mock_gh([success(base)])

    result = plan(repo, base, head)

    assert result["metadata_only"] is False
    assert result["selected_groups"] == ["control", "full"]


@pytest.mark.parametrize("mutation", ["rename", "delete", "mode", "symlink", "package_order"])
def test_tree_and_package_order_changes_block_fastpath(repo, mock_gh, mutation):
    base = git(repo, "rev-parse", "HEAD")
    bump(repo)
    path = repo / "pyproject.toml"
    if mutation == "rename":
        (repo / "docs/notes.md").rename(repo / "docs/renamed.md")
    elif mutation == "delete":
        (repo / "uv.lock").unlink()
    elif mutation == "mode":
        path.chmod(0o755)
    elif mutation == "symlink":
        path.unlink()
        path.symlink_to("docs/notes.md")
    else:
        parts = (repo / "uv.lock").read_text().split("[[package]]")
        write(repo, "uv.lock", parts[0] + "[[package]]" + parts[2] + "[[package]]" + parts[1])
    head = commit(repo)
    mock_gh([success(base)])

    assert plan(repo, base, head)["metadata_only"] is False


@pytest.mark.parametrize("mutation", ["mismatch", "empty", "numeric", "missing", "duplicate", "malformed", "no_change"])
def test_missing_or_inconsistent_version_proof_blocks_fastpath(repo, mock_gh, mutation):
    base = git(repo, "rev-parse", "HEAD")
    bump(repo)
    if mutation == "mismatch":
        write(repo, "uv.lock", LOCK)
    elif mutation in {"empty", "numeric", "missing"}:
        value = {"empty": 'version = ""', "numeric": "version = 1", "missing": ""}[mutation]
        write(repo, "pyproject.toml", PROJECT.replace('version = "1.0.0"', value))
    elif mutation == "duplicate":
        with (repo / "uv.lock").open("a") as handle:
            handle.write('\n[[package]]\nname="horizon"\nversion="1.0.1"\nsource={editable="."}\n')
    elif mutation == "malformed":
        write(repo, "pyproject.toml", "[invalid\n")
    else:
        write(repo, "pyproject.toml", PROJECT + "\n# formatting\n")
        write(repo, "uv.lock", LOCK)
    head = commit(repo)
    mock_gh([success(base)])

    assert plan(repo, base, head)["metadata_only"] is False


def test_inconsistent_old_root_versions_cannot_prove_version_only(repo, mock_gh):
    write(repo, "uv.lock", LOCK.replace('version = "1.0.0"', 'version = "0.9.0"', 1))
    base = commit(repo)
    bump(repo)
    head = commit(repo)
    mock_gh([success(base)])
    assert plan(repo, base, head)["metadata_only"] is False


def test_cli_writes_private_plan_and_bounded_existing_summary(repo, mock_gh, monkeypatch, capsys, tmp_path):
    base = git(repo, "rev-parse", "HEAD")
    bump(repo)
    head = commit(repo)
    write(repo, "tests/test_impact_map.json", json.dumps(MAPPING))
    mock_gh([success(base)])
    monkeypatch.setattr(ci, "_PROJECT_ROOT", repo)
    output = tmp_path / "impact.json"
    output.write_text("replace me")
    output.chmod(0o644)

    status = ci.main(["--event", "push", "--base", base, "--head", head, "--output", str(output)])

    captured = capsys.readouterr()
    result = json.loads(output.read_text())
    assert status == 0
    assert result["metadata_only"] is True
    assert stat.S_IMODE(output.stat().st_mode) == 0o600
    assert len(captured.out.encode()) <= 2048
    assert json.loads(captured.out)["selected_groups"] == ["control"]
    assert captured.err == ""


def test_invalid_head_is_an_explicit_configuration_error(repo, mock_gh):
    calls = mock_gh([])
    with pytest.raises(GateConfigError):
        plan(repo, "", "missing")
    assert calls == []
