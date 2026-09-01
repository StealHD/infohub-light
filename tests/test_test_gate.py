import json
import shutil
import stat
import subprocess
import sys
from pathlib import Path

import pytest

from scripts.test_gate import (
    CommandSpec,
    GateConfigError,
    build_command_specs,
    build_plan,
    build_snapshot,
    _check_snapshot_diff,
    changed_files_from_git,
    changed_files_from_snapshot,
    changed_files_from_staged,
    execute_specs,
    format_summary,
    load_mapping,
    load_snapshot,
    _validate_json_files,
    _reconcile_mapping_miss,
    _prepare_release_smoke_data,
)
from scripts.test_gate_changes import code_size_policy_domains
from scripts.check_observability_contract import PROTECTED_RUNTIME_FILES


ROOT = Path(__file__).resolve().parents[1]
MAPPING = ROOT / "tests" / "test_impact_map.json"


def test_snapshot_cli_records_only_safe_relative_file_hashes(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "src").mkdir()
    (repo / "src" / "module.py").write_text("VALUE = 1\n", encoding="utf-8")
    (repo / "src" / "secret_store.py").write_text("SAFE_CODE = True\n", encoding="utf-8")
    (repo / "api_token.txt").write_text("do-not-read-either\n", encoding="utf-8")
    (repo / "data").mkdir()
    (repo / "data" / "service.db").write_text("private", encoding="utf-8")
    (repo / ".env").write_text("API_TOKEN=do-not-read\n", encoding="utf-8")
    subprocess.run(["git", "add", "src/module.py", "src/secret_store.py"], cwd=repo, check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-qm", "base",
        ],
        cwd=repo,
        check=True,
    )
    output = tmp_path / "snapshot.json"

    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "test_gate.py"),
            "--root",
            str(repo),
            "snapshot",
            "--output",
            str(output),
        ],
        cwd=ROOT,
        capture_output=True,
        text=True,
    )

    assert result.returncode == 0, result.stderr
    snapshot = json.loads(output.read_text(encoding="utf-8"))
    assert snapshot["version"] == 2
    assert len(snapshot["base_sha"]) == 40
    assert list(snapshot["files"]) == ["src/module.py", "src/secret_store.py"]
    assert len(snapshot["files"]["src/module.py"]) == 64
    serialized = output.read_text(encoding="utf-8")
    assert "do-not-read" not in serialized
    assert "do-not-read-either" not in serialized
    assert "service.db" not in serialized


def test_snapshot_diff_is_task_scoped_and_detects_add_modify_delete(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    for relative, content in {
        "src/changed.py": "old\n",
        "src/deleted.py": "delete me\n",
        "src/untouched.py": "same\n",
    }.items():
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(content, encoding="utf-8")
    subprocess.run(["git", "add", "src"], cwd=repo, check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-qm", "base",
        ],
        cwd=repo,
        check=True,
    )
    base_sha = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(
        json.dumps(
            {
                "version": 2,
                "base_sha": base_sha,
                "files": {
                    relative: __import__("hashlib").sha256(content.encode()).hexdigest()
                    for relative, content in {
                        "src/changed.py": "old\n",
                        "src/deleted.py": "delete me\n",
                        "src/untouched.py": "same\n",
                    }.items()
                },
            }
        ),
        encoding="utf-8",
    )
    (repo / "src" / "changed.py").write_text("new\n", encoding="utf-8")
    (repo / "src" / "deleted.py").unlink()
    (repo / "src" / "added.py").write_text("added\n", encoding="utf-8")

    changed = changed_files_from_snapshot(repo, load_snapshot(snapshot_path))

    assert changed == ["src/added.py", "src/changed.py", "src/deleted.py"]


