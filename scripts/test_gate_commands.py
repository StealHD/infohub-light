"""Command selection for local gates and independently scheduled CI domains."""

from __future__ import annotations

import secrets
import sys
from dataclasses import dataclass
from pathlib import Path
from typing import Any

from scripts.test_gate_changes import GateConfigError


@dataclass(frozen=True)
class CommandSpec:
    command_id: str
    argv: tuple[str, ...]
    cwd: Path
    env: dict[str, str] | None = None
    domain: str = "backend"


def _python(root: Path) -> str:
    candidate = root / ".venv" / "bin" / "python"
    return str(candidate) if candidate.is_file() else sys.executable


def _spec(
    command_id: str,
    argv: list[str] | tuple[str, ...],
    cwd: Path,
    *,
    domain: str = "backend",
    env: dict[str, str] | None = None,
) -> CommandSpec:
    return CommandSpec(command_id, tuple(str(item) for item in argv), cwd, env, domain)


def _code_size_spec(root: Path, scope: str, compare_base: str | None = None) -> CommandSpec:
    domain = {"policy": "control", "backend": "backend", "frontend": "frontend"}[scope]
    argv = [_python(root), "scripts/check_code_size.py", "--scope", scope]
    if compare_base:
        argv.extend(["--compare-base", compare_base])
    return _spec(
        f"code_size_{scope}",
        argv,
        root,
        domain=domain,
    )


def _control_specs(
    root: Path,
    *,
    diff_check_argv: list[str] | tuple[str, ...] | None = None,
    compare_base: str | None = None,
) -> list[CommandSpec]:
    python = _python(root)
    return [
        _spec(
            "markdown_controls",
            [python, "scripts/check_markdown_controls.py"],
            root,
            domain="control",
        ),
        _code_size_spec(root, "policy", compare_base),
        _spec(
            "observability_contract",
            [python, "scripts/check_observability_contract.py"],
            root,
            domain="control",
        ),
        _spec(
            "control_json",
            [python, "-m", "json.tool", "project-defaults.yaml"],
            root,
            domain="control",
        ),
        _spec(
            "diff_check",
            diff_check_argv or ["git", "diff", "--check"],
            root,
            domain="control",
        ),
    ]


def _changed_shell_spec(root: Path, changed_files: list[str]) -> CommandSpec | None:
    shell_files = [
        relative
        for relative in changed_files
        if (relative.endswith(".sh") or relative.startswith(".githooks/"))
        and (root / relative).is_file()
    ]
    if not shell_files:
        return None
    return _spec(
        "shell_changed_syntax",
        ["bash", "-n", *shell_files],
        root,
        domain="control",
    )


def _e2e_contract_spec(
    root: Path,
    changed_files: list[str] | None = None,
    *,
    domain: str = "frontend",
) -> CommandSpec:
    argv = [_python(root), "scripts/check_e2e_contract.py"]
    if changed_files:
        argv.extend(f"--changed-file={relative}" for relative in changed_files)
    return _spec("e2e_contract", argv, root, domain=domain)


def _full_backend_specs(root: Path, compare_base: str | None = None) -> list[CommandSpec]:
    python = _python(root)
    script = str(Path(__file__).resolve().with_name("test_gate.py"))
    return [
        _code_size_spec(root, "backend", compare_base),
        _spec(
            "python_full",
            [
                python,
                "-m",
                "pytest",
                "-q",
                "--tb=short",
                "--maxfail=1",
                "-W",
                "error::ResourceWarning",
            ],
            root,
        ),
        _spec("python_syntax", [python, "-m", "compileall", "-q", "src", "scripts"], root),
        _spec("compose_default", ["docker", "compose", "-f", "docker-compose.yml", "config"], root),
        _spec("compose_light", ["docker", "compose", "-f", "docker-compose.light.yml", "config"], root),
        _spec(
            "compose_test_gate",
            ["docker", "compose", "-f", "docker-compose.test-gate.yml", "config"],
            root,
            env={"HORIZON_AUTH_PASSWORD": "test-gate-config-only"},
        ),
        _spec("json_validation", [python, script, "--root", str(root), "_validate-json"], root),
    ]


