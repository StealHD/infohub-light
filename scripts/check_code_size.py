#!/usr/bin/env python3
"""Enforce project-specific code-size debt ratchets with compact output."""

from __future__ import annotations

import argparse
import ast
import json
import subprocess
import sys
from dataclasses import asdict, dataclass
from pathlib import Path, PurePosixPath
from typing import Any

_PROJECT_ROOT = Path(__file__).resolve().parents[1]
if str(_PROJECT_ROOT) not in sys.path:
    sys.path.insert(0, str(_PROJECT_ROOT))

from scripts.code_size_policy import (
    POLICY_RELATIVE,
    PolicyError,
    compare_policy,
    debt_maps,
    load_policy,
)

SOURCE_SUFFIXES = {".cjs", ".css", ".js", ".jsx", ".mjs", ".py", ".sh", ".ts", ".tsx"}
TYPESCRIPT_SUFFIXES = {".cjs", ".js", ".jsx", ".mjs", ".ts", ".tsx"}


@dataclass(frozen=True)
class FileMetric:
    path: str
    category: str
    lines: int


@dataclass(frozen=True)
class CallableMetric:
    path: str
    symbol: str
    category: str
    lines: int
    complexity: int
    max_nesting: int

    @property
    def key(self) -> tuple[str, str, str]:
        return self.path, self.symbol, self.category


def _git_paths(root: Path) -> list[str]:
    result = subprocess.run(
        ["git", "ls-files", "-z", "--cached", "--others", "--exclude-standard"],
        cwd=root,
        capture_output=True,
        check=False,
    )
    if result.returncode != 0:
        raise PolicyError("code-size root is not a readable Git worktree")
    return sorted(
        value
        for value in result.stdout.decode("utf-8", errors="surrogateescape").split("\0")
        if value
    )


def _is_excluded(relative: str, policy: dict[str, Any]) -> bool:
    exclusions = policy["exclusions"]
    return relative in exclusions["paths"] or any(
        relative.startswith(prefix) for prefix in exclusions["prefixes"]
    )


def _in_scope(relative: str, scope: str) -> bool:
    is_frontend = relative.startswith("frontend/")
    return scope == "all" or (scope == "frontend" and is_frontend) or (
        scope == "backend" and not is_frontend
    )


def _file_category(relative: str) -> str:
    name = PurePosixPath(relative).name
    if (
        relative.startswith("tests/")
        or relative.startswith("frontend/e2e/")
        or ".test." in name
        or ".spec." in name
    ):
        return "test"
    if relative.startswith("scripts/migrate_") or "/migrations/" in relative:
        return "migration"
    return "production"


def _physical_lines(path: Path) -> int:
    return len(path.read_text(encoding="utf-8", errors="surrogateescape").splitlines())


class _PythonShape(ast.NodeVisitor):
    def __init__(self, root: ast.AST) -> None:
        self.root = root
        self.complexity = 1
        self.depth = 0
        self.max_nesting = 0

    def _control(self, node: ast.AST, extra_complexity: int = 1) -> None:
        self.complexity += extra_complexity
        self.depth += 1
        self.max_nesting = max(self.max_nesting, self.depth)
        self.generic_visit(node)
        self.depth -= 1

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        if node is self.root:
            self.generic_visit(node)

    def visit_If(self, node: ast.If) -> None:
        self._control(node)

    def visit_For(self, node: ast.For) -> None:
        self._control(node)

    def visit_AsyncFor(self, node: ast.AsyncFor) -> None:
        self._control(node)

    def visit_While(self, node: ast.While) -> None:
        self._control(node)

    def visit_Try(self, node: ast.Try) -> None:
        self._control(node, max(1, len(node.handlers)))

    def visit_TryStar(self, node: ast.TryStar) -> None:
        self._control(node, max(1, len(node.handlers)))

    def visit_Match(self, node: ast.Match) -> None:
        self._control(node, max(1, len(node.cases)))

    def visit_IfExp(self, node: ast.IfExp) -> None:
        self._control(node)

    def visit_BoolOp(self, node: ast.BoolOp) -> None:
        self.complexity += max(0, len(node.values) - 1)
        self.generic_visit(node)

    def visit_comprehension(self, node: ast.comprehension) -> None:
        self.complexity += 1 + len(node.ifs)
        self.generic_visit(node)