def test_json_validation_ignores_deleted_tracked_json(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    removed = repo / "removed.json"
    removed.write_text("not-json\n", encoding="utf-8")
    (repo / "active.json").write_text('{"status":"current"}\n', encoding="utf-8")
    subprocess.run(["git", "add", "removed.json", "active.json"], cwd=repo, check=True)
    removed.unlink()

    _validate_json_files(repo)


@pytest.mark.parametrize(
    ("payload", "message"),
    [
        ("not-json", "invalid snapshot JSON"),
        ('{"version":99,"files":{}}', "unsupported snapshot version"),
        ('{"version":2,"base_sha":"0000000000000000000000000000000000000000","files":[]}', "snapshot files must be an object"),
        ('{"version":2,"base_sha":"0000000000000000000000000000000000000000","files":{"../escape.py":"bad"}}', "unsafe snapshot path"),
    ],
)
def test_snapshot_corruption_fails_closed(tmp_path, payload, message):
    snapshot_path = tmp_path / "snapshot.json"
    snapshot_path.write_text(payload, encoding="utf-8")

    with pytest.raises(GateConfigError, match=message):
        load_snapshot(snapshot_path)


@pytest.mark.parametrize(
    ("changed_files", "expected_groups", "ui_impacted", "mapping_miss"),
    [
        (["WORKLOG.md"], {"control"}, False, False),
        (["docs/usage_zh.md"], {"control"}, False, False),
        (["src/api/server.py"], {"control", "python_api_store"}, False, False),
        (["src/services/job_queue.py"], {"control", "python_queue_worker"}, False, False),
        (["src/services/feed_production.py"], {"control", "python_feed"}, False, False),
        (
            ["src/services/source_acquisition.py"],
            {
                "control",
                "python_api_store",
                "python_feed",
                "python_source_acquisition",
            },
            False,
            False,
        ),
        (
            ["src/services/apify_actor_ops.py"],
            {
                "control",
                "python_api_store",
                "python_queue_worker",
                "python_source_acquisition",
            },
            False,
            False,
        ),
        (
            ["src/services/apify_actor_manifest.py"],
            {"control", "python_queue_worker", "python_source_acquisition"},
            False,
            False,
        ),
        (
            ["src/services/apify_actor_discovery.py"],
            {"control", "python_api_store", "python_queue_worker", "python_scrapers"},
            False,
            False,
        ),
        (
            ["src/services/apify_actor_maintenance.py"],
            {"control", "python_api_store", "python_queue_worker", "python_scrapers"},
            False,
            False,
        ),
        (
            ["src/services/apify_actor_runtime.py"],
            {
                "control",
                "python_queue_worker",
                "python_source_acquisition",
                "python_scrapers",
            },
            False,
            False,
        ),
        (
            ["src/services/apify_actor_canary.py"],
            {
                "control",
                "python_queue_worker",
                "python_source_acquisition",
                "python_scrapers",
            },
            False,
            False,
        ),
        (
            ["src/services/apify_native_fallback.py"],
            {"control", "python_source_acquisition"},
            False,
            False,
        ),
        (["src/ai/analyzer.py"], {"control", "python_ai_orchestrator"}, False, False),
        (["src/scrapers/rss.py"], {"control", "python_scrapers"}, False, False),
        (["scripts/reset_local_service.py"], {"control", "python_scripts"}, False, False),
        (
            ["frontend/src/features/feed/feedModel.ts"],
            {"control", "frontend_checks", "frontend_related"},
            True,
            False,
        ),
        (["frontend/vite.config.ts"], {"control", "frontend_full"}, True, False),
        (["frontend/src/AppBootstrap.tsx"], {"control", "frontend_full"}, True, False),
        (["docs/contracts/ui/README.md"], {"control", "frontend_full"}, True, False),
        (["tests/test_worker.py"], {"control", "python_test_files"}, False, False),
        (["tests/conftest.py"], {"control", "full"}, False, False),
        (["tests/code_size_policy.json"], {"control"}, False, False),
        (["pyproject.toml"], {"control", "full"}, False, False),
        (["src/new_subsystem/module.py"], {"control", "full"}, False, True),
    ],
)
def test_deterministic_impact_mapping(
    changed_files, expected_groups, ui_impacted, mapping_miss
):
    plan = build_plan(changed_files, load_mapping(MAPPING))

    assert set(plan["selected_groups"]) == expected_groups
    assert plan["ui_impacted"] is ui_impacted
    assert plan["backend_impacted"] is (
        "full" in expected_groups
        or any(group.startswith("python_") for group in expected_groups)
    )
    assert plan["frontend_impacted"] is (
        "full" in expected_groups
        or any(group.startswith("frontend_") for group in expected_groups)
    )
    assert plan["mapping_miss"] is mapping_miss
    if "tests/test_worker.py" in changed_files:
        assert plan["python_test_targets"] == ["tests/test_worker.py"]


def test_mapping_file_rejects_unknown_group(tmp_path):
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "version": 2,
                "rules": [
                    {"id": "bad", "globs": ["src/**"], "groups": ["does_not_exist"]}
                ],
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(GateConfigError, match="unknown group"):
        load_mapping(mapping_path)


def test_mapping_file_rejects_duplicate_group_test_paths(tmp_path):
    mapping_path = tmp_path / "mapping.json"
    mapping_path.write_text(
        json.dumps(
            {
                "version": 2,
                "rules": [],
                "group_tests": {
                    "python_api_store": ["tests/test_example.py", "tests/test_example.py"]
                },
            }
        ),
        encoding="utf-8",
    )

    with pytest.raises(GateConfigError, match="duplicate test paths"):
        load_mapping(mapping_path)


def test_mapping_group_tests_reference_existing_files():
    mapping = load_mapping(MAPPING)
    missing = [
        test
        for tests in mapping["group_tests"].values()
        for test in tests
        if not (ROOT / test).is_file()
    ]

    assert not missing, f"missing mapped tests: {missing}"


@pytest.mark.parametrize(
    ("changed_file", "targets", "full"),
    [
        (
            "frontend/src/features/apify-actors/HeroActorOpsControlPlane.tsx",
            {"e2e/actorops-pool-management.spec.ts", "e2e/production-admin.spec.ts"},
            False,
        ),
        (
            "frontend/src/features/workbench-live/VirtualFeed.tsx",
            {
                "e2e/desktop-sidebar-motion.spec.ts",
                "e2e/feed-expand-motion.spec.ts",
                "e2e/heroui-workbench-preview.spec.ts",
                "e2e/production-workbench.spec.ts",
            },
            False,
        ),
        (
            "frontend/src/features/openclaw/ui/OpenClawComposer.tsx",
            {"e2e/production-workbench.spec.ts", "e2e/production-admin.spec.ts"},
            False,
        ),
        (
            "frontend/e2e/production-admin.spec.ts-snapshots/actorops-guided-light-mobile-linux.png",
            {"e2e/production-admin.spec.ts"},
            False,
        ),
        ("frontend/src/app/App.tsx", set(), True),
        ("frontend/src/features/new-area/Unknown.tsx", set(), True),
    ],
)
def test_e2e_impact_selection(changed_file, targets, full):
    plan = build_plan([changed_file], load_mapping(MAPPING))

    assert set(plan["e2e_targets"]) == targets
    assert plan["e2e_full"] is full


def test_code_size_policy_change_selects_only_its_domain(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    policy_path = repo / "tests" / "code_size_policy.json"
    policy_path.parent.mkdir()
    policy = {
        "version": 2,
        "limits": {"unchanged": True},
        "frozen_files": ["frontend/src/Legacy.tsx", "src/legacy.py"],
    }
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-qm", "base",
        ],
        cwd=repo,
        check=True,
    )
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    policy["frozen_files"].remove("frontend/src/Legacy.tsx")
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    domains = code_size_policy_domains(repo, base)
    plan = build_plan(
        ["tests/code_size_policy.json"],
        load_mapping(MAPPING),
        code_size_domains=domains,
    )

    assert domains == {"frontend"}
    assert set(plan["selected_groups"]) == {"control", "code_size_frontend"}
    assert plan["frontend_impacted"] is True
    assert plan["backend_impacted"] is False