def _full_frontend_specs(root: Path, compare_base: str | None = None) -> list[CommandSpec]:
    frontend = root / "frontend"
    return [
        _code_size_spec(root, "frontend", compare_base),
        _e2e_contract_spec(root),
        _spec("frontend_contract", ["npm", "run", "check:ui"], frontend, domain="frontend"),
        _spec("frontend_lint", ["npm", "run", "lint"], frontend, domain="frontend"),
        _spec("frontend_typecheck", ["npm", "run", "typecheck"], frontend, domain="frontend"),
        _spec("frontend_vitest", ["npm", "test", "--", "--reporter=default"], frontend, domain="frontend"),
        _spec("frontend_build", ["npm", "run", "build"], frontend, domain="frontend"),
    ]


def _targeted_specs(root: Path, plan: dict[str, Any], mapping: dict[str, Any]) -> list[CommandSpec]:
    python = _python(root)
    groups = set(plan["selected_groups"])
    specs: list[CommandSpec] = []
    if any(path.startswith("frontend/e2e/") for path in plan["changed_files"]):
        specs.append(_e2e_contract_spec(root, plan["changed_files"], domain="control"))
    python_groups = {
        "python_ai_orchestrator",
        "python_api_store",
        "python_feed",
        "python_queue_worker",
        "python_scrapers",
        "python_scripts",
        "python_source_acquisition",
    }
    targets = set(plan.get("python_test_targets", []))
    for group in sorted(groups & python_groups):
        targets.update(mapping.get("group_tests", {}).get(group, []))
    if groups & python_groups or targets or "code_size_backend" in groups:
        specs.append(_code_size_spec(root, "backend", plan.get("base_sha")))
    if targets:
        # A removed/renamed spec cannot be passed to pytest. Cover surviving tests.
        selected_targets = sorted(targets) if all(
            (root / target.partition("::")[0]).is_file() for target in targets
        ) else []
        if not selected_targets:
            plan["reasons"].append("selected Python target removed or unavailable: full backend pytest")
        specs.append(
            _spec(
                "python_targeted" if selected_targets else "python_full",
                [
                    python,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "--maxfail=1",
                    "-W",
                    "error::ResourceWarning",
                    *selected_targets,
                ],
                root,
            )
        )
    changed_python = [
        relative
        for relative in plan["changed_files"]
        if relative.endswith(".py") and (root / relative).is_file()
    ]
    if changed_python:
        specs.append(_spec("python_changed_syntax", [python, "-m", "py_compile", *changed_python], root))

    frontend = root / "frontend"
    if groups & {
        "code_size_frontend", "frontend_checks", "frontend_full", "frontend_related",
    }:
        specs.append(_code_size_spec(root, "frontend", plan.get("base_sha")))
    if groups & {"frontend_checks", "frontend_full", "frontend_related"}:
        specs.append(_e2e_contract_spec(root, plan["changed_files"]))
    if "frontend_checks" in groups:
        specs.extend(
            [
                _spec("frontend_contract", ["npm", "run", "check:ui"], frontend, domain="frontend"),
                _spec("frontend_lint", ["npm", "run", "lint"], frontend, domain="frontend"),
                _spec("frontend_typecheck", ["npm", "run", "typecheck"], frontend, domain="frontend"),
            ]
        )
    related = plan.get("frontend_related_files", [])
    related_files_exist = all((frontend / relative).is_file() for relative in related)
    if "frontend_related" in groups and related and related_files_exist:
        specs.append(
            _spec(
                "frontend_related",
                [
                    "npx",
                    "vitest",
                    "related",
                    *related,
                    "--run",
                    "--passWithNoTests",
                    "--reporter=default",
                ],
                frontend,
                domain="frontend",
            )
        )
    elif "frontend_related" in groups and related and not related_files_exist:
        specs.extend(_full_frontend_specs(root, plan.get("base_sha"))[-5:])
    if "frontend_full" in groups:
        specs.extend(_full_frontend_specs(root, plan.get("base_sha")))
    return specs


