#!/usr/bin/env python3
"""Validate bounded, directory-based Markdown control sources."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path


MAX_ACTIVE_MARKDOWN = 64 * 1024
MAX_CONTRACT_MODULE = 48 * 1024
MAX_INDEX = 24 * 1024
MAX_ROOT_CONTROL = 32 * 1024
MAX_PLAN = 12 * 1024
ARCHIVE_PREFIX = "archive/"
EXCLUDED_PARTS = {".git", ".venv", "node_modules", "build", "dist", "__pycache__"}
AUTHORITY_INDEXES = (
    "docs/contracts/api/README.md",
    "docs/contracts/architecture/README.md",
    "docs/contracts/ui/README.md",
    "docs/decisions/README.md",
)
LEGACY_AUTHORITIES = tuple(
    f"{name}_CONTRACT.md" for name in ("API", "ARCHITECTURE", "UI")
) + ("DECISION_" + "LOG.md", "CONTEXT_" + "READ_RULES.md")
DECISION_INDEX_ROW = re.compile(
    r"^\| (D\d{3}) \| .*? \| .*? \| \[查看\]"
    r"\(records/(D\d{3})-(D\d{3})\.md#(d\d{3})\) \|$",
    re.MULTILINE,
)
DECISION_HEADING = re.compile(r"^### (D\d{3})\b", re.MULTILINE)


def _relative(root: Path, path: Path) -> str:
    return path.relative_to(root).as_posix()


def _markdown_paths(root: Path) -> list[Path]:
    return sorted(
        path
        for path in root.rglob("*.md")
        if path.is_file() and not (set(path.relative_to(root).parts) & EXCLUDED_PARTS)
    )


def _check_size(path: Path, limit: int, label: str, errors: list[str]) -> None:
    size = path.stat().st_size
    if size > limit:
        errors.append(f"{path.as_posix()}: {label} exceeds {limit} bytes ({size})")


def _validate_decisions(root: Path, errors: list[str]) -> None:
    index = root / "docs/decisions/README.md"
    records_dir = root / "docs/decisions/records"
    if not index.is_file() or not records_dir.is_dir():
        return

    records: list[tuple[int, str, Path]] = []
    for path in sorted(records_dir.glob("D*-D*.md")):
        numbers = [int(value[1:]) for value in DECISION_HEADING.findall(path.read_text(encoding="utf-8"))]
        if numbers != sorted(numbers):
            errors.append(f"{_relative(root, path)}: decision IDs are not in numeric order")
        for number in numbers:
            records.append((number, f"D{number:03d}", path))

    numbers = [number for number, _, _ in records]
    if len(numbers) != len(set(numbers)):
        errors.append("docs/decisions/records: decision IDs must be unique")
    if numbers != sorted(numbers):
        errors.append("docs/decisions/records: decision IDs must be globally ordered")

    index_rows = DECISION_INDEX_ROW.findall(index.read_text(encoding="utf-8"))
    indexed = [row[0] for row in index_rows]
    actual = [identifier for _, identifier, _ in records]
    if len(indexed) != len(set(indexed)):
        errors.append("docs/decisions/README.md: decision IDs must be unique")
    if indexed != actual:
        errors.append("docs/decisions/README.md: index must exactly match record IDs and order")
    for identifier, bucket_start, bucket_end, anchor in index_rows:
        number = int(identifier[1:])
        if anchor != identifier.lower() or not (int(bucket_start[1:]) <= number <= int(bucket_end[1:])):
            errors.append(f"docs/decisions/README.md: invalid record target for {identifier}")


def _validate_authorities(root: Path, errors: list[str]) -> None:
    for relative in AUTHORITY_INDEXES:
        if not (root / relative).is_file():
            errors.append(f"missing authority index: {relative}")
    agents = root / "AGENTS.md"
    if not agents.is_file():
        errors.append("missing AGENTS.md")
        return
    text = agents.read_text(encoding="utf-8")
    for required in (
        "docs/contracts/api/",
        "docs/contracts/architecture/",
        "docs/contracts/ui/",
        "docs/decisions/",
        "任务读取路由",
    ):
        if required not in text:
            errors.append(f"AGENTS.md: missing authority routing for {required}")


def _validate_legacy_references(root: Path, errors: list[str]) -> None:
    for path in root.rglob("*"):
        if not path.is_file() or set(path.relative_to(root).parts) & EXCLUDED_PARTS:
            continue
        relative = _relative(root, path)
        if relative.startswith(ARCHIVE_PREFIX) or relative.startswith("docs/decisions/records/"):
            continue
        if path.suffix.lower() not in {".md", ".py", ".json", ".ts", ".tsx"}:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        for legacy in LEGACY_AUTHORITIES:
            if legacy in text:
                errors.append(f"{relative}: obsolete authority reference {legacy}")


def validate(root: Path) -> list[str]:
    root = root.resolve()
    errors: list[str] = []
    for path in _markdown_paths(root):
        relative = _relative(root, path)
        if not relative.startswith(ARCHIVE_PREFIX):
            _check_size(path, MAX_ACTIVE_MARKDOWN, "active Markdown", errors)
        if relative.startswith("docs/contracts/"):
            _check_size(path, MAX_CONTRACT_MODULE, "contract module", errors)
        if relative in AUTHORITY_INDEXES:
            _check_size(path, MAX_INDEX, "contract or decision index", errors)
    for relative in ("AGENTS.md", "PLAN.md", "WORKLOG.md"):
        path = root / relative
        if path.is_file():
            _check_size(path, MAX_ROOT_CONTROL, "root control", errors)
    plan = root / "PLAN.md"
    if plan.is_file():
        _check_size(plan, MAX_PLAN, "PLAN", errors)
    _validate_authorities(root, errors)
    _validate_decisions(root, errors)
    _validate_legacy_references(root, errors)
    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    args = parser.parse_args()
    errors = validate(args.root)
    if errors:
        print("MARKDOWN_CONTROL_FAIL")
        print("\n".join(f"- {error}" for error in errors))
        return 1
    print("MARKDOWN_CONTROL_PASS")
    return 0


if __name__ == "__main__":
    sys.exit(main())