def test_code_size_limit_change_fails_closed_to_full_impact(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    policy_path = repo / "tests" / "code_size_policy.json"
    policy_path.parent.mkdir()
    policy = {"version": 2, "limits": {"hard": 800}, "frozen_files": []}
    policy_path.write_text(json.dumps(policy), encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git", "-c", "user.name=Test", "-c", "user.email=test@example.invalid",
            "commit", "-qm", "base",
        ],
        cwd=repo,
        check=True,
    )
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    policy["limits"]["hard"] = 799
    policy_path.write_text(json.dumps(policy), encoding="utf-8")

    domains = code_size_policy_domains(repo, base)
    plan = build_plan(
        ["tests/code_size_policy.json"],
        load_mapping(MAPPING),
        code_size_domains=domains,
    )

    assert domains == {"full"}
    assert set(plan["selected_groups"]) == {"control", "full"}


def test_git_diff_reports_rename_as_old_and_new_paths(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test Gate"], cwd=repo, check=True)
    old = repo / "src" / "old.py"
    old.parent.mkdir()
    old.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    old.rename(repo / "src" / "new.py")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "rename"], cwd=repo, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    assert changed_files_from_git(repo, base, head) == ["src/new.py", "src/old.py"]


def test_snapshot_and_git_range_produce_same_changed_file_set(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.email", "test@example.invalid"], cwd=repo, check=True)
    subprocess.run(["git", "config", "user.name", "Test Gate"], cwd=repo, check=True)
    path = repo / "src" / "module.py"
    path.parent.mkdir()
    path.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "base"], cwd=repo, check=True)
    base = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()
    snapshot = build_snapshot(repo)
    path.write_text("VALUE = 2\n", encoding="utf-8")
    added = repo / "src" / "added.py"
    added.write_text("ADDED = True\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(["git", "commit", "-qm", "head"], cwd=repo, check=True)
    head = subprocess.check_output(["git", "rev-parse", "HEAD"], cwd=repo, text=True).strip()

    assert changed_files_from_snapshot(repo, snapshot) == changed_files_from_git(repo, base, head)


def test_staged_selector_detects_add_delete_and_rename(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    for relative in ("src/deleted.py", "src/old.py"):
        path = repo / relative
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text("VALUE = 1\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "base",
        ],
        cwd=repo,
        check=True,
    )
    (repo / "src" / "deleted.py").unlink()
    (repo / "src" / "old.py").rename(repo / "src" / "renamed.py")
    (repo / "src" / "added.py").write_text("ADDED = True\n", encoding="utf-8")
    subprocess.run(["git", "add", "-A"], cwd=repo, check=True)

    assert changed_files_from_staged(repo) == [
        "src/added.py",
        "src/deleted.py",
        "src/old.py",
        "src/renamed.py",
    ]


def test_snapshot_diff_check_includes_untracked_files(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q", "-b", "main"], cwd=repo, check=True)
    (repo / "tracked.txt").write_text("tracked\n", encoding="utf-8")
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "base",
        ],
        cwd=repo,
        check=True,
    )
    (repo / "new.txt").write_text("bad trailing whitespace   \n", encoding="utf-8")

    with pytest.raises(GateConfigError, match="untracked diff check failed"):
        _check_snapshot_diff(repo, ["new.txt"])


