"""Syntax checks for changed scripts without importing business dependencies."""
from __future__ import annotations

import argparse
import ast
import subprocess
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.release_mode import git


def check(root: Path, base: str, head: str) -> None:
    try:
        files = git(root, "diff", "--name-only", "--diff-filter=ACMR", "-z", base, head, "--").split("\0")
    except subprocess.SubprocessError:
        files = git(root, "ls-files", "-z", "scripts").split("\0")
    for name in files:
        path = root / name
        if not name.startswith("scripts/") or not path.is_file():
            continue
        if path.suffix == ".py":
            ast.parse(path.read_bytes(), filename=name)
        elif path.suffix == ".sh":
            subprocess.run(["bash", "-n", str(path)], check=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--base", required=True)
    parser.add_argument("--head", default="HEAD")
    args = parser.parse_args()
    check(ROOT, args.base, args.head)
