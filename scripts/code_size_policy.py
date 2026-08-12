"""Validation and immutable-ratchet checks for the code-size policy."""

from __future__ import annotations

import json
import re
import subprocess
from pathlib import Path, PurePosixPath
from typing import Any


POLICY_RELATIVE = "tests/code_size_policy.json"
CALLABLE_CATEGORIES = {"entrypoint", "migration", "production", "test"}
FILE_CATEGORIES = {"migration", "production", "test"}
SHA_PATTERN = re.compile(r"[0-9a-f]{40}")


class PolicyError(RuntimeError):
    """Raised when the size policy or repository inventory is invalid."""


def _read_json(path: Path) -> dict[str, Any]:
    try:
        payload = json.loads(path.read_text(encoding="utf-8"))
    except FileNotFoundError as exc:
        raise PolicyError(f"policy not found: {path}") from exc
    except json.JSONDecodeError as exc:
        raise PolicyError(f"invalid policy JSON: {exc}") from exc
    if not isinstance(payload, dict):
        raise PolicyError("policy must be a JSON object")
    return payload


def _positive_int(value: Any, label: str) -> int:
    if not isinstance(value, int) or isinstance(value, bool) or value <= 0:
        raise PolicyError(f"{label} must be a positive integer")
    return value


def _validate_limits(policy: dict[str, Any]) -> None:
    limits = policy.get("limits")
    if not isinstance(limits, dict):
        raise PolicyError("limits must be an object")
    expected = {"files": FILE_CATEGORIES, "callables": CALLABLE_CATEGORIES}
    for group, categories in expected.items():
        values = limits.get(group)
        if not isinstance(values, dict) or set(values) != categories:
            raise PolicyError(f"limits.{group} must define exactly {sorted(categories)}")
        for category, limit in values.items():
            if not isinstance(limit, dict):
                raise PolicyError(f"limits.{group}.{category} must be an object")
            target = _positive_int(limit.get("target"), f"{group}.{category}.target")
            soft = _positive_int(limit.get("soft"), f"{group}.{category}.soft")
            hard = _positive_int(limit.get("hard"), f"{group}.{category}.hard")
            if not target <= soft <= hard:
                raise PolicyError(f"limits.{group}.{category} must satisfy target <= soft <= hard")
    complexity = limits.get("complexity")
    nesting = limits.get("nesting")
    if not isinstance(complexity, dict) or complexity.get("mode") != "report":
        raise PolicyError("limits.complexity must use report mode during the migration phase")
    _positive_int(complexity.get("target"), "complexity.target")
    _positive_int(complexity.get("future_hard"), "complexity.future_hard")
    if not isinstance(nesting, dict) or nesting.get("mode") != "report":
        raise PolicyError("limits.nesting must use report mode during the migration phase")
    _positive_int(nesting.get("target"), "nesting.target")


def _safe_relative(value: Any, label: str, *, allow_prefix: bool = False) -> str:
    if not isinstance(value, str) or not value:
        raise PolicyError(f"{label} must be a non-empty path")
    normalized = value.rstrip("/") if allow_prefix else value
    path = PurePosixPath(normalized)
    if path.is_absolute() or ".." in path.parts:
        raise PolicyError(f"{label} must be a safe repository-relative path")
    return value


def _validate_debt(policy: dict[str, Any]) -> None:
    debt = policy.get("debt")
    if not isinstance(debt, dict) or set(debt) != {"files", "callables"}:
        raise PolicyError("debt must define files and callables")
    file_keys: set[str] = set()
    for index, entry in enumerate(debt["files"]):
        if not isinstance(entry, dict) or set(entry) != {"path", "category", "max_lines"}:
            raise PolicyError(f"debt.files[{index}] has an invalid shape")
        path = _safe_relative(entry["path"], f"debt.files[{index}].path")
        if entry["category"] not in FILE_CATEGORIES:
            raise PolicyError(f"debt.files[{index}] has an invalid category")
        _positive_int(entry["max_lines"], f"debt.files[{index}].max_lines")
        if path in file_keys:
            raise PolicyError(f"duplicate file debt: {path}")
        file_keys.add(path)
    callable_keys: set[tuple[str, str, str]] = set()
    for index, entry in enumerate(debt["callables"]):
        required = {"path", "symbol", "category", "max_lines"}
        if not isinstance(entry, dict) or set(entry) != required:
            raise PolicyError(f"debt.callables[{index}] has an invalid shape")
        path = _safe_relative(entry["path"], f"debt.callables[{index}].path")
        symbol = entry["symbol"]
        category = entry["category"]
        if not isinstance(symbol, str) or not symbol or category not in CALLABLE_CATEGORIES:
            raise PolicyError(f"debt.callables[{index}] has an invalid symbol or category")
        _positive_int(entry["max_lines"], f"debt.callables[{index}].max_lines")
        key = (path, symbol, category)
        if key in callable_keys:
            raise PolicyError(f"duplicate callable debt: {path}::{symbol}::{category}")
        callable_keys.add(key)