def test_targeted_full_and_release_commands_have_expected_safety_boundaries():
    mapping = load_mapping(MAPPING)
    plan = build_plan(
        ["src/api/server.py", "frontend/src/features/feed/feedModel.ts"],
        mapping,
    )

    targeted = build_command_specs(ROOT, plan, mapping, mode="targeted", scope="all")
    control = build_command_specs(ROOT, plan, mapping, mode="targeted", scope="control")
    full = build_command_specs(ROOT, plan, mapping, mode="full", scope="all")
    release = build_command_specs(ROOT, plan, mapping, mode="release", scope="all")

    targeted_commands = [" ".join(spec.argv) for spec in targeted]
    full_ids = {spec.command_id for spec in full}
    release_by_id = {spec.command_id: spec for spec in release}
    assert any("pytest" in command and "tests/test_api_service.py" in command for command in targeted_commands)
    assert any("vitest related" in command and "feedModel.ts" in command for command in targeted_commands)
    for spec in [*targeted, *full, *release]:
        if "pytest" in spec.argv:
            assert "-W" in spec.argv
            assert "error::ResourceWarning" in spec.argv
    assert {
        "code_size_backend",
        "code_size_frontend",
        "python_full",
        "frontend_vitest",
        "frontend_build",
    } <= full_ids
    assert "legacy_node_full" not in full_ids
    assert {spec.domain for spec in control} == {"control"}
    assert {spec.command_id for spec in control} == {
        "markdown_controls",
        "code_size_policy",
        "observability_contract",
        "control_json",
        "diff_check",
    }
    assert all(
        "observability_contract" in {
            spec.command_id for spec in specs
        }
        for specs in (targeted, full, release)
    )
    assert "release_playwright" in release_by_id
    assert release_by_id["release_playwright"].argv == ("npm", "run", "e2e:release")
    smoke = release_by_id["release_api_docker_smoke"]
    smoke_command = " ".join(smoke.argv)
    assert "--api-only" in smoke_command
    assert "--run-worker" not in smoke_command
    assert "--full-real-source" not in smoke_command
    assert "horizon-worker" not in smoke_command
    assert "scheduler" not in smoke_command
    assert smoke.env
    assert all(
        value not in smoke_command
        for name, value in smoke.env.items()
        if any(marker in name for marker in ("KEY", "TOKEN", "SECRET", "PASSWORD"))
    )


