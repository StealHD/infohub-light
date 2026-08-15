#!/usr/bin/env python3
"""Low-output, deterministic test selection and execution gate."""

from __future__ import annotations

import argparse
import json
import os
import re
import secrets
import shlex
import subprocess
import sys
import tempfile
import time
from collections import deque
from dataclasses import dataclass
from datetime import datetime, timezone
from pathlib import Path, PurePosixPath
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.test_gate_log import (
    redact_gate_text as _redact,
    sanitize_gate_log as _sanitize_log,
    sensitive_values as _sensitive_values,
    sqlite_warning_gate_failure as _sqlite_warning_gate_failure,
    unclosed_sqlite_connection_warnings as _unclosed_sqlite_connection_warnings,
)
from scripts.test_gate_changes import (
    EXCLUDED_PARTS,
    SECRET_NAME_PARTS,
    GateConfigError,
    build_plan,
    build_snapshot,
    changed_files_from_git,
    changed_files_from_snapshot,
    changed_files_from_staged,
    code_size_policy_domains,
    load_mapping,
    load_snapshot,
    _is_safe_relative_path,
)


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


def _product_docs_spec(root: Path, changed_files: list[str]) -> CommandSpec | None:
    if not changed_files:
        return None
    python = _python(root)
    return _spec(
        "product_docs_preflight",
        [
            python,
            "scripts/check_product_docs.py",
            *[f"--changed-file={relative}" for relative in changed_files],
        ],
        root,
        domain="control",
    )


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
    script = str(Path(__file__).resolve())
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
        specs.append(
            _spec(
                "python_targeted",
                [
                    python,
                    "-m",
                    "pytest",
                    "-q",
                    "--tb=short",
                    "--maxfail=1",
                    "-W",
                    "error::ResourceWarning",
                    *sorted(targets),
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
) -> list[CommandSpec]:
    if mode not in {"preflight", "targeted", "full", "release"}:
        raise GateConfigError(f"unsupported run mode: {mode}")
    if scope not in {"all", "control", "backend", "frontend", "e2e", "smoke"}:
        raise GateConfigError(f"unsupported run scope: {scope}")
    compare_base = plan.get("base_sha")
    specs = _control_specs(
        root,
        diff_check_argv=diff_check_argv,
        compare_base=compare_base,
    )
    if mode == "preflight":
        product_docs = _product_docs_spec(root, plan["changed_files"])
        if product_docs is not None:
            specs.append(product_docs)
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
    if scope == "all":
        return deduplicated
    allowed_domains = {scope, "control"}
    return [
        spec
        for spec in deduplicated
        if spec.domain in allowed_domains
    ]


def _failure_details(
    spec: CommandSpec,
    exit_code: int,
    log_path: Path,
    sensitive_values: list[str],
) -> dict[str, Any]:
    last_lines: deque[str] = deque(maxlen=80)
    failure_id: str | None = None
    pattern = re.compile(
        r"(?:FAILED|FAIL)\s+((?:tests|frontend)/[A-Za-z0-9_./\-\[\]]+(?:::[A-Za-z0-9_./\-\[\]]+)*)"
    )
    with log_path.open("r", encoding="utf-8", errors="replace") as handle:
        for line in handle:
            last_lines.append(line.rstrip("\n"))
            if failure_id is None and (match := pattern.search(line)):
                failure_id = match.group(1)
    excerpt = "\n".join(last_lines)
    encoded = excerpt.encode("utf-8")
    if len(encoded) > 7000:
        excerpt = encoded[-7000:].decode("utf-8", errors="ignore")
    return {
        "command": _redact(shlex.join(spec.argv), sensitive_values),
        "command_id": spec.command_id,
        "duration": 0.0,
        "exit_code": exit_code,
        "id": failure_id or spec.command_id,
        "excerpt": excerpt,
    }


def _display_path(root: Path, path: Path) -> str:
    try:
        return str(path.relative_to(root))
    except ValueError:
        return str(path)


def _prepare_release_smoke_data(root: Path, data_dir: Path) -> None:
    source = root / "data" / "config.light.example.json"
    if not source.is_file():
        raise GateConfigError("release smoke requires data/config.light.example.json")
    data_dir.mkdir(parents=True, exist_ok=True)
    data_dir.chmod(0o700)
    target = data_dir / "config.json"
    descriptor = os.open(target, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with source.open("rb") as source_handle, os.fdopen(descriptor, "wb") as target_handle:
        for chunk in iter(lambda: source_handle.read(1024 * 1024), b""):
            target_handle.write(chunk)
    target.chmod(0o600)


def execute_specs(
    root: Path,
    specs: list[CommandSpec],
    base_result: dict[str, Any],
    *,
    result_root: Path | None = None,
    run_id: str | None = None,
) -> dict[str, Any]:
    started = time.monotonic()
    run_id = run_id or datetime.now(timezone.utc).strftime("%Y%m%dT%H%M%SZ") + f"-{os.getpid()}"
    if not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9._-]{0,95}", run_id):
        raise GateConfigError("run id must be 1-96 safe filename characters")
    result_root = result_root or root / ".test-results"
    run_dir = result_root / run_id
    try:
        run_dir.mkdir(parents=True, exist_ok=False)
    except FileExistsError as exc:
        raise GateConfigError(f"result run id already exists: {run_id}") from exc
    os.chmod(run_dir, 0o700)
    result = dict(base_result)
    result["status"] = "passed"
    result["first_failure"] = None
    result["log_paths"] = []
    commands: list[dict[str, Any]] = []
    passed = 0
    failed = 0
    error = 0
    unclosed_sqlite_connection_warnings = 0
    for index, original_spec in enumerate(specs, start=1):
        replacements = {
            "{run_dir}": str(run_dir),
            "{run_id}": run_id,
            "{run_id_lower}": run_id.lower(),
        }
        def materialize(value: str) -> str:
            for marker, replacement in replacements.items():
                value = value.replace(marker, replacement)
            return value
        materialized_env = (
            {name: materialize(value) for name, value in original_spec.env.items()}
            if original_spec.env
            else None
        )
        spec = CommandSpec(
            command_id=original_spec.command_id,
            argv=tuple(materialize(value) for value in original_spec.argv),
            cwd=original_spec.cwd,
            env=materialized_env,
            domain=original_spec.domain,
        )
        if spec.command_id == "release_api_docker_smoke" and spec.env:
            _prepare_release_smoke_data(root, Path(spec.env["HORIZON_TEST_DATA_DIR"]))
            log_dir = Path(spec.env["HORIZON_TEST_LOG_DIR"])
            log_dir.mkdir(parents=True, exist_ok=True)
            log_dir.chmod(0o700)
        command_started = time.monotonic()
        log_path = run_dir / f"{index:02d}-{spec.command_id}.log"
        environment = dict(os.environ)
        if spec.env:
            environment.update(spec.env)
        sensitive_values = _sensitive_values(environment)
        exit_code = 2
        missing_executable = False
        with tempfile.TemporaryFile(
            mode="w+",
            encoding="utf-8",
            errors="replace",
        ) as handle:
            try:
                handle.write(f"$ {shlex.join(spec.argv)}\n")
                handle.flush()
                try:
                    completed = subprocess.run(
                        spec.argv,
                        cwd=spec.cwd,
                        env=environment,
                        stdout=handle,
                        stderr=subprocess.STDOUT,
                        check=False,
                    )
                    exit_code = completed.returncode
                except FileNotFoundError as exc:
                    missing_executable = True
                    handle.write(f"environment error: executable not found: {exc.filename}\n")
            finally:
                handle.flush()
                handle.seek(0)
                _sanitize_log(handle, log_path, sensitive_values)
        for generated_report in run_dir.glob("*.json"):
            try:
                report_text = generated_report.read_text(encoding="utf-8")
            except (OSError, UnicodeDecodeError):
                continue
            generated_report.write_text(
                _redact(report_text, sensitive_values),
                encoding="utf-8",
            )
            generated_report.chmod(0o600)
        elapsed = round(time.monotonic() - command_started, 3)
        result["log_paths"].append(_display_path(root, log_path))
        command_sqlite_warnings = _unclosed_sqlite_connection_warnings(
            log_path
        )
        unclosed_sqlite_connection_warnings += command_sqlite_warnings
        command_result = {
            "command_id": spec.command_id,
            "command": _redact(shlex.join(spec.argv), sensitive_values),
            "duration": elapsed,
            "exit_code": exit_code,
            "log_path": _display_path(root, log_path),
            "unclosed_sqlite_connection_warnings": command_sqlite_warnings,
        }
        commands.append(command_result)
        if exit_code == 0 and command_sqlite_warnings:
            failed += 1
            result.update(_sqlite_warning_gate_failure(command_result, command_sqlite_warnings))
            break
        if exit_code == 0:
            passed += 1
            continue
        if missing_executable:
            error += 1
            result["status"] = "error"
        else:
            failed += 1
            result["status"] = "failed"
        result["first_failure"] = _failure_details(
            spec,
            exit_code,
            log_path,
            sensitive_values,
        )
        result["first_failure"]["duration"] = elapsed
        break
    result["commands"] = commands
    result["counts"] = {
        "commands_total": len(specs),
        "commands_run": len(commands),
        "commands_passed": passed,
        "commands_failed": failed,
        "commands_error": error,
        "unclosed_sqlite_connection_warnings": (
            unclosed_sqlite_connection_warnings
        ),
    }
    result["duration"] = round(time.monotonic() - started, 3)
    result_path = run_dir / "result.json"
    result["result_path"] = _display_path(root, result_path)
    _write_json_private(result_path, result)
    return result


def _bounded_array(values: Any, limit: int) -> Any:
    if not isinstance(values, list) or len(values) <= limit:
        return values
    return [*values[:limit], f"...<{len(values) - limit} more>"]


def format_summary(result: dict[str, Any]) -> str:
    limit = 2048 if result.get("status") in {"passed", "planned"} else 8192
    summary = {
        "mode": result.get("mode"),
        "status": result.get("status"),
        "changed_files": _bounded_array(result.get("changed_files", []), 12),
        "selected_groups": _bounded_array(result.get("selected_groups", []), 12),
        "reasons": _bounded_array(result.get("reasons", []), 4),
        "counts": result.get("counts", {}),
        "duration": result.get("duration", 0.0),
        "first_failure": result.get("first_failure"),
        "log_paths": _bounded_array(result.get("log_paths", []), 8),
        "ui_impacted": bool(result.get("ui_impacted")),
        "backend_impacted": bool(result.get("backend_impacted")),
        "frontend_impacted": bool(result.get("frontend_impacted")),
        "mapping_miss": bool(result.get("mapping_miss")),
    }

    def serialize() -> str:
        return json.dumps(summary, ensure_ascii=False, separators=(",", ":")) + "\n"

    text = serialize()
    if len(text.encode("utf-8")) <= limit:
        return text
    failure = summary.get("first_failure")
    if isinstance(failure, dict) and isinstance(failure.get("excerpt"), str):
        excerpt = failure["excerpt"].encode("utf-8")
        available = max(256, limit - 1400)
        failure["excerpt"] = excerpt[-available:].decode("utf-8", errors="ignore")
    summary["changed_files"] = _bounded_array(result.get("changed_files", []), 3)
    summary["reasons"] = _bounded_array(result.get("reasons", []), 1)
    summary["log_paths"] = _bounded_array(result.get("log_paths", []), 3)
    text = serialize()
    while len(text.encode("utf-8")) > limit and isinstance(summary.get("first_failure"), dict):
        excerpt = summary["first_failure"].get("excerpt", "")
        if len(excerpt) <= 128:
            break
        summary["first_failure"]["excerpt"] = excerpt[len(excerpt) // 4 :]
        text = serialize()
    if len(text.encode("utf-8")) > limit:
        summary["first_failure"] = {
            "id": (result.get("first_failure") or {}).get("id"),
            "excerpt": "<summary truncated; see private log>",
        }
        text = serialize()
    return text


def _selector_changed_files(args: argparse.Namespace, root: Path) -> list[str]:
    has_snapshot = bool(getattr(args, "snapshot", None))
    has_base = bool(getattr(args, "base", None))
    has_head = bool(getattr(args, "head", None))
    has_staged = bool(getattr(args, "staged", False))
    selectors = int(has_snapshot) + int(has_base or has_head) + int(has_staged)
    if selectors > 1:
        raise GateConfigError(
            "choose one of --snapshot, --staged, or --base/--head"
        )
    if has_snapshot:
        return changed_files_from_snapshot(root, load_snapshot(args.snapshot))
    if has_staged:
        return changed_files_from_staged(root)
    if has_base != has_head:
        raise GateConfigError("--base and --head must be provided together")
    if has_base:
        return changed_files_from_git(root, args.base, args.head)
    raise GateConfigError(
        "a task --snapshot, --staged, or Git --base/--head range is required"
    )


def _selector_base_sha(args: argparse.Namespace, root: Path) -> str:
    if getattr(args, "snapshot", None):
        return str(load_snapshot(args.snapshot)["base_sha"])
    if getattr(args, "staged", False):
        result = subprocess.run(
            ["git", "rev-parse", "HEAD"],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if result.returncode != 0:
            raise GateConfigError("unable to resolve HEAD for staged comparison")
        return result.stdout.strip()
    if getattr(args, "base", None):
        return str(args.base)
    raise GateConfigError("a comparison base is required")


def _selector_impact_plan(
    args: argparse.Namespace,
    root: Path,
    mapping: dict[str, Any],
) -> dict[str, Any]:
    changed_files = _selector_changed_files(args, root)
    base_sha = _selector_base_sha(args, root)
    policy_domains = None
    if "tests/code_size_policy.json" in changed_files:
        policy_domains = code_size_policy_domains(root, base_sha)
    plan = build_plan(changed_files, mapping, code_size_domains=policy_domains)
    plan["base_sha"] = base_sha
    return plan


def _preflight_diff_check_argv(
    args: argparse.Namespace,
    root: Path,
    changed_files: list[str],
) -> list[str]:
    if getattr(args, "staged", False):
        return ["git", "diff", "--cached", "--check", "--"]
    if getattr(args, "base", None):
        return ["git", "diff", "--check", args.base, args.head, "--"]
    return [
        _python(root),
        str(Path(__file__).resolve()),
        "--root",
        str(root),
        "_check-snapshot-diff",
        *[f"--changed-file={relative}" for relative in changed_files],
    ]


def _check_snapshot_diff(root: Path, changed_files: list[str]) -> None:
    tracked = subprocess.run(
        ["git", "diff", "--check", "HEAD", "--"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if tracked.returncode != 0:
        detail = tracked.stdout or tracked.stderr
        raise GateConfigError(f"tracked diff check failed: {detail[:1000].strip()}")
    for relative in changed_files:
        if not _is_safe_relative_path(relative):
            raise GateConfigError(f"unsafe changed path: {relative!r}")
        path = root / relative
        if not path.is_file():
            continue
        is_tracked = subprocess.run(
            ["git", "ls-files", "--error-unmatch", "--", relative],
            cwd=root,
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            check=False,
        )
        if is_tracked.returncode == 0:
            continue
        untracked = subprocess.run(
            ["git", "diff", "--no-index", "--check", "--", "/dev/null", relative],
            cwd=root,
            capture_output=True,
            text=True,
            check=False,
        )
        if untracked.returncode > 1:
            detail = untracked.stdout or untracked.stderr
            raise GateConfigError(
                f"untracked diff check failed for {relative}: {detail[:1000].strip()}"
            )


def _load_plan_file(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GateConfigError(f"impact plan not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GateConfigError("invalid impact plan JSON") from exc
    required = {
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
    }
    if not isinstance(payload, dict) or not required <= payload.keys():
        raise GateConfigError("impact plan is missing required result fields")
    return payload


def _blank_plan(mode: str) -> dict[str, Any]:
    return {
        "mode": mode,
        "status": "planned",
        "changed_files": [],
        "selected_groups": [mode],
        "reasons": [f"explicit {mode} gate"],
        "counts": {"changed_files": 0, "selected_groups": 1},
        "duration": 0.0,
        "first_failure": None,
        "log_paths": [],
        "ui_impacted": mode == "release",
        "backend_impacted": mode in {"full", "release"},
        "frontend_impacted": mode in {"full", "release"},
        "mapping_miss": False,
        "python_test_targets": [],
        "frontend_related_files": [],
        "e2e_full": mode == "release",
        "e2e_targets": [],
        "base_sha": None,
    }


def _run_plan(mode: str, impact_plan: dict[str, Any]) -> dict[str, Any]:
    plan = dict(impact_plan)
    plan["mode"] = mode
    if mode == "full":
        plan["selected_groups"] = ["full"]
        plan["backend_impacted"] = True
        plan["frontend_impacted"] = True
    elif mode == "release":
        plan["selected_groups"] = ["full", "release_api_docker_smoke", "release_playwright"]
        plan["backend_impacted"] = True
        plan["frontend_impacted"] = True
    return plan


def _reconcile_mapping_miss(
    result: dict[str, Any], impact_plan: dict[str, Any] | None, mapping: dict[str, Any]
) -> None:
    if not impact_plan or result.get("status") == "passed":
        return
    if impact_plan.get("mapping_miss"):
        result["mapping_miss"] = True
        return
    selected = set(impact_plan.get("selected_groups", []))
    if "full" in selected:
        return
    failure = result.get("first_failure") or {}
    failure_id = str(failure.get("id") or "")
    failure_path = failure_id.split("::", 1)[0]
    if not failure_path.startswith("tests/"):
        return
    covered = set(impact_plan.get("python_test_targets", []))
    for group in selected:
        covered.update(mapping.get("group_tests", {}).get(group, []))
    if failure_path not in covered:
        result["mapping_miss"] = True


def _validate_json_files(root: Path) -> None:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise GateConfigError("JSON validation root is not a Git worktree")
    paths = result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
    for relative in sorted(path for path in paths if path.endswith(".json")):
        pure = PurePosixPath(relative)
        upper = pure.name.upper()
        if any(part in EXCLUDED_PARTS for part in pure.parts):
            continue
        if any(marker in upper for marker in SECRET_NAME_PARTS):
            continue
        candidate = root / relative
        if not candidate.is_file():
            continue
        try:
            json.loads(candidate.read_text(encoding="utf-8"))
        except (OSError, json.JSONDecodeError) as exc:
            raise GateConfigError(f"invalid JSON file {relative}: {exc}") from exc


def _write_json_private(path: Path, payload: dict[str, Any]) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    descriptor = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    try:
        with os.fdopen(descriptor, "w", encoding="utf-8") as handle:
            json.dump(payload, handle, ensure_ascii=False, sort_keys=True, separators=(",", ":"))
            handle.write("\n")
    finally:
        try:
            os.chmod(path, 0o600)
        except OSError:
            pass


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    subparsers = parser.add_subparsers(dest="command", required=True)
    snapshot = subparsers.add_parser("snapshot", help="record safe task-start file hashes")
    snapshot.add_argument("--output", type=Path, required=True)
    plan = subparsers.add_parser("plan", help="select deterministic gates for an impact set")
    plan.add_argument("--snapshot", type=Path)
    plan.add_argument("--base")
    plan.add_argument("--head")
    plan.add_argument("--mapping", type=Path)
    plan.add_argument("--output", type=Path)
    plan.add_argument("--json", action="store_true")
    preflight = subparsers.add_parser(
        "preflight",
        help="run bounded impacted checks before an expensive full or release gate",
    )
    preflight.add_argument("--snapshot", type=Path)
    preflight.add_argument("--staged", action="store_true")
    preflight.add_argument("--base")
    preflight.add_argument("--head")
    preflight.add_argument("--mapping", type=Path)
    preflight.add_argument("--result-root", type=Path)
    preflight.add_argument("--run-id")
    run = subparsers.add_parser("run", help="execute a targeted, full, or release gate")
    run.add_argument("--snapshot", type=Path)
    run.add_argument("--base")
    run.add_argument("--head")
    run.add_argument("--mapping", type=Path)
    run.add_argument("--impact-plan", type=Path)
    run.add_argument("--mode", choices=("targeted", "full", "release"), required=True)
    run.add_argument(
        "--scope",
        choices=("all", "control", "backend", "frontend", "e2e", "smoke"),
        default="all",
    )
    run.add_argument("--result-root", type=Path)
    run.add_argument("--run-id")
    run.add_argument(
        "--full-e2e",
        action="store_true",
        help="run every Playwright spec for the final main/release revision",
    )
    subparsers.add_parser("_validate-json", help=argparse.SUPPRESS)
    snapshot_diff = subparsers.add_parser("_check-snapshot-diff", help=argparse.SUPPRESS)
    snapshot_diff.add_argument("--changed-file", action="append", default=[])
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    try:
        if args.command == "snapshot":
            _write_json_private(args.output, build_snapshot(root))
            print(json.dumps({"status": "passed", "snapshot": str(args.output)}, separators=(",", ":")))
            return 0
        if args.command == "_validate-json":
            _validate_json_files(root)
            return 0
        if args.command == "_check-snapshot-diff":
            _check_snapshot_diff(root, args.changed_file)
            return 0
        mapping_path = args.mapping or root / "tests" / "test_impact_map.json"
        mapping = load_mapping(mapping_path)
        if args.command == "plan":
            plan = _selector_impact_plan(args, root, mapping)
            if args.output:
                _write_json_private(args.output, plan)
            if args.json:
                sys.stdout.write(format_summary(plan))
            else:
                print(
                    f"status=planned changed={len(plan['changed_files'])} "
                    f"groups={','.join(plan['selected_groups'])} ui={str(plan['ui_impacted']).lower()}"
                )
            return 0
        if args.command == "preflight":
            impact_plan = _selector_impact_plan(args, root, mapping)
            changed_files = impact_plan["changed_files"]
            plan = _run_plan("preflight", impact_plan)
            specs = build_command_specs(
                root,
                plan,
                mapping,
                mode="preflight",
                diff_check_argv=_preflight_diff_check_argv(
                    args,
                    root,
                    changed_files,
                ),
            )
            result = execute_specs(
                root,
                specs,
                plan,
                result_root=args.result_root,
                run_id=args.run_id,
            )
            _reconcile_mapping_miss(result, impact_plan, mapping)
            result_path = Path(result["result_path"])
            if not result_path.is_absolute():
                result_path = root / result_path
            _write_json_private(result_path, result)
            sys.stdout.write(format_summary(result))
            return 0 if result["status"] == "passed" else (
                2 if result["status"] == "error" else 1
            )
        if args.command == "run":
            impact_plan: dict[str, Any] | None = None
            if args.impact_plan:
                impact_plan = _load_plan_file(args.impact_plan)
            elif args.snapshot or args.base or args.head:
                impact_plan = _selector_impact_plan(args, root, mapping)
            elif args.mode == "targeted":
                raise GateConfigError("targeted mode requires --snapshot, --base/--head, or --impact-plan")
            plan = _run_plan(args.mode, impact_plan or _blank_plan(args.mode))
            specs = build_command_specs(
                root,
                plan,
                mapping,
                mode=args.mode,
                scope=args.scope,
                full_e2e=args.full_e2e,
            )
            result = execute_specs(
                root,
                specs,
                plan,
                result_root=args.result_root,
                run_id=args.run_id,
            )
            _reconcile_mapping_miss(result, impact_plan, mapping)
            result_path = Path(result["result_path"])
            if not result_path.is_absolute():
                result_path = root / result_path
            _write_json_private(result_path, result)
            sys.stdout.write(format_summary(result))
            return 0 if result["status"] == "passed" else (2 if result["status"] == "error" else 1)
    except GateConfigError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, separators=(",", ":")), file=sys.stderr)
        return 2
    return 2


if __name__ == "__main__":
    raise SystemExit(main())
