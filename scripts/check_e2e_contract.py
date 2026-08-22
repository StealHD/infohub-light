#!/usr/bin/env python3
"""Reject a few Playwright patterns that repeatedly waste the Linux gate."""

from __future__ import annotations

import argparse
import re
import sys
from pathlib import Path, PurePosixPath


PORT_PATTERN = re.compile(r"https?://(?:127\.0\.0\.1|localhost):(?:4173|4174)\b")
COUNT_PATTERN = re.compile(r"\.count\(\)")
TRANSIENT_PATTERN = re.compile(r"aria-hidden|\binert\b")


def _safe_relative(value: str) -> PurePosixPath:
    relative = PurePosixPath(value)
    if relative.is_absolute() or ".." in relative.parts:
        raise ValueError(f"unsafe E2E path: {value}")
    if relative.suffix != ".ts" or not str(relative).startswith("frontend/e2e/"):
        raise ValueError(f"E2E contract input must be a frontend/e2e TypeScript file: {value}")
    return relative


def _safe_file(root: Path, value: str) -> Path:
    relative = _safe_relative(value)
    path = root / relative
    if not path.is_file():
        raise ValueError(f"E2E contract input must be an existing frontend/e2e TypeScript file: {value}")
    return path


def _files(root: Path, changed: list[str]) -> list[Path]:
    selected = [value for value in changed if value.startswith("frontend/e2e/") and value.endswith(".ts")]
    if selected:
        return sorted({_safe_file(root, value) for value in selected if (root / _safe_relative(value)).is_file()})
    return sorted((root / "frontend" / "e2e").glob("*.ts"))


def check_file(root: Path, path: Path) -> list[str]:
    relative = path.relative_to(root).as_posix()
    text = path.read_text(encoding="utf-8")
    errors: list[str] = []
    for match in PORT_PATTERN.finditer(text):
        line = text.count("\n", 0, match.start()) + 1
        errors.append(f"{relative}:{line}: preview URL must use Playwright baseURL")
    for match in COUNT_PATTERN.finditer(text):
        nearby = text[match.end():match.end() + 1200]
        if TRANSIENT_PATTERN.search(nearby):
            line = text.count("\n", 0, match.start()) + 1
            errors.append(
                f"{relative}:{line}: do not count a locator before asserting transient aria-hidden/inert"
            )
    if "toHaveScreenshot" in text:
        requirements = {
            "reduced motion": "reducedMotion: 'reduce'" in text or 'reducedMotion: "reduce"' in text,
            "fixed theme/session state": "localStorage.setItem" in text or "sessionStorage.setItem" in text,
            "disabled animations": "animations: 'disabled'" in text or 'animations: "disabled"' in text,
        }
        for label, present in requirements.items():
            if not present:
                errors.append(f"{relative}: visual tests require {label}")
    return errors


def main(argv: list[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--root", type=Path, default=Path(__file__).resolve().parents[1])
    parser.add_argument("--changed-file", action="append", default=[])
    args = parser.parse_args(argv)
    root = args.root.resolve()
    try:
        errors = [error for path in _files(root, args.changed_file) for error in check_file(root, path)]
    except (OSError, ValueError) as exc:
        print(f"E2E contract error: {exc}", file=sys.stderr)
        return 2
    if errors:
        print("\n".join(errors), file=sys.stderr)
        return 1
    print(f"E2E contract passed ({len(_files(root, args.changed_file))} files)")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