def test_release_playwright_uses_impacted_specs_until_final_full_gate():
    mapping = load_mapping(MAPPING)
    plan = build_plan(
        ["frontend/src/features/apify-actors/HeroActorOpsControlPlane.tsx"],
        mapping,
    )
    plan["base_sha"] = "1" * 40

    targeted = build_command_specs(ROOT, plan, mapping, mode="release", scope="e2e")
    full = build_command_specs(
        ROOT,
        plan,
        mapping,
        mode="release",
        scope="e2e",
        full_e2e=True,
    )

    targeted_playwright = next(spec for spec in targeted if spec.command_id == "release_playwright")
    full_playwright = next(spec for spec in full if spec.command_id == "release_playwright")
    assert targeted_playwright.argv == (
        "npm",
        "run",
        "e2e:release",
        "--",
        "e2e/actorops-pool-management.spec.ts",
        "e2e/production-admin.spec.ts",
    )
    assert full_playwright.argv == ("npm", "run", "e2e:release")


def test_snapshot_base_is_forwarded_to_code_size_preflight(tmp_path):
    mapping = load_mapping(MAPPING)
    plan = build_plan(["src/api/server.py"], mapping)
    plan["base_sha"] = "a" * 40

    specs = build_command_specs(ROOT, plan, mapping, mode="preflight")
    code_size = [spec for spec in specs if spec.command_id.startswith("code_size_")]

    assert code_size
    assert all(("--compare-base", "a" * 40) == spec.argv[-2:] for spec in code_size)


def test_preflight_fail_closed_runs_full_code_checks_without_docker_or_playwright():
    mapping = load_mapping(MAPPING)
    plan = build_plan(["src/new_subsystem/module.py"], mapping)

    specs = build_command_specs(ROOT, plan, mapping, mode="preflight")
    ids = {spec.command_id for spec in specs}

    assert plan["mapping_miss"] is True
    assert "python_full" in ids
    assert "frontend_vitest" in ids
    assert "code_size_backend" in ids
    assert "code_size_frontend" in ids
    assert not any(command_id.startswith("compose_") for command_id in ids)
    assert "release_playwright" not in ids
    assert "release_api_docker_smoke" not in ids
    command_text = "\n".join(" ".join(spec.argv).lower() for spec in specs)
    for forbidden in ("service_stack_smoke", "horizon-worker", "scheduler", "vps-tokyo"):
        assert forbidden not in command_text


def test_preflight_checks_changed_shell_syntax():
    mapping = load_mapping(MAPPING)
    plan = build_plan(["scripts/release_vps.sh"], mapping)

    specs = build_command_specs(ROOT, plan, mapping, mode="preflight")
    shell = next(spec for spec in specs if spec.command_id == "shell_changed_syntax")

    assert shell.argv == ("bash", "-n", "scripts/release_vps.sh")