def _release_specs(
    root: Path,
    plan: dict[str, Any],
    *,
    full_e2e: bool = False,
) -> list[CommandSpec]:
    password = secrets.token_urlsafe(24)
    smoke_env = {
        "HORIZON_AUTH_USER": "admin",
        "HORIZON_AUTH_PASSWORD": password,
        "HORIZON_REQUIRE_WORKER_FOR_READINESS": "false",
        "HORIZON_TEST_DATA_DIR": "{run_dir}/docker-data",
        "HORIZON_TEST_LOG_DIR": "{run_dir}/docker-logs",
        "HORIZON_TEST_WEB_PORT": "18081",
    }
    playwright_argv = ["npm", "run", "e2e:release"]
    if not full_e2e and not plan.get("e2e_full") and plan.get("e2e_targets"):
        playwright_argv.extend(["--", *plan["e2e_targets"]])
    return [
        _e2e_contract_spec(root, plan.get("changed_files"), domain="e2e"),
        _spec(
            "release_playwright",
            playwright_argv,
            root / "frontend",
            domain="e2e",
        ),
        _spec(
            "release_api_docker_smoke",
            [
                _python(root),
                "scripts/service_stack_smoke.py",
                "--compose-file",
                "docker-compose.test-gate.yml",
                "--base-url",
                "http://127.0.0.1:18081",
                "--api-only",
                "--project-name",
                "inteliscope-test-gate-{run_id_lower}",
                "--cleanup",
                "--report-dir",
                "{run_dir}",
                "--json-output",
                "{run_dir}/service-stack-smoke.json",
            ],
            root,
            domain="smoke",
            env=smoke_env,
        ),
    ]


def build_command_specs(
    root: Path,
    plan: dict[str, Any],
    mapping: dict[str, Any],
    *,
    mode: str,
    scope: str = "all",
    diff_check_argv: list[str] | tuple[str, ...] | None = None,
    full_e2e: bool = False,
    skip_control: bool = False,
) -> list[CommandSpec]:
    if skip_control and scope in {"all", "control"}:
        raise GateConfigError("--skip-control requires a specific code, E2E or smoke scope")
    if mode not in {"preflight", "targeted", "full", "release"}:
        raise GateConfigError(f"unsupported run mode: {mode}")
    if scope not in {"all", "control", "backend", "frontend", "e2e", "smoke"}:
        raise GateConfigError(f"unsupported run scope: {scope}")
    compare_base = plan.get("base_sha")
    if diff_check_argv is None and compare_base and plan.get("head_sha"):
        diff_check_argv = ["git", "diff", "--check", compare_base, plan["head_sha"], "--"]
    specs = _control_specs(
        root,
        diff_check_argv=diff_check_argv,
        compare_base=compare_base,
    )
    if mode == "preflight":
        shell_syntax = _changed_shell_spec(root, plan["changed_files"])
        if shell_syntax is not None:
            specs.append(shell_syntax)
        if "full" in set(plan["selected_groups"]):
            specs.extend(
                spec
                for spec in [
                    *_full_backend_specs(root, compare_base),
                    *_full_frontend_specs(root, compare_base),
                ]
                if not spec.command_id.startswith("compose_")
            )
        else:
            specs.extend(_targeted_specs(root, plan, mapping))
    elif mode == "targeted" and "full" not in set(plan["selected_groups"]):
        specs.extend(_targeted_specs(root, plan, mapping))
    else:
        specs.extend(_full_backend_specs(root, compare_base))
        specs.extend(_full_frontend_specs(root, compare_base))
    if mode == "release":
        specs.extend(_release_specs(root, plan, full_e2e=full_e2e))
    deduplicated: list[CommandSpec] = []
    seen: set[str] = set()
    for spec in specs:
        if spec.command_id not in seen:
            deduplicated.append(spec)
            seen.add(spec.command_id)
    if any(spec.command_id == "frontend_build" for spec in deduplicated):
        deduplicated = [spec for spec in deduplicated if spec.command_id != "frontend_typecheck"]
    if scope == "all":
        return deduplicated
    allowed_domains = {scope} if skip_control else {scope, "control"}
    return [
        spec
        for spec in deduplicated
        if spec.domain in allowed_domains
    ]