class _PythonCallables(ast.NodeVisitor):
    def __init__(self, relative: str, category: str, entrypoints: set[tuple[str, str]]) -> None:
        self.relative = relative
        self.category = category
        self.entrypoints = entrypoints
        self.parents: list[str] = []
        self.metrics: list[CallableMetric] = []

    def _visit_callable(self, node: ast.FunctionDef | ast.AsyncFunctionDef) -> None:
        symbol = ".".join([*self.parents, node.name])
        start = min([node.lineno, *(item.lineno for item in node.decorator_list)])
        shape = _PythonShape(node)
        shape.visit(node)
        category = "entrypoint" if (self.relative, symbol) in self.entrypoints else self.category
        self.metrics.append(
            CallableMetric(
                path=self.relative,
                symbol=symbol,
                category=category,
                lines=(node.end_lineno or node.lineno) - start + 1,
                complexity=shape.complexity,
                max_nesting=shape.max_nesting,
            )
        )
        self.parents.append(node.name)
        self.generic_visit(node)
        self.parents.pop()

    def visit_FunctionDef(self, node: ast.FunctionDef) -> None:
        self._visit_callable(node)

    def visit_AsyncFunctionDef(self, node: ast.AsyncFunctionDef) -> None:
        self._visit_callable(node)

    def visit_ClassDef(self, node: ast.ClassDef) -> None:
        self.parents.append(node.name)
        self.generic_visit(node)
        self.parents.pop()


def _python_callables(
    root: Path,
    relative: str,
    category: str,
    entrypoints: set[tuple[str, str]],
) -> list[CallableMetric]:
    try:
        tree = ast.parse((root / relative).read_text(encoding="utf-8"), filename=relative)
    except (OSError, SyntaxError, UnicodeError) as exc:
        raise PolicyError(f"unable to parse {relative}: {exc}") from exc
    visitor = _PythonCallables(relative, category, entrypoints)
    visitor.visit(tree)
    return visitor.metrics