def test_deleted_frontend_source_escalates_to_complete_frontend_gate(tmp_path):
    mapping = load_mapping(MAPPING)
    plan = build_plan(["frontend/src/features/feed/Deleted.tsx"], mapping)

    specs = build_command_specs(tmp_path, plan, mapping, mode="targeted")
    ids = {spec.command_id for spec in specs}

    assert "frontend_vitest" in ids
    assert "frontend_build" in ids
    assert "frontend_related" not in ids


def test_full_failure_outside_targeted_coverage_sets_mapping_miss():
    mapping = load_mapping(MAPPING)
    impact = build_plan(["src/api/server.py"], mapping)
    result = {
        "status": "failed",
        "mapping_miss": False,
        "first_failure": {"id": "tests/test_worker.py::test_uncovered"},
    }

    _reconcile_mapping_miss(result, impact, mapping)

    assert result["mapping_miss"] is True


def test_full_failure_inside_targeted_coverage_is_not_mapping_miss():
    mapping = load_mapping(MAPPING)
    impact = build_plan(["src/api/server.py"], mapping)
    result = {
        "status": "failed",
        "mapping_miss": False,
        "first_failure": {"id": "tests/test_api_service.py::test_covered"},
    }

    _reconcile_mapping_miss(result, impact, mapping)

    assert result["mapping_miss"] is False


def test_execute_specs_writes_private_redacted_logs_and_bounded_failure_summary(tmp_path):
    secret = "injected-test-secret-123"
    result_root = tmp_path / ".test-results"
    specs = [
        CommandSpec(
            command_id="first_failure",
            argv=(
                sys.executable,
                "-c",
                "import os; print('FAILED tests/test_demo.py::test_secret'); "
                "print(os.environ['DEMO_API_TOKEN']); "
                "print('authorization=Bearer private-token'); "
                "print('https://private.example/path person@example.com'); "
                "raise SystemExit(7)",
            ),
            cwd=tmp_path,
            env={"DEMO_API_TOKEN": secret},
        )
    ]
    base_result = {
        "mode": "targeted",
        "status": "planned",
        "changed_files": [f"src/file_{index}.py" for index in range(500)],
        "selected_groups": ["python_api_store"],
        "reasons": ["test"],
        "counts": {},
        "duration": 0.0,
        "first_failure": None,
        "log_paths": [],
        "ui_impacted": False,
        "mapping_miss": False,
    }

    result = execute_specs(
        ROOT,
        specs,
        base_result,
        result_root=result_root,
        run_id="unit-failure",
    )
    summary = format_summary(result)

    assert result["status"] == "failed"
    assert result["first_failure"]["id"] == "tests/test_demo.py::test_secret"
    assert secret not in json.dumps(result)
    assert secret not in summary
    assert "[REDACTED]" in summary
    assert "private-token" not in summary
    assert "private.example" not in summary
    assert "person@example.com" not in summary
    assert len(summary.encode("utf-8")) <= 8192
    for relative in result["log_paths"]:
        path = ROOT / relative if not Path(relative).is_absolute() else Path(relative)
        if not path.exists():
            path = result_root / "unit-failure" / Path(relative).name
        assert secret not in path.read_text(encoding="utf-8")
        assert "private-token" not in path.read_text(encoding="utf-8")
        assert "private.example" not in path.read_text(encoding="utf-8")
        assert "person@example.com" not in path.read_text(encoding="utf-8")
        assert stat.S_IMODE(path.stat().st_mode) == 0o600
    assert list((result_root / "unit-failure").glob("*.raw")) == []
    result_path = result_root / "unit-failure" / "result.json"
    assert result_path.exists()
    assert stat.S_IMODE(result_path.stat().st_mode) == 0o600


