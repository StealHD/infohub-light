"""Task snapshots and deterministic impact selection for the test gate."""

from __future__ import annotations

import hashlib
import json
import os
import re
import subprocess
from fnmatch import fnmatchcase
from pathlib import Path, PurePosixPath
from typing import Any


SNAPSHOT_VERSION = 2
EXCLUDED_PARTS = {
    ".git", ".mypy_cache", ".pytest_cache", ".ruff_cache", ".superpowers",
    ".test-results", ".uv", ".venv", "__pycache__", "build", "dist", "logs",
    "node_modules", "playwright-report", "test-results", "venv",
}
EXCLUDED_PREFIXES = ("data/", "docs/_posts/", "src/ui/service_static/")
SECRET_NAME_PARTS = ("KEY", "TOKEN", "SECRET", "PASSWORD", "CREDENTIAL")
SECRET_DATA_SUFFIXES = {".env", ".json", ".txt", ".yaml", ".yml"}
KNOWN_GROUPS = {
    "code_size_backend", "code_size_frontend", "control", "frontend_checks",
    "frontend_full", "frontend_related", "full",
    "python_ai_orchestrator", "python_api_store", "python_feed",
    "python_queue_worker", "python_scrapers", "python_scripts",
    "python_source_acquisition", "python_test_files",
}
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class GateConfigError(RuntimeError):
    """Raised for invalid snapshots, mappings, or environment configuration."""


def _is_safe_relative_path(relative: str) -> bool:
    path = PurePosixPath(relative)
    if path.is_absolute() or ".." in path.parts:
        return False
    if any(part in EXCLUDED_PARTS for part in path.parts) or relative.startswith(EXCLUDED_PREFIXES):
        return False
    name_upper = path.name.upper()
    if path.name == ".env" or path.name.startswith(".env."):
        return False
    if path.suffix.lower() in SECRET_DATA_SUFFIXES and any(
        marker in name_upper for marker in SECRET_NAME_PARTS
    ):
        return False
    return path.suffix.lower() not in {".db", ".sqlite", ".sqlite3", ".pem", ".key", ".p12"}


def _git_file_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "--cached", "--others", "--exclude-standard", "-z"],
        cwd=root, capture_output=True, check=False,
    )
    if result.returncode != 0:
        raise GateConfigError("snapshot root is not a readable Git worktree")
    return sorted(
        path for path in result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
        if path and _is_safe_relative_path(path)
    )


def _git_head(root: Path) -> str:
    result = subprocess.run(
        ["git", "rev-parse", "HEAD"], cwd=root, capture_output=True, text=True, check=False,
    )
    revision = result.stdout.strip()
    if result.returncode != 0 or not SHA_PATTERN.fullmatch(revision):
        raise GateConfigError("snapshot root has no valid HEAD commit")
    return revision


def _sha256(path: Path) -> str:
    digest = hashlib.sha256()
    with path.open("rb") as handle:
        for chunk in iter(lambda: handle.read(1024 * 1024), b""):
            digest.update(chunk)
    return digest.hexdigest()


def build_snapshot(root: Path) -> dict[str, Any]:
    files: dict[str, str] = {}
    for relative in _git_file_paths(root):
        path = root / relative
        if path.is_symlink():
            files[relative] = hashlib.sha256(os.readlink(path).encode("utf-8")).hexdigest()
        elif path.is_file():
            files[relative] = _sha256(path)
    return {"version": SNAPSHOT_VERSION, "base_sha": _git_head(root), "files": files}


