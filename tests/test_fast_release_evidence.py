"""Stale inputs and incomplete local coverage cannot authorize a fast release."""
import json
from pathlib import Path

import pytest

from scripts.release_evidence import read_passed, validate, required_plan
from scripts.release_mode import git
from scripts.test_gate import execute_specs
from scripts.test_gate_changes import GateConfigError
from scripts.test_gate_commands import CommandSpec, build_command_specs
from scripts.test_gate_evidence import environment, inputs, normalized

ROOT = Path(__file__).parents[1]


@pytest.fixture
def repository(tmp_path):
    git(tmp_path, "init", "-b", "main")
    git(tmp_path, "config", "user.email", "test@example.invalid")
    git(tmp_path, "config", "user.name", "Test")
    (tmp_path / ".gitignore").write_text(".test-results/\n")
    (tmp_path / "scripts").mkdir()
    (tmp_path / "tests").mkdir()
    (tmp_path / "tests/test_impact_map.json").write_bytes((ROOT / "tests/test_impact_map.json").read_bytes())
    (tmp_path / "scripts/example.py").write_text("print('example')\n")
    git(tmp_path, "add", ".")
    git(tmp_path, "commit", "-m", "base")
    return tmp_path


def report(root, specs):
    payload = {"status": "passed", "mapping_miss": False,
               "commands": [{"command_id": s.command_id, "exit_code": 0} for s in specs],
               "verification": {"schema": 1, "reusable": True, "inputs": inputs(root),
                                "environment": environment(),
                                "specs": [{"id": s.command_id, "argv": normalized(s.argv, root)} for s in specs]}}
    path = root / ".test-results/evidence.json"
    path.parent.mkdir(exist_ok=True)
    path.write_text(json.dumps(payload))
    return path


def test_code_changes_invalidate_but_plain_worklog_does_not(repository):
    path = report(repository, [])
    (repository / "WORKLOG.md").write_text("evidence only\n")
    read_passed(repository, path)
    (repository / "scripts/example.py").write_text("print('new code')\n")
    with pytest.raises(GateConfigError, match="stale"):
        read_passed(repository, path)


@pytest.mark.parametrize("change", ["mode", "symlink", "lock"])
def test_modes_links_and_dependencies_invalidate(repository, change):
    path = report(repository, [])
    source = repository / "scripts/example.py"
    if change == "mode":
        source.chmod(0o755)
    elif change == "symlink":
        source.unlink()
        source.symlink_to("../WORKLOG.md")
    else:
        (repository / "uv.lock").write_text("changed lock")
    with pytest.raises(GateConfigError):
        read_passed(repository, path)


def test_unknown_baseline_and_uncovered_merge_require_full_evidence(repository):
    path = report(repository, [])
    with pytest.raises(GateConfigError, match="missing coverage"):
        validate(repository, path, None, None)
    base = git(repository, "rev-parse", "HEAD")
    (repository / "scripts/example.py").write_text("print('merged code')\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "merged change")
    path = report(repository, [])
    with pytest.raises(GateConfigError, match="missing coverage"):
        validate(repository, path, None, base)


def test_real_gate_records_changes_during_execution_as_nonreusable(repository):
    spec = CommandSpec("change", ("sh", "-c", "echo changed >> scripts/example.py"), repository)
    result = execute_specs(repository, [spec], {"mode": "targeted"}, run_id="change-input")
    assert result["status"] == "passed"
    assert result["verification"]["reusable"] is False


def test_old_and_failed_results_cannot_be_reused(repository):
    path = report(repository, [])
    for payload in ({"status": "passed"}, {"status": "failed", "verification": {}}):
        path.write_text(json.dumps(payload))
        with pytest.raises(GateConfigError):
            read_passed(repository, path)


def test_ui_requires_separate_browser_coverage(repository):
    base = git(repository, "rev-parse", "HEAD")
    page = repository / "frontend/src/features/admin-heroui/HeroLoginPage.tsx"
    page.parent.mkdir(parents=True)
    page.write_text("export const page = 'login';\n")
    git(repository, "add", ".")
    git(repository, "commit", "-m", "login change")
    plan, mapping = required_plan(repository, base)
    assert plan["ui_impacted"]
    code = build_command_specs(repository, plan, mapping, mode="preflight")
    code_path = report(repository, code)
    with pytest.raises(GateConfigError, match="release_playwright"):
        validate(repository, code_path, None, base)
    browser = build_command_specs(repository, plan, mapping, mode="release", scope="e2e", skip_control=True)
    # Duplicate contract IDs are not valid evidence; real gates deduplicate them.
    all_specs = list({s.command_id: s for s in code + browser}.values())
    code_path = report(repository, all_specs)
    assert validate(repository, code_path, None, base)["baseline"] == base