def test_success_summary_is_at_most_two_kibibytes(tmp_path):
    spec = CommandSpec(
        command_id="success",
        argv=(sys.executable, "-c", "print('ok')"),
        cwd=tmp_path,
    )
    result = execute_specs(
        ROOT,
        [spec],
        {
            "mode": "full",
            "status": "planned",
            "changed_files": [f"src/file_{index}.py" for index in range(500)],
            "selected_groups": ["full"],
            "reasons": ["full gate"],
            "counts": {},
            "duration": 0.0,
            "first_failure": None,
            "log_paths": [],
            "ui_impacted": False,
            "mapping_miss": False,
        },
        result_root=tmp_path / ".test-results",
        run_id="unit-success",
    )

    summary = format_summary(result)

    assert result["status"] == "passed"
    assert len(summary.encode("utf-8")) <= 2048
    assert set(
        (
            "mode",
            "status",
            "changed_files",
            "selected_groups",
            "reasons",
            "counts",
            "duration",
            "first_failure",
            "log_paths",
            "ui_impacted",
            "backend_impacted",
            "frontend_impacted",
            "mapping_miss",
        )
    ) <= json.loads(summary).keys()


def test_execute_specs_counts_unclosed_sqlite_resource_warnings(tmp_path):
    spec = CommandSpec(
        command_id="sqlite_warning",
        argv=(
            sys.executable,
            "-c",
            "print('ResourceWarning: unclosed database in <sqlite3.Connection object>'); "
            "print('ResourceWarning: unclosed database in <sqlite3.Connection object>')",
        ),
        cwd=tmp_path,
    )
    result = execute_specs(
        ROOT,
        [spec],
        {
            "mode": "full",
            "status": "planned",
            "changed_files": [],
            "selected_groups": ["full"],
            "reasons": ["warning observation"],
            "counts": {},
            "duration": 0.0,
            "first_failure": None,
            "log_paths": [],
            "ui_impacted": False,
            "mapping_miss": False,
        },
        result_root=tmp_path / ".test-results",
        run_id="unit-sqlite-warning",
    )

    assert result["commands"][0]["unclosed_sqlite_connection_warnings"] == 2
    assert result["counts"]["unclosed_sqlite_connection_warnings"] == 2
    assert result["status"] == "failed"
    assert result["counts"]["commands_failed"] == 1
    assert result["first_failure"]["id"] == "unclosed_sqlite_connection"
    assert (
        json.loads(format_summary(result))["counts"][
            "unclosed_sqlite_connection_warnings"
        ]
        == 2
    )


def test_run_id_cannot_escape_private_result_directory(tmp_path):
    with pytest.raises(GateConfigError, match="run id"):
        execute_specs(
            ROOT,
            [],
            {
                "mode": "targeted",
                "status": "planned",
                "changed_files": [],
                "selected_groups": ["control"],
                "reasons": [],
                "counts": {},
                "duration": 0.0,
                "first_failure": None,
                "log_paths": [],
                "ui_impacted": False,
                "mapping_miss": False,
            },
            result_root=tmp_path,
            run_id="../../escape",
        )


def test_release_smoke_prepares_private_safe_config_in_temporary_data(tmp_path):
    root = tmp_path / "repo"
    (root / "data").mkdir(parents=True)
    example = root / "data" / "config.light.example.json"
    example.write_text('{"ai":{"enabled":false}}\n', encoding="utf-8")
    data_dir = tmp_path / "run" / "docker-data"

    _prepare_release_smoke_data(root, data_dir)

    config = data_dir / "config.json"
    assert config.read_text(encoding="utf-8") == example.read_text(encoding="utf-8")
    assert stat.S_IMODE(data_dir.stat().st_mode) == 0o700
    assert stat.S_IMODE(config.stat().st_mode) == 0o600