def load_policy(path: Path) -> dict[str, Any]:
    policy = _read_json(path)
    if policy.get("version") != 1:
        raise PolicyError("unsupported code-size policy version")
    if not isinstance(policy.get("baseline_sha"), str) or not SHA_PATTERN.fullmatch(
        policy["baseline_sha"]
    ):
        raise PolicyError("baseline_sha must be a full lowercase Git SHA")
    if policy.get("exceptions") not in (None, []):
        raise PolicyError("code-size exceptions are not permitted")
    _validate_limits(policy)
    exclusions = policy.get("exclusions")
    if not isinstance(exclusions, dict) or set(exclusions) != {"paths", "prefixes"}:
        raise PolicyError("exclusions must define paths and prefixes")
    for index, value in enumerate(exclusions["paths"]):
        _safe_relative(value, f"exclusions.paths[{index}]")
    for index, value in enumerate(exclusions["prefixes"]):
        _safe_relative(value, f"exclusions.prefixes[{index}]", allow_prefix=True)
    entrypoints = policy.get("entrypoints")
    if not isinstance(entrypoints, list):
        raise PolicyError("entrypoints must be an array")
    seen_entrypoints: set[tuple[str, str]] = set()
    for index, entry in enumerate(entrypoints):
        if not isinstance(entry, dict) or set(entry) != {"path", "symbol", "reason"}:
            raise PolicyError(f"entrypoints[{index}] has an invalid shape")
        key = (
            _safe_relative(entry["path"], f"entrypoints[{index}].path"),
            entry["symbol"],
        )
        if not isinstance(key[1], str) or not key[1] or not isinstance(entry["reason"], str):
            raise PolicyError(f"entrypoints[{index}] requires symbol and reason")
        if key in seen_entrypoints:
            raise PolicyError(f"duplicate entrypoint: {key[0]}::{key[1]}")
        seen_entrypoints.add(key)
    _validate_debt(policy)
    return policy


def debt_maps(
    policy: dict[str, Any],
) -> tuple[dict[str, dict[str, Any]], dict[tuple[str, str, str], dict[str, Any]]]:
    files = {item["path"]: item for item in policy["debt"]["files"]}
    callables = {
        (item["path"], item["symbol"], item["category"]): item
        for item in policy["debt"]["callables"]
    }
    return files, callables


def _git_policy(root: Path, revision: str) -> dict[str, Any] | None:
    result = subprocess.run(
        ["git", "show", f"{revision}:{POLICY_RELATIVE}"],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        return None
    try:
        return json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PolicyError("base code-size policy is invalid JSON") from exc


def _git_commit_exists(root: Path, revision: str) -> bool:
    result = subprocess.run(
        ["git", "cat-file", "-e", f"{revision}^{{commit}}"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    return result.returncode == 0


def _git_is_ancestor(root: Path, ancestor: str, descendant: str) -> bool:
    result = subprocess.run(
        ["git", "merge-base", "--is-ancestor", ancestor, descendant],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode == 0:
        return True
    if result.returncode == 1:
        return False
    raise PolicyError("unable to verify code-size policy ancestry")


def _first_branch_policy(root: Path, base: str) -> dict[str, Any] | None:
    result = subprocess.run(
        ["git", "rev-list", "--reverse", f"{base}..HEAD", "--", POLICY_RELATIVE],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        raise PolicyError("unable to inspect code-size policy history")
    if not result.stdout.strip():
        return None
    for revision in result.stdout.splitlines():
        introduced = _git_policy(root, revision)
        if introduced is not None:
            return introduced
    return None


def compare_policy(root: Path, policy: dict[str, Any], base: str) -> list[str]:
    if not base or base.startswith("-"):
        raise PolicyError("compare base must be a valid Git revision")
    previous = _git_policy(root, base)
    if previous is None:
        baseline = policy["baseline_sha"]
        if not _git_commit_exists(root, baseline):
            return [
                "initial policy baseline_sha must be an existing ancestor "
                f"of trusted base {base}"
            ]
        if not _git_is_ancestor(root, baseline, base):
            return [
                "initial policy baseline_sha must equal trusted base "
                f"{base} or be its ancestor"
            ]
        previous = _first_branch_policy(root, baseline)
        if previous is None:
            return []
    errors: list[str] = []
    if policy["baseline_sha"] != previous.get("baseline_sha"):
        errors.append("baseline_sha cannot change")
    if policy["exclusions"] != previous.get("exclusions"):
        errors.append("exclusions cannot change in an ordinary code change")
    if policy["entrypoints"] != previous.get("entrypoints"):
        errors.append("entrypoints cannot change in an ordinary code change")
    for group in ("files", "callables"):
        for category, current in policy["limits"][group].items():
            before = previous["limits"][group][category]
            for name in ("target", "soft", "hard"):
                if current[name] > before[name]:
                    errors.append(f"limits.{group}.{category}.{name} cannot increase")
    for group, names in (
        ("complexity", ("target", "future_hard")),
        ("nesting", ("target",)),
    ):
        current = policy["limits"][group]
        before = previous["limits"][group]
        for name in names:
            if current[name] > before[name]:
                errors.append(f"limits.{group}.{name} cannot increase")
    previous_files, previous_callables = debt_maps(previous)
    current_files, current_callables = debt_maps(policy)
    for path, debt in current_files.items():
        if path not in previous_files:
            errors.append(f"new file debt is forbidden: {path}")
        elif debt["max_lines"] > previous_files[path]["max_lines"]:
            errors.append(f"file debt cannot increase: {path}")
    for key, debt in current_callables.items():
        label = f"{key[0]}::{key[1]}::{key[2]}"
        if key not in previous_callables:
            errors.append(f"new callable debt is forbidden: {label}")
        elif debt["max_lines"] > previous_callables[key]["max_lines"]:
            errors.append(f"callable debt cannot increase: {label}")
    return errors
