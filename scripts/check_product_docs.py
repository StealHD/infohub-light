#!/usr/bin/env python3
"""Require product-code merges to review both user-facing documentation sources."""

from __future__ import annotations

import argparse
import json
import subprocess
from dataclasses import dataclass
from pathlib import Path, PurePosixPath


DOCUMENTATION_SOURCES = {
    "frontend/src/features/changelog/changelogEntries.ts",
    "frontend/src/features/manual/manualContent.ts",
}

NON_PRODUCT_SCRIPT_PATHS = {
    "scripts/check_product_docs.py",
    "scripts/test_gate.py",
}

PRODUCT_ROOT_FILES = {
    "Dockerfile",
    "docker-compose.light.yml",
    "docker-compose.test-gate.yml",
    "docker-compose.yml",
    "frontend/package-lock.json",
    "frontend/package.json",
    "pyproject.toml",
    "uv.lock",
}


class ProductDocumentationError(RuntimeError):
    """Raised when a product-code change omits a required documentation review."""


@dataclass(frozen=True)
class ChangedPath:
    status: str
    path: str
    previous_path: str | None = None

    @property
    def all_paths(self) -> tuple[str, ...]:
        if self.previous_path:
            return (self.previous_path, self.path)
        return (self.path,)


def _safe_relative_path(value: str) -> str:
    normalized = value.replace("\\", "/")
    path = PurePosixPath(normalized)
    if path.is_absolute() or not normalized or ".." in path.parts:
        raise ProductDocumentationError(f"unsafe changed path: {value!r}")
    return path.as_posix()


def _is_test_source(path: str) -> bool:
    name = PurePosixPath(path).name
    return (
        ".test." in name
        or ".spec." in name
        or path.startswith("frontend/src/test/")
        or path.startswith("tests/")
    )


def is_product_code(path: str) -> bool:
    path = _safe_relative_path(path)
    if path in DOCUMENTATION_SOURCES or _is_test_source(path):
        return False
    if path.startswith("frontend/src/"):
        return PurePosixPath(path).suffix in {".css", ".ts", ".tsx"}
    if path.startswith("src/"):
        return PurePosixPath(path).suffix == ".py"
    if path.startswith("scripts/"):
        return path not in NON_PRODUCT_SCRIPT_PATHS and PurePosixPath(path).suffix in {".py", ".sh"}
    if path.startswith("deploy/"):
        return PurePosixPath(path).suffix not in {".md", ".txt"}
    return path in PRODUCT_ROOT_FILES


def documentation_check(changes: list[ChangedPath]) -> dict[str, object]:
    product_paths = sorted(
        {
            path
            for change in changes
            for path in change.all_paths
            if is_product_code(path)
        }
    )
    updated_paths = {
        change.path
        for change in changes
        if change.status != "D"
    }
    missing = sorted(DOCUMENTATION_SOURCES - updated_paths) if product_paths else []
    return {
        "required": bool(product_paths),
        "product_paths": product_paths,
        "documentation_sources": sorted(DOCUMENTATION_SOURCES & updated_paths),
        "missing": missing,
    }


def changed_paths_from_git(root: Path, base: str, head: str) -> list[ChangedPath]:
    command = [
        "git",
        "-C",
        str(root),
        "diff",
        "--name-status",
        "--find-renames",
        base,
        head,
        "--",
    ]
    completed = subprocess.run(command, check=True, capture_output=True, text=True)
    changes: list[ChangedPath] = []
    for line in completed.stdout.splitlines():
        if not line.strip():
            continue
        fields = line.split("\t")
        raw_status = fields[0]
        status = raw_status[:1]
        if status in {"R", "C"}:
            if len(fields) != 3:
                raise ProductDocumentationError(f"unexpected Git rename record: {line!r}")
            changes.append(
                ChangedPath(
                    status=status,
                    previous_path=_safe_relative_path(fields[1]),
                    path=_safe_relative_path(fields[2]),
                )
            )
            continue
        if len(fields) != 2 or status not in {"A", "D", "M", "T"}:
            raise ProductDocumentationError(f"unexpected Git change record: {line!r}")
        changes.append(ChangedPath(status=status, path=_safe_relative_path(fields[1])))
    return changes


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="Verify that product-code changes review the operation manual and changelog.",
    )
    parser.add_argument("--base", required=True, help="Base Git revision")
    parser.add_argument("--head", required=True, help="Head Git revision")
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    return parser


def main() -> int:
    args = _parser().parse_args()
    root = args.root.resolve()
    try:
        changes = changed_paths_from_git(root, args.base, args.head)
        result = documentation_check(changes)
        if result["missing"]:
            missing = ", ".join(result["missing"])
            raise ProductDocumentationError(
                "product code changed without reviewing both documentation sources; "
                f"missing: {missing}"
            )
        absent = [
            path
            for path in result["documentation_sources"]
            if not (root / path).is_file()
        ]
        if absent:
            raise ProductDocumentationError(
                f"documentation source is not present at HEAD: {', '.join(absent)}"
            )
    except (ProductDocumentationError, subprocess.CalledProcessError) as error:
        print(f"Product documentation gate failed: {error}")
        return 1

    print(
        json.dumps(
            {
                "status": "passed",
                "required": result["required"],
                "product_change_count": len(result["product_paths"]),
                "documentation_sources": result["documentation_sources"],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