def _typescript_callables(
    root: Path,
    relatives: list[str],
    categories: dict[str, str],
    entrypoints: set[tuple[str, str]],
) -> list[CallableMetric]:
    if not relatives:
        return []
    result = subprocess.run(
        ["node", "scripts/code_size_ts_ast.mjs", str(root), *relatives],
        cwd=root,
        capture_output=True,
        text=True,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr.strip() or result.stdout.strip()
        raise PolicyError(f"TypeScript AST analysis failed: {detail[:500]}")
    try:
        records = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise PolicyError("TypeScript AST analyzer returned invalid JSON") from exc
    metrics: list[CallableMetric] = []
    for record in records:
        relative = record["path"]
        symbol = record["symbol"]
        category = "entrypoint" if (relative, symbol) in entrypoints else categories[relative]
        metrics.append(
            CallableMetric(
                path=relative,
                symbol=symbol,
                category=category,
                lines=int(record["lines"]),
                complexity=int(record["complexity"]),
                max_nesting=int(record["max_nesting"]),
            )
        )
    return metrics


def collect_metrics(
    root: Path,
    policy: dict[str, Any],
    scope: str,
) -> tuple[list[FileMetric], list[CallableMetric]]:
    entrypoints = {(item["path"], item["symbol"]) for item in policy["entrypoints"]}
    files: list[FileMetric] = []
    callables: list[CallableMetric] = []
    typescript_paths: list[str] = []
    categories: dict[str, str] = {}
    for relative in _git_paths(root):
        path = root / relative
        if (
            not _in_scope(relative, scope)
            or _is_excluded(relative, policy)
            or path.suffix.lower() not in SOURCE_SUFFIXES
            or not path.is_file()
        ):
            continue
        category = _file_category(relative)
        categories[relative] = category
        files.append(FileMetric(relative, category, _physical_lines(path)))
        if path.suffix.lower() == ".py":
            callables.extend(_python_callables(root, relative, category, entrypoints))
        elif relative.startswith("frontend/") and path.suffix.lower() in TYPESCRIPT_SUFFIXES:
            typescript_paths.append(relative)
    callables.extend(_typescript_callables(root, typescript_paths, categories, entrypoints))
    return files, callables


def _evaluate_metric(
    label: str,
    lines: int,
    hard: int,
    debt: dict[str, Any] | None,
    errors: list[str],
) -> None:
    if lines > hard and debt is None:
        errors.append(f"{label}: {lines} lines exceeds hard limit {hard} without baseline debt")
        return
    if debt is None:
        return
    maximum = debt["max_lines"]
    if lines <= hard:
        errors.append(f"{label}: now {lines} lines; remove obsolete debt allowance {maximum}")
    elif lines < maximum:
        errors.append(f"{label}: shrank to {lines} lines; lower debt allowance from {maximum}")
    elif lines > maximum:
        errors.append(f"{label}: grew from debt allowance {maximum} to {lines} lines")


def evaluate(
    policy: dict[str, Any],
    files: list[FileMetric],
    callables: list[CallableMetric],
    scope: str,
) -> dict[str, Any]:
    errors: list[str] = []
    soft: list[dict[str, Any]] = []
    file_debt, callable_debt = debt_maps(policy)
    seen_files: set[str] = set()
    seen_callables: set[tuple[str, str, str]] = set()
    for metric in files:
        seen_files.add(metric.path)
        limit = policy["limits"]["files"][metric.category]
        _evaluate_metric(metric.path, metric.lines, limit["hard"], file_debt.get(metric.path), errors)
        if metric.lines > limit["soft"]:
            soft.append({"kind": "file", **asdict(metric), "soft": limit["soft"]})
    for metric in callables:
        seen_callables.add(metric.key)
        limit = policy["limits"]["callables"][metric.category]
        label = f"{metric.path}::{metric.symbol}::{metric.category}"
        _evaluate_metric(label, metric.lines, limit["hard"], callable_debt.get(metric.key), errors)
        if metric.lines > limit["soft"]:
            soft.append({"kind": "callable", **asdict(metric), "soft": limit["soft"]})
    for path in sorted(file_debt):
        if _in_scope(path, scope) and path not in seen_files:
            errors.append(f"{path}: debt entry is stale because the file is absent or excluded")
    for key in sorted(callable_debt):
        if _in_scope(key[0], scope) and key not in seen_callables:
            errors.append(f"{key[0]}::{key[1]}::{key[2]}: stale callable debt entry")
    complexity_target = policy["limits"]["complexity"]["target"]
    nesting_target = policy["limits"]["nesting"]["target"]
    complex_metrics = [metric for metric in callables if metric.complexity > complexity_target]
    nested_metrics = [metric for metric in callables if metric.max_nesting > nesting_target]
    soft.sort(key=lambda item: (-item["lines"], item["path"], item.get("symbol", "")))
    return {
        "status": "failed" if errors else "passed",
        "scope": scope,
        "counts": {
            "files": len(files),
            "callables": len(callables),
            "soft_violations": len(soft),
            "complexity_reports": len(complex_metrics),
            "nesting_reports": len(nested_metrics),
            "errors": len(errors),
        },
        "errors": errors[:20],
        "soft_top": soft[:10],
        "complexity_top": [
            asdict(metric)
            for metric in sorted(complex_metrics, key=lambda item: -item.complexity)[:10]
        ],
        "nesting_top": [
            asdict(metric)
            for metric in sorted(nested_metrics, key=lambda item: -item.max_nesting)[:10]
        ],
    }


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--policy", type=Path)
    parser.add_argument("--scope", choices=("policy", "backend", "frontend", "all"), default="all")
    parser.add_argument("--compare-base")
    return parser


def main(argv: list[str] | None = None) -> int:
    args = _parser().parse_args(argv)
    root = args.root.resolve()
    policy_path = args.policy or root / POLICY_RELATIVE
    try:
        policy = load_policy(policy_path)
        comparison_errors = compare_policy(root, policy, args.compare_base) if args.compare_base else []
        if args.scope == "policy":
            result = {
                "status": "failed" if comparison_errors else "passed",
                "scope": "policy",
                "counts": {"errors": len(comparison_errors)},
                "errors": comparison_errors[:20],
            }
        else:
            files, callables = collect_metrics(root, policy, args.scope)
            result = evaluate(policy, files, callables, args.scope)
            if comparison_errors:
                result["status"] = "failed"
                result["errors"] = [*comparison_errors, *result["errors"]][:20]
                result["counts"]["errors"] += len(comparison_errors)
        print(json.dumps(result, ensure_ascii=False, separators=(",", ":")))
        return 0 if result["status"] == "passed" else 1
    except PolicyError as exc:
        print(json.dumps({"status": "error", "error": str(exc)}, separators=(",", ":")), file=sys.stderr)
        return 2


if __name__ == "__main__":
    sys.exit(main())
