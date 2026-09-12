#!/usr/bin/env python3
"""Plan CI impact against verified main history, conservatively when proof is absent."""

from __future__ import annotations

import argparse
import json
import subprocess
import sys
import tomllib
from pathlib import Path
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.test_gate import _write_json_private, format_summary
from scripts.release_mode import commit_mode
from scripts.test_gate_changes import (
    SHA_PATTERN,
    GateConfigError,
    build_plan,
    changed_files_from_git,
    code_size_policy_domains,
    load_mapping,
)

_VERSION_FILES = {"pyproject.toml", "uv.lock"}


def _git(root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", *args], cwd=root, capture_output=True, text=True, check=False, timeout=30,
    )
    if result.returncode:
        raise GateConfigError("unable to read CI comparison history")
    return result.stdout


def _resolve_commit(root: Path, revision: str) -> str:
    if not revision or revision.startswith("-"):
        raise GateConfigError("CI comparison requires a valid commit")
    resolved = _git(root, "rev-parse", "--verify", f"{revision}^{{commit}}").strip()
    if not SHA_PATTERN.fullmatch(resolved):
        raise GateConfigError("CI comparison requires a full Git SHA")
    return resolved


def verified_main_base(root: Path, head: str) -> str | None:
    """Choose the nearest strictly older first-parent success, regardless of run order."""
    try:
        result = subprocess.run(
            [
                "gh", "run", "list", "--workflow", "test-gate.yml", "--branch", "main",
                "--event", "push", "--status", "success", "--limit", "100", "--json",
                "headSha,status,conclusion,event,headBranch",
            ],
            cwd=root, capture_output=True, text=True, check=False, timeout=30,
        )
        if result.returncode:
            return None
        runs = json.loads(result.stdout)
        if not isinstance(runs, list):
            return None
        candidates = {
            run["headSha"] for run in runs
            if isinstance(run, dict)
            and isinstance(run.get("headSha"), str)
            and SHA_PATTERN.fullmatch(run["headSha"])
            and run.get("status") == "completed"
            and run.get("conclusion") == "success"
            and run.get("event") == "push"
            and run.get("headBranch") == "main"
            and run["headSha"] != head
        }
        history = _git(root, "rev-list", "--first-parent", head).splitlines()
        return next((sha for sha in history[1:] if sha in candidates
                     and commit_mode(root, sha) == "standard"), None)
    except (OSError, subprocess.SubprocessError, ValueError, GateConfigError):
        return None


def _regular_version_diff(root: Path, base: str, head: str) -> bool:
    """Inspect unfiltered raw paths, including paths excluded from normal impact selection."""
    raw = _git(root, "diff", "--raw", "--no-abbrev", "--no-renames", "--no-ext-diff", "-z", base, head, "--")
    fields = raw.split("\0")
    if not raw or fields[-1] != "" or len(fields) % 2 != 1:
        return False
    for index in range(0, len(fields) - 1, 2):
        metadata, path = fields[index:index + 2]
        parts = metadata.split()
        if len(parts) != 5 or path not in _VERSION_FILES:
            return False
        old_mode, new_mode, _, _, status = parts
        if old_mode not in {":100644", ":100755"} or old_mode[1:] != new_mode or status != "M":
            return False
    return True


def _read_version_objects(root: Path, revision: str) -> tuple[str, dict[str, Any], dict[str, Any]]:
    project = tomllib.loads(_git(root, "show", f"{revision}:pyproject.toml"))
    lock = tomllib.loads(_git(root, "show", f"{revision}:uv.lock"))
    metadata = project.get("project")
    packages = lock.get("package")
    if not isinstance(metadata, dict) or metadata.get("name") != "horizon" or not isinstance(packages, list):
        raise ValueError("root project metadata is missing")
    roots = [
        package for package in packages if isinstance(package, dict)
        and package.get("name") == "horizon" and package.get("source") == {"editable": "."}
    ]
    version = metadata.pop("version", None)
    if not isinstance(version, str) or not version.strip() or len(roots) != 1:
        raise ValueError("root package version is missing or ambiguous")
    if roots[0].pop("version", None) != version:
        raise ValueError("project and editable lock versions disagree")
    return version, project, lock


