"""Behavior coverage for shared CI controls and bounded test selection."""

from pathlib import Path
import subprocess

import pytest

from scripts.test_gate import GateConfigError, build_command_specs, build_plan, load_mapping, main


ROOT = Path(__file__).resolve().parents[1]
MAPPING = load_mapping(ROOT / "tests/test_impact_map.json")


def commands(changed, mode="targeted", scope="all", **kwargs):
    return build_command_specs(ROOT, build_plan(changed, MAPPING), MAPPING,
                               mode=mode, scope=scope, **kwargs)


@pytest.mark.parametrize("scope", ["backend", "frontend", "e2e", "smoke"])
def test_ci_can_run_only_its_domain_after_shared_control(scope):
    specs = commands(["pyproject.toml"], mode="release", scope=scope, skip_control=True)
    assert specs
    assert {spec.domain for spec in specs} == {scope}
    assert any(spec.domain == "control" for spec in commands(
        ["pyproject.toml"], mode="release", scope=scope))


@pytest.mark.parametrize("scope", ["all", "control"])
def test_skip_control_cannot_disable_the_aggregate_gate(scope):
    with pytest.raises(GateConfigError, match="skip-control"):
        commands(["WORKLOG.md"], scope=scope, skip_control=True)


def test_build_owns_typecheck_but_targeted_without_build_keeps_it():
    full = {spec.command_id for spec in commands(["pyproject.toml"], mode="full")}
    targeted = {spec.command_id for spec in commands([
        "frontend/src/features/settings/SettingsAIPage.tsx"])}
    assert "frontend_build" in full
    assert "frontend_typecheck" not in full
    assert "frontend_typecheck" in targeted


@pytest.mark.parametrize("path", [
    "frontend/e2e/production-admin.spec.ts",
    "frontend/e2e/production-admin.spec.ts-snapshots/login-dark-mobile-linux.png",
])
def test_browser_only_change_does_not_schedule_vitest(path):
    plan = build_plan([path], MAPPING)
    assert plan["ui_impacted"] is True
    assert plan["frontend_impacted"] is False
    assert "e2e/production-admin.spec.ts" in plan["e2e_targets"]
    local = commands([path], mode="preflight")
    assert "e2e_contract" in {spec.command_id for spec in local}
    assert not any("vitest" in spec.command_id for spec in local)
    release = commands([path], mode="release", scope="e2e", full_e2e=True)
    assert next(s.argv for s in release if s.command_id == "release_playwright") == (
        "npm", "run", "e2e:release")


def test_global_frontend_and_unknown_code_remain_conservative():
    shell = commands(["frontend/src/design-system/Example.tsx"])
    unknown = commands(["src/unknown_package/example.py"], mode="preflight")
    assert "frontend_vitest" in {s.command_id for s in shell}
    assert {"python_full", "frontend_vitest"} <= {s.command_id for s in unknown}


def test_skip_control_cli_rejects_control_scope(capsys):
    assert main(["run", "--mode", "full", "--scope", "control", "--skip-control"]) == 2
    assert "skip-control" in capsys.readouterr().err


def test_ci_control_checks_committed_range_instead_of_clean_checkout():
    plan = build_plan(["WORKLOG.md"], MAPPING)
    plan.update(base_sha="a" * 40, head_sha="b" * 40)
    specs = build_command_specs(ROOT, plan, MAPPING, mode="targeted", scope="control")
    assert next(s.argv for s in specs if s.command_id == "diff_check") == (
        "git", "diff", "--check", "a" * 40, "b" * 40, "--")


@pytest.mark.parametrize("renamed", [False, True])
def test_removed_or_renamed_python_test_runs_surviving_suite(tmp_path, renamed):
    tests = tmp_path / "tests"
    tests.mkdir()
    (tests / "test_surviving.py").write_text("def test_surviving():\n    assert False, 'surviving-test-ran'\n")
    changed = ["tests/test_removed.py"]
    if renamed:
        (tests / "test_new.py").write_text("def test_new():\n    assert True\n")
        changed.append("tests/test_new.py")
    plan = build_plan(changed, MAPPING)
    specs = build_command_specs(tmp_path, plan, MAPPING, mode="preflight")
    command = next(s for s in specs if s.command_id == "python_full")
    assert not any(s.command_id.startswith("compose_") for s in specs)
    result = subprocess.run(command.argv, cwd=command.cwd, capture_output=True, text=True)
    assert result.returncode == 1
    assert "surviving-test-ran" in result.stdout
    assert "file or directory not found" not in result.stderr