def load_snapshot(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GateConfigError(f"snapshot not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GateConfigError("invalid snapshot JSON") from exc
    if not isinstance(payload, dict):
        raise GateConfigError("snapshot must be an object")
    if payload.get("version") != SNAPSHOT_VERSION:
        raise GateConfigError("unsupported snapshot version")
    if not isinstance(payload.get("base_sha"), str) or not SHA_PATTERN.fullmatch(payload["base_sha"]):
        raise GateConfigError("snapshot base_sha must be a full lowercase Git SHA")
    files = payload.get("files")
    if not isinstance(files, dict):
        raise GateConfigError("snapshot files must be an object")
    for relative, digest in files.items():
        if not isinstance(relative, str) or not _is_safe_relative_path(relative):
            raise GateConfigError(f"unsafe snapshot path: {relative!r}")
        if not isinstance(digest, str) or not re.fullmatch(r"[0-9a-f]{64}", digest):
            raise GateConfigError(f"invalid snapshot digest for {relative}")
    return payload


def changed_files_from_snapshot(root: Path, snapshot: dict[str, Any]) -> list[str]:
    before = snapshot["files"]
    after = build_snapshot(root)["files"]
    return sorted(path for path in set(before) | set(after) if before.get(path) != after.get(path))


def _changed_files_from_name_status(output: bytes) -> list[str]:
    fields = output.decode("utf-8", errors="surrogateescape").split("\0")
    changed: list[str] = []
    index = 0
    while index < len(fields) and fields[index]:
        status = fields[index]
        index += 1
        path_count = 2 if status.startswith(("R", "C")) else 1
        if index + path_count > len(fields):
            raise GateConfigError("malformed Git name-status output")
        changed.extend(path for path in fields[index:index + path_count] if _is_safe_relative_path(path))
        index += path_count
    return sorted(set(changed))


def changed_files_from_git(root: Path, base: str, head: str) -> list[str]:
    if not base or not head or base.startswith("-") or head.startswith("-"):
        raise GateConfigError("base and head must be valid Git revisions")
    result = subprocess.run(
        ["git", "diff", "--name-status", "-z", "-M", base, head, "--"],
        cwd=root, capture_output=True, check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GateConfigError(f"unable to diff base/head: {detail[:300]}")
    return _changed_files_from_name_status(result.stdout)


def changed_files_from_staged(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "diff", "--cached", "--name-status", "-z", "-M", "--"],
        cwd=root, capture_output=True, check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.decode("utf-8", errors="replace").strip()
        raise GateConfigError(f"unable to inspect staged changes: {detail[:300]}")
    return _changed_files_from_name_status(result.stdout)


def _matches(relative: str, patterns: list[str]) -> bool:
    return any(fnmatchcase(relative, pattern) for pattern in patterns)


def load_mapping(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise GateConfigError(f"mapping not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise GateConfigError("invalid mapping JSON") from exc
    if not isinstance(payload, dict) or payload.get("version") != 2:
        raise GateConfigError("unsupported mapping version")
    rules = payload.get("rules")
    if not isinstance(rules, list):
        raise GateConfigError("mapping rules must be an array")
    for rule in rules:
        if not isinstance(rule, dict) or not isinstance(rule.get("id"), str):
            raise GateConfigError("each mapping rule requires an id")
        for field in ("globs", "groups"):
            if not isinstance(rule.get(field), list) or not all(isinstance(item, str) for item in rule[field]):
                raise GateConfigError(f"mapping rule {rule['id']} has invalid {field}")
        unknown = sorted(set(rule["groups"]) - KNOWN_GROUPS)
        if unknown:
            raise GateConfigError(f"mapping rule {rule['id']} uses unknown group: {', '.join(unknown)}")
    for field in ("docs_only_globs", "full_globs", "fail_closed_globs", "ui_globs", "e2e_all_globs"):
        values = payload.get(field, [])
        if not isinstance(values, list) or not all(isinstance(item, str) for item in values):
            raise GateConfigError(f"mapping {field} must be an array of globs")
    e2e_rules = payload.get("e2e_rules", [])
    if not isinstance(e2e_rules, list):
        raise GateConfigError("mapping e2e_rules must be an array")
    for rule in e2e_rules:
        if not isinstance(rule, dict) or set(rule) != {"id", "globs", "specs"}:
            raise GateConfigError("each E2E mapping rule requires id, globs and specs")
        if (
            not isinstance(rule["id"], str)
            or not all(isinstance(rule[field], list) for field in ("globs", "specs"))
            or not all(isinstance(value, str) for field in ("globs", "specs") for value in rule[field])
        ):
            raise GateConfigError(f"E2E mapping rule {rule.get('id', '?')} is invalid")
    group_tests = payload.get("group_tests", {})
    if not isinstance(group_tests, dict) or set(group_tests) - KNOWN_GROUPS:
        raise GateConfigError("mapping group_tests contains an unknown group")
    for group, tests in group_tests.items():
        if not isinstance(tests, list) or not all(isinstance(test, str) for test in tests):
            raise GateConfigError(f"mapping group_tests {group} must be an array of test paths")
        if len(tests) != len(set(tests)):
            raise GateConfigError(f"mapping group_tests {group} contains duplicate test paths")
    return payload


def code_size_policy_domains(root: Path, base: str) -> set[str]:
    result = subprocess.run(
        ["git", "show", f"{base}:tests/code_size_policy.json"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    try:
        before = json.loads(result.stdout) if result.returncode == 0 else None
        after = json.loads((root / "tests/code_size_policy.json").read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError):
        return {"full"}
    if not isinstance(before, dict) or not isinstance(after, dict):
        return {"full"}
    before_frozen = before.get("frozen_files")
    after_frozen = after.get("frozen_files")
    before_shape = {key: value for key, value in before.items() if key != "frozen_files"}
    after_shape = {key: value for key, value in after.items() if key != "frozen_files"}
    if before_shape != after_shape or not isinstance(before_frozen, list) or not isinstance(after_frozen, list):
        return {"full"}
    changed = set(before_frozen) ^ set(after_frozen)
    domains = {"frontend" if path.startswith("frontend/") else "backend" for path in changed}
    return domains or {"control"}


def build_plan(
    changed_files: list[str],
    mapping: dict[str, Any],
    *,
    code_size_domains: set[str] | None = None,
) -> dict[str, Any]:
    changed = sorted(dict.fromkeys(changed_files))
    groups = {"control"}
    reasons: list[str] = []
    python_targets: list[str] = []
    frontend_related: list[str] = []
    e2e_targets: set[str] = set()
    mapping_miss = False
    e2e_full = False
    for relative in changed:
        if not _is_safe_relative_path(relative):
            raise GateConfigError(f"unsafe changed path: {relative!r}")
        rules = [rule for rule in mapping["rules"] if _matches(relative, rule["globs"])]
        if relative == "tests/code_size_policy.json" and code_size_domains:
            if "full" in code_size_domains:
                groups.add("full")
            if "backend" in code_size_domains:
                groups.add("code_size_backend")
            if "frontend" in code_size_domains:
                groups.add("code_size_frontend")
        if _matches(relative, mapping.get("docs_only_globs", [])) and not rules:
            reasons.append(f"{relative}: documentation/control formatting only")
            continue
        if _matches(relative, mapping.get("full_globs", [])):
            groups.add("full")
            reasons.append(f"{relative}: dependency/build/global configuration requires full gate")
        elif relative.startswith("tests/") and relative.endswith(".py"):
            groups.add("python_test_files")
            python_targets.append(relative)
            reasons.append(f"{relative}: changed Python test runs itself")
        else:
            for rule in rules:
                groups.update(rule["groups"])
                reasons.append(f"{relative}: {rule['id']}")
            if not rules and _matches(relative, mapping.get("fail_closed_globs", [])):
                groups.add("full")
                mapping_miss = True
                reasons.append(f"{relative}: unmapped executable path; fail-closed to full")
            elif not rules:
                reasons.append(f"{relative}: formatting/control validation")
        if relative.startswith("frontend/src/") and any(
            "frontend_related" in rule["groups"] for rule in rules
        ):
            frontend_related.append(relative.removeprefix("frontend/"))
        if _matches(relative, mapping.get("e2e_all_globs", [])):
            e2e_full = True
        matched_e2e = False
        for rule in mapping.get("e2e_rules", []):
            if _matches(relative, rule["globs"]):
                e2e_targets.update(rule["specs"])
                matched_e2e = True
        if _matches(relative, mapping.get("ui_globs", [])) and not matched_e2e:
            e2e_full = True
    if "full" in groups:
        groups = {"control", "full"}
    elif "frontend_full" in groups:
        groups -= {"frontend_checks", "frontend_related"}
    ui_impacted = any(_matches(path, mapping.get("ui_globs", [])) for path in changed)
    if e2e_full:
        e2e_targets.clear()
    backend_impacted = "full" in groups or "code_size_backend" in groups or any(
        group.startswith("python_") for group in groups
    )
    frontend_impacted = "full" in groups or "code_size_frontend" in groups or any(
        group.startswith("frontend_") for group in groups
    )
    return {
        "mode": "targeted", "status": "planned", "changed_files": changed,
        "selected_groups": sorted(groups), "reasons": reasons,
        "counts": {"changed_files": len(changed), "selected_groups": len(groups)},
        "duration": 0.0, "first_failure": None, "log_paths": [],
        "ui_impacted": ui_impacted, "backend_impacted": backend_impacted,
        "frontend_impacted": frontend_impacted, "mapping_miss": mapping_miss,
        "python_test_targets": sorted(set(python_targets)),
        "frontend_related_files": sorted(set(frontend_related)),
        "e2e_full": e2e_full, "e2e_targets": sorted(e2e_targets),
    }