def test_plan_and_targeted_cli_share_snapshot_and_write_result(tmp_path):
    repo = tmp_path / "repo"
    repo.mkdir()
    subprocess.run(["git", "init", "-q"], cwd=repo, check=True)
    (repo / "project-defaults.yaml").write_text("{}\n", encoding="utf-8")
    (repo / "WORKLOG.md").write_text("before\n", encoding="utf-8")
    for relative in (
        *PROTECTED_RUNTIME_FILES,
        "scripts/check_observability_contract.py",
        "scripts/check_markdown_controls.py",
        "scripts/check_code_size.py",
        "scripts/code_size_policy.py",
        "scripts/test_gate_log.py",
        "tests/code_size_policy.json",
        "AGENTS.md",
        "PLAN.md",
    ):
        target = repo / relative
        target.parent.mkdir(parents=True, exist_ok=True)
        shutil.copy2(ROOT / relative, target)
    for relative in ("docs/contracts", "docs/decisions"):
        shutil.copytree(ROOT / relative, repo / relative)
    subprocess.run(["git", "add", "."], cwd=repo, check=True)
    subprocess.run(
        [
            "git",
            "-c",
            "user.name=Test",
            "-c",
            "user.email=test@example.invalid",
            "commit",
            "-qm",
            "base",
        ],
        cwd=repo,
        check=True,
    )
    snapshot = tmp_path / "snapshot.json"
    plan_output = tmp_path / "plan.json"
    result_root = tmp_path / "results"
    script = str(ROOT / "scripts" / "test_gate.py")
    subprocess.run(
        [sys.executable, script, "--root", str(repo), "snapshot", "--output", str(snapshot)],
        check=True,
        capture_output=True,
        text=True,
    )
    (repo / "WORKLOG.md").write_text("after\n", encoding="utf-8")
    subprocess.run(["git", "add", "WORKLOG.md"], cwd=repo, check=True)

    planned = subprocess.run(
        [
            sys.executable,
            script,
            "--root",
            str(repo),
            "plan",
            "--snapshot",
            str(snapshot),
            "--mapping",
            str(MAPPING),
            "--output",
            str(plan_output),
            "--json",
        ],
        capture_output=True,
        text=True,
    )
    run = subprocess.run(
        [
            sys.executable,
            script,
            "--root",
            str(repo),
            "run",
            "--snapshot",
            str(snapshot),
            "--mapping",
            str(MAPPING),
            "--mode",
            "targeted",
            "--result-root",
            str(result_root),
            "--run-id",
            "cli-targeted",
        ],
        capture_output=True,
        text=True,
    )
    preflight = subprocess.run(
        [
            sys.executable,
            script,
            "--root",
            str(repo),
            "preflight",
            "--staged",
            "--mapping",
            str(MAPPING),
            "--result-root",
            str(result_root),
            "--run-id",
            "cli-preflight",
        ],
        capture_output=True,
        text=True,
    )

    assert planned.returncode == 0, planned.stderr
    assert run.returncode == 0, run.stderr
    assert preflight.returncode == 0, preflight.stderr
    assert len(planned.stdout.encode("utf-8")) <= 2048
    assert len(run.stdout.encode("utf-8")) <= 2048
    plan = json.loads(plan_output.read_text(encoding="utf-8"))
    result = json.loads((result_root / "cli-targeted" / "result.json").read_text(encoding="utf-8"))
    assert plan["changed_files"] == ["WORKLOG.md"]
    assert plan["selected_groups"] == ["control"]
    assert plan["backend_impacted"] is False
    assert plan["frontend_impacted"] is False
    assert result["status"] == "passed"
    assert result["changed_files"] == plan["changed_files"]
    assert result["selected_groups"] == plan["selected_groups"]
    preflight_result = json.loads(
        (result_root / "cli-preflight" / "result.json").read_text(encoding="utf-8")
    )
    assert preflight_result["mode"] == "preflight"
    assert preflight_result["changed_files"] == ["WORKLOG.md"]


def test_plan_cli_without_snapshot_or_git_range_returns_configuration_error(tmp_path):
    result = subprocess.run(
        [
            sys.executable,
            str(ROOT / "scripts" / "test_gate.py"),
            "--root",
            str(tmp_path),
            "plan",
            "--mapping",
            str(MAPPING),
            "--json",
        ],
        capture_output=True,
        text=True,
    )

    assert result.returncode == 2
    assert "snapshot" in result.stderr.lower() or "base" in result.stderr.lower()