def _same_toml(before: Any, after: Any) -> bool:
    """Keep TOML scalar types and array order significant while ignoring table key order."""
    if type(before) is not type(after):
        return False
    if isinstance(before, dict):
        return before.keys() == after.keys() and all(_same_toml(value, after[key]) for key, value in before.items())
    if isinstance(before, list):
        return len(before) == len(after) and all(_same_toml(left, right) for left, right in zip(before, after))
    return before == after


def version_metadata_only(root: Path, base: str, head: str) -> bool:
    """Prove that both root versions changed together and every other TOML field is equal."""
    try:
        if not _regular_version_diff(root, base, head):
            return False
        before_version, before_project, before_lock = _read_version_objects(root, base)
        after_version, after_project, after_lock = _read_version_objects(root, head)
        return (
            before_version != after_version
            and _same_toml(before_project, after_project)
            and _same_toml(before_lock, after_lock)
        )
    except (OSError, subprocess.TimeoutExpired, ValueError, GateConfigError):
        return False


def _comparison_base(root: Path, base: str, head: str) -> tuple[str, bool]:
    for candidate, verified_range in ((base, True), (f"{head}^", False)):
        try:
            return _resolve_commit(root, candidate), verified_range
        except (OSError, subprocess.TimeoutExpired, GateConfigError):
            continue
    return head, False


def _force_full(plan: dict[str, Any], reason: str) -> None:
    plan.update(
        selected_groups=["control", "full"], backend_impacted=True, frontend_impacted=True,
        ui_impacted=True, e2e_full=True, e2e_targets=[], python_test_targets=[], frontend_related_files=[],
    )
    plan["counts"]["selected_groups"] = 2
    plan["reasons"].insert(0, reason)


def build_ci_plan(
    root: Path,
    event: str,
    base: str,
    head: str,
    mapping: dict[str, Any] | None = None,
) -> dict[str, Any]:
    if event not in {"push", "pull_request", "workflow_dispatch"}:
        raise GateConfigError("unsupported CI event")
    mapping = mapping if mapping is not None else load_mapping(root / "tests/test_impact_map.json")
    head = _resolve_commit(root, head)
    mode = commit_mode(root, head) if event == "push" else "standard"
    verified = verified_main_base(root, head) if event == "push" and mode == "standard" else None
    compare_base, comparison_known = (verified, True) if verified else _comparison_base(root, base, head)
    changed = changed_files_from_git(root, compare_base, head)
    metadata_only = bool(verified and version_metadata_only(root, verified, head))
    policy_domains = code_size_policy_domains(root, compare_base) if "tests/code_size_policy.json" in changed else None
    plan = build_plan([] if metadata_only else changed, mapping, code_size_domains=policy_domains)
    if metadata_only:
        plan["changed_files"] = changed
        plan["counts"]["changed_files"] = len(changed)
        plan["reasons"] = ["verified main baseline: only consistent root version metadata changed"]
    elif event == "push" and mode == "standard" and not verified:
        _force_full(plan, "no verified older main success: full code domains and complete E2E required")
    elif not comparison_known or compare_base == head:
        _force_full(plan, "no verified comparison range: full code domains and complete E2E required")
    plan.update(base_sha=compare_base, head_sha=head, verified_main_base=verified,
                metadata_only=metadata_only, release_mode=mode)
    if event == "workflow_dispatch":
        _force_full(plan, "explicit manual regression covers all domains and E2E")
    return plan


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--event", required=True, choices=("push", "pull_request", "workflow_dispatch"))
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", required=True)
    parser.add_argument("--output", required=True, type=Path)
    args = parser.parse_args(argv)
    try:
        plan = build_ci_plan(_PROJECT_ROOT, args.event, args.base, args.head)
        _write_json_private(args.output, plan)
    except (OSError, subprocess.TimeoutExpired, GateConfigError) as exc:
        sys.stderr.write(f"CI impact planning failed: {exc}\n")
        return 2
    sys.stdout.write(format_summary(plan))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
