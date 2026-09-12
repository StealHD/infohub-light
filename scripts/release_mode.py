"""Explicit release routing; a lightweight green check is not full test evidence."""
from __future__ import annotations

import argparse
import os
import re
import subprocess
import sys
import tomllib
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
if str(ROOT) not in sys.path:
    sys.path.insert(0, str(ROOT))
from scripts.test_gate_changes import GateConfigError


def git(root: Path, *args: str) -> str:
    return subprocess.run(["git", *args], cwd=root, check=True, capture_output=True,
                          text=True, timeout=30).stdout.strip()


def parse_mode(message: str) -> str:
    trailers = subprocess.run(["git", "interpret-trailers", "--parse"], input=message,
                              text=True, capture_output=True, check=True, timeout=10).stdout
    values = [line.split(":", 1)[1].strip() for line in trailers.splitlines()
              if line.lower().startswith("release-mode:")]
    mentions = re.findall(r"(?im)^Release-Mode\s*:", message)
    if len(values) != len(mentions) or len(values) > 1 or (values and values[0] not in {"fast", "standard"}):
        raise GateConfigError("Release-Mode must be one final Git trailer: standard or fast")
    return values[0] if values else "standard"


def commit_mode(root: Path, revision: str = "HEAD") -> str:
    if revision.startswith("-"):
        raise GateConfigError("invalid release revision")
    return parse_mode(git(root, "show", "-s", "--format=%B", f"{revision}^{{commit}}"))


def version(root: Path) -> str:
    project = tomllib.loads((root / "pyproject.toml").read_text())
    lock = tomllib.loads((root / "uv.lock").read_text())
    current = project["project"]["version"]
    roots = [p for p in lock["package"] if p.get("name") == project["project"]["name"]
             and p.get("source") == {"editable": "."}]
    if not re.fullmatch(r"[0-9]+\.[0-9]+\.[0-9]+(?:[-+][A-Za-z0-9.-]+)?", current):
        raise GateConfigError("invalid release version")
    if len(roots) != 1 or roots[0].get("version") != current:
        raise GateConfigError("project and editable lock versions disagree")
    return current


def tag_mode(root: Path, tag: str) -> str:
    if tag != "v" + version(root):
        raise GateConfigError("tag and project version disagree")
    ref = f"refs/tags/{tag}"
    if git(root, "cat-file", "-t", ref) != "tag":
        raise GateConfigError("release tag must be annotated")
    message = git(root, "cat-file", "tag", ref).split("\n\n", 1)[1]
    mode = parse_mode(message)
    if mode != commit_mode(root, ref) or git(root, "rev-parse", f"{ref}^{{commit}}") != git(root, "rev-parse", "HEAD"):
        raise GateConfigError("tag mode or revision does not match release commit")
    return mode


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--revision", default="HEAD")
    parser.add_argument("--require", choices=("standard", "fast"))
    parser.add_argument("--tag")
    parser.add_argument("--check-version", action="store_true")
    parser.add_argument("--github-output", action="store_true")
    args = parser.parse_args()
    try:
        mode = tag_mode(ROOT, args.tag) if args.tag else commit_mode(ROOT, args.revision)
        if args.check_version:
            version(ROOT)
        if args.require and args.require != mode:
            raise GateConfigError(f"this entry requires Release-Mode: {args.require}; commit is {mode}")
        if args.github_output:
            with open(os.environ["GITHUB_OUTPUT"], "a") as stream:
                stream.write(f"release_mode={mode}\n")
        print(mode)
        return 0
    except (GateConfigError, OSError, ValueError, KeyError, subprocess.SubprocessError) as exc:
        print(f"release mode: {exc}", file=sys.stderr)
        return 2


if __name__ == "__main__":
    raise SystemExit(main())
